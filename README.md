# SEO

Standalone SEO/AEO/GEO operating system extracted from Legion.

This repository is the canonical implementation for search visibility: technical SEO, query ownership, content/SXO, AEO, GEO/AI visibility, rank tracking, Search Console/GA4/Bing integrations, intervention state, and recurring operations.

## Origin

Extracted from `Orthic-Labs/legion` SEO skill at Legion commit `a4eaaa223c284ab81641c4283903648a2a8c1f14`.

## Integration model

- Standalone CLI/scripts are the source of truth.
- ChatGPT/Codex/other agents should call the same implementation through plugin/tool adapters rather than duplicate SEO logic.
- Legion should eventually retain only a thin adapter/client and cross-capability orchestration.
- Secrets do not live in repository project state.

## Current layout

- `SKILL.md` — domain operating contract
- `scripts/` — deterministic implementation and provider adapters
- `references/` — SEO/AEO/GEO doctrine and provider guidance
- `config/` — provider registry, contracts, control catalogue, qualification
- `tests/` — deterministic/adversarial qualification
- `evals/` — model-facing evaluations
- `schema/` — structured output templates
- `hooks/` — release/pre-commit checks
- `agents/` — generated agent metadata

## Project state

Per-site non-secret durable state remains under `.legion/seo/` for compatibility during extraction. A future migration may rename that path only with explicit backwards compatibility.

## Status

This extraction preserves the implementation; live provider credentials, runtime scheduling and real-property qualification remain environment-specific evidence and are not implied by repository presence alone.
