#!/usr/bin/env python3
"""Portable SEO entrypoint; works independently from any directory and any agent host."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'scripts'))
from runtime_setup import python_executable

COMMANDS={
    'project':'seo_project.py','doctor':'provider_doctor.py','runtime':'runtime_setup.py',
    'audit':'site_audit.py','gsc':'gsc_query_v2.py','ga4':'ga4_report.py',
    'bing':'bing_webmaster.py','rank':'rank_tracker.py','backlinks':'backlink_tracker.py',
    'ops':'search_ops.py','run':'seo_runner.py','content':'content_queue.py',
    'scan':'external_scan.py','closure':'seo_closure.py','providers':'provider_registry.py',
    'mcp':'mcp_server.py','coverage':'coverage.py',
}


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {'--help','-h'}:
        print('SEO 0.2.0 — standalone; no Legion dependency\n')
        print('Usage: python /path/to/SEO/seo.py COMMAND [arguments]\n')
        for k,v in COMMANDS.items():print(f'  {k:12s} {v}')
        print('  migrate-state  --root SITE_ROOT (preserves historical state)')
        return 0
    cmd=args.pop(0)
    if cmd=='migrate-state':
        import argparse
        from seo_state import migrate
        ap=argparse.ArgumentParser();ap.add_argument('--root',default='.')
        print(json.dumps(migrate(ap.parse_args(args).root),indent=2));return 0
    if cmd not in COMMANDS:
        print('Unknown SEO command',file=sys.stderr);return 2
    script=ROOT/'scripts'/COMMANDS[cmd]
    return subprocess.run([python_executable(),str(script),*args],check=False).returncode

if __name__=='__main__':
    raise SystemExit(main())
