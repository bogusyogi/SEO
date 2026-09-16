#!/usr/bin/env python3
"""Explicit opt-in setup. Does not install any agent framework or modify host settings."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import venv
from pathlib import Path

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--path', default=str(Path.home() / '.local' / 'share' / 'seo' / 'runtime'))
    ap.add_argument('--google', action='store_true'); ap.add_argument('--reports', action='store_true')
    ap.add_argument('--browser', action='store_true'); ap.add_argument('--mcp', action='store_true')
    args = ap.parse_args()
    target = Path(args.path).expanduser().resolve()
    venv.EnvBuilder(with_pip=True).create(target)
    executable = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    groups = []
    if args.google: groups += ['google-api-python-client>=2.100,<3', 'google-auth>=2.20,<3', 'google-auth-oauthlib>=1,<2', 'google-auth-httplib2>=0.2,<1', 'google-analytics-data>=0.18,<1']
    if args.reports: groups += ['matplotlib>=3.8,<4', 'weasyprint>=61,<70', 'openpyxl>=3.1,<4']
    if args.browser: groups += ['playwright>=1.56,<2']
    if args.mcp: groups += ['mcp>=1.12,<2']
    if groups: subprocess.run([str(executable), '-m', 'pip', 'install', *groups], check=True)
    if args.browser: subprocess.run([str(executable), '-m', 'playwright', 'install', 'chromium'], check=True)
    print(json.dumps({'status': 'ok', 'python': str(executable), 'usage': f'{executable} <seo-package>/seo.py --root <site-project> doctor', 'framework_dependencies': []}))
    return 0

if __name__ == '__main__': raise SystemExit(main())
