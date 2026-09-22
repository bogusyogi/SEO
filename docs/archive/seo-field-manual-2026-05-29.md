# SEO field manual — historical archive

Archived from https://spoares.com/seo on 2026-09-22. Original publication: 2026-05-29.

**Historical reference, not current operating instructions.** Fixed AI visibility percentages, word-count recipes, crawler classifications, paid-provider availability, old commands & brand deployment states below must not be treated as verified current facts. Current guidance lives in `SKILL.md`, `references/ai-search-2026.md` & `docs/SUPPORT-MATRIX.md`. Current dashboard uses free direct first-party collectors.

---

I · How search works☰

- IHow search works
- IIFoundations
- IIIOn-page & content
- IVGEO / AEO
- VOff-page links
- VIMeasurement
- VIIRun the agent
- VIIIBrand status

SEO · Operator v0.1

# SEO Field Manual

One system for ranking and getting cited by AI, across nine ventures. Foundations, on-page, GEO/AEO, off-page link earning, measurement, and how to drive the agent. Eight acts you can read on your phone.

Adrian · Operator v0.1 · 2026-05-29

Sources: site-playbook+ /seo skill+ 2026-05 reel batch+ Google GEO guidance+ off-page reference

Act II / VIII

## How search works now

SEO and AI search are one system, not two.

SECTION 1 / 8

SECTION 1 / 17

### Fundamentals still ruleGoogle’s own GEO guidance, 2026

AI Overviews + AI Mode are rooted in core ranking and quality systems. Google’s AI uses the search index; ChatGPT does a web search then summarises. So traditional SEO + E-E-A-T are the foundation, and “AEO/GEO” is a thin layer on top — not a separate discipline.

What Google itself calls myths (stop over-investing as ranking levers)

| “AEO hack” | Reality | Our stance |
| --- | --- | --- |
| Schema / structured data | Not required to appear in AI features | Keep for rich-result eligibility + entity clarity — not a ranking boost |
| llms.txt & special AI markup | Not used by Google AI features | Publish for tidiness; don’t count it as a GEO win |
| Content chunking for AI | No requirement | Good H2/H3 structure already does this |
| Rewriting content just for AI | Discouraged | Write for humans; SEO fundamentals carry |

SECTION 2 / 17

### The real levers, in order

- 1Genuinely useful content with first-hand experience (E-E-A-T)
- 2Traditional on-page + technical SEO
- 3Earned brand presence off-site (mentions, Reddit, YouTube, Wikipedia)
- 4Cheap on-page AEO formatting (answer-first, question headings, cited stats)

Brand mentions > backlinks for AI

Brand mentions correlate ~3× more strongly with AI visibility than backlinks (Ahrefs Dec-2025, 75k brands).

| YouTube mentions | ~0.737 (strongest) |
| --- | --- |
| Reddit mentions | High |
| Wikipedia presence | High |
| Domain Rating (backlinks) | ~0.266 (weak) |

Act IIII / VIII

## Foundations

The audit floor. AI crawlers don’t run JavaScript — this matters more than ever.

SECTION 3 / 8

SECTION 3 / 17

### Technical checklist

- Crawl + index — clean robots.txt, valid sitemap, no stray noindex, correct canonicals, no orphans — verify in GSC URL Inspection, never assume
- Server-side rendering — key content in the HTML, not client-only. Qwik storefronts + CF Pages are SSR/static — spot-check view-source
- Core Web Vitals — LCP, INP (replaced FID Mar-2024 — never say FID), CLS. Use CrUX field data
- AI crawler access — allow GPTBot, OAI-SearchBot, ChatGPT-User, ClaudeBot, PerplexityBot; block training crawlers separately (Act VIII)
- Schema (hygiene) — Article, BreadcrumbList, Organization, Person, Product. FAQPage = AI-citation benefit only (Google rich result restricted to gov/health). No HowTo for rich results

Run /seo audit <url> (parallel) or /seo technical <url>

Act IIIIII / VIII

## On-page & content

The moat: real experience, structured for extraction.

SECTION 4 / 8

SECTION 4 / 17

### Answer-first / TL;DRthe highest-ROI AEO win

Answer the title’s question in the first sentence (≤40 words, self-contained, quotable), or lead with a 2–3 line “TL;DR:”. AI lifts the answer; humans don’t bounce.

Reel: heytony — paste a post URL into an LLM, ask for an answer-first intro.

SECTION 5 / 17

### Citability + E-E-A-T

Extractable structure

- 134–167-word answer blocks — self-contained
- Definitions — “X is…” / “X refers to…”
- Question-shaped H2/H3s — match how people ask
- Tables for comparisons — short paragraphs elsewhere

Princeton GEO boosts

- Cite sources — +40% AI visibility
- Add statistics — +37%
- Add quotations — +30%
- Keyword stuffing — −10% (actively hurts)

Author credentials from SEO/AUTHOR-PROFILE.md — never invent a bio claim.

SECTION 6 / 17

### The ideation loopthe unique-content engine

- 

1 — Mine real questions

PAA, AlsoAsked, AnswerThePublic, findquestions, Reddit threads, and the GSC 8+ word query trick (Act IV).
- 

2 — Interview the founder, don’t invent

Prompt: “I’m writing a post answering <question>. Ask me up to 10 questions, one at a time, to surface my real experience, examples, case studies, and opinions.” Adrian answers (voice fine). Build the post from his answers.
- 

3 — One target query per post

Map to SEO/data/<brand>/keyword-map.csv; target the gap clusters.

Facts — hard gate

Every stat cited or removed. No fabricated surveys/quotes/press/reviews. Scope geo stats. AI fact-audits over-flag — verify each flag against LIVE content before “fixing” (~4 real per ~15 flags). Outbound = authority only; never link competitors.

Governed by blog-post-contract.md. Run /brand then /seo content or /writing-pro.

Act IVIV / VIII

## GEO / AEO / AI search

Optimise to be cited by AI Overviews, ChatGPT, Perplexity, Gemini, Copilot.

SECTION 5 / 8

SECTION 7 / 17

### The three pillars

01

Structure

definition / step / comparison / FAQ / stat blocks. Lead each section with the answer.

02

Authority

sources, stats, quotes, dates, author credentials, entity clarity.

03

Presence

Wikipedia, Reddit, YouTube, Quora, roundups, review sites. Third-party > your own site for ChatGPT/Perplexity → Act V.

SECTION 8 / 17

### Platform cheat-sheet

| Platform | Cites | Optimise for |
| --- | --- | --- |
| Google AI Overviews | Top-10 ranking pages | Traditional SEO + passage optimisation |
| ChatGPT | Wikipedia (~48%) + Reddit | Entity presence, authoritative sources |
| Perplexity | Reddit (~47%) + Wikipedia | Community validation, recency |
| Bing Copilot | Bing index + authoritative | Bing SEO + IndexNow |

Only ~11% of domains are cited by both ChatGPT and Google AIO for the same query — optimise per-platform.

SECTION 9 / 17

### The GSC long-tail / LLM-query trickreel: iojeet

In GSC → Performance → Queries → filter → Custom (regex), surface 8+ word conversational queries — the question-shaped ones that surface in LLMs and competitors ignore. High-impression + low-CTR long-tails are ready-made AEO targets; build an answer-first block per exact phrasing.`GSC regex:   ^(\S+\s+){7,}\S+$
In pipeline: /seo google gsc <property>
then filter  len(query.split()) >= 8`

Calibration: llms.txt + deep schema are hygiene, not ranking levers. Spend effort on answer-first blocks, question headings, cited stats, earned mentions.

Run /seo geo <url> → outputs GEO-ANALYSIS.md (readiness score + per-platform + crawler access + citability passages).

Act VV / VIII

## Off-page: earning links & trust

The half most SEO tools skip. White-hat only.

SECTION 6 / 8

SECTION 10 / 17

### Hard guardrailnever do these

| Banned | Why |
| --- | --- |
| Buying reviews | Trustpilot/Google/G2/Glassdoor farms — fraud, platform bans |
| Reddit / forum comment spam | Astroturfing; subreddit + Google spam actions |
| Paid “PR” link placements | Forbes/Reuters/Yahoo “$300–1000” = link scheme |
| Parasite SEO | Medium/Substack stuffed with your links — host crackdowns |
| Backlink-exchange / reciprocal networks | Link scheme per Google guidelines |
| PBNs, mass directory blasts | Classic spam footprints |

A 2026-05 reel taught all of these as “hacks.” They’re link schemes / fraud. We do the legitimate mirror of each.

SECTION 11 / 17

### The four legitimate tactics

Digital PR / HARO

Build a cited-stat linkable-asset page, then pitch journalists (Qwoted/Featured/SourceBottle) with a tight quotable answer + one stat. Highest authority.

Unlinked-mention reclamation

Find mentions without a link (Ahrefs Mentions, Google Alerts, Unlinked.io, "Brand" -site:brand.com) and ask warmly. Best ROI — they already like you.

Guest posting

Operators ("niche" + "write for us"); qualify DA≥30, traffic up, spam <5%, niche-relevant; <200-word pitch, one follow-up; 1,500–2,500w original.

Distribution (legit)

Repurpose each pillar → LinkedIn, YouTube, genuine Reddit/Quora, email. Canonical-tag syndication. Route via /social.

Outreach tracker

One row per prospect in SEO/data/<brand>/outreach-log.csv: brand · tactic · domain · DA · contact · url_mentioned · pitch_date · follow_up · status · placement_url · anchor. Never pitch a won/pitched domain twice.

Run /seo off-page [tactic] <domain> → OFF-PAGE-PLAN.md.

Act VIVI / VIII

## Measurement & tools

What to watch, and where.

SECTION 7 / 8

SECTION 12 / 17

### Tool map

| Need | Tool | Command |
| --- | --- | --- |
| Rankings, DR, backlinks, referring domains, organic keywords, competitor gap, Brand Radar (AI visibility) | Ahrefs MCP | /seo ahrefs |
| Real CWV field data, indexation, GSC clicks/impressions/CTR/position, GA4 organic | Google APIs | /seo google |
| Live SERP, keyword volume, backlinks (alt) | DataForSEO | /seo dataforseo |
| Full-site crawl / URL discovery | Firecrawl | /seo firecrawl |
| AI-visibility monitoring (cited or not, per platform) | Otterly / Peec / ZipTie / LLMrefs — or DIY monthly query log | — |

SECTION 13 / 17

### Standing cadence

- Weekly — GSC quick-wins (pos 4–10, high impressions) + 8+ word long-tails
- Monthly — Ahrefs new/lost backlinks + referring domains + Brand Radar; manual AI-citation check (top 20 queries)
- Per-post — submit to GSC/Bing after publish; watch rankings at 30 / 60 / 90 days

Act VIIVII / VIII

## How to run the agent

The skills do the work — prompt them right.

SECTION 8 / 8

SECTION 14 / 17

### Rules of engagement

- /brand <DD|RH|HR|TS> first — loads voice, palette, restrictions. SS is exempt — no commercial/SEO work on Stunning Strangers, ever.
- /seo <command> <url> — audit · page · technical · content · schema · geo/aeo · local · backlinks · off-page · ahrefs · google. Router loads only the matching reference.
- Blog work auto-loads the contract — anatomy + answer-first + FAQ + author bio + internal links + fact gate
- Fact discipline — WebSearch-first + ≥2 sources for any stat; no fabrication; verify every fact-audit flag against live content first

SECTION 15 / 17

### Copy-paste starters

`/seo audit https://damneddesigns.com — full audit, prioritise AEO + off-page gaps.``/brand RH, then write 3 fabric-education posts to the blog contract, answer-first, target the gap clusters in the RH keyword map.``/seo off-page heardright.app — build a linkable-asset plan + unlinked-mention list + 10 guest prospects.``Pull GSC 8+ word queries for DD and turn the top 10 into answer-first blocks.`

Act VIIIVIII / VIII

## Per-brand status

AI-crawler controls + earned presence.

SECTION 9 / 8

SECTION 16 / 17

### AI-crawler / training-block statusas of 2026-05-29

Method: robots.txt Content-Signal: ai-train=no + training-bot Disallow (keeps citation crawlers), plus noai, noimageai meta + X-Robots-Tag image header.

| Brand | Stack | Training block | llms.txt | Notes |
| --- | --- | --- | --- | --- |
| DD | Vendure | ✅ live | ✅ live | citation kept |
| RH | Vendure | ✅ live | ✅ live |  |
| mailright | CF Pages | ✅ live | ✅ live | llms added 2026-05-29 |
| viewright | CF Pages | ✅ live | ✅ live | llms added 2026-05-29 |
| TS | Vendure | ✅ built | ✅ built | dist ready — live blocked: nginx docroot ≠ dist (need served path) |
| bogusyogi | CF Pages | ✅ live | ✅ live | site shipped 2026-05-29 |
| SS | Vendure | ✅ live (defensive) | — | passion project — passive technical optimization only; no active commercial SEO |
| heardright | CF Worker | ✅ live | ✅ live | redeployed 2026-05-29 (zephyr fixed) |

SECTION 17 / 17

### Earned-presence checklistper commercial brand — ongoing

- Wikipedia / Wikidata — accurate entity where notability allows (don’t force a page that fails notability). Strongest for ChatGPT citation.
- Reddit / forums — genuine participation (r/knives, r/EDC → DD; r/malefashionadvice, r/ethicalfashion → RH/TS; r/dictation, r/productivity → HR). Answer first; never buy/spam.
- YouTube — even modest explainer content — strongest AI-citation correlation
- Review platforms — real reviews only (G2/Capterra for HR/MailRight/ViewRight; brand-site/Trustpilot for DD/RH/TS)

End of field manual

Fundamentals + E-E-A-T + earned presence. Everything else is formatting.

Pick the brand with the weakest AI visibility. Run /seo audit, fix the foundations, ship three answer-first posts to the contract, and start one off-page tactic. Measure at 30/60/90.Back to top ↑

SEO Field Manual · Operator v0.1 · 2026-05-29 · 8 acts
