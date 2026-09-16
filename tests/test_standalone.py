from __future__ import annotations
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from seo_runtime import Runtime, Blocked, init_site, load_site, migrate_state
from seo_io import digest, public_target
import rank_tracker
import backlink_history
import bing_webmaster
import gsc_query_v2

def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

class ContractRepairTests(unittest.TestCase):
    def test_gsc_legacy_totals_are_authoritative_not_dimension_sum(self):
        result = gsc_query_v2.normalize_result(site_url='sc-domain:example.com', start_date='2026-08-01', end_date='2026-08-28',
            dimensions=['query'], search_type='web', aggregate_row={'clicks':10, 'impressions':100, 'ctr':0.1, 'position':4},
            rows=[{'keys':['term'], 'clicks':4, 'impressions':40, 'ctr':0.1, 'position':4}], max_rows=10, hit_cap=False)
        self.assertEqual(result['totals']['clicks'], 10)
        self.assertEqual(result['aggregate'], result['totals'])
        self.assertEqual(result['dimension_sum']['clicks'], 4)
        self.assertEqual(result['row_count'], 1)
        self.assertIsNone(result['coverage']['complete'])
    def test_gsc_cli_scopes_page_prefix(self):
        with patch.object(gsc_query_v2, 'query', return_value={}) as mocked, patch.object(sys, 'argv', ['gsc', '--property', 'sc-domain:example.com', '--page-prefix', 'https://example.com/blog/']), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gsc_query_v2.main(), 0)
        filters = mocked.call_args.args[7]
        self.assertEqual(filters[0]['dimension'], 'page')
        self.assertTrue(filters[0]['expression'].startswith('^https://example'))
    def test_bing_backlinks_paginates_actual_api_contract(self):
        values = [{'d':{'Details':[{'Url':'https://a.example/a','AnchorText':'a'}], 'TotalPages':2}},
                  {'d':{'Details':[{'Url':'https://b.example/b','AnchorText':'b'}], 'TotalPages':2}}]
        with patch.object(bing_webmaster, 'call', side_effect=values) as mocked:
            result = bing_webmaster.url_links('https://example.com/', 'https://example.com/page', 5)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(mocked.call_args_list[0].args[1]['page'], 0)
        self.assertEqual(mocked.call_args_list[1].args[1]['page'], 1)
        self.assertEqual(mocked.call_args_list[0].args[1]['link'], 'https://example.com/page')
    def test_bing_cap_and_failure_are_not_empty_success(self):
        with patch.object(bing_webmaster, 'call', return_value={'d':{'Details':[], 'TotalPages':2}}):
            result = bing_webmaster.url_links('https://example.com/', 'https://example.com/p', 1)
        self.assertFalse(result['complete']); self.assertEqual(result['status'], 'partial')
        with patch.object(bing_webmaster, 'call', return_value={'error':'HTTP 403','status':'unauthorized'}):
            self.assertEqual(bing_webmaster.url_links('https://example.com/', 'https://example.com/p')['status'], 'unauthorized')
    def test_backlink_partial_snapshot_never_declares_loss(self):
        before = {'provider':'bing', 'property':'example.com', 'target':'/p', 'complete':True,
                  'rows':[{'source_url':'https://source.example/a','target_url':'https://example.com/p'}]}
        after = {**before, 'complete':False, 'rows':[]}
        result = backlink_history.compare(before, after)
        self.assertEqual(result['lost_candidates'], [])
        self.assertEqual(len(result['unconfirmed_missing']), 1)
        self.assertEqual(result['confirmed_lost'], [])
    def test_rank_missing_is_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            defaults = {'market':'IN','language':'en','provider':'fixture'}
            rank_tracker.ingest(td, [{'query':'a','position':4},{'query':'b','position':7}], {**defaults,'snapshot':'001'})
            rank_tracker.ingest(td, [{'query':'a','position':2}], {**defaults,'snapshot':'002'})
            result = rank_tracker.compare(td)
        self.assertEqual(result['missing_observations'], 1)
        self.assertTrue(any(x.get('position_improvement') == 2 for x in result['changes']))
    def test_rank_provider_change_not_compared(self):
        with tempfile.TemporaryDirectory() as td:
            defaults = {'market':'IN','language':'en'}
            rank_tracker.ingest(td,[{'query':'a','position':4}],{**defaults,'provider':'gsc','snapshot':'001'})
            rank_tracker.ingest(td,[{'query':'a','position':1}],{**defaults,'provider':'serp','snapshot':'002'})
            result = rank_tracker.compare(td)
        self.assertFalse(any(x.get('comparable') for x in result['changes']))
    def test_rank_rejects_nan_and_path_escape(self):
        with self.assertRaises(ValueError):
            rank_tracker.normalize({'query':'a','position':float('nan')},{'market':'IN','language':'en','provider':'p'})
        with tempfile.TemporaryDirectory() as td, self.assertRaises(ValueError):
            rank_tracker.ingest(td, [], {'snapshot':'../../outside'})
    def test_schema_supports_graph_and_type_arrays(self):
        schema = load('standalone_schema', 'hooks/validate-schema.py')
        html = '<script data-test="x" type="application/ld+json">'+json.dumps({'@context':'https://schema.org','@graph':[{'@type':['HowTo','Article'],'name':'Guide'},{'@type':'FAQPage','name':'Questions'}]})+'</script>'
        self.assertEqual(schema.validate_jsonld(html), [])
    def test_schema_hook_reads_stdin_event(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'page.html'
            p.write_text('<script type="application/ld+json">{broken}</script>')
            result = subprocess.run([sys.executable,str(ROOT/'hooks/validate-schema.py')], input=json.dumps({'tool_input':{'file_path':str(p)}}), text=True,capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('invalid JSON', result.stdout)
    def test_http_rejects_private_resolution_and_outside_scope(self):
        with patch('socket.getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',443))]), self.assertRaises(ValueError):
            public_target('https://example.com/', {'example.com'})
        with self.assertRaises(ValueError): public_target('https://other.example/', {'example.com'})
        with self.assertRaises(ValueError): public_target('file:///etc/passwd', {'example.com'})
    def test_source_maturity_requires_verified_and_mature(self):
        ops = load('standalone_ops', 'scripts/search_ops.py')
        state = {'interventions':[{'id':'i','deployment':{'identity':'x'},'verification':{'result':'pass'},'evaluation':{'earliest_date':'2999-01-01'}}]}
        with self.assertRaises(SystemExit): ops.cmd_outcome(NS(id='i', verdict='improved', evidence='gsc'), state)
    def test_cli_is_independent_of_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run([sys.executable,str(ROOT/'seo.py'),'--version'],cwd=td,capture_output=True,text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0.2.0', result.stdout)

class GA4RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import google.analytics.data_v1beta
        except ImportError:
            raise unittest.SkipTest('optional Google SDK unavailable; full CI installs it')
        cls.ga4 = load('standalone_ga4', 'scripts/ga4_report.py')
    def fake(self, fail_pages=False):
        calls = []
        def row(dims, values):
            return NS(dimension_values=[NS(value=str(x)) for x in dims], metric_values=[NS(value=str(x)) for x in values])
        def execute(request):
            calls.append(request)
            dims = [x.name for x in request.dimensions]
            if dims == ['date']:
                rows = [row(['20260901'],[2,2,4,.1,60,.9]), row(['20260902'],[2,2,4,.1,60,.9])]
            elif dims == ['landingPage']:
                if fail_pages: raise RuntimeError('page query failed')
                rows = [row(['/'],[4,2,8,.1,.9])]
            else: rows = [row([], [4,2,8,1,30,1])]
            return NS(rows=rows,property_quota=None,metadata=NS(currency_code='USD',time_zone='UTC',subject_to_thresholding=False,data_loss_from_other_row=False))
        return NS(run_report=execute), calls
    def test_period_users_not_sum_and_hostname_is_applied(self):
        client,calls = self.fake()
        with patch.object(self.ga4,'_build_ga4_client',return_value=client):
            report = self.ga4.organic_traffic_report('123',2,10,'example.com')
        self.assertEqual(report['totals']['users'],2)
        self.assertEqual(sum(x['users'] for x in report['daily_data']),4)
        self.assertEqual(report['totals']['revenue'],30)
        self.assertEqual(report['totals']['key_events'],1)
        for call in calls:
            filters = call.dimension_filter.and_group.expressions
            self.assertEqual(filters[1].filter.field_name,'hostName')
            self.assertEqual(filters[1].filter.string_filter.value,'example.com')
    def test_page_failure_survives_wrapper(self):
        client,_ = self.fake(True)
        with patch.object(self.ga4,'_build_ga4_client',return_value=client):
            report = self.ga4.top_pages_report('123')
        self.assertIn('page query failed',report['error'])
        self.assertEqual(report['status'],'partial')
    def test_json_error_exit_is_nonzero(self):
        with patch.object(self.ga4,'organic_traffic_report',return_value={'error':'denied'}), patch.object(sys,'argv',['ga4','--property','123','--json']), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.ga4.main(),1)

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        init_site(self.root,'example.com','IN','en',gsc_property='sc-domain:example.com',ga4_property='123')
        self.runtime = Runtime(self.root)
    def tearDown(self): self.temp.cleanup()
    def policy(self, **values):
        p = self.root/'.seo/site.yaml'
        site = json.loads(p.read_text())
        site['policy'].update(values)
        p.write_text(json.dumps(site))
    def allow_writes(self):
        self.policy(allowed_actions=['collect','report','draft','patch','rollback','publish'],auto_actions=['collect','report','draft','patch','rollback','publish'],allowed_paths=['content'])
    def patch_job(self):
        self.allow_writes()
        (self.root/'content').mkdir(exist_ok=True)
        (self.root/'content/page.md').write_text('before')
        return self.runtime.enqueue('patch',{'path':'content/page.md','expected_sha256':digest(b'before'),'content':'after','category':'technical'})
    def test_patch_receipt_idempotence_and_rollback(self):
        job = self.patch_job()
        self.runtime.tick()
        row = self.runtime.row(job['id'])
        self.assertEqual(row['state'],'succeeded')
        self.assertFalse(row['result']['deployed'])
        self.assertEqual((self.root/'content/page.md').read_text(),'after')
        self.assertEqual(self.runtime.tick()['jobs'],[])
        self.assertEqual(self.runtime.enqueue('patch',job['payload'])['id'],job['id'])
        undo = self.runtime.enqueue('rollback',{'job_id':job['id']})
        self.runtime.tick()
        self.assertEqual(self.runtime.row(undo['id'])['state'],'succeeded')
        self.assertEqual((self.root/'content/page.md').read_text(),'before')
    def test_rollback_does_not_overwrite_new_change(self):
        job = self.patch_job(); self.runtime.tick()
        (self.root/'content/page.md').write_text('another writer')
        undo = self.runtime.enqueue('rollback',{'job_id':job['id']}); self.runtime.tick()
        self.assertEqual(self.runtime.row(undo['id'])['state'],'blocked')
        self.assertEqual((self.root/'content/page.md').read_text(),'another writer')
    def test_read_command_does_not_drain_mutations(self):
        pending = self.patch_job()
        report = self.runtime.enqueue('report',{})
        self.runtime.tick(only_id=report['id'])
        self.assertEqual(self.runtime.row(pending['id'])['state'],'pending')
        self.assertEqual(self.runtime.row(report['id'])['state'],'succeeded')
    def test_policy_change_invalidates_queued_authority(self):
        job = self.patch_job()
        self.policy(max_change_bytes=200000)
        self.runtime.tick()
        self.assertEqual(self.runtime.row(job['id'])['state'],'blocked')
        self.assertEqual((self.root/'content/page.md').read_text(),'before')
    def test_technical_only_blocks_drafts(self):
        self.policy(technical_only=True)
        job = self.runtime.enqueue('draft',{'title':'Title','query':'q','sources':[{'id':'a','url':'https://example.com'}],'body':'draft'})
        self.runtime.tick()
        self.assertEqual(self.runtime.row(job['id'])['state'],'blocked')
    def test_cross_site_property_is_rejected(self):
        p = self.root/'.seo/site.yaml'; site = json.loads(p.read_text()); site['properties']['gsc']='sc-domain:other.example'; p.write_text(json.dumps(site))
        with self.assertRaises(Blocked): Runtime(self.root)
    def test_mutation_crash_is_uncertain_not_retried(self):
        job = self.patch_job(); claimed,_ = self.runtime.claim()
        with self.runtime.connection() as db: db.execute('UPDATE jobs SET lease=0 WHERE id=?',(job['id'],))
        self.runtime.tick()
        self.assertEqual(self.runtime.row(job['id'])['state'],'uncertain')
        self.assertEqual(self.runtime.row(job['id'])['attempts'],1)
    def test_only_one_mutation_can_be_claimed(self):
        first = self.patch_job()
        self.runtime.enqueue('patch',{**first['payload'],'content':'different'})
        self.assertIsNotNone(self.runtime.claim()[0])
        self.assertIsNone(self.runtime.claim()[0])
    def test_path_escape_is_blocked(self):
        self.allow_writes()
        job = self.runtime.enqueue('patch',{'path':'../escape','content':'bad','expected_sha256':'absent'})
        self.runtime.tick()
        self.assertNotEqual(self.runtime.row(job['id'])['state'],'succeeded')
    def test_schedule_coalesces_and_is_read_only(self):
        self.runtime.add_schedule('daily',{},24,'report')
        self.runtime.due_schedules(); self.runtime.due_schedules()
        self.assertEqual(len(self.runtime.jobs()),1)
        with self.assertRaises(Blocked): self.runtime.add_schedule('bad',{},24,'publish')
    def test_explicit_approval_binds_exact_payload(self):
        self.patch_job()
        self.policy(auto_actions=['collect','report','draft'])
        job = self.runtime.enqueue('patch',{'path':'content/page.md','expected_sha256':digest(b'before'),'content':'approved'})
        self.runtime.tick(only_id=job['id'])
        self.assertEqual(self.runtime.row(job['id'])['state'],'blocked')
        self.runtime.approve(job['id']); self.runtime.tick(only_id=job['id'])
        self.assertEqual(self.runtime.row(job['id'])['state'],'succeeded')
    def test_budget_is_reserved_again_on_read_retry(self):
        p=self.root/'.seo/site.yaml'; site=json.loads(p.read_text())
        site['policy']['monthly_budget_usd']=.5
        site['adapters']={'data':{'effect':'read','argv':[sys.executable,'-c','import json; print(json.dumps({"error":"transient"}))'],'max_cost_usd':.5}}
        p.write_text(json.dumps(site))
        job=self.runtime.enqueue('collect',{'provider':'adapter:data'})
        self.runtime.tick()
        with self.runtime.connection() as db: db.execute('UPDATE jobs SET due=0 WHERE id=?',(job['id'],))
        self.runtime.tick()
        self.assertEqual(self.runtime.row(job['id'])['state'],'blocked')
    def test_publish_has_separate_observed_verification(self):
        self.allow_writes()
        draft=self.runtime.enqueue('draft',{'title':'Title','query':'question','sources':[{'id':'a','url':'https://example.com'}],'body':'the actual article'})
        self.runtime.tick()
        data=self.runtime.row(draft['id'])['result']
        job=self.runtime.enqueue('publish',{'artifact':data['artifact'],'sha256':data['sha256'],'rollback_plan':'restore CMS revision 1','verification':{'url':'https://example.com/post','contains':['the actual article']}})
        with patch.object(self.runtime,'adapter',return_value={'job_id':job['id'],'receipt':'cms:2'}), patch('seo_runtime.fetch',return_value={'status':200,'body':b'the actual article'}):
            self.runtime.tick()
        row=self.runtime.row(job['id'])
        self.assertEqual(row['state'],'succeeded'); self.assertTrue(row['result']['verified'])
        self.assertEqual(row['result']['outcome'],'not_evaluated')
    def test_migration_preserves_original_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path(td)/'.legion/seo'; old.mkdir(parents=True)
            (old/'site.yaml').write_text('{"domain":"example.com"}')
            (old/'snapshot.json').write_bytes(b'important history')
            result=migrate_state(td)
            self.assertTrue(result['source_preserved'])
            self.assertEqual((Path(td)/'.seo/snapshot.json').read_bytes(),b'important history')
            self.assertTrue((old/'snapshot.json').exists())

if __name__ == '__main__': unittest.main()
