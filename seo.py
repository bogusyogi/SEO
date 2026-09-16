#!/usr/bin/env python3
"""Independent SEO CLI. Run with --root /absolute/site/project from any directory."""
from __future__ import annotations
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts'))
from seo_runtime import Runtime, Blocked, init_site, load_site, migrate_state

VERSION = '0.2.0'

def payload(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict): raise ValueError('job input must be a JSON object')
    return value

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', default='.', help='site project, not plugin installation directory')
    ap.add_argument('--version', action='version', version=VERSION)
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('init')
    for key in ('domain', 'market', 'language'): p.add_argument('--' + key, required=True)
    p.add_argument('--gsc-property'); p.add_argument('--ga4-property'); p.add_argument('--bing-site')
    p = sub.add_parser('doctor'); p.add_argument('--live', action='store_true')
    p.add_argument('--provider', choices=['gsc', 'ga4', 'bing_links'], action='append')
    sub.add_parser('migrate-state')
    p = sub.add_parser('collect'); p.add_argument('provider', choices=['gsc', 'ga4', 'bing_links', 'crawl', 'pagespeed'])
    p.add_argument('--options', help='JSON file containing provider options')
    sub.add_parser('report')
    p = sub.add_parser('enqueue'); p.add_argument('kind', choices=['collect', 'report', 'draft', 'patch', 'publish', 'rollback', 'deliver'])
    p.add_argument('--input', required=True); p.add_argument('--at'); p.add_argument('--key')
    p = sub.add_parser('approve'); p.add_argument('job_id')
    p = sub.add_parser('inspect'); p.add_argument('job_id')
    p = sub.add_parser('jobs'); p.add_argument('--limit', type=int, default=20)
    p = sub.add_parser('schedule'); p.add_argument('name'); p.add_argument('--provider')
    p.add_argument('--report', action='store_true'); p.add_argument('--every-hours', type=float, default=24)
    p.add_argument('--options')
    p = sub.add_parser('tick'); p.add_argument('--limit', type=int, default=10)
    p = sub.add_parser('serve'); p.add_argument('--interval-seconds', type=int, default=60)
    p = sub.add_parser('portfolio'); p.add_argument('--projects', required=True, help='JSON array of explicit site project paths')
    args = ap.parse_args(argv)
    if args.command == 'init':
        out = init_site(args.root, args.domain, args.market, args.language,
                       gsc_property=args.gsc_property, ga4_property=args.ga4_property, bing_site=args.bing_site)
    elif args.command == 'migrate-state': out = migrate_state(args.root)
    elif args.command == 'doctor':
        from provider_doctor import doctor
        out = doctor(args.root, live=args.live, providers=args.provider)
    elif args.command == 'portfolio':
        projects = json.loads(Path(args.projects).read_text())
        if not isinstance(projects, list) or not all(isinstance(p, str) for p in projects):
            raise ValueError('portfolio must be an array of project paths')
        out = []
        for project in projects:
            try: out.append({'project': project, 'result': Runtime(project).tick()})
            except Exception as exc: out.append({'project': project, 'status': 'failed', 'error': str(exc)})
    else:
        runtime = Runtime(args.root)
        if args.command == 'enqueue':
            due = None
            if args.at:
                dt = datetime.fromisoformat(args.at.replace('Z', '+00:00'))
                if dt.tzinfo is None: raise ValueError('--at must include a timezone offset')
                due = dt.timestamp()
            out = runtime.enqueue(args.kind, payload(args.input), due=due, key=args.key)
        elif args.command == 'approve': out = runtime.approve(args.job_id)
        elif args.command == 'inspect': out = runtime.row(args.job_id)
        elif args.command == 'jobs': out = runtime.jobs(args.limit)
        elif args.command == 'schedule':
            if not args.report and not args.provider: raise ValueError('schedule needs --provider or --report')
            p = {} if args.report else {'provider': args.provider, 'options': payload(args.options) if args.options else {}}
            out = runtime.add_schedule(args.name, p, args.every_hours, 'report' if args.report else 'collect')
        elif args.command == 'tick': out = runtime.tick(args.limit)
        elif args.command == 'serve':
            if args.interval_seconds < 30: raise ValueError('poll interval must be at least 30 seconds')
            try:
                while True:
                    print(json.dumps(runtime.tick(), ensure_ascii=False), flush=True)
                    time.sleep(args.interval_seconds)
            except KeyboardInterrupt:
                return 0
        elif args.command in ('collect', 'report'):
            p = {'provider': args.provider, 'options': payload(args.options) if args.options else {}} if args.command == 'collect' else {}
            job = runtime.enqueue(args.command, p, key=datetime.now().isoformat())
            out = runtime.tick(limit=1, only_id=job['id'])
        else: raise ValueError('unsupported command')
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if isinstance(out, dict) and (out.get('error') or out.get('status') in {'failed', 'blocked', 'unconfigured'}): return 1
    if isinstance(out, dict) and any(j['state'] not in {'succeeded', 'partial'} for j in out.get('jobs', [])): return 1
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'blocked', 'error': str(exc)}), file=sys.stderr)
        raise SystemExit(2)
