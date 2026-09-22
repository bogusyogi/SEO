"""Publish allowlisted, read-only portfolio evidence for a private dashboard."""
from __future__ import annotations
import argparse
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from seo_project import load_site

LANES = ('gsc', 'ga4', 'bing', 'audit', 'backlinks')
SCORES = ('performance', 'accessibility', 'best-practices', 'seo')
MIN_TIME = datetime.min.replace(tzinfo=timezone.utc)
STATUSES = {'ok', 'success', 'partial', 'failed', 'error', 'missing', 'blocked', 'no_data', 'not_testable'}


def _read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def _dict(value):
    return value if isinstance(value, dict) else {}


def _text(value, limit=500):
    return value[:limit] if isinstance(value, str) else ''


def _stamp(value, allow_day=False):
    if not isinstance(value, str):
        return MIN_TIME
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if allow_day and len(value) == 10:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else MIN_TIME
    except ValueError:
        return MIN_TIME


def _num(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _status(env):
    value = _dict(env).get('status')
    return value if value in STATUSES else ('missing' if env is None else 'failed')


def _base(env):
    stamp = _dict(env).get('collected_at')
    return {'status': _status(env), 'collected_at': stamp if _stamp(stamp) != MIN_TIME else None}


def _data(env):
    # Even partial responses retain status, but cannot silently supply complete totals.
    return _dict(_dict(env).get('data')) if _status(env) in {'ok', 'success'} else {}


def _envelopes(root, lane):
    domain = load_site(root).get('domain')
    values = []
    for path in (root / '.seo' / lane).glob('*.json'):
        obj = _read(path)
        if isinstance(obj, dict) and obj.get('lane') == lane and obj.get('site') == domain and _stamp(obj.get('collected_at')) != MIN_TIME:
            values.append(obj)
    return sorted(values, key=lambda obj: _stamp(obj['collected_at']), reverse=True)


def _latest(root, lane):
    values = _envelopes(root, lane)
    return values[0] if values else None


def _date_range(data):
    value = _dict(data.get('date_range'))
    start, end = value.get('start'), value.get('end')
    if _stamp(start, True) != MIN_TIME and _stamp(end, True) != MIN_TIME:
        return {'start': start[:10], 'end': end[:10]}
    return None


def _gsc(env):
    data = _data(env)
    aggregate = _dict(data.get('aggregate', data.get('totals')))
    rows = []
    for row in data.get('rows', []):
        if isinstance(row, dict):
            rows.append({'query': _text(row.get('query')), 'page': _text(row.get('page'), 2048), **{k: _num(row.get(k)) for k in ('clicks', 'impressions', 'ctr', 'position')}})
    rows.sort(key=lambda row: row['impressions'] or 0, reverse=True)
    coverage = _dict(data.get('coverage'))
    allowed = ('row_count', 'returned_rows', 'rows_returned', 'complete', 'complete_within_cap', 'row_limit', 'max_rows', 'cap_reached', 'clicks_coverage_percent', 'impressions_coverage_percent')
    return {**_base(env), 'date_range': _date_range(data), 'metrics': {k: _num(aggregate.get(k)) for k in ('clicks', 'impressions', 'ctr', 'position')}, 'coverage': {k: v for k in allowed if type(v := coverage.get(k)) in (bool, int, float) and (type(v) is bool or _num(v) is not None)}, 'rows': rows[:100], 'history': []}


def _ga4(env, event_arrival='unknown'):
    data = _data(env)
    totals = _dict(data.get('totals'))
    metadata = _dict(data.get('metadata'))
    currency = metadata.get('currency_code')
    daily = [{'date': _text(row.get('date'), 10), 'sessions': _num(row.get('sessions')), 'users': _num(row.get('users'))} for row in data.get('daily_data', []) if isinstance(row, dict)]
    return {**_base(env), 'date_range': _date_range(data), 'metrics': {k: _num(totals.get(k)) for k in ('sessions', 'users', 'key_events', 'revenue')}, 'currency': currency if isinstance(currency, str) and re.fullmatch('[A-Z]{3}', currency) else None, 'event_arrival': event_arrival if event_arrival in {'verified', 'not_yet_verified', 'unknown'} else 'unknown', 'daily': daily[-90:]}


def _bing(env):
    data = _data(env)
    rows = data.get('d', [])
    out = []
    invalid_dates = False
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        value = row.get('Date', row.get('date'))
        try:
            match = re.fullmatch(r'/Date\((-?\d+)(?:[+-]\d{4})?\)/', str(value))
            stamp = datetime.fromtimestamp(int(match[1]) / 1000, timezone.utc) if match else _stamp(value, True)
            if stamp == MIN_TIME:
                invalid_dates = True
                continue
        except (ValueError, OverflowError, OSError):
            invalid_dates = True
            continue
        out.append({'date': stamp.date().isoformat(), 'clicks': _num(row.get('Clicks', row.get('clicks'))), 'impressions': _num(row.get('Impressions', row.get('impressions')))})
    out.sort(key=lambda row: row['date'])
    metrics = {k: sum(row[k] for row in out) if out and all(row[k] is not None for row in out) and not invalid_dates else None for k in ('clicks', 'impressions')}
    status = _base(env)
    if _status(env) == 'ok' and not out:
        status['status'] = 'no_data' if not rows else 'partial'
    elif invalid_dates:
        status['status'] = 'partial'
    return {**status, 'date_range': {'start': out[0]['date'], 'end': out[-1]['date']} if out else None, 'metrics': metrics, 'daily': out[-400:]}


def _simple(env, lane):
    data = _data(env)
    if lane == 'audit':
        issues = []
        severity = _dict(data.get('severity'))
        for name, targets in _dict(data.get('issues')).items():
            if not isinstance(targets, list):
                continue
            level = next((level for level in ('errors', 'warnings', 'info') if name in severity.get(level, [])), 'info')
            issues.append({'name': _text(name), 'severity': level, 'count': len(targets), 'urls': [_text(url, 2048) for url in targets if isinstance(url, str)][:10]})
        complete = _dict(data.get('coverage')).get('complete')
        return {**_base(env), 'crawled': _num(data.get('crawled')), 'complete': complete if type(complete) is bool else None, 'issues': sorted(issues, key=lambda item: ({'errors': 0, 'warnings': 1, 'info': 2}[item['severity']], item['name']))}
    rows = data.get('rows')
    return {**_base(env), 'count': len(rows) if isinstance(rows, list) else None, 'note': 'Configured URL samples in Bing; not a domain or web-wide backlink census.'}


def _crux_status(obj):
    crux = _dict(obj.get('crux'))
    error = str(crux.get('error') or '').lower()
    if error:
        return 'no_data' if any(term in error for term in ('no crux history', 'no crux data', 'insufficient chrome traffic', 'insufficient traffic volume', 'not eligible')) else 'failed'
    status = obj.get('crux_status') or crux.get('status')
    if status in {'no_data', 'failed', 'error', 'missing'}:
        return status
    if status in {'data', 'success', 'ok'} or crux.get('metrics') or crux.get('record'):
        return 'data'
    return 'unknown' if crux else 'missing'


def _performance(reports, domain):
    empty = {'status': 'missing', 'collected_at': None, 'scores': {k: None for k in SCORES}, 'crux_status': 'unknown'}
    candidates = []
    for pattern in ('performance-baseline-*', 'performance-weekly-*'):
        for folder in reports.glob(pattern):
            if not folder.is_dir():
                continue
            for path in folder.glob('*.json'):
                if path.name.endswith('.psi.json'):
                    continue
                obj = _read(path)
                if isinstance(obj, dict) and obj.get('site') == domain and _stamp(obj.get('captured_at'), True) != MIN_TIME:
                    candidates.append((_stamp(obj['captured_at'], True), path, obj))
    if not candidates:
        return empty
    stamp, path, obj = max(candidates, key=lambda candidate: (candidate[0], str(candidate[1])))
    sidecar = _dict(_read(path.with_suffix('.psi.json')))
    psi = _dict(sidecar.get('psi', obj.get('psi')))
    psi = _dict(psi.get('mobile', psi))
    scores = _dict(psi.get('lighthouse_scores', psi.get('scores')))
    failed = bool(obj.get('error') or psi.get('error') or obj.get('status') in {'failed', 'error'} or psi.get('status') in {'failed', 'error'})
    values = {key: _num(scores.get(key)) if not failed else None for key in SCORES}
    return {'status': 'ok' if not failed and values['performance'] is not None else 'failed', 'collected_at': stamp.isoformat(), 'scores': values, 'crux_status': _crux_status(obj)}


def _site(root, reports):
    site = load_site(root)
    domain = site.get('domain')
    if not isinstance(domain, str) or not re.fullmatch(r'[a-zA-Z0-9.-]+', domain):
        raise ValueError('Invalid site identity')
    setup = _dict(site.get('measurement_setup'))
    mode = 'monitoring' if setup.get('source_root_verified') is not True else 'technical' if domain == 'stunningstrangers.com' else 'maintenance'
    gsc = _gsc(_latest(root, 'gsc'))
    seen, history = set(), []
    for env in _envelopes(root, 'gsc'):
        data = _data(env)
        dates = _date_range(data)
        if not dates:
            continue
        key = (dates['start'], dates['end'])
        if key in seen:
            continue
        seen.add(key)
        aggregate = _dict(data.get('aggregate'))
        history.append({'collected_at': env['collected_at'], **dates, 'clicks': _num(aggregate.get('clicks')), 'impressions': _num(aggregate.get('impressions'))})
    gsc['history'] = sorted(history[:26], key=lambda row: row['start'])
    schedule = _dict(_read(root / '.seo' / 'schedule.json'))
    jobs = [{'lane': job['lane'], 'interval_seconds': job['interval_seconds']} for job in schedule.get('jobs', []) if isinstance(job, dict) and job.get('lane') in LANES and type(job.get('interval_seconds')) is int and job['interval_seconds'] > 0]
    return {'domain': domain, 'mode': mode, 'gsc': gsc, 'ga4': _ga4(_latest(root, 'ga4'), setup.get('ga4_event_arrival', 'unknown')), 'bing': _bing(_latest(root, 'bing')), 'audit': _simple(_latest(root, 'audit'), 'audit'), 'backlinks': _simple(_latest(root, 'backlinks'), 'backlinks'), 'performance': _performance(reports, domain), 'jobs': jobs, 'indexnow': 'accepted_202' if setup.get('indexnow_homepage_submission') == 'accepted_202' else 'verified_key' if setup.get('indexnow_live_verified') else 'unknown', 'limitations': ['Provider periods can differ. A recent collection may return older underlying data.', 'Search changes after deployment do not establish causation.', 'AI citations, competitor traffic & a comprehensive backlink index are not automated by this dashboard.']}


def build_snapshot(portfolio: Path, performance_reports: Path):
    manifest = _dict(_read(portfolio))
    roots = manifest.get('roots')
    if not isinstance(roots, list) or not 1 <= len(roots) <= 100:
        raise ValueError('Portfolio must contain 1–100 explicit roots')
    sites = []
    for index, value in enumerate(roots):
        try:
            root = Path(value)
            if not root.is_absolute():
                root = portfolio.parent / root
            sites.append(_site(root, performance_reports))
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            sites.append({'domain': f'unavailable-site-{index + 1}.invalid', 'mode': 'monitoring', 'gsc': _gsc(None), 'ga4': _ga4(None), 'bing': _bing(None), 'audit': _simple(None, 'audit'), 'backlinks': _simple(None, 'backlinks'), 'performance': {'status': 'missing', 'collected_at': None, 'scores': {k: None for k in SCORES}, 'crux_status': 'unknown'}, 'jobs': [], 'indexnow': 'unknown', 'limitations': ['Project evidence could not be read. Collector host needs attention.']})
    return {'schema_version': 1, 'generated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'), 'sites': sites}


def write_snapshot(snapshot, output: Path):
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=output.name + '.', suffix='.tmp', dir=output.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, output)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portfolio', type=Path, required=True)
    parser.add_argument('--performance-reports', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build_snapshot(args.portfolio, args.performance_reports)
    write_snapshot(result, args.output)
    print(json.dumps({'event': 'seo.dashboard.exported', 'status': 'ok', 'sites': len(result['sites']), 'generated_at': result['generated_at']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
