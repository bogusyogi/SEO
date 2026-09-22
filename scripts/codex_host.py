"""Optional, bounded adapter for an operator-selected Codex CLI executable.

This is a transport only.  It asks ``codex exec`` for a JSON SEO proposal and
returns that proposal; ``seo_workflow.validate_plan`` remains the policy gate.
No SDK, provider, shell, network permission, or write authority is added.
Timeout cleanup terminates the direct Codex process only; it does not claim
containment or termination of a process tree.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

MAX_INPUT = 2 * 1024 * 1024
MAX_OUTPUT = 2 * 1024 * 1024
MAX_TIMEOUT = 1800
PLAN_KEYS = {
    "schema_version", "task_id", "decision", "reason", "path", "content",
    "expected_text", "review", "editorial", "media_ids", "next_review_days",
    "supporting_changes", "verification",
}
WRAPPER_SUFFIXES = {".cmd", ".bat", ".ps1", ".sh"}


def proposal_schema():
    """Return strict transport schema; proposal details are validated locally."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "properties": {"proposal_json": {"type": "string", "minLength": 2}},
        "required": ["proposal_json"],
    }


def _json_bytes(value, label):
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be JSON") from exc
    if len(encoded) > MAX_INPUT:
        raise ValueError(f"{label} exceeds 2 MiB")
    return encoded


def _validate_result(request, result):
    if not isinstance(result, dict) or set(result) - PLAN_KEYS:
        raise ValueError("Codex response is not a version-1 proposal")
    if result.get("schema_version") != 1 or result.get("task_id") != request.get("task_id"):
        raise ValueError("Codex proposal schema_version or task_id mismatch")
    if result.get("decision") not in {"change", "retain", "defer"}:
        raise ValueError("Codex proposal has unsupported decision")
    if not isinstance(result.get("reason"), str) or not result["reason"].strip():
        raise ValueError("Codex proposal requires a reason")
    if result["decision"] == "change":
        for key in ("path", "content", "expected_text", "review"):
            if key not in result:
                raise ValueError("change proposal is incomplete")
    elif "next_review_days" not in result:
        raise ValueError("retain/defer proposal requires next_review_days")
    return result


def _over_output_cap(*paths):
    return sum(path.stat().st_size for path in paths if path.is_file()) > MAX_OUTPUT


def invoke(request, codex, *, model=None, timeout=180, root=None):
    """Run one bounded Codex proposal request using an existing executable."""
    if not isinstance(request, dict) or not isinstance(request.get("task_id"), str) or not request["task_id"]:
        raise ValueError("request requires a task_id")
    executable = Path(codex)
    if not executable.is_absolute() or not executable.is_file() or executable.suffix.lower() in WRAPPER_SUFFIXES:
        raise ValueError("--codex must be an existing absolute executable, not a shell wrapper")
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT:
        raise ValueError("timeout must be within 1..1800 seconds")
    if model is not None and (not isinstance(model, str) or not model or "\x00" in model):
        raise ValueError("model must be a nonempty string")
    prompt_request = dict(request)
    prompt_request["instructions"] = str(request.get("instructions", "")) + (
        " Return strict JSON envelope {proposal_json: string}; proposal_json must be the JSON text of the "
        "full version-1 proposal. Inspect only supplied evidence and explicitly reachable approved sources. "
        "If source facts or a preview cannot be verified, choose defer; never invent facts, IDs, review passes, "
        "deployment, or provider success. Include verification [{path,url,kind,value}] for every native or "
        "supporting file as required by the workflow."
    )
    encoded = _json_bytes(prompt_request, "request")
    work_root = Path(root or os.getcwd()).resolve()
    with tempfile.TemporaryDirectory(prefix="seo-codex-") as directory:
        base = Path(directory)
        schema_path, output_path = base / "schema.json", base / "proposal.json"
        schema_path.write_text(json.dumps(proposal_schema(), ensure_ascii=False), encoding="utf-8")
        argv = [str(executable), "exec", "--sandbox", "read-only", "--ephemeral",
                "--output-schema", str(schema_path), "--output-last-message", str(output_path),
                "--cd", str(work_root)]
        if model is not None:
            argv += ["--model", model]
        argv.append("-")
        with (base / "request.json").open("w+b") as source, (base / "stdout").open("wb") as out, (base / "stderr").open("wb") as err:
            source.write(encoded); source.flush(); source.seek(0)
            try:
                process = subprocess.Popen(argv, cwd=work_root, stdin=source, stdout=out, stderr=err, shell=False)
            except OSError as exc:
                raise RuntimeError("Codex executable could not be started") from exc
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Codex host exceeded configured deadline")
                    if _over_output_cap(base / "stdout", base / "stderr", output_path):
                        raise ValueError("Codex host output exceeds 2 MiB")
                    time.sleep(0.02)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
        if _over_output_cap(base / "stdout", base / "stderr", output_path):
            raise ValueError("Codex host output exceeds 2 MiB")
        if process.returncode != 0:
            raise RuntimeError("Codex host failed; sensitive stderr was not retained")
        if not output_path.is_file() or output_path.stat().st_size > MAX_OUTPUT:
            raise ValueError("Codex host did not produce bounded output")
        try:
            envelope = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Codex host output was not JSON") from exc
        if not isinstance(envelope, dict) or set(envelope) != {"proposal_json"} or not isinstance(envelope["proposal_json"], str):
            raise ValueError("Codex host response must be a strict proposal_json envelope")
        try:
            result = json.loads(envelope["proposal_json"])
        except json.JSONDecodeError as exc:
            raise ValueError("proposal_json was not JSON") from exc
        return _validate_result(request, result)


def main(argv=None):
    parser = argparse.ArgumentParser(description="bounded Codex SEO proposal adapter")
    parser.add_argument("--codex", required=True, help="operator-supplied absolute Codex executable")
    parser.add_argument("--model", help="optional operator-selected model")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("request exceeds 2 MiB")
        request = json.loads(raw.decode("utf-8"))
        result = invoke(request, args.codex, model=args.model, timeout=args.timeout_seconds)
        sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
        return 0
    except (ValueError, RuntimeError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"codex host error: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
