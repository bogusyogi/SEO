"""Publish allowlisted, read-only portfolio evidence for a private dashboard."""
from __future__ import annotations
import argparse
import json
import math
import os
import re
import tempfile
from urllib.parse import urlsplit
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


def _url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    value = value.strip().split(' (', 1)[0]
    parsed = urlsplit(value)
    return value if parsed.scheme in {'http', 'https'} and parsed.hostname else None


def _unique_urls(values):
    out = []
    seen = set()
    for value in values:
        candidate = _url(value)
        if candidate and candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


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
        affected = {level: set() for level in ('critical', 'errors', 'warnings', 'info')}
        for name, targets in _dict(data.get('issues')).items():
            if not isinstance(targets, list):
                continue
            level = next((level for level in ('critical', 'errors', 'warnings', 'info') if name in severity.get(level, [])), 'info')
            urls = [_text(url, 2048) for url in targets if isinstance(url, str)]
            affected[level].update(_unique_urls(urls))
            issues.append({'name': _text(name), 'severity': level, 'count': len(targets), 'urls': urls[:10]})
        complete = _dict(data.get('coverage')).get('complete')
        pages = _dict(data.get('pages'))
        page_urls = _unique_urls(pages.keys())
        error_free = 0
        unknown_status = False
        if page_urls:
            for page_url in page_urls:
                row = _dict(pages.get(page_url))
                status = row.get('status', row.get('initial_status'))
                if type(status) is int and 200 <= status < 300:
                    error_free += 1
                elif type(status) is not int:
                    unknown_status = True
        health = (100 * error_free / len(page_urls)) if page_urls and not unknown_status else None
        broken = _dict(data.get('broken_links_all', data.get('broken_links')))
        redirects = _dict(data.get('redirects'))
        blocked_urls = []
        broken_urls = []
        for raw_url, row in broken.items():
            candidate = _url(raw_url)
            if not candidate:
                continue
            status = _dict(row).get('status')
            if type(status) is int and status in {401, 403, 429, 451, 999} or status == 0:
                blocked_urls.append(candidate)
            else:
                broken_urls.append(candidate)
        redirect_urls = _unique_urls(redirects.keys())
        return {**_base(env), 'crawled': _num(data.get('crawled')), 'complete': complete if type(complete) is bool else None,
                'issues': sorted(issues, key=lambda item: ({'critical': 0, 'errors': 1, 'warnings': 2, 'info': 3}[item['severity']], item['name'])),
                'response_health_score': health, 'response_health_basis': {'error_free_urls': error_free, 'crawled_urls': len(page_urls), 'unknown_status_urls': sum(1 for url in page_urls if type(_dict(pages.get(url)).get('status', _dict(pages.get(url)).get('initial_status'))) is not int)} if page_urls else None,
                'affected_urls': {key: len(value) for key, value in affected.items()},
                'redirects': {'count': len(redirect_urls), 'urls': redirect_urls[:100]},
                'broken': {'count': len(_unique_urls(broken_urls)), 'urls': _unique_urls(broken_urls)[:100]},
                'blocked': {'count': len(_unique_urls(blocked_urls)), 'urls': _unique_urls(blocked_urls)[:100]}}
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
    empty = {'status': 'missing', 'collected_at': None, 'scores': {k: None for k in SCORES}, 'crux_status': 'unknown', 'vitals': {'lab': {'lcp_ms': None, 'cls': None, 'tbt_ms': None}, 'crux': {'lcp_ms': None, 'inp_ms': None, 'cls': None}}}
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
    lab = _dict(psi.get('lab_metrics'))
    def metric(name, aliases=()):
        row = _dict(lab.get(name))
        value = row.get('value', lab.get(name))
        if value is None:
            for alias in aliases:
                row = _dict(lab.get(alias)); value = row.get('value', lab.get(alias))
                if value is not None: break
        return _num(value) if not failed else None
    crux = _dict(obj.get('crux'))
    cm = _dict(crux.get('metrics'))
    latest = _dict(crux.get('latest_p75'))
    def crux_metric(key, aliases=()):
        for source in (latest, cm):
            for name in (key, *aliases):
                value = source.get(name)
                if isinstance(value, dict): value = value.get('p75', value.get('value'))
                if value is not None: return _num(value) if not failed else None
        return None
    vitals = {'lab': {'lcp_ms': metric('largest-contentful-paint', ('lcp',)), 'cls': metric('cumulative-layout-shift', ('cls',)), 'tbt_ms': metric('total-blocking-time', ('tbt',))},
              'crux': {'lcp_ms': crux_metric('lcp_ms', ('lcp', 'largest_contentful_paint')), 'inp_ms': crux_metric('inp_ms', ('inp', 'interaction_to_next_paint')), 'cls': crux_metric('cls', ('cumulative_layout_shift',))}}
    return {'status': 'ok' if not failed and values['performance'] is not None else 'failed', 'collected_at': stamp.isoformat(), 'scores': values, 'crux_status': _crux_status(obj), 'vitals': vitals}


def _sanitize_detail(value, key='', depth=0):
    if depth > 4:
        return None
    if type(value) in (int, float, bool):
        return _num(value) if type(value) in (int, float) else value
    if isinstance(value, str):
        if key == 'page' and value.startswith('/') and not value.startswith('//') and '\\' not in value and not any(ord(ch) < 32 for ch in value):
            return _text(value, 2048)
        if key.endswith('_url') or key in {'url', 'page', 'source_url', 'target_url', 'google_canonical', 'user_canonical'}:
            return _url(value)
        return _safe_error(value) if key in {'error', 'message'} else _text(value, 256)
    if isinstance(value, list):
        return [clean for item in value[:400] if (clean := _sanitize_detail(item, key, depth + 1)) is not None]
    if isinstance(value, dict):
        out = {}
        allowed = {'query', 'page', 'url', 'source_url', 'target_url', 'domain', 'referring_domain', 'clicks', 'previous_clicks', 'impressions', 'previous_impressions', 'ctr', 'position', 'previous_position', 'sessions', 'users', 'key_events', 'revenue', 'date', 'country', 'device', 'links', 'change', 'delta', 'current', 'previous', 'daily', 'devices', 'countries', 'pages', 'query_changes', 'totals', 'date_range', 'coverage', 'complete', 'scope', 'start', 'end', 'status', 'collected_at', 'imported_at', 'value', 'provider', 'attribution', 'currency', 'time_zone', 'event_arrival', 'rows', 'referring_domains', 'newly_observed', 'missing', 'stats', 'queries', 'crawl', 'index_status', 'crawl_info', 'canonical', 'mobile_usability', 'rich_results', 'verdict', 'error', 'issues', 'google_canonical', 'user_canonical', 'match', 'identity_configured', 'collection', 'mode', 'state', 'prerequisites', 'evidence', 'reports', 'saved_site_report', 'pageviews', 'coverage_state', 'robots_txt_state', 'indexing_state', 'page_fetch_state', 'last_crawl_time', 'crawled_as', 'referring_urls', 'query_rows', 'query_cap', 'query_hit_cap', 'note', 'missing_observation', 'urls_requested', 'targets_requested', 'target_urls', 'avg_impression_position'}
        for name, item in value.items():
            if not isinstance(name, str) or name not in allowed or name.lower() in {'token', 'secret', 'authorization', 'key_source', 'path'}:
                continue
            clean = _sanitize_detail(item, name, depth + 1)
            if clean is not None:
                out[name] = clean
        return out
    return None


def _detail_rows(value, limit=400):
    if not isinstance(value, list):
        return []
    rows = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        row = _sanitize_detail(item)
        if row:
            rows.append(row)
    return rows


def _bing_stats(value):
    out = {}
    for group in ('queries', 'pages', 'crawl'):
        rows = []
        for item in _dict(value).get(group, [])[:10000] if isinstance(_dict(value).get(group), list) else []:
            if not isinstance(item, dict):
                continue
            raw_date = item.get('Date')
            match = re.fullmatch(r'/Date\((-?\d+)(?:[+-]\d{4})?\)/', str(raw_date))
            try:
                date = datetime.fromtimestamp(int(match[1]) / 1000, timezone.utc) if match else _stamp(raw_date, True)
            except (ValueError, OverflowError, OSError):
                date = MIN_TIME
            row = {'date': date.date().isoformat() if date != MIN_TIME else None,
                   'query': _url(item.get('Query')) if group == 'pages' else _text(item.get('Query'), 512) if isinstance(item.get('Query'), str) else None,
                   'clicks': _num(item.get('Clicks')), 'impressions': _num(item.get('Impressions')),
                   'avg_impression_position': _num(item.get('AvgImpressionPosition'))}
            rows.append({key: val for key, val in row.items() if val is not None})
        out[group] = sorted(rows, key=lambda row: row.get('date', ''), reverse=True)[:400]
    return out


def _detail_report(root, name):
    obj = _read(root / '.seo' / 'reports' / name)
    return obj if isinstance(obj, dict) else None


def _detail_status(value):
    status = _dict(value).get('status')
    return status if status in STATUSES else 'missing'


def _safe_error(value):
    value = _text(value, 256)
    value = re.sub(r'(?i)(?:[A-Za-z]:)?[\\/](?:[^\s\\/]+[\\/])*[^\s]+', '[redacted]', value)
    value = re.sub(r'(?i)(token|secret|key|authorization)\s*[:=]\s*[^\s]+', r'\1=[redacted]', value)
    return value


def _safe_mapping(value, depth=0):
    if depth > 2 or not isinstance(value, dict):
        return {}
    out = {}
    for key, raw in value.items():
        if not isinstance(key, str) or len(key) > 80 or key.lower() in {'token', 'secret', 'key', 'authorization', 'path', 'source'}:
            continue
        if isinstance(raw, dict):
            clean = _safe_mapping(raw, depth + 1)
        elif type(raw) in (int, float, bool):
            clean = _num(raw) if type(raw) in (int, float) else raw
        elif isinstance(raw, str) and key.lower() in {'start', 'end', 'date', 'scope', 'complete', 'provider', 'attribution', 'time_zone', 'status'}:
            clean = _text(raw, 256)
        else:
            continue
        out[key] = clean
    return out


def _provider_details(root):
    domain = load_site(root).get('domain')
    report = _detail_report(root, 'provider-details.json')
    links = _detail_report(root, 'gsc-links.json')
    if report and (report.get('schema_version') != 1 or report.get('site') != domain):
        report = None
    if links and (links.get('schema_version') != 1 or links.get('site') != domain):
        links = None
    details = {}
    if report:
        out = {'status': _detail_status(report), 'collected_at': report.get('collected_at') if _stamp(report.get('collected_at')) != MIN_TIME else None}
        for lane, keys in {
            'gsc': ('date_range', 'current', 'previous', 'daily', 'devices', 'countries', 'pages', 'query_changes', 'coverage'),
            'ga4': ('date_range', 'totals', 'daily', 'pages', 'devices', 'countries', 'currency', 'time_zone', 'event_arrival'),
            'indexing': ('rows', 'coverage'), 'backlinks': ('rows', 'referring_domains', 'coverage', 'newly_observed', 'missing', 'stats'),
            'domain_rating': ('value', 'provider', 'attribution', 'collected_at'),
            'bing': ('rows', 'referring_domains', 'coverage', 'newly_observed', 'missing', 'stats')}.items():
            source = _dict(report.get(lane)); lane_out = {'status': _detail_status(source), 'collected_at': source.get('collected_at') if _stamp(source.get('collected_at')) != MIN_TIME else None}
            if lane_out['status'] in {'failed', 'error'}:
                out[lane] = lane_out
                continue
            for key in keys:
                value = source.get(key)
                if key in {'daily', 'devices', 'countries', 'pages', 'query_changes', 'rows', 'newly_observed', 'missing'}: value = _detail_rows(value, 2000 if key == 'query_changes' else 400)
                elif key == 'stats': value = _bing_stats(value)
                elif key == 'referring_domains': value = _num(value) if type(value) in (int, float) else [_text(item, 256) for item in value[:400] if isinstance(item, str)] if isinstance(value, list) else None
                elif key in {'value'}: value = _num(value)
                elif key in {'collected_at'}: value = value if _stamp(value) != MIN_TIME else None
                elif key in {'date_range', 'coverage', 'current', 'previous', 'totals'}: value = _sanitize_detail(value, key)
                elif key in {'currency'}: value = value if isinstance(value, str) and re.fullmatch('[A-Z]{3}', value) else None
                elif isinstance(value, str): value = _text(value, 256)
                if value is not None: lane_out[key] = value
            if source.get('error'): lane_out['error'] = _safe_error(source.get('error'))
            out[lane] = lane_out
        if report.get('errors'):
            out['errors'] = [{'provider': _text(_dict(item).get('provider'), 80), 'message': _safe_error(_dict(item).get('message'))} for item in report['errors'][:20] if isinstance(item, dict)]
        details['provider'] = out
    if links:
        rows = []
        for row in links.get('rows', [])[:400] if isinstance(links.get('rows'), list) else []:
            if not isinstance(row, dict): continue
            source, target = _url(row.get('source_url')), _url(row.get('target_url'))
            if source: rows.append({'source_url': source, 'target_url': target, 'referring_domain': _text(row.get('referring_domain'), 256) if isinstance(row.get('referring_domain'), str) else None})
        domain_rows = _detail_rows(links.get('domains'))
        details['imported_links'] = {'status': _detail_status(links), 'collected_at': links.get('collected_at') if _stamp(links.get('collected_at')) != MIN_TIME else None, 'imported_at': links.get('imported_at') if _stamp(links.get('imported_at')) != MIN_TIME else None, 'coverage': _sanitize_detail(links.get('coverage'), 'coverage'), 'rows': rows, 'domains': domain_rows, 'referring_domains': _num(links.get('referring_domains')) if type(links.get('referring_domains')) in (int, float) else len(links.get('referring_domains', [])) if isinstance(links.get('referring_domains'), list) else None}
    observed = _detail_report(root, 'ahrefs-observed.json')
    if observed and (observed.get('schema_version') != 1 or observed.get('site') != domain):
        observed = None
    if observed:
        details['ahrefs_observed'] = {
            'schema_version': 1,
            'site': _text(observed.get('site'), 256),
            'provider': 'ahrefs_web',
            'observed_at': observed.get('observed_at') if _stamp(observed.get('observed_at')) != MIN_TIME else None,
            'collected_at': observed.get('collected_at') if _stamp(observed.get('collected_at')) != MIN_TIME else None,
            'observed_date': observed.get('observed_date') if _stamp(observed.get('observed_date'), True) != MIN_TIME else None,
            'recorded_at': observed.get('recorded_at') if _stamp(observed.get('recorded_at')) != MIN_TIME else None,
            'status': _detail_status(observed),
            'health_score': _num(observed.get('health_score')),
            'crawled': _num(observed.get('crawled')),
            'redirects': _num(observed.get('redirects')),
            'broken': _num(observed.get('broken')),
            'blocked': _num(observed.get('blocked')),
            'domain_rating': _num(observed.get('domain_rating')),
            'referring_domains': _num(observed.get('referring_domains')),
            'coverage': _safe_mapping(observed.get('coverage')),
        }
    return details


def _merge_provider_overview(gsc, details):
    source = _dict(_dict(details.get('provider')).get('gsc'))
    current = _dict(source.get('current'))
    if source.get('status') not in {'ok', 'success', 'partial'} or not current or _stamp(source.get('collected_at')) < _stamp(gsc.get('collected_at')):
        return gsc
    values = {key: _num(current.get(key)) for key in ('clicks', 'impressions', 'ctr', 'position')}
    if not any(value is not None for value in values.values()):
        return gsc
    legacy_collected = gsc.get('collected_at')
    gsc['rows_collected_at'] = legacy_collected
    gsc['collected_at'] = source.get('collected_at')
    gsc['status'] = source.get('status')
    gsc['metrics'] = values
    date_range = _dict(source.get('date_range')).get('current')
    if isinstance(date_range, dict) and _stamp(date_range.get('start'), True) != MIN_TIME and _stamp(date_range.get('end'), True) != MIN_TIME:
        gsc['date_range'] = {'start': date_range['start'][:10], 'end': date_range['end'][:10]}
    previous = _dict(source.get('previous'))
    if previous:
        gsc['previous'] = {key: _num(previous.get(key)) for key in ('clicks', 'impressions', 'ctr', 'position')}
    return gsc


def _readiness(reports, domain):
    obj = _read(reports.parent / 'agent-readiness.json')
    if not isinstance(obj, dict) or obj.get('schema_version') != 1 or obj.get('kind') != 'seo_agent_readiness':
        return None
    site = next((item for item in obj.get('sites', []) if isinstance(item, dict) and item.get('site') == domain), None)
    if not site:
        return None
    identities = {}
    for name, value in _dict(site.get('provider_identities')).items():
        if isinstance(value, dict):
            identities[name] = {'identity_configured': value.get('identity_configured') is True, 'collection': _text(value.get('collection'), 64) if isinstance(value.get('collection'), str) else None}
    route = {}
    for name, value in _dict(site.get('route_plan')).items():
        if isinstance(value, dict) and isinstance(value.get('state'), str):
            route[name] = {'state': _text(value['state'], 64)}
    evidence = _dict(site.get('evidence'))
    return {'activation': obj.get('activation') if isinstance(obj.get('activation'), str) else None, 'provider_identities': identities, 'policy': {'mode': _text(_dict(site.get('policy')).get('mode'), 64)}, 'route_plan': route, 'evidence': {'reports': [_text(item, 128) for item in evidence.get('reports', [])[:100] if isinstance(item, str)], 'saved_site_report': evidence.get('saved_site_report') is True}}


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
    details = _provider_details(root)
    readiness = _readiness(reports, domain)
    if readiness:
        details['readiness'] = readiness
    gsc = _merge_provider_overview(gsc, details)
    result = {'domain': domain, 'mode': mode, 'gsc': gsc, 'ga4': _ga4(_latest(root, 'ga4'), setup.get('ga4_event_arrival', 'unknown')), 'bing': _bing(_latest(root, 'bing')), 'audit': _simple(_latest(root, 'audit'), 'audit'), 'backlinks': _simple(_latest(root, 'backlinks'), 'backlinks'), 'performance': _performance(reports, domain), 'jobs': jobs, 'indexnow': 'accepted_202' if setup.get('indexnow_homepage_submission') == 'accepted_202' else 'verified_key' if setup.get('indexnow_live_verified') else 'unknown', 'limitations': ['Provider periods can differ. A recent collection may return older underlying data.', 'Search changes after deployment do not establish causation.', 'AI citations, competitor traffic & a comprehensive backlink index are not automated by this dashboard.']}
    if details: result['details'] = details
    return result


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
            sites.append({'domain': f'unavailable-site-{index + 1}.invalid', 'mode': 'monitoring', 'gsc': _gsc(None), 'ga4': _ga4(None), 'bing': _bing(None), 'audit': _simple(None, 'audit'), 'backlinks': _simple(None, 'backlinks'), 'performance': _performance(Path('Z:\missing-performance-reports'), f'unavailable-site-{index + 1}.invalid'), 'jobs': [], 'indexnow': 'unknown', 'limitations': ['Project evidence could not be read. Collector host needs attention.']})
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
