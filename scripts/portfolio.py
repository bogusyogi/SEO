"""Explicit portfolio inventory. Discovery reads site identity, never credentials or policy writes."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from seo_state import atomic_json, state_dir
from site_policy import load
from reporting import analyze

SKIP = {'.git', '.seo', '.legion', '.venv', 'node_modules', 'vendor', 'dist', 'build', '__pycache__'}


def roots_from(path):
    path = Path(path).expanduser().resolve()
    config = json.loads(path.read_text(encoding='utf-8'))
    values = config.get('roots')
    if not isinstance(values, list) or not 1 <= len(values) <= 100 or not all(isinstance(x, str) and x.strip() for x in values):
        raise ValueError('portfolio requires 1..100 explicit site roots')
    roots = [(path.parent / value).resolve() for value in values]
    if len(set(roots)) != len(roots):
        raise ValueError('duplicate portfolio roots (including aliases)')
    # A second workspace for one site is not an independent production writer.
    owners = {}
    for root in roots:
        try:
            domain = load(root)['domain']
        except (OSError, ValueError, TypeError):
            continue  # Report this site as blocked, without preventing other sites.
        if domain in owners:
            raise ValueError('duplicate site identity in portfolio: ' + domain)
        owners[domain] = root
    return roots


def discover(search_roots, *, max_depth=4, max_directories=5000):
    if not 0 <= max_depth <= 10 or not 1 <= max_directories <= 50000:
        raise ValueError('discovery bounds exceeded')
    found, errors, visited = {}, [], 0
    for search_root in search_roots:
        base = Path(search_root).expanduser().resolve()
        if not base.is_dir():
            errors.append({'root': str(base), 'error': 'not_a_directory'})
            continue
        def onerror(error):
            errors.append({'root': str(base), 'error': type(error).__name__})
        for directory, dirs, _ in os.walk(base, followlinks=False, onerror=onerror):
            visited += 1
            if visited > max_directories:
                return {'status': 'partial', 'roots': sorted(found), 'sites': list(found.values()),
                        'errors': errors, 'reason': 'directory cap reached', 'directories': visited - 1}
            current = Path(directory)
            depth = len(current.relative_to(base).parts)
            dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith('.') and
                             not (current / d).is_symlink()) if depth < max_depth else []
            site_file = state_dir(current) / 'site.yaml'
            if site_file.is_symlink() or site_file.parent.is_symlink():
                errors.append({'root': str(current), 'error': 'symlink_state_rejected'})
                continue
            if site_file.is_file():
                try:
                    site = load(current)
                    found[str(current)] = {'root': str(current), 'domain': site['domain'],
                                           'policy_mode': site['policy']['mode']}
                except (OSError, ValueError, TypeError) as error:
                    errors.append({'root': str(current), 'error': type(error).__name__})
    return {'status': 'partial' if errors else 'ok', 'roots': sorted(found),
            'sites': [found[x] for x in sorted(found)], 'errors': errors, 'directories': visited,
            'scope': 'existing configured projects under explicit roots; not a complete domain-ownership census'}


def readiness(root):
    site = load(root)
    evidence = analyze(root)
    cfg = site.get('workflow') or {}
    deploy = site.get('deployment') or {}
    props = site.get('properties') or {}
    lanes = evidence['lanes']
    workflow_path = state_dir(root) / 'interventions/search-ops.json'
    from search_ops import load_state
    tasks = [r for r in load_state(workflow_path)['interventions'] if r.get('workflow')]
    return {'root': str(Path(root).resolve()), 'domain': site['domain'], 'policy_mode': site['policy']['mode'],
        'properties': {name: {'configured': bool(props.get(name)),
            'last_collection': lanes.get(name, {}).get('status', 'missing'),
            'freshness': lanes.get(name, {}).get('freshness', {}).get('status', 'unknown')}
            for name in ('gsc', 'ga4', 'bing')},
        'schedule_configured': (state_dir(root) / 'schedule.json').is_file(),
        'workflow_enabled': cfg.get('enabled') is True,
        'host_configured': bool((cfg.get('host') or {}).get('argv')),
        'deployment_provider': deploy.get('provider'),
        'tasks': [{'id': r['id'], 'target': r['target'], 'stage': r['workflow']['stage'],
                   'blocker': r['workflow'].get('blocker'), 'next_run_at': r['workflow'].get('next_run_at')}
                  for r in tasks],
        'critical_findings': len(evidence['critical']), 'unusable_lanes': evidence['missing'],
        'qualification': 'configuration and saved evidence only; not authenticated or live-site qualification'}


def inventory(path):
    rows = []
    for root in roots_from(path):
        try:
            rows.append(readiness(root))
        except (OSError, ValueError, TypeError, KeyError) as error:
            rows.append({'root': str(root), 'status': 'blocked', 'error': type(error).__name__})
    return {'status': 'partial' if any(x.get('status') == 'blocked' for x in rows) else 'ok', 'sites': rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('discover'); p.add_argument('--root', action='append', required=True)
    p.add_argument('--max-depth', type=int, default=4); p.add_argument('--output')
    p = sub.add_parser('status'); p.add_argument('portfolio')
    args = ap.parse_args()
    result = discover(args.root, max_depth=args.max_depth) if args.command == 'discover' else inventory(args.portfolio)
    if args.command == 'discover' and args.output:
        output = Path(args.output).resolve()
        if output.exists():
            raise ValueError('refusing to overwrite an existing portfolio manifest')
        if result['status'] != 'ok' or not result['roots']:
            raise ValueError('incomplete/empty discovery cannot silently become a portfolio manifest')
        atomic_json(output, {'roots': result['roots']})
    print(json.dumps(result, indent=2)); return 0 if result['status'] == 'ok' else 2


if __name__ == '__main__':
    raise SystemExit(main())
