"""Optional controlled DataForSEO SERPs. Free first-party operation never needs this lane.

Operator-approved local reservations are not a vendor-enforced billing cap. A paid
request with an uncertain response is retained and never silently billed again.
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from urllib.parse import urlsplit
from authenticated_http import request
from measurement_scope import site_hosts
from seo_state import state_dir, atomic_json, transaction_lock
from site_policy import load
from remote_actions import digest


def micros(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            raise ValueError('invalid budget')
        return int((number * 1000000).to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, TypeError):
        raise ValueError('invalid budget') from None


def settings(site):
    cfg, policy = site.get('serp') or {}, site['policy']
    if cfg.get('provider') != 'dataforseo' or not policy.get('approval_ref') or 'dataforseo' not in policy.get('allowed_paid_providers', []):
        raise PermissionError('controlled SERPs require explicitly approved optional provider spending')
    if site['policy']['mode'] == 'technical_only':
        raise PermissionError('technical-only sites do not run keyword campaigns')
    words = cfg.get('keywords')
    if not isinstance(words, list) or not 1 <= len(words) <= 100 or not all(isinstance(x, str) and 0 < len(x.strip()) <= 700 for x in words):
        raise ValueError('configure 1..100 nonempty keyword strings')
    if type(cfg.get('location_code')) is not int or cfg['location_code'] <= 0:
        raise ValueError('explicit provider location_code required')
    if not isinstance(cfg.get('language_code'), str) or not cfg['language_code'] or cfg.get('device') not in {'desktop', 'mobile'}:
        raise ValueError('explicit language_code and desktop/mobile device required')
    if cfg.get('os') not in ({'windows', 'macos'} if cfg['device'] == 'desktop' else {'android', 'ios'}):
        raise ValueError('explicit compatible operating system required for comparable SERPs')
    if type(cfg.get('depth')) is not int or not 10 <= cfg['depth'] <= 100:
        raise ValueError('configured depth must be 10..100')
    if micros(cfg.get('reserve_per_request_usd')) <= 0 or micros(policy.get('monthly_serp_budget_usd')) <= 0:
        raise ValueError('positive request reservation and monthly budget required')
    return cfg


def normalize_response(site, cfg, keyword, payload):
    tasks = payload.get('tasks') or []
    if payload.get('status_code') != 20000 or len(tasks) != 1 or tasks[0].get('status_code') != 20000:
        raise ValueError('SERP provider did not complete the task successfully')
    results = tasks[0].get('result') or []
    if len(results) != 1 or not isinstance(results[0].get('items'), list):
        raise ValueError('SERP task returned no verifiable result set')
    actual = results[0]
    echo = tasks[0].get('data') or {}
    if any(echo.get(key) != cfg[key] for key in ('device', 'os', 'depth')):
        raise ValueError('provider did not confirm the requested device/OS/depth')
    if actual.get('keyword') != keyword or actual.get('location_code') != cfg['location_code'] or actual.get('language_code') != cfg['language_code']:
        raise ValueError('provider returned a different query/location/language')
    matches = [item for item in actual['items'] if item.get('type') == 'organic'
               and urlsplit(item.get('url') or '').hostname in site_hosts(site)]
    if any(type(item.get('rank_group')) is not int or item['rank_group'] < 1 for item in matches):
        raise ValueError('invalid provider organic position')
    best = min(matches, key=lambda x: x['rank_group']) if matches else None
    return {'keyword': keyword, 'position': best['rank_group'] if best else None,
            'url': best['url'] if best else None, 'status': 'ranked' if best else 'checked_not_found',
            'provider': 'dataforseo', 'observation_type': 'serp_rank', 'engine': 'google',
            'market': site['market'], 'language': cfg['language_code'], 'device': cfg['device'],
            'location': str(cfg['location_code']), 'os': cfg['os'], 'search_depth': cfg['depth'],
            'serp_features': sorted({x.get('type') for x in actual['items'] if x.get('type')}),
            'scope': 'not found means absent from this returned SERP sample, not globally unranked'}


def collect(root, run_id=None, transport=request):
    site = load(root)
    cfg = settings(site)
    run_id = run_id or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if not isinstance(run_id, str) or not 1 <= len(run_id) <= 100:
        raise ValueError('bounded run identity required')
    login, password = os.environ.get('DATAFORSEO_LOGIN'), os.environ.get('DATAFORSEO_PASSWORD')
    if not login or not password:
        raise ValueError('DataForSEO credentials are not configured')
    headers = {'Authorization': 'Basic ' + base64.b64encode((login + ':' + password).encode()).decode()}
    base = state_dir(root) / 'serp'
    rows, receipts, failures = [], [], []
    with transaction_lock(base / 'collection'):
        db = sqlite3.connect(base / 'spend.sqlite')
        try:
            db.execute('CREATE TABLE IF NOT EXISTS spend (id TEXT PRIMARY KEY, month TEXT, reserved INTEGER, actual INTEGER, state TEXT)')
            for keyword in dict.fromkeys(word.strip() for word in cfg['keywords']):
                task = {'keyword': keyword, 'location_code': cfg['location_code'], 'language_code': cfg['language_code'],
                        'device': cfg['device'], 'os': cfg['os'], 'depth': cfg['depth']}
                identity = digest([site['domain'], site_hosts(site), run_id, task])
                path = base / 'requests' / (identity + '.json')
                prior = db.execute('SELECT state FROM spend WHERE id=?', (identity,)).fetchone()
                if prior:
                    if prior[0] == 'ok' and path.exists():
                        saved = json.loads(path.read_text(encoding='utf-8'))
                        rows.append(saved['observation']); receipts.append({'id': identity, 'cached': True})
                    else:
                        failures.append({'keyword': keyword, 'reason': 'previous paid request unresolved; no automatic retry'})
                    continue
                if db.execute('SELECT 1 FROM spend WHERE actual > reserved LIMIT 1').fetchone():
                    failures.append({'keyword': keyword, 'reason': 'prior charge exceeded reservation; paid collection paused for operator reconciliation'})
                    break
                month = datetime.now(timezone.utc).strftime('%Y-%m')
                reservation = micros(cfg['reserve_per_request_usd'])
                used = db.execute('SELECT COALESCE(SUM(MAX(reserved,COALESCE(actual,0))),0) FROM spend WHERE month=?', (month,)).fetchone()[0]
                if used + reservation > micros(site['policy']['monthly_serp_budget_usd']):
                    failures.append({'keyword': keyword, 'reason': 'monthly local reservation budget exhausted'})
                    continue
                db.execute('INSERT INTO spend VALUES (?,?,?,?,?)', (identity, month, reservation, None, 'uncertain'))
                db.commit()  # A crash/timeout cannot turn a possibly charged request into a fresh request.
                try:
                    response = transport('https://api.dataforseo.com', 'POST', '/v3/serp/google/organic/live/advanced', headers=headers, payload=[task])
                    if response.get('cost') is None:
                        raise ValueError('provider cost receipt missing; reservation remains consumed')
                    actual_cost = micros(response['cost'])
                    db.execute('UPDATE spend SET actual=? WHERE id=?', (actual_cost, identity)); db.commit()
                    observation = normalize_response(site, cfg, keyword, response)
                    observation['collected_at'] = datetime.now(timezone.utc).isoformat()
                    atomic_json(path, {'request': task, 'response': response, 'observation': observation, 'cost_usd': str(Decimal(actual_cost) / 1000000)})
                    db.execute("UPDATE spend SET state='ok' WHERE id=?", (identity,)); db.commit()
                    rows.append(observation); receipts.append({'id': identity, 'cached': False, 'actual_cost_usd': actual_cost / 1000000})
                    if actual_cost > reservation:
                        failures.append({'keyword': keyword, 'reason': 'provider charge exceeded reservation; collection stopped'})
                        break
                except Exception as exc:
                    failures.append({'keyword': keyword, 'reason': type(exc).__name__, 'state': 'uncertain'})
        finally:
            db.close()
    return {'status': 'partial' if failures else 'ok', 'provider': 'dataforseo', 'rows': rows, 'failures': failures,
            'receipts': receipts, 'run_id': run_id, 'billing_limit': 'local reservation; not a vendor-enforced cap'}


def main():
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument('--root', default='.'); ap.add_argument('--run-id')
    a = ap.parse_args()
    try:
        result = collect(a.root, a.run_id)
        if result['rows']:
            from rank_tracker import ingest
            result['snapshot'] = str(ingest(a.root, result['rows'], {'provider': 'dataforseo'}))
    except (ValueError, OSError, PermissionError) as exc:
        result = {'status': 'blocked', 'error': str(exc)}
    print(json.dumps(result, indent=2)); return 0 if result['status'] == 'ok' else 2


if __name__ == '__main__':
    raise SystemExit(main())
