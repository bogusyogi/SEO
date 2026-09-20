"""Exact-approved GitHub branch/PR publication using the existing remote-effect ledger.

Never force-push or mutate the default branch directly. Optional merges need a separate
policy, exact head SHA and named passing checks. Deployment is a provider receipt for
the exact merged commit/environment; public HTTP verification happens separately.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import quote, urlencode
from authenticated_http import request
import content_queue as queue
import media_assets
import remote_actions as actions
from seo_state import state_dir, atomic_json, transaction_lock
from site_policy import load, authorize


def git_blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise ValueError('invalid Git object identity')
    return value


class GitHub:
    def __init__(self, site, transport=request):
        self.site, self.config, self.transport = site, site.get('deployment') or {}, transport
        cfg = self.config
        if cfg.get('provider') != 'github' or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', cfg.get('repository', '')):
            raise ValueError('configure an exact GitHub repository')
        if type(cfg.get('repository_id')) is not int or cfg['repository_id'] <= 0:
            raise ValueError('exact numeric repository_id required')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', cfg.get('token_env', '')):
            raise ValueError('GitHub token environment reference required')
        if not cfg.get('base_branch') or not cfg.get('environment'):
            raise ValueError('explicit base_branch and deployment environment required')
        self.prefix = '/repos/'+cfg['repository']

    def call(self, method, path, payload=None, *, list_result=False):
        token = os.environ.get(self.config['token_env'])
        if not token:
            raise ValueError('GitHub token unavailable; provision/renew outside SEO state')
        return self.transport('https://api.github.com', method, self.prefix+path,
            headers={'Authorization': 'Bearer '+token, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2026-03-10'}, payload=payload,
            allow_list=list_result, max_payload_bytes=8*1024*1024)

    def identity(self):
        repo = self.call('GET', '')
        if repo.get('id') != self.config['repository_id'] or str(repo.get('full_name', '')).lower() != self.config['repository'].lower():
            raise PermissionError('repository identity mismatch')

    def base(self):
        return sha(self.call('GET', '/git/ref/heads/'+quote(self.config['base_branch'], safe=''))['object']['sha'])

    def tree(self, commit):
        record = self.call('GET', '/git/commits/'+sha(commit))
        tree_sha = sha(record['tree']['sha'])
        tree = self.call('GET', '/git/trees/'+tree_sha+'?recursive=1')
        if tree.get('truncated') or not isinstance(tree.get('tree'), list):
            raise ValueError('Git tree is truncated or malformed')
        entries = {row['path']: {'sha': sha(row['sha']), 'mode': row['mode'], 'type': row['type']}
                   for row in tree['tree'] if row['type'] != 'tree'}
        return tree_sha, entries

    def checks(self, commit):
        names = self.config.get('required_checks')
        if not isinstance(names, list) or not names or not all(isinstance(x, str) and x for x in names):
            raise PermissionError('automatic merge requires explicit nonempty required_checks')
        statuses = self.call('GET', '/commits/'+sha(commit)+'/statuses?per_page=100', list_result=True)
        runs = self.call('GET', '/commits/'+commit+'/check-runs?per_page=100')
        if len(statuses) >= 100 or runs.get('total_count', 0) > 100:
            raise ValueError('check/status evidence capped; cannot qualify merge')
        latest = {}
        for row in sorted(statuses, key=lambda r: r.get('id', 0)):
            latest[row['context']] = row.get('state') == 'success'
        latest_runs = {}
        for row in sorted(runs.get('check_runs', []), key=lambda r: r.get('id', 0)):
            passed = row.get('status') == 'completed' and row.get('conclusion') == 'success' and row.get('head_sha') == commit
            name = row.get('name')
            # A successful status cannot mask a failing same-named check run.
            latest_runs[name] = passed
        for name, passed in latest_runs.items():
            latest[name] = latest.get(name, True) and passed
        if any(latest.get(name) is not True for name in names):
            raise ValueError('required commit checks are missing, pending or failed')

    def preflight(self, payload):
        self.identity()
        if payload.get('repository_id') != self.config['repository_id']:
            raise PermissionError('publication repository changed')
        if payload['operation'] == 'merge':
            pr = self.call('GET', '/pulls/'+str(payload['pr_number']))
            self.validate_pr(pr, payload['head_sha'])
            if pr.get('merged') or pr.get('state') != 'open' or pr.get('draft'):
                raise ValueError('PR is not an open reviewed merge candidate')
            if self.base() != payload['base_sha']:
                raise ValueError('base advanced after merge preparation; prepare a new reviewed merge')
            self.checks(payload['head_sha'])
        else:
            if self.base() != payload['base_sha']:
                raise ValueError('base advanced after preparation; no repository write attempted')
            refs = self.call('GET', '/git/matching-refs/heads/'+quote(payload['branch'], safe=''), list_result=True)
            if any(row.get('ref') == 'refs/heads/'+payload['branch'] for row in refs):
                raise ValueError('publication branch already exists; reconcile instead of overwriting')
            for item in payload['files']:
                authorize(self.site, 'deploy', path=item['path'])
                if item.get('content') is not None and git_blob(decode(item)) != item['sha']:
                    raise ValueError('publication content changed')

    def validate_pr(self, pr, head_sha):
        if pr.get('head', {}).get('sha') != head_sha or pr.get('base', {}).get('ref') != self.config['base_branch']:
            raise ValueError('PR head or base does not match approved publication')
        if any(pr.get(side, {}).get('repo', {}).get('id') != self.config['repository_id'] for side in ('head', 'base')):
            raise PermissionError('PR belongs to a different repository')

    def perform(self, payload, action_id):
        if payload['operation'] == 'merge':
            result = self.call('PUT', '/pulls/'+str(payload['pr_number'])+'/merge',
                               {'sha': payload['head_sha'], 'merge_method': 'squash'})
            if result.get('merged') is not True:
                raise ValueError('merge was not accepted')
            return {'kind': 'github_merge', 'status': 'accepted', 'repository_id': self.config['repository_id'],
                    'pr_number': payload['pr_number'], 'commit_sha': sha(result.get('sha'))}
        elements = []
        for item in payload['files']:
            if item['content'] is None:
                elements.append({'path': item['path'], 'mode': item['mode'], 'type': 'blob', 'sha': None})
                continue
            blob = self.call('POST', '/git/blobs', {'content': item['content'], 'encoding': item['encoding']})
            if blob.get('sha') != item['sha']:
                raise ValueError('uploaded blob hash mismatch')
            elements.append({'path': item['path'], 'mode': item['mode'], 'type': 'blob', 'sha': item['sha']})
        tree = self.call('POST', '/git/trees', {'base_tree': payload['base_tree'], 'tree': elements})
        commit = self.call('POST', '/git/commits', {'message': 'SEO '+action_id+'\n\nRequest: '+actions.digest(payload),
            'tree': sha(tree['sha']), 'parents': [payload['base_sha']]})
        head = sha(commit['sha'])
        self.call('POST', '/git/refs', {'ref': 'refs/heads/'+payload['branch'], 'sha': head})
        pr = self.call('POST', '/pulls', {'title': 'SEO: '+action_id, 'head': payload['branch'],
            'base': self.config['base_branch'], 'body': 'Exact approved site change. Request: '+actions.digest(payload)})
        self.validate_pr(pr, head)
        return {'kind': 'github_pull_request', 'status': 'accepted', 'repository_id': self.config['repository_id'],
                'head_sha': head, 'tree_sha': tree['sha'], 'pr_number': pr['number'], 'url': pr['html_url'],
                'deployed': False, 'branch': payload['branch']}


def decode(item):
    return item['content'].encode('utf-8') if item['encoding'] == 'utf-8' else base64.b64decode(item['content'], validate=True)


def prepare(root, action_id, task_id, *, media_ids=(), evidence, transport=request):
    site = load(root); authorize(site, 'deploy')
    row = json.loads(queue.item_path(root, task_id).read_text(encoding='utf-8')); queue.check_binding(row, site)
    if row['status'] not in {'applied', 'deployed_verified'} or row['site'] != site['domain']:
        raise ValueError('publication requires an exact approved/applied local queue item')
    client = GitHub(site, transport); client.identity(); base = client.base(); tree_sha, entries = client.tree(base)
    path = row['path']; authorize(site, 'deploy', path=path, url=row['url'])
    target = queue.target_path(root, path)
    if queue.digest(target.read_bytes()) != row['content_sha256'] or queue.digest(row['content'].encode()) != row['content_sha256']:
        raise ValueError('local content changed after approval')
    previous = entries.get(path)
    expected = git_blob(row['baseline'].encode()) if row['baseline'] is not None else None
    if (previous or {}).get('sha') != expected or previous and previous['mode'] not in {'100644', '100755'}:
        raise ValueError('remote content baseline conflicts with approved local baseline')
    files = [{'path': path, 'mode': previous['mode'] if previous else '100644', 'content': row['content'],
              'encoding': 'utf-8', 'sha': git_blob(row['content'].encode())}]
    if len(media_ids) > 10 or len(set(media_ids)) != len(media_ids):
        raise ValueError('bounded unique media IDs required')
    assets = []
    for identifier in media_ids:
        asset = media_assets.read(root, identifier); raw = media_assets.bytes_for(root, identifier)
        authorize(site, 'deploy', path=asset['path'], url=asset['public_url'])
        if asset['path'] in entries or any(f['path'] == asset['path'] for f in files):
            raise ValueError('media must use a new immutable path; existing assets are not overwritten')
        files.append({'path': asset['path'], 'mode': '100644', 'content': base64.b64encode(raw).decode('ascii'),
                      'encoding': 'base64', 'sha': git_blob(raw)})
        assets.append(asset)
    return actions.propose(root, action_id, 'repository', {'operation': 'publish', 'task_id': task_id,
        'repository_id': client.config['repository_id'], 'base_sha': base, 'base_tree': tree_sha,
        'branch': 'seo/'+action_id, 'files': files, 'media': assets, 'original_entries': entries}, evidence)


def apply(root, action_id, *, transport=request):
    return actions.execute(root, action_id, 'repository',
        lambda site, payload, identifier: GitHub(site, transport).perform(payload, identifier),
        preflight=lambda site, payload: GitHub(site, transport).preflight(payload))


def reconcile(root, action_id, *, transport=request):
    """Read-only proof of the exact branch, tree and PR; never replay uncertain POSTs."""
    site = load(root); client = GitHub(site, transport); client.identity()
    with transaction_lock(state_dir(root)/'remote-actions'):
        row = actions.read(root, action_id); payload = row['payload']
        if row['kind'] != 'repository' or row['site'] != site['domain'] or row['config_digest'] != actions.digest(site) or actions.fingerprint(row) != row['request_sha256']:
            raise PermissionError('reconciliation action/config mismatch')
        if row['state'] not in {'running', 'uncertain', 'succeeded'}:
            raise ValueError('reconciliation requires an attempted effect')
        if payload['operation'] == 'merge':
            pr = client.call('GET', '/pulls/'+str(payload['pr_number'])); client.validate_pr(pr, payload['head_sha'])
            if pr.get('merged') is not True:
                return {'state': 'uncertain', 'reason': 'merge not observed; no retry authorized'}
            receipt = {'kind': 'github_merge', 'status': 'accepted', 'repository_id': client.config['repository_id'],
                       'pr_number': payload['pr_number'], 'commit_sha': sha(pr['merge_commit_sha'])}
        else:
            head = sha(client.call('GET', '/git/ref/heads/'+quote(payload['branch'], safe=''))['object']['sha'])
            commit = client.call('GET', '/git/commits/'+head)
            if [p['sha'] for p in commit.get('parents', [])] != [payload['base_sha']] or commit.get('message') != 'SEO '+action_id+'\n\nRequest: '+actions.digest(payload):
                raise ValueError('branch does not prove this exact approved action')
            tree_sha, entries = client.tree(head); expected = dict(payload['original_entries'])
            for item in payload['files']:
                if item['content'] is None: expected.pop(item['path'], None)
                else: expected[item['path']] = {'type': 'blob', 'sha': item['sha'], 'mode': item['mode']}
            if entries != expected:
                raise ValueError('branch contains missing/extra/changed files')
            prs = client.call('GET', '/pulls?'+urlencode({'state': 'all', 'head': client.config['repository'].split('/')[0]+':'+payload['branch'],
                'base': client.config['base_branch'], 'per_page': 100}), list_result=True)
            if len(prs) != 1:
                return {'state': 'uncertain', 'reason': 'unique PR not observed; no repeat creation authorized'}
            pr = prs[0]; client.validate_pr(pr, head)
            receipt = {'kind': 'github_pull_request', 'status': 'accepted', 'repository_id': client.config['repository_id'],
                'pr_number': pr['number'], 'head_sha': head, 'tree_sha': tree_sha, 'url': pr['html_url'],
                'branch': payload['branch'], 'deployed': False}
        row.update(state='succeeded', receipt=receipt, reconciled_at=actions.stamp())
        atomic_json(actions.path_for(root, action_id), row)
        return {'state': 'succeeded', 'receipt': receipt}


def prepare_merge(root, action_id, publication_id, *, evidence, transport=request):
    site = load(root); authorize(site, 'merge'); original = actions.read(root, publication_id)
    check_original(original, site)
    client = GitHub(site, transport); client.identity(); receipt = original['receipt']
    pr = client.call('GET', '/pulls/'+str(receipt['pr_number'])); client.validate_pr(pr, receipt['head_sha'])
    client.checks(receipt['head_sha'])
    return actions.propose(root, action_id, 'repository', {'operation': 'merge',
        'repository_id': client.config['repository_id'], 'pr_number': receipt['pr_number'],
        'head_sha': receipt['head_sha'], 'base_sha': client.base()}, evidence)


def check_original(row, site):
    if row['kind'] != 'repository' or row['state'] != 'succeeded' or row['site'] != site['domain'] or row['config_digest'] != actions.digest(site) or actions.fingerprint(row) != row['request_sha256']:
        raise PermissionError('identified successful publication under unchanged policy required')


def deployment(root, publication_id, *, transport=request):
    site = load(root); row = actions.read(root, publication_id); check_original(row, site)
    client = GitHub(site, transport); client.identity(); receipt = row['receipt']
    pr = client.call('GET', '/pulls/'+str(receipt['pr_number'])); client.validate_pr(pr, receipt['head_sha'])
    if pr.get('merged') is not True:
        return {'state': 'awaiting_merge' if pr.get('state') == 'open' else 'closed_unmerged'}
    commit = sha(pr['merge_commit_sha'])
    deployments = client.call('GET', '/deployments?'+urlencode({'sha': commit, 'environment': client.config['environment'], 'per_page': 100}), list_result=True)
    candidates = [d for d in deployments if d.get('sha') == commit and d.get('environment') == client.config['environment']]
    if len(deployments) >= 100:
        return {'state': 'blocked', 'reason': 'deployment evidence capped'}
    if not candidates:
        return {'state': 'awaiting_deployment'}
    latest = max(candidates, key=lambda d: d['id'])
    statuses = client.call('GET', '/deployments/'+str(latest['id'])+'/statuses?per_page=1', list_result=True)
    if not statuses or statuses[0].get('state') != 'success':
        return {'state': 'awaiting_deployment', 'reason': (statuses[0].get('state') if statuses else 'missing_status')}
    environment_url = statuses[0].get('environment_url')
    if not environment_url:
        return {'state': 'blocked', 'reason': 'deployment is missing environment URL identity'}
    authorize(site, 'verify', url=environment_url)
    return {'state': 'deployed', 'identity': commit,
            'effect_receipt': 'github:'+client.config['repository']+':deployment:'+str(latest['id']),
            'rollback': 'seo.py publication rollback '+publication_id+' NEW_ID --evidence APPROVED_RECOVERY',
            'evidence': {'pr_number': receipt['pr_number'], 'environment': client.config['environment'],
                         'environment_url': environment_url, 'deployment_id': latest['id']}}


def prepare_rollback(root, original_id, new_id, *, evidence, transport=request):
    site = load(root); authorize(site, 'rollback')
    original = actions.read(root, original_id); check_original(original, site)
    if original['payload']['operation'] != 'publish':
        raise ValueError('rollback source must be the original publication')
    client = GitHub(site, transport); client.identity(); base = client.base(); tree_sha, entries = client.tree(base)
    task = json.loads(queue.item_path(root, original['payload']['task_id']).read_text(encoding='utf-8'))
    queue.check_binding(task, site)
    content_file = original['payload']['files'][0]; current = entries.get(content_file['path'])
    if not current or current['sha'] != content_file['sha']:
        raise ValueError('rollback would overwrite subsequent page edits')
    baseline = task['baseline']
    files = [{'path': content_file['path'], 'mode': current['mode'], 'content': baseline,
              'encoding': 'utf-8', 'sha': git_blob(baseline.encode()) if baseline is not None else None}]
    # Restore/remove only the original page. New immutable media stays in place;
    # never delete shared assets or reset a whole repository to an older commit.
    return actions.propose(root, new_id, 'repository', {'operation': 'rollback', 'task_id': task['id'],
        'repository_id': client.config['repository_id'], 'base_sha': base, 'base_tree': tree_sha,
        'branch': 'seo/'+new_id, 'files': files, 'media': [], 'original_entries': entries}, evidence)


def progress(root, task_id, plan, *, transport=request):
    site = load(root); cfg = site.get('deployment') or {}; identifier = task_id+'-repo'
    if not actions.path_for(root, identifier).exists():
        prepare(root, identifier, task_id, media_ids=plan.get('media_ids', []), evidence=plan['review']['evidence'], transport=transport)
    row = actions.read(root, identifier)
    if row['state'] == 'proposed':
        if cfg.get('auto_submit') is not True or not cfg.get('approval_ref'):
            return {'state': 'awaiting_repository_approval', 'action_id': identifier, 'digest': row['request_sha256']}
        actions.approve(root, identifier, row['request_sha256'], cfg['approval_ref'])
    effect = apply(root, identifier, transport=transport)
    if effect['state'] != 'succeeded':
        return {'state': effect['state'], 'reason': 'repository effect requires reconciliation', 'action_id': identifier}
    observed = deployment(root, identifier, transport=transport)
    if observed['state'] == 'awaiting_merge' and cfg.get('auto_merge') is True:
        merge_id = task_id+'-merge'
        if not actions.path_for(root, merge_id).exists():
            prepare_merge(root, merge_id, identifier, evidence=plan['review']['evidence'], transport=transport)
        merge_row = actions.read(root, merge_id)
        if merge_row['state'] == 'proposed':
            if not cfg.get('merge_approval_ref'):
                return {'state': 'awaiting_merge_approval', 'action_id': merge_id}
            actions.approve(root, merge_id, merge_row['request_sha256'], cfg['merge_approval_ref'])
        effect = apply(root, merge_id, transport=transport)
        if effect['state'] != 'succeeded':
            return {'state': effect['state'], 'reason': 'merge requires reconciliation', 'action_id': merge_id}
        observed = deployment(root, identifier, transport=transport)
    return observed


def main():
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument('--root', default='.')
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('id'); p.add_argument('--task', required=True); p.add_argument('--media', action='append', default=[]); p.add_argument('--evidence', required=True)
    p = sub.add_parser('approve'); p.add_argument('id'); p.add_argument('--digest', required=True); p.add_argument('--approval-ref', required=True)
    for name in ('apply', 'reconcile', 'status'):
        sub.add_parser(name).add_argument('id')
    for name in ('prepare-merge', 'rollback'):
        p = sub.add_parser(name); p.add_argument('original'); p.add_argument('id'); p.add_argument('--evidence', required=True)
    a = ap.parse_args()
    if a.command == 'prepare': result = prepare(a.root, a.id, a.task, media_ids=a.media, evidence=a.evidence)
    elif a.command == 'approve': result = actions.approve(a.root, a.id, a.digest, a.approval_ref)
    elif a.command == 'status': result = deployment(a.root, a.id)
    elif a.command == 'prepare-merge': result = prepare_merge(a.root, a.id, a.original, evidence=a.evidence)
    elif a.command == 'rollback': result = prepare_rollback(a.root, a.original, a.id, evidence=a.evidence)
    else: result = globals()[a.command](a.root, a.id)
    print(json.dumps(result, indent=2)); return 2 if result.get('state') in {'uncertain', 'blocked', 'partial'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
