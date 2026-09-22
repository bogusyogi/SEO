from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
SEO_ROOT = HERE.parent
SCRIPTS = SEO_ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))
FIX = HERE / 'fixtures'


def load(name: str):
    path = SCRIPTS / f'{name}.py'
    spec = importlib.util.spec_from_file_location(f'seo_replay_{name}', path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProviderReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gsc = load('gsc_query_v2')
        cls.ai = load('ai_visibility_import')
        try:
            import requests  # noqa: F401
        except ImportError:
            requests_stub = types.ModuleType('requests')
            requests_stub.get = Mock()
            requests_stub.post = Mock()
            requests_stub.exceptions = types.SimpleNamespace(
                Timeout=TimeoutError,
                HTTPError=RuntimeError,
                RequestException=Exception,
            )
            sys.modules['requests'] = requests_stub
            try:
                cls.pagespeed = load('pagespeed_check')
            finally:
                sys.modules.pop('requests', None)
        else:
            cls.pagespeed = load('pagespeed_check')

    def test_pagespeed_audit_details_preserves_heading_rows(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            'analysisUTCTimestamp': '2026-09-22T00:00:00.000Z',
            'lighthouseResult': {
                'categories': {},
                'audits': {
                    'unused-css-rules': {
                        'title': 'Unused CSS',
                        'details': {
                            'headings': [{'key': 'url'}],
                            'items': [{'url': 'https://example.com/app.css'}],
                        },
                    },
                },
            },
        }
        with patch.object(self.pagespeed.requests, 'get', return_value=response):
            result = self.pagespeed.run_pagespeed('https://example.com/', strategy='mobile')
        self.assertIsNone(result['error'])
        self.assertEqual(result['audit_details']['unused-css-rules']['headings'], ['url'])
        self.assertEqual(result['audit_details']['unused-css-rules']['items'][0]['url'], 'https://example.com/app.css')

    def test_gsc_aggregate_is_not_dimension_sum(self):
        fixture = json.loads((FIX / 'gsc_replay.json').read_text())
        out = self.gsc.normalize_result(
            site_url='sc-domain:example.com', start_date='2026-08-01', end_date='2026-08-28',
            dimensions=['query', 'page'], search_type='web',
            aggregate_row=fixture['aggregate_row'], rows=fixture['rows'], max_rows=100000, hit_cap=False,
        )
        self.assertEqual(out['aggregate']['clicks'], 100.0)
        self.assertEqual(out['dimension_sum']['clicks'], 70.0)
        self.assertEqual(out['aggregate']['impressions'], 1000.0)
        self.assertEqual(out['dimension_sum']['impressions'], 550.0)
        self.assertEqual(out['coverage']['query_click_coverage'], 0.7)
        self.assertIn('dimensionless', out['aggregate']['provenance'])

    def test_gsc_replay_is_deterministic(self):
        fixture = json.loads((FIX / 'gsc_replay.json').read_text())
        kwargs = dict(
            site_url='sc-domain:example.com', start_date='2026-08-01', end_date='2026-08-28',
            dimensions=['query', 'page'], search_type='web', aggregate_row=fixture['aggregate_row'],
            rows=fixture['rows'], max_rows=100000, hit_cap=False,
        )
        self.assertEqual(self.gsc.normalize_result(**kwargs), self.gsc.normalize_result(**kwargs))

    def test_google_ai_export_replay_is_deterministic(self):
        rows = self.ai.load_rows(FIX / 'ai_google.csv')
        one = self.ai.google(rows, 'fixture.csv')
        two = self.ai.google(rows, 'fixture.csv')
        one.pop('imported_at')
        two.pop('imported_at')
        self.assertEqual(one, two)

    def test_bing_ai_export_replay_is_deterministic(self):
        rows = self.ai.load_rows(FIX / 'ai_bing.csv')
        one = self.ai.bing(rows, 'fixture.csv')
        two = self.ai.bing(rows, 'fixture.csv')
        one.pop('imported_at')
        two.pop('imported_at')
        self.assertEqual(one, two)


if __name__ == '__main__':
    unittest.main()
