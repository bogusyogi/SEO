"""Explicit site-bound collection. External SDKs are lazy and failures remain failures."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from runtime_setup import python_executable
from site_policy import load, authorize, property_for

SCRIPTS = Path(__file__).resolve().parent


def collect(root, lane: str, *, days: int = 28, max_pages: int = 100,
            timeout: int = 180) -> dict:
    if not 1 <= days <= 3650 or not 1 <= max_pages <= 1000 or not 1 <= timeout <= 1800:
        raise ValueError('collection bounds exceeded')
    site = load(root)
    authorize(site, lane)
    url = 'https://' + site['domain'] + '/'
    with tempfile.TemporaryDirectory(prefix='seo-collect-') as td:
        output = Path(td) / 'result.json'
        if lane == 'gsc':
            args = ['gsc_query_v2.py', '--property', property_for(site, 'gsc'), '--days', str(days)]
        elif lane == 'ga4':
            args = ['ga4_report.py', '--property', property_for(site, 'ga4'), '--days', str(days), '--json']
        elif lane == 'bing':
            args = ['bing_webmaster.py', 'traffic', '--site', property_for(site, 'bing')]
        elif lane == 'backlinks':
            args = ['bing_webmaster.py', 'links', '--site', property_for(site, 'bing'), '--url', url]
        elif lane == 'audit':
            args = ['site_audit.py', '--url', url, '--max', str(max_pages), '--json', str(output)]
        else:
            raise ValueError('unknown collector lane')
        try:
            result = subprocess.run([python_executable(), str(SCRIPTS / args[0]), *args[1:]],
                                    cwd=str(Path(root).resolve()), capture_output=True, text=True,
                                    timeout=timeout, check=False)
            text = output.read_text() if output.exists() else result.stdout
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError('collector returned a non-object')
            # A completed crawl with findings is valid evidence, not failed collection.
            bad = data.get('error') or data.get('pages_error') or data.get('status') in {'fail', 'partial', 'error'}
            if lane == 'audit':
                usable = any(x.get('status') == 200 for x in data.get('pages', {}).values())
                bad = bad or not usable or data.get('coverage', {}).get('collection_failures', 0) > 0
            elif result.returncode:
                bad = True
            state = 'partial' if bad else 'ok'
            error = 'collector failed or returned incomplete evidence' if bad else None
        except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
            state, data, error = 'failed', {}, type(exc).__name__
        return {'schema_version': 1, 'site': site['domain'], 'lane': lane,
                'collected_at': datetime.now(timezone.utc).isoformat(),
                'status': state, 'error': error, 'data': data,
                'scope': 'owned site; unavailable data is not zero'}
