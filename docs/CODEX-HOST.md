# Optional Codex host

`scripts/codex_host.py` is a small optional adapter for an operator-selected
Codex CLI executable. It reads one `seo_workflow.host_request` JSON object from
stdin, invokes `codex exec`, then writes one version-1 proposal JSON object to
stdout. Codex strict output uses envelope `{"proposal_json":"<JSON text>"}`;
the adapter decodes and validates that proposal before returning it. It does
not call a model during installation, and it has no SDK or
provider dependency.

An operator-owned site configuration can use this command as its `workflow.host`
argv. The executable must be an existing absolute executable path. On Windows,
use the actual executable (for example `codex.exe`), never a `.cmd` or PowerShell
wrapper. A typical argv is:

```json
{"argv":["C:/Python311/python.exe","C:/repo/scripts/codex_host.py","--codex","C:/Tools/codex.exe"],"approval_ref":"operator","timeout_seconds":180}
```

Append `--model` only when operator has selected a model. Adapter invokes
`codex exec --sandbox read-only --ephemeral --output-schema ...
--output-last-message ... --cd <site-root> -`; request JSON is supplied as
stdin. Input and combined process output are bounded at 2 MiB, timeout is
bounded to 1..1800 seconds, shell execution is disabled, and stderr is never
returned. A failed or malformed response is an error.

The generated strict JSON Schema permits only the `proposal_json` envelope;
decoded content is restricted to proposal fields already accepted by
`seo_workflow`: `change`, `retain`, or `defer`, matching `task_id`, at most
nine `supporting_changes`, and workflow `verification` entries. The adapter does not approve a proposal, verify
facts, grant review `pass`, publish files, call SellRight, or claim deployment.
The existing deterministic `seo_workflow.validate_plan` remains the acceptance
gate. If the model cannot source or preview a claim, its prompt directs it to
defer; operators must still review evidence and policy.

Authentication is separate and remains operator-owned through trusted config or
MCP permissions. Codex CLI's read-only sandbox is a process setting, not a
blanket guarantee about network or tool availability. This adapter has not been
qualified against a live model/provider; tests mock the subprocess only.

The command shape follows the installed Codex CLI `exec --help` contract and
[Codex non-interactive mode documentation](https://learn.chatgpt.com/docs/non-interactive-mode).

Timeout cleanup terminates the direct Codex process only. Qualify host-level process-tree containment separately before unattended use; this wrapper does not provide that containment.
