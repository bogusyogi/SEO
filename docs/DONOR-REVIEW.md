# Donor review — 2026-09-16

Reviewed the user-nominated repositories. No donor framework is required by SEO.
Review pins below are README **blob IDs**, not whole-repository release pins. This
pass assessed their documented interfaces/workflows; it is not a deep audit of all
seven codebases. Native third-party tools still require separate qualification.

| Source | Reviewed material | Decision in this repair |
|---|---|---|
| AgriciDaniel/claude-seo | README blob `1ab8963d4fa22142008ef248f03b6908a6ad50bf`; MIT blob `94fac7465f1e76414fc59f9fd97cdfd2105e030d` | Restore inherited image/report support with attribution; isolated explicit runtime setup; evidence-first workflows. Do not import its model/agent topology. |
| every-app/open-seo | README blob `9a874a272ea17aebb6bca0efe6d5552ee0fb677a` | Persistent per-site context, normalized data and common CLI/MCP implementation. No mandatory DataForSEO account, billing shell or hosted application. |
| seranking/seo-skills | README fetched 2026-09-16 | Content briefs, page decisions, backlink-gap and drift workflow benchmarks. No SE Ranking subscription dependency; account-specific integration remains optional host/provider tooling. |
| harlan-zw/unlighthouse | README blob `ed9c5722d6ade4c7d47c51c04c49be6151800e01` | Optional installed `unlighthouse-ci` adapter with explicit lab-measurement scope; no auto-install. |
| seo-skills/seo-audit-skill | README blob `7ed1d88148b011c1d8a35baded274b580a7fc8d7` | Optional installed SEOmator CLI adapter; preserve unknown/unmeasured results rather than adopting a marketing rule-count score. |
| best-of-ai/awesome-ai-seo | README blob `c87cf5366707fad1fe0a30d08d493b2a80aa5329` | Discovery reference only. Its CC0 label/CC-BY-SA link is inconsistent; no list copied. |
| EinGuterWaran/awesome-free-seo-backlinks | lowercase readme.md blob `a1f6554bfc2fc222c6b743fc4c58dd94654195e7` | Prospect discovery only. No root license found in inspected tree. No wholesale list import, automatic submission, or acceptance of DR as ranking truth. |

## Historical recovery

Copied support assets from `Orthic-Labs/legion` commit
`a4eaaa223c284ab81641c4283903648a2a8c1f14`, then adapted portable paths and explicit
paid-image authority. Restored `extensions/banana` (seven helpers and seven references)
and `pdf/google-seo-reference.md`. The root license is retained unchanged; donor MIT
material remains subject to its own terms. No runtime fetch from the history repository
is necessary. The temporary recovery workflow is removed from the delivered tree.

## Official contracts consulted

- OpenAI plugin package: https://developers.openai.com/plugins/build/plugins
- Claude plugin reference: https://code.claude.com/docs/en/plugins-reference
- Claude command-hook input: https://code.claude.com/docs/en/hooks
- MCP stdio and tool messages: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- Google Analytics metric schema: https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema
- Bing GetUrlLinks: https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi.geturllinks
- Unlighthouse CI adapter: https://unlighthouse.dev/integrations/ci

Provider configuration presence is not a successful live integration. Protocol fixture
success is not proof of marketplace publication or installation in every native host.

## Follow-up contract work — 2026-09-17

The 0.3.0 follow-up adds original concrete integration code rather than importing a donor
runtime. API/protocol contracts consulted:

- Google Analytics FilterExpression: https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/FilterExpression
- DataForSEO Live Advanced: https://docs.dataforseo.com/v3/serp-se-type-live-advanced/
- Official MCP Python clients: https://py.sdk.modelcontextprotocol.io/client/transports/

SellRight's authenticated blog contract was inspected during the earlier repair.
The resulting direct client was based on a mistaken publishing-route assumption and
has been removed. SellRight is a backend provider for RightApps/RightSites, not an
SEO write API or a prerequisite for this project. No private server implementation
or credentials are copied into this package. Optional
SDK qualification covers supported MCP v1/v2 client branches without making either a
core runtime dependency. This does not broaden the earlier donor review into an exhaustive
review of every upstream file.
