# Portfolio maintenance workflow

This is an extension of the existing runner, content queue, remote-action receipts
and intervention ledger. It is not a new agent framework. One installation serves
multiple independently configured site roots. No site, host, paid service, merge,
production schedule or credential is enabled by installing this code.

## Inventory and recurring execution

Discover existing site configuration under explicit local directories, without
reading credential stores or assuming that the discovered set is all owned domains:

```sh
python /opt/SEO/seo.py portfolio discover --root /sites --output /config/portfolio.json
python /opt/SEO/seo.py portfolio status /config/portfolio.json
python /opt/SEO/seo.py run --portfolio /config/portfolio.json tick
python /opt/SEO/seo.py run --portfolio /config/portfolio.json serve --poll-seconds 300
```

The manifest remains `{"roots":["/sites/one","/sites/two"]}`. Relative paths resolve
against the manifest, not the process working directory. Discovery is bounded,
does not follow directory symlinks, refuses to overwrite an existing manifest and
will not silently promote incomplete discovery into a complete inventory. Duplicate
roots or two workspaces for one domain are rejected to avoid competing writers.
A broken configuration or failed provider on one site does not stop other sites.

Each site keeps its own collection schedule, policies, mappings and `.seo` state.
Collection still runs through `seo_runner.py`. An explicitly enabled workflow can
run even without a collection schedule; it needs actual saved evidence or an
explicitly enqueued task. Missing GA4 does not block an independently verifiable
technical repair. Portfolio JSON and Markdown summaries are written beside the
manifest as `<name>.report.json` and `<name>.report.md`; these are files, not claims
of email delivery. Installing a managed OS service is a separate operation.

## Site authorization and host connection

Preserve existing `.seo/site.yaml` fields. The following is an illustrative
configuration fragment, not authority to change any real site:

```json
{
  "policy": {
    "mode": "approved", "approval_ref": "operator-reviewed-site-policy",
    "allowed_actions": ["metadata", "draft", "deploy", "media", "rollback"],
    "write_prefixes": ["content", "public/images"], "allowed_hosts": []
  },
  "workflow": {
    "enabled": true, "max_tasks_per_tick": 3, "max_host_attempts": 3,
    "evaluation_days": 28, "minimum_impressions": 100,
    "auto_approve_kinds": ["metadata"],
    "approval_ref": "standing-reviewed-metadata-policy",
    "require_media": false,
    "host": {
      "argv": ["/absolute/path/to/existing-host-wrapper"],
      "approval_ref": "operator-approved-host-executable",
      "timeout_seconds": 180, "env_allowlist": []
    }
  }
}
```

The wrapper is an existing harness integration chosen by the operator. It receives
one UTF-8 JSON request on stdin and returns one JSON object on stdout. It must read
and review the actual site files and evidence, and use its own supported reasoning,
research, preview and review capabilities. The package does not invent a universal
Claude/Codex CLI invocation or install a model. No Legion role is required.

Only the explicitly approved executable/arguments run, without a shell. Input and
combined output are bounded at 2 MiB and execution has a timeout. Sensitive stderr
is not retained. Credential environment names can be explicitly allowlisted; values
must never be placed in site YAML or host responses. The host is trusted operator
code, **not sandboxed by this transport**. Configure its own file/network/tool
permissions so proposal generation cannot publish or alter SEO policy. Any model
costs or credentials belong to that separately authorized host, not an implicit
paid SEO provider dependency.

The host request exposes task evidence, business/author facts, allowed paths and the
maintained topic map, not the complete site configuration. Host output cannot grant
authority, select arbitrary commands or assert deployment success. Standing content
approval and repository submission/merge approval are distinct. Stunning Strangers'
technical-only restriction remains enforced by the existing site policy.

## Manual handoff and accepted proposals

An existing interactive agent can use the same interface without a subprocess:

```sh
python /opt/SEO/seo.py workflow --root /sites/one sync
python /opt/SEO/seo.py workflow --root /sites/one enqueue \
  --target https://example.com/guide/ --kind metadata \
  --issue 'Observed missing canonical' --evidence /private/evidence/audit.json
python /opt/SEO/seo.py workflow --root /sites/one request TASK_ID
python /opt/SEO/seo.py workflow --root /sites/one submit TASK_ID --plan /private/reviewed-plan.json
python /opt/SEO/seo.py workflow --root /sites/one advance TASK_ID
python /opt/SEO/seo.py workflow --root /sites/one status
```

A change response has this structure; actual content must use the site's native
format and include the expected public text:

```json
{
  "schema_version": 1, "task_id": "TASK_ID", "decision": "change",
  "reason": "Repair the observed canonical defect without changing factual copy",
  "path": "content/guide.html",
  "content": "<html><head><link rel=\"canonical\" href=\"https://example.com/guide/\"></head><body>Existing verified guide.</body></html>",
  "expected_text": "Existing verified guide.", "media_ids": [],
  "review": {"facts":"pass","intent":"pass","links":"pass","preview":"pass",
             "evidence":"/private/reviews/guide-review.json"}
}
```

`retain` and `defer` instead require a reason and may provide `next_review_days`
(1..365). They schedule reconsideration rather than manufacturing a change.
Content changes additionally require `editorial.author_id` present in operator-owned
`author_facts`, a distinct `intent`, useful `information_gain`, verified sources
(`url`, timezone-aware `checked_at`, `supports`) and the existing claim contract
(`claim`, `source`, `state`, `use_in_output`). Used claims must be approved and cite
one of those sources. Source checks older than 90 days are rejected. Topic ownership
combines operator `topic_map` with prior validated intervention plans. Existing
business facts, author facts and source records must be genuine, not filled with
invented first-hand experience or placeholders.

These gates validate structure, binding and recorded review; **they cannot prove
that an LLM's claim or preview attestation is true**. The authorized host/reviewer
must actually inspect sources and preview artifacts before returning `pass`.
The existing specialist SEO/blog contracts continue to govern that work.

## Media and concrete repository publication

Stage real, licensed image bytes before referring to their IDs in a proposal:

```sh
python /opt/SEO/seo.py media --root /sites/one stage guide-image \
  --source /private/assets/guide.png --path public/images/guide-v1.png \
  --url https://example.com/images/guide-v1.png --alt 'Actual image description' \
  --license-ref /private/assets/rights-record.json --role featured
```

PNG, JPEG and WebP headers/dimensions are checked without a decoder dependency;
this is not full image-decoder validation. Each file is at most 4 MiB. IDs and
repository asset paths are immutable. A page can reference at most ten assets and
one featured asset; additional assets use `--role inline`. The actual content must
use the approved URL/alt text, with width and height present in the rendered HTML.
The featured asset must also appear in OG and Article/BlogPosting image metadata.

For a real GitHub-backed site, configure its actual identity and deployment route:

```json
{
  "deployment": {
    "provider": "github", "repository": "OWNER/ACTUAL_SITE_REPOSITORY",
    "repository_id": 123456, "base_branch": "main", "environment": "production",
    "token_env": "SITE_GITHUB_TOKEN", "auto_submit": false,
    "approval_ref": "operator-approved-repository-submission",
    "auto_merge": false, "required_checks": ["ACTUAL_REQUIRED_BUILD_CHECK"],
    "merge_approval_ref": "separately-approved-production-merges"
  }
}
```

Do not copy the example identity/check names into production. Token provisioning
and renewal occur outside SEO state. The client checks exact repository ID, base,
approved content baseline and actual media bytes. It creates one Git tree/commit
containing **one page file plus its associated media**, a new branch, and a PR.
It never force-pushes or directly replaces the default branch. Arbitrary multi-file
application changes are not represented as a supported transactional patch here.

`auto_submit` needs its standing reference and `deploy` policy. `auto_merge` also
needs a separate reference, `merge` in allowed actions and named successful checks.
Submission does not imply merging. With manual approval:

```sh
python /opt/SEO/seo.py publication --root /sites/one prepare ACTION_ID \
  --task TASK_ID --media guide-image --evidence /private/reviews/guide-review.json
python /opt/SEO/seo.py publication --root /sites/one approve ACTION_ID \
  --digest EXACT_RETURNED_REQUEST_SHA256 --approval-ref OPERATOR_REFERENCE
python /opt/SEO/seo.py publication --root /sites/one apply ACTION_ID
python /opt/SEO/seo.py publication --root /sites/one status ACTION_ID
```

The site's existing build/deployment pipeline must emit GitHub Deployment records
for the **exact merged commit**, configured environment and owned environment URL.
Missing/pending/failed receipts remain blockers. A green build, a PR or a merge alone
is not deployment. This adapter does not guess Cloudflare, Vercel, CMS, preview or
production ownership. It is not automatically attached to every domain.

## Recovery and later measurement

Workflow state lives in the existing `.seo/interventions/search-ops.json`; prepared
files use the existing queue and remote effects use existing remote-action receipts.
A validated plan is persisted before preparing effects; crashes resume that exact
plan instead of reauthoring. Repeated successful operations return recorded results.
A changed site configuration or baseline invalidates approval. Uncertain remote writes
are never automatically replayed. `publication reconcile ACTION_ID` reads the exact
branch/commit/tree/PR to prove the prior effect; missing or conflicting evidence stays
uncertain. Expired credentials require renewal outside state, followed by a read or
reconciliation as appropriate, not another blind create request.

`publication rollback ORIGINAL_ID NEW_ID --evidence REFERENCE` prepares a new,
separately approved reverse PR. It restores/removes only the original page if that
page still matches the prior effect. It does not reset the repository, undo unrelated
commits or delete potentially shared media. The reverse PR still needs merge,
deployment and verification; local rollback is not production recovery.

After a matching deployment receipt, the public verifier checks HTTP status, intended
URL, visible expected text, a unique canonical, indexing directives, media attributes,
featured-image metadata and exact asset bytes. It does not execute JavaScript or
replace a browser/visual/accessibility review. Sites that transform image bytes need
a specifically qualified output contract; transformed bytes do not silently pass.

Successful public verification schedules a real future page-filtered GSC collection
in the same ledger. The default baseline is 28 days ending four days before capture;
the follow-up starts two days after public verification, lasts 28 days and becomes
due four days later. The existing recurring runner executes it when due. Three bounded
follow-up attempts are allowed, a day apart; collection failure never republishes.
An unavailable baseline/follow-up yields not-measurable, low impressions yield
inconclusive, and descriptive movement is never presented as causal attribution.
Review each site's cadence, threshold, instrumentation and measurement suitability.

## Qualification boundary

Repository tests exercise real local writes, subprocess handoff, persistence and
recovery, with simulated provider/GitHub/HTTP boundaries. Archived-package smoke uses
no credentials, SDKs or Legion. This does not qualify a live agent host, website,
analytics tag, production pipeline or search outcome.

SellRight is a backend provider used by RightApps/RightSites, not an SEO publishing
API. Direct SellRight writes are prohibited, including through a host tool. The
previous adapter and command have been removed; server concurrency, machine tokens
and backend media upload are not remaining SEO work. Old CMS action receipts remain
readable but cannot execute. Existing site-provider usage is unchanged. Discover each
site's actual source/content ownership and normal deployment route rather than inferring
it from a backend integration or repository name.
