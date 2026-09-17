# SEO 0.3.0

Independent SEO/AEO/GEO skill, CLI and local MCP tools for owned-site operations.
**Legion is not required.** Any agent/harness can use SEO directly; additional writing,
coding or design roles are optional conveniences, not runtime dependencies.

## What is implemented

Technical crawling and on-page evidence; GSC Search Analytics/inspection; GA4 organic
traffic, period-level users, key events and revenue; Bing reads and paginated per-URL
backlinks; provider-scoped rank/backlink snapshot comparisons; site policy; scheduled
read jobs with durable retries; evidence-based reports; reviewed repository-file changes
with idempotency, deployed-text verification and conflict-safe rollback. Site-scoped
GSC rank histories, multi-page Bing backlinks, exact-approved SellRight blog operations
and TLS SMTP report delivery use the same independent runtime. Controlled DataForSEO
SERPs are an optional explicit-budget lane, not a requirement.

Optional restored Banana image helpers and HTML/PDF reporting are included. Unlighthouse
and SEOmator can be invoked as separately installed scanners. Paid providers and external
agent frameworks are optional. No credential, live schedule, paid call, public post or
site deployment is enabled by cloning/installing the package.

## Quick start

```sh
python /absolute/path/SEO/seo.py --help
python /absolute/path/SEO/seo.py runtime --install-deps
python /absolute/path/SEO/seo.py project --root /path/to/site setup --domain example.com --market IN --language en
python /absolute/path/SEO/seo.py doctor --root /path/to/site
```

The runtime setup is explicit and isolated. Credentials and property IDs are configured
separately. See [operations](docs/OPERATIONS.md) for Google access, schedules, portfolio
runs, content policy, examples and scope limitations.

## Plugin installation

**Claude Code:** add this repository as a marketplace, then install `seo@bogusyogi-seo`.
For a local checkout, the marketplace source is the absolute SEO directory. Pin a reviewed release or commit when installing; native host installation
is distinct from authenticated access to your properties.

```text
/plugin marketplace add /absolute/path/SEO
/plugin install seo@bogusyogi-seo
```

**Codex/ChatGPT-compatible plugin hosts:** the package manifest is
`.codex-plugin/plugin.json`, with the skill under `skills/seo/` and a local MCP server
in `.mcp.codex.json`. Use the host's supported local/custom plugin installation flow.
This repository is not automatically published to an OpenAI directory by having a
manifest. Native-host installation must be smoke-tested in the actual host.

**Any other harness:** read `SKILL.md` and call the absolute `seo.py` entrypoint. No
plugin is necessary. The same scripts are used by the stdio MCP server.

Set `SEO_PROJECT_ROOTS` in the host environment to explicit absolute site roots,
separated by the OS path separator (`;` on Windows, `:` on Unix). Without this allowlist,
MCP tools cannot access a project. Five read-only tools expose access checks, collection,
reports, rank changes and backlink changes. Publication remains an explicitly authorized
CLI/host action, not an automatically trusted MCP write tool.

Plugin launchers use `python3`; on a Windows host that only exposes `python` or `py -3`,
override the MCP command in that host to the installed interpreter. The core CLI and
tests work with Python 3.10+; no framework-specific runtime is needed.

## State and compatibility

New per-site state is `.seo/`. Historical `.legion/seo/` is read only as a backwards
compatibility location, never as a dependency. `seo.py migrate-state --root SITE` copies
and verifies it while preserving the original. Plugin updates never delete project
state. Google config migrates by new writes into `~/.config/seo` with legacy read fallback.

## Verify

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/seo_closure.py --json
python -m compileall -q scripts hooks extensions seo.py
python scripts/qualify_package.py  # Tests committed HEAD as a clean archive
```

Tests cover deterministic and mocked integration behavior. Live-provider access,
live CMS/deployment qualification, scheduler activation and search outcomes are
separate qualification. This is not a claim that every site is already on autopilot.

Origin: extracted from `Orthic-Labs/legion` at
`a4eaaa223c284ab81641c4283903648a2a8c1f14`. The original source-use license is retained
in [LICENSE](LICENSE); inherited third-party components keep their licenses. See
[notices](docs/THIRD_PARTY_NOTICES.md) and [donor review](docs/DONOR-REVIEW.md).

See [operational integration](docs/INTEGRATIONS.md) for the CMS, SMTP, SERP and history
contracts, and [PR reconciliation](docs/RECONCILIATION-2026-09-17.md) for the disposition
of the two overlapping repair branches. No companion framework is required.
