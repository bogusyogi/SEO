# Repair-branch reconciliation — 2026-09-17

## Scope correction — 2026-09-20

The sections below record historical changes, not current publication instructions.
The direct SellRight integration in that repair was an architectural error. SellRight
is a backend provider for RightApps/RightSites, not an SEO publishing interface. Direct
SellRight API writes are prohibited; the client and command have been removed. The
historical server-concurrency/media/token gaps below are superseded, not SEO backlog.
Shared approved-action, SMTP, repository, collection and recovery safeguards remain.
See [current integrations](INTEGRATIONS.md) for the corrected boundary. This correction
does not alter SellRight, the sites' provider usage or any saved historical receipts.

## Historical reconciliation

PR #2 was squash-merged as `402f1879073eebefb32dca792a57862686630210`.
Its tested modular implementation is the sole canonical runtime. PR #1 at
`300ac7378a56602633d2b5890ea36ccd1a8c9a24` is retained in history for comparison;
it must not be merged as a second runtime. This is a semantic reconciliation of the
published repair claims and inspected execution/qualification code, not a claim that
all historical tests from the alternative branch have been ported verbatim.

| PR #1 area | Canonical disposition |
|---|---|
| Independence, recovery assets, licenses, paths, plugin packaging | Already retained by merged #2; no companion dependency added. |
| Google aggregate compatibility, GA4 users/error/business metrics, Bing pagination | Retain #2 fixes and regression coverage. |
| Exact hostname/site binding | Extend canonical collectors, `measurement_scope.py`, `site_policy.py` and project setup; every GA4 request and GSC collection is scoped. |
| Recurrence, SQLite uniqueness, bounded read retry, portfolio isolation | Retain `seo_runner.py`; add foreground service mode rather than importing a second scheduler. |
| GSC rank/backlink persistence and operator decisions | Wire normalized histories into runner/reporting; compare per measurement stream and preserve incomplete link coverage. Existing deterministic prioritization remains in reporting. |
| Exact config/payload authority and uncertain external writes | Strengthen `content_queue.py`; add shared `remote_actions.py` for concrete CMS/SMTP effects. Renames/retargeting/config drift invalidate approval; process death never grants a retry. |
| Local patch and rollback | Retain canonical conflict-safe file workflow, bind baseline/target/config to approval. |
| Generic publish/delivery/writer adapters | Do not copy shell-dispatched placeholder contracts. Concrete SellRight and SMTP adapters now implement reviewed effects. Authoring remains a host task with existing source/claim contracts. |
| Paid budget reservations | Implement only for an explicit optional DataForSEO SERP collector, with durable reservations, ambiguity handling and overrun pause. Free first-party operation remains independent. |
| Outcome maturity | Merged `search_ops.py` already requires verified deployment, earliest evaluation date and evidence for terminal outcomes. No new competing intervention ledger. |
| Minimal archived installation and real SDK qualification | Adapt the useful test method into `qualify_package.py`; add `sdk_contracts.py` to test real GA4 protobuf filters and official MCP clients without live accounts. |
| Optional external scanners and curated lists | Preserve existing optional Unlighthouse/SEOmator adapters and donor review. Do not import lists or perform backlink submissions. |

## Follow-up checks

The original 78 tests are retained. Additional tests exercise hostname scoping, per-page
backlink bounds, normalized history wiring, interleaved rank streams, exact approvals,
CMS draft/update/rollback contracts, SMTP transmission states, paid reservations and MCP
lane enforcement. CI also checks a committed archive in a clean SDK-free virtual environment.
The SDK-only CI jobs install optional libraries for qualification, not for core operation.

## Activation boundaries

No real site repository/configuration, CMS post, GA4 tag, provider account, email recipient
or production scheduler was changed during implementation. This repository has concrete
adapters, not evidence that the operator's environment is already configured.

SellRight currently lacks a server-side atomic conditional PATCH; existing-post mutation
is blocked by default and only becomes available under explicit risk acknowledgement.
Media upload, other CMS platforms, real account access, public-page rendering, service
liveness and long-term SEO outcomes still need their own qualification. These are not
hidden behind the unit-test or structural-closure status.
