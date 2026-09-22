#!/usr/bin/env python3
"""Import manually exported Google Search Console Links CSVs.

GSC Links exports are sampled observations. This importer does not fetch links,
infer missing targets, score toxicity, or create a disavow file.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seo_state import atomic_json, state_dir, transaction_lock

DEFAULT_MAX_ROWS = 100_000
DEFAULT_MAX_BYTES = 25 * 1024 * 1024


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().casefold()).strip()


def _field(row: dict[str, object], names: tuple[str, ...]) -> object:
    fields = {_key(k): v for k, v in row.items()}
    for name in names:
        if _key(name) in fields:
            return fields[_key(name)]
    return None


def safe_url(value: object, *, allow_bare_domain: bool = False) -> str | None:
    """Return a bounded HTTP(S) URL, or None for an absent value."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError("URL contains control characters")
    candidate = text if "://" in text else ("https://" + text if allow_bare_domain else text)
    parsed = urlsplit(candidate)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"unsafe URL: {text!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs with embedded credentials are not accepted")
    try:
        host = parsed.hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"invalid URL hostname: {text!r}") from exc
    if not host or len(candidate) > 8192:
        raise ValueError(f"invalid URL: {text!r}")
    # Preserve exported URL text while checking the normalized host.
    return text


def _number(value: object) -> int | float | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip().replace(",", "")
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"invalid link count: {value!r}") from exc
    if number < 0 or not number.is_integer():
        raise ValueError(f"link count must be a non-negative integer: {value!r}")
    return int(number)


def _domain(value: object) -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    parsed = urlsplit(text if "://" in text else "https://" + text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"unsafe referring domain: {text!r}")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError(f"invalid referring domain: {text!r}")
    return parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")


def _site(root: Path, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    config = state_dir(root) / "site.yaml"
    if not config.exists():
        return None
    try:
        data = json.loads(config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for key in ("site", "domain", "property", "url"):
        if data.get(key):
            return str(data[key])
    return None


def read_csv(path: Path, max_bytes: int, max_rows: int) -> list[dict[str, str]]:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"CSV exceeds size cap ({max_bytes} bytes)")
    raw = path.read_bytes()
    encoding = "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            if row_number > max_rows + 1:
                raise ValueError(f"CSV exceeds row cap ({max_rows} rows)")
            rows.append({str(k): (v or "") for k, v in row.items() if k is not None})
    return rows


def import_rows(root: str | Path, file: str | Path, fmt: str = "auto", *, site: str | None = None,
                collected_at: str | None = None, max_rows: int = DEFAULT_MAX_ROWS,
                max_bytes: int = DEFAULT_MAX_BYTES) -> dict:
    if max_rows < 0 or max_bytes < 0:
        raise ValueError("row and byte caps must be non-negative")
    root_path, source = Path(root).resolve(), Path(file).resolve()
    rows = read_csv(source, max_bytes, max_rows)
    headers = {_key(name) for name in (rows[0].keys() if rows else [])}
    link_headers = {"source url", "source", "url from", "linking page"}
    domain_headers = {"top linking sites", "linking site", "referring domain", "domain"}
    if fmt == "auto":
        if headers & domain_headers and not (headers & link_headers):
            fmt = "gsc-domains"
        else:
            fmt = "gsc-links"
    if fmt not in {"gsc-links", "gsc-domains"}:
        raise ValueError("format must be gsc-links, gsc-domains, or auto")

    output_rows: list[dict] = []
    domain_counts: Counter[str] = Counter()
    domain_values: dict[str, int | None] = {}
    seen_links: set[tuple[str, str | None]] = set()
    for row in rows:
        if fmt == "gsc-domains":
            domain = _domain(_field(row, ("top linking sites", "linking site", "referring domain", "domain")))
            count = _number(_field(row, ("links", "link count", "number of links", "backlinks")))
            if domain is None:
                continue
            domain_values[domain] = count
            continue
        source_url = safe_url(_field(row, ("source url", "source", "url from", "linking page")))
        target_raw = _field(row, ("target url", "target", "url to", "target page", "linked page"))
        target_url = safe_url(target_raw) if target_raw is not None and str(target_raw).strip() else None
        if source_url is None:
            continue
        link_key = (source_url, target_url)
        if link_key in seen_links:
            continue
        seen_links.add(link_key)
        source_host = urlsplit(source_url).hostname
        if not source_host:
            raise ValueError(f"source URL has no hostname: {source_url!r}")
        domain = source_host.encode("idna").decode("ascii").lower().rstrip(".")
        domain_counts[domain] += 1
        output_rows.append({
            "source_url": source_url,
            "target_url": target_url,
            "referring_domain": domain,
            "anchor": None,
            "rel": None,
        })

    if fmt == "gsc-domains":
        domains = [{"domain": domain, "links": domain_values[domain]} for domain in sorted(domain_values)]
    else:
        domains = [{"domain": domain, "links": count} for domain, count in sorted(domain_counts.items())]
    envelope = {
        "schema_version": 1,
        "site": _site(root_path, site),
        "provider": "gsc_export",
        "status": "ok",
        "collected_at": collected_at or "unknown",
        "imported_at": now(),
        "coverage": {"complete": False, "scope": fmt, "source_rows": len(rows)},
        "rows": output_rows,
        "domains": domains,
        "referring_domains": len(domains),
    }
    destination = root_path / ".seo" / "reports" / "gsc-links.json"
    with transaction_lock(destination.parent):
        atomic_json(destination, envelope)
    return envelope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--file", required=True)
    parser.add_argument("--format", choices=("gsc-links", "gsc-domains", "auto"), default="auto")
    parser.add_argument("--site")
    parser.add_argument("--collected-at")
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args(argv)
    result = import_rows(args.root, args.file, args.format, site=args.site,
                         collected_at=args.collected_at, max_rows=args.max_rows,
                         max_bytes=args.max_bytes)
    print(json.dumps({"status": result["status"], "path": str(Path(args.root).resolve() / ".seo" / "reports" / "gsc-links.json"),
                      "rows": len(result["rows"]), "referring_domains": result["referring_domains"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
