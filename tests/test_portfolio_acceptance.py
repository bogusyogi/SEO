"""Cross-site portfolio acceptance seams using real local commands/state.

Provider, GitHub and HTTP edges remain deterministic fixtures; queue, workflow,
portfolio and outcome state are exercised through the shipped entry points.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import content_queue as queue
import outcome_jobs
import public_verify
import seo_runner
import seo_workflow as workflow
from seo_project import save_site
from seo_state import atomic_json, state_dir
from test_portfolio_workflow import fixture_site, measure, png
import test_github_publication as github_fixtures
import github_publication as gh
import remote_actions as actions

NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
SEO = Path(__file__).resolve().parent.parent / "seo.py"


def command(*args, cwd):
    """Run one public command and return its JSON stdout."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run([sys.executable, str(SEO), *map(str, args)], cwd=cwd,
                            check=False, capture_output=True, text=True, encoding="utf-8", env=env)
    if result.returncode not in (0, 2):
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout)


def metadata_plan(task_id):
    return {
        "schema_version": 1, "task_id": task_id, "decision": "change",
        "reason": "Repair observed title and canonical",
        "path": "content/page.html",
        "content": '<html><head><title>Site title</title><link rel="canonical" href="https://example.com/page"></head><body>Verified metadata repair.</body></html>',
        "expected_text": "Verified metadata repair.",
        "review": {"facts": "pass", "intent": "pass", "links": "pass", "preview": "pass", "evidence": "operator-review"},
    }


class PortfolioAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.one = self.root / "one"
        self.two = self.root / "two"
        fixture_site(self.one, "example.com")
        fixture_site(self.two, "other.example")
        site = json.loads((self.two / ".seo" / "site.yaml").read_text(encoding="utf-8"))
        site["workflow"]["require_media"] = True
        site["workflow"]["auto_approve_kinds"] = ["metadata", "content"]
        site["author_facts"] = {"founder": {"name": "Fixture founder", "evidence": "operator fixture"}}
        save_site(site, self.two)
        for root in (self.one, self.two):
            atomic_json(state_dir(root) / "schedule.json", {"jobs": [{"lane": "gsc", "interval_seconds": 86400}]})
        self.manifest = self.root / "portfolio.json"
        atomic_json(self.manifest, {"roots": ["one", "two"]})

    def test_two_sites_share_command_state_while_one_provider_fails(self):
        """Portfolio tick isolates a failed provider while another site advances."""
        first = command("workflow", "--root", self.one, "enqueue", "--target", "https://example.com/page",
                        "--kind", "metadata", "--issue", "missing_title", "--evidence", "audit", cwd=self.root)
        second = command("workflow", "--root", self.two, "enqueue", "--target", "https://other.example/page",
                         "--kind", "content", "--issue", "thin_content", "--evidence", "audit", cwd=self.root)
        plan_path = self.root / "one-plan.json"
        plan_path.write_text(json.dumps(metadata_plan(first["id"])), encoding="utf-8")
        command("workflow", "--root", self.one, "submit", first["id"], "--plan", plan_path, cwd=self.root)

        # A staged image and source-bound content plan prove media/content gates in
        # this same portfolio, while the second site's provider is unavailable.
        source = self.root / "hero.png"
        source.write_bytes(png())
        media = command("media", "--root", self.two, "stage", "hero", "--source", source,
                        "--path", "public/assets/hero.png", "--url", "https://other.example/assets/hero.png",
                        "--alt", "Verified site diagram", "--license-ref", "fixture-license", cwd=self.root)
        second_plan = {
            "schema_version": 1, "task_id": second["id"], "decision": "change",
            "reason": "Publish sourced page improvement", "path": "content/page.html",
            "content": '<html><head><title>Other page</title></head><body>Sourced content. <img src="https://other.example/assets/hero.png" alt="Verified site diagram" width="2" height="3"></body></html>',
            "expected_text": "Sourced content.", "media_ids": [media["id"]],
            "editorial": {"author_id": "founder", "intent": "voice input", "information_gain": "fixture facts",
                          "sources": [{"url": "https://example.org/source", "checked_at": datetime.now(timezone.utc).isoformat(), "supports": "fixture feature"}],
                          "claims": [{"claim": "fixture feature", "source": "https://example.org/source", "state": "approved", "use_in_output": True}]},
            "review": {"facts": "pass", "intent": "pass", "links": "pass", "preview": "pass", "evidence": "operator-review"},
        }
        # Shared portfolio runner catches one site's failure, preserves its report,
        # and runs real workflow state for the healthy site.
        real_tick = seo_runner.tick
        def isolated_tick(root):
            def measured(root, target, window):
                return measure(root, target, window)
            if Path(root).name == "two":
                def failed_provider(*args, **kwargs):
                    raise RuntimeError("provider unavailable")
                with patch.object(outcome_jobs, "measure", side_effect=measured):
                    return real_tick(root, run_collector=failed_provider, now=NOW.timestamp())
            def healthy_provider(root, lane, **kwargs):
                return {"site": "example.com", "lane": lane, "status": "ok",
                        "collected_at": NOW.isoformat(), "data": {}}
            with patch.object(outcome_jobs, "measure", side_effect=measured):
                return real_tick(root, run_collector=healthy_provider, now=NOW.timestamp())

        with patch.object(seo_runner, "tick", side_effect=isolated_tick):
            result = seo_runner.portfolio(self.manifest)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sites"][0]["workflow"]["tasks"][0]["stage"], "applied")
        self.assertEqual(result["sites"][1]["status"], "partial")
        self.assertTrue((self.root / "portfolio.report.json").is_file())
        self.assertIn("Verified metadata repair", (self.one / "content/page.html").read_text(encoding="utf-8"))
        # Content/media plan is accepted via same queue state after provider recovery.
        second_plan_path = self.root / "two-plan.json"
        second_plan_path.write_text(json.dumps(second_plan), encoding="utf-8")
        command("workflow", "--root", self.two, "submit", second["id"], "--plan", second_plan_path, cwd=self.root)
        self.assertEqual(workflow.advance(self.two, second["id"], now=NOW, measurer=measure)["stage"], "applied")

    def test_duplicate_tick_and_interrupted_local_write_resume_without_clobber(self):
        task = workflow.enqueue(self.one, target="https://example.com/page", kind="metadata",
                                issue="title", evidence="audit", now=NOW)["id"]
        plan = metadata_plan(task)
        original = queue.propose

        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise KeyboardInterrupt("simulated interruption")

        with patch.object(queue, "propose", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                workflow.advance(self.one, task, now=NOW, host=lambda *a: copy.deepcopy(plan), measurer=measure)
        # Persisted preparation is resumed exactly once; second tick is duplicate.
        self.assertEqual(workflow.advance(self.one, task, now=NOW, measurer=measure)["stage"], "applied")
        again = workflow.advance(self.one, task, now=NOW + timedelta(seconds=1), host=lambda *a: self.fail("reauthoring"), measurer=measure)
        self.assertEqual(again["stage"], "applied")
        deployed = lambda *a: {"state": "deployed", "identity": "revision", "effect_receipt": "fixture-receipt", "rollback": "scoped"}
        self.assertEqual(workflow.advance(self.one, task, now=NOW, measurer=measure,
                                          publisher=deployed, verifier=lambda *a: {"passed": True})["stage"], "awaiting_outcome")
        self.assertEqual(workflow.advance(self.one, task, now=NOW + timedelta(days=34), measurer=measure,
                                          publisher=lambda *a: self.fail("due outcome must not republish"))["stage"], "done")
        (self.one / "content/page.html").write_text("competing edit", encoding="utf-8")
        with self.assertRaises(ValueError): queue.apply(self.one, task)

    def test_uncertain_remote_pending_deployment_failed_verify_scoped_rollback_and_due_outcome(self):
        # Reuse the existing deterministic GitHub boundary, then drive local
        # deployment/public verification/outcome state through actual functions.
        fixture = github_fixtures.PublicationTests("test_real_protocol_creates_scoped_branch_pr_not_live_deployment")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self.addCleanup(fixture.doCleanups)
        fixture.api.fail_after = "create"
        uncertain = fixture.publish()
        self.assertEqual(uncertain["state"], "uncertain")
        self.assertEqual(gh.apply(fixture.root, "pub", transport=fixture.api)["state"], "uncertain")
        fixture.api.pr = None
        self.assertEqual(gh.reconcile(fixture.root, "pub", transport=fixture.api)["state"], "uncertain")
        # A second independent action demonstrates pending/failed deployment
        # evidence, then exact deployment is enough for a scoped reverse action.
        fixture.api.pr = {"number": 7, "html_url": "https://github.com/owner/site/pull/7", "state": "open", "merged": False, "draft": False,
                          "head": {"sha": github_fixtures.HEAD, "repo": {"id": 123}}, "base": {"ref": "main", "repo": {"id": 123}}}
        fixture.api.fail_after = None
        self.assertEqual(gh.reconcile(fixture.root, "pub", transport=fixture.api)["state"], "succeeded")
        self.assertEqual(gh.deployment(fixture.root, "pub", transport=fixture.api)["state"], "awaiting_merge")
        fixture.merge()
        fixture.api.deployments = [{"id": 1, "sha": github_fixtures.MERGE, "environment": "production"}]
        fixture.api.statuses = [{"state": "failure", "environment_url": "https://example.com/"}]
        self.assertEqual(gh.deployment(fixture.root, "pub", transport=fixture.api)["state"], "awaiting_deployment")
        fixture.api.statuses = [{"state": "success", "environment_url": "https://example.com/"}]
        self.assertEqual(gh.deployment(fixture.root, "pub", transport=fixture.api)["state"], "deployed")
        rollback = gh.prepare_rollback(fixture.root, "pub", "restore", evidence="recovery", transport=fixture.api)
        actions.approve(fixture.root, "restore", rollback["request_sha256"], "operator")
        self.assertEqual(gh.apply(fixture.root, "restore", transport=fixture.api)["state"], "succeeded")
        self.assertFalse(public_verify.verify(fixture.root, "page", {"expected_text": "new reviewed content"},
                                              fetcher=lambda url: {"url": url, "status": 200, "body": "wrong", "headers": {}})["passed"])
        due = outcome_jobs.schedule_after(NOW.date())
        self.assertLess(datetime.fromisoformat(due["due_at"]), NOW + timedelta(days=40))


if __name__ == "__main__":
    unittest.main()
