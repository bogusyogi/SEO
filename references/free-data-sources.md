# Free SEO data sources

Several first-party sources have free access or free quotas, subject to current product limits,
property eligibility, authentication and export coverage. Availability is not a promise that every
SEO data type is free or automatable.

## Why you don't need a paid tool for your own sites

Ahrefs/Semrush cost money because they run a **web-scale crawler** (AhrefsBot is the #2 crawler
on Earth) that visits billions of pages a day, records every `<a href>` across the entire web to
build the **backlink graph**, and scrape Google SERPs continuously for keyword volumes and
rankings. You cannot reproduce that — it's petabytes and thousands of servers. That is the moat,
and the *only* thing worth paying for.

But that moat only matters for **competitor** data. For **sites you own**, the search engines
themselves hand you the same facts for free — and more accurately, because it's their real index:

| Question about YOUR site | Free source | Paid tool needed? |
|---|---|---|
| Crawl/technical issues (titles, meta, h1, links, canonicals…) | `site_audit.py` | No |
| Rankings, clicks, impressions, positions | Google Search Console | No |
| Is this URL indexed? | GSC URL Inspection | No |
| My backlinks | GSC + Bing Webmaster | No |
| Core Web Vitals (lab + field) | PageSpeed + CrUX | No |
| Traffic, conversions | GA4 | No |
| **Competitor** backlinks / keywords / rankings | — | **Yes (Ahrefs/Semrush/DataForSEO)** |

Owned-site evidence can often be collected at no provider charge. It remains bounded by each
source's scope: GSC Links exports are sampled, and they have no official API for the Links report.
Competitor backlink and keyword datasets generally require a separate paid provider or manual export.

## The providers

| Provider | Gives | Credential | Env var(s) | Auto? |
|---|---|---|---|---|
| **PageSpeed Insights** | CWV lab (Lighthouse) | API key | `GOOGLE_API_KEY` | ✅ |
| **CrUX** | CWV **field** data (real users) | same API key | `GOOGLE_API_KEY` | ✅ |
| **Search Console** | queries, clicks, impressions, position, indexation | service account | `GOOGLE_APPLICATION_CREDENTIALS`, `GSC_PROPERTY` | ✅ |
| **GA4 Data API** | sessions, conversions, landing pages | same service account | `GOOGLE_APPLICATION_CREDENTIALS`, `GA4_PROPERTY_ID` | ✅ |
| **Bing Webmaster** | Bing rankings, crawl issues, **your backlinks**, URL submit | free API key | `BING_API_KEY` | ✅ |
| **IndexNow** | instant-index push (Bing/Yandex/others) | self-hosted key file | `INDEXNOW_KEY` | ✅ |

> **Ahrefs Webmaster Tools (AWT)** can be used through its dashboard and manual exports. Ahrefs now
> documents a free Domain Rating API endpoint that requires a free API v3 key and attribution:
> [Get Domain Rating (free)](https://docs.ahrefs.com/en/api/reference/public/get-domain-rating-free).
> It does not make the full Ahrefs backlink graph free or remove provider limits.
> Google's **Indexing API** (`indexing_notify.py`) is free but officially only honors JobPosting/
> VideoObject pages — use IndexNow for general pages instead.

## Where to get each credential

1. **Google API key** (PageSpeed + CrUX) — [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials).
   Create project → **Create credentials → API key**. Then **enable** these APIs in
   [API Library](https://console.cloud.google.com/apis/library): *PageSpeed Insights API*,
   *Chrome UX Report API*. (No billing needed; both are free-quota.)
2. **Service account** (GSC + GA4) — [Cloud Console → Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts).
   Create service account → **Keys → Add key → JSON** → download. Save the JSON somewhere private
   outside the repo — do not commit it or hardcode its path in shared config. Enable *Search Console API* and
   *Google Analytics Data API* in the API Library. Then **grant that service-account email access**:
   - GSC: [Search Console](https://search.google.com/search-console) → your property → Settings →
     Users & permissions → **Add user** → paste the `...@...iam.gserviceaccount.com` email → Full.
   - GA4: [GA4 Admin](https://analytics.google.com) → Property → Property Access Management →
     **+** → add the same email → Viewer.
3. **GSC property** — the exact property string, e.g. `sc-domain:example.com` (domain property)
   or `https://example.com/` (URL-prefix). One per site.
4. **GA4 property ID** — GA4 Admin → Property Settings → the numeric **Property ID** (e.g. `123456789`).
5. **Bing API key** — [Bing Webmaster Tools](https://www.bing.com/webmasters) → verify your site →
   Settings (gear) → **API access → API Key** → generate. One key covers all your BWT sites.
6. **IndexNow key** — no signup. Run `python scripts/indexnow.py genkey`, then host the printed key
   as a text file at the site root: `https://<host>/<key>.txt` whose *contents are exactly the key*
   (for the Right-Suite Qwik sites: drop `<key>.txt` in `public/`).

## Setting provider configuration (PowerShell, Windows)

Keep API keys and service-account paths private. Use a secret manager or local process environment;
never commit, print, or paste credentials into reports.

```powershell
# Set protected local values only as needed:
$env:GOOGLE_API_KEY = '<local secret>'
$env:GOOGLE_APPLICATION_CREDENTIALS = '<private service-account path>'
$env:GSC_PROPERTY = 'sc-domain:example.com'
$env:GA4_PROPERTY_ID = '<property id>'
$env:BING_API_KEY = '<local secret>'
$env:INDEXNOW_KEY = '<local secret>'
```

## Which script consumes which

| Script | Provider | Reads |
|---|---|---|
| `pagespeed_check.py` | PageSpeed + CrUX | `GOOGLE_API_KEY` |
| `crux_history.py` | CrUX | `GOOGLE_API_KEY` |
| `gsc_query.py`, `gsc_inspect.py` | Search Console | `GOOGLE_APPLICATION_CREDENTIALS`, `GSC_PROPERTY` |
| `ga4_report.py` | GA4 | `GOOGLE_APPLICATION_CREDENTIALS`, `GA4_PROPERTY_ID` |
| `bing_webmaster.py` | Bing Webmaster | `BING_API_KEY` |
| `indexnow.py` | IndexNow | `INDEXNOW_KEY` |
| `site_audit.py` | (none — crawls directly) | — |

Once the env vars are set and the service account is granted access to each property, the audit
pulls all six providers automatically — no per-run auth.
