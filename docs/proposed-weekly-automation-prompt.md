# Proposed update to the weekly SEO portfolio automation prompt

**Status: proposal only.** This file is not wired into
`~/.codex/automations/weekly-seo-portfolio-monitoring/automation.toml`; an
operator must review and copy the relevant section in manually.

## Why

The current weekly automation picks at most one fix per week with no
systematic prioritization. The decision layer (`docs/DECISIONS.md`) now
produces a ranked, machine-readable action queue with risk classes and
site-policy gating already applied. The automation should consume that queue
instead of picking ad hoc.

## Proposed prompt text (replaces the "pick one fix" step)

> 1. Run the opportunity engine to refresh the ranked action queue:
>    `python /path/to/standalone-seo/scripts/opportunity_engine.py portfolio
>    <portfolio.json> --reports-dir <reports_dir> --out
>    <reports_dir>/opportunities-<date>.json`
> 2. From `portfolio_queue`, select the **highest-scoring item whose
>    `risk_class` is `auto_safe`**. Skip any item whose `risk_class` is
>    `needs_review` or `forbidden` — those require a human decision or are
>    disallowed by that site's policy; do not act on them automatically.
> 3. If no `auto_safe` item exists this week, do not force a change — record
>    that the queue had none and stop.
> 4. Apply the single selected fix through the existing site-policy-checked
>    write path (unchanged).
> 5. Immediately register the change for measurement:
>    `python /path/to/standalone-seo/scripts/change_measurement.py register
>    <site_root> --id <task_id> --url <affected_url> [--commit <sha>]
>    --deploy-time <now, ISO-8601> --detector <item.detector>
>    --action-type <item.proposed_action.type>`
> 6. On a subsequent run, before picking a new fix, sweep pending
>    registrations: `python /path/to/standalone-seo/scripts/change_measurement.py
>    list <site_root>` and call `measure` on any change whose window has
>    likely elapsed. This closes the loop: outcomes feed
>    `.seo/interventions/scoring-feedback.json`, which the opportunity engine
>    already applies to future scores for that detector.

## Notes for the operator reviewing this

- This only changes *selection logic* (rank + gate by risk class) and adds a
  measurement-registration step; it does not change how a fix is actually
  applied or what site policies allow.
- `read_only`/monitoring-only sites (Toxic Sundae) and `technical_only`
  sites (Stunning Strangers) will never surface a `needs_review` item as
  `auto_safe`; the gating happens inside the opportunity engine, not in the
  automation prompt, so this text does not need per-site special-casing.
