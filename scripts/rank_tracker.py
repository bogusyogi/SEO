#!/usr/bin/env python3
"""Provenance-aware rank snapshots. Missing collection is not a lost ranking."""
from __future__ import annotations
import argparse
import csv
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parent))
from seo_state import state_dir as project_state_dir, atomic_json, transaction_lock


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def state_dir(root: str | Path) -> Path:
    return project_state_dir(root) / 'rank-tracking'


def read_input(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == '.csv':
        with path.open(newline='', encoding='utf-8-sig') as fh: return list(csv.DictReader(fh))
    payload = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(payload, list): return payload
    if isinstance(payload, dict):
        for name in ('rows', 'observations'):
            if isinstance(payload.get(name), list): return payload[name]
    raise ValueError('expected list or object with rows[]/observations[]')


def normalize(row: dict, defaults: dict) -> dict:
    keyword = str(row.get('keyword') or row.get('query') or '').strip()
    provider = str(row.get('provider') or defaults.get('provider') or '').strip()
    if not keyword or not provider: raise ValueError('keyword and provider are required')
    value = row.get('organic_position', row.get('position'))
    position = float(value) if value not in (None, '') else None
    if position is not None and (not math.isfinite(position) or position < 1):
        raise ValueError('position must be finite and >= 1, or null')
    status = row.get('status') or ('ranked' if position is not None else 'not_collected')
    if status not in {'ranked','checked_not_found','not_collected','provider_failed'}:
        raise ValueError('invalid rank observation status')
    if (status == 'ranked') != (position is not None):
        raise ValueError('only ranked observations may carry a position')
    kind = row.get('observation_type') or defaults.get('observation_type') or ('gsc_average_position' if provider in {'gsc','google_gsc'} else 'serp_rank')
    result = {name: str(row.get(name) or defaults.get(name) or fallback) for name, fallback in (
        ('market',''),('language',''),('device','desktop'),('engine','google'),('location',''),('os',''))}
    if not result['market'] or not result['language']: raise ValueError('market and language are required')
    result.update(keyword=keyword, provider=provider, observation_type=kind, status=status,
                  intended_page=row.get('intended_page') or row.get('target_url'),
                  observed_url=row.get('observed_url') or row.get('url') or row.get('page'),
                  organic_position=position, serp_features=row.get('serp_features') or [],
                  search_depth=row.get('search_depth') or defaults.get('search_depth'),
                  collected_at=row.get('collected_at') or defaults.get('collected_at') or now())
    return result


def key(row: dict) -> tuple:
    return tuple(row.get(k) for k in ('keyword','market','language','device','provider','engine','location','observation_type','os'))


def ingest(root: str | Path, observations: list[dict], defaults: dict) -> Path:
    directory = state_dir(root)
    normalized = [normalize(r, defaults) for r in observations]
    keys = [key(r) for r in normalized]
    if len(set(keys)) != len(keys): raise ValueError('duplicate keyword/measurement identity in snapshot')
    stamp = defaults.get('snapshot') or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', stamp): raise ValueError('invalid snapshot identifier')
    path = directory / f'{stamp}.json'
    with transaction_lock(directory / '.snapshots'):
        if path.exists(): raise ValueError('snapshot already exists; never overwrite evidence')
        atomic_json(path, {'schema_version':2, 'created_at':now(), 'observations':normalized})
    return path


def snapshots(root: str | Path) -> list[Path]:
    directory = state_dir(root)
    return sorted(directory.glob('*.json')) if directory.exists() else []


def compare_rows(previous: list[dict], current: list[dict]) -> dict:
    pmap, cmap = {key(r):r for r in previous}, {key(r):r for r in current}
    streams = lambda rows: {key(r)[1:] for r in rows}
    if previous and current and not streams(previous).intersection(streams(current)):
        return {'status':'not_comparable','reason':'provider, engine, market, device or measurement type changed','changes':[]}
    changes = []
    for k in sorted(pmap.keys() | cmap.keys(), key=str):
        old, cur = pmap.get(k), cmap.get(k)
        if cur is None:
            changes.append({'type':'missing_observation','keyword':old['keyword'],'provider':old.get('provider'),
                            'status':'not_collected','previous':old})
            continue
        if old is None:
            changes.append({'type':'new_keyword_observation','keyword':cur['keyword'],'current':cur}); continue
        comparable = old.get('status','ranked') == cur.get('status','ranked') == 'ranked'
        op, np = old.get('organic_position'), cur.get('organic_position')
        changes.append({'type':'comparison','keyword':cur['keyword'], 'provider':cur.get('provider'),
                        'market':cur.get('market'),'language':cur.get('language'),'device':cur.get('device'),
                        'observation_type':cur.get('observation_type'),'status':cur.get('status'),
                        'previous_position':op,'current_position':np,
                        'position_improvement':round(op-np,3) if comparable and op is not None and np is not None else None,
                        'previous_url':old.get('observed_url'),'current_url':cur.get('observed_url'),
                        'ownership_changed':bool(comparable and old.get('observed_url') and cur.get('observed_url') and old['observed_url'] != cur['observed_url']),
                        'intended_page_mismatch':bool(cur.get('intended_page') and cur.get('observed_url') and cur['intended_page'] != cur['observed_url'])})
    return {'status':'ok','changes':changes,
            'ownership_changes':sum(bool(c.get('ownership_changed')) for c in changes),
            'intended_page_mismatches':sum(bool(c.get('intended_page_mismatch')) for c in changes),
            'missing_observations':sum(c.get('type') == 'missing_observation' for c in changes)}


def compare(root: str | Path) -> dict:
    paths = snapshots(root)
    if len(paths) < 2:
        return {'status':'not_testable','reason':'two snapshots required','snapshots':len(paths)}
    # Collectors may interleave different providers/devices. Compare consecutive
    # observations within each stream, never just the last two files globally.
    streams = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding='utf-8'))
        grouped = {}
        for row in payload.get('observations', []):
            grouped.setdefault(key(row)[1:], []).append(row)
        for identity, rows in grouped.items():
            streams.setdefault(identity, []).append((payload.get('created_at', ''), path.name, rows))
    results = []
    for identity, observations in streams.items():
        observations.sort(key=lambda item: (item[0], item[1]))
        if len(observations) < 2:
            results.append({'status':'not_testable', 'stream':list(identity), 'changes':[],
                            'reason':'two snapshots of this measurement stream required'})
            continue
        previous, current = observations[-2:]
        result = compare_rows(previous[2], current[2])
        results.append(dict(result, stream=list(identity), previous_snapshot=previous[1],
                            current_snapshot=current[1], collected_at=current[0]))
    usable = [x for x in results if x['status'] == 'ok']
    if len(results) == 1:
        return dict(results[0], streams=results)
    changes = [item for result in usable for item in result['changes']]
    return {'status':'ok' if usable else 'not_testable', 'streams':results, 'changes':changes,
            'ownership_changes':sum(x.get('ownership_changes',0) for x in usable),
            'intended_page_mismatches':sum(x.get('intended_page_mismatches',0) for x in usable),
            'missing_observations':sum(x.get('missing_observations',0) for x in usable),
            'unqualified_streams':len(results)-len(usable)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    sub = parser.add_subparsers(dest='command',required=True)
    p = sub.add_parser('ingest'); p.add_argument('input'); p.add_argument('--market',required=True)
    p.add_argument('--language',required=True); p.add_argument('--provider',required=True)
    p.add_argument('--device',default='desktop'); p.add_argument('--engine',default='google'); p.add_argument('--snapshot')
    sub.add_parser('compare'); args=parser.parse_args()
    try:
        result = {'status':'ok','path':str(ingest(args.root,read_input(Path(args.input)),vars(args)))} if args.command == 'ingest' else compare(args.root)
    except (ValueError,OSError) as exc:
        result={'status':'error','error':str(exc)}
    print(json.dumps(result,indent=2)); return 1 if result['status'] == 'error' else 0

if __name__ == '__main__': raise SystemExit(main())
