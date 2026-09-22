# Preserved guidance from the historical SEO skill

This reference records semantic instructions that were easy to lose when the
workspace skill moved into Legion and then into the standalone package. It carries
guidance only; it does not create a scorer, provider, template engine, or publishing
route.

## Local identity reconciliation

When local identity differs across a page, structured data, and a business profile,
compare each field against the site's named source of truth. Record the field, each
observed value, source, observation date, and confidence. Treat an unavailable profile
or an undetectable field as unknown. Recommend one owner and one correction set, then
recheck page-visible NAP, schema, profile, and linked location surfaces after the
site's normal publishing flow. Do not silently choose a value or claim consistency
from one surface.

Use the same evidence discipline for location architecture: connect service pages,
location pages, and the primary local hub only when the relationship is real and useful
to visitors. Avoid doorway or duplicated location pages.

## Truthful authorship and identity

Use `Person` and `ProfilePage` only when a real author or expert is represented on the
page with a visible biography or other first-party identity evidence. Keep name,
role, credentials, affiliation, and authorship claims tied to approved sources. Add
`sameAs` only for authoritative profiles that represent that same person or entity;
never infer identity from a matching name or invent credentials, profiles, or links.
Schema must match visible page content and current feature eligibility. A FAQ or Q&A
section may answer a real user need without implying a rich-result entitlement.

## Vertical and industry weighting

Industry and domain context may change which checks are relevant and how a finding is
prioritized. Use typed vertical criteria, such as applicable local schema or regulated
content requirements, with the site's market and page purpose. Do not apply unexplained
numeric multipliers, universal local scores, or fixed ranking weights. If a weighting
model is explicitly supplied, record its source, version, inputs, and effect on
priority; otherwise report criteria and evidence without manufacturing a score.

## Query opportunity rows

Every near-miss, zero-click, or true-gap row must identify:

- query and market/device/date scope;
- matching page URL, or an explicit `none` for a true gap;
- evidence source and coverage limits;
- classification and observed condition;
- one proposed action with its reason and dependency;
- priority plus confidence or an explicit unknown.

Near-miss means the site appears for the query but the observed position is weak;
zero-click means impressions exist with little or no clicks and requires a stated
hypothesis rather than a claimed cause; true gap means the selected evidence shows no
owned page/query presence within its coverage. These labels are observations for
triage, not proof of causality or automatic permission to create, consolidate, or
redirect a page.
