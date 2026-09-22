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


class LaneRegistrationTests(unittest.TestCase):
    def test_new_lanes_are_registered_for_scheduling(self):
        import seo_runner
        self.assertIn('gsc_sitemaps', seo_runner.LANES)
        self.assertIn('bing_crawl', seo_runner.LANES)

    def test_new_lanes_are_read_only_actions(self):
        import site_policy
        self.assertIn('gsc_sitemaps', site_policy.READ_ACTIONS)
        self.assertIn('bing_crawl', site_policy.READ_ACTIONS)


if __name__ == '__main__':
    unittest.main()
