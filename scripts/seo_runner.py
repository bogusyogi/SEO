"""Standalone scheduled reads with SQLite uniqueness, bounded retries and operator briefs.

Invoke tick from any scheduler. No cron, service, cloud job or publication is installed
implicitly. Schedules are local operator-authored JSON, never LLM-generated commands.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from collector import collect, persist_observations
from seo_state import state_dir, atomic_json, transaction_lock
from site_policy import load
from reporting import analyze, render

LANES = {'audit', 'gsc', 'ga4', 'bing', 'backlinks', 'gsc_ranks', 'serp'}


def tick(root='.', *, now=None, run_collector=collect):
    site = load(root)
    now = float(time.time() if now is None else now)
    base = state_dir(root)
    path = base / 'schedule.json'
    if not path.exists():
        return {'status': 'not_configured', 'reason': 'no schedule.json; no jobs run'}
    schedule = json.loads(path.read_text(encoding='utf-8'))
    jobs = schedule.get('jobs', [])
    if len(jobs) > 20:
        raise ValueError('at most 20 jobs per site')
    # Serialize local workers for the whole bounded batch. OS releases SQLite locks
    # on process death; completed cadence keys are durable and never duplicated.
    with transaction_lock(base / 'runner', timeout=1):
        db = sqlite3.connect(base / 'jobs.sqlite')
        db.execute('CREATE TABLE IF NOT EXISTS jobs (key TEXT PRIMARY KEY, lane TEXT, bucket INTEGER, attempts INTEGER, state TEXT, next_retry REAL, result TEXT)')
        runs = []
        try:
            for job in jobs:
                lane = job.get('lane')
                seconds = job.get('interval_seconds', 86400)
                if lane not in LANES or not isinstance(seconds, int) or not 3600 <= seconds <= 2678400:
                    raise ValueError('unknown lane or interval outside one hour..31 days')
                if job.get('enabled', True) is not True:
                    continue
                bucket = int(now // seconds)
                fingerprint = hashlib.sha256(json.dumps({'site': site, 'job': job}, sort_keys=True).encode()).hexdigest()[:16]
                key = f'{lane}:{bucket}:{fingerprint}'
                row = db.execute('SELECT attempts,state,next_retry,result FROM jobs WHERE key=?', (key,)).fetchone()
                if row and (row[1] == 'ok' or row[0] >= 3 or row[2] > now):
                    runs.append({'key': key, 'lane': lane, 'status': 'already_recorded', 'last_status': row[1]})
                    continue
                attempt = (row[0] if row else 0) + 1
                db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?)', (key, lane, bucket, attempt, 'running', now + 60, None))
                db.commit()
                try:
                    result = run_collector(root, lane, days=int(job.get('days', 28)),
                                           max_pages=int(job.get('max_pages', 100)),
                                           timeout=int(job.get('timeout_seconds', 180)))
                except Exception as exc:
                    result = {'status': 'failed', 'site': site['domain'], 'lane': lane, 'error': type(exc).__name__}
                if result.get('site') != site['domain']:
                    result = {'status': 'failed', 'lane': lane, 'site': site['domain'], 'error': 'collector site mismatch'}
                stamp = key.replace(':', '-') + f'-{attempt}'
                artifact = base / lane / (stamp + '.json')
                atomic_json(artifact, result)
                try:
                    result.update(persist_observations(root, result, stamp))
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    result.update(status='partial', history_error=type(exc).__name__)
                atomic_json(artifact, result)
                db.execute('UPDATE jobs SET state=?,next_retry=?,result=? WHERE key=?',
                           (result.get('status', 'failed'), now + min(3600, 60 * 2**attempt), str(artifact), key))
                db.commit()
                runs.append({'key': key, 'lane': lane, 'status': result.get('status'), 'artifact': str(artifact), 'attempt': attempt})
            failed = any(x.get('status') not in {'ok', 'already_recorded'} or
                         x.get('status') == 'already_recorded' and x.get('last_status') != 'ok' for x in runs)
            report = {'status': 'partial' if failed else 'ok', 'site': site['domain'],
                      'recorded_at': datetime.fromtimestamp(now, timezone.utc).isoformat(), 'jobs': runs}
            atomic_json(base / 'reports/latest-run.json', report)
            analysis = analyze(root)
            atomic_json(base / 'reports/evidence-brief.json', analysis)
            (base / 'reports/latest-run.md').write_text(render(site['domain'], analysis), encoding='utf-8')
            if (site.get('delivery') or {}).get('auto_send_reports') is True:
                from report_delivery import deliver_latest
                try:
                    report['delivery'] = deliver_latest(root)
                except Exception as exc:
                    report['delivery'] = {'state': 'blocked', 'error': type(exc).__name__}
                if report['delivery'].get('state') != 'succeeded':
                    report['status'] = 'partial'
                atomic_json(base / 'reports/latest-run.json', report)
            return report
        finally:
            db.close()


def portfolio(path):
    config_path = Path(path).resolve()
    config = json.loads(config_path.read_text(encoding='utf-8'))
    roots = config.get('roots') or []
    if not roots or len(roots) > 100:
        raise ValueError('portfolio requires 1..100 explicit site roots')
    results = []
    for root in roots:
        site_root = (config_path.parent / root).resolve()
        try:
            results.append(tick(site_root))
        except Exception as exc:
            results.append({'root': str(site_root), 'status': 'failed', 'error': type(exc).__name__})
    return {'status': 'ok' if all(x.get('status') == 'ok' for x in results) else 'partial', 'sites': results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--portfolio')
    ap.add_argument('command', choices=['tick', 'serve'], nargs='?', default='tick')
    ap.add_argument('--poll-seconds', type=int, default=300)
    ap.add_argument('--max-ticks', type=int, default=0, help='0 runs in the foreground until stopped')
    a = ap.parse_args()
    if a.command == 'serve':
        if a.poll_seconds < 60 or a.max_ticks < 0:
            ap.error('poll interval must be at least 60 seconds and max-ticks nonnegative')
        count = 0
        try:
            while not a.max_ticks or count < a.max_ticks:
                result = portfolio(a.portfolio) if a.portfolio else tick(a.root)
                print(json.dumps(result), flush=True)
                count += 1
                if not a.max_ticks or count < a.max_ticks:
                    time.sleep(a.poll_seconds)
        except KeyboardInterrupt:
            return 0
        return 0 if result['status'] == 'ok' else 2
    result = portfolio(a.portfolio) if a.portfolio else tick(a.root)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'ok' else 2

if __name__ == '__main__':
    raise SystemExit(main())
