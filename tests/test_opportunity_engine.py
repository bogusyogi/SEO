"""Fixture tests for the decision layer: opportunity ranking and change measurement."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import opportunity_engine as engine
import change_measurement as cm
from seo_state import atomic_json, state_dir
from test_portfolio_workflow import fixture_site


def _write_envelope(root, lane, name, *, status="ok", collected_at, data):
    path = state_dir(root) / lane / f"{name}.json"
    atomic_json(path, {"schema_version": 2, "site": "example.com", "lane": lane, "status": status,
                        "collected_at": collected_at, "hostname_scope": ["example.com"],
                        "collection_route": "test", "data": data})


class OpportunityEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "site"
        fixture_site(self.root, domain="example.com")

    def tearDown(self):
        self.temp.cleanup()

    def test_striking_distance_and_ctr_detectors(self):
        _write_envelope(self.root, "gsc", "gsc-1", collected_at="2026-09-10T00:00:00+00:00", data={
            "rows": [
                {"query": "widget buyer guide", "page": "https://example.com/widgets", "position": 8.2,
                 "impressions": 500, "clicks": 2, "ctr": 0.004},
                {"query": "irrelevant", "page": "https://example.com/other", "position": 45, "impressions": 5, "clicks": 0, "ctr": 0},
            ],
        })
        items = engine.build_site_queue(self.root, "example.com", "approved", apply_feedback=False)
        detectors = {i["detector"] for i in items}
        self.assertIn("striking_distance_query", detectors)
        self.assertIn("ctr_below_expected", detectors)
        top = items[0]
        self.assertIn(top["risk_class"], engine.RISK_CLASSES)
        self.assertEqual(top["evidence"]["source"], "gsc")

    def test_decay_detector_needs_two_periods(self):
        _write_envelope(self.root, "gsc", "gsc-1", collected_at="2026-08-01T00:00:00+00:00", data={
            "rows": [{"query": "seasonal item", "page": "https://example.com/seasonal", "position": 6,
                      "impressions": 400, "clicks": 40}]})
        _write_envelope(self.root, "gsc", "gsc-2", collected_at="2026-09-01T00:00:00+00:00", data={
            "rows": [{"query": "seasonal item", "page": "https://example.com/seasonal", "position": 9,
                      "impressions": 300, "clicks": 10}]})
        items = engine.build_site_queue(self.root, "example.com", "approved", apply_feedback=False)
        decay = [i for i in items if i["detector"] == "decaying_query"]
        self.assertEqual(len(decay), 1)
        self.assertIn("75.0% decline", decay[0]["proposed_action"]["notes"])

    def test_technical_audit_findings_and_risk_class(self):
        _write_envelope(self.root, "audit", "audit-1", collected_at="2026-09-15T00:00:00+00:00", data={
            "severity": {"errors": ["canonical_missing"], "warnings": ["orphan_in_sitemap"]},
            "issues": {"canonical_missing": ["https://example.com/a"], "orphan_in_sitemap": ["https://example.com/b"]},
            "broken_links_all": [{"url": "https://example.com/dead"}],
        })
        items = engine.build_site_queue(self.root, "example.com", "read_only", apply_feedback=False)
        by_url = {i["url"]: i for i in items}
        self.assertEqual(by_url["https://example.com/a"]["proposed_action"]["type"], "fix_canonical")
        # read_only sites cannot execute anything, even metadata-only fixes.
        self.assertEqual(by_url["https://example.com/a"]["risk_class"], "forbidden")

    def test_policy_mode_gates_action_types(self):
        _write_envelope(self.root, "audit", "audit-1", collected_at="2026-09-15T00:00:00+00:00", data={
            "severity": {"errors": [], "warnings": []},
            "issues": {"title_too_long": ["https://example.com/a"]},
        })
        _write_envelope(self.root, "gsc", "gsc-1", collected_at="2026-09-15T00:00:00+00:00", data={
            "rows": [{"query": "q", "page": "https://example.com/thin", "position": 8, "impressions": 300, "clicks": 3}]})
        items = engine.build_site_queue(self.root, "example.com", "technical_only", apply_feedback=False)
        by_action = {i["proposed_action"]["type"]: i for i in items if i["url"]}
        self.assertEqual(by_action["fix_title_length"]["risk_class"], "auto_safe")
        self.assertEqual(by_action["improve_striking_distance_content"]["risk_class"], "forbidden")

    def test_engine_survives_malformed_envelope(self):
        (state_dir(self.root) / "gsc").mkdir(parents=True, exist_ok=True)
        (state_dir(self.root) / "gsc" / "bad.json").write_text("{not json", encoding="utf-8")
        items = engine.build_site_queue(self.root, "example.com", "approved", apply_feedback=False)
        self.assertEqual(items, [])

    def test_portfolio_ranking_orders_by_score(self):
        _write_envelope(self.root, "gsc", "gsc-1", collected_at="2026-09-15T00:00:00+00:00", data={
            "rows": [{"query": "big", "page": "https://example.com/big", "position": 5, "impressions": 1000, "clicks": 5}]})
        portfolio = Path(self.temp.name) / "portfolio.json"
        portfolio.write_text(json.dumps({"roots": ["site"]}), encoding="utf-8")
        result = engine.build_portfolio_queue(portfolio)
        self.assertEqual(result["sites"][0]["status"], "ok")
        self.assertTrue(result["portfolio_queue"])
        scores = [i["score"] for i in result["portfolio_queue"]]
        self.assertEqual(scores, sorted(scores, reverse=True))


class ChangeMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "site"
        fixture_site(self.root, domain="example.com")

    def tearDown(self):
        self.temp.cleanup()

    def test_register_rejects_duplicate_id(self):
        deploy = "2026-09-01T00:00:00+00:00"
        cm.register(self.root, change_id="chg-1", urls=["https://example.com/a"], commit="abc123",
                    deploy_time=deploy, detector="technical_audit:title_too_long", action_type="fix_title_length")
        with self.assertRaises(ValueError):
            cm.register(self.root, change_id="chg-1", urls=["https://example.com/a"], commit="abc123",
                        deploy_time=deploy, detector="x", action_type="y")

    def test_measure_before_window_elapsed_is_insufficient(self):
        deploy = datetime.now(timezone.utc) - timedelta(days=1)
        cm.register(self.root, change_id="chg-2", urls=["https://example.com/a"], commit=None,
                    deploy_time=deploy.isoformat(), detector="d", action_type="fix_title_length", measurement_window_days=28)
        result = cm.measure(self.root, "chg-2")
        self.assertEqual(result["verdict"], "insufficient_data")

    def test_measure_combines_and_updates_feedback(self):
        deploy = datetime.now(timezone.utc) - timedelta(days=40)
        cm.register(self.root, change_id="chg-3", urls=["https://example.com/a"], commit="abc",
                    deploy_time=deploy.isoformat(), detector="fix_title_length_detector",
                    action_type="fix_title_length", measurement_window_days=28)

        def fake_collect(root, url, window):
            improved = window["start"] > deploy.date().isoformat()
            return {"schema_version": 2, "site": "example.com", "lane": "gsc", "status": "ok", "target": url,
                    "collected_at": "2026-09-20T00:00:00+00:00", "hostname_scope": ["example.com"],
                    "collection_route": "test",
                    "data": {"property": "sc-domain:example.com", "search_type": "web", "dimensions": ["query"],
                             "filters": [], "aggregation_type": "byPage", "data_state": "final",
                             "time_zone": "UTC", "date_range": window,
                             "aggregate": {"clicks": 60 if improved else 30, "impressions": 500}}}

        with patch.object(cm, "_collect_gsc", side_effect=fake_collect):
            result = cm.measure(self.root, "chg-3")
        self.assertEqual(result["verdict"], "improved")
        multipliers = cm.load_feedback_multipliers(self.root)
        self.assertIn("fix_title_length_detector", multipliers)
        self.assertGreater(multipliers["fix_title_length_detector"], 1.0)

    def test_unknown_change_raises(self):
        with self.assertRaises(ValueError):
            cm.measure(self.root, "does-not-exist")


if __name__ == "__main__":
    unittest.main()
