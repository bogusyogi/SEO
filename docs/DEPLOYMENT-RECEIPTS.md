# Existing server deployments

SEO submits reviewed source changes through the site's existing GitHub repository.
It does not build, restart PM2, update nginx/Cloudflare, or write a backend provider.
An existing server pipeline can satisfy the GitHub deployment reader without moving
hosting to GitHub. This integration must be wired by that pipeline's owner before
unattended publication is considered qualified.

## Receipt producer contract

After an authorized merge, the normal deployment pipeline must:

1. Resolve the exact merged commit, repository ID, environment, site subdirectory,
   and owned public URL. Build that commit in a clean, isolated checkout. Retain its
   commit and build-output identity with the deployment log.
2. Run the site's existing build/restart/cache steps. A process being online is not
   sufficient: health and public checks must show the newly built revision is served.
   Never run a site's build command as a harmless preview without inspecting it;
   some scripts also restart production and purge caches.
3. Create a GitHub Deployment for the exact commit, with `auto_merge:false` and the
   configured environment. `required_contexts:[]` here only avoids implicit GitHub
   deployment gating; it does not replace SEO's separate reviewed merge checks.
4. Append `success` only after those checks, with the owned `environment_url` and
   durable `log_url`. Emit `failure` on failed build/restart/health checks. The
   authenticated deployment producer is responsible for truthful runtime evidence.
5. Let SEO's next tick independently read that receipt and verify the approved
   public assertions. Missing/pending/failing receipts remain blocked.

For a reviewed deployment, save these UTF-8 JSON bodies outside the public repo.
Replace example identities with the verified pipeline values:

```json
{
  "ref": "EXACT_MERGED_COMMIT_SHA",
  "environment": "production",
  "auto_merge": false,
  "required_contexts": [],
  "description": "Normal site pipeline deployment",
  "payload": {"source_subdirectory": "site-a", "build_evidence": "PRIVATE_DURABLE_LOG_REFERENCE"}
}
```

```sh
gh api --method POST repos/OWNER/REPOSITORY/deployments --input deployment.json
```

Use the returned deployment ID for the successful pipeline's status body:

```json
{
  "state": "success",
  "environment": "production",
  "environment_url": "https://example.com/",
  "log_url": "https://example.com/operator-owned-deployment-log",
  "description": "Exact revision built, served and health-checked"
}
```

```sh
gh api --method POST repos/OWNER/REPOSITORY/deployments/DEPLOYMENT_ID/statuses --input status.json
```

These are pipeline integration commands, not actions performed during repository
qualification. Never emit success simply to unblock SEO. A timeout after either
POST requires read-only reconciliation of that exact deployment before any retry.
Use separate environment names for independent apps sharing a repository so one
app's receipt cannot qualify another app. Environment URL ownership is also checked.

Recovery follows the same normal pipeline after a separately reviewed reverse PR.
SEO does not reset a shared repository or delete unrelated media.

Contracts: [GitHub Deployments](https://docs.github.com/en/rest/deployments/deployments)
and [deployment statuses](https://docs.github.com/en/rest/deployments/statuses).
