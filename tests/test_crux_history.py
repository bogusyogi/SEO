import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    import requests
except ImportError:
    # Parsing fixtures do not require the optional live HTTP dependency.
    with patch.dict(sys.modules, {'requests': Mock()}):
        import crux_history
else:
    import crux_history


class _Response:
    status_code = 200
    def raise_for_status(self):
        return None
    def json(self):
        return {"record": {
            "collectionPeriods": [],
            "metrics": {
                "largest_contentful_paint": {"percentilesTimeseries": {"p75s": [{"p75": 2100}, {"p75": 2200}]}},
                "cumulative_layout_shift": {"percentilesTimeseries": {"p75s": [{"p75": "0.04"}]}}
            }
        }}


class CruxHistoryTests(unittest.TestCase):
    def test_missing_current_period_does_not_relabel_older_observation(self):
        payload = {'record': {'collectionPeriods': [
            {'firstDate': {'year': 2026, 'month': 4, 'day': 1}, 'lastDate': {'year': 2026, 'month': 4, 'day': 28}},
            {'firstDate': {'year': 2026, 'month': 5, 'day': 1}, 'lastDate': {'year': 2026, 'month': 5, 'day': 28}}],
            'metrics': {'largest_contentful_paint': {'percentilesTimeseries': {'p75s': [2100, None]}}}}}
        response = _Response()
        with patch.object(response, 'json', return_value=payload), patch.object(crux_history.requests, 'post', return_value=response):
            metric = crux_history.query_history('https://example.com/', 'test-key')['metrics']['largest_contentful_paint']
        self.assertIsNone(metric['latest_p75'])
        self.assertEqual(metric['latest_observed_p75'], 2100)
        self.assertEqual(metric['latest_observed_period'], {'first': '2026-04-01', 'last': '2026-04-28'})

    def test_history_percentile_objects_are_unwrapped(self):
        with patch.object(crux_history.requests, "post", return_value=_Response()):
            result = crux_history.query_history("https://example.com/", "test-key")
        self.assertEqual(result["metrics"]["largest_contentful_paint"]["latest_p75"], 2200)
        self.assertEqual(result["metrics"]["cumulative_layout_shift"]["latest_p75"], 0.04)


if __name__ == "__main__":
    unittest.main()
