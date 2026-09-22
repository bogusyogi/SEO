# Signals — collected evidence schema

This document is the field-level reference for everything `collector.py` / `seo_runner.py`
collect and store, for a downstream decision/opportunity layer to consume. It is precise
about field names, types, storage paths and units. All collection is free-tier, read-only,
first-party (Google Search Console API, Bing Webmaster API, GA4 Data API, CrUX/PageSpeed
Insights, and the project's own crawler) — no paid provider is used.

## Storage convention

Every collector lane, when run through `seo_runner.tick`, is wrapped in a common envelope
and written to `<state_dir>/<lane>/<UTC timestamp>.json`:

```json
{
  "schema_version": 2,
  "site": "example.com",
  "lane": "<lane name>",
  "collected_at": "2026-09-23T00:00:00+00:00",
  "status": "ok | partial | failed",
  "error": "string or null",
  "data": { "...": "lane-specific payload, see below" },
  "hostname_scope": ["example.com"],
  "collection_route": "standalone_direct",
  "scope": "owned site; unavailable data is not zero"
}
```

### Measured-zero vs missing (binding convention — apply this to every new collector)

- `status: "ok"` with a genuinely empty result (`rows: []`, `issue_count: 0`, `sitemaps: []`,
  etc.) means the API was queried successfully and reported nothing — a **measured zero**.
  Consumers may treat this as a real "no issues" / "no data in this window" fact.
- `status: "partial"` or `"failed"` with `data` containing `error` (and, for the new
  collectors below, `null` in the numeric/list fields) means evidence is **missing** —
  the API could not be reached, credentials were absent, or the response shape was not
  recognized. Consumers must never coerce a missing value to `0`.
- Never sum dimensioned rows to fabricate a total; GSC totals come from a separate
  dimensionless aggregate query (see `gsc` below), not from summing `gsc_ranks` rows.

## Existing collectors (context, unchanged by this work)

| Lane | Source | Storage | Key fields |
|---|---|---|---|
| `gsc` | GSC Search Analytics, dimensionless aggregate + `query,page` rows | `.seo/gsc/*.json` | `data.aggregate.{clicks,impressions,ctr,position}`, `data.rows[].{query,page,clicks,impressions,ctr,position}`, `data.date_range.{start,end}`, `data.coverage.hit_client_cap` (bool) |
| `gsc_ranks` | GSC Search Analytics, dimensions `query,country,device` | `.seo/ranks/*.json` via `rank_tracker.ingest` | rows normalized to `{query,market,language:'not-reported',device,position,observed_url:null}`; `provider:'google_gsc'`, `observation_type:'gsc_average_position'` — an **average position over the window**, not a single SERP rank |
| `ga4` | GA4 Data API report | `.seo/ga4/*.json` | site-defined report rows plus `property` (numeric GA4 property id, no `properties/` prefix in comparisons) |
| `bing` | Bing Webmaster `GetRankAndTrafficStats` | `.seo/bing/*.json` | traffic/impressions time series, raw `{method,d}` shape |
| `backlinks` | Bing Webmaster `GetUrlLinks`, per configured target URL | `.seo/backlinks/snapshots/*.json` via `backlink_tracker.ingest` | `rows[].{source_url,target_url,anchor,provider:'bing_webmaster'}`; `coverage.{complete,pages_fetched,total_pages,scope}` — sampled from Bing's own index of your owned target URLs, not a web-wide backlink census |
| `audit` | Own crawler: robots.txt, sitemap.xml, canonical, on-page signals | `.seo/audit/*.json` (also written via `--json <path>`) | `pages{url:{status,title,meta_desc,h1,canonical,...}}`, `issues.{missing_canonical,canonical_points_elsewhere,duplicate_title,...}` (arrays of URLs), `coverage.collection_failures` (int) |
| `serp` | Controlled/manual SERP collection (not a paid API) | `.seo/ranks/*.json` via `rank_tracker.ingest` | same shape as `gsc_ranks`, `provider:'dataforseo'` only if that manual/free path is configured — **do not enable a paid tier for this** |

## New collectors added in this change (`signals-expansion`)

### Lane `gsc_sitemaps` — GSC Sitemaps API (list + per-sitemap status)

Fills the gap: sitemap submission/index status was never collected (only `robots.txt`/
`sitemap.xml` discovery via the `audit` crawler, which does not know Google's own
processing state).

- Script: `scripts/gsc_query.py sitemaps --property <site_url>` (already existed;
  now wired into `collector.py` / `seo_runner.LANES` for the first time).
- Auth/scope: `https://www.googleapis.com/auth/webmasters.readonly` (same OAuth/service
  account already used by `gsc`/`gsc_ranks`).
- Storage: `.seo/gsc_sitemaps/<timestamp>.json`, envelope `data` shape:

```json
{
  "property": "sc-domain:example.com",
  "error": "string or null",
  "sitemaps": [
    {
      "path": "https://example.com/sitemap.xml",
      "last_submitted": "RFC3339 timestamp or null",
      "is_pending": false,
      "is_index": false,
      "type": "sitemap | rss | atom | ...",
      "warnings": 0,
      "errors": 0,
      "contents": [ {"type": "web", "submitted": 40, "indexed": 38} ]
    }
  ]
}
```

- Field notes: `warnings`/`errors` are integer counts Google reports for that sitemap
  (units: count, not percent). `contents[].submitted`/`.indexed` are integer URL counts —
  `indexed < submitted` is a real, non-zero gap and must not be reported as "0 issues".
  An empty `sitemaps` list with `error: null` is a **measured zero** (no sitemap
  registered in GSC for this property) — different from `error` being set (missing,
  e.g. permission denied), which the envelope surfaces as `status: "partial"`.
- Property-scope check: `collector.collect` rejects a response whose `property` does not
  exactly match the configured GSC property (`status: "failed"`), the same defense used
  for `gsc`/`gsc_ranks`/`ga4`.

### Lane `bing_crawl` — Bing Webmaster crawl issues (`GetCrawlIssues`)

Fills the gap: Bing Webmaster exposes free crawl-issue data (4xx/5xx, blocked, malware,
etc.) that `bing_webmaster.py` already had a `crawl` subcommand for, but it was never
wired into scheduled collection or normalized to the measured-zero convention.

- Script: `scripts/bing_webmaster.py crawl --site <site_url>` (existing raw call),
  normalized by a new function `collector.normalize_bing_crawl(prop, raw, code)`.
- Auth: `BING_API_KEY` environment variable (same key already used by `bing`/`backlinks`).
- Storage: `.seo/bing_crawl/<timestamp>.json`, envelope `data` shape:

```json
{
  "provider": "bing_webmaster",
  "property": "https://example.com/",
  "status": "ok | failed",
  "error": "string or null",
  "issues": [ {"url": "...", "issue_type": "...", "severity": "...", "detected": "..."} ],
  "issue_count": 0,
  "measured_zero": true,
  "coverage": {"complete": true, "scope": "crawl issues Bing has recorded for this verified property"}
}
```

- On failure (missing `BING_API_KEY`, HTTP error, unexpected response shape, or a
  subprocess timeout), `data.status` is `"failed"`, `data.issues`/`data.issue_count` are
  **`null`** (never `0`), and the outer envelope `status` is `"failed"`. Consumers must
  branch on `issue_count is None` (missing) vs `issue_count == 0` (measured zero,
  `data.measured_zero == true`).
- `issue_type` is read from BWT's `IssueType` field, falling back to `ImgKey` for older
  API responses that only carry the icon-key field; `detected` prefers `DetectedDate`,
  falling back to `CrawlDate`. Bing's `/Date(â€¦)/` JSON date format is passed through
  unparsed — treat it as an opaque provider timestamp string, not a normalized ISO date.

### Lane `gsc_appearance` — GSC Search Analytics, `searchAppearance,device,country` dimensions

Same underlying script (`gsc_query_v2.py`) and schema as `gsc`/`gsc_ranks` (schema_version 2,
`rows[]`/`aggregate`/`coverage` as documented above), just a distinct dimension combination
so a rich-result-driven view (AMP, review snippets, etc.) doesn't get overwritten by the
`query,page` or `query,country,device` schedules. Storage: `.seo/gsc_appearance/*.json`.

### Lane `gsc_inspect_bulk` — GSC URL Inspection API, automatic important-URL list

Bulk-inspects an automatically assembled "important URL" list instead of requiring an
operator-curated one: the top-impression pages from a fresh `page`-dimension GSC query
(sorted client-side by impressions, since the API does not sort by impressions) unioned
with every URL discovered in the site's own sitemap(s) (via the same `site_audit`
discovery functions the `audit`/`sitemap_probe` lanes use), filtered to the site's
configured hostname scope, deduplicated, and capped by `inspect_max_urls` (site.yaml,
default 20, hard bound 1..2000 — the API's own daily quota is 2000/site, 600/minute).

- Storage: `.seo/gsc_inspect_bulk/<timestamp>.json`, `data` shape:

```json
{
  "property": "sc-domain:example.com",
  "error": "string or null",
  "results": [ { "url": "...", "verdict": "PASS|FAIL|NEUTRAL|VERDICT_UNSPECIFIED",
                 "index_status": {"coverage_state": "...", "indexing_state": "...", "page_fetch_state": "...", "..."},
                 "canonical": {"google_canonical": "...", "user_canonical": "...", "match": true},
                 "error": "string or null" } ],
  "summary": {"pass": 0, "fail": 0, "neutral": 0, "error": 0},
  "candidate_sources": {"from_top_impression_pages": 0, "from_sitemap": 0,
                         "considered_in_scope": 0, "inspected": 0, "inspect_max_urls": 20,
                         "daily_quota_note": "GSC URL Inspection allows 2000/day, 600/min per site"}
}
```

- No writes/submissions. `results` empty with `error: null` and `candidate_sources.inspected: 0`
  is a measured zero (no eligible URL found); a non-empty `error` is missing evidence.

### Lane `sitemap_probe` — own-site sitemap reachability (no GSC dependency, never submits)

Answers "does the live site itself serve a sitemap" independently of what is registered
in GSC — for the 5 portfolio sites with zero GSC-registered sitemaps, this tells you
whether a sitemap exists but was never submitted, versus none existing at all. Read-only:
fetches `robots.txt` and probes `/sitemap.xml`; never calls any submission endpoint.

- Storage: `.seo/sitemap_probe/*.json`, `data` shape:

```json
{
  "url": "https://example.com",
  "robots_status": 200,
  "robots_declares_sitemap": false,
  "robots_sitemap_urls": [],
  "default_sitemap_xml_status": 404,
  "default_sitemap_xml_reachable": false,
  "measured_zero": true
}
```

- `measured_zero: true` means robots.txt was fetched successfully (status 200) and
  declared no `Sitemap:` line, and the default `/sitemap.xml` path returned a non-200 —
  a genuine "no sitemap findable" result. A `robots_status` that isn't 200/404 marks the
  envelope `partial` (fetch failed — missing, not zero).

### GA4 lane — added `all_channels_sanity`

`ga4_report.py` gained an `all_channels_sanity` report (`--report sanity`): an
undimensioned, unfiltered 7-day totals query (`sessions`, `total_users`, `event_count`)
across every channel, not just organic. `collector.py`'s `ga4` lane now runs it
automatically alongside the existing organic report and stores it at
`data.all_channels_sanity` in the same `.seo/ga4/*.json` envelope:

```json
"all_channels_sanity": {"property": "properties/123", "report": "all_channels_sanity",
  "date_range": {"start": "...", "end": "..."}, "error": "string or null",
  "totals": {"sessions": 0, "total_users": 0, "event_count": 0}, "measured_zero": true}
```

`measured_zero: true` (all three totals genuinely 0) means GA4 itself saw zero traffic
of any kind in the window — property/tagging is likely broken. `all_channels_sanity`
non-zero alongside a zero organic total in the main report means organic specifically is
zero, not the whole property. Never infer "tagging is broken" from organic being zero alone.

### `crux_history` / `pagespeed` lanes — now orchestrated (previously standalone-only)

No schema change: `crux_history.py --origin --json` and `pagespeed_check.py <url>
--strategy mobile --json` outputs are stored verbatim as `data` under
`.seo/crux_history/*.json` and `.seo/pagespeed/*.json` respectively. Both already
defined `error` at the top level, so they use the same generic ok/partial detection.
`pagespeed` runs `mobile` strategy only by default (schedule cadence/quota reasons —
add a second job entry with different args for `desktop`).

### `site_audit` (own crawl) — hreflang, JSON-LD, robots-meta added to `parse()`

Per-page `pages[url]` signals gained:
- `robots_meta`: list of raw `<meta name="robots"|"googlebot">` content strings; `nofollow`: bool.
- `hreflang`: `{lang code: href}` from `<link rel="alternate" hreflang=...>` tags.
- `jsonld_types`: sorted list of `@type` values found in `application/ld+json` blocks;
  `jsonld_invalid_blocks`: count of blocks that failed to parse as JSON (not silently
  dropped); `jsonld_present`: true if any JSON-LD block (valid or invalid) exists.

New `issues` keys: `missing_structured_data` (warning — no JSON-LD found), `invalid_jsonld`
(error — a block failed to parse), `hreflang_points_offsite` (error — an hreflang alternate
points to a different, unrelated host), `hreflang_missing_self_reference` (warning — a page
declares hreflang alternates but not one pointing at itself, the standard self-reference
requirement). These are mechanical signals, not a schema.org conformance or Google
rich-result eligibility claim.

## Schedule wiring

All new lanes are registered in `seo_runner.LANES` and `site_policy.READ_ACTIONS`, so any
of them can be added to a site's `.seo/schedule.json` exactly like existing lanes, e.g.:

```json
{"jobs":[
  {"lane":"gsc_sitemaps","interval_seconds":604800},
  {"lane":"bing_crawl","interval_seconds":604800},
  {"lane":"gsc_appearance","interval_seconds":86400,"days":28},
  {"lane":"gsc_inspect_bulk","interval_seconds":604800},
  {"lane":"sitemap_probe","interval_seconds":604800},
  {"lane":"crux_history","interval_seconds":604800},
  {"lane":"pagespeed","interval_seconds":604800}
]}
```

All are pure reads: `gsc_sitemaps`/`gsc_appearance`/`gsc_inspect_bulk` use the read-only
GSC scope already granted; `bing_crawl` uses the same read-only BWT API key already
granted for `bing`/`backlinks`; `sitemap_probe` fetches only the site's own robots.txt/
sitemap.xml; `crux_history`/`pagespeed` use `GOOGLE_API_KEY`. None submits, writes, or
mutates anything — `gsc_inspect_bulk` never calls the write-capable indexing/submission
endpoints, only `urlInspection().index().inspect()`.
