"""Read-only readiness map for an interactive SEO agent host.

The command inspects an explicit portfolio manifest, site policy/configuration,
and saved reports. It never invokes a provider, model, deployment, scheduler,
or shell wrapper. Default output is safe for dashboards: private filesystem
paths, credentials, and executable argv are omitted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STATES = {"ready", "missing", "not_verified", "disabled_by_design"}
PRIVATE_KEYS = {"token", "secret", "password", "credential", "argv", "path", "root"}


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            try:
                import yaml
                value = yaml.safe_load(text)
            except (ImportError, ValueError, TypeError):
                return None
    except (OSError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def _safe_state(value: str) -> str:
    return value if value in STATES else "not_verified"


def _evidence(reports_dir: Path) -> dict[str, Any]:
    """Read only portfolio reports; retain report names, never private paths."""
    result: dict[str, Any] = {}
    candidates = sorted(reports_dir.glob("portfolio-*.json"), key=lambda path: path.stat().st_mtime if path.exists() else 0)
    for path in candidates[-8:]:
        name = path.name
        payload = _load_json(path)
        if payload is not None:
            result[name] = payload
    return result


def _report_site(reports: dict[str, Any], domain: str) -> dict[str, Any]:
    for payload in reports.values():
        for site in payload.get("sites", []):
            if site.get("domain") == domain or site.get("site") == domain:
                return site
    return {}


def _provider(config: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    props = config.get("properties") or {}
    measurement = config.get("measurement_setup") or {}
    result = {}
    for name in ("gsc", "ga4", "bing"):
        identity = props.get(name)
        provider = evidence.get(name) or {}
        status = provider.get("status")
        result[name] = {
            "identity_configured": bool(identity),
            "identity": identity if name != "ga4" else (str(identity) if identity else None),
            "collection": "verified" if status == "ok" and evidence.get("schema_version") == 1 else "not_verified",
            "collected_at": evidence.get("collected_at") if status == "ok" else None,
        }
    return result


def _route(config: dict[str, Any], site_root: Path, domain: str, report: dict[str, Any], evidence: dict[str, Any], audit: dict[str, Any] | None, saved_route: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = config.get("policy") or {}
    ownership = config.get("source_ownership") or {}
    maintenance = config.get("maintenance") or {}
    workflow = config.get("workflow") or {}
    configured_owner = bool(ownership.get("repository") or maintenance.get("source_root_verified") or (saved_route or {}).get("local_git_root_verified"))
    root_verified = bool((config.get("measurement_setup") or {}).get("source_root_verified"))
    source_state = "ready" if configured_owner and root_verified else "not_verified"
    blocker = None
    if not configured_owner:
        blocker = "No source_ownership or maintenance source-root assertion is recorded in site policy."
    elif not root_verified:
        blocker = "site policy records source_root_verified=false; canonical source ownership needs operator evidence."
    if saved_route and (saved_route.get("evidence_status", "").startswith("source mapping evidenced") or saved_route.get("evidence_status", "").startswith("static artifact deployed")):
        source_state = "ready"
        blocker = "Saved deployment evidence maps canonical source/artifact ownership; source parity or executable deployment remains unqualified."
    collection = "ready" if evidence.get("status") == "ok" and evidence.get("schema_version") == 1 else "not_verified"
    proposal = "ready" if policy.get("mode") in {"approved", "technical_only", "read_only"} else "missing"
    deploy_allowed = "deploy" in (policy.get("allowed_actions") or [])
    deploy = "ready" if deploy_allowed and source_state == "ready" and (not saved_route or saved_route.get("route_state") == "ready") else ("disabled_by_design" if not deploy_allowed else "not_verified")
    verify = "ready" if collection == "ready" and audit is not None else "not_verified"
    recovery = "ready" if "rollback" in (policy.get("allowed_actions") or []) and source_state == "ready" else "not_verified"
    host = workflow.get("host")
    activation = "ready" if workflow.get("enabled") is True and host else "disabled_by_design"
    return {
        "collection": {"state": collection, "prerequisites": ["provider identity", "saved evidence or authorized collection", "site policy"]},
        "proposal": {"state": proposal, "prerequisites": ["task evidence", "policy review", "interactive agent review"]},
        "deploy": {"state": deploy, "prerequisites": ["canonical source ownership", "approved proposal", "exact commit", "deployment receipt"]},
        "verify": {"state": verify, "prerequisites": ["matching deployment receipt", "public URL checks", "approved assertions"]},
        "recovery": {"state": recovery, "prerequisites": ["separate reverse proposal", "matching prior effect", "deployment and public verification"]},
        "activation": {"state": activation, "workflow_enabled": bool(workflow.get("enabled")), "reason": "Activation is separate from readiness and remains disabled until explicitly configured."},
        "source_ownership": {"state": source_state, "repository": ownership.get("repository"), "site_subdir": ownership.get("site_subdir"), "blocker": blocker},
        "route": maintenance.get("deployment_route") or "existing site deployment route requires operator evidence",
        "saved_route": {key: (saved_route or {}).get(key) for key in ("siteprefix", "remote_sitepath", "pm2target", "liveurl", "route_state", "pending", "evidence_status") if (saved_route or {}).get(key) is not None},
        "interfaces": {
            "sync": "workflow sync",
            "enqueue": "workflow enqueue --target URL --kind KIND --issue ISSUE --evidence EVIDENCE",
            "request": "workflow request TASK_ID",
            "submit": "workflow submit TASK_ID --plan REVIEWED_PLAN",
            "advance": "workflow advance TASK_ID",
            "prepare": "publication prepare ACTION_ID --task TASK_ID --evidence REVIEW_EVIDENCE",
            "approve": "publication approve ACTION_ID --digest REQUEST_SHA256 --approval-ref OPERATOR_REFERENCE",
            "apply": "publication apply ACTION_ID",
            "status": "publication status ACTION_ID",
            "reconcile": "publication reconcile ACTION_ID",
            "rollback": "publication rollback ORIGINAL_ID NEW_ID --evidence REFERENCE",
        },
    }


def build_readiness(portfolio_path: str | Path, reports_dir: str | Path | None = None, *, include_private: bool = False) -> dict[str, Any]:
    manifest_path = Path(portfolio_path)
    manifest = _load_json(manifest_path)
    if not manifest or not isinstance(manifest.get("roots"), list):
        raise ValueError("portfolio manifest must contain roots[]")
    report_map = _evidence(Path(reports_dir) if reports_dir else manifest_path.parent / "reports")
    route_payload = _load_json(manifest_path.parent / "agent-routes.json") or {}
    saved_routes = {route.get("site"): route for route in route_payload.get("routes", []) if isinstance(route, dict)}
    sites = []
    for raw_root in manifest["roots"]:
        root = Path(str(raw_root))
        if not root.is_absolute():
            root = (manifest_path.parent / root).resolve()
        config_path = root / ".seo" / "site.yaml"
        config = _load_json(config_path) or {}
        domain = str(config.get("domain") or root.name)
        report = _report_site(report_map, domain)
        evidence_path = root / ".seo" / "reports" / "provider-details.json"
        evidence = _load_json(evidence_path) or {}
        audit_candidates = sorted((root / ".seo" / "reports").glob("*audit*.json"), key=lambda path: path.stat().st_mtime if path.exists() else 0)
        audit = _load_json(audit_candidates[-1]) if audit_candidates else None
        sites.append({
            "site": domain,
            "provider_identities": _provider(config, evidence),
            "policy": {"mode": (config.get("policy") or {}).get("mode", "missing")},
            "route_plan": _route(config, root, domain, report, evidence, audit, saved_routes.get(domain)),
            "evidence": {"reports": sorted(report_map), "provider_details": evidence_path.name if evidence else None, "audit": audit_candidates[-1].name if audit else None, "saved_site_report": bool(report)},
        })
    wrapper = Path(__file__).resolve().with_name("codex_host.py")
    host = {
        "adapter": "codex_host.py",
        "state": "ready" if wrapper.is_file() else "missing",
        "interactive_route_state": "ready",
        "unattended_route_state": "not_verified",
        "interactive_route": "Codex interactive host using workflow request/submit interface",
        "model_invoked": False,
        "activation": "disabled_by_design",
        "checks": {
            "strict_proposal_envelope": "ready" if wrapper.is_file() else "missing",
            "read_only_sandbox_flag": "ready" if wrapper.is_file() else "missing",
            "shell_false": "ready" if wrapper.is_file() else "missing",
            "bounded_input_output": "ready" if wrapper.is_file() else "missing",
            "process_tree_containment": "not_verified",
            "absolute_executable_and_permissions": "not_verified",
        },
        "recommendation": "Use existing interactive Codex route; qualify operator executable, permissions, process-tree containment, and site evidence before unattended host use.",
    }
    output = {"schema_version": SCHEMA_VERSION, "kind": "seo_agent_readiness", "activation": "disabled_by_design", "host": host, "sites": sites}
    if include_private:
        output["private_inputs"] = {"portfolio": str(manifest_path), "reports_dir": str(Path(reports_dir) if reports_dir else manifest_path.parent / "reports")}
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="read-only SEO agent readiness map")
    parser.add_argument("--portfolio", required=True)
    parser.add_argument("--reports-dir")
    parser.add_argument("--output")
    parser.add_argument("--include-private", action="store_true", help="include local input paths; private output only")
    args = parser.parse_args(argv)
    try:
        result = build_readiness(args.portfolio, args.reports_dir, include_private=args.include_private)
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
