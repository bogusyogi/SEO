import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import codex_host


class CodexHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def request(self):
        return {"schema_version": 1, "task_id": "wf-1", "task": {"kind": "metadata"}}

    def test_flags_stdin_output_file_and_read_only_contract(self):
        observed = {}
        def fake_popen(args, **kwargs):
            observed["args"] = args
            observed["stdin"] = json.load(kwargs["stdin"])
            out = args[args.index("--output-last-message") + 1]
            proposal = {"schema_version": 1, "task_id": "wf-1", "decision": "defer",
                "reason": "needs source", "next_review_days": 7}
            Path(out).write_text(json.dumps({"proposal_json": json.dumps(proposal)}), encoding="utf-8")
            return type("Process", (), {"returncode": 0, "poll": lambda self: 0, "wait": lambda self: None})()
        with patch.object(codex_host.subprocess, "Popen", fake_popen):
            result = codex_host.invoke(self.request(), sys.executable, root=self.root)
        self.assertEqual(result["decision"], "defer")
        self.assertEqual(observed["stdin"]["task_id"], "wf-1")
        self.assertEqual(observed["args"][0], sys.executable)
        self.assertEqual(observed["args"][1:4], ["exec", "--sandbox", "read-only"])
        self.assertIn("--ephemeral", observed["args"])
        self.assertEqual(observed["args"][-1], "-")

    def test_model_is_optional_and_task_identity_is_checked(self):
        def fake_popen(args, **kwargs):
            out = args[args.index("--output-last-message") + 1]
            proposal = {"schema_version": 1, "task_id": "wrong", "decision": "defer",
                "reason": "x", "next_review_days": 7}
            Path(out).write_text(json.dumps({"proposal_json": json.dumps(proposal)}), encoding="utf-8")
            return type("Process", (), {"returncode": 0, "poll": lambda self: 0, "wait": lambda self: None})()
        with patch.object(codex_host.subprocess, "Popen", fake_popen):
            with self.assertRaises(ValueError):
                codex_host.invoke(self.request(), sys.executable, model="operator-choice", root=self.root)

    def test_nonzero_exit_does_not_expose_stderr(self):
        def fake_popen(args, **kwargs):
            return type("Process", (), {"returncode": 3, "poll": lambda self: 3, "wait": lambda self: None})()
        with patch.object(codex_host.subprocess, "Popen", fake_popen):
            with self.assertRaisesRegex(RuntimeError, "sensitive stderr") as caught:
                codex_host.invoke(self.request(), sys.executable, root=self.root)
        self.assertNotIn("SECRET-TOKEN", str(caught.exception))

    def test_wrapper_paths_and_incomplete_proposals_rejected(self):
        with self.assertRaises(ValueError):
            codex_host.invoke(self.request(), str(self.root / "fake.cmd"), root=self.root)
        def fake_popen(args, **kwargs):
            out = args[args.index("--output-last-message") + 1]
            proposal = {"schema_version": 1, "task_id": "wf-1", "decision": "change", "reason": "x"}
            Path(out).write_text(json.dumps({"proposal_json": json.dumps(proposal)}), encoding="utf-8")
            return type("Process", (), {"returncode": 0, "poll": lambda self: 0, "wait": lambda self: None})()
        with patch.object(codex_host.subprocess, "Popen", fake_popen):
            with self.assertRaises(ValueError):
                codex_host.invoke(self.request(), sys.executable, root=self.root)


if __name__ == "__main__":
    unittest.main()
