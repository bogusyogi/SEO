# SEO migration coverage

This record compares the last workspace tree (`78e96c6368f9677c927963e338b1d909808a3b39`,
`tools/skills/seo/**`) with Legion extraction (`a4eaaa223c284ab81641c4283903648a2a8c1f14`,
`skills/seo/**`) and standalone PR revision (`f53573eefd6f1f36d08f498dd8bc4addd6ec6346`,
repository root). The comparison is path-mapped, excludes generated `__pycache__` files,
and is static evidence; it does not certify live providers or site outcomes.

The workspace tree contained 94 tracked SEO files at its historical revision. All 94
paths exist in Legion and in standalone. Of those paths, 46 retain identical SHA-256
content across all three revisions. Forty-eight are edited in Legion, standalone, or
both; no baseline path is missing. Legion adds 52 SEO paths, chiefly governed config,
AI/ecommerce/search-experience/workflow references, provider and closure scripts,
fixtures, and tests. Standalone adds its root CLI, state, portfolio/workflow, queue,
publication/media, measurement, reporting, host/MCP, docs, and qualification layers.

The edited set is concentrated in `SKILL.md`, hooks, evals, banana/image references,
Google/measurement and audit references, plus scripts hardened for evidence coverage,
provider state, page/query contracts, and standalone path/runtime behavior. The
standalone revision adds operational code rather than deleting a historical executable
path. The standalone root skill deliberately removes Legion-only routing metadata and
delegation budgets; its independent authority/effect rules live in `SKILL.md`,
`AGENTS.md`, `config/contracts.json`, `scripts/contracts.py`, and the queue/publication
receipts.

## Historical 17-line migration obligations

These rows come from the historical workspace migration notes (lines 140–162). A disposition is
listed with concrete current evidence. “Unresolved” means the exact historical
instruction is not proven by this bounded static check.

| Historical obligation | Current evidence and status |
|---|---|
| Banana image edit operation | `references/image-gen.md` and `extensions/banana/scripts/edit.py`; superseded by optional host/image lane. Preserved as an executable fallback, ownership changed. |
| Manual-action recovery fixes root cause | `pdf/google-seo-reference.md:112-129` retains unnatural-link/cloaking causes and reconsideration steps. Preserved. |
| Ahrefs export preserves requested filters | `references/ahrefs.md:48-68` records source, filters, date, target, row count and limitations. Preserved. |
| Blog deploy is site-specific | `references/blog-post-contract.md:53-60` requires the verified site flow and separates deploy from SEO. Preserved with corrected ownership. |
| HTTPS remediation | `references/eeat-framework.md:112` plus `references/sitemap.md:35` retain HTTPS checks. Preserved. |
| Truthful Person/ProfilePage schema | `references/geo.md:64`, `references/schema-markup.md:17-30,73`, and `references/migration-preserved-guidance.md` retain visible-evidence, truthful identity, and `sameAs` rules. Preserved as guidance; no template engine claimed. |
| Visible FAQ without mandatory commercial schema | `references/geo.md:35,58` and `references/ai-search-2026.md:106` explicitly reject synthetic FAQ/schema. Preserved and current. |
| Verified `sameAs` identity links | `references/schema-markup.md:73` and `references/maps-gbp-checklist.md:65` retain `sameAs`; authoritative-profile gating is stated in `references/geo.md:64`. Preserved. |
| Duplicate image edit operation | Same `references/image-gen.md` plus extension edit script; superseded duplicate ownership. Preserved as one optional lane. |
| Domain-specific visual weights | `references/migration-preserved-guidance.md` retains the intent as typed vertical criteria and explicitly rejects unexplained numeric multipliers. Preserved as guidance; no fabricated score model. |
| Local NAP discrepancy reconciliation | `references/local.md:4,137-145` plus `references/migration-preserved-guidance.md` require source-of-truth, field-level discrepancy, date/confidence, correction, and post-publish recheck. Preserved as guidance; no receipt engine claimed. |
| Hub-and-spoke location linking | `references/local.md:145` retains the three-click hub-and-spoke rule. Preserved. |
| Industry-specific score multipliers | No score-multiplier implementation found; `references/workflow-packs.md:56-57` routes vertical extensions through generic semantics. Not implemented as numeric multipliers; original vertical-assessment intent is preserved in `references/migration-preserved-guidance.md`. |
| Static fallback with detected signals/missing providers/confidence | `references/geo.md:110` requires confidence and limitations; `config/contracts.json` requires confidence/coverage state; provider fallbacks exist. Preserved. |
| Schema validation errors corrected | `hooks/validate-schema.py`, `references/schema-markup.md:30-45`, and `scripts/coverage.py` provide validation. Preserved. |
| Sitemap quality gates | `references/sitemap.md:18-35` lists canonical, noindex, redirect, HTTPS and robots checks. Preserved. |
| Ranked near-miss, zero-click, true-gap rows | `references/google.md:149-151` retains classifications; `references/migration-preserved-guidance.md` adds query/page-or-none/scope/evidence/condition/action/priority/confidence row requirements. Preserved as guidance; no automatic causal claim or mutation. |

No standalone source imports Legion. `config/source-manifest.json` is provenance only;
runtime checks reject Legion-named package contents and `.legion` state is a readable
migration source, not a dependency. External donor material remains documented in
`docs/DONOR-REVIEW.md` and `docs/THIRD_PARTY_NOTICES.md`; this record makes no new donor
claims.
