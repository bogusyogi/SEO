#!/usr/bin/env python3
"""Comparable rank observations. Missing data is not a measured ranking loss."""
from __future__ import annotations
import argparse
import csv
import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATES = {'ranked', 'checked_not_found', 'not_collected', 'provider_failed'}
KEYS = ('keyword', 'market', 'language', 'device', 'provider', 'engine', 'location', 'measurement')

def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def state_dir(root: str | Path) -> Path:
    return Path(root).resolve() / '.seo' / 'rank-tracking'

def read_input(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == '.csv':
        with path.open(newline='', encoding='utf-8-sig') as fh:
            return list(csv.DictReader(fh))
    data = json.loads(path.read_text(encoding='utf-8'))
    rows = data if isinstance(data, list) else data.get('rows', data.get('observations'))
    if not isinstance(rows, list):
        raise ValueError('expected rows[] or observations[]')
    return rows

def normalize(row: dict, defaults: dict) -> dict:
    keyword = str(row.get('keyword') or row.get('query') or '').strip()
    raw = row.get('organic_position', row.get('position'))
    position = float(raw) if raw not in (None, '') else None
    if not keyword or position is not None and (not math.isfinite(position) or position <= 0):
        raise ValueError('keyword and finite positive rank are required; use explicit state for no observation')
    state = row.get('state') or ('ranked' if position is not None else 'not_collected')
    if state not in STATES or (state == 'ranked') != (position is not None):
        raise ValueError('rank state and position disagree')
    out = {'keyword': keyword, 'organic_position': position, 'state': state,
           'intended_page': row.get('intended_page') or row.get('target_url'),
           'observed_url': row.get('observed_url') or row.get('url') or row.get('page'),
           'serp_features': row.get('serp_features') or [],
           'collected_at': row.get('collected_at') or defaults.get('collected_at') or now(),
           'checked_depth': row.get('checked_depth', defaults.get('checked_depth'))}
    for name, fallback in [('market', ''), ('language', ''), ('device', 'desktop'),
                           ('provider', ''), ('engine', 'google'), ('location', ''), ('measurement', 'serp_rank')]:
        out[name] = str(row.get(name) or defaults.get(name) or fallback).strip()
    if not all(out[k] for k in ('market', 'language', 'provider')):
        raise ValueError('market, language and provider must be explicit')
    return out

def ingest(root: str | Path, observations: list[dict], defaults: dict) -> Path:
    normalized = [normalize(row, defaults) for row in observations]
    keys = [tuple(row.get(k) for k in KEYS) for row in normalized]
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate observation identity in snapshot')
    stamp = defaults.get('snapshot') or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8]
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', stamp):
        raise ValueError('snapshot must be a safe basename')
    directory = state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{stamp}.json'
    # Exclusive creation: never overwrite evidence on retries or timestamp collisions.
    with path.open('x', encoding='utf-8') as fh:
        json.dump({'schema_version': 2, 'created_at': now(), 'observations': normalized}, fh, indent=2)
        fh.write('\n')
    return path

def snapshots(root: str | Path) -> list[Path]:
    directory = state_dir(root)
    return sorted(directory.glob('*.json')) if directory.exists() else []

def compare(root: str | Path) -> dict:
    paths = snapshots(root)
    if len(paths) < 2:
        return {'status': 'not_testable', 'reason': 'two snapshots required', 'snapshots': len(paths)}
    previous, current = [json.loads(p.read_text(encoding='utf-8'))['observations'] for p in paths[-2:]]
    key = lambda row: tuple(row.get(k, 'google' if k == 'engine' else 'serp_rank' if k == 'measurement' else '') for k in KEYS)
    pmap, cmap = {key(x): x for x in previous}, {key(x): x for x in current}
    changes = []
    for identity in sorted(set(pmap) | set(cmap)):
        old, cur = pmap.get(identity), cmap.get(identity)
        if old is None or cur is None:
            changes.append({'type': 'new_keyword_observation' if old is None else 'missing_observation',
                            'current': cur, 'previous': old, 'comparable': False,
                            'reason': 'scope/provider/keyword absent; not evidence of rank change'})
            continue
        old_state = old.get('state', 'ranked' if old.get('organic_position') is not None else 'not_collected')
        cur_state = cur.get('state', 'ranked' if cur.get('organic_position') is not None else 'not_collected')
        comparable = old_state == cur_state == 'ranked'
        delta = round(old['organic_position'] - cur['organic_position'], 3) if comparable else None
        ownership = bool(comparable and old.get('observed_url') and cur.get('observed_url') and old['observed_url'] != cur['observed_url'])
        mismatch = bool(cur.get('intended_page') and cur.get('observed_url') and cur['intended_page'] != cur['observed_url'])
        changes.append({**{k: cur.get(k) for k in KEYS}, 'type': 'comparison', 'comparable': comparable,
            'previous_state': old_state, 'current_state': cur_state,
            'previous_position': old.get('organic_position'), 'current_position': cur.get('organic_position'),
            'position_improvement': delta, 'ownership_changed': ownership, 'intended_page_mismatch': mismatch,
            'previous_url': old.get('observed_url'), 'current_url': cur.get('observed_url'),
            'checked_depth': cur.get('checked_depth')})
    return {'status': 'ok', 'previous_snapshot': paths[-2].name, 'current_snapshot': paths[-1].name,
            'changes': changes, 'ownership_changes': sum(bool(x.get('ownership_changed')) for x in changes),
            'intended_page_mismatches': sum(bool(x.get('intended_page_mismatch')) for x in changes),
            'missing_observations': sum(x['type'] == 'missing_observation' for x in changes)}

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', default='.')
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('ingest')
    p.add_argument('input')
    for field in ('market', 'language', 'provider'):
        p.add_argument('--' + field, required=True)
    p.add_argument('--device', default='desktop')
    p.add_argument('--engine', default='google')
    p.add_argument('--location', default='')
    p.add_argument('--measurement', choices=['serp_rank', 'gsc_average_position'], default='serp_rank')
    p.add_argument('--snapshot')
    sub.add_parser('compare')
    args = ap.parse_args()
    out = compare(args.root) if args.command == 'compare' else {'status': 'ok', 'path': str(ingest(args.root, read_input(Path(args.input)), vars(args)))}
    print(json.dumps(out, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
