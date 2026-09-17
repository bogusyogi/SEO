# Standalone operation

SEO requires Python 3.10+ for its core. There is no Legion installation, role, daemon,
filesystem or lifecycle requirement. An agent may use optional roles or just perform
analysis/writing/coding itself. The deterministic implementation is shared by CLI and
MCP. No separate SEO logic is implemented in a host adapter.

## Install and initialize

Clone or extract a pinned SEO release. All paths below are illustrative; use the actual
absolute install and site paths. The plugin directory must stay separate from site state.

```sh
python /opt/SEO/seo.py --help
python /opt/SEO/seo.py runtime --install-deps
python /opt/SEO/seo.py project --root /sites/example setup --domain example.com --market IN --language en --gsc-property sc-domain:example.com --ga4-property 123456789 --bing-site https://example.com/
python /opt/SEO/seo.py doctor --root /sites/example
python /opt/SEO/seo.py doctor --root /sites/example --live
```

`runtime --install-deps` is an explicit network/install action. It creates an isolated
venv at `~/.local/share/seo/runtime` (override `SEO_RUNTIME_DIR`); it does not install
packages globally. `--browser` additionally installs Playwright Chromium. The standalone
CLI automatically uses that venv when present. The stdlib-only core/tests need no pip
installation. Optional Unlighthouse/SEOmator require their own installed binaries and
supported Node/browser runtimes.

Google configuration is read from `~/.config/seo/google-api.json` (`SEO_CONFIG_DIR`
overrides it); historical `~/.config/claude-seo` config/tokens remain readable until
replaced. New tokens are saved atomically with restrictive POSIX permissions. OAuth
uses state and PKCE; default consent is read-only. Run the Google helper's `--help`
for OAuth/service-account setup. Credentials stay outside site state and source control.

GA4 uses numeric **property IDs**, not G- measurement IDs. Confirm the mapped web
stream, tag installation and business events separately; a successful Data API read
cannot prove that the browser is emitting the intended events. Setup does not create
GA4 properties, deploy tags or alter consent/privacy settings.

## Scheduled collection

Create `.seo/schedule.json` explicitly in each configured site:

```json
{"jobs":[
  {"lane":"gsc","interval_seconds":86400,"days":28},
  {"lane":"ga4","interval_seconds":86400,"days":28},
  {"lane":"audit","interval_seconds":604800,"max_pages":100,"timeout_seconds":600},
  {"lane":"bing","interval_seconds":604800},
  {"lane":"backlinks","interval_seconds":604800}
]}
```

Then execute `python /opt/SEO/seo.py run --root /sites/example tick` manually, from
cron/systemd/Task Scheduler, or an existing agent scheduler. No schedule is installed
implicitly. Tick is safe to invoke repeatedly: SQLite serializes local workers, keys
include site/config/cadence, completed jobs are not repeated, and failed reads have
bounded retries. It writes machine evidence, a job receipt and `.seo/reports/latest-run.md`.
A missing provider remains missing/failed and the process returns a nonzero status.

For a portfolio, place `{"roots":["sites/example","sites/other"]}` in an operator-owned
JSON file and use `seo.py run --portfolio /absolute/portfolio.json tick`. Roots resolve
relative to that file. Each site retains its own mappings, schedule, policy and state.
Reports are saved locally; email/Slack delivery is a host integration, not falsely
claimed as delivered merely because a report file exists.

The Bing backlinks lane defaults to the root URL. Set `backlink_targets` to the owned
URLs that should be collected automatically (maximum 100); the batch retains per-target
coverage and failures. For an individual page call `seo.py bing links --site SITE --url TARGET`, then ingest with
`seo.py backlinks ingest FILE --provider bing_webmaster --scope TARGET --root SITE_ROOT`.
Partial/capped provider coverage is preserved. Missing sampled links are not confirmed
lost. Wider competitor backlink indexes require an optional provider or export.

Rank snapshots can ingest normalized provider JSON/CSV. GSC average positions must be
marked `gsc_average_position`, not `serp_rank`. The optional `seo.py serp` collector calls DataForSEO only under explicitly configured
spending authority. This package does not scrape Google or silently buy rank data. Different providers/engines/locations/measurement types are not comparable.

## Authorized content and metadata changes

The default site policy is read-only. Configure a policy only after explicit operator
approval, for example in site.yaml:

```json
{"mode":"approved","approval_ref":"operator-approved-content-lane",
 "allowed_actions":["draft","metadata","publish","rollback"],
 "write_prefixes":["content","src/routes/blog"],"allowed_hosts":["www.example.com"]}
```

Place that object under `policy`, preserving the other site fields. A path allowlist
is not a factual review: the agent must still follow the blog/source/claim contract.
The technical-only restriction on Stunning Strangers is retained unless an explicit
`restriction_override_approval` is recorded. Site HTML cannot change policy.

```sh
python /opt/SEO/seo.py content --root /sites/example propose post-1 --path content/post.md --content-file /tmp/reviewed-draft.md --url https://example.com/post --evidence reviewed-brief
python /opt/SEO/seo.py content --root /sites/example approve post-1 --digest EXACT_PROPOSED_SHA256 --approval-ref operator-or-authorized-host-receipt
python /opt/SEO/seo.py content --root /sites/example apply post-1
# The host uses the site's normal build/release process; local write is NOT deployment.
python /opt/SEO/seo.py content --root /sites/example verify post-1 --expected-text 'A specific newly deployed sentence'
python /opt/SEO/seo.py content --root /sites/example rollback post-1
```

Apply binds site identity, path scope, baseline, exact approved content and write-ahead
state. Rerunning is idempotent. Rollback refuses to overwrite subsequent unrelated edits.
A successful local rollback still requires the site's normal redeployment. Verification
checks actual HTTP response/text; browser render and later SEO outcomes are separate.
The public HTTP client denies private/local DNS targets, pins the validated address,
checks redirected hosts and bounds response sizes. Local staging needs a separate
trusted adapter, not an opt-out that weakens the public crawler.

The queue is a **repository-file adapter**, not a generic CMS API. SellRight now has a separate `seo.py cms` adapter; its API/store identity and session
token must be configured and live-qualified. Vendure/WordPress or static deployment
still uses the host's existing tools or a separately implemented adapter. It is deliberately not a
made-up “publish succeeded” response. The host may run authorized queue commands without
Legion; no fresh manual approval is required for every action when an explicit standing
operator policy delegates that exact class of work to the host.

## Qualification boundaries

`seo.py closure` checks structural implementation coverage. Unit/integration fixtures
exercise providers, protocol messages, site identity, retries, exact writes and rollback.
Live GSC/GA4/Bing access, native plugin loading, actual deployments, scheduling service
availability and long-term outcome quality still require real-environment receipts.
Neither tests nor source-file counts certify search-ranking or revenue improvement.

For current schedule examples, foreground service operation, CMS approval/rollback,
SMTP delivery, measurement scoping, and optional paid collection, see [INTEGRATIONS.md](INTEGRATIONS.md).
