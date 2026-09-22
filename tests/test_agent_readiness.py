import json
import tempfile
import unittest
from pathlib import Path

from scripts.agent_readiness import build_readiness


class AgentReadinessTests(unittest.TestCase):
    def test_machine_readable_map_and_activation_separation(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "site"
            (root / ".seo").mkdir(parents=True)
            (root / ".seo" / "site.yaml").write_text(json.dumps({
                "domain": "example.com",
                "properties": {"gsc": "sc-domain:example.com", "ga4": "123", "bing": "https://example.com/"},
                "policy": {"mode": "approved", "allowed_actions": ["deploy", "rollback"]},
                "measurement_setup": {"source_root_verified": True},
                "source_ownership": {"repository": "owner/site", "site_subdir": ""},
                "maintenance": {"deployment_route": "existing scoped SSH build/restart"},
            }), encoding="utf-8")
            manifest = base / "portfolio.json"
            manifest.write_text(json.dumps({"roots": [str(root)]}), encoding="utf-8")
            reports = base / "reports"
            reports.mkdir()
            (reports / "portfolio-status-2026-09-22.json").write_text(json.dumps({"sites": [{"domain": "example.com", "gsc": {"status": "ok"}}]}), encoding="utf-8")
            result = build_readiness(manifest, reports)
            self.assertEqual(result["schema_version"], 1)
            self.assertEqual(result["activation"], "disabled_by_design")
            self.assertEqual(result["host"]["interactive_route_state"], "ready")
            self.assertEqual(result["host"]["unattended_route_state"], "not_verified")
            self.assertEqual(result["sites"][0]["route_plan"]["source_ownership"]["state"], "ready")
            self.assertIn("request", result["sites"][0]["route_plan"]["interfaces"])
            self.assertNotIn(str(base), json.dumps(result))

    def test_toxic_mapping_stays_unverified(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "toxicsundae.com"
            (root / ".seo").mkdir(parents=True)
            (root / ".seo" / "site.yaml").write_text(json.dumps({"domain": "toxicsundae.com", "policy": {"mode": "read_only"}}), encoding="utf-8")
            manifest = base / "portfolio.json"
            manifest.write_text(json.dumps({"roots": [str(root)]}), encoding="utf-8")
            result = build_readiness(manifest, base / "reports")
            owner = result["sites"][0]["route_plan"]["source_ownership"]
            self.assertEqual(owner["state"], "not_verified")
            self.assertIn("source", owner["blocker"].lower())


if __name__ == "__main__":
    unittest.main()
