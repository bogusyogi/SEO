# Decision layer: opportunity ranking + post-change measurement

This is the layer agents use to *choose* what to do next and to *know whether
it worked*. It reads evidence other tools already collected; it never talks
to a live provider to make a ranking decision, and it never writes to a site.

## Modules

- `scripts/signal_adapter.py` — tolerant read-only loader over a site's
  `.seo/<lane>/*.json` envelopes and the operator's portfolio `reports/`
  snapshots (PSI scores, technical-audit rollups). Missing lanes, unknown
  schema fields, or malformed JSON degrade to "no evidence" instead of
  raising, so a parallel effort adding new collectors (`docs/SIGNALS.md`)
  does not break ranking — new lanes (`cwv`, `indexing`, `internal_links`)
  are wired in but simply produce nothing until populated.
- `scripts/opportunity_engine.py` — the ranking engine. Detectors:
  striking-distance queries (position 4-20 with meaningful impressions),
  CTR below a position-banded expectation curve, period-over-period decay
  in clicks, technical-audit findings (titles, meta descriptions,
  canonicals, noindex mistakes, orphan pages, broken links), indexing/
  coverage problems (URL inspection / sitemap errors, once collected),
  CWV/PageSpeed failures, and weak/orphan internal-link pages. Every
  emitted item carries `site`, `url`, `detector`, `evidence` (source +
  date), `proposed_action` (type + notes), `risk_class`, `expected_metric`,
  `measurement_window_days`, and `score`.
- `scripts/change_measurement.py` — records a shipped change (`register`)
  keyed by site/urls/commit/deploy time/detector/action type, then later
  (`measure`) pulls matching before/after GSC windows through the existing
  `gsc_query_v2` collector and `reporting.metric_changes`, and records
  `improved` / `neutral` / `regressed` / `insufficient_data`. Outcomes
  accumulate into `.seo/interventions/scoring-feedback.json` per detector;
  `opportunity_engine.build_site_queue` multiplies future scores for that
  detector by the resulting factor (bounded, ±15% per net win/loss ratio),
  so a detector that keeps producing regressions is naturally deprioritized.

## Risk classes and site policy

`risk_class` is derived from the proposed action type and then gated by
`site_policy.load(root)['policy']['mode']`:

- `auto_safe` — metadata/internal-link technical repair (title/meta/
  canonical/noindex fixes, adding an internal link, fixing a broken link,
  resubmitting a sitemap, requesting indexing).
- `needs_review` — anything touching editorial content or off-site
  acquisition (rewrites, content expansion, backlink building, CWV work).
- `forbidden` — the site's policy disallows this here. `read_only` sites
  (e.g. Toxic Sundae, monitoring-only) forbid everything; `technical_only`
  sites (e.g. Stunning Strangers) forbid everything except `auto_safe`.

This mirrors `site_policy.authorize`'s existing READ_ACTIONS/CONTENT_ACTIONS
split rather than inventing a second source of truth for what a site allows.

## CLI

```
python scripts/opportunity_engine.py site <root> --domain example.com --policy-mode approved [--out FILE]
python scripts/opportunity_engine.py portfolio <portfolio.json> [--reports-dir DIR] [--out FILE]

python scripts/change_measurement.py register <root> --id chg-1 --url https://example.com/a \
    --commit abc123 --deploy-time 2026-09-01T00:00:00Z --detector striking_distance_query \
    --action-type improve_striking_distance_content
python scripts/change_measurement.py measure <root> --id chg-1
python scripts/change_measurement.py list <root>
```

Also exposed through the shared entrypoint: `python seo.py opportunities ...`
and `python seo.py changes ...`.

## Known gaps

- Live URL-inspection and CWV per-page data are not yet universally
  collected (see the parallel collectors effort); those detectors are
  wired and tested against fixtures but currently no-op on real data until
  that lane exists. This is intentional — no fabricated findings.
- `measurement_window_days` and the CTR expectation curve are heuristics,
  not fit to this portfolio's historical conversion data; they are a
  reasonable starting default, not a tuned model.
