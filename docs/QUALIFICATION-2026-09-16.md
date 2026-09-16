# Qualification evidence — independent SEO repair

## Observed cross-platform run

GitHub Actions run: https://github.com/bogusyogi/SEO/actions/runs/35121128112
Source ref: a09afa2fae195c1ad04a422247a94438df660c29, with its final portable source edit applied during this one transition run.
The resulting source was committed as f181652bea8cf930f60608cb2c055114f74f3655.

All five jobs completed successfully:

- Ubuntu / Python 3.11: regression suite, closure, package smoke, minimal SDK-free environment.
- Ubuntu / Python 3.13: the same checks.
- Windows / Python 3.12: the same checks.
- macOS / Python 3.12: the same checks.
- Claude Code 2.1.273: strict validation of both plugin and marketplace manifests.

The source materialization scripts and workflows are removed from the package.
The final CI no longer runs any source codemods. It tests the committed source
and a separate git archive extracted into a clean directory, with an isolated
Python environment containing neither optional SDKs nor Legion. Consult that
final head's Actions result for the archive qualification outcome; this document
does not predeclare a future test result.

## What these checks establish

Deterministic regressions exercise the independent runtime and its state machine,
provider-response replay, data contracts, scope filters, error handling,
observations, local reversible changes, exact approval binding, budgets, crash
states, schema validation and the MCP SDK interface. A real SDK MCP client can
list the tools and call the same independent runtime in the test process.

The package smoke initializes a separate site project and generates a report
from outside the installation directory, without .legion state or credentials.
Claude native validation checks plugin/marketplace packaging; it does not prove
that a user's desktop host has installed or authorized the plugin.

## Not established by these tests

- Live GSC/GA4/Bing account access, property mappings or actual site measurements.
- GA4 tag/event correctness on deployed websites.
- Production CMS/repository publisher and remote rollback behavior for each site.
- Autonomous task execution on a machine without an activated scheduler.
- Optional external SEOMator/Unlighthouse binary runtime behavior beyond fixture normalization.
- Public ChatGPT app-directory publication or authenticated remote MCP hosting.
- Real-world ranking, citation, lead, conversion or revenue improvement.

No tests are waived as proof of any of these live capabilities. Qualify each
explicit boundary on the target host/site before enabling production writes.
