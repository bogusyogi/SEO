"""Configuration inspection, optionally followed by bounded site-specific live reads."""
from __future__ import annotations
import argparse
import importlib.util
import json
import sys
from pathlib import Path
from collector import collect
from provider_registry import discover
from site_policy import load, property_for


def doctor(root='.', live=False):
    result = {'status': 'configured_only', 'runtime_verified': False,
              'providers': discover()['providers'], 'properties': {},
              'python': sys.version.split()[0]}
    try:
        site = load(root)
    except (ValueError, OSError) as exc:
        return result | {'status': 'unconfigured', 'error': str(exc)}
    result['site'] = site['domain']
    for provider in ('gsc', 'ga4', 'bing'):
        try:
            value = property_for(site, provider)
            row = {'status': 'mapped', 'property': value}
            if live:
                evidence = collect(root, provider, days=7, max_pages=1, timeout=90)
                row.update(status='data_available' if evidence['status'] == 'ok' else 'failed',
                           collected_at=evidence['collected_at'], error=evidence['error'])
            result['properties'][provider] = row
        except (ValueError, PermissionError) as exc:
            result['properties'][provider] = {'status': 'unconfigured', 'error': str(exc)}
    result['runtime_verified'] = live and all(v['status'] == 'data_available' for v in result['properties'].values())
    if live:
        result['status'] = 'ok' if result['runtime_verified'] else 'partial'
    result['note'] = 'GA4 identity mapping is operator-supplied; confirm the web stream and instrumentation separately.'
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--live', action='store_true')
    a = ap.parse_args()
    result = doctor(a.root, a.live)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] in {'ok', 'configured_only'} else 2

if __name__ == '__main__':
    raise SystemExit(main())
