"""Provider-scoped backlink snapshots. Missing sampled links are not confirmed losses."""
from __future__ import annotations
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from seo_state import atomic_json, state_dir, transaction_lock


def normalize(rows, provider):
    out = {}
    for row in rows:
        source = row.get('source_url') or row.get('url_from') or row.get('Url')
        target = row.get('target_url') or row.get('url_to')
        if not source or not target or any(urlsplit(x).scheme not in {'http','https'} for x in (source,target)):
            raise ValueError('backlink requires source_url and target_url')
        out[(source,target)] = {'source_url': source, 'target_url': target,
                               'referring_domain': urlsplit(source).hostname,
                               'anchor': row.get('anchor') or row.get('AnchorText'),
                               'rel': row.get('rel'), 'provider': provider}
    return list(out.values())


def ingest(root, payload, provider, scope, snapshot=None):
    if not provider or not scope:
        raise ValueError('provider and measured scope required')
    if payload.get('error') or payload.get('status') in {'failed','error'}:
        raise ValueError('failed provider response cannot become a snapshot')
    rows = normalize(payload.get('rows', []), provider)
    stamp = snapshot or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', stamp):
        raise ValueError('invalid snapshot name')
    path = state_dir(root) / 'backlinks' / (stamp + '.json')
    result = {'provider': provider, 'scope': scope, 'rows': rows,
              'collected_at': datetime.now(timezone.utc).isoformat(),
              'coverage': payload.get('coverage') or {'complete': False}}
    with transaction_lock(state_dir(root) / 'backlinks'):
        if path.exists():
            raise FileExistsError('immutable snapshot already exists')
        atomic_json(path, result)
    return path


def compare(old, new):
    if (old.get('provider'), old.get('scope')) != (new.get('provider'), new.get('scope')):
        return {'status': 'not_comparable', 'reason': 'provider or measured scope changed'}
    key = lambda x: (x['source_url'],x['target_url'])
    a, b = {key(x): x for x in old['rows']}, {key(x): x for x in new['rows']}
    complete = old.get('coverage', {}).get('complete') is True and new.get('coverage', {}).get('complete') is True
    return {'status': 'ok', 'newly_observed': [b[k] for k in sorted(b.keys()-a.keys())],
            'missing': [{'link': a[k], 'state': 'loss_candidate' if complete else 'not_observed_in_sample',
                         'confirmed_lost': False} for k in sorted(a.keys()-b.keys())],
            'retained': len(a.keys() & b.keys()), 'comparable_complete_coverage': complete,
            'note': 'Loss candidates require rechecking the source page; no automatic disavow or outreach.'}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.')
    sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('ingest');p.add_argument('input');p.add_argument('--provider',required=True);p.add_argument('--scope',required=True)
    sub.add_parser('compare');a=ap.parse_args()
    if a.command=='ingest':
        result={'status':'ok','path':str(ingest(a.root,json.loads(Path(a.input).read_text()),a.provider,a.scope))}
    else:
        paths=sorted((state_dir(a.root)/'backlinks').glob('*.json'))
        result=compare(*[json.loads(x.read_text()) for x in paths[-2:]]) if len(paths)>=2 else {'status':'not_testable','reason':'two snapshots required'}
    print(json.dumps(result,indent=2));return 0

if __name__=='__main__':
    raise SystemExit(main())
