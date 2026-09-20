"""Executable regressions for PR reconciliation and the operational integrations."""
from __future__ import annotations
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import collector
import content_queue
import remote_actions as actions
import report_delivery as delivery
import reporting
import seo_runner
import rank_tracker
import backlink_tracker
import serp_collect
import authenticated_http
import mcp_server
from measurement_scope import gsc_host_filter, site_hosts
from seo_project import setup_project, save_site
from seo_state import state_dir, atomic_json
from site_policy import property_for, load
from test_standalone_repairs import load_ga4, response, row


def setup(root):
    site = setup_project(root, domain='example.com', market='US', language='en',
        gsc_property='sc-domain:example.com', ga4_property='123', bing_site='https://example.com/')
    site['policy'] = {'mode': 'approved', 'approval_ref': 'operator-test',
        'allowed_actions': ['draft', 'publish', 'metadata', 'rollback', 'deliver'], 'write_prefixes': ['content', 'pages']}
    site['delivery'] = {'provider': 'smtp', 'host': 'smtp.example.com', 'port': 465, 'security': 'ssl',
        'from': 'report@example.com', 'to': ['owner@example.com']}
    save_site(site, root)
    return site


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        self.site = setup(self.root)
        self.env = patch.dict(os.environ, {'DATAFORSEO_LOGIN': 'fixture', 'DATAFORSEO_PASSWORD': 'not-real'})
        self.env.start()

    def tearDown(self):
        self.env.stop(); self.temp.cleanup()


    def prepare_delivery(self, action_id='report'):
        report = state_dir(self.root) / 'reports/test.md'
        report.write_text('Reviewed report', encoding='utf-8')
        result = delivery.prepare(self.root, action_id, report, 'operator')
        actions.approve(self.root, action_id, result['request_sha256'], 'operator:test')
        return result

    def test_host_regex_excludes_suffix_and_other_subdomains(self):
        rule = gsc_host_filter(['example.com', 'www.example.com'])
        self.assertIsNotNone(re.search(rule['expression'], 'https://example.com/post'))
        self.assertIsNone(re.search(rule['expression'], 'https://example.com.attacker.test/post'))
        self.assertIsNone(re.search(rule['expression'], 'https://other.example.com/post'))

    def test_domain_property_can_cover_subdomain_but_url_prefix_cannot(self):
        site = dict(load(self.root), domain='blog.example.com')
        self.assertEqual(property_for(site, 'gsc'), 'sc-domain:example.com')
        site['properties'] = {'gsc': 'https://example.com/'}
        with self.assertRaises(PermissionError): property_for(site, 'gsc')

    def test_path_property_does_not_claim_whole_site(self):
        site = load(self.root); site['properties']['gsc'] = 'https://example.com/blog/'
        with self.assertRaises(PermissionError): property_for(site, 'gsc')
        site['base_url'] = 'https://example.com/blog/'
        self.assertEqual(property_for(site, 'gsc'), site['base_url'])

    def test_project_cannot_be_repurposed_to_another_domain(self):
        with self.assertRaises(ValueError): setup_project(self.root, domain='other.test', market='US', language='en')

    def test_ga4_host_filter_applies_to_daily_pages_and_totals(self):
        ga4 = load_ga4()
        client = Mock(); client.run_report.side_effect = [response([row(['20260901'], [3, 2, 4, .1, 10, .9])]), response([]), response([row([], [3, 2, 4, 1, 10])])]
        with patch.object(ga4, '_build_ga4_client', return_value=client):
            result = ga4.organic_traffic_report('123', 1, hostnames=['example.com'])
        self.assertEqual(result['hostname_scope'], ['example.com'])
        for call in client.run_report.call_args_list:
            expr = call.args[0].dimension_filter.and_group['expressions'][1]
            self.assertEqual(expr['filter']['field_name'], 'hostName')
            self.assertEqual(expr['filter']['in_list_filter']['values'], ['example.com'])

    def test_collector_supplies_host_scope_and_gsc_rank_dimensions(self):
        with patch.object(collector, 'run_json', return_value=({'property': 'sc-domain:example.com', 'rows': []}, 0)) as run:
            result = collector.collect(self.root, 'gsc_ranks')
        self.assertEqual(result['status'], 'ok')
        args = run.call_args.args[1]
        self.assertIn('--host', args); self.assertIn('example.com', args); self.assertIn('query,country,device', args)

    def test_collector_rejects_wrong_property_response(self):
        with patch.object(collector, 'run_json', return_value=({'property': 'sc-domain:other.test', 'rows': []}, 0)):
            result = collector.collect(self.root, 'gsc')
        self.assertEqual(result['status'], 'failed')

    def test_backlinks_collect_every_explicit_target(self):
        self.site['backlink_targets'] = ['https://example.com/', 'https://example.com/pricing']
        save_site(self.site, self.root)
        def run(root, args, timeout, output=None):
            target = args[args.index('--url') + 1]
            return {'status': 'ok', 'property': 'https://example.com/', 'target': target,
                'rows': [{'source_url': 'https://press.test/review', 'target_url': target}], 'coverage': {'complete': True}}, 0
        with patch.object(collector, 'run_json', side_effect=run) as wrapped:
            result = collector.collect(self.root, 'backlinks')
        self.assertEqual(wrapped.call_count, 2)
        self.assertEqual(result['data']['coverage']['targets_requested'], 2)
        self.assertEqual(len(result['data']['rows']), 2)

    def test_backlinks_validate_entire_target_scope_before_any_request(self):
        self.site['backlink_targets'] = ['https://example.com/', 'https://another.test/']
        save_site(self.site, self.root)
        with patch.object(collector, 'run_json') as run:
            self.assertEqual(collector.collect(self.root, 'backlinks')['status'], 'failed')
        run.assert_not_called()

    def test_partial_backlinks_preserve_other_targets(self):
        self.site['backlink_targets'] = ['https://example.com/', 'https://example.com/pricing']
        save_site(self.site, self.root)
        good = {'status': 'ok', 'property': 'https://example.com/', 'target': 'https://example.com/',
                'rows': [{'source_url': 'https://press.test/a', 'target_url': 'https://example.com/'}], 'coverage': {'complete': True}}
        with patch.object(collector, 'run_json', side_effect=[(good, 0), ({'status': 'error', 'error': 'denied'}, 1)]):
            result = collector.collect(self.root, 'backlinks')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['data']['rows']), 1)
        self.assertFalse(result['data']['coverage']['complete'])

    def test_raw_backlink_envelopes_cannot_break_history(self):
        base = state_dir(self.root)
        atomic_json(base / 'backlinks/raw.json', {'lane': 'backlinks', 'data': {}, 'collected_at': '9999'})
        for index in range(2): backlink_tracker.ingest(self.root, {'rows': []}, 'bing_webmaster', 'root', snapshot=str(index))
        self.assertEqual(backlink_tracker.latest(self.root)['status'], 'ok')

    def test_gsc_rank_collection_creates_real_history_consumed_by_report(self):
        schedule = state_dir(self.root) / 'schedule.json'
        atomic_json(schedule, {'jobs': [{'lane': 'gsc_ranks', 'interval_seconds': 3600}]})
        def collect(root, lane, **kw):
            return {'site': 'example.com', 'lane': lane, 'status': 'ok', 'collected_at': '2026-09-17T00:00:00Z',
                    'data': {'rows': [{'query': 'good software', 'country': 'usa', 'device': 'MOBILE', 'position': 5}]}}
        self.assertEqual(seo_runner.tick(self.root, now=10000, run_collector=collect)['status'], 'ok')
        self.assertEqual(len(rank_tracker.snapshots(self.root)), 1)
        row = json.loads(rank_tracker.snapshots(self.root)[0].read_text())['observations'][0]
        self.assertEqual(row['observation_type'], 'gsc_average_position')
        self.assertEqual(row['language'], 'not-reported')
        self.assertEqual(row['market'], 'usa')
        self.assertIn('rank_movement', reporting.analyze(self.root))

    def test_changed_host_scope_makes_metrics_incomparable(self):
        a = {'site': 'example.com', 'lane': 'gsc', 'status': 'ok', 'hostname_scope': ['example.com'], 'data': {}}
        b = {**a, 'hostname_scope': ['www.example.com']}
        self.assertEqual(reporting.metric_changes(a, b)['status'], 'not_comparable')

    def test_content_approval_binds_path_and_config(self):
        result = content_queue.propose(self.root, 'item', path='content/a.md', content='Reviewed content', url='https://example.com/a', evidence='source')
        content_queue.approve(self.root, 'item', content_sha256=result['content_sha256'], approval_ref='operator')
        path = content_queue.item_path(self.root, 'item'); data = json.loads(path.read_text())
        data['path'] = 'content/b.md'; atomic_json(path, data)
        with self.assertRaises(PermissionError): content_queue.apply(self.root, 'item')
        self.assertFalse((Path(self.root) / 'content/b.md').exists())


    def test_remote_config_drift_invalidates_approval(self):
        self.prepare_delivery()
        self.site['delivery']['host'] = 'other.example.com'; save_site(self.site, self.root)
        sender = Mock()
        with self.assertRaises(PermissionError): delivery.send(self.root, 'report', sender)
        sender.assert_not_called()

    def test_smtp_proposal_freezes_report_content(self):
        report = state_dir(self.root) / 'reports/test.md'; report.write_text('Original report', encoding='utf-8')
        result = delivery.prepare(self.root, 'report', report, 'operator'); actions.approve(self.root, 'report', result['request_sha256'], 'operator')
        report.write_text('Changed report', encoding='utf-8')
        sender = Mock(return_value={'status': 'accepted', 'kind': 'smtp_server_acceptance'})
        self.assertEqual(delivery.send(self.root, 'report', sender)['state'], 'succeeded')
        self.assertEqual(sender.call_args.args[1]['body'], 'Original report')
        self.assertTrue(delivery.send(self.root, 'report', sender)['duplicate']); self.assertEqual(sender.call_count, 1)

    def test_smtp_failure_is_not_silently_resent(self):
        report = state_dir(self.root) / 'reports/test.md'; report.write_text('Report', encoding='utf-8')
        result = delivery.prepare(self.root, 'report', report, 'operator'); actions.approve(self.root, 'report', result['request_sha256'], 'operator')
        sender = Mock(side_effect=TimeoutError)
        self.assertEqual(delivery.send(self.root, 'report', sender)['state'], 'uncertain')
        self.assertEqual(delivery.send(self.root, 'report', sender)['state'], 'uncertain'); self.assertEqual(sender.call_count, 1)

    def test_smtp_rejects_header_injection_and_foreign_file(self):
        with self.assertRaises(ValueError): delivery.address('a@example.com\nBcc: other@test.com')
        foreign = Path(self.root) / 'private.txt'; foreign.write_text('private')
        with self.assertRaises(ValueError): delivery.prepare(self.root, 'private', foreign, 'operator')

    def test_no_delivery_when_not_explicitly_enabled(self):
        self.assertEqual(delivery.deliver_latest(self.root)['state'], 'not_configured')

    def test_authenticated_transport_rejects_http_and_userinfo(self):
        for origin in ('http://api.example.com', 'https://secret@api.example.com', 'https://api.example.com/elsewhere'):
            with self.assertRaises(ValueError): authenticated_http.request(origin, 'GET', '/path')

    def serp_config(self, budget='0.1'):
        self.site['policy'].update(allowed_paid_providers=['dataforseo'], monthly_serp_budget_usd=budget)
        self.site['serp'] = {'provider': 'dataforseo', 'keywords': ['good software'], 'location_code': 2840,
                            'language_code': 'en', 'device': 'desktop', 'os': 'windows', 'depth': 10, 'reserve_per_request_usd': '0.02'}
        save_site(self.site, self.root)

    def serp_response(self):
        return {'status_code': 20000, 'cost': .01, 'tasks': [{'status_code': 20000, 'data': {'device': 'desktop', 'os': 'windows', 'depth': 10}, 'result': [
            {'keyword': 'good software', 'location_code': 2840, 'language_code': 'en', 'items': [
                {'type': 'organic', 'url': 'https://example.com/', 'rank_group': 2, 'rank_absolute': 5}]}]}]}

    def test_serp_provider_is_opt_in(self):
        with self.assertRaises(PermissionError): serp_collect.collect(self.root, 'r1', transport=Mock())

    def test_serp_uses_organic_rank_and_caches_charged_request(self):
        self.serp_config(); transport = Mock(return_value=self.serp_response())
        result = serp_collect.collect(self.root, 'r1', transport)
        self.assertEqual(result['rows'][0]['position'], 2)
        self.assertEqual(result['rows'][0]['observation_type'], 'serp_rank')
        again = serp_collect.collect(self.root, 'r1', transport)
        self.assertTrue(again['receipts'][0]['cached']); self.assertEqual(transport.call_count, 1)

    def test_serp_budget_denies_request_before_network(self):
        self.serp_config(budget='0.005'); transport = Mock()
        result = serp_collect.collect(self.root, 'r1', transport)
        transport.assert_not_called(); self.assertEqual(result['status'], 'partial')

    def test_serp_timeout_reservation_is_not_replayed(self):
        self.serp_config(); transport = Mock(side_effect=TimeoutError)
        self.assertEqual(serp_collect.collect(self.root, 'r1', transport)['status'], 'partial')
        self.assertEqual(serp_collect.collect(self.root, 'r1', transport)['status'], 'partial')
        self.assertEqual(transport.call_count, 1)

    def test_serp_wrong_location_cannot_create_rank(self):
        self.serp_config(); data = self.serp_response(); data['tasks'][0]['result'][0]['location_code'] = 123
        with self.assertRaises(ValueError): serp_collect.normalize_response(load(self.root), self.site['serp'], 'good software', data)

    def test_serp_no_match_is_sample_absence_not_global_loss(self):
        self.serp_config(); data = self.serp_response(); data['tasks'][0]['result'][0]['items'] = []
        result = serp_collect.normalize_response(load(self.root), self.site['serp'], 'good software', data)
        self.assertEqual(result['status'], 'checked_not_found'); self.assertIsNone(result['position']); self.assertEqual(result['search_depth'], 10)

    def test_serp_negative_and_nonfinite_budgets_rejected(self):
        for value in ('NaN', '-1', 'Infinity'):
            with self.assertRaises(ValueError): serp_collect.micros(value)

    def test_smtp_starttls_precedes_login_and_quit_failure_keeps_receipt(self):
        self.site['delivery'].update(security='starttls', port=587,
            username_env='TEST_SMTP_USER', password_env='TEST_SMTP_PASS')
        events = []
        server = Mock()
        for name in ('ehlo', 'starttls', 'login'):
            getattr(server, name).side_effect = lambda *a, n=name, **kw: events.append(n)
        server.send_message.return_value = {}
        server.quit.side_effect = OSError('disconnect after acknowledgement')
        with patch.dict(os.environ, {'TEST_SMTP_USER':'fixture', 'TEST_SMTP_PASS':'test-only'}), patch.object(delivery.smtplib, 'SMTP', return_value=server):
            result = delivery.smtp_send(self.site, {'from':'report@example.com', 'to':['owner@example.com'], 'subject':'Report', 'body':'Facts'}, 'test')
        self.assertEqual(events, ['ehlo','starttls','ehlo','login'])
        self.assertEqual(result['status'], 'accepted')
        self.assertFalse(result['inbox_delivery_confirmed'])
        server.close.assert_called_once()

    def test_smtp_partial_recipient_receipt_is_not_replayed(self):
        report = state_dir(self.root) / 'reports/test.md'; report.write_text('Report', encoding='utf-8')
        prepared = delivery.prepare(self.root, 'report', report, 'operator')
        actions.approve(self.root, 'report', prepared['request_sha256'], 'operator')
        sender = Mock(return_value={'kind':'smtp_server_acceptance', 'status':'partial'})
        self.assertEqual(delivery.send(self.root, 'report', sender)['state'], 'partial')
        self.assertTrue(delivery.send(self.root, 'report', sender)['duplicate'])
        sender.assert_called_once()

    def test_automatic_delivery_recovers_preapproval_crash(self):
        self.site['delivery']['auto_send_reports'] = True; save_site(self.site, self.root)
        report = state_dir(self.root) / 'reports/latest-run.md'; report.write_text('Report', encoding='utf-8')
        with patch.object(actions, 'approve', side_effect=SystemExit('simulated process stop')):
            with self.assertRaises(SystemExit): delivery.deliver_latest(self.root)
        with patch.object(delivery, 'send', return_value={'state':'succeeded'}) as send:
            self.assertEqual(delivery.deliver_latest(self.root)['state'], 'succeeded')
        self.assertEqual(actions.read(self.root, send.call_args.args[1])['state'], 'approved')

    def test_process_death_after_write_marker_never_replays_delivery(self):
        self.prepare_delivery()
        with self.assertRaises(SystemExit):
            actions.execute(self.root, 'report', 'delivery', Mock(side_effect=SystemExit('crash')))
        sender = Mock()
        result = actions.execute(self.root, 'report', 'delivery', sender)
        self.assertEqual(result['state'], 'uncertain'); sender.assert_not_called()


    def test_authenticated_http_does_not_redirect_tokens(self):
        response = Mock(status=302); response.read.return_value = b'{"error":"redirect"}'
        connection = Mock(); connection.getresponse.return_value = response
        with patch.object(authenticated_http, 'public_address', return_value='93.184.216.34'), patch.object(authenticated_http, 'PinnedHTTPS', return_value=connection):
            with self.assertRaises(RuntimeError):
                authenticated_http.request('https://api.example.com', 'GET', '/read', headers={'Authorization':'Bearer private'})
        connection.request.assert_called_once(); connection.close.assert_called_once()

    def test_serp_overrun_pauses_future_paid_requests(self):
        self.serp_config(); data = self.serp_response(); data['cost'] = .03
        transport = Mock(return_value=data)
        self.assertEqual(serp_collect.collect(self.root, 'r1', transport)['status'], 'partial')
        result = serp_collect.collect(self.root, 'r2', transport)
        self.assertEqual(result['status'], 'partial'); self.assertEqual(transport.call_count, 1)
        self.assertIn('paused', result['failures'][0]['reason'])

    def test_serp_wrong_device_echo_cannot_create_rank(self):
        self.serp_config(); data = self.serp_response(); data['tasks'][0]['data']['device'] = 'mobile'
        with self.assertRaises(ValueError): serp_collect.normalize_response(load(self.root), self.site['serp'], 'good software', data)

    def test_interleaved_gsc_and_serp_snapshots_compare_within_stream(self):
        common = {'market':'US', 'language':'en', 'device':'desktop'}
        for name, provider, position in [('1','google_gsc',8),('2','dataforseo',5),('3','google_gsc',7),('4','dataforseo',3)]:
            rank_tracker.ingest(self.root, [{'query':'viewer','position':position}], {**common,'snapshot':name,'provider':provider})
        result = rank_tracker.compare(self.root)
        self.assertEqual(result['status'],'ok'); self.assertEqual(len(result['streams']),2)
        self.assertEqual(sorted(x['position_improvement'] for x in result['changes']),[1,2])

    def test_renamed_remote_action_does_not_reuse_approval(self):
        self.prepare_delivery()
        row = actions.read(self.root, 'report'); row['id'] = 'another'
        atomic_json(actions.path_for(self.root, 'another'), row)
        sender = Mock()
        with self.assertRaises(PermissionError): delivery.send(self.root, 'another', sender)
        sender.assert_not_called()

    def test_changed_measurement_window_length_is_not_comparable(self):
        first = {'site':'example.com','lane':'gsc','status':'ok','data':{'date_range':{'start':'2026-01-01','end':'2026-01-07'},'totals':{'clicks':7}}}
        second = copy.deepcopy(first); second['data']['date_range']['end']='2026-01-28'
        self.assertEqual(reporting.metric_changes(first, second)['status'],'not_comparable')

    def test_mcp_cannot_smuggle_paid_lane_past_schema(self):
        with patch.dict(os.environ, {'SEO_PROJECT_ROOTS':self.root}), patch.object(mcp_server,'collect') as collect:
            with self.assertRaises(ValueError): mcp_server.call('seo_collect', {'root':self.root,'lane':'serp'})
        collect.assert_not_called()

    def test_mcp_uses_normalized_backlinks_not_raw_collections(self):
        for stamp in ('a','b'):
            backlink_tracker.ingest(self.root, {'rows':[]}, 'bing_webmaster', 'https://example.com/', stamp)
        atomic_json(state_dir(self.root)/'backlinks/raw.json', {'lane':'backlinks','data':{}})
        with patch.dict(os.environ, {'SEO_PROJECT_ROOTS':self.root}):
            self.assertEqual(mcp_server.call('seo_backlink_changes', {'root':self.root})['status'],'ok')

    def test_new_cli_commands_work_from_unrelated_directory(self):
        for command in ('deliver', 'serp'):
            result = subprocess.run([sys.executable, str(ROOT / 'seo.py'), command, '--help'], cwd=self.root, capture_output=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
