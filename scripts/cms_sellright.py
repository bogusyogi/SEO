"""SellRight blog adapter: explicit store identity, reviewed drafts, and uncertain-write recovery.

No password login, automatic token acquisition, deletion or blind retry. Existing-post
updates require explicit acknowledgement that this API lacks atomic compare-and-set.
"""
from __future__ import annotations
import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import quote, urlsplit
from authenticated_http import request
from site_policy import load, authorize
from seo_state import atomic_json, state_dir, transaction_lock
import remote_actions as actions

FIELDS = {'title', 'excerpt', 'body', 'authorName', 'tags', 'isPublished', 'seoTitle', 'seoDescription'}


def editable(post):
    return {key: post.get(key) if post.get(key) is not None else ([] if key == 'tags' else False if key == 'isPublished' else '')
            for key in sorted(FIELDS)}


def validate_body(body, create=False):
    if not isinstance(body, dict) or not body or set(body) - FIELDS - ({'slug'} if create else set()):
        raise ValueError('unsupported/empty blog fields')
    for key, value in body.items():
        if key == 'tags':
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise ValueError('tags must be strings')
        elif key == 'isPublished':
            if type(value) is not bool:
                raise ValueError('isPublished must be boolean')
        elif not isinstance(value, str):
            raise ValueError('blog fields must be strings')
    if create:
        if not body.get('title', '').strip() or not body.get('body', '').strip() or not body.get('authorName', '').strip():
            raise ValueError('new drafts require a title, body and real author name')
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', body.get('slug', '')) or len(body['slug']) > 80:
            raise ValueError('explicit stable slug required (maximum 80 characters)')
        if body.get('isPublished', False) is not False:
            raise ValueError('create a draft first; publication is a separate reviewed update')
    if 'title' in body and not body['title'].strip():
        raise ValueError('title cannot be empty')


class SellRight:
    def __init__(self, site, transport=request):
        self.site = site
        self.config = site.get('cms') or {}
        self.transport = transport
        cfg = self.config
        if cfg.get('provider') != 'sellright' or not all(cfg.get(k) for k in ('api_origin', 'store_slug', 'store_id', 'token_env')):
            raise ValueError('configure SellRight origin, exact store slug/ID and token environment name')
        p = urlsplit(cfg['api_origin'])
        if p.scheme != 'https' or not p.hostname or p.path not in ('', '/') or p.username or p.password or p.query or p.fragment:
            raise ValueError('SellRight requires an explicit HTTPS origin')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', cfg['token_env']):
            raise ValueError('token_env must be an environment-variable name')

    def call(self, method, path, payload=None):
        token = os.environ.get(self.config['token_env'])
        if not token:
            raise ValueError('CMS session token environment variable is not configured')
        return self.transport(self.config['api_origin'], method, path,
            headers={'Authorization': 'Bearer ' + token, 'x-store-slug': self.config['store_slug']}, payload=payload)

    def identity(self, write=False):
        me = self.call('GET', '/v1/admin/me')
        matches = [s for s in me.get('stores', []) if s.get('slug') == self.config['store_slug'] and s.get('storeId') == self.config['store_id']]
        if len(matches) != 1 or write and matches[0].get('role') not in {'owner', 'manager', 'staff'}:
            raise PermissionError('CMS session does not grant the exact configured store/role')
        return {'store_id': self.config['store_id'], 'store_slug': self.config['store_slug'], 'role': matches[0]['role']}

    def listing(self):
        self.identity()
        result = self.call('GET', '/v1/admin/blog')
        if not isinstance(result.get('items'), list):
            raise ValueError('invalid blog list')
        return result['items']

    def read(self, post_id):
        if not isinstance(post_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', post_id):
            raise ValueError('invalid post ID')
        post = self.call('GET', '/v1/admin/blog/' + quote(post_id, safe=''))
        if str(post.get('id')) != post_id or post.get('storeId') != self.config['store_id']:
            raise PermissionError('CMS response crossed post/store identity')
        return post

    def prepare(self, body, post_id=None):
        self.identity()
        validate_body(body, create=post_id is None)
        if post_id is None:
            if any(p.get('slug') == body['slug'] for p in self.listing()):
                raise ValueError('slug exists; use an explicitly selected post ID')
            desired = dict(body, isPublished=False)
            return {'operation': 'create_draft', 'body': desired, 'post_id': None, 'baseline': None}
        before = self.read(post_id)
        return {'operation': 'update', 'body': body, 'post_id': post_id,
                'baseline': editable(before), 'baseline_sha256': actions.digest(editable(before))}

    def preflight(self, payload):
        self.identity(write=True)
        body, post_id = payload['body'], payload['post_id']
        validate_body(body, create=post_id is None)
        if post_id is None:
            if any(p.get('slug') == body['slug'] for p in self.listing()):
                raise ValueError('slug appeared after preparation; no creation attempted')
        else:
            if self.config.get('allow_non_atomic_updates') is not True:
                raise PermissionError('CMS lacks atomic conditional updates; explicit allow_non_atomic_updates acknowledgement required')
            if actions.digest(editable(self.read(post_id))) != payload['baseline_sha256']:
                raise ValueError('CMS baseline conflict; remote post changed')

    def apply(self, payload):
        post_id = payload['post_id']
        created = post_id is None
        result = self.call('POST' if created else 'PATCH', '/v1/admin/blog' + ('' if created else '/' + quote(post_id, safe='')), payload['body'])
        actual_id = str(result.get('id') or '')
        if not actual_id or not created and actual_id != post_id:
            raise ValueError('CMS response has no matching post ID')
        observed = self.read(actual_id)
        if created and observed.get('slug') != payload['body']['slug']:
            raise ValueError('CMS assigned a different slug; reconcile without deleting/retrying')
        expected = dict(payload.get('baseline') or {}, **payload['body'])
        if any(editable(observed).get(k) != v for k, v in expected.items() if k in FIELDS):
            raise ValueError('CMS readback does not match approved fields')
        return {'kind': 'sellright_blog_readback', 'status': 'accepted', 'post_id': actual_id,
            'store_id': self.config['store_id'], 'slug': observed.get('slug'),
            'remote_sha256': actions.digest(editable(observed)), 'remote_state': editable(observed),
            'is_published': observed.get('isPublished'), 'public_page_verified': False,
            'concurrency': 'preflight comparison only; API has no atomic conditional write'}


def prepare(root, action_id, body, *, evidence, post_id=None, transport=request):
    site = load(root)
    authorize(site, 'draft')
    return actions.propose(root, action_id, 'cms', SellRight(site, transport).prepare(body, post_id), evidence)


def apply(root, action_id, transport=request):
    return actions.execute(root, action_id, 'cms',
        lambda site, payload, _: SellRight(site, transport).apply(payload),
        preflight=lambda site, payload: SellRight(site, transport).preflight(payload))


def reconcile(root, action_id, post_id, transport=request):
    """Read-only external check; never invent a missing receipt or retry an uncertain POST."""
    site = load(root)
    authorize(site, 'cms_read')
    with transaction_lock(state_dir(root) / 'remote-actions'):
        row = actions.read(root, action_id)
        if row['kind'] != 'cms' or row['site'] != site['domain'] or row['config_digest'] != actions.digest(site) or actions.fingerprint(row) != row['request_sha256']:
            raise PermissionError('action or configuration mismatch')
        if row['payload']['post_id'] is not None and row['payload']['post_id'] != post_id:
            raise ValueError('reconciliation post does not match the approved target')
        client = SellRight(site, transport)
        client.identity()
        post = client.read(post_id)
        wanted = row['payload']['body']
        actual = dict(editable(post), slug=post.get('slug'))
        matches = all(actual.get(k) == v for k, v in wanted.items())
        result = {'post_id': post_id, 'matches_approved_fields': matches,
                  'state': row['state'], 'causation_proven': False, 'automatic_retry': False,
                  'checked_at': actions.stamp()}
        row['reconciliation'] = result
        atomic_json(actions.path_for(root, action_id), row)
        return result


def prepare_rollback(root, original_id, new_id, evidence, transport=request):
    row = actions.read(root, original_id)
    if row['kind'] != 'cms' or row['state'] != 'succeeded':
        raise ValueError('rollback needs a successful, identified CMS receipt')
    site = load(root)
    authorize(site, 'rollback')
    if row['site'] != site['domain'] or row['config_digest'] != actions.digest(site) or actions.fingerprint(row) != row['request_sha256']:
        raise PermissionError('rollback source/site/configuration mismatch')
    receipt = row['receipt']
    client = SellRight(site, transport)
    client.identity()
    if actions.digest(editable(client.read(receipt['post_id']))) != receipt['remote_sha256']:
        raise ValueError('rollback would overwrite a subsequent CMS edit')
    body = row['payload']['baseline'] or {'isPublished': False}
    # New drafts are retained/unpublished, never deleted. Rollback itself needs approval.
    return prepare(root, new_id, body, evidence=evidence, post_id=receipt['post_id'], transport=transport)



def verify(root, action_id, url, expected_text, fetcher=None):
    from safe_http import fetch
    fetcher = fetch if fetcher is None else fetcher
    site = load(root)
    authorize(site, 'verify', url=url)
    with transaction_lock(state_dir(root) / 'remote-actions'):
        row = actions.read(root, action_id)
        if row['kind'] != 'cms' or row['state'] != 'succeeded' or row['site'] != site['domain'] or row['config_digest'] != actions.digest(site) or actions.fingerprint(row) != row['request_sha256']:
            raise ValueError('public verification requires an identified successful CMS action')
        body = {**(row['payload'].get('baseline') or {}), **row['payload']['body']}
        if not expected_text or len(expected_text) > 10000 or not any(expected_text in str(body.get(k, '')) for k in ('body', 'title', 'excerpt')):
            raise ValueError('expected text must occur in the approved content')
        observed = fetcher(url)
        authorize(site, 'verify', url=observed['url'])
        result = {'url': observed['url'], 'http_status': observed['status'],
            'passed': observed['status'] == 200 and expected_text in observed['body'],
            'checked_at': actions.stamp(), 'body_sha256': actions.digest(observed['body']),
            'scope': 'HTTP response assertion only; rendered DOM and search outcomes are separate'}
        row['public_verification'] = result
        atomic_json(actions.path_for(root, action_id), row)
        return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', default='.')
    sub = ap.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    p = sub.add_parser('prepare'); p.add_argument('id'); p.add_argument('--body', required=True); p.add_argument('--post-id'); p.add_argument('--evidence', required=True)
    p = sub.add_parser('approve'); p.add_argument('id'); p.add_argument('--digest', required=True); p.add_argument('--approval-ref', required=True)
    p = sub.add_parser('apply'); p.add_argument('id')
    p = sub.add_parser('reconcile'); p.add_argument('id'); p.add_argument('--post-id', required=True)
    p = sub.add_parser('verify'); p.add_argument('id'); p.add_argument('--url', required=True); p.add_argument('--expected-text', required=True)
    p = sub.add_parser('rollback'); p.add_argument('original'); p.add_argument('id'); p.add_argument('--evidence', required=True)
    a = ap.parse_args()
    try:
        if a.command == 'list':
            site = load(a.root); authorize(site, 'cms_read'); result = {'items': SellRight(site).listing()}
        elif a.command == 'prepare':
            result = prepare(a.root, a.id, json.loads(Path(a.body).read_text(encoding='utf-8')), evidence=a.evidence, post_id=a.post_id)
        elif a.command == 'approve': result = actions.approve(a.root, a.id, a.digest, a.approval_ref)
        elif a.command == 'apply': result = apply(a.root, a.id)
        elif a.command == 'verify': result = verify(a.root, a.id, a.url, a.expected_text)
        elif a.command == 'reconcile': result = reconcile(a.root, a.id, a.post_id)
        else: result = prepare_rollback(a.root, a.original, a.id, a.evidence)
    except (ValueError, OSError, PermissionError, RuntimeError) as exc:
        result = {'state': 'blocked', 'error': str(exc)}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 2 if result.get('passed') is False or result.get('state') in {'blocked', 'uncertain', 'partial'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
