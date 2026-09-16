"""Reviewable single-file content/metadata changes with real local receipts and rollback.

The operator approves an exact content digest. This adapter writes only approved
prefixes inside a configured site repository. Publication to a remote deployment is
separate: verify reads the actual URL and never equates a local edit with deployment.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from seo_state import atomic_json, state_dir, transaction_lock
from site_policy import load, authorize
from safe_http import fetch


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def item_path(root, item_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', item_id):
        raise ValueError('invalid queue id')
    return state_dir(root) / 'queue' / (item_id + '.json')


def target_path(root, relative):
    base = Path(root).resolve()
    target = base / relative
    if target.is_symlink() or any(p.is_symlink() for p in target.parents if p != base and base in p.parents):
        raise PermissionError('symlink publication targets are forbidden')
    target = target.resolve()
    if target == base or base not in target.parents:
        raise PermissionError('target escapes site repository')
    return target


def replace_bytes(target, data):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.seo-write-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if target.exists():
            os.chmod(tmp, target.stat().st_mode & 0o777)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def propose(root, item_id, *, path, content, url, kind='content', evidence=None):
    site = load(root)
    authorize(site, 'draft' if kind == 'content' else 'metadata', url=url, path=path)
    if kind not in {'content', 'metadata'} or not isinstance(content, str) or not content.strip():
        raise ValueError('nonempty text and content/metadata kind required')
    raw = content.encode()
    if len(raw) > 1024 * 1024 or not evidence:
        raise ValueError('proposal requires evidence and must not exceed 1 MiB')
    target = target_path(root, path)
    out = item_path(root, item_id)
    with transaction_lock(state_dir(root) / 'queue'):
        if out.exists():
            raise FileExistsError('proposal id already exists')
        previous = target.read_bytes() if target.exists() else None
        row = {'id': item_id, 'site': site['domain'], 'path': path, 'url': url, 'kind': kind,
               'content': content, 'content_sha256': digest(raw),
               'baseline_sha256': digest(previous) if previous is not None else None,
               'baseline': previous.decode('utf-8') if previous is not None else None,
               'evidence': evidence, 'status': 'proposed', 'approval': None,
               'created_at': datetime.now(timezone.utc).isoformat()}
        atomic_json(out, row)
        return {k: v for k, v in row.items() if k not in {'content', 'baseline'}}


def approve(root, item_id, *, content_sha256, approval_ref):
    if not approval_ref or len(approval_ref) > 500:
        raise ValueError('explicit approval reference required')
    with transaction_lock(state_dir(root) / 'queue'):
        path = item_path(root, item_id)
        row = json.loads(path.read_text())
        if row['status'] != 'proposed' or row['content_sha256'] != content_sha256:
            raise ValueError('approval must match the exact proposed digest')
        row.update(status='approved', approval={'reference': approval_ref, 'digest': content_sha256})
        atomic_json(path, row)
        return {'id': item_id, 'status': 'approved', 'content_sha256': content_sha256}


def apply(root, item_id):
    with transaction_lock(state_dir(root) / 'queue'):
        path = item_path(root, item_id)
        row = json.loads(path.read_text())
        site = load(root)
        action = 'publish' if row['kind'] == 'content' else 'metadata'
        authorize(site, action, url=row['url'], path=row['path'])
        if row['site'] != site['domain']:
            raise PermissionError('proposal site identity changed')
        data = row['content'].encode()
        if digest(data) != row['content_sha256'] or (row.get('approval') or {}).get('digest') != digest(data):
            raise PermissionError('content changed after approval')
        target = target_path(root, row['path'])
        current = digest(target.read_bytes()) if target.exists() else None
        if row['status'] in {'applied', 'deployed_verified'}:
            if current != row['content_sha256']:
                raise ValueError('applied target subsequently changed')
            return {'id': item_id, 'status': row['status'], 'duplicate': True, 'receipt': row['receipt']}
        if row['status'] not in {'approved', 'applying'}:
            raise PermissionError('proposal has not been approved')
        if current != row['baseline_sha256'] and not (row['status'] == 'applying' and current == digest(data)):
            raise ValueError('baseline mismatch; reconcile concurrent site edits')
        # Write-ahead state allows safe recovery if the process dies after replace.
        row['status'] = 'applying'
        atomic_json(path, row)
        replace_bytes(target, data)
        row['receipt'] = {'kind': 'local_file_write', 'path': row['path'],
                          'sha256': digest(target.read_bytes()), 'recorded_at': datetime.now(timezone.utc).isoformat()}
        row['status'] = 'applied'
        atomic_json(path, row)
        return {'id': item_id, 'status': 'applied', 'receipt': row['receipt'],
                'deployed': False, 'next': 'host deploys the change, then verify the public URL'}


def verify(root, item_id, *, expected_text, fetcher=fetch):
    if not expected_text or len(expected_text) > 10000:
        raise ValueError('nonempty expected rendered text required')
    path = item_path(root, item_id)
    with transaction_lock(state_dir(root) / 'queue'):
        row = json.loads(path.read_text())
        authorize(load(root), 'verify', url=row['url'])
        if row['status'] not in {'applied', 'deployed_verified'}:
            raise ValueError('verification requires an applied proposal')
        result = fetcher(row['url'])
        passed = result['status'] == 200 and expected_text in result['body']
        row['verification'] = {'passed': passed, 'url': result['url'], 'http_status': result['status'],
                               'body_sha256': digest(result['body'].encode()), 'expected_text': expected_text,
                               'checked_at': datetime.now(timezone.utc).isoformat(),
                               'scope': 'HTTP response and expected text only; not full render or SEO outcome'}
        row['status'] = 'deployed_verified' if passed else 'applied'
        atomic_json(path, row)
        return row['verification']


def rollback(root, item_id):
    with transaction_lock(state_dir(root) / 'queue'):
        path = item_path(root, item_id)
        row = json.loads(path.read_text())
        site = load(root)
        authorize(site, 'rollback', url=row['url'], path=row['path'])
        target = target_path(root, row['path'])
        if row['status'] not in {'applied', 'deployed_verified'}:
            raise ValueError('rollback requires applied change')
        if not target.exists() or digest(target.read_bytes()) != row['content_sha256']:
            raise ValueError('rollback would overwrite unrelated edits')
        if row['baseline'] is None:
            target.unlink()
        else:
            replace_bytes(target, row['baseline'].encode())
        row['status'] = 'rolled_back'
        row['rollback_receipt'] = {'kind': 'local_file_rollback', 'path': row['path'], 'remote_redeploy_required': True}
        atomic_json(path, row)
        return row['rollback_receipt']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('propose'); p.add_argument('id'); p.add_argument('--path', required=True)
    p.add_argument('--content-file', required=True); p.add_argument('--url', required=True)
    p.add_argument('--kind', choices=['content','metadata'], default='content'); p.add_argument('--evidence', required=True)
    p = sub.add_parser('approve'); p.add_argument('id'); p.add_argument('--digest', required=True); p.add_argument('--approval-ref', required=True)
    for cmd in ('apply','rollback'):
        p = sub.add_parser(cmd); p.add_argument('id')
    p = sub.add_parser('verify'); p.add_argument('id'); p.add_argument('--expected-text', required=True)
    a = ap.parse_args()
    if a.command == 'propose':
        result = propose(a.root, a.id, path=a.path, content=Path(a.content_file).read_text(), url=a.url, kind=a.kind, evidence=a.evidence)
    elif a.command == 'approve':
        result = approve(a.root, a.id, content_sha256=a.digest, approval_ref=a.approval_ref)
    elif a.command == 'verify':
        result = verify(a.root, a.id, expected_text=a.expected_text)
    else:
        result = globals()[a.command](a.root, a.id)
    print(json.dumps(result, indent=2))
    return 2 if result.get('passed') is False else 0

if __name__ == '__main__':
    raise SystemExit(main())
