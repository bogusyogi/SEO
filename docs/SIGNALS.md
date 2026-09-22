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

## Schedule wiring

Both lanes are registered in `seo_runner.LANES` and `site_policy.READ_ACTIONS`, so they
can be added to any site's `.seo/schedule.json` exactly like existing lanes, e.g.:

```json
{"jobs":[
  {"lane":"gsc_sitemaps","interval_seconds":604800},
  {"lane":"bing_crawl","interval_seconds":604800}
]}
```

Both are pure reads — `gsc_sitemaps` uses the read-only GSC scope already granted;
`bing_crawl` uses the same read-only BWT API key already granted for `bing`/`backlinks`.
Neither submits, writes, or mutates anything.

## Deliberately not implemented in this pass (see final report for rationale)

- GSC URL Inspection API bulk collection: `scripts/gsc_inspect.py` already exists
  (single/batch URL inspection) but is a manual/on-demand tool (2000/day, 600/min quota
  per site) — wiring it into unattended scheduled collection for "important URLs" needs
  an operator-curated URL list per site, which does not exist yet in `site.yaml`.
- GSC `searchAppearance` dimension: supported by `gsc_query_v2.py --dimensions` already
  (any dimension combination Google accepts can be passed), so this is a config change,
  not a missing collector — add `searchAppearance` to a `gsc` schedule job's
  `--dimensions` when a distinct rich-result-driven lane is wanted.
- CrUX History, PageSpeed Insights: already collected by `crux_history.py` /
  `pagespeed_check.py` respectively; not orchestrated through `collector.py` lanes today,
  left untouched to avoid scope creep on read cadence/quota this pass did not budget for.
- hreflang / JSON-LD structured-data audit: `site_audit.py` covers canonical/meta/H1/
  sitemap issues only; adding hreflang and structured-data checks is additional own-crawl
  parsing, not an API integration, and was out of scope for the API-surface gap analysis
  this pass prioritized.
