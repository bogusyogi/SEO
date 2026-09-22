"""Fixture-based tests for the signals-expansion collectors: gsc_sitemaps, bing_crawl.

No live network calls. Subprocess/API responses are mocked with recorded-shape fixtures.
"""
from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import collector
from seo_project import setup_project


def make_site(root):
    return setup_project(root, domain='example.com', market='US', language='en',
                          gsc_property='sc-domain:example.com', ga4_property='123',
                          bing_site='https://example.com/')


class GscSitemapsLaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_site(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_ok_sitemaps_response_is_ok_status(self):
        fixture = {'property': 'sc-domain:example.com', 'error': None, 'sitemaps': [
            {'path': 'https://example.com/sitemap.xml', 'last_submitted': '2026-09-01T00:00:00Z',
             'is_pending': False, 'is_index': True, 'type': 'sitemap', 'warnings': 0, 'errors': 0,
             'contents': [{'type': 'web', 'submitted': 40, 'indexed': 38}]}]}
        with patch.object(collector, 'run_json', return_value=(fixture, 0)):
            result = collector.collect(self.root, 'gsc_sitemaps')
        self.assertEqual(result['status'], 'ok')
        self.assertIsNone(result['error'])
        self.assertEqual(result['data']['sitemaps'][0]['errors'], 0)

    def test_measured_zero_no_sitemaps_registered_is_ok_not_missing(self):
        fixture = {'property': 'sc-domain:example.com', 'error': None, 'sitemaps': []}
        with patch.object(collector, 'run_json', return_value=(fixture, 0)):
            result = collector.collect(self.root, 'gsc_sitemaps')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['data']['sitemaps'], [])

    def test_api_error_is_partial_not_a_silent_zero(self):
        fixture = {'property': 'sc-domain:example.com', 'error': 'HTTP 403', 'sitemaps': []}
        with patch.object(collector, 'run_json', return_value=(fixture, 0)):
            result = collector.collect(self.root, 'gsc_sitemaps')
        self.assertEqual(result['status'], 'partial')
        self.assertIsNotNone(result['error'])

    def test_property_mismatch_is_rejected(self):
        fixture = {'property': 'sc-domain:other.com', 'error': None, 'sitemaps': []}
        with patch.object(collector, 'run_json', return_value=(fixture, 0)):
            result = collector.collect(self.root, 'gsc_sitemaps')
        self.assertEqual(result['status'], 'failed')


class BingCrawlLaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_site(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_ok_response_with_issues(self):
        fixture = ({'method': 'GetCrawlIssues', 'error': None, 'd': [
            {'Url': 'https://example.com/broken', 'IssueType': 'NotFound',
             'Severity': 'high', 'DetectedDate': '/Date(1758000000000)/'}]}, 0)
        with patch.object(collector, 'run_json', return_value=fixture):
            result = collector.collect(self.root, 'bing_crawl')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['data']['issue_count'], 1)
        self.assertFalse(result['data']['measured_zero'])

    def test_measured_zero_no_crawl_issues_is_ok_not_missing(self):
        fixture = ({'method': 'GetCrawlIssues', 'error': None, 'd': []}, 0)
        with patch.object(collector, 'run_json', return_value=fixture):
            result = collector.collect(self.root, 'bing_crawl')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['data']['issue_count'], 0)
        self.assertTrue(result['data']['measured_zero'])
        self.assertIsNone(result['error'])

    def test_null_payload_treated_as_measured_zero_list(self):
        fixture = ({'method': 'GetCrawlIssues', 'error': None, 'd': None}, 0)
        with patch.object(collector, 'run_json', return_value=fixture):
            result = collector.collect(self.root, 'bing_crawl')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['data']['issue_count'], 0)

    def test_missing_api_key_is_failed_not_zero(self):
        fixture = ({'error': 'BING_API_KEY not set', 'method': 'GetCrawlIssues'}, 2)
        with patch.object(collector, 'run_json', return_value=fixture):
            result = collector.collect(self.root, 'bing_crawl')
        self.assertEqual(result['status'], 'failed')
        self.assertIsNotNone(result['data'].get('error'))
        self.assertIsNone(result['data'].get('issue_count'))

    def test_unexpected_shape_is_failed_not_zero(self):
        fixture = ({'method': 'GetCrawlIssues', 'error': None, 'd': {'unexpected': True}}, 0)
        with patch.object(collector, 'run_json', return_value=fixture):
            result = collector.collect(self.root, 'bing_crawl')
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['data'].get('issue_count'))

    def test_subprocess_timeout_is_failed(self):
        import subprocess
        with patch.object(collector, 'run_json', side_effect=subprocess.TimeoutExpired(cmd='x', timeout=1)):
            result = collector.collect(self.root, 'bing_crawl')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['data']['status'], 'failed')


class GscAppearanceLaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_site(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_ok_appearance_dimensions_response(self):
        fixture = {'schema_version': 2, 'property': 'sc-domain:example.com', 'error': None,
                   'dimensions': ['searchAppearance', 'device', 'country'],
                   'rows': [{'searchAppearance': 'AMP_BLUE_LINK', 'device': 'MOBILE', 'country': 'usa',
                             'clicks': 3, 'impressions': 50}],
                   'coverage': {'hit_client_cap': False}}
        with patch.object(collector, 'run_json', return_value=(fixture, 0)):
            result = collector.collect(self.root, 'gsc_appearance')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['data']['dimensions'], ['searchAppearance', 'device', 'country'])

    def test_property_mismatch_is_rejected(self):
        fixture = {'property': 'sc-domain:other.com', 'rows': [], 'coverage': {}}
        with patch.object(collector, 'run_json', return_value=(fixture, 0)):
            result = collector.collect(self.root, 'gsc_appearance')
        self.assertEqual(result['status'], 'failed')


class Ga4SanityMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_site(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_sanity_report_merged_alongside_organic(self):
        organic = {'property': 'properties/123', 'report': 'organic_traffic', 'error': None, 'totals': {}}
        sanity = {'property': 'properties/123', 'report': 'all_channels_sanity', 'error': None,
                  'totals': {'sessions': 100, 'total_users': 80, 'event_count': 500}, 'measured_zero': False}
        with patch.object(collector, 'run_json', side_effect=[(organic, 0), (sanity, 0)]):
            result = collector.collect(self.root, 'ga4')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['data']['all_channels_sanity']['totals']['sessions'], 100)

    def test_zero_organic_distinguished_from_zero_everything(self):
        organic = {'property': 'properties/123', 'report': 'organic_traffic', 'error': None,
                   'totals': {'sessions': 0}}
        sanity_all_zero = {'property': 'properties/123', 'totals': {'sessions': 0, 'total_users': 0, 'event_count': 0},
                            'measured_zero': True, 'error': None}
        with patch.object(collector, 'run_json', side_effect=[(organic, 0), (sanity_all_zero, 0)]):
            result = collector.collect(self.root, 'ga4')
        self.assertTrue(result['data']['all_channels_sanity']['measured_zero'])
        sanity_nonzero = {'property': 'properties/123', 'totals': {'sessions': 40, 'total_users': 30, 'event_count': 200},
                           'measured_zero': False, 'error': None}
        with patch.object(collector, 'run_json', side_effect=[(organic, 0), (sanity_nonzero, 0)]):
            result2 = collector.collect(self.root, 'ga4')
        self.assertFalse(result2['data']['all_channels_sanity']['measured_zero'])


class CruxAndPagespeedLaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_site(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_crux_history_ok(self):
        fixture = {'target': 'https://example.com', 'form_factor': 'ALL', 'metrics': {'largest_contentful_paint': {}},
                   'collection_periods': [{'firstDate': {}, 'lastDate': {}}], 'trends': {}, 'error': None}
        with patch.object(collector, 'run_json', return_value=(fixture, 0)):
            result = collector.collect(self.root, 'crux_history')
        self.assertEqual(result['status'], 'ok')

    def test_crux_history_missing_api_key_is_not_zero(self):
        with patch.object(collector, 'run_json', side_effect=ValueError('Expecting value')):
            result = collector.collect(self.root, 'crux_history')
        self.assertEqual(result['status'], 'failed')

    def test_pagespeed_ok(self):
        fixture = {'url': 'https://example.com', 'psi': {'mobile': {'error': None}}, 'crux': None, 'error': None}
        with patch.object(collector, 'run_json', return_value=(fixture, 0)):
            result = collector.collect(self.root, 'pagespeed')
        self.assertEqual(result['status'], 'ok')

    def test_pagespeed_error_is_partial_not_zero(self):
        fixture = {'url': 'https://example.com', 'psi': {'mobile': {'error': 'quota exceeded'}},
                   'crux': None, 'error': 'quota exceeded'}
        with patch.object(collector, 'run_json', return_value=(fixture, 0)):
            result = collector.collect(self.root, 'pagespeed')
        self.assertEqual(result['status'], 'partial')


class GscInspectBulkLaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_site(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_top_pages_and_sitemap_urls_combined_and_capped(self):
        top_pages = {'property': 'sc-domain:example.com', 'error': None, 'rows': [
            {'page': 'https://example.com/a', 'impressions': 500},
            {'page': 'https://example.com/b', 'impressions': 900},
        ]}
        inspect_result = {'total': 2, 'results': [
            {'url': 'https://example.com/b', 'verdict': 'PASS', 'error': None},
            {'url': 'https://example.com/a', 'verdict': 'PASS', 'error': None},
        ], 'summary': {'pass': 2, 'fail': 0, 'neutral': 0, 'error': 0}, 'error': None}
        import site_audit
        with patch.object(collector, 'run_json', side_effect=[(top_pages, 0), (inspect_result, 0)]), \
             patch.object(site_audit, 'get', return_value=(200, 'https://example.com/robots.txt', '', {})), \
             patch.object(site_audit, 'discover_sitemaps', return_value=[]), \
             patch.object(site_audit, 'sitemap_urls', return_value=set()):
            result = collector.collect(self.root, 'gsc_inspect_bulk')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['data']['candidate_sources']['from_top_impression_pages'], 2)
        self.assertEqual(result['data']['candidate_sources']['inspected'], 2)

    def test_offsite_urls_are_excluded(self):
        top_pages = {'property': 'sc-domain:example.com', 'error': None, 'rows': [
            {'page': 'https://not-example.com/a', 'impressions': 999},
        ]}
        import site_audit
        with patch.object(collector, 'run_json', return_value=(top_pages, 0)), \
             patch.object(site_audit, 'get', return_value=(200, 'https://example.com/robots.txt', '', {})), \
             patch.object(site_audit, 'discover_sitemaps', return_value=[]), \
             patch.object(site_audit, 'sitemap_urls', return_value=set()):
            result = collector.collect(self.root, 'gsc_inspect_bulk')
        self.assertEqual(result['data']['candidate_sources']['considered_in_scope'], 0)

    def test_inspect_max_urls_bounds_enforced(self):
        site_yaml = self.root / '.seo' / 'site.yaml'
        import json as _json
        payload = _json.loads(site_yaml.read_text(encoding='utf-8'))
        payload['inspect_max_urls'] = 0
        site_yaml.write_text(_json.dumps(payload), encoding='utf-8')
        result = collector.collect(self.root, 'gsc_inspect_bulk')
        self.assertEqual(result['status'], 'failed')


class SitemapProbeLaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_site(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_robots_declares_sitemap(self):
        import site_audit
        robots = 'User-agent: *\nSitemap: https://example.com/sitemap.xml\n'
        with patch.object(site_audit, 'get', side_effect=[
                (200, 'https://example.com/robots.txt', robots, {}),
                (200, 'https://example.com/sitemap.xml', '<urlset></urlset>', {})]):
            result = collector.collect(self.root, 'sitemap_probe')
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(result['data']['robots_declares_sitemap'])
        self.assertTrue(result['data']['default_sitemap_xml_reachable'])
        self.assertFalse(result['data']['measured_zero'])

    def test_no_sitemap_anywhere_is_measured_zero_not_missing(self):
        import site_audit
        with patch.object(site_audit, 'get', side_effect=[
                (200, 'https://example.com/robots.txt', 'User-agent: *\n', {}),
                (404, 'https://example.com/sitemap.xml', '', {})]):
            result = collector.collect(self.root, 'sitemap_probe')
        self.assertEqual(result['status'], 'ok')
        self.assertFalse(result['data']['robots_declares_sitemap'])
        self.assertFalse(result['data']['default_sitemap_xml_reachable'])
        self.assertTrue(result['data']['measured_zero'])

    def test_robots_fetch_failure_is_partial_not_zero(self):
        import site_audit
        with patch.object(site_audit, 'get', side_effect=[
                (0, 'https://example.com/robots.txt', 'ConnectionError', {}),
                (0, 'https://example.com/sitemap.xml', 'ConnectionError', {})]):
            result = collector.collect(self.root, 'sitemap_probe')
        self.assertEqual(result['status'], 'partial')


class SiteAuditStructuredDataTests(unittest.TestCase):
    def test_jsonld_type_extracted(self):
        import site_audit
        html = '<html><head><script type="application/ld+json">{"@type":"Article","@context":"https://schema.org"}</script></head><body></body></html>'
        sig, _ = site_audit.parse(html)
        self.assertEqual(sig['jsonld_types'], ['Article'])
        self.assertTrue(sig['jsonld_present'])
        self.assertEqual(sig['jsonld_invalid_blocks'], 0)

    def test_invalid_jsonld_block_counted_not_dropped_silently(self):
        import site_audit
        html = '<script type="application/ld+json">{not valid json</script>'
        sig, _ = site_audit.parse(html)
        self.assertEqual(sig['jsonld_invalid_blocks'], 1)
        self.assertTrue(sig['jsonld_present'])

    def test_no_structured_data_is_measured_absence(self):
        import site_audit
        sig, _ = site_audit.parse('<html><body>hello</body></html>')
        self.assertFalse(sig['jsonld_present'])
        self.assertEqual(sig['jsonld_types'], [])

    def test_hreflang_extracted(self):
        import site_audit
        html = '<link rel="alternate" hreflang="es" href="https://example.com/es/"><link rel="alternate" hreflang="x-default" href="https://example.com/">'
        sig, _ = site_audit.parse(html)
        self.assertEqual(sig['hreflang']['es'], 'https://example.com/es/')

    def test_robots_meta_and_nofollow_extracted(self):
        import site_audit
        html = '<meta name="robots" content="noindex, nofollow">'
        sig, _ = site_audit.parse(html)
        self.assertIn('noindex, nofollow', sig['robots_meta'])
        self.assertTrue(sig['nofollow'])
        self.assertTrue(sig['noindex'])


class LaneRegistrationTests(unittest.TestCase):
    def test_new_lanes_are_registered_for_scheduling(self):
        import seo_runner
        for lane in ('gsc_sitemaps', 'bing_crawl', 'gsc_appearance', 'gsc_inspect_bulk',
                     'sitemap_probe', 'crux_history', 'pagespeed'):
            self.assertIn(lane, seo_runner.LANES)

    def test_new_lanes_are_read_only_actions(self):
        import site_policy
        for lane in ('gsc_sitemaps', 'bing_crawl', 'gsc_appearance', 'gsc_inspect_bulk',
                     'sitemap_probe', 'crux_history', 'pagespeed'):
            self.assertIn(lane, site_policy.READ_ACTIONS)


if __name__ == '__main__':
    unittest.main()
