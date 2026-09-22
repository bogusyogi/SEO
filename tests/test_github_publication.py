"""GitHub REST publication fixture with real queue/action persistence and simulated races."""
from __future__ import annotations
import base64
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'scripts'))
import content_queue as queue
import github_publication as gh
import media_assets
import remote_actions as actions
from seo_project import save_site
from test_portfolio_workflow import fixture_site,png

BASE='a'*40;TREE='b'*40;HEAD='c'*40;NEWTREE='d'*40;MERGE='e'*40


class API:
    def __init__(self):
        self.base=BASE;self.entries={'content/page.html':{'sha':gh.git_blob(b'old content'),'mode':'100644','type':'blob'},
                                    'content/other.html':{'sha':gh.git_blob(b'unrelated'),'mode':'100644','type':'blob'}}
        self.new_entries={};self.refs={};self.pr=None;self.calls=[];self.commit={}
        self.fail_after=None;self.check_state='success';self.deployments=[];self.statuses=[]
        self.repository_id=123;self.commit_statuses=[];self.check_runs=None

    def __call__(self,origin,method,path,**kwargs):
        assert origin=='https://api.github.com'
        assert kwargs['headers']['Authorization']=='Bearer fixture-token'
        body=kwargs.get('payload');path=path.removeprefix('/repos/owner/site')
        self.calls.append((method,path,copy.deepcopy(body)))
        if method=='GET' and path=='':return {'id':self.repository_id,'full_name':'owner/site'}
        if method=='GET' and path=='/git/ref/heads/main':return {'object':{'sha':self.base}}
        if method=='GET' and path.startswith('/git/matching-refs/'):
            return [{'ref':'refs/heads/'+key,'object':{'sha':value}} for key,value in self.refs.items()]
        if method=='GET' and path.startswith('/git/ref/heads/'):
            from urllib.parse import unquote
            return {'object':{'sha':self.refs[unquote(path.removeprefix('/git/ref/heads/'))]}}
        if method=='GET' and path.startswith('/git/commits/'):
            if path.endswith(HEAD):return self.commit
            return {'tree':{'sha':TREE}}
        if method=='GET' and path.startswith('/git/trees/'):
            entries=self.new_entries if NEWTREE in path else self.entries
            return {'truncated':False,'tree':[dict(v,path=k) for k,v in entries.items()]}
        if method=='POST' and path=='/git/blobs':
            raw=body['content'].encode() if body['encoding']=='utf-8' else base64.b64decode(body['content'])
            return {'sha':gh.git_blob(raw)}
        if method=='POST' and path=='/git/trees':
            self.new_entries=copy.deepcopy(self.entries)
            for row in body['tree']:
                if row['sha'] is None:self.new_entries.pop(row['path'],None)
                else:self.new_entries[row['path']]={k:row[k] for k in ('sha','mode','type')}
            return {'sha':NEWTREE}
        if method=='POST' and path=='/git/commits':
            self.commit={'sha':HEAD,'tree':{'sha':NEWTREE},'message':body['message'],'parents':[{'sha':x} for x in body['parents']]}
            return self.commit
        if method=='POST' and path=='/git/refs':
            key=body['ref'].removeprefix('refs/heads/')
            if key in self.refs:raise RuntimeError('HTTP 422')
            self.refs[key]=body['sha'];return {'object':{'sha':body['sha']}}
        if method=='POST' and path=='/pulls':
            self.pr={'number':7,'html_url':'https://github.com/owner/site/pull/7','state':'open','merged':False,'draft':False,
                'head':{'sha':HEAD,'repo':{'id':123}},'base':{'ref':'main','repo':{'id':123}}}
            if self.fail_after=='create':raise TimeoutError('success at remote; response was lost')
            return self.pr
        if method=='GET' and path.startswith('/pulls?'):return [self.pr] if self.pr else []
        if method=='GET' and path=='/pulls/7':return self.pr
        if method=='GET' and '/statuses?' in path and path.startswith('/commits/'):
            return self.commit_statuses
        if method=='GET' and '/check-runs?' in path:
            return self.check_runs or {'total_count':1,'check_runs':[{'id':10,'name':'build','head_sha':HEAD,
                'status':'completed','conclusion':self.check_state}]}
        if method=='PUT' and path=='/pulls/7/merge':
            if body['sha']!=self.pr['head']['sha']:raise RuntimeError('HTTP 409')
            self.pr.update(merged=True,state='closed',merge_commit_sha=MERGE)
            self.base=MERGE;self.entries=copy.deepcopy(self.new_entries)
            if self.fail_after=='merge':raise TimeoutError('merge success with lost response')
            return {'merged':True,'sha':MERGE}
        if method=='GET' and path.startswith('/deployments?'):return self.deployments
        if method=='GET' and path.startswith('/deployments/') and '/statuses?' in path:return self.statuses[:1]
        raise AssertionError((method,path,body))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.site=fixture_site(self.root)
        self.site['deployment']={'provider':'github','repository':'owner/site','repository_id':123,
            'base_branch':'main','environment':'production','token_env':'SEO_TEST_TOKEN','required_checks':['build'],
            'auto_submit':True,'approval_ref':'operator-repository'}
        save_site(self.site,self.root)
        patcher=patch.dict(os.environ,{'SEO_TEST_TOKEN':'fixture-token'});patcher.start();self.addCleanup(patcher.stop)
        queue.propose(self.root,'page',path='content/page.html',content='new reviewed content',url='https://example.com/page',kind='metadata',evidence='review')
        queue.approve(self.root,'page',content_sha256=queue.digest(b'new reviewed content'),approval_ref='operator');queue.apply(self.root,'page')
        self.api=API()

    def prepare(self):return gh.prepare(self.root,'pub','page',evidence='approved-review',transport=self.api)
    def publish(self):
        proposal=self.prepare();actions.approve(self.root,'pub',proposal['request_sha256'],'operator')
        return gh.apply(self.root,'pub',transport=self.api)

    def merge(self):
        proposal=gh.prepare_merge(self.root,'merge','pub',evidence='passing build',transport=self.api)
        actions.approve(self.root,'merge',proposal['request_sha256'],'operator-merge')
        return gh.apply(self.root,'merge',transport=self.api)

    def test_real_protocol_creates_scoped_branch_pr_not_live_deployment(self):
        result=self.publish();self.assertEqual(result['state'],'succeeded')
        self.assertFalse(result['receipt']['deployed']);self.assertEqual(self.api.base,BASE)
        self.assertEqual(self.api.new_entries['content/other.html'],self.api.entries['content/other.html'])
        self.assertFalse(any(method=='PATCH' and '/git/refs' in path for method,path,_ in self.api.calls))

    def test_repeat_returns_receipt_without_another_network_write(self):
        self.publish();writes=sum(c[0]!='GET' for c in self.api.calls)
        result=gh.apply(self.root,'pub',transport=self.api)
        self.assertTrue(result['duplicate']);self.assertEqual(sum(c[0]!='GET' for c in self.api.calls),writes)

    def test_base_concurrency_change_blocks_before_first_write(self):
        proposal=self.prepare();actions.approve(self.root,'pub',proposal['request_sha256'],'operator')
        self.api.base='f'*40
        with self.assertRaises(ValueError):gh.apply(self.root,'pub',transport=self.api)
        self.assertFalse(any(c[0]!='GET' for c in self.api.calls))

    def test_remote_content_conflict_rejects_local_baseline(self):
        self.api.entries['content/page.html']['sha']='f'*40
        with self.assertRaises(ValueError):self.prepare()

    def test_branch_collision_never_overwrites_other_writer(self):
        proposal=self.prepare();actions.approve(self.root,'pub',proposal['request_sha256'],'operator')
        self.api.refs['seo/pub']='f'*40
        with self.assertRaises(ValueError):gh.apply(self.root,'pub',transport=self.api)
        self.assertEqual(self.api.refs['seo/pub'],'f'*40)

    def test_timeout_after_remote_success_is_reconciled_not_replayed(self):
        self.api.fail_after='create';result=self.publish();self.assertEqual(result['state'],'uncertain')
        writes=sum(c[0]!='GET' for c in self.api.calls)
        self.assertEqual(gh.apply(self.root,'pub',transport=self.api)['state'],'uncertain')
        self.assertEqual(sum(c[0]!='GET' for c in self.api.calls),writes)
        result=gh.reconcile(self.root,'pub',transport=self.api)
        self.assertEqual(result['state'],'succeeded');self.assertEqual(sum(c[0]!='GET' for c in self.api.calls),writes)

    def test_reconciliation_rejects_extra_remote_edits(self):
        self.api.fail_after='create';self.publish()
        self.api.new_entries['content/extra.html']={'type':'blob','mode':'100644','sha':'f'*40}
        with self.assertRaises(ValueError):gh.reconcile(self.root,'pub',transport=self.api)

    def test_missing_pr_remains_uncertain_without_creating_duplicate(self):
        self.api.fail_after='create';self.publish();self.api.pr=None
        result=gh.reconcile(self.root,'pub',transport=self.api)
        self.assertEqual(result['state'],'uncertain');self.assertIn('no repeat',result['reason'])

    def test_wrong_repository_id_fails_closed(self):
        self.api.repository_id=999
        with self.assertRaises(PermissionError):self.prepare()

    def test_tampered_content_and_config_cannot_reuse_approval(self):
        proposal=self.prepare();actions.approve(self.root,'pub',proposal['request_sha256'],'operator')
        self.site['deployment']['repository_id']=999;save_site(self.site,self.root)
        with self.assertRaises(PermissionError):gh.apply(self.root,'pub',transport=self.api)

    def test_media_and_page_are_one_git_tree_and_assets_are_immutable(self):
        source=self.root/'test.png';source.write_bytes(png())
        media_assets.stage(self.root,'hero',source,path='public/assets/hero.png',public_url='https://example.com/assets/hero.png',alt='actual diagram',license_ref='original')
        proposal=gh.prepare(self.root,'pub','page',media_ids=['hero'],evidence='review',transport=self.api)
        actions.approve(self.root,'pub',proposal['request_sha256'],'operator');gh.apply(self.root,'pub',transport=self.api)
        trees=[c for c in self.api.calls if c[:2]==('POST','/git/trees')]
        self.assertEqual(len(trees),1);self.assertEqual(len(trees[0][2]['tree']),2)
        self.assertEqual(self.api.new_entries['public/assets/hero.png']['sha'],gh.git_blob(png()))
        self.api.entries['public/assets/hero.png']={'sha':'f'*40,'type':'blob','mode':'100644'}
        with self.assertRaises(ValueError):gh.prepare(self.root,'other','page',media_ids=['hero'],evidence='review',transport=self.api)

    def test_merge_requires_checks_and_frozen_head(self):
        self.publish();self.api.check_state='failure'
        with self.assertRaises(ValueError):self.merge()
        self.api.check_state='success';self.api.pr['head']['sha']='f'*40
        with self.assertRaises(ValueError):self.merge()

    def test_pending_and_neutral_checks_do_not_authorize_merge(self):
        self.publish()
        for state in ['neutral','skipped','timed_out','cancelled']:
            self.api.check_state=state
            with self.assertRaises(ValueError):gh.prepare_merge(self.root,'merge','pub',evidence='review',transport=self.api)

    def test_missing_required_checks_and_capped_lists_are_not_green(self):
        self.publish();self.api.check_runs={'total_count':101,'check_runs':[]}
        with self.assertRaises(ValueError):self.merge()
        self.api.check_runs={'total_count':0,'check_runs':[]}
        with self.assertRaises(ValueError):self.merge()

    def test_successful_merge_still_is_not_deployment(self):
        self.publish();self.assertEqual(self.merge()['state'],'succeeded')
        self.assertEqual(gh.deployment(self.root,'pub',transport=self.api)['state'],'awaiting_deployment')

    def test_lost_merge_response_can_be_reconciled(self):
        self.publish();self.api.fail_after='merge';self.assertEqual(self.merge()['state'],'uncertain')
        self.assertEqual(gh.reconcile(self.root,'merge',transport=self.api)['state'],'succeeded')

    def test_deployment_requires_exact_commit_environment_and_latest_status(self):
        self.publish();self.merge()
        self.api.deployments=[{'id':1,'sha':'f'*40,'environment':'production'},{'id':2,'sha':MERGE,'environment':'preview'}]
        self.api.statuses=[{'state':'success','environment_url':'https://example.com/'}]
        self.assertEqual(gh.deployment(self.root,'pub',transport=self.api)['state'],'awaiting_deployment')
        self.api.deployments.append({'id':3,'sha':MERGE,'environment':'production'})
        self.api.statuses=[{'state':'failure','environment_url':'https://example.com/'},{'state':'success','environment_url':'https://example.com/'}]
        self.assertEqual(gh.deployment(self.root,'pub',transport=self.api)['state'],'awaiting_deployment')
        self.api.statuses=[{'state':'success','environment_url':'https://example.com/'}]
        self.assertEqual(gh.deployment(self.root,'pub',transport=self.api)['state'],'deployed')

    def test_deployment_wrong_host_is_not_site_success(self):
        self.publish();self.merge();self.api.deployments=[{'id':3,'sha':MERGE,'environment':'production'}]
        self.api.statuses=[{'state':'success','environment_url':'https://another.com/'}]
        with self.assertRaises(PermissionError):gh.deployment(self.root,'pub',transport=self.api)

    def test_scoped_rollback_preserves_unrelated_edits(self):
        self.publish();self.merge();self.api.entries['content/other.html']['sha']=gh.git_blob(b'new unrelated change')
        proposal=gh.prepare_rollback(self.root,'pub','restore',evidence='operator recovery',transport=self.api)
        actions.approve(self.root,'restore',proposal['request_sha256'],'operator');result=gh.apply(self.root,'restore',transport=self.api)
        self.assertEqual(result['state'],'succeeded')
        self.assertEqual(self.api.new_entries['content/page.html']['sha'],gh.git_blob(b'old content'))
        self.assertEqual(self.api.new_entries['content/other.html']['sha'],gh.git_blob(b'new unrelated change'))

    def test_rollback_rejects_concurrent_page_change(self):
        self.publish();self.merge();self.api.entries['content/page.html']['sha']=gh.git_blob(b'new unrelated page edit')
        with self.assertRaises(ValueError):gh.prepare_rollback(self.root,'pub','restore',evidence='operator recovery',transport=self.api)

    def test_progress_runs_approved_route_and_waits_for_merge(self):
        result=gh.progress(self.root,'page',{'review':{'evidence':'review'}},transport=self.api)
        self.assertEqual(result['state'],'awaiting_merge');self.assertEqual(self.api.base,BASE)

    def test_latest_check_rerun_can_recover_but_cannot_hide_failing_status(self):
        self.publish()
        self.api.check_runs={'total_count':2,'check_runs':[
            {'id':1,'name':'build','head_sha':HEAD,'status':'completed','conclusion':'failure'},
            {'id':2,'name':'build','head_sha':HEAD,'status':'completed','conclusion':'success'}]}
        client=gh.GitHub(self.site,self.api);client.checks(HEAD)
        self.api.commit_statuses=[{'id':3,'context':'build','state':'failure'}]
        with self.assertRaises(ValueError):client.checks(HEAD)

    def test_read_only_policy_cannot_gain_repo_write_through_remote_actions(self):
        self.site['policy']['mode']='read_only';save_site(self.site,self.root)
        with self.assertRaises(PermissionError):self.prepare()
        self.assertFalse(any(c[0]!='GET' for c in self.api.calls))

    def test_automatic_merge_is_separate_from_submission_authority(self):
        result=gh.progress(self.root,'page',{'review':{'evidence':'review'}},transport=self.api)
        self.assertEqual(result['state'],'awaiting_merge')
        self.assertFalse(any(c[0]=='PUT' for c in self.api.calls))



if __name__=='__main__':unittest.main()
