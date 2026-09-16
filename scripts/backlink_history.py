"""Provider-scoped backlink observations. A disappearance is initially unconfirmed."""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from seo_io import atomic_write, digest

def ingest(root, payload):
    for field in ('provider', 'property', 'target', 'collected_at'):
        if not payload.get(field):
            raise ValueError('backlink snapshot missing ' + field)
    if not isinstance(payload.get('rows'), list):
        raise ValueError('backlink rows must be an array')
    rows = []
    for row in payload['rows']:
        source, target = row.get('source_url'), row.get('target_url')
        if not source or not target:
            raise ValueError('backlink row needs source_url and target_url')
        rows.append({**row, 'referring_domain': urlsplit(source).hostname})
    record = {**payload, 'schema_version': 1, 'rows': rows, 'snapshot_digest': digest(payload)}
    path = Path(root).resolve() / '.seo' / 'backlinks' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8] + '.json')
    atomic_write(path, json.dumps(record, indent=2).encode())
    return path

def compare(previous, current):
    context = ('provider', 'property', 'target', 'filters')
    if any(previous.get(k) != current.get(k) for k in context):
        return {'status': 'not_testable', 'reason': 'incomparable provider, site, target or filters'}
    key = lambda x: (x.get('source_url'), x.get('target_url'))
    old = {key(x): x for x in previous.get('rows', [])}
    new = {key(x): x for x in current.get('rows', [])}
    complete = previous.get('complete') is True and current.get('complete') is True and not current.get('error') and not previous.get('error')
    return {'status': 'ok' if complete else 'partial', 'provider': current['provider'],
        'new_observations': [new[k] for k in sorted(new.keys() - old.keys())],
        'lost_candidates': [old[k] for k in sorted(old.keys() - new.keys())] if complete else [],
        'unconfirmed_missing': [old[k] for k in sorted(old.keys() - new.keys())] if not complete else [],
        'confirmed_lost': [], 'rule': 'Candidates require source-page/provider recheck. No automatic disavow or outreach.'}

def latest(root):
    paths = sorted((Path(root).resolve() / '.seo' / 'backlinks').glob('*.json'))
    if len(paths) < 2:
        return {'status': 'not_testable', 'reason': 'two snapshots required'}
    return compare(*[json.loads(p.read_text()) for p in paths[-2:]])
