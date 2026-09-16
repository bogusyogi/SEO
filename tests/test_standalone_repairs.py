from __future__ import annotations
import ast
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import backlink_tracker as backlinks
import bing_webmaster as bing
import content_queue as content
import gsc_query_v2 as gsc
import google_auth as auth
import mcp_server as mcp
import provider_registry as registry
import rank_tracker as ranks
import safe_http
import seo_runner as runner
import seo_state
import site_policy
from seo_project import setup_project, save_site, load_site


def load_file(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod


class Node:
    def __init__(self,**kw):self.__dict__.update(kw)
Node.StringFilter=Node
Node.MatchType=types.SimpleNamespace(EXACT='EXACT')
Node.DimensionOrderBy=Node
Node.MetricOrderBy=Node


def load_ga4():
    data=types.ModuleType('google.analytics.data_v1beta');data.BetaAnalyticsDataClient=Mock()
    t=types.ModuleType('google.analytics.data_v1beta.types')
    for key in ('DateRange','Dimension','Filter','FilterExpression','Metric','OrderBy','RunReportRequest'):setattr(t,key,Node)
    with patch.dict(sys.modules,{'google.analytics.data_v1beta':data,'google.analytics.data_v1beta.types':t}):
        return load_file('ga4_repair_test',ROOT/'scripts/ga4_report.py')


def row(dims,values):
    return Node(dimension_values=[Node(value=x) for x in dims],metric_values=[Node(value=str(x)) for x in values])


def response(rows):return Node(rows=rows,row_count=len(rows),metadata=Node(currency_code='USD',time_zone='UTC'),property_quota=None)


class StandaloneRepairs(unittest.TestCase):
    def setup_site(self,root):
        site=setup_project(root,domain='example.com',market='IN',language='en',gsc_property='sc-domain:example.com',ga4_property='123',bing_site='https://example.com/')
        site['policy']={'mode':'approved','approval_ref':'operator:test','allowed_actions':['draft','metadata','publish','rollback'],'write_prefixes':['content','pages']}
        save_site(site,root);return site

    def test_no_legion_needed_for_cli_from_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as td:
            run=subprocess.run([sys.executable,str(ROOT/'seo.py'),'--help'],cwd=td,capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr);self.assertIn('standalone',run.stdout)

    def test_new_state_is_seo_not_legion(self):
        with tempfile.TemporaryDirectory() as td:
            self.setup_site(td);self.assertTrue((Path(td)/'.seo/site.yaml').is_file());self.assertFalse((Path(td)/'.legion').exists())

    def test_legacy_state_migrates_without_deletion(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path(td)/'.legion/seo';old.mkdir(parents=True);(old/'site.yaml').write_text('{"domain":"example.com"}')
            self.assertEqual(seo_state.state_dir(td),old)
            result=seo_state.migrate(td);self.assertEqual(result['status'],'migrated');self.assertTrue(old.is_dir())
            self.assertEqual((Path(td)/'.seo/site.yaml').read_bytes(),(old/'site.yaml').read_bytes())
            with self.assertRaises(ValueError):seo_state.migrate(td)

    def test_atomic_state_rejects_nonfinite_values(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.json';seo_state.atomic_json(p,{'value':1})
            with self.assertRaises(ValueError):seo_state.atomic_json(p,{'value':float('nan')})
            self.assertEqual(json.loads(p.read_text()),{'value':1})

    def test_gsc_compatibility_alias_is_authoritative(self):
        r=gsc.normalize_result(site_url='sc-domain:example.com',start_date='2026-01-01',end_date='2026-01-28',dimensions=['query'],search_type='web',aggregate_row={'clicks':1234,'impressions':9876,'ctr':.1,'position':4},rows=[{'clicks':1,'impressions':10,'position':5,'keys':['query']}],max_rows=100,hit_cap=False)
        self.assertEqual(r['totals']['clicks'],1234);self.assertEqual(r['dimension_sum']['clicks'],1)
        self.assertEqual(r['row_count'],1);self.assertIsNone(r['coverage']['complete'])
        # Execute the actual pure renderer functions, not a hand-written replacement,
        # without requiring matplotlib/WeasyPrint for deterministic contract tests.
        tree=ast.parse((ROOT/'scripts/google_report.py').read_text())
        needed={'_build_executive_summary','_metric_card'}
        code=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in needed],type_ignores=[])
        ns={'BRAND':{'primary':'x','secondary':'y'}};exec(compile(code,'google_report.py','exec'),ns)
        html=ns['_build_executive_summary']('example.com','date',{'gsc':r},'gsc-performance')
        self.assertIn('1,234',html);self.assertIn('9,876',html)

    def test_gsc_service_failure_is_structured(self):
        with patch.object(gsc,'service',side_effect=RuntimeError('auth failed')):
            result=gsc.query('x','2026-01-01','2026-01-28',['query'],'web',100,100)
        self.assertTrue(result['error'])

    def test_ga4_period_users_not_daily_sum(self):
        ga4=load_ga4()
        client=Mock();client.run_report.side_effect=[response([row(['20260101'],[10,7,20,.2,30,.8]),row(['20260102'],[10,7,20,.2,30,.8])]),response([row(['/'],[20,9,40,.2,.8])]),response([row([],[20,9,40,3,12.5])])]
        with patch.object(ga4,'_build_ga4_client',return_value=client):result=ga4.organic_traffic_report('123',2)
        self.assertEqual(result['totals']['users'],9);self.assertNotEqual(result['totals']['users'],14)
        self.assertEqual(result['totals']['key_events'],3);self.assertEqual(result['totals']['revenue'],12.5)
        self.assertEqual(client.run_report.call_args_list[-1][0][0].dimensions,[])

    def test_ga4_partial_pages_error_survives_wrapper(self):
        ga4=load_ga4()
        with patch.object(ga4,'organic_traffic_report',return_value={'pages_error':'denied','status':'partial','totals':{'sessions':10}}):
            result=ga4.top_pages_report('123')
        self.assertEqual(result['error'],'denied');self.assertEqual(result['status'],'partial')

    def test_ga4_json_errors_return_nonzero(self):
        ga4=load_ga4()
        with patch.object(sys,'argv',['ga4','--property','123','--json']),patch.object(ga4,'organic_traffic_report',return_value={'error':'denied'}),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ga4.main(),1)

    def test_bing_links_paginate_with_target(self):
        with patch.object(bing,'call',side_effect=[{'d':{'Details':[{'Url':'https://a.com/','AnchorText':'A'}],'TotalPages':2}},{'d':{'Details':[{'Url':'https://b.com/','AnchorText':'B'}],'TotalPages':2}}]) as call:
            result=bing.links('https://example.com/','https://example.com/post')
        self.assertEqual(len(result['rows']),2);self.assertTrue(result['coverage']['complete'])
        self.assertEqual(call.call_args_list[1].kwargs['params']['page'],1)
        self.assertEqual(call.call_args_list[0].kwargs['params']['link'],'https://example.com/post')

    def test_bing_partial_failure_preserves_data(self):
        with patch.object(bing,'call',side_effect=[{'d':{'Details':[{'Url':'https://a.com/'}],'TotalPages':2}},{'error':'429'}]):
            result=bing.links('https://example.com/','https://example.com/')
        self.assertEqual(result['status'],'partial');self.assertEqual(len(result['rows']),1);self.assertFalse(result['coverage']['complete'])

    def test_rank_provider_change_not_movement(self):
        a=ranks.normalize({'keyword':'q','position':3},{'market':'IN','language':'en','provider':'one'})
        b=ranks.normalize({'keyword':'q','position':1},{'market':'IN','language':'en','provider':'two'})
        self.assertEqual(ranks.compare_rows([a],[b])['status'],'not_comparable')

    def test_rank_missing_is_not_collected_not_lost(self):
        a=ranks.normalize({'keyword':'q','position':3},{'market':'IN','language':'en','provider':'one'})
        change=ranks.compare_rows([a],[])['changes'][0]
        self.assertEqual(change['type'],'missing_observation');self.assertEqual(change['status'],'not_collected')

    def test_rank_rejects_invalid_position_and_snapshot_escape(self):
        with self.assertRaises(ValueError):ranks.normalize({'keyword':'q','position':float('nan')},{'market':'IN','language':'en','provider':'one'})
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):ranks.ingest(td,[],{'snapshot':'../../escape'})

    def test_sampled_backlinks_never_confirm_loss(self):
        a={'provider':'bing','scope':'root','coverage':{'complete':False},'rows':[{'source_url':'https://a.com/','target_url':'https://example.com/'}]}
        b={**a,'rows':[]};result=backlinks.compare(a,b)
        self.assertFalse(result['missing'][0]['confirmed_lost']);self.assertEqual(result['missing'][0]['state'],'not_observed_in_sample')

    def test_backlink_source_change_not_comparable(self):
        self.assertEqual(backlinks.compare({'provider':'a','scope':'x'},{'provider':'b','scope':'x'})['status'],'not_comparable')

    def test_missing_credential_file_is_not_configured(self):
        with patch.dict(os.environ,{'GOOGLE_APPLICATION_CREDENTIALS':'/no/such/file'}),patch.object(auth,'load_config',return_value={}),patch.object(auth,'_load_oauth_token',return_value=None):
            r=registry.availability({'availability':'env_any','env':['GOOGLE_APPLICATION_CREDENTIALS']})
        self.assertNotEqual(r,'available');self.assertNotEqual(r,'configured')

    def test_expired_oauth_without_client_falls_back(self):
        with patch.object(auth,'load_config',return_value={}),patch.object(auth,'_load_oauth_token',return_value={'access_token':'expired','expires_at':1}),patch.object(auth,'get_service_account_credentials',return_value='fallback'):
            self.assertEqual(auth.get_oauth_credentials([]),'fallback')

    def test_token_save_omits_client_secret(self):
        with tempfile.TemporaryDirectory() as td,patch.object(auth,'TOKEN_PATH',str(Path(td)/'token.json')):
            auth._save_oauth_token({'access_token':'x','client_secret':'never-store'})
            data=json.loads((Path(td)/'token.json').read_text());self.assertNotIn('client_secret',data)

    def test_private_dns_and_mixed_dns_rejected(self):
        for ips in (['127.0.0.1'],['8.8.8.8','10.0.0.1'],['::1']):
            with patch.object(safe_http.socket,'getaddrinfo',return_value=[(None,None,None,None,(ip,443)) for ip in ips]):
                with self.assertRaises(ValueError):safe_http.public_address('example.com',443)

    def test_public_url_rejects_credentials_ports_and_protocols(self):
        for url in ('file:///etc/passwd','https://user:pass@example.com/','http://example.com:8080/'):
            with self.assertRaises(ValueError):safe_http.validate_url(url)

    def test_wrong_gsc_property_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            site=self.setup_site(td);site['properties']['gsc']='sc-domain:other.com'
            with self.assertRaises(PermissionError):site_policy.property_for(site,'gsc')

    def test_technical_only_site_cannot_publish(self):
        with tempfile.TemporaryDirectory() as td:
            site=self.setup_site(td);site['domain']='stunningstrangers.com';save_site(site,td);loaded=site_policy.load(td)
            self.assertEqual(loaded['policy']['mode'],'technical_only')
            with self.assertRaises(PermissionError):site_policy.authorize(loaded,'publish',path='content/a.md')

    def test_content_apply_is_idempotent_and_rollback_is_real(self):
        with tempfile.TemporaryDirectory() as td:
            self.setup_site(td)
            p=Path(td)/'content/post.md';p.parent.mkdir();p.write_text('old')
            proposal=content.propose(td,'p1',path='content/post.md',content='new',url='https://example.com/post',evidence='approved-source')
            content.approve(td,'p1',content_sha256=proposal['content_sha256'],approval_ref='operator:p1')
            result=content.apply(td,'p1');self.assertEqual(result['status'],'applied');self.assertEqual(p.read_text(),'new')
            self.assertTrue(content.apply(td,'p1')['duplicate'])
            verify=content.verify(td,'p1',expected_text='new',fetcher=lambda u:{'status':200,'url':u,'body':'<html>new</html>'})
            self.assertTrue(verify['passed'])
            content.rollback(td,'p1');self.assertEqual(p.read_text(),'old')

    def test_content_tamper_after_approval_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            self.setup_site(td)
            proposal=content.propose(td,'p1',path='content/post.md',content='new',url='https://example.com/post',evidence='source')
            content.approve(td,'p1',content_sha256=proposal['content_sha256'],approval_ref='operator:p1')
            p=content.item_path(td,'p1');data=json.loads(p.read_text());data['content']='tampered';seo_state.atomic_json(p,data)
            with self.assertRaises(PermissionError):content.apply(td,'p1')

    def test_content_baseline_conflict_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            self.setup_site(td);p=Path(td)/'content/post.md';p.parent.mkdir();p.write_text('old')
            prop=content.propose(td,'p1',path='content/post.md',content='new',url='https://example.com/post',evidence='source')
            content.approve(td,'p1',content_sha256=prop['content_sha256'],approval_ref='operator:p1');p.write_text('another writer')
            with self.assertRaises(ValueError):content.apply(td,'p1')
            self.assertEqual(p.read_text(),'another writer')

    def test_content_cannot_write_credentials_or_parent(self):
        with tempfile.TemporaryDirectory() as td:
            site=self.setup_site(td)
            for path in ('../escape','.env','content/../.env','/tmp/x'):
                with self.assertRaises(PermissionError):site_policy.authorize(site,'publish',path=path)

    def test_runner_duplicate_tick_does_not_collect_twice(self):
        with tempfile.TemporaryDirectory() as td:
            self.setup_site(td);seo_state.atomic_json(seo_state.state_dir(td)/'schedule.json',{'jobs':[{'lane':'gsc','interval_seconds':86400}]})
            collector=Mock(return_value={'status':'ok','site':'example.com','lane':'gsc','data':{}})
            self.assertEqual(runner.tick(td,now=100000,run_collector=collector)['status'],'ok')
            result=runner.tick(td,now=100010,run_collector=collector)
            self.assertEqual(collector.call_count,1);self.assertEqual(result['jobs'][0]['status'],'already_recorded')

    def test_runner_failed_job_retries_but_never_reports_ok(self):
        with tempfile.TemporaryDirectory() as td:
            self.setup_site(td);seo_state.atomic_json(seo_state.state_dir(td)/'schedule.json',{'jobs':[{'lane':'gsc','interval_seconds':86400}]})
            collector=Mock(return_value={'status':'failed','site':'example.com','lane':'gsc'})
            for t in (100000,100001,100500):self.assertEqual(runner.tick(td,now=t,run_collector=collector)['status'],'partial')
            self.assertEqual(collector.call_count,2)

    def test_runner_rejects_wrong_site_result(self):
        with tempfile.TemporaryDirectory() as td:
            self.setup_site(td);seo_state.atomic_json(seo_state.state_dir(td)/'schedule.json',{'jobs':[{'lane':'gsc'}]})
            result=runner.tick(td,now=100000,run_collector=lambda *a,**k:{'status':'ok','site':'other.com'})
            self.assertEqual(result['status'],'partial')

    def test_runner_no_schedule_means_no_work(self):
        with tempfile.TemporaryDirectory() as td:
            self.setup_site(td);collector=Mock();self.assertEqual(runner.tick(td,run_collector=collector)['status'],'not_configured');collector.assert_not_called()

    def test_schema_event_and_valid_graph(self):
        validator=load_file('schema_repair_test',ROOT/'hooks/validate-schema.py')
        good='<script id="schema" type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":["HowTo","CreativeWork"],"name":"Steps"}]}</script>'
        self.assertEqual(validator.validate_jsonld(good),[])
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'page.html';p.write_text(good)
            with patch.object(sys,'stdin',io.StringIO(json.dumps({'tool_input':{'file_path':str(p)}}))),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(validator.main([]),0)

    def test_schema_invalid_json_blocks_explicit_gate(self):
        validator=load_file('schema_repair_test2',ROOT/'hooks/validate-schema.py')
        self.assertTrue(validator.validate_jsonld('<script type="application/ld+json">{invalid}</script>'))

    def test_mcp_initialize_list_and_allowlist(self):
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},
                  {'jsonrpc':'2.0','method':'notifications/initialized'},
                  {'jsonrpc':'2.0','id':2,'method':'tools/list'},
                  {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'seo_report','arguments':{'root':'/not/approved'}}}]
        output=io.StringIO()
        with patch.dict(os.environ,{'SEO_PROJECT_ROOTS':''}):mcp.serve(io.StringIO('\n'.join(json.dumps(x) for x in messages)+'\n'),output)
        rows=[json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual(len(rows),3);self.assertEqual(len(rows[1]['result']['tools']),5);self.assertTrue(rows[2]['result']['isError'])

    def test_plugin_folder_paths_resolve(self):
        for name in ('.codex-plugin/plugin.json','.claude-plugin/plugin.json'):
            manifest=json.loads((ROOT/name).read_text())
            self.assertTrue((ROOT/manifest['skills']/'seo/SKILL.md').is_file());self.assertTrue((ROOT/manifest['mcpServers']).is_file())
        hooks=json.loads((ROOT/'hooks/hooks.json').read_text());self.assertNotIn('$FILE_PATH',json.dumps(hooks))

if __name__=='__main__':unittest.main()
