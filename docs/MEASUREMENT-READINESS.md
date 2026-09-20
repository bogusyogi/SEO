# Measurement-readiness milestone

This extends the existing collector, rank history and evidence brief. It does not
install a service, add an agent framework, alter site policy, publish content, or
qualify an authenticated production host. SEO remains standalone; there is no
new runtime dependency or paid-provider requirement.

## What changed

Scheduled GSC rank snapshots retain a deliberately non-secret measurement context:
site, measured hosts, property, search type, filters, dimensions, aggregation,
data state, timezone, collection route, and inclusive measurement dates. Coverage
and the original observation timestamp remain attached. The comparison code
actually consumes these fields. It does not substitute the site's current config
for the config that produced an old observation.

Different properties, host scopes, query filters, aggregation, data state, or
collection routes cannot become rank gains/losses. Known-context snapshots cannot
be mixed with legacy unqualified imports. Legacy-to-legacy comparisons remain
readable, with an explicit qualification warning; old evidence is not rewritten.

A refresh of the same measured dates is not movement. Reversed, malformed,
missing, and unequal-length periods are not comparable. Advancing equal-length
rolling periods remain descriptive comparisons, with the exact inclusive overlap
in days reported. They are not independent experiments or causal outcome proof.

Empty successful GSC batches and failed/partial batches are persisted. Missing
country/device/query rows become missing observations, never inferred losses.
A failed batch blocks comparison across the failure: recovery needs two usable
measurements. A client row cap makes collection partial rather than allowing an
apparently complete rank comparison. Search Console's own row omissions still
mean that absence of a client cap does not establish full coverage.

Worker exception envelopes receive a timestamp before persistence. Otherwise a
new failure could sort behind an earlier success and disappear from the brief.

The brief now includes absolute baseline metrics even with only one observation,
measurement context, coverage, freshness, and reasons for blocked comparisons.
Null values render as unavailable; a genuine numeric zero stays zero. Failed,
partial, stale, or unknown-age observations do not generate current first-party
metric opportunities or rank movement. Historical evidence remains on disk.

## Freshness policy

Observation age is not the same as the measurement period's end date. Both are
shown. The default maximum observation age is 168 hours. Set an explicit
site-local policy appropriate to the reporting cadence in `.seo/site.yaml`:

```yaml
reporting:
  max_age_hours: 168
```

The accepted range is 1 through 8760 hours. Changing this threshold does not
refresh data, authenticate a provider, or prove that tracking instrumentation is
correct. Collection timestamps require an explicit timezone; a timestamp more
than five minutes in the future is invalid.

## Qualification and remaining live work

Run from a complete checkout:

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/seo_closure.py --json
python -m compileall -q scripts hooks extensions seo.py
python seo.py --help
python scripts/qualify_package.py
```

`qualify_package.py` tests committed HEAD, not unstaged edits. The focused
regressions are in `tests/test_measurement_readiness.py`. They cover scope changes,
period overlap/repetition, sparse/empty observations, failed collection, recovery,
row caps, baseline rendering, and freshness. They do not use live credentials.

A host must still authenticate the direct first-party clients, confirm property
and hostname scope, validate analytics instrumentation, establish report delivery,
and run the managed scheduler. A chat connector can supply one-off evidence but
its authorization does not authenticate the standalone Python process. Record
connector evidence separately and never present it as a successful direct-client
or host-installation test. Private account details and samples do not belong in
this public repository.

No publication/media/deployment/recovery qualification is claimed by this
milestone. The previous SellRight publication assumption was withdrawn: SellRight
is a backend provider for RightApps/RightSites and direct API writes are prohibited.
Its token, concurrency and media APIs are not SEO prerequisites. Qualify the site's
actual source/content and deployment route instead.

## First-party contract reference

Google's [Search Analytics query contract](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)
defines inclusive Pacific-time dates, dimensionless aggregation, page-filter
aggregation constraints, and finalized versus incomplete data. Scope and
aggregation must match before interpreting two snapshots as comparable.
