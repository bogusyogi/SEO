# Standalone repair ledger — 0.2.0

Baseline: SEO `2608fd64b48ab3762039d1d2f80673f54af89a2f`.
Repository repair branch: `fix/standalone-seo-20260916`.
No live site was modified, credential provisioned, paid service purchased, report
sent to an external recipient or recurring worker activated by this change.

## Repairs implemented

- Restore the historically omitted image helpers, PDF support reference and source
  license, preserving upstream attribution.
- Remove Legion CI path dependency; independent package/CLI, per-site `.seo` state,
  explicit checksum-verified legacy migration and no framework imports.
- Correct Codex skill-folder packaging; add Claude plugin/marketplace metadata,
  optional local MCP transport over the same runtime, no invented ChatGPT manifest.
- Preserve GSC corrected aggregates while restoring legacy renderer totals and the
  Python compatibility function. Explicit page-prefix scope, dates and filters.
- GA4 distinct period users from a separate aggregate request; preserve page-query
  errors and failure exit codes; include key events/revenue/purchases and explicit
  hostname filters. Live GA4 tagging/conversion configuration is still site-specific.
- Correct Bing per-URL GetUrlLinks arguments, pagination, incomplete/error semantics
  and secret-safe errors. No claim of complete backlinks across the whole web.
- Comparable provider/market/device/measurement rank identities, missing observations,
  snapshot overwrite/path safety, and first-party GSC-average-position ingestion.
- Backlink history with new observations, lost candidates and partial-data suppression.
- Schema hook reads real stdin events, supports JSON-LD graphs and type arrays,
  separates valid vocabulary from rich-result eligibility and catches syntax errors.
- Replace contradictory blog instructions with evidence/source/author requirements
  and generic per-site rules. SS technical-only policy remains explicit.
- Independent SQLite job execution, bounded read retries, recurrence materialization,
  per-site claims, write serialization, exact approval/config binding and budget
  reservations per adapter attempt. An uncertain mutation is not auto-retried.
- Reversible local file changes with baseline and after hashes, journal/backups and
  conflict-safe rollback. Publishing has a trusted adapter seam and independent
  public-page verification; local file success is never labelled deployment.
- Site-scoped safe HTTP: reject private/mixed DNS, pin validated address to TLS
  connection, revalidate redirects, cap bytes and web ports. Optional third-party
  browser processes still require host-level sandboxing.
- Read-only default OAuth setup, private atomic token replacement, serialized
  compatibility intervention state, idempotency conflict detection and maturity checks.
- Optional SEOMator/Unlighthouse execution/export normalizers, unknown-format failure,
  lab/field distinctions, and explicit unmeasured control states.

## Evidence and test scope

The original baseline ran 39 tests: 38 passed and the Legion-dependent closure
test failed. The first standalone repair passed all 39. Expanded regressions retain
those tests and add provider replays, CLI installation smoke, approval/crash/rollback,
secret handling, scoped collection and a real MCP SDK handshake/tool call.
Use GitHub Actions at the exact PR head for the final test count and OS matrix.
Do not treat this document's checklist as evidence that a test ran.

Two intermediate failures were caught and repaired rather than waived: a nested
adapter error incorrectly appearing successful, and bare-dict MCP returns lacking
structured content. All temporary source migration scripts/workflows are removed
from the materialized package; they are not runtime dependencies.

## Still requires operator/site qualification

1. Install on the target agent host and verify discoverability, hook trust and the
   actual selected site directory. Native plugin validation is not authenticated
   account qualification. Public ChatGPT directory registration is not done.
2. Supply GSC/GA4/Bing access, verify property mappings, confirm real events/tagging
   and conversions. Provider fixture tests do not create or configure accounts.
3. Configure any optional paid SERP/backlink provider, writer, CMS/repository deploy,
   delivery and rollback/reconciliation adapter. The adapter contract is implemented;
   a concrete production publisher for each site's platform is not auto-generated.
4. Choose and explicitly authorize standing site policies and budgets. Run a controlled
   preview/publication/rollback rehearsal before production unattended changes.
5. Activate an OS-scheduled tick or supervised serve process. Then qualify missed-run,
   provider-failure and alert delivery behavior on that actual host.

An offline package cannot honestly attest to live search outcomes or arbitrary
CMS deployment. The independent runtime supplies executable mechanisms; the site
adapter and credential boundaries fail closed until configured and tested.
