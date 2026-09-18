"""Readiness regressions: real scope/period metadata must govern operator reports."""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import collector
import measurement_scope as scope
import rank_tracker as ranks
import reporting
import seo_runner
from seo_project import setup_project, save_site
from seo_state import state_dir, atomic_json

NOW = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)


def envelope(*, start='2026-08-19', end='2026-09-15', stamp='2026-09-19T10:00:00Z',
             position=5, status='ok', lane='gsc_ranks'):
    return {'site': 'example.com', 'lane': lane, 'status': status, 'collected_at': stamp,
            'hostname_scope': ['example.com'], 'collection_route': 'standalone_direct',
            'data': {'property': 'sc-domain:example.com', 'search_type': 'web',
                'time_zone': 'America/Los_Angeles', 'data_state': 'final',
                'dimensions': ['query', 'country', 'device'],
                'aggregation_type': 'byPage', 'filters': [scope.gsc_host_filter(['example.com'])],
                'date_range': {'start': start, 'end': end},
                'aggregate': {'clicks': 0, 'impressions': 100, 'position': position},
                'coverage': {'hit_client_cap': False, 'complete': None},
                'rows': [{'query': 'useful software', 'country': 'usa', 'device': 'MOBILE',
                          'position': position}]}}


def earlier():
    return envelope(start='2026-07-22', end='2026-08-18',
                    stamp='2026-09-18T10:00:00Z', position=10)


class MeasurementReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.site = setup_project(self.root, domain='example.com', market='US', language='en',
                                  gsc_property='sc-domain:example.com', ga4_property='123')

    def tearDown(self):
        self.temp.cleanup()

    def store(self, row, name):
        atomic_json(state_dir(self.root) / row['lane'] / (name+'.json'), row)
        return collector.persist_observations(self.root, row, name)

    def pair(self, current=None):
        self.store(earlier(), 'previous')
        self.store(current or envelope(), 'current')
        return ranks.compare(self.root)

    def test_rank_persistence_retains_exact_nonsecret_measurement(self):
        row = envelope()
        row['credentials'] = {'access_token': 'must-not-be-copied'}
        path = self.store(row, 'sample')['rank_snapshot']
        stored = json.loads(Path(path).read_text())
        self.assertEqual(stored['measurement'], scope.measurement_context(row))
        self.assertEqual(stored['coverage'], row['data']['coverage'])
        self.assertEqual(stored['collected_at'], row['collected_at'])
        self.assertNotIn('must-not-be-copied', Path(path).read_text())

    def test_scoped_nonoverlapping_rank_change_is_usable(self):
        result = self.pair()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['changes'][0]['position_improvement'], 5)
        self.assertEqual(result['comparison_context']['overlap_days'], 0)

    def test_changed_property_cannot_be_rank_movement(self):
        row = envelope(); row['data']['property'] = 'https://example.com/'
        result = self.pair(row)
        self.assertEqual(result['status'], 'not_comparable')
        self.assertIn('property', result['reason']); self.assertEqual(result['changes'], [])

    def test_changed_hostname_cannot_be_rank_movement(self):
        row = envelope(); row['hostname_scope'] = ['www.example.com']
        self.assertEqual(self.pair(row)['status'], 'not_comparable')

    def test_changed_search_type_and_filter_cannot_be_rank_movement(self):
        for field, value in [('search_type', 'image'), ('filters', []),
                             ('aggregation_type', 'byProperty'), ('data_state', 'all'),
                             ('time_zone', 'UTC'), ('dimensions', ['query', 'device'])]:
            a, b = earlier(), envelope(); b['data'][field] = value
            result = scope.compare_contexts(scope.measurement_context(a), scope.measurement_context(b))
            self.assertEqual(result['status'], 'not_comparable', field)

    def test_known_and_legacy_rank_context_never_mix(self):
        ranks.ingest(self.root, [{'query': 'useful software', 'position': 10}],
            {'provider': 'google_gsc', 'market': 'usa', 'language': 'not-reported', 'device': 'MOBILE',
             'snapshot': 'old', 'collected_at': '2026-09-18T10:00:00Z'})
        self.store(envelope(), 'new')
        result = ranks.compare(self.root)
        self.assertEqual(result['status'], 'not_comparable')
        self.assertIn('context missing', result['reason'])

    def test_repeated_measurement_window_does_not_claim_movement(self):
        a = envelope(stamp='2026-09-18T10:00:00Z', position=10)
        self.store(a, 'before'); self.store(envelope(), 'after')
        result = ranks.compare(self.root)
        self.assertEqual(result['status'], 'not_comparable')
        self.assertIn('same measurement window', result['reason'])
        self.assertEqual(result['changes'], [])

    def test_rolling_window_reports_exact_overlap(self):
        a, b = earlier(), envelope(start='2026-07-29', end='2026-08-25')
        result = reporting.metric_changes(a, b)
        self.assertEqual(result['status'], 'ok'); self.assertEqual(result['overlap_days'], 21)
        self.assertIn('21 overlapping days', result['interpretation'])

    def test_reverse_missing_and_malformed_windows_are_not_movement(self):
        for dates in [None, {'start': 'no', 'end': 'no'}, {'start':'2026-09-15', 'end':'2026-08-19'},
                      {'start':'2026-06-24', 'end':'2026-07-21'}]:
            row = envelope(); row['data']['date_range'] = dates
            self.assertNotEqual(reporting.metric_changes(earlier(), row)['status'], 'ok')

    def test_dimension_and_hostname_order_does_not_change_scope(self):
        a, b = earlier(), envelope()
        a['hostname_scope'] = ['example.com', 'www.example.com']
        b['hostname_scope'] = ['www.example.com', 'EXAMPLE.COM']
        b['data']['dimensions'].reverse()
        self.assertEqual(reporting.metric_changes(a, b)['status'], 'ok')

    def test_connector_and_direct_collection_are_distinct_streams(self):
        a, b = earlier(), envelope(); b['collection_route'] = 'connector'
        self.assertEqual(reporting.metric_changes(a, b)['status'], 'not_comparable')

    def test_empty_current_gsc_batch_replaces_old_observations_not_losses(self):
        row = envelope(); row['data']['rows'] = []
        result = self.pair(row)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['changes'][0]['type'], 'missing_observation')
        self.assertNotIn('position_improvement', result['changes'][0])

    def test_missing_country_stream_does_not_reuse_older_success(self):
        self.store(earlier(), 'before')
        row = envelope(); row['data']['rows'][0]['country'] = 'ind'
        self.store(row, 'after'); result = ranks.compare(self.root)
        usa = next(s for s in result['streams'] if s['stream'][0] == 'usa')
        self.assertEqual(usa['changes'][0]['type'], 'missing_observation')

    def test_failed_or_partial_collection_is_persisted_as_barrier(self):
        self.pair()
        for index, status in enumerate(('failed', 'partial')):
            row = envelope(status=status, stamp=f'2026-09-19T1{index+1}:00:00Z')
            self.store(row, f'failure-{index}')
            result = ranks.compare(self.root)
            self.assertEqual(result['status'], 'not_testable'); self.assertEqual(result['changes'], [])

    def test_recovery_requires_two_usable_measurements(self):
        self.store(earlier(), 'old')
        self.store(envelope(status='failed'), 'failure')
        self.store(envelope(stamp='2026-09-19T11:00:00Z'), 'recovered')
        self.assertEqual(ranks.compare(self.root)['status'], 'not_testable')
        self.store(envelope(start='2026-08-20', end='2026-09-16', stamp='2026-09-19T12:00:00Z'), 'next')
        self.assertEqual(ranks.compare(self.root)['status'], 'ok')

    def test_cap_is_partial_and_cannot_feed_rank_changes(self):
        data = envelope()['data']; data['coverage']['hit_client_cap'] = True
        with patch.object(collector, 'run_json', return_value=(data, 0)):
            result = collector.collect(self.root, 'gsc_ranks')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['collection_route'], 'standalone_direct')

    def test_report_shows_single_baseline_and_unavailable_not_fake_zero(self):
        row = envelope(lane='gsc'); row['data']['aggregate']['ctr'] = None
        self.store(row, 'baseline')
        text = reporting.render('example.com', reporting.analyze(self.root, now=NOW))
        self.assertIn('clicks: 0 (recorded value', text)
        self.assertIn('impressions: 100 (recorded value', text)
        self.assertIn('ctr: unavailable', text)
        self.assertIn('2026-08-19', text); self.assertIn('sc-domain:example.com', text)
        self.assertIn('Coverage:', text)

    def test_zero_baseline_relative_change_is_unknown_not_infinite(self):
        result = reporting.metric_changes(earlier(), envelope())
        self.assertEqual(result['metrics']['clicks']['delta'], 0)
        self.assertIsNone(result['metrics']['clicks']['relative_percent'])

    def test_report_explains_blocked_metric_comparison(self):
        self.store(earlier() | {'lane': 'gsc'}, 'old')
        row = envelope(lane='gsc'); row['data']['property'] = 'https://example.com/'
        self.store(row, 'new')
        text = reporting.render('example.com', reporting.analyze(self.root, now=NOW))
        self.assertIn('not_comparable', text); self.assertIn('property changed', text)

    def test_stale_history_not_reported_as_current_movement(self):
        self.pair()
        result = reporting.analyze(self.root, now=datetime(2026, 10, 19, tzinfo=timezone.utc))
        self.assertEqual(result['rank_movement']['status'], 'not_testable')
        self.assertEqual(result['rank_movement']['changes'], [])
        self.assertEqual(result['lanes']['gsc_ranks']['freshness']['status'], 'stale')

    def test_freshness_requires_timezone_and_rejects_future_time(self):
        for value in (None, 'no', '2026-09-19T00:00:00', '2027-01-01T00:00:00Z'):
            self.assertNotEqual(reporting.freshness(value, now=NOW)['status'], 'current')

    def test_operator_can_set_report_freshness_budget(self):
        self.site['reporting'] = {'max_age_hours': 24}
        save_site(self.site, self.root)
        self.store(earlier() | {'lane': 'gsc'}, 'old')
        result = reporting.analyze(self.root, now=NOW)
        self.assertEqual(result['lanes']['gsc']['freshness']['status'], 'stale')

    def test_failed_worker_always_records_a_timestamp(self):
        atomic_json(state_dir(self.root)/'schedule.json', {'jobs': [{'lane': 'gsc_ranks', 'interval_seconds': 3600}]})
        def broken(*args, **kwargs):
            raise TimeoutError('fixture')
        result = seo_runner.tick(self.root, now=NOW.timestamp(), run_collector=broken)
        saved = json.loads(Path(result['jobs'][0]['artifact']).read_text())
        self.assertEqual(saved['status'], 'failed')
        self.assertEqual(saved['collected_at'], NOW.isoformat())
        self.assertIn('rank_snapshot', saved)

    def test_existing_report_does_not_reuse_rank_after_failed_worker(self):
        self.pair()
        atomic_json(state_dir(self.root)/'schedule.json', {'jobs': [{'lane': 'gsc_ranks', 'interval_seconds': 3600}]})
        def broken(*args, **kwargs):
            raise TimeoutError('fixture')
        seo_runner.tick(self.root, now=NOW.timestamp(), run_collector=broken)
        result = reporting.analyze(self.root, now=NOW)
        self.assertEqual(result['lanes']['gsc_ranks']['status'], 'failed')
        self.assertEqual(result['rank_movement']['changes'], [])


if __name__ == '__main__':
    unittest.main()
