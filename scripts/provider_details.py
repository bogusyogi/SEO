#!/usr/bin/env python3
"""Bounded, read-only provider evidence collector for configured SEO sites.

The collector intentionally records incomplete coverage.  It is a snapshot helper,
not a scheduler, index submitter, or publishing adapter.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from seo_state import atomic_json, state_dir  # noqa: E402
from seo_project import load_site  # noqa: E402

SCHEMA_VERSION = 1
MAX_GSC_ROWS = 1000
MAX_INSPECTIONS = 6
MAX_BING_TARGETS = 10
TIMEOUT = 20


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _dates(now: datetime | None = None) -> dict[str, dict[str, str]]:
    today = (now or _now()).date()
    # GSC normally has a short reporting delay.  Keep two non-overlapping windows.
    end = today - timedelta(days=3)
    current_start = end - timedelta(days=27)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=27)
    daily_start = end - timedelta(days=55)
    return {
        "current": {"start": current_start.isoformat(), "end": end.isoformat()},
        "previous": {"start": previous_start.isoformat(), "end": previous_end.isoformat()},
        "daily": {"start": daily_start.isoformat(), "end": end.isoformat()},
    }


def _error(exc: Exception) -> str:
    """Return provider-safe errors without tokens, URLs with query strings, or bodies."""
    msg = re.sub(r"([?&](?:key|apikey|token|access_token|authorization)=)[^&\s]+", r"\1<redacted>", str(exc), flags=re.I)
    msg = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1<redacted>", msg)
    for name in ("AHREFS_API_KEY", "BING_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_API_KEY"):
        secret = os.environ.get(name)
        if secret and len(secret) >= 4:
            msg = msg.replace(secret, "<redacted>")
    return msg[:500]


def _host(site: dict[str, Any]) -> str:
    domain = str(site.get("domain") or "").strip().lower().rstrip(".")
    if not domain:
        raise ValueError("site domain is missing")
    return domain.removeprefix("www.")


def _owned_url(url: str, host: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        candidate = (parsed.hostname or "").lower().rstrip(".").removeprefix("www.")
        return parsed.scheme in {"http", "https"} and candidate == host
    except ValueError:
        return False


def _origin(site: dict[str, Any]) -> str:
    value = str(site.get("url") or site.get("origin") or "")
    if not value:
        value = "https://" + _host(site)
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not _owned_url(value, _host(site)):
        value = "https://" + _host(site)
    return value.rstrip("/")


def _status(result: dict[str, Any], err_key: str = "error") -> str:
    if result.get(err_key):
        return "partial" if any(result.get(k) for k in ("rows", "current", "daily", "totals")) else "error"
    return "ok"


def _gsc(site_url: str, dates: dict[str, dict[str, str]]) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "missing", "date_range": dates, "current": {}, "previous": {}, "daily": [], "devices": [], "countries": [], "pages": [], "query_changes": [], "coverage": {}}
    try:
        from gsc_query_v2 import query
        def ask(period: str, dims: list[str], limit: int = MAX_GSC_ROWS) -> dict[str, Any]:
            d = dates[period]
            return query(site_url, d["start"], d["end"], dims, "web", min(1000, limit), limit)
        cur = ask("current", [])
        prev = ask("previous", [])
        prev_queries = ask("previous", ["query"], MAX_GSC_ROWS)
        daily = ask("daily", ["date"], 1000)
        devices = ask("current", ["device"], 1000)
        countries = ask("current", ["country"], 1000)
        pages = ask("current", ["page"], MAX_GSC_ROWS)
        queries = ask("current", ["query"], MAX_GSC_ROWS)
        out.update(current=cur.get("aggregate", cur.get("totals", {})), previous=prev.get("aggregate", prev.get("totals", {})), daily=daily.get("rows", []), devices=devices.get("rows", []), countries=countries.get("rows", []), pages=pages.get("rows", []))
        old_rows = {r.get("query"): r for r in prev_queries.get("rows", []) if r.get("query")}
        changes = []
        seen_queries = set()
        for row in queries.get("rows", []):
            q = row.get("query")
            if not q: continue
            seen_queries.add(q)
            old = old_rows.get(q, {})
            changes.append({"query": q, "clicks": row.get("clicks"), "previous_clicks": old.get("clicks"), "impressions": row.get("impressions"), "previous_impressions": old.get("impressions"), "position": row.get("position"), "previous_position": old.get("position")})
        for q, old in old_rows.items():
            if q not in seen_queries:
                changes.append({"query": q, "clicks": None, "previous_clicks": old.get("clicks"), "impressions": None, "previous_impressions": old.get("impressions"), "position": None, "previous_position": old.get("position"), "missing_observation": True})
        out["query_changes"] = changes
        out["coverage"] = {"query_rows": len(queries.get("rows", [])), "query_cap": MAX_GSC_ROWS, "query_hit_cap": bool(queries.get("coverage", {}).get("hit_client_cap")), "note": "Aggregate totals are dimensionless; dimension rows may omit anonymized or low-volume queries."}
        errors = [x.get("error") for x in (cur, prev, prev_queries, daily, devices, countries, pages, queries) if x.get("error")]
        out["status"] = "partial" if errors else "ok"
        if errors: out["error"] = _error(Exception(errors[0]))
    except Exception as exc:
        out["status"], out["error"] = "error", _error(exc)
    return out


def _ga4(property_id: str, host: str, dates: dict[str, dict[str, str]]) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "missing", "date_range": None, "totals": {}, "daily": [], "pages": [], "devices": [], "countries": [], "currency": None, "time_zone": None, "event_arrival": "unknown"}
    try:
        import ga4_report
        days = 28
        hostnames = [host] if host.startswith("www.") else [host, "www." + host]
        report = ga4_report.organic_traffic_report(property_id, days=days, limit=100, hostnames=hostnames)
        out.update(date_range=report.get("date_range"), totals=report.get("totals", {}), daily=report.get("daily_data", []), pages=report.get("top_pages", []), currency=(report.get("metadata") or {}).get("currency_code"), time_zone=(report.get("metadata") or {}).get("time_zone"))
        lane_errors = []
        try:
            device = ga4_report.device_breakdown(property_id, days=28, hostnames=hostnames)
            out["devices"] = device.get("devices", [])
            if device.get("error"): lane_errors.append(device["error"])
        except Exception as exc: lane_errors.append(_error(exc))
        try:
            country = ga4_report.country_breakdown(property_id, days=28, limit=100, hostnames=hostnames)
            out["countries"] = country.get("countries", [])
            if country.get("error"): lane_errors.append(country["error"])
        except Exception as exc: lane_errors.append(_error(exc))
        # key_events is actual observed event data; zero/absent is not proof of arrival.
        if float(out["totals"].get("key_events") or 0) > 0: out["event_arrival"] = "verified"
        out["status"] = "partial" if report.get("error") or lane_errors else "ok"
        if report.get("error") or lane_errors: out["error"] = _error(Exception(report.get("error") or lane_errors[0]))
    except Exception as exc:
        out["status"], out["error"] = "error", _error(exc)
    return out


def _sitemap_urls(site: dict[str, Any], host: str, limit: int = MAX_BING_TARGETS) -> list[str]:
    url = _origin(site) + "/sitemap.xml"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "standalone-seo/1"})
        body = urllib.request.urlopen(req, timeout=TIMEOUT).read(2_000_000)
        root = ET.fromstring(body)
        urls = []
        for loc in root.iter():
            if loc.tag.rsplit("}", 1)[-1] == "loc" and loc.text and _owned_url(loc.text.strip(), host): urls.append(loc.text.strip())
        return urls[:limit]
    except Exception:
        return []


def _bing(site: dict[str, Any], host: str, gsc_pages: list[dict[str, Any]], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "missing", "rows": [], "referring_domains": [], "coverage": {"complete": False, "scope": "sampled owned target URLs"}, "newly_observed": [], "missing": []}
    props = site.get("properties") or {}
    bing_site = props.get("bing") or site.get("bing_site")
    if not bing_site or not os.environ.get("BING_API_KEY"):
        out["status"] = "missing"
        out["error"] = "Bing property or BING_API_KEY not configured"
        return out
    try:
        import bing_webmaster
        urls = [_origin(site)]
        for row in gsc_pages:
            candidate = row.get("page")
            if candidate and _owned_url(candidate, host) and candidate not in urls: urls.append(candidate)
        urls.extend(x for x in _sitemap_urls(site, host) if x not in urls)
        rows = []
        stats: dict[str, Any] = {}
        for method, key in (("GetQueryStats", "queries"), ("GetPageStats", "pages"), ("GetCrawlIssues", "crawl")):
            response = bing_webmaster.call(method, params={"siteUrl": str(bing_site)})
            if response.get("error"):
                out.setdefault("errors", []).append(_error(Exception(response["error"])))
            else:
                stats[key] = response.get("d", [])
        out.update(stats=stats)
        for target in urls[: MAX_BING_TARGETS + 1]:
            result = bing_webmaster.links(str(bing_site), target, max_pages=1)
            rows.extend(result.get("rows", []))
            if result.get("error") and not rows: out["error"] = _error(Exception(result["error"]))
        out["rows"] = rows
        out["referring_domains"] = sorted({(urllib.parse.urlparse(r.get("source_url") or "").hostname or "").lower() for r in rows if urllib.parse.urlparse(r.get("source_url") or "").hostname})
        target_urls = urls[: MAX_BING_TARGETS + 1]
        out["coverage"] = {"complete": False, "targets_requested": len(target_urls), "target_urls": target_urls, "scope": "sampled owned target URLs; not a web-wide backlink census"}
        old_cov = (previous or {}).get("coverage", {})
        old_rows = (previous or {}).get("rows", [])
        if old_cov.get("target_urls") == target_urls:
            current_keys = {(r.get("source_url"), r.get("target_url")) for r in rows}
            previous_keys = {(r.get("source_url"), r.get("target_url")) for r in old_rows}
            out["newly_observed"] = [{"source_url": s, "target_url": t} for s, t in sorted(current_keys - previous_keys)]
            out["missing"] = [{"source_url": s, "target_url": t} for s, t in sorted(previous_keys - current_keys)]
        out["status"] = "partial" if out.get("error") or out.get("errors") else "ok"
    except Exception as exc: out["status"], out["error"] = "error", _error(exc)
    return out


def _indexing(site: dict[str, Any], host: str, gsc_pages: list[dict[str, Any]]) -> dict[str, Any]:
    out = {"status": "missing", "rows": [], "coverage": {"complete": False, "scope": "homepage plus up to five important/GSC pages"}}
    prop = (site.get("properties") or {}).get("gsc") or site.get("gsc_property")
    if not prop: return out | {"error": "GSC property not configured"}
    try:
        import gsc_inspect
        urls = [_origin(site)]
        for row in gsc_pages:
            u = row.get("page")
            if u and _owned_url(u, host) and u not in urls: urls.append(u)
        for u in urls[:MAX_INSPECTIONS]: out["rows"].append(gsc_inspect.inspect_url(u, str(prop)))
        out["status"] = "partial" if any(r.get("error") for r in out["rows"]) else "ok"
        out["coverage"] = {"complete": False, "urls_requested": min(len(urls), MAX_INSPECTIONS), "scope": "homepage plus up to five important/GSC pages"}
    except Exception as exc: out["status"], out["error"] = "error", _error(exc)
    return out


def _ahrefs(site: dict[str, Any], host: str) -> dict[str, Any]:
    out = {"status": "missing", "value": None, "collected_at": None, "provider": "ahrefs", "attribution": "Domain Rating by Ahrefs"}
    key = os.environ.get("AHREFS_API_KEY")
    if not key: return out | {"error": "AHREFS_API_KEY not configured"}
    try:
        query = urllib.parse.urlencode({"target": host, "mode": "domain"})
        req = urllib.request.Request("https://api.ahrefs.com/v3/public/domain-rating-free?" + query, headers={"Authorization": "Bearer " + key, "User-Agent": "standalone-seo/1"})
        payload = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8"))
        value = payload.get("domain_rating", payload.get("domainRating"))
        if isinstance(value, dict): value = value.get("domain_rating", value.get("domainRating"))
        if value is None: raise ValueError("Ahrefs response did not contain domain rating")
        out.update(status="ok", value=value, collected_at=_now().isoformat().replace("+00:00", "Z"))
    except Exception as exc: out.update(status="error", error=_error(exc))
    return out


def collect_site(root: str | Path, *, only: set[str] | None = None, skip_fresh: int = 0) -> dict[str, Any]:
    root = Path(root).resolve()
    state_path = state_dir(root) / "site.yaml"
    try: site = load_site(root)
    except Exception as exc: site = {"domain": root.name, "_load_error": _error(exc)}
    host = _host(site)
    out_path = state_dir(root) / "reports" / "provider-details.json"
    existing: dict[str, Any] = {}
    try: existing = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, ValueError): pass
    if not isinstance(existing, dict) or existing.get('schema_version') != SCHEMA_VERSION or existing.get('site') != site.get('domain'):
        existing = {}
    dates = _dates()
    props = site.get("properties") or {}
    def fresh(value: dict[str, Any] | None) -> bool:
        if not value or value.get("status") != "ok" or not value.get("collected_at") or skip_fresh <= 0:
            return False
        try:
            stamp = datetime.fromisoformat(str(value["collected_at"]).replace("Z", "+00:00"))
            age = (_now() - stamp).total_seconds()
            return 0 <= age <= skip_fresh * 60
        except (TypeError, ValueError):
            return False
    def run(name: str, factory: Callable[[], dict[str, Any]], default: dict[str, Any]) -> dict[str, Any]:
        if only is not None and name not in only:
            return existing.get(name) or default
        if fresh(existing.get(name)):
            return existing[name]
        try:
            return factory()
        except Exception as exc:
            return {**default, 'status': 'error', 'error': _error(exc)}
    gsc_default = {"status": "missing", "date_range": dates, "current": {}, "previous": {}, "daily": [], "devices": [], "countries": [], "pages": [], "query_changes": [], "coverage": {}}
    ga4_default = {"status": "missing", "date_range": None, "totals": {}, "daily": [], "pages": [], "devices": [], "countries": [], "currency": None, "time_zone": None, "event_arrival": "unknown"}
    gsc = run("gsc", lambda: _gsc(str(props.get("gsc") or site.get("gsc_property") or ""), dates), gsc_default) if (props.get("gsc") or site.get("gsc_property")) else gsc_default
    ga4 = run("ga4", lambda: _ga4(str(props.get("ga4") or site.get("ga4_property") or ""), host, dates), ga4_default) if (props.get("ga4") or site.get("ga4_property")) else ga4_default
    indexing = run("indexing", lambda: _indexing(site, host, gsc.get("pages", [])), {"status": "missing", "rows": [], "coverage": {}})
    bing_default = {"status": "missing", "rows": [], "referring_domains": [], "coverage": {}, "newly_observed": [], "missing": []}
    old_bing = existing.get("backlinks") or existing.get("bing")
    bing = (old_bing if fresh(old_bing) else _bing(site, host, gsc.get("pages", []), old_bing)
            if only is None or "bing" in only or "backlinks" in only
            else (existing.get("bing") or existing.get("backlinks") or bing_default))
    backlinks = bing
    ahrefs = run("domain_rating", lambda: _ahrefs(site, host), {"status": "missing", "value": None, "collected_at": None, "provider": "ahrefs", "attribution": "Domain Rating by Ahrefs"})
    collected = _now().isoformat().replace("+00:00", "Z")
    for lane in (gsc, ga4, indexing, backlinks, ahrefs):
        if lane.get("status") == "ok":
            lane.setdefault("collected_at", collected)
    errors = []
    for name, item in (("gsc", gsc), ("ga4", ga4), ("indexing", indexing), ("backlinks", backlinks), ("bing", bing), ("domain_rating", ahrefs)):
        if item.get("error"): errors.append({"provider": name, "message": item["error"]})
        for message in item.get("errors", []): errors.append({"provider": name, "message": message})
    lane_values = (gsc, ga4, indexing, backlinks, ahrefs)
    overall = "partial" if errors or any(x.get("status") in {"missing", "error", "partial"} for x in lane_values) else "ok"
    payload = {"schema_version": SCHEMA_VERSION, "site": site.get("domain"), "collected_at": collected, "status": overall, "gsc": gsc, "ga4": ga4, "indexing": indexing, "backlinks": backlinks, "bing": bing, "domain_rating": ahrefs, "errors": errors}
    atomic_json(out_path, payload)
    return payload


def collect_roots(roots: list[str | Path], *, only: set[str] | None = None, skip_fresh: int = 0) -> list[dict[str, Any]]:
    def one(root):
        try:
            result = collect_site(root, only=only, skip_fresh=skip_fresh)
            print(f"provider-details {result.get('site')}: {result.get('status')}", file=sys.stderr)
            return result
        except Exception as exc:
            return {"site": str(root), "status": "error", "errors": [{"provider": "collector", "message": _error(exc)}]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(3, max(1, len(roots)))) as pool:
        return list(pool.map(one, roots))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--root")
    group.add_argument("--portfolio")
    ap.add_argument("--only", help="comma-separated lanes: gsc,ga4,indexing,backlinks,bing,domain_rating")
    ap.add_argument("--skip-fresh", type=int, default=0, metavar="MINUTES", help="reuse saved report when newer than this many minutes")
    args = ap.parse_args(argv)
    if args.root: roots = [args.root]
    else:
        from portfolio import roots_from
        roots = roots_from(args.portfolio)
    allowed = {"gsc", "ga4", "indexing", "backlinks", "bing", "domain_rating"}
    only = {x.strip() for x in args.only.split(",") if x.strip()} if args.only else None
    if only is not None and not only <= allowed: ap.error("--only contains unknown lane")
    if args.skip_fresh < 0: ap.error("--skip-fresh must be non-negative")
    result = collect_roots(roots, only=only, skip_fresh=args.skip_fresh)
    overall = result[0] if args.root else {"status": "ok" if all(item.get("status") == "ok" for item in result) else "partial", "sites": result}
    # Provider data contains non-ASCII; a redirected Windows console defaults to cp1252.
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(overall, indent=2, ensure_ascii=False))
    return 0 if all(item.get("status") == "ok" for item in result) else 2


if __name__ == "__main__": raise SystemExit(main())
