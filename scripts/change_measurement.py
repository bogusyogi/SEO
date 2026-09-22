#!/usr/bin/env python3
"""Register a shipped change and measure its before/after outcome.

Complements ``outcome_jobs.py`` (which already knows how to take a fixed GSC
window before/after a single page) by giving the decision layer a durable,
detector-aware record: register a change once (site, urls, commit, deploy
time, detector, action type), then measure it later against GSC and GA4 and
record improved/neutral/regressed/insufficient_data. Outcomes accumulate into
a per-detector feedback file that ``opportunity_engine`` can use to bias
future scoring toward detectors/action types that have actually worked.

Nothing here executes a change or talks to a live provider directly; GSC/GA4
collection is delegated to the existing ``gsc_query_v2``/``ga4_report``
collectors via the same envelope contract the rest of the system uses.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from seo_state import atomic_json, state_dir, transaction_lock
from site_policy import load as load_policy, authorize, property_for
from measurement_scope import site_hosts, gsc_host_filter
from reporting import metric_changes

import gsc_query_v2

SCHEMA_VERSION = 1
STORE_NAME = "change-measurements.json"
OUTCOMES = {"improved", "neutral", "regressed", "insufficient_data"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_path(root) -> Path:
    return state_dir(root) / "interventions" / STORE_NAME


def _load_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "changes": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("changes", [])
    return data


def register(root, *, change_id: str, urls: list[str], commit: str | None, deploy_time: str,
             detector: str, action_type: str, expected_metric: str = "clicks",
             measurement_window_days: int = 28) -> dict[str, Any]:
    site = load_policy(root)
    try:
        deploy_dt = datetime.fromisoformat(deploy_time.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("deploy_time must be ISO-8601") from error
    if deploy_dt.tzinfo is None:
        raise ValueError("deploy_time must be timezone-aware")
    path = _store_path(root)
    with transaction_lock(path.parent):
        store = _load_store(path)
        if any(c["id"] == change_id for c in store["changes"]):
            raise ValueError(f"change already registered: {change_id}")
        record = {
            "id": change_id, "site": site["domain"], "urls": list(urls), "commit": commit,
            "deploy_time": deploy_dt.isoformat(), "detector": detector, "action_type": action_type,
            "expected_metric": expected_metric, "measurement_window_days": measurement_window_days,
            "registered_at": _utc_now(), "status": "pending_measurement", "outcome": None, "measurement": None,
        }
        store["changes"].append(record)
        atomic_json(path, store)
    return record


def _window(deploy_dt: datetime, days: int, *, before: bool) -> dict[str, str]:
    if before:
        end = deploy_dt - timedelta(days=2)
        start = end - timedelta(days=days - 1)
    else:
        start = deploy_dt + timedelta(days=2)
        end = start + timedelta(days=days - 1)
    return {"start": start.date().isoformat(), "end": end.date().isoformat()}


def _collect_gsc(root, url: str, window: dict[str, str]) -> dict[str, Any]:
    site = load_policy(root)
    authorize(site, "gsc", url=url)
    names = site_hosts(site)
    filters = [gsc_host_filter(names), {"dimension": "page", "operator": "equals", "expression": url}]
    try:
        prop = property_for(site, "gsc")
        data = gsc_query_v2.query(prop, window["start"], window["end"], ["query"], "web", 25000, 25000, filters, "final")
        state = "partial" if data.get("error") or data.get("coverage", {}).get("hit_client_cap") else "ok"
    except Exception as error:
        state, data = "failed", {"error": type(error).__name__, "date_range": window}
    return {"schema_version": 2, "site": site["domain"], "lane": "gsc", "status": state, "target": url,
            "collected_at": _utc_now(), "hostname_scope": names, "collection_route": "standalone_direct", "data": data}


def measure(root, change_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    path = _store_path(root)
    with transaction_lock(path.parent):
        store = _load_store(path)
        record = next((c for c in store["changes"] if c["id"] == change_id), None)
        if record is None:
            raise ValueError(f"unknown change: {change_id}")
        deploy_dt = datetime.fromisoformat(record["deploy_time"])
        days = record["measurement_window_days"]
        after_window = _window(deploy_dt, days, before=False)
        after_end = datetime.fromisoformat(after_window["end"] + "T00:00:00+00:00")
        if now < after_end + timedelta(days=1):
            record["status"] = "pending_measurement"
            atomic_json(path, store)
            return {"verdict": "insufficient_data", "reason": "measurement window has not elapsed yet",
                     "ready_at": (after_end + timedelta(days=1)).isoformat()}

        before_window = _window(deploy_dt, days, before=True)
        per_url = []
        outcomes = []
        for url in record["urls"]:
            before_env = _collect_gsc(root, url, before_window)
            after_env = _collect_gsc(root, url, after_window)
            comparison = metric_changes(before_env, after_env)
            verdict = "insufficient_data"
            if comparison.get("status") == "ok" and record["expected_metric"] in comparison.get("metrics", {}):
                before_data = (before_env.get("data") or {}).get("aggregate") or {}
                after_data = (after_env.get("data") or {}).get("aggregate") or {}
                impressions_floor = min(before_data.get("impressions", 0) or 0, after_data.get("impressions", 0) or 0)
                if impressions_floor < 20:
                    verdict = "insufficient_data"
                else:
                    metric = comparison["metrics"][record["expected_metric"]]
                    delta = metric["delta"] * (-1 if record["expected_metric"] == "position" else 1)
                    rel = metric.get("relative_percent") or 0
                    if delta > 0 and rel >= 5:
                        verdict = "improved"
                    elif delta < 0 and rel <= -5:
                        verdict = "regressed"
                    else:
                        verdict = "neutral"
            outcomes.append(verdict)
            per_url.append({"url": url, "before": before_env, "after": after_env, "comparison": comparison, "verdict": verdict})

        overall = _combine_outcomes(outcomes)
        record["status"] = "measured"
        record["outcome"] = overall
        record["measurement"] = {"measured_at": _utc_now(), "before_window": before_window,
                                  "after_window": after_window, "per_url": per_url}
        atomic_json(path, store)

    feedback_path = state_dir(root) / "interventions" / "scoring-feedback.json"
    update_feedback(feedback_path, record["detector"], overall)
    return {"verdict": overall, "record": record}


def _combine_outcomes(outcomes: list[str]) -> str:
    if not outcomes or all(o == "insufficient_data" for o in outcomes):
        return "insufficient_data"
    counted = [o for o in outcomes if o != "insufficient_data"]
    if not counted:
        return "insufficient_data"
    if any(o == "regressed" for o in counted):
        return "regressed"
    if any(o == "improved" for o in counted):
        return "improved"
    return "neutral"


def update_feedback(path: Path, detector: str, outcome: str) -> dict[str, Any]:
    with transaction_lock(path.parent):
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": SCHEMA_VERSION, "detectors": {}}
        entry = data["detectors"].setdefault(detector, {"improved": 0, "neutral": 0, "regressed": 0, "insufficient_data": 0})
        entry[outcome] = entry.get(outcome, 0) + 1
        total_scored = entry["improved"] + entry["neutral"] + entry["regressed"]
        entry["multiplier"] = round(1.0 + 0.15 * ((entry["improved"] - entry["regressed"]) / total_scored), 4) if total_scored else 1.0
        atomic_json(path, data)
    return data


def load_feedback_multipliers(root) -> dict[str, float]:
    path = state_dir(root) / "interventions" / "scoring-feedback.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {name: entry.get("multiplier", 1.0) for name, entry in (data.get("detectors") or {}).items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("register")
    p.add_argument("root")
    p.add_argument("--id", required=True)
    p.add_argument("--url", action="append", dest="urls", required=True)
    p.add_argument("--commit")
    p.add_argument("--deploy-time", required=True)
    p.add_argument("--detector", required=True)
    p.add_argument("--action-type", required=True)
    p.add_argument("--expected-metric", default="clicks")
    p.add_argument("--window-days", type=int, default=28)

    p = sub.add_parser("measure")
    p.add_argument("root")
    p.add_argument("--id", required=True)

    p = sub.add_parser("list")
    p.add_argument("root")

    args = ap.parse_args()
    if args.command == "register":
        result = register(args.root, change_id=args.id, urls=args.urls, commit=args.commit,
                           deploy_time=args.deploy_time, detector=args.detector, action_type=args.action_type,
                           expected_metric=args.expected_metric, measurement_window_days=args.window_days)
    elif args.command == "measure":
        result = measure(args.root, args.id)
    else:
        result = _load_store(_store_path(args.root))
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
