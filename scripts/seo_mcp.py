#!/usr/bin/env python3
"""Optional MCP transport over the SAME independent runtime. Local stdio only.

The host fixes SEO_PROJECT_ROOT at server launch. Tools cannot change the root,
policy, credentials or approvals. No unauthenticated public HTTP endpoint exists.
"""
from __future__ import annotations
import os
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from seo_runtime import Runtime
from provider_doctor import doctor

try:
    from mcp.server import MCPServer
except ImportError:
    print('SEO MCP requires mcp>=2,<3. Run scripts/setup_runtime.py --mcp and use that interpreter.', file=sys.stderr)
    raise SystemExit(2)

def build_server(root=None):
    project = Path(root or os.environ.get('SEO_PROJECT_ROOT') or os.getcwd()).resolve()
    server = MCPServer('SEO', version='0.2.0', instructions='Use real evidence. This server is scoped to one configured site. Queue proposals, never invent approval. Legion is not required.')
    @server.tool()
    def seo_status() -> dict:
        """Read configured site identity and job states; does not execute queued jobs."""
        runtime = Runtime(project)
        return {'site': runtime.site['domain'], 'jobs': runtime.jobs()}
    @server.tool()
    def seo_doctor(live: bool = False) -> dict:
        """Check configuration; live=true performs bounded authenticated property reads."""
        return doctor(project, live=live)
    @server.tool()
    def seo_collect(provider: str, options: dict | None = None) -> dict:
        """Collect evidence for this site only. Does not drain other jobs or publish."""
        runtime = Runtime(project)
        job = runtime.enqueue('collect', {'provider': provider, 'options': options or {}}, key=uuid.uuid4().hex)
        return runtime.tick(limit=1, only_id=job['id'])
    @server.tool()
    def seo_report() -> dict:
        """Produce an evidence-health brief from stored observations; no publication."""
        runtime = Runtime(project)
        job = runtime.enqueue('report', {}, key=uuid.uuid4().hex)
        return runtime.tick(limit=1, only_id=job['id'])
    @server.tool()
    def seo_propose(kind: str, payload: dict) -> dict:
        """Queue an exact proposed action. Does not approve or execute it."""
        runtime = Runtime(project)
        job = runtime.enqueue(kind, payload)
        return {'job_id': job['id'], 'state': job['state'], 'approval': 'Separate owner approval or standing site policy is required for effects.'}
    @server.tool()
    def seo_execute(job_id: str) -> dict:
        """Execute ONLY this due job if exact approval/standing policy permits; may mutate this site."""
        runtime = Runtime(project)
        runtime.row(job_id)
        return runtime.tick(limit=1, only_id=job_id)
    @server.tool()
    def seo_inspect(job_id: str) -> dict:
        """Read a queued job, its actual state and observed result from this site."""
        return Runtime(project).row(job_id)
    return server

if __name__ == '__main__':
    build_server().run(transport='stdio')
