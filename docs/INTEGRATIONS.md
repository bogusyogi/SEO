# Operational integrations — 0.3.0

The core, CLI, plugin and scheduler require no Legion installation or companion repository.
All new integrations are disabled until configured. These examples are templates, not
an assertion that a real site, property, token or paid account has been connected.
Secrets are environment references; do not put their values in site.yaml, reports or Git.

## First-party collection and movement

Per-site mappings remain under `.seo/site.yaml`. The configured domain and explicit
`policy.allowed_hosts` constrain GSC page filters and every GA4 report. A broader domain
property is not permission to mix unrelated subdomains into one site's measurements.
GA4 identity and hostname filters do not prove that browser tagging/key events work.

A useful free collection schedule in `.seo/schedule.json` is:

```json
{"jobs":[
  {"lane":"gsc","interval_seconds":86400,"days":28},
  {"lane":"gsc_ranks","interval_seconds":86400,"days":28},
  {"lane":"ga4","interval_seconds":86400,"days":28},
  {"lane":"audit","interval_seconds":604800,"max_pages":100,"timeout_seconds":600},
  {"lane":"bing","interval_seconds":604800},
  {"lane":"backlinks","interval_seconds":604800,"timeout_seconds":600}
]}
```

Add `backlink_targets` to site.yaml for the homepage and important owned pages; at most
100 targets and 1..100 `backlink_max_pages` per target are supported. All targets are
validated before collection. A single batch deadline bounds the work. Per-target errors
and capped coverage survive into evidence/history; this is not a complete web census.
Normalized backlinks live in `.seo/backlinks/snapshots`, separate from raw responses.
Existing flat history remains readable. A missing sampled link is not a confirmed loss.

GSC rank observations retain country/device and are labelled `gsc_average_position`.
They do not invent query language or a precise SERP rank. Rank reports compare the latest
two snapshots within each provider/market/device/measurement stream, so interleaved
GSC and controlled SERP runs cannot produce fabricated movement. Metrics with changed
property, hosts, dimensions, currency, timezone or window length are not comparable.

```sh
python /opt/SEO/seo.py run --root /sites/example tick
python /opt/SEO/seo.py run --portfolio /sites/portfolio.json serve --poll-seconds 300
```

`serve` is a foreground process, not a detached job. Run it under your existing service
manager, or invoke `tick` using cron/Task Scheduler. No production service is installed
or activated by the package. `--max-ticks 1` permits a bounded service smoke test. The
runner does not autonomously invent article facts, approved changes, credentials or policy.

## SellRight blog workflow

The concrete client targets SellRight's blog API, not a guessed Vendure endpoint. Configure
an explicit origin, store slug, store ID and existing bearer-session token environment name:

```json
{"cms":{"provider":"sellright","api_origin":"https://api.example.com",
 "store_slug":"example","store_id":"actual-store-id","token_env":"SEO_CMS_TOKEN"}}
```

Merge that object into the site's existing configuration. The client verifies the exact
store ID/slug in `/v1/admin/me`, sends `x-store-slug` on every request and verifies the
post/store identity on readback. It never falls back to the session's first store.
It does not log in, obtain or renew tokens, disable CSRF or request broader permissions.

An approved site policy needs `draft`, `publish` and, for rollback, `rollback` among its
allowed actions. New posts must first be drafts with explicit slug, real author, title,
body and reviewed-source evidence. A creation request cannot conceal immediate publication.

```sh
python /opt/SEO/seo.py cms --root /sites/example list
python /opt/SEO/seo.py cms --root /sites/example prepare guide-1 --body /tmp/reviewed-post.json --evidence reviewed-source-brief
python /opt/SEO/seo.py cms --root /sites/example approve guide-1 --digest EXACT_REQUEST_SHA256 --approval-ref operator-or-delegated-host
python /opt/SEO/seo.py cms --root /sites/example apply guide-1
```

Preparation is read-only against the CMS and freezes the desired body and existing-post
baseline. Approval binds action ID, payload, target, site and current configuration.
Changing them requires a fresh proposal. Repeating a successful apply returns its receipt,
not another post. A timeout/process death after the write-ahead marker is `uncertain`,
never automatically retried. The CMS currently changes colliding slugs; an unexpected
slug is also uncertain and is not "cleaned up" through automatic deletion.

### Existing posts, publication and rollback

PATCH is a real API mutation, but this API currently has no atomic conditional-write
contract. Existing-post changes therefore default to blocked. An operator who accepts
the remaining concurrent-edit race can explicitly set `cms.allow_non_atomic_updates`
to `true` **before preparation**. A preflight baseline hash catches changes already
visible at that point; it cannot prevent another editor racing the subsequent PATCH.
Fully unattended concurrent publishing requires a server-side conditional-write contract
or an externally enforced exclusive writer. Do not describe this client as atomic.

With that limitation deliberately accepted, create an update proposal using `--post-id`
and a JSON body such as `{"isPublished":true}`. Approve and apply its exact digest. A
successful receipt means matching CMS readback, not a verified public page or SEO uplift.

```sh
python /opt/SEO/seo.py cms --root /sites/example verify publish-1 --url https://example.com/blog/useful-guide --expected-text 'An exact sentence in the approved content'
python /opt/SEO/seo.py cms --root /sites/example reconcile guide-1 --post-id IDENTIFIED_POST_ID
python /opt/SEO/seo.py cms --root /sites/example rollback update-1 restore-1 --evidence approved-rollback
```

`reconcile` reads and records whether an identified post matches; it does not invent
causation or authorize a retry. Rollback creates a new approval-required proposal and
refuses to overwrite subsequent changes. Newly created drafts are retained/unpublished,
never deleted. Public verification is a bounded HTTP assertion; rendered DOM, indexing
and later business outcomes are separate. Media upload/featured-image handling is not
implemented by this blog adapter; use the site's qualified media workflow.

## SMTP report delivery

SMTP is optional, explicit and TLS-only. Put only configuration and secret references
in the site config; keep credentials in the operator's environment:

```json
{"delivery":{"provider":"smtp","host":"smtp.example.com","port":587,
 "security":"starttls","from":"reports@example.com","to":["owner@example.com"],
 "username_env":"SEO_SMTP_USER","password_env":"SEO_SMTP_PASSWORD",
 "auto_send_reports":false}}
```

A delivery needs an approved `deliver` policy. Only this site's report files are accepted,
up to 1 MiB. The prepared body, recipients and configuration are frozen in the action.

```sh
python /opt/SEO/seo.py deliver --root /sites/example prepare weekly-1 --report /sites/example/.seo/reports/latest-run.md --evidence operator-reviewed-report
python /opt/SEO/seo.py deliver --root /sites/example approve weekly-1 --digest EXACT_REQUEST_SHA256 --approval-ref operator
python /opt/SEO/seo.py deliver --root /sites/example send weekly-1
```

`auto_send_reports:true` plus an explicit standing `deliver` policy authorizes the runner
to prepare/approve the exact generated report without asking a fresh question every time.
Changing the report/config produces a new identity; unchanged content is not resent.
Recipient refusal yields partial status. A timeout after possible transmission remains
uncertain and is not resent automatically. The receipt means SMTP server acceptance,
not arrival in the inbox. Recipients receive the report's existing evidence; email does
not make missing measurements complete.

## Optional controlled SERPs

Direct GSC/GA4/Bing operation remains free of third-party subscriptions. Controlled Google
SERP observations can use DataForSEO only with explicit paid authority:

```json
{"serp":{"provider":"dataforseo","keywords":["example query"],
 "location_code":2840,"language_code":"en","device":"desktop","os":"windows",
 "depth":10,"reserve_per_request_usd":"0.02"}}
```

The reservation value above is an illustrative operator budget, **not a price quote**.
Confirm current provider pricing before enabling. Policy must include `approval_ref`,
`allowed_paid_providers:["dataforseo"]` and a positive `monthly_serp_budget_usd`.
Set `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD` outside state. Technical-only sites are blocked.

```sh
python /opt/SEO/seo.py serp --root /sites/example --run-id 2026-09-17
```

One keyword/task is submitted per Live Advanced call. Request identity includes site,
host scope, run ID, location, language, device, OS and depth. Reservations are durable
before network I/O. A completed request is cached; ambiguous charged requests are not
silently repeated. An actual charge above the reservation pauses further paid calls
until the operator reconciles billing/state. Local reservations are not vendor-enforced
caps. No automated billing-resolution command is supplied.

Organic position comes from `rank_group`, not `rank_absolute`. A checked absence means
not found in the returned sample, not globally unranked. Device/OS/depth and query/location/
language are checked against provider echoes. A scheduled `serp` lane defaults to a UTC
calendar-day run ID, so repeated ticks on that day reuse receipts. MCP collection tools
cannot invoke this paid lane. Unknown/unsupported backlink providers remain optional imports.

Official contracts: Google Analytics FilterExpression and DataForSEO Live Advanced SERP
API documentation were consulted on 2026-09-17. Provider account smoke tests and real billing
were not performed by writing these adapters.

## Portfolio host and GitHub-backed site route

The [portfolio workflow](PORTFOLIO-WORKFLOW.md) connects existing mechanisms without a
Legion dependency. `github_publication.py` uses GitHub Git/PR/Deployment APIs for an
exact-approved page plus immutable media assets. Branch/PR publication, separately
approved merge, exact-commit deployment and public HTML/image verification are separate
receipts. Recovery creates a scoped reverse PR rather than resetting unrelated work.

This route requires an actual repository identity, base branch, named checks and an
existing deployment pipeline emitting GitHub Deployment records. Its presence does
not establish that any particular domain uses that route. `agent_host.py` is a bounded
JSON handoff to an existing operator-approved executable, not a model installation or
an OS sandbox. Semantic source and preview review remain host responsibilities.

On September 20, 2026 the SellRight server route was inspected at
`bogusyogi/rightsites` commit `818f054044229ea96fe47eca85d8576261a982e7`,
`packages/api/src/routes/admin-content.ts` (blob `55948e8354057201d2edca15afc96f799b553b19`).
It still selects then unconditionally patches posts and does not expose an atomic
version precondition or server-idempotent creation contract. That server was not
modified by this SEO milestone. CMS machine-credential lifecycle and asset upload
also remain separate integration work. Do not enable non-atomic writes and label
these gaps resolved.

Primary API contracts: GitHub REST [Git trees](https://docs.github.com/en/rest/git/trees),
[pull-request merge](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request),
[deployments](https://docs.github.com/en/rest/deployments/deployments), and Google's
[Search Analytics query](https://developers.google.com/webmaster-tools/v1/searchanalytics/query).
No production API or provider write was used to qualify these code paths.
