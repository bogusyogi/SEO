"""Durable, exact-approved external effects; ambiguous writes are never auto-replayed."""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from seo_state import state_dir, atomic_json, transaction_lock
from site_policy import load, authorize


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat()


def path_for(root, action_id):
    if not isinstance(action_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', action_id):
        raise ValueError('invalid remote action ID')
    return state_dir(root) / 'remote-actions' / (action_id + '.json')


def fingerprint(row):
    return digest({k: row[k] for k in ('id', 'site', 'kind', 'config_digest', 'payload', 'evidence')})


def action_for(kind, payload):
    if kind == 'repository':
        return 'merge' if payload.get('operation') == 'merge' else 'deploy'
    return 'publish' if kind == 'cms' else 'deliver'


def propose(root, action_id, kind, payload, evidence):
    site = load(root)
    if kind not in {'cms', 'delivery', 'repository'} or not evidence:
        raise ValueError('supported kind and source/review evidence required')
    authorize(site, 'draft' if kind == 'cms' else action_for(kind, payload))
    with transaction_lock(state_dir(root) / 'remote-actions'):
        path = path_for(root, action_id)
        if path.exists():
            raise FileExistsError('remote action ID already exists')
        row = {'schema_version': 1, 'id': action_id, 'site': site['domain'], 'kind': kind,
               'config_digest': digest(site), 'payload': payload, 'evidence': evidence,
               'state': 'proposed', 'approval': None, 'created_at': stamp()}
        row['request_sha256'] = fingerprint(row)
        atomic_json(path, row)
        return {'id': action_id, 'state': row['state'], 'request_sha256': row['request_sha256']}


def read(root, action_id):
    row = json.loads(path_for(root, action_id).read_text(encoding='utf-8'))
    if row.get('id') != action_id:
        raise ValueError('action filename and identity mismatch')
    return row


def approve(root, action_id, expected_digest, reference):
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 500:
        raise ValueError('operator or authorized-host approval reference required')
    with transaction_lock(state_dir(root) / 'remote-actions'):
        row, site = read(root, action_id), load(root)
        if row['state'] != 'proposed' or fingerprint(row) != expected_digest or row['config_digest'] != digest(site):
            raise ValueError('proposal/configuration changed; create a fresh reviewed action')
        authorize(site, action_for(row['kind'], row['payload']))
        row.update(state='approved', approval={'digest': expected_digest, 'reference': reference})
        atomic_json(path_for(root, action_id), row)
        return {'id': action_id, 'state': 'approved', 'request_sha256': expected_digest}


def execute(root, action_id, kind, operation, *, preflight=None):
    with transaction_lock(state_dir(root) / 'remote-actions'):
        row, site = read(root, action_id), load(root)
        if row['kind'] != kind or row['site'] != site['domain'] or row['config_digest'] != digest(site):
            raise PermissionError('action kind/site/configuration mismatch')
        if fingerprint(row) != row['request_sha256'] or (row.get('approval') or {}).get('digest') != row['request_sha256']:
            raise PermissionError('exact action approval is missing or invalid')
        authorize(site, action_for(kind, row['payload']))
        if row['state'] in {'succeeded', 'partial'}:
            return {'id': action_id, 'state': row['state'], 'duplicate': True, 'receipt': row.get('receipt')}
        if row['state'] in {'running', 'uncertain'}:
            return {'id': action_id, 'state': 'uncertain', 'retry_allowed': False,
                    'reason': 'read/reconcile the external effect before any new action'}
        if row['state'] != 'approved':
            raise PermissionError('remote action is not approved')
        if preflight:
            preflight(site, row['payload'])  # Reads/validation fail before the write-ahead marker.
        row.update(state='running', started_at=stamp())
        atomic_json(path_for(root, action_id), row)
        try:
            receipt = operation(site, row['payload'], row['id'])
            if not isinstance(receipt, dict) or receipt.get('status') not in {'accepted', 'partial'} or not receipt.get('kind'):
                raise ValueError('external receipt is missing or malformed')
            row.update(state='succeeded' if receipt['status'] == 'accepted' else 'partial', receipt=receipt)
        except Exception as exc:
            # Do not persist credentials, complete exception text or API bodies into a report.
            row.update(state='uncertain', error=type(exc).__name__, retry_allowed=False)
        row['finished_at'] = stamp()
        atomic_json(path_for(root, action_id), row)
        return {'id': action_id, 'state': row['state'], 'receipt': row.get('receipt'),
                'error': row.get('error'), 'retry_allowed': False}
