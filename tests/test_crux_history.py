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
    def test_history_percentile_objects_are_unwrapped(self):
        with patch.object(crux_history.requests, "post", return_value=_Response()):
            result = crux_history.query_history("https://example.com/", "test-key")
        self.assertEqual(result["metrics"]["largest_contentful_paint"]["latest_p75"], 2200)
        self.assertEqual(result["metrics"]["cumulative_layout_shift"]["latest_p75"], 0.04)


if __name__ == "__main__":
    unittest.main()
