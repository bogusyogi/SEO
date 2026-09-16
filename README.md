# SEO

Independent, first-party-first SEO operations for websites. Run it from the CLI,
through a local MCP host, or as a Codex/Claude Code plugin. **Legion is not a
runtime, build, installation, scheduling, or permission dependency.** A harness
may optionally use any installed writing, coding or design roles.

The reusable domain references cover technical SEO, page/query ownership,
content, AEO/GEO, links, local/international/ecommerce SEO and measurement. The
runtime provides site-bound collection, durable jobs, recurring schedules,
policy checks, evidence history, draft handoffs and reversible local changes.

## Install

Python 3.11+ is required. Clone this repository or extract its complete archive.
No `pip install` is required for the core queue, policy, local HTTP crawl,
backlink/rank history, reports or reversible file operations.

```sh
git clone https://github.com/bogusyogi/SEO.git
python /absolute/path/SEO/seo.py --help
```

Install optional Google and MCP dependencies in an isolated environment:

```sh
python /absolute/path/SEO/scripts/setup_runtime.py --google --mcp
```

The setup command prints the exact interpreter to use (including Windows paths).
It does not install Legion, configure a model, change host settings or start a
scheduler. Add `--reports` for legacy PDF/Excel rendering; `--browser` for optional
Playwright-based checks. The standalone CLI remains usable without MCP.

## Configure one site

Use an explicit site project directory, not the plugin installation directory:

```sh
python /path/SEO/seo.py --root /path/site init --domain example.com --market IN --language en --gsc-property sc-domain:example.com --ga4-property 123456789 --bing-site https://example.com/
python /path/SEO/seo.py --root /path/site doctor
python /path/SEO/seo.py --root /path/site doctor --live
```

Use the isolated interpreter printed by setup for Google/MCP commands. Property
IDs are examples, not real mappings. Google OAuth/service-account credentials
belong in `~/.config/seo` or `SEO_CONFIG_DIR`; Bing uses `BING_API_KEY`. Existing
`~/.config/claude-seo` credentials remain readable as a compatibility fallback.
A configured credential is not verified access: the live doctor performs bounded
reads against the selected site. Google OAuth requests read-only scopes by default.

Durable project state is `.seo/`. To preserve existing installations, run
`migrate-state` once to copy `.legion/seo` into `.seo`; it verifies file bytes,
refuses conflicting destinations and leaves the original untouched. Do not run
`init` over unmigrated legacy state. The old directory name is data compatibility,
not a dependency on Legion.

## Collect and report

```sh
python /path/SEO/seo.py --root /path/site collect crawl
python /path/SEO/seo.py --root /path/site collect gsc
python /path/SEO/seo.py --root /path/site collect ga4
python /path/SEO/seo.py --root /path/site collect gsc_ranks
python /path/SEO/seo.py --root /path/site report
```

GSC average positions are labelled as such, never substituted for discrete SERP
ranks. Optional rank-provider exports can be imported with `scripts/rank_tracker.py`.
Bing backlinks are per explicit target URL with pagination, not a complete
web-wide link index. `collect bing_links --options options.json` accepts
`{"target":"https://example.com/page/","max_pages":10}`. New/lost candidates
preserve provider scope, and an incomplete collection never certifies a lost link.

Read commands execute only their own job. They do not drain queued mutations.
Errors remain errors in JSON output, process exit codes and operator reports.

## Recurring operation

```sh
python /path/SEO/seo.py --root /path/site schedule daily-gsc --provider gsc --every-hours 24
python /path/SEO/seo.py --root /path/site schedule weekly-brief --report --every-hours 168
python /path/SEO/seo.py --root /path/site tick
```

Use your OS scheduler to invoke `tick`, or run `serve` as a supervised process.
Installing the plugin **does not activate a daemon**. `portfolio --projects
projects.json` processes an explicit JSON array of project paths with isolated
state and mappings. It does not guess sites or reuse global analytics defaults.

## Changes, drafts and publishing

Queue a proposal with `enqueue KIND --input payload.json`. Inspect its exact
payload with `inspect JOB_ID`. Read operations and draft preparation are enabled
by default; publishing, delivery and repository writes are not.

A site's trusted policy specifies `allowed_actions`, standing `auto_actions`,
path allowlists and budgets. Otherwise `approve JOB_ID` binds approval to the
exact payload and config digest. `tick` executes due authorized jobs. Protect
policy and approval access at the host; a CLI cannot sandbox arbitrary trusted
executables installed by the operator.

Local patches require an expected file digest, allowlisted path and bounded
replacement. A verified backup/change journal supports conflict-safe rollback.
Local writes are explicitly not live deployments. Drafts require sources and
remain reviewable; optional writer/publisher/delivery adapters use a fixed argv
and a JSON stdin/stdout contract. Publishing verifies the approved draft digest,
requires a rollback plan and checks the public page independently after receiving
a deployment receipt. A production publisher still requires site-specific
installation and qualification, including remote rollback/reconciliation.

Interrupted or ambiguous writes become `uncertain`, not silently replayed. Read
retries are bounded; adapter budgets are reserved per attempt. Successful deploys
are not SEO outcomes. `search_ops.py` records verified, mature outcome reviews
separately from deployment, with evidence and confounders.

See [standalone operations](references/standalone-operations.md) for contracts and
[site policy example](examples/site-policy.json) for non-secret configuration.
The historical Stunning Strangers technical-only restriction remains a site policy,
not a reason to impose that restriction on other sites.

## Plugins and MCP

Claude Code can load a local clone with `claude --plugin-dir /absolute/path/SEO`.
The repository also contains an `orthic-seo` marketplace definition; install from
a reviewed release/ref rather than relying on an arbitrary moving branch.
Codex packaging is `.codex-plugin/plugin.json` plus `skills/seo/` and a bundled
MCP configuration. Both use the same `seo.py`/Python runtime and evidence state.

The MCP server is **local stdio only**, fixed to `SEO_PROJECT_ROOT` at launch
(or the host's launch directory). Set `SEO_PYTHON` to the optional environment's
interpreter, or use the default setup location. It offers status, doctor,
collection, reports, proposals, exact-job execution and inspection. It exposes
no tool to alter site root, policy, credentials or grant itself approval.

A repository manifest is not a public ChatGPT directory listing. Hosted ChatGPT
use needs an authenticated remote deployment/registration, not a pretend local
`.chatgpt-plugin` file. None is provisioned by this repository. Native host
installation and real-property access must be evidenced on the target host.

## Optional audit donors

SEOMator and Unlighthouse can run as explicitly installed external adapters or
supply exports to `scripts/external_audit.py`. Unmeasured rules remain unmeasured;
Lighthouse lab results are not field CrUX or rank evidence. External browsers/tools
need the host's sandbox and version pinning. No donor tool is installed at runtime.
[Donor review](docs/DONOR-REVIEW.md) distinguishes absorbed concepts, inherited
source, optional executable integrations, and discovery-only lists.

## Qualification

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/seo_closure.py --json
python scripts/qualify_package.py
```

CI exercises the core without SDKs and the Google/MCP integration tests with real
SDKs plus deterministic provider replays. Provider replay is not live credential
qualification. See [repair ledger](docs/REPAIR-LEDGER.md) for scope and remaining
operator setup. Do not describe the package as unattended production-qualified
before a real site completes collection, a controlled change, deployed verification,
rollback rehearsal and later measurement.

## License and provenance

Original extraction: `Orthic-Labs/legion@a4eaaa223c284ab81641c4283903648a2a8c1f14`.
This is provenance only. The root [LICENSE](LICENSE) is the original Orthic Labs
source-use license, not a blanket MIT license. Third-party components retain their
own notices; see [THIRD_PARTY_NOTICES](docs/THIRD_PARTY_NOTICES.md).
