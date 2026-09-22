"""Regression tests for bounded provider-details snapshots."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import provider_details


class ProviderDetailsTests(unittest.TestCase):
    def site(self, root):
        state = root / ".seo"
        state.mkdir()
        (state / "site.yaml").write_text(json.dumps({
            "domain": "example.com",
            "properties": {"gsc": "sc-domain:example.com", "ga4": "123", "bing": "https://example.com/"},
        }), encoding="utf-8")

    def test_dates_are_non_overlapping_and_daily_is_56_days(self):
        periods = provider_details._dates()
        self.assertLess(periods["previous"]["end"], periods["current"]["start"])
        from datetime import date
        self.assertEqual((date.fromisoformat(periods["daily"]["end"]) - date.fromisoformat(periods["daily"]["start"])).days, 55)

    def test_owned_url_rejects_off_host_and_credentials_are_redacted(self):
        self.assertTrue(provider_details._owned_url("https://www.example.com/a", "example.com"))
        self.assertFalse(provider_details._owned_url("https://other.example/a", "example.com"))
        self.assertNotIn("secret", provider_details._error(Exception("https://x.test/?key=secret")))

    def test_collect_writes_atomic_schema_and_preserves_measured_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.site(root)
            with patch.object(provider_details, "_gsc", return_value={"status": "ok", "pages": [], "current": {}, "previous": {}, "daily": [], "devices": [], "countries": [], "query_changes": [], "coverage": {}}), patch.object(provider_details, "_ga4", return_value={"status": "ok", "totals": {}, "daily": [], "pages": [], "devices": [], "countries": [], "currency": None, "time_zone": None, "event_arrival": "unknown"}), patch.object(provider_details, "_indexing", return_value={"status": "ok", "rows": [], "coverage": {}}), patch.object(provider_details, "_bing", return_value={"status": "ok", "rows": [], "referring_domains": [], "coverage": {}, "newly_observed": [], "missing": []}), patch.object(provider_details, "_ahrefs", return_value={"status": "ok", "value": 0, "collected_at": "2026-01-01T00:00:00Z", "provider": "ahrefs", "attribution": "Domain Rating by Ahrefs"}):
                result = provider_details.collect_site(root)
            report = root / ".seo" / "reports" / "provider-details.json"
            self.assertTrue(report.is_file())
            self.assertEqual(result["schema_version"], 1)
            self.assertEqual(result["domain_rating"]["value"], 0)
            self.assertEqual(set(result), {"schema_version", "site", "collected_at", "status", "gsc", "ga4", "indexing", "backlinks", "bing", "domain_rating", "errors"})

    def test_only_lane_and_skip_fresh_do_not_repeat_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.site(root)
            with patch.object(provider_details, "_gsc", side_effect=AssertionError("gsc should be skipped")), patch.object(provider_details, "_ga4", return_value={"status": "ok", "totals": {}, "daily": [], "pages": [], "devices": [], "countries": [], "currency": None, "time_zone": None, "event_arrival": "unknown"}), patch.object(provider_details, "_indexing", return_value={"status": "missing", "rows": [], "coverage": {}}), patch.object(provider_details, "_bing", return_value={"status": "missing", "rows": [], "referring_domains": [], "coverage": {}, "newly_observed": [], "missing": []}), patch.object(provider_details, "_ahrefs", return_value={"status": "missing", "value": None, "collected_at": None, "provider": "ahrefs", "attribution": "Domain Rating by Ahrefs"}):
                provider_details.collect_site(root, only={"ga4"})
            with patch.object(provider_details, "_ga4", side_effect=AssertionError("fresh report should be reused")):
                reused = provider_details.collect_site(root, only={"ga4"}, skip_fresh=60)
            self.assertEqual(reused["schema_version"], 1)

    def test_failed_lane_is_not_marked_fresh(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.site(root)
            with patch.object(provider_details, "_gsc", side_effect=RuntimeError("temporary")):
                result = provider_details.collect_site(root, only={"gsc"})
            self.assertEqual(result["gsc"]["status"], "error")
            self.assertNotIn("collected_at", result["gsc"])


if __name__ == "__main__":
    unittest.main()
