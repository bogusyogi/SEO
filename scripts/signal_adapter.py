"""Tolerant adapter that loads stored SEO signals for opportunity detection.

Signals live as versioned JSON envelopes under a site's ``.seo/<lane>/*.json``
(schema: ``{lane, status, collected_at, data}``, written by the various
``*_query*``/``*_check``/``site_audit`` collectors) plus a handful of portfolio
report snapshots under the operator's ``reports/`` directory (performance
baselines, technical-audit rollups).

This module is deliberately defensive: lane schemas evolve, a parallel effort
is adding new collectors (documented separately in ``docs/SIGNALS.md``), and a
missing/malformed file must degrade to "no evidence" rather than raise. Nothing
here mutates state; it only reads what other tools already collected.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LANES = ("gsc", "ga4", "bing", "audit", "backlinks", "gsc_ranks", "serp",
         "cwv", "indexing", "internal_links")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def _envelopes(lane_dir: Path, lane: str) -> list[dict[str, Any]]:
    """All readable envelopes for a lane, oldest first, tolerant of schema drift."""
    if not lane_dir.is_dir():
        return []
    out = []
    for path in sorted(lane_dir.glob("*.json")):
        payload = _read_json(path)
        if payload is None:
            continue
        # Accept any envelope naming this lane, or an untagged one living in the
        # lane's own directory (covers collectors that predate the lane field).
        if payload.get("lane") not in (lane, None):
            continue
        payload.setdefault("_source_file", path.name)
        out.append(payload)
    out.sort(key=lambda env: str(env.get("collected_at") or ""))
    return out


@dataclass
class SiteSignals:
    root: Path
    domain: str
    policy_mode: str
    gsc_history: list[dict[str, Any]] = field(default_factory=list)
    audit_history: list[dict[str, Any]] = field(default_factory=list)
    ga4_history: list[dict[str, Any]] = field(default_factory=list)
    bing_history: list[dict[str, Any]] = field(default_factory=list)
    backlinks_history: list[dict[str, Any]] = field(default_factory=list)
    cwv_history: list[dict[str, Any]] = field(default_factory=list)
    indexing_history: list[dict[str, Any]] = field(default_factory=list)
    internal_links_history: list[dict[str, Any]] = field(default_factory=list)
    pagespeed_scores: dict[str, Any] | None = None
    extra_reports: dict[str, Any] = field(default_factory=dict)

    def latest(self, lane: str) -> dict[str, Any] | None:
        history = getattr(self, f"{lane}_history", [])
        for env in reversed(history):
            if env.get("status") == "ok":
                return env
        return history[-1] if history else None

    def previous_ok(self, lane: str) -> dict[str, Any] | None:
        history = [e for e in getattr(self, f"{lane}_history", []) if e.get("status") == "ok"]
        return history[-2] if len(history) >= 2 else None


def state_dir(root: str | Path) -> Path:
    return Path(root).expanduser().resolve() / ".seo"


def load_site_signals(root: str | Path, *, domain: str | None = None,
                       policy_mode: str = "read_only") -> SiteSignals:
    """Load whatever evidence exists for one site root. Never raises on missing data."""
    base = state_dir(root)
    signals = SiteSignals(root=Path(root).expanduser().resolve(), domain=domain or "", policy_mode=policy_mode)
    for lane in ("gsc", "audit", "ga4", "bing", "backlinks", "cwv", "indexing", "internal_links"):
        attr = f"{lane}_history"
        if hasattr(signals, attr):
            setattr(signals, attr, _envelopes(base / lane, lane))
    return signals


def load_pagespeed_scores(reports_dir: str | Path, filename_glob: str = "performance-baseline-*.json") -> dict[str, dict[str, Any]]:
    """Best-effort read of the newest portfolio-wide PSI score snapshot, keyed by host."""
    reports_dir = Path(reports_dir)
    candidates = sorted(reports_dir.glob(filename_glob))
    if not candidates:
        return {}
    payload = _read_json(candidates[-1])
    if not payload:
        return {}
    scores = payload.get("psi_scores")
    return scores if isinstance(scores, dict) else {}


def load_technical_audit_rollup(reports_dir: str | Path, filename_glob: str = "initial-technical-audits-*.json") -> dict[str, dict[str, Any]]:
    """Best-effort read of a portfolio-wide technical-audit rollup, keyed by short site name."""
    reports_dir = Path(reports_dir)
    candidates = sorted(reports_dir.glob(filename_glob))
    if not candidates:
        return {}
    payload = _read_json(candidates[-1])
    if not payload or not isinstance(payload.get("sites"), list):
        return {}
    return {str(row.get("site")): row for row in payload["sites"] if isinstance(row, dict) and row.get("site")}
