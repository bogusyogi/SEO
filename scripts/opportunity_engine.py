#!/usr/bin/env python3
"""Rank a machine-readable action queue from already-collected SEO signals.

This is the decision layer: it does not collect new evidence and does not
write to any site. It reads stored envelopes (via ``signal_adapter``), runs a
fixed set of detectors, scores and ranks the resulting opportunities, and
applies each site's operator policy (``site_policy.py``) so that a
technical-only or monitoring-only site never receives a forbidden action type.

Each emitted item has: site, url, detector, evidence (source + date),
proposed action type, risk class, expected metric + measurement window, score.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from signal_adapter import SiteSignals, load_pagespeed_scores, load_site_signals, load_technical_audit_rollup
from site_policy import load as load_policy

SCHEMA_VERSION = 1

RISK_CLASSES = ("auto_safe", "needs_review", "forbidden")

# Action types that are pure metadata/internal-link technical repair; everything
# else touches editorial content or off-site acquisition and needs review.
AUTO_SAFE_ACTIONS = {
    "fix_title_length", "fix_meta_description", "fix_canonical", "fix_noindex_mistake",
    "add_internal_link", "fix_broken_link", "resubmit_sitemap", "request_indexing",
}
NEEDS_REVIEW_ACTIONS = {
    "expand_thin_content", "rewrite_for_ctr", "refresh_decaying_content",
    "improve_striking_distance_content", "consolidate_duplicate_targets",
    "improve_cwv", "build_backlinks",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _risk_class(action_type: str, policy_mode: str) -> str:
    if action_type in AUTO_SAFE_ACTIONS:
        base = "auto_safe"
    elif action_type in NEEDS_REVIEW_ACTIONS:
        base = "needs_review"
    else:
        base = "needs_review"
    if policy_mode == "technical_only" and base != "auto_safe":
        return "forbidden"
    if policy_mode == "read_only":
        return "forbidden"
    return base


def _item(site: str, url: str, detector: str, evidence: dict[str, Any], action_type: str,
          policy_mode: str, expected_metric: str, measurement_window_days: int,
          score: float, notes: str = "") -> dict[str, Any]:
    return {
        "site": site,
        "url": url,
        "detector": detector,
        "evidence": evidence,
        "proposed_action": {"type": action_type, "notes": notes},
        "risk_class": _risk_class(action_type, policy_mode),
        "expected_metric": expected_metric,
        "measurement_window_days": measurement_window_days,
        "score": round(score, 4),
    }


# ---------------------------------------------------------------------------
# Detectors. Each takes (site_domain, signals, policy_mode) and returns items.
# ---------------------------------------------------------------------------

def detect_striking_distance(domain, signals: SiteSignals, policy_mode, *, min_impressions=10) -> list[dict]:
    env = signals.latest("gsc")
    if not env or env.get("status") != "ok":
        return []
    rows = (env.get("data") or {}).get("rows") or []
    out = []
    for row in rows:
        pos = row.get("position")
        impressions = row.get("impressions") or 0
        if pos is None or impressions < min_impressions or not (4 <= pos <= 20):
            continue
        # Closer to the top of the striking-distance band and more impressions score higher.
        proximity = (21 - pos) / 17.0
        score = proximity * min(1.0, impressions / 200.0) * 10
        out.append(_item(domain, row.get("page") or "", "striking_distance_query",
                          {"source": "gsc", "date": env.get("collected_at")}, "improve_striking_distance_content",
                          policy_mode, "clicks", 28, score,
                          notes=f"query={row.get('query')!r} position={pos} impressions={impressions}"))
    return out


def detect_ctr_below_expected(domain, signals: SiteSignals, policy_mode, *, min_impressions=50) -> list[dict]:
    # Position-banded CTR expectation curve, coarse but directionally sound.
    expected = [(1, 3, 0.28), (3, 5, 0.15), (5, 10, 0.07), (10, 20, 0.02), (20, 100, 0.005)]

    def expected_ctr(pos):
        for lo, hi, ctr in expected:
            if lo <= pos < hi:
                return ctr
        return 0.28

    env = signals.latest("gsc")
    if not env or env.get("status") != "ok":
        return []
    rows = (env.get("data") or {}).get("rows") or []
    out = []
    for row in rows:
        pos, impressions = row.get("position"), row.get("impressions") or 0
        clicks = row.get("clicks") or 0
        if pos is None or impressions < min_impressions:
            continue
        actual = clicks / impressions if impressions else 0
        exp = expected_ctr(pos)
        gap = exp - actual
        if gap <= 0.01:
            continue
        score = gap * min(1.0, impressions / 500.0) * 20
        out.append(_item(domain, row.get("page") or "", "ctr_below_expected",
                          {"source": "gsc", "date": env.get("collected_at")}, "rewrite_for_ctr",
                          policy_mode, "ctr", 28, score,
                          notes=f"query={row.get('query')!r} position={round(pos,1)} actual_ctr={round(actual,4)} expected_ctr={exp}"))
    return out


def detect_decay(domain, signals: SiteSignals, policy_mode, *, min_impressions=20) -> list[dict]:
    """Period-over-period decline in clicks or impressions for a page/query."""
    current = signals.latest("gsc")
    previous = signals.previous_ok("gsc")
    if not current or not previous or current.get("status") != "ok":
        return []
    cur_rows = {(r.get("query"), r.get("page")): r for r in (current.get("data") or {}).get("rows") or []}
    prev_rows = {(r.get("query"), r.get("page")): r for r in (previous.get("data") or {}).get("rows") or []}
    out = []
    for key, prow in prev_rows.items():
        crow = cur_rows.get(key)
        prev_clicks, prev_impr = prow.get("clicks") or 0, prow.get("impressions") or 0
        if prev_impr < min_impressions:
            continue
        cur_clicks = (crow or {}).get("clicks") or 0
        cur_impr = (crow or {}).get("impressions") or 0
        if prev_clicks <= 0:
            continue
        decline = (prev_clicks - cur_clicks) / prev_clicks
        if decline < 0.25:
            continue
        score = decline * min(1.0, prev_impr / 500.0) * 15
        out.append(_item(domain, key[1] or "", "decaying_query",
                          {"source": "gsc", "date": current.get("collected_at"), "compared_to": previous.get("collected_at")},
                          "refresh_decaying_content", policy_mode, "clicks", 28, score,
                          notes=f"query={key[0]!r} clicks {prev_clicks}->{cur_clicks} ({round(decline*100,1)}% decline), impressions {prev_impr}->{cur_impr}"))
    return out


def detect_technical_audit_findings(domain, signals: SiteSignals, policy_mode) -> list[dict]:
    env = signals.latest("audit")
    if not env or env.get("status") != "ok":
        return []
    data = env.get("data") or {}
    issues = data.get("issues") or {}
    action_map = {
        "title_too_long": "fix_title_length", "title_too_short": "fix_title_length",
        "title_missing": "fix_title_length", "duplicate_title": "fix_title_length",
        "meta_desc_too_long": "fix_meta_description", "meta_desc_missing": "fix_meta_description",
        "duplicate_meta_description": "fix_meta_description",
        "canonical_missing": "fix_canonical", "canonical_mismatch": "fix_canonical",
        "noindex_on_indexable_page": "fix_noindex_mistake",
        "orphan_in_sitemap": "add_internal_link", "orphan_page": "add_internal_link",
    }
    severity = data.get("severity") or {}
    errors = set(severity.get("errors") or [])
    out = []
    for issue_key, targets in issues.items():
        action_type = action_map.get(issue_key)
        if not action_type or not isinstance(targets, list):
            continue
        is_error = issue_key in errors
        for target in targets[:50]:
            url = str(target).split(" (", 1)[0]
            score = (8.0 if is_error else 4.0)
            out.append(_item(domain, url, f"technical_audit:{issue_key}",
                              {"source": "audit", "date": env.get("collected_at")}, action_type,
                              policy_mode, "impressions", 28, score,
                              notes=f"{issue_key} ({'error' if is_error else 'warning'})"))
    for link in (data.get("broken_links_all") or [])[:100]:
        url = link.get("url") if isinstance(link, dict) else str(link)
        out.append(_item(domain, url or "", "technical_audit:broken_link",
                          {"source": "audit", "date": env.get("collected_at")}, "fix_broken_link",
                          policy_mode, "impressions", 28, 6.0, notes="broken link found in crawl"))
    return out


def detect_indexing_coverage(domain, signals: SiteSignals, policy_mode) -> list[dict]:
    """Indexing/coverage problems from a URL-inspection or sitemap-error lane, if present.

    This lane is not yet universally collected; when absent this detector is a no-op,
    and the queue reflects that rather than fabricating findings.
    """
    env = signals.latest("indexing")
    if not env or env.get("status") != "ok":
        return []
    data = env.get("data") or {}
    out = []
    for row in data.get("rows") or data.get("urls") or []:
        if not isinstance(row, dict):
            continue
        status = str(row.get("coverage_state") or row.get("index_status") or "").lower()
        url = row.get("url") or row.get("inspection_url") or ""
        if not url:
            continue
        problem = any(k in status for k in ("not indexed", "error", "excluded", "blocked"))
        if not problem:
            continue
        action_type = "resubmit_sitemap" if "sitemap" in status else "request_indexing"
        out.append(_item(domain, url, "indexing_coverage",
                          {"source": "indexing", "date": env.get("collected_at")}, action_type,
                          policy_mode, "impressions", 28, 7.0, notes=status))
    for entry in data.get("sitemap_errors") or []:
        out.append(_item(domain, str(entry.get("url") if isinstance(entry, dict) else entry) or "",
                          "indexing_coverage:sitemap_error", {"source": "indexing", "date": env.get("collected_at")},
                          "resubmit_sitemap", policy_mode, "impressions", 28, 6.0))
    return out


def detect_cwv_failures(domain, signals: SiteSignals, policy_mode, *, pagespeed_scores: dict[str, Any] | None = None) -> list[dict]:
    out = []
    env = signals.latest("cwv")
    if env and env.get("status") == "ok":
        data = env.get("data") or {}
        for row in data.get("rows") or []:
            if not isinstance(row, dict):
                continue
            failing = row.get("failing_metrics") or ([row["metric"]] if row.get("status") == "fail" and row.get("metric") else [])
            if not failing:
                continue
            url = row.get("url") or ""
            out.append(_item(domain, url, "cwv_failure", {"source": "cwv", "date": env.get("collected_at")},
                              "improve_cwv", policy_mode, "impressions", 42, 6.0 + len(failing), notes=",".join(failing)))
    if pagespeed_scores:
        entry = pagespeed_scores.get(domain) or pagespeed_scores.get(domain.removeprefix("www."))
        if entry and isinstance(entry.get("performance"), (int, float)) and entry["performance"] < 70:
            gap = 70 - entry["performance"]
            out.append(_item(domain, "", "pagespeed_below_threshold",
                              {"source": "performance_baseline", "date": None}, "improve_cwv",
                              policy_mode, "impressions", 42, gap / 5.0,
                              notes=f"PSI performance score {entry['performance']}"))
    return out


def detect_orphan_weak_pages(domain, signals: SiteSignals, policy_mode) -> list[dict]:
    env = signals.latest("audit")
    if not env or env.get("status") != "ok":
        return []
    data = env.get("data") or {}
    out = []
    for url in (data.get("issues") or {}).get("orphan_in_sitemap") or []:
        url = str(url).split(" (", 1)[0]
        out.append(_item(domain, url, "orphan_page", {"source": "audit", "date": env.get("collected_at")},
                          "add_internal_link", policy_mode, "impressions", 28, 5.0,
                          notes="in sitemap but not linked from crawled pages"))
    ilinks = signals.latest("internal_links")
    if ilinks and ilinks.get("status") == "ok":
        for row in (ilinks.get("data") or {}).get("weak_pages") or []:
            url = row.get("url") if isinstance(row, dict) else str(row)
            inbound = row.get("inbound_links", 0) if isinstance(row, dict) else 0
            out.append(_item(domain, url or "", "weak_internal_links",
                              {"source": "internal_links", "date": ilinks.get("collected_at")}, "add_internal_link",
                              policy_mode, "impressions", 28, max(1.0, 4 - inbound),
                              notes=f"inbound_links={inbound}"))
    return out


DETECTORS: list[Callable[..., list[dict]]] = [
    detect_striking_distance, detect_ctr_below_expected, detect_decay,
    detect_technical_audit_findings, detect_indexing_coverage,
    detect_cwv_failures, detect_orphan_weak_pages,
]


def build_site_queue(root: str | Path, domain: str, policy_mode: str, *,
                      pagespeed_scores: dict[str, Any] | None = None,
                      apply_feedback: bool = True) -> list[dict]:
    signals = load_site_signals(root, domain=domain, policy_mode=policy_mode)
    items: list[dict] = []
    for detector in DETECTORS:
        try:
            if detector is detect_cwv_failures:
                items.extend(detector(domain, signals, policy_mode, pagespeed_scores=pagespeed_scores))
            else:
                items.extend(detector(domain, signals, policy_mode))
        except Exception as error:  # a single bad detector/signal must not blank the queue
            items.append({"site": domain, "url": "", "detector": f"{detector.__name__}:error",
                          "evidence": {"source": "internal", "date": None}, "proposed_action": {"type": "none"},
                          "risk_class": "forbidden", "expected_metric": None, "measurement_window_days": 0,
                          "score": 0.0, "error": type(error).__name__})
    if apply_feedback:
        try:
            from change_measurement import load_feedback_multipliers
            multipliers = load_feedback_multipliers(root)
        except Exception:
            multipliers = {}
        for item in items:
            factor = multipliers.get(item["detector"])
            if factor:
                item["score"] = round(item["score"] * factor, 4)
                item["feedback_multiplier"] = factor
    items.sort(key=lambda x: x["score"], reverse=True)
    return items


def build_portfolio_queue(portfolio_path: str | Path, *, reports_dir: str | Path | None = None) -> dict[str, Any]:
    portfolio_path = Path(portfolio_path)
    config = json.loads(portfolio_path.read_text(encoding="utf-8"))
    roots = config.get("roots") or []
    reports_dir = Path(reports_dir) if reports_dir else portfolio_path.parent / "reports"
    pagespeed_scores = load_pagespeed_scores(reports_dir)

    sites_out = []
    all_items = []
    for root in roots:
        root = (portfolio_path.parent / root).resolve() if not Path(root).is_absolute() else Path(root)
        try:
            policy = load_policy(root)
        except (OSError, ValueError, TypeError) as error:
            sites_out.append({"root": str(root), "status": "blocked", "error": type(error).__name__})
            continue
        domain, mode = policy["domain"], policy["policy"]["mode"]
        items = build_site_queue(root, domain, mode, pagespeed_scores=pagespeed_scores)
        for item in items:
            item["policy_mode"] = mode
        all_items.extend(items)
        sites_out.append({"root": str(root), "domain": domain, "policy_mode": mode,
                          "status": "ok", "opportunity_count": len(items),
                          "top_score": items[0]["score"] if items else 0.0,
                          "opportunities": items})
    portfolio_ranked = sorted(all_items, key=lambda x: x["score"], reverse=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "scope": "read-only ranking over already-collected local evidence; not a live-provider call",
        "sites": sites_out,
        "portfolio_queue": portfolio_ranked,
        "portfolio_queue_top": portfolio_ranked[:50],
        "risk_class_legend": {
            "auto_safe": "metadata/internal-link technical repair, no editorial or acquisition judgment required",
            "needs_review": "content or off-site action; requires human/editorial approval before execution",
            "forbidden": "site policy (technical_only/read_only/monitoring-only) disallows this action here",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("site", help="rank opportunities for one site root")
    p.add_argument("root")
    p.add_argument("--domain", required=True)
    p.add_argument("--policy-mode", default="read_only", choices=("read_only", "technical_only", "approved"))
    p.add_argument("--out")

    p = sub.add_parser("portfolio", help="rank opportunities across a portfolio.json")
    p.add_argument("portfolio")
    p.add_argument("--reports-dir")
    p.add_argument("--out")

    args = ap.parse_args()
    if args.command == "site":
        result = {"schema_version": SCHEMA_VERSION, "generated_at": _now_iso(),
                  "site": args.domain, "opportunities": build_site_queue(args.root, args.domain, args.policy_mode)}
    else:
        result = build_portfolio_queue(args.portfolio, reports_dir=args.reports_dir)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
