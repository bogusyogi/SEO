#!/usr/bin/env python3
"""Offline contracts against real Google and MCP SDKs, installed only in qualification CI."""
from __future__ import annotations
import asyncio
import json
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check_google():
    from ga4_report import organic_filter
    from google.analytics.data_v1beta.types import RunReportRequest
    expression = organic_filter(['example.com', 'www.example.com'])
    request = RunReportRequest(property='properties/123', dimension_filter=expression)
    children = request.dimension_filter.and_group.expressions
    assert children[0].filter.string_filter.value == 'Organic Search'
    assert children[1].filter.field_name == 'hostName'
    assert list(children[1].filter.in_list_filter.values) == ['example.com', 'www.example.com']
    return {'google_analytics_data': version('google-analytics-data'), 'hostname_filter': 'pass'}


async def check_mcp():
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    with tempfile.TemporaryDirectory() as directory:
        server = StdioServerParameters(command=sys.executable, args=[str(ROOT / 'scripts/mcp_server.py')],
                                       env={'SEO_PROJECT_ROOTS': directory, 'PYTHONUTF8': '1'})
        async def exercise(client):
            tools = await client.list_tools()
            assert len(tools.tools) == 5 and any(t.name == 'seo_collect' for t in tools.tools)
            result = await client.call_tool('seo_report', {'root': directory})
            assert json.loads(result.content[0].text)['status'] == 'no_report'
            denied = await client.call_tool('seo_collect', {'root': directory, 'lane': 'serp'})
            assert getattr(denied, 'is_error', getattr(denied, 'isError', False))
        major = int(version('mcp').split('.')[0])
        if major >= 2:
            from mcp import Client
            async with Client(stdio_client(server)) as client:
                await exercise(client)
        else:
            from mcp import ClientSession
            async with stdio_client(server) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    await exercise(client)
    return {'mcp': version('mcp'), 'real_stdio_protocol': 'pass'}


def main():
    google = check_google()
    mcp = asyncio.run(asyncio.wait_for(check_mcp(), timeout=30))
    print(json.dumps({'status': 'pass', **google, **mcp, 'live_accounts_used': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
