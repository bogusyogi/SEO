# Dashboard snapshot exporter

`python scripts/dashboard_export.py --portfolio PATH --performance-reports PATH --output PATH` creates schema version 1 JSON for the dashboard. Portfolio roots are read from `portfolio.json`; each root contributes only normalized `.seo` evidence. Performance folders matching `performance-baseline-*` or `performance-weekly-*` are supported, with a same-name `.psi.json` sidecar taking precedence.

Provider failures remain visible at newest observation timestamp. Missing values are `null`; measured empty GSC aggregates can be zero, while empty successful Bing observations are `no_data`. Output is allowlisted, redacted, UTF-8, and atomically replaced only after complete JSON serialization.
