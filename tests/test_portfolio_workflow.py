"""Portfolio/workflow regressions using real local queues, ledger writes and host processes."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'scripts'))
import agent_host
import content_queue as queue
import media_assets
import outcome_jobs
import portfolio
import public_verify
import seo_runner
import seo_workflow as workflow
from seo_project import setup_project, save_site
from seo_state import atomic_json, state_dir
from measurement_scope import gsc_host_filter

NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def fixture_site(root, domain='example.com'):
    site = setup_project(root, domain=domain, market='IN', language='en', gsc_property='sc-domain:'+domain)
    site['policy'] = {'mode': 'approved', 'approval_ref': 'operator-policy',
        'allowed_actions': ['metadata', 'draft', 'publish', 'rollback', 'media', 'deploy', 'merge'],
        'write_prefixes': ['content', 'public/assets']}
    site['workflow'] = {'enabled': True, 'approval_ref': 'operator-workflow', 'auto_approve_kinds': ['metadata', 'content'],
                        'max_tasks_per_tick': 3}
    site['author_facts'] = {'founder': {'name': 'Actual founder', 'evidence': 'operator-provided'}}
    save_site(site, root)
    (root/'content').mkdir(exist_ok=True); (root/'content/page.html').write_text('old content', encoding='utf-8')
    return site


def measure(root, target, window, *, failed=False):
    domain = target.split('/')[2]
    return {'site': domain, 'target': target, 'lane': 'gsc', 'status': 'failed' if failed else 'ok',
        'collected_at': NOW.isoformat(), 'collection_route': 'standalone_direct', 'hostname_scope': [domain],
        'data': {'property': 'sc-domain:'+domain, 'date_range': window, 'search_type': 'web', 'dimensions': ['query'],
                 'filters': [gsc_host_filter([domain]), {'dimension': 'page', 'operator': 'equals', 'expression': target}],
                 'aggregation_type': 'byPage', 'data_state': 'final', 'time_zone': 'America/Los_Angeles',
                 'aggregate': {'clicks': 5, 'impressions': 200, 'ctr': 2.5, 'position': 10}}}


def png(width=2, height=3):
    import zlib
    def chunk(name, data):
        return struct.pack('>I', len(data))+name+data+struct.pack('>I', zlib.crc32(name+data))
    header = struct.pack('>II', width, height)+b'\x08\x02\x00\x00\x00'
    pixels = (b'\x00'+b'\x80\x80\x80'*width)*height
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',header)+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')



class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'a'; self.site = fixture_site(self.root)
        self.task = workflow.enqueue(self.root, target='https://example.com/page', kind='metadata',
                                     issue='missing_title', evidence='measured audit', now=NOW)['id']
        self.plan = {'schema_version': 1, 'task_id': self.task, 'decision': 'change', 'reason': 'Repair observed title',
            'path': 'content/page.html', 'content': '<html><head><title>Accurate title</title><link rel="canonical" href="https://example.com/page"></head><body>A new verified sentence.</body></html>',
            'expected_text': 'A new verified sentence.',
            'review': {'facts': 'pass', 'intent': 'pass', 'links': 'pass', 'preview': 'pass', 'evidence': 'host-reviewed-preview'}}

    def advance(self, **kwargs):
        defaults = {'now': NOW, 'host': lambda *args: copy.deepcopy(self.plan), 'measurer': measure}
        defaults.update(kwargs); return workflow.advance(self.root, self.task, **defaults)

    def test_duplicate_enqueue_has_one_intervention(self):
        duplicate = workflow.enqueue(self.root, target='https://example.com/page', kind='metadata', issue='missing_title', evidence='new observation', now=NOW)
        self.assertTrue(duplicate['duplicate']); self.assertEqual(duplicate['id'], self.task)
        self.assertEqual(len(workflow.ops.load_state(workflow.ledger(self.root))['interventions']), 1)

    def test_local_application_does_not_claim_deployment(self):
        result = self.advance()
        self.assertEqual(result['stage'], 'applied'); self.assertIn('not live', result['blocker'])
        self.assertIn('A new verified sentence', (self.root/'content/page.html').read_text())
        row = workflow.find(workflow.ops.load_state(workflow.ledger(self.root)), self.task)
        self.assertIsNone(row['deployment']); self.assertEqual(row['outcomes'], [])

    def test_repeat_does_not_reauthor_or_reapply(self):
        self.advance()
        result = self.advance(host=lambda *a: self.fail('host must not run twice'))
        self.assertEqual(result['stage'], 'applied')
        self.assertEqual(result['host_attempts'], 1)

    def test_no_standing_approval_stops_before_apply(self):
        self.site['workflow']['auto_approve_kinds'] = []; save_site(self.site, self.root)
        workflow.replan(self.root, self.task, 'operator accepts config change')
        result = self.advance()
        self.assertEqual(result['stage'], 'prepared'); self.assertEqual((self.root/'content/page.html').read_text(), 'old content')
        queued = json.loads(queue.item_path(self.root,self.task).read_text())
        queue.approve(self.root, self.task, content_sha256=queued['content_sha256'], approval_ref='exact operator approval')
        self.assertEqual(self.advance()['stage'], 'applied')

    def test_missing_ga4_does_not_block_local_technical_work(self):
        self.assertIsNone(self.site['properties']['ga4'])
        self.assertEqual(self.advance()['stage'], 'applied')

    def test_failed_gsc_baseline_does_not_block_local_repair(self):
        result = self.advance(measurer=lambda *args: measure(*args, failed=True))
        self.assertEqual(result['stage'], 'applied')

    def test_public_check_required_before_scheduling_outcome(self):
        deployed = lambda *a: {'state': 'deployed', 'identity': 'revision1', 'effect_receipt': 'observed-platform-receipt', 'rollback': 'scoped-restore'}
        result = self.advance(publisher=deployed, verifier=lambda *a: {'passed': False})
        self.assertEqual(result['stage'], 'deployed'); self.assertEqual(result['blocker'], 'public_verification_failed')
        row = workflow.find(workflow.ops.load_state(workflow.ledger(self.root)),self.task)
        self.assertNotIn('outcome_job', row['workflow'])

    def test_end_to_end_resume_and_actual_due_followup(self):
        calls = []
        def measurement(*args): calls.append(args[-1]); return measure(*args)
        deployed = lambda *a: {'state': 'deployed', 'identity': 'revision1', 'effect_receipt': 'observed-platform-receipt', 'rollback': 'scoped-restore'}
        result = self.advance(measurer=measurement, publisher=deployed,
            verifier=lambda *a: public_verify.verify(*a, fetcher=lambda url: {'url': url, 'status': 200, 'body': self.plan['content'], 'headers': {}}))
        self.assertEqual(result['stage'], 'awaiting_outcome'); self.assertEqual(len(calls),1)
        later = self.advance(now=NOW+timedelta(days=10), measurer=measurement)
        self.assertEqual(later['stage'], 'awaiting_outcome'); self.assertEqual(len(calls),1)
        due = self.advance(now=NOW+timedelta(days=34), measurer=measurement,
                           host=lambda *a:self.fail('no reauthoring'), publisher=lambda *a:self.fail('no republication'))
        self.assertEqual(due['stage'], 'done'); self.assertEqual(len(calls),2)
        row = workflow.find(workflow.ops.load_state(workflow.ledger(self.root)),self.task)
        self.assertEqual(row['outcomes'][0]['verdict'], 'inconclusive')
        self.assertTrue(Path(row['outcomes'][0]['evidence']).is_file())
        self.advance(now=NOW+timedelta(days=35), measurer=lambda *a:self.fail('duplicate outcome collection'))

    def test_fake_deployment_success_without_effect_receipt_rejected(self):
        result = self.advance(publisher=lambda *a: {'state':'deployed'})
        self.assertEqual(result['stage'], 'applied'); self.assertEqual(result['blocker'], 'ValueError')

    def test_retain_is_valid_and_does_not_write_or_loop(self):
        result = self.advance(host=lambda *a: {'schema_version':1,'task_id':self.task,'decision':'retain','reason':'current page meets intent'})
        self.assertEqual(result['stage'],'retained'); self.assertEqual((self.root/'content/page.html').read_text(),'old content')
        self.advance(host=lambda *a: self.fail('retained item must not regenerate'))

    def test_defer_has_bounded_retry_date(self):
        response = {'schema_version':1,'task_id':self.task,'decision':'defer','reason':'original research unavailable','next_review_days':7}
        self.assertEqual(self.advance(host=lambda *a:response)['stage'],'deferred')
        self.assertEqual(self.advance(now=NOW+timedelta(days=1),host=lambda *a:self.fail())['stage'],'deferred')
        self.assertEqual(self.advance(now=NOW+timedelta(days=8))['stage'],'applied')

    def test_host_failure_is_bounded_and_does_not_leak_exception(self):
        def broken(*a): raise RuntimeError('SECRET-TOKEN-in-sdk-exception')
        for n in range(4): result=self.advance(now=NOW+timedelta(hours=n),host=broken)
        self.assertEqual(result['host_attempts'],3)
        self.assertIn('budget_exhausted',result['blocker'])
        self.assertNotIn('SECRET-TOKEN',workflow.ledger(self.root).read_text())

    def test_configuration_drift_requires_explicit_replan(self):
        self.site['policy']['write_prefixes']=['other']; save_site(self.site,self.root)
        result=self.advance(); self.assertEqual(result['blocker'],'PermissionError')
        self.assertFalse(queue.item_path(self.root,self.task).exists())

    def test_technical_only_prohibits_editorial_not_metadata(self):
        other=Path(self.temp.name)/'restricted'; fixture_site(other,'stunningstrangers.com')
        with self.assertRaises(PermissionError):
            workflow.enqueue(other,target='https://stunningstrangers.com/a',kind='content',issue='new blog',evidence='x')
        row=workflow.enqueue(other,target='https://stunningstrangers.com/a',kind='metadata',issue='title',evidence='x')
        self.assertEqual(row['stage'],'needs_plan')

    def test_outside_site_target_never_enqueued(self):
        for url in ['https://example.com.evil.test/a','https://other.example.com/a','https://example.com/a?x=1','https://user:password@example.com/a']:
            with self.assertRaises((ValueError,PermissionError)):
                workflow.enqueue(self.root,target=url,kind='metadata',issue='title',evidence='x')

    def test_host_cannot_smuggle_policy_commands_or_approval(self):
        for key in ['policy','command','approval_ref','deployed']:
            plan=copy.deepcopy(self.plan);plan[key]='malicious instruction'
            with self.assertRaises(ValueError): workflow.validate_plan(self.root,self.row(),plan,now=NOW)

    def row(self): return workflow.find(workflow.ops.load_state(workflow.ledger(self.root)),self.task)

    def test_plan_identity_review_and_assertion_are_required(self):
        for key,value in [('task_id','different'),('review',{}),('expected_text','not in approved content'),('path','../elsewhere')]:
            plan=copy.deepcopy(self.plan); plan[key]=value
            with self.assertRaises((ValueError,PermissionError)): workflow.validate_plan(self.root,self.row(),plan,now=NOW)

    def test_host_request_does_not_export_tokens_or_authority(self):
        self.site['cms']={'token_env':'PRIVATE_TOKEN','unexpected_secret':'SECRET'};save_site(self.site,self.root)
        text=json.dumps(workflow.host_request(self.root,self.row()))
        for word in ['PRIVATE_TOKEN','SECRET','operator-policy','operator-workflow']:self.assertNotIn(word,text)

    def test_declared_editorial_author_and_topic_ownership_are_enforced(self):
        task=workflow.enqueue(self.root,target='https://example.com/new',kind='content',issue='new page',evidence='x')['id']
        row=workflow.find(workflow.ops.load_state(workflow.ledger(self.root)),task)
        plan=copy.deepcopy(self.plan);plan['task_id']=task
        with self.assertRaises(ValueError):workflow.validate_plan(self.root,row,plan,now=NOW)
        plan['editorial']={'author_id':'founder','intent':'voice input','information_gain':'documented original capability',
            'sources':[{'url':'https://example.org/source','checked_at':NOW.isoformat(),'supports':'verified feature'}],
            'claims':[{'claim':'feature','source':'https://example.org/source','state':'approved','use_in_output':True}]}
        workflow.validate_plan(self.root,row,plan,now=NOW)
        self.site['topic_map']={'voice input':'https://example.com/other'};save_site(self.site,self.root)
        with self.assertRaises(ValueError):workflow.validate_plan(self.root,row,plan,now=NOW)

    def test_invalid_or_stale_claim_sources_rejected(self):
        task=workflow.enqueue(self.root,target='https://example.com/new',kind='content',issue='new',evidence='x')['id']
        row=workflow.find(workflow.ops.load_state(workflow.ledger(self.root)),task)
        plan=copy.deepcopy(self.plan); plan['task_id']=task
        plan['editorial']={'author_id':'founder','intent':'new intent','information_gain':'original facts',
            'sources':[{'url':'https://example.org/source','checked_at':(NOW-timedelta(days=91)).isoformat(),'supports':'feature'}]}
        with self.assertRaises(ValueError):workflow.validate_plan(self.root,row,plan,now=NOW)
        plan['editorial']['sources'][0]['checked_at']=NOW.isoformat()
        plan['editorial']['claims']=[{'claim':'invented claim','source':'https://example.org/unverified','state':'approved','use_in_output':True}]
        with self.assertRaises(ValueError):workflow.validate_plan(self.root,row,plan,now=NOW)

    def test_blocked_item_does_not_starve_other_work(self):
        self.site['workflow']['max_tasks_per_tick']=1;save_site(self.site,self.root)
        workflow.replan(self.root,self.task,'config')
        other=workflow.enqueue(self.root,target='https://example.com/b',kind='metadata',issue='other',evidence='x',now=NOW+timedelta(seconds=1))['id']
        a=workflow.tick(self.root,now=NOW,host=lambda *a:copy.deepcopy(self.plan),measurer=measure)
        b=workflow.tick(self.root,now=NOW+timedelta(seconds=2),host=lambda *a: {'schema_version':1,'task_id':other,'decision':'retain','reason':'no change justified'})
        self.assertEqual(a['tasks'][0]['id'],self.task);self.assertEqual(b['tasks'][0]['id'],other)

    def test_runner_executes_workflow_without_collection_schedule(self):
        with patch('seo_workflow.tick',return_value={'status':'ok','tasks':[]}) as tick:
            result=seo_runner.tick(self.root,now=NOW.timestamp())
        tick.assert_called_once();self.assertEqual(result['workflow']['status'],'ok')

    def test_manual_request_submit_uses_same_executor(self):
        accepted=workflow.accept_plan(self.root,self.task,self.plan,now=NOW)
        self.assertEqual(accepted['stage'],'prepared')
        result=self.advance(host=lambda *a:self.fail('already prepared'))
        self.assertEqual(result['stage'],'applied')

    def test_crash_after_proposal_persistence_resumes_exact_plan_without_reauthoring(self):
        original = queue.propose
        def crash(*args, **kwargs):
            original(*args, **kwargs)
            raise KeyboardInterrupt('simulated process death')
        with patch.object(queue, 'propose', side_effect=crash):
            with self.assertRaises(KeyboardInterrupt): self.advance()
        self.assertEqual(self.row()['workflow']['stage'], 'plan_ready')
        result = self.advance(host=lambda *a: self.fail('persisted plan must be reused'))
        self.assertEqual(result['stage'], 'applied')
        self.assertEqual(result['host_attempts'], 1)

    def test_workflow_plan_tamper_is_rejected_on_resume(self):
        self.advance()
        path = workflow.ledger(self.root); state = workflow.ops.load_state(path)
        workflow.find(state, self.task)['workflow']['plan']['expected_text'] = 'Accurate title'
        workflow.ops.save_state(path, state)
        self.assertEqual(self.advance()['blocker'], 'PermissionError')

    def test_failed_followup_retries_without_republishing(self):
        deployed = lambda *a: {'state': 'deployed', 'identity': 'revision1', 'effect_receipt': 'real receipt', 'rollback': 'scoped restore'}
        self.advance(publisher=deployed, verifier=lambda *a:{'passed':True})
        failed = self.advance(now=NOW+timedelta(days=34), measurer=lambda *a:measure(*a,failed=True))
        self.assertEqual(failed['stage'], 'awaiting_outcome')
        self.assertIn('retry scheduled', failed['blocker'])
        recovered = self.advance(now=NOW+timedelta(days=36), measurer=measure,
                                publisher=lambda *a:self.fail('must not republish'))
        self.assertEqual(recovered['stage'], 'done')
        self.assertEqual(self.row()['workflow']['outcome_attempts'], 2)

    def test_retained_task_can_be_reviewed_after_its_due_date(self):
        self.advance(host=lambda *a:{'schema_version':1,'task_id':self.task,'decision':'retain','reason':'not needed','next_review_days':7})
        result = self.advance(now=NOW+timedelta(days=8))
        self.assertEqual(result['stage'], 'applied')

    def test_completed_issue_gets_a_new_action_identity_if_it_recurs(self):
        state=workflow.ops.load_state(workflow.ledger(self.root));workflow.find(state,self.task)['workflow']['stage']='done'
        workflow.ops.save_state(workflow.ledger(self.root),state)
        new=workflow.enqueue(self.root,target='https://example.com/page',kind='metadata',issue='missing_title',evidence='new regression',now=NOW+timedelta(days=40))
        self.assertNotEqual(new['id'],self.task);self.assertFalse(new['duplicate'])
        repeated=workflow.enqueue(self.root,target='https://example.com/page',kind='metadata',issue='missing_title',evidence='same regression',now=NOW+timedelta(days=41))
        self.assertEqual(repeated['id'],new['id']);self.assertTrue(repeated['duplicate'])

    def test_sync_reads_all_targets_and_warnings_not_display_truncation(self):
        targets=['https://example.com/page'+str(i) for i in range(12)]
        envelope={'site':'example.com','lane':'audit','status':'ok','collected_at':NOW.isoformat(),
            'data':{'severity':{'errors':['missing_title'],'warnings':['missing_canonical','broken_internal_links']},
                    'issues':{'missing_title':targets,'missing_canonical':['https://example.com/other'],
                              'broken_internal_links':['[404] https://example.com/broken (from 3 pages)']}}}
        atomic_json(state_dir(self.root)/'audit'/'snapshot.json',envelope)
        result=workflow.sync(self.root,now=NOW)
        self.assertEqual(result['candidates_discovered'],14)
        self.assertEqual(len(result['candidates']),14)
        state=workflow.ops.load_state(workflow.ledger(self.root))
        self.assertIn('https://example.com/broken',[r['target'] for r in state['interventions']])



class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        fixture_site(self.root/'a');fixture_site(self.root/'b','other.example')
        self.path=self.root/'portfolio.json';atomic_json(self.path,{'roots':['a','b']})

    def test_discovery_finds_all_configured_sites_without_secrets(self):
        (self.root/'a/.env').write_text('PRIVATE=SECRET')
        result=portfolio.discover([self.root]);self.assertEqual(len(result['roots']),2)
        self.assertNotIn('SECRET',json.dumps(result));self.assertEqual(result['status'],'ok')

    def test_inaccessible_root_is_not_an_empty_complete_inventory(self):
        result=portfolio.discover([self.root/'missing']);self.assertEqual(result['status'],'partial')

    def test_discovery_cap_cannot_silently_claim_complete(self):
        self.assertEqual(portfolio.discover([self.root],max_directories=1)['status'],'partial')

    def test_duplicate_alias_and_domain_workspaces_rejected(self):
        for values in [['a','a/../a'],['a','c']]:
            if values[1]=='c':fixture_site(self.root/'c')
            atomic_json(self.path,{'roots':values})
            with self.assertRaises(ValueError):portfolio.roots_from(self.path)

    def test_one_broken_site_does_not_stop_other_site_tick(self):
        atomic_json(self.path,{'roots':['missing','a']})
        with patch.object(seo_runner,'tick',side_effect=lambda root: (_ for _ in ()).throw(ValueError('bad')) if root.name=='missing' else {'status':'ok','site':'example.com'}):
            result=seo_runner.portfolio(self.path)
        self.assertEqual(result['status'],'partial');self.assertEqual(result['sites'][1]['status'],'ok')
        self.assertTrue((self.root/'portfolio.report.json').is_file())

    def test_status_never_calls_configured_properties_authenticated(self):
        result=portfolio.inventory(self.path);a=result['sites'][0]
        self.assertTrue(a['properties']['gsc']['configured']);self.assertEqual(a['properties']['gsc']['last_collection'],'missing')
        self.assertIn('not authenticated',a['qualification'])


class HostTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def invoke(self,code,timeout=2):
        script=self.root/'host.py';script.write_text(code)
        return agent_host.invoke(self.root,{'argv':[sys.executable,str(script)],'approval_ref':'operator','timeout_seconds':timeout},{'task_id':'x'})

    def test_real_subprocess_json_protocol_and_minimal_env(self):
        with patch.dict(os.environ,{'CMS_SECRET_SENTINEL':'PRIVATE'}):
            result=self.invoke("import json,sys,os; x=json.load(sys.stdin); print(json.dumps({'id':x['task_id'],'leaked':'CMS_SECRET_SENTINEL' in os.environ}))")
        self.assertEqual(result,{'id':'x','leaked':False})

    def test_timeout_is_bounded(self):
        with self.assertRaises(TimeoutError):self.invoke('import time;time.sleep(5)',timeout=1)

    def test_invalid_json_and_nonobject_output_rejected(self):
        for code in ["print('no json')","print('[]')"]:
            with self.assertRaises(ValueError):self.invoke(code)

    def test_output_cap_is_enforced(self):
        with self.assertRaises(ValueError):self.invoke("print('x'*3000000)")

    def test_host_not_invoked_without_operator_argv_authority(self):
        with self.assertRaises(ValueError):agent_host.invoke(self.root,{'argv':['python','-c','print(1)']},{})


class MediaAndPublicTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        fixture_site(self.root);source=self.root/'image.png';source.write_bytes(png())
        self.asset=media_assets.stage(self.root,'hero',source,path='public/assets/hero.png',public_url='https://example.com/assets/hero.png',alt='Actual diagram',license_ref='original licensed fixture')
        self.html='<html><head><link rel="canonical" href="https://example.com/page"><meta property="og:image" content="https://example.com/assets/hero.png"><script type="application/ld+json">{"@type":"BlogPosting","image":"https://example.com/assets/hero.png"}</script></head><body>A visible sentence.<img src="/assets/hero.png" alt="Actual diagram" width="2" height="3"></body></html>'
        queue.propose(self.root,'page',path='content/page.html',content=self.html,url='https://example.com/page',kind='metadata',evidence='review')
        queue.approve(self.root,'page',content_sha256=queue.digest(self.html.encode()),approval_ref='operator');queue.apply(self.root,'page')
        self.plan={'expected_text':'A visible sentence.','media_ids':['hero']}

    def read(self,url,**kwargs):
        return {'status':200,'url':url,'body':png() if kwargs.get('binary') else self.html,'headers':{}}

    def test_public_page_and_exact_media_bytes_verified(self):
        result=public_verify.verify(self.root,'page',self.plan,fetcher=self.read)
        self.assertTrue(result['passed']);self.assertTrue(result['media'][0]['approved_bytes'])
        self.assertIn('not JavaScript',result['scope'])

    def test_script_only_expected_text_is_not_visible_proof(self):
        self.html=self.html.replace('A visible sentence.','<script>A visible sentence.</script>')
        self.assertFalse(public_verify.verify(self.root,'page',self.plan,fetcher=self.read)['passed'])

    def test_wrong_canonical_noindex_and_wrong_asset_bytes_fail(self):
        original=self.html
        for bad in [original.replace('rel="canonical" href="https://example.com/page"','rel="canonical" href="https://example.com/wrong"'),
                    original.replace('<head>','<head><meta name="robots" content="noindex">'),original.replace('width="2"','width="4"')]:
            self.html=bad;self.assertFalse(public_verify.verify(self.root,'page',self.plan,fetcher=self.read)['passed'])
        self.html=original
        def bad_image(url,**kwargs):
            row=self.read(url,**kwargs)
            if kwargs.get('binary'):row['body']=b'wrong image'
            return row
        self.assertFalse(public_verify.verify(self.root,'page',self.plan,fetcher=bad_image)['passed'])

    def test_foreign_redirect_rejected(self):
        with self.assertRaises(PermissionError):public_verify.verify(self.root,'page',self.plan,fetcher=lambda url:{'url':'https://other.com/page','status':200,'body':self.html})

    def test_staged_material_tamper_and_mismatched_extension_fail(self):
        data=state_dir(self.root)/'media'/(self.asset['sha256']+'.bin');data.write_bytes(b'bad')
        with self.assertRaises(ValueError):media_assets.read(self.root,'hero')
        with self.assertRaises(ValueError):media_assets.stage(self.root,'new',self.root/'image.png',path='public/assets/new.jpg',public_url='https://example.com/assets/new.jpg',alt='actual',license_ref='licensed')

    def test_media_requires_license_alt_and_finite_dimensions(self):
        for alt,ref in [('', 'license'),('description','')]:
            with self.assertRaises(ValueError):media_assets.stage(self.root,'bad',self.root/'image.png',path='public/assets/new.png',public_url='https://example.com/assets/new.png',alt=alt,license_ref=ref)
        with self.assertRaises(ValueError):media_assets.dimensions(png(width=0))
        with self.assertRaises(ValueError):media_assets.dimensions(b'<svg>not a raster</svg>')


class OutcomeTests(unittest.TestCase):
    def test_windows_are_equal_length_nonoverlapping_and_delayed(self):
        before=outcome_jobs.window_before(NOW.date());later=outcome_jobs.schedule_after(NOW.date())
        from datetime import date
        self.assertEqual((date.fromisoformat(before['end'])-date.fromisoformat(before['start'])).days,27)
        self.assertEqual((date.fromisoformat(later['window']['end'])-date.fromisoformat(later['window']['start'])).days,27)
        self.assertGreater(later['window']['start'],NOW.date().isoformat())
        self.assertGreater(later['due_at'][:10],later['window']['end'])

    def test_incompatible_missing_and_small_sample_are_not_uplift(self):
        before=measure('.', 'https://example.com/page',outcome_jobs.window_before(NOW.date()))
        after=measure('.', 'https://example.com/page',outcome_jobs.schedule_after(NOW.date())['window'])
        after['data']['aggregate']['clicks']=500
        after['data']['aggregate']['impressions']=10
        self.assertEqual(outcome_jobs.evaluate(before,after)['verdict'],'inconclusive')
        after['status']='failed';self.assertEqual(outcome_jobs.evaluate(before,after)['verdict'],'not_measurable')
        after['status']='ok';after['target']='https://example.com/other'
        self.assertEqual(outcome_jobs.evaluate(before,after)['verdict'],'not_measurable')


if __name__=='__main__':unittest.main()
