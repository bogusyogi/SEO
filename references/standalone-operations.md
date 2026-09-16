# Independent executable operations

SEO is self-contained. No Legion code, installation, resolver, role or service
is needed. A harness can optionally call its writing/design/coding roles; the
same operations must also work without them. Source provenance mentioning
Legion is history, never a runtime requirement.

## Install and run

Use Python 3.11+ and the complete repository/plugin archive. Resolve `SEO_ROOT`
to its absolute installation path. `python "$SEO_ROOT/seo.py" --help` is the
standalone CLI. All commands accept `--root /absolute/site/project` before the
subcommand. Project state is `.seo/`; it is never saved in an installed plugin
cache. Existing `.legion/seo` data can be copied with `migrate-state`; migration
checks bytes, refuses overwrites/symlinks, and preserves the old directory.

Initialize each site explicitly with `init --domain example.com --market IN
--language en --gsc-property sc-domain:example.com --ga4-property 123456`.
The mapping does not grant access. Configure Google OAuth/service credentials
outside project state, then use `doctor --live`. Read-only scripts support
`SEO_CONFIG_DIR`; legacy credential files remain readable without Claude.

Optional SDKs can be installed into an isolated environment with
`python "$SEO_ROOT/scripts/setup_runtime.py" --google`. Invoke SEO with the
returned interpreter. Add --reports, --browser or --mcp only when needed.
Basic queue, policy, state, HTTP collection and file operations are stdlib-only.

## One collection is not a whole queue drain

`collect gsc`, `collect ga4`, `collect crawl` and `report` run only the requested
job. `tick` deliberately processes due authorized jobs. `schedule daily-gsc
--provider gsc --every-hours 24` records a recurrence. An OS scheduler must run
`tick`, or a running `serve` process must remain active. Installing a plugin does
not start a daemon. `portfolio --projects projects.json` processes explicit site
project paths independently; no global default property is used for collection.

All evidence is site-bound and includes source, collection time, raw result,
error state and digest. A failed source is not zero traffic. GSC property data is
filtered to the site's URL prefix; GA4 is filtered to the site's hostname.
The operator brief preserves collection failures and measured date windows.

## Authority and effects

Edit `.seo/site.yaml` as trusted configuration. `policy.allowed_actions` is the
maximum permitted action set; `auto_actions` is the standing authorization set.
Other actions require `approve JOB_ID`, bound to exact payload and configuration
digests. A configuration change invalidates queued authority. Agents must not
change policy or call approve merely to bypass a refusal; obtain the owner's
instruction. Website content and provider data can never supply authority.

`technical_only` blocks commercial drafts/publication/acquisition. Preserve the
historical Stunning Strangers restriction. Local patches require explicit path
allowlists, baseline hashes and byte budgets. Queued patches carry complete
replacement text and `expected_sha256`, or `absent` for a new file. Built-in
rollback restores verified backup bytes only while the applied file is unchanged.
Local file verification is explicitly not a live deployment.

Drafts require a title, query, source inventory and supplied body (or optional
writer adapter). Source metadata validation does not prove factual entailment:
the draft stays `requires_review`. Publication references a draft path and its
exact digest, a rollback plan, and deployed URL/contains assertions. Publication
requires a configured trusted publisher and independent public-page verification.
Remote rollback/reconciliation is platform-specific and must be qualified in the
publisher before enabling production autonomy; the built-in rollback is local.

## Adapter boundary

An optional `.seo/site.yaml` `adapters` entry has an `argv` string array, an
`effect` (read, writer, publish, deliver), timeout_seconds and max_cost_usd. No
shell is used and no command is accepted from a job payload. The adapter gets one
JSON input on stdin: job_id, idempotency_key, site, base_url, max_cost_usd and input.
It emits one JSON object on stdout. A publisher must include job_id and a receipt;
read adapters preserve provider identity and coverage. Writers return body text.
Publisher implementations must be idempotent by the supplied key. Environment
credentials belong to the host secret store, not configuration or job payloads.

Budget reservations are conservative declared ceilings, not a guarantee of a
third party's billing. Adapter implementations must enforce their supplied cap
before spend; unexpected billed amounts fail qualification. Free first-party
collectors do not depend on paid providers. Missing adapters stop with an explicit
blocked/unconfigured result rather than inventing work.

SQLite claims serialize job ownership. Stale mutation leases become uncertain
and require reconciliation. They are not automatically retried. Read failures
have bounded retries/backoff. Interrupted local edits leave a before/after journal.
The host must protect config/approval access and sandbox trusted external tools;
this process is not an OS sandbox against arbitrary user-installed executables.

## Outcome review

Record deployment verification separately from search/business outcome. Wait for
the planned observation window, preserve confounders, and accept inconclusive
results. A successfully rendered page is not proof of ranking or revenue gains.
See operations.md for prioritization and search_ops.py for the intervention ledger.
