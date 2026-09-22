# Agent readiness

`scripts/agent_readiness.py` builds a read-only, machine-readable route map for an interactive SEO agent. It reads explicit portfolio roots, each root's `.seo/site.yaml`, and saved portfolio reports. It does not invoke models, provider APIs, schedulers, deployment commands, or browser tools.

An operator-owned private route manifest may supply concrete local repo/site-prefix, remote checkout/site path, build command, PM2 target, live URL, recovery procedure, local Git-root evidence, and pending qualification rows. Readiness exposes only safe route identifiers, PM2 target, live URL, route state, and pending blockers.

```sh
python scripts/agent_readiness.py --portfolio /path/to/portfolio.json --reports-dir /path/to/reports
python scripts/agent_readiness.py --portfolio /path/to/portfolio.json --reports-dir /path/to/reports --output /private/agent-readiness.json --include-private
```

Output schema is version 1. Each site route includes exact existing workflow and publication interface names (`sync`, `enqueue`, `request`, `submit`, `advance`, `prepare`, `approve`, `apply`, `status`, `reconcile`, and `rollback`) plus documented argument shapes.

```json
{
  "schema_version": 1,
  "kind": "seo_agent_readiness",
  "activation": "disabled_by_design",
  "host": {
    "state": "ready|missing|not_verified|disabled_by_design",
    "interactive_route_state": "ready",
    "unattended_route_state": "not_verified",
    "checks": {"strict_proposal_envelope": "...", "read_only_sandbox_flag": "...", "shell_false": "...", "bounded_input_output": "...", "process_tree_containment": "...", "absolute_executable_and_permissions": "..."}
  },
  "sites": [{
    "site": "example.com",
    "provider_identities": {"gsc": {}, "ga4": {}, "bing": {}},
    "policy": {"mode": "approved"},
    "route_plan": {
      "collection": {}, "proposal": {}, "deploy": {}, "verify": {}, "recovery": {},
      "activation": {}, "source_ownership": {}, "route": "..."
    },
    "evidence": {"reports": [], "saved_site_report": true}
  }]
}
```

`ready` means configuration and saved evidence meet that route's local prerequisite. `not_verified` means an operator or external system must supply evidence. `missing` means required configuration or implementation is absent. `disabled_by_design` means a route is intentionally inactive, such as workflow activation in this readiness run. A report or model attestation never upgrades factual verification by itself.

The recommended route is an interactive Codex host using existing workflow `request`/`submit` interfaces. `codex_host.py` already uses read-only Codex execution, strict proposal JSON, bounded input/output, shell disabled, and bounded direct-process cleanup. Process-tree containment, operator executable identity, and permissions remain `not_verified` until qualified. Deployment continues through each site's existing scoped SSH build/restart path after canonical commit and push; GitHub deployment receipts are evidence obligations, not a requirement to enable `workflow.enabled` or to invent a native deployment adapter.

Sites with static or legacy hosting use a separate private route. The readiness map keeps those routes distinct from SSR/PM2 deployment and reports source parity, static readback, exact receipt, and public verification as separate prerequisites.

The private output may include input paths only when `--include-private` is explicitly used. Public stdout contains site/domain identifiers and report basenames, never credentials or local filesystem paths.
