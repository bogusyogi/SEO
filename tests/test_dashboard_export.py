import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import dashboard_export as exporter


class DashboardExportTests(unittest.TestCase):
    def env(self, data, lane='gsc', status='ok', stamp='2026-09-22T00:00:00Z'):
        return {'site': 'example.com', 'lane': lane, 'status': status, 'collected_at': stamp, 'data': data}

    def test_missing_explicit_zero_and_incomplete_aggregate_are_distinct(self):
        self.assertIsNone(exporter._gsc(None)['metrics']['clicks'])
        result = exporter._gsc(self.env({'aggregate': {'clicks': 0}, 'rows': []}))
        self.assertEqual(result['metrics']['clicks'], 0)
        self.assertIsNone(result['metrics']['impressions'])
        self.assertIsNone(result['metrics']['position'])
        self.assertEqual(exporter._bing(self.env({'d': []}, 'bing'))['status'], 'no_data')
        self.assertIsNone(exporter._bing(self.env({'d': []}, 'bing'))['metrics']['clicks'])

    def test_failed_responses_do_not_expose_partial_totals(self):
        for normalizer, data in [(exporter._gsc, {'aggregate': {'clicks': 99}, 'rows': [{'query': 'hidden'}]}), (exporter._ga4, {'totals': {'sessions': 99}}), (exporter._bing, {'d': [{'Date': '/Date(1735776000000)/', 'Clicks': 99, 'Impressions': 100}]})]:
            result = normalizer(self.env(data, status='failed'))
            self.assertEqual(result['status'], 'failed')
            self.assertTrue(all(value is None for value in result['metrics'].values()))

    def test_bing_dates_period_sort_and_nullable_fields(self):
        result = exporter._bing(self.env({'d': [{'Date': '/Date(1735862400000)/', 'Clicks': 0, 'Impressions': 0}, {'Date': '/Date(1735776000000)/', 'Clicks': 2, 'Impressions': 3}]}, 'bing'))
        self.assertEqual(result['date_range'], {'start': '2025-01-02', 'end': '2025-01-03'})
        self.assertEqual(result['daily'][0]['date'], '2025-01-02')
        self.assertEqual(result['metrics']['clicks'], 2)
        missing = exporter._bing(self.env({'d': [{'Date': '/Date(1735776000000)/', 'Clicks': None, 'Impressions': 0}]}, 'bing'))
        self.assertIsNone(missing['metrics']['clicks'])
        self.assertEqual(missing['metrics']['impressions'], 0)

    def test_actual_audit_structure_and_scoped_backlinks(self):
        result = exporter._simple(self.env({'crawled': 2, 'coverage': {'complete': False}, 'issues': {'thin_content': ['https://example.com/ (134w)'], 'title_too_long': ['https://example.com/p']}, 'severity': {'warnings': ['thin_content'], 'errors': []}}, 'audit'), 'audit')
        self.assertFalse(result['complete'])
        self.assertEqual(result['issues'][0]['severity'], 'warnings')
        self.assertEqual(result['issues'][0]['count'], 1)
        self.assertEqual(exporter._simple(self.env({'rows': []}, 'backlinks'), 'backlinks')['count'], 0)
        self.assertIsNone(exporter._simple(None, 'backlinks')['count'])

    def test_newest_failure_identity_and_valid_timestamp(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); lane = root / '.seo' / 'gsc'; lane.mkdir(parents=True)
            (root / '.seo' / 'site.yaml').write_text(json.dumps({'domain': 'example.com'}), encoding='utf-8')
            entries = [self.env({'aggregate': {'clicks': 1}}, stamp='2026-09-20T00:00:00Z'), self.env({}, status='failed'), {**self.env({}), 'site': 'other.com', 'collected_at': '2026-09-23T00:00:00Z'}, self.env({}, lane='bing', stamp='2026-09-24T00:00:00Z'), self.env({}, stamp='2026-09-25')]
            for index, value in enumerate(entries): (lane / f'{index}.json').write_text(json.dumps(value), encoding='utf-8')
            self.assertEqual(exporter._latest(root, 'gsc')['status'], 'failed')
            self.assertEqual(len(exporter._envelopes(root, 'gsc')), 2)

    def test_coverage_allowlist_and_nonfinite_numbers(self):
        result = exporter._gsc(self.env({'aggregate': {'clicks': float('nan')}, 'coverage': {'row_count': 0, 'complete': {'secret': 'injected'}, 'token': 'injected', 'path': 'C:/private'}}))
        self.assertEqual(result['coverage'], {'row_count': 0})
        self.assertIsNone(result['metrics']['clicks'])
        self.assertNotIn('injected', json.dumps(result))

    def test_performance_sidecar_nested_mobile_and_latest_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            reports = Path(temp); folder = reports / 'performance-baseline-2026-09-22'; folder.mkdir()
            main = folder / 'example-com.json'
            main.write_text(json.dumps({'site': 'example.com', 'captured_at': '2026-09-22', 'psi': {'status': 'response_not_persisted'}, 'crux': {'status': 'no_data', 'error': 'No CrUX history'}}), encoding='utf-8')
            main.with_suffix('.psi.json').write_text(json.dumps({'psi': {'mobile': {'lighthouse_scores': {'performance': 65}, 'key_source': 'C:/secret'}}}), encoding='utf-8')
            result = exporter._performance(reports, 'example.com')
            self.assertEqual(result['status'], 'ok'); self.assertEqual(result['scores']['performance'], 65)
            self.assertEqual(result['crux_status'], 'no_data'); self.assertNotIn('secret', json.dumps(result))
            newer = reports / 'performance-weekly-2026-09-28'; newer.mkdir()
            (newer / 'example-com.json').write_text(json.dumps({'site': 'example.com', 'captured_at': '2026-09-28T00:00:00Z', 'status': 'failed', 'psi': {'error': 'quota'}, 'crux': {'error': 'quota'}}), encoding='utf-8')
            result = exporter._performance(reports, 'example.com')
            self.assertEqual(result['status'], 'failed'); self.assertIsNone(result['scores']['performance']); self.assertEqual(result['crux_status'], 'failed')

    def test_history_modes_relative_roots_and_unreadable_site(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); root = base / 'site'; lane = root / '.seo' / 'gsc'; lane.mkdir(parents=True)
            (root / '.seo' / 'site.yaml').write_text(json.dumps({'domain': 'example.com', 'measurement_setup': {'gsc_direct_read': 'verified', 'source_root_verified': False, 'ga4_event_arrival': 'not_yet_verified'}}), encoding='utf-8')
            for index in range(2): (lane / f'{index}.json').write_text(json.dumps(self.env({'date_range': {'start': '2026-08-23', 'end': '2026-09-19'}, 'aggregate': {'clicks': index}}, stamp=f'2026-09-2{index}T00:00:00Z')), encoding='utf-8')
            portfolio = base / 'portfolio.json'; portfolio.write_text(json.dumps({'roots': ['site', 'unreadable']}), encoding='utf-8')
            result = exporter.build_snapshot(portfolio, base / 'reports')
            site = result['sites'][0]
            self.assertEqual(site['mode'], 'monitoring'); self.assertEqual(site['ga4']['event_arrival'], 'not_yet_verified')
            self.assertEqual(len(site['gsc']['history']), 1); self.assertEqual(site['gsc']['history'][0]['clicks'], 1)
            self.assertEqual(result['sites'][1]['gsc']['status'], 'missing')
            self.assertNotIn(str(base), json.dumps(result))

    def test_interrupted_and_invalid_write_preserves_existing_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'portfolio.json'; output.write_text('original', encoding='utf-8')
            with patch.object(exporter.os, 'replace', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError): exporter.write_snapshot({'sites': []}, output)
            self.assertEqual(output.read_text(), 'original')
            self.assertEqual(list(Path(temp).glob('*.tmp')), [])
            with self.assertRaises(ValueError): exporter.write_snapshot({'number': float('nan')}, output)
            self.assertEqual(output.read_text(), 'original')


if __name__ == '__main__':
    unittest.main()
