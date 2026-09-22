"""Bounded, explicitly site/host-scoped first-party collection. No paid dependency."""
from __future__ import annotations
import json
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from runtime_setup import python_executable
from site_policy import load, authorize, property_for
from measurement_scope import site_hosts, owned_url, measurement_context

SCRIPTS = Path(__file__).resolve().parent


def run_json(root, args, timeout, output=None):
    """Run only a packaged collector, with UTF-8 and structured failures."""
    completed = subprocess.run([python_executable(), str(SCRIPTS / args[0]), *args[1:]],
        cwd=str(Path(root).resolve()), capture_output=True, encoding='utf-8', errors='strict',
        timeout=timeout, check=False)
    text = output.read_text(encoding='utf-8') if output and output.exists() else completed.stdout
    if len(text.encode('utf-8')) > 32 * 1024 * 1024:
        raise ValueError('collector output exceeds 32 MiB')
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError('collector returned a non-object')
    return payload, completed.returncode


def normalize_bing_crawl(prop, raw, code):
    """Normalize BWT GetCrawlIssues into the measured-zero-vs-missing convention.

    'ok' with issues == [] means we successfully queried Bing and it reported no
    crawl issues (a genuine measured zero). 'failed' means we could not obtain
    evidence at all (missing, not zero) — the two must never be conflated.
    """
    if code != 0 or raw.get('error'):
        return {'provider': 'bing_webmaster', 'property': prop, 'status': 'failed',
                'error': raw.get('error') or 'non-zero exit from bing_webmaster.py crawl',
                'issues': None, 'issue_count': None, 'coverage': {'complete': False}}
    payload = raw.get('d')
    if payload is None:
        payload = []
    if not isinstance(payload, list):
        return {'provider': 'bing_webmaster', 'property': prop, 'status': 'failed',
                'error': 'unexpected Bing crawl-issue response shape', 'issues': None,
                'issue_count': None, 'coverage': {'complete': False}}
    issues = [{'url': item.get('Url'), 'issue_type': item.get('IssueType') or item.get('ImgKey'),
               'severity': item.get('Severity'), 'detected': item.get('DetectedDate') or item.get('CrawlDate')}
              for item in payload]
    return {'provider': 'bing_webmaster', 'property': prop, 'status': 'ok', 'error': None,
            'issues': issues, 'issue_count': len(issues),
            'measured_zero': len(issues) == 0,
            'coverage': {'complete': True, 'scope': 'crawl issues Bing has recorded for this verified property'}}


def backlink_targets(site):
    values = site.get('backlink_targets') or ['https://' + site['domain'] + '/']
    if not isinstance(values, list) or not 1 <= len(values) <= 100:
        raise ValueError('backlink_targets must contain 1..100 owned URLs')
    return sorted({owned_url(site, url) for url in values})


def collect(root, lane: str, *, days: int = 28, max_pages: int = 100,
            timeout: int = 180) -> dict:
    if not 1 <= days <= 3650 or not 1 <= max_pages <= 1000 or not 1 <= timeout <= 1800:
        raise ValueError('collection bounds exceeded')
    site = load(root)
    authorize(site, lane)
    url = 'https://' + site['domain'] + '/'
    host_args = [part for name in site_hosts(site) for part in ('--host', name)]
    data, state, error = {}, 'failed', None
    try:
        with tempfile.TemporaryDirectory(prefix='seo-collect-') as td:
            output = Path(td) / 'result.json'
            if lane in {'gsc', 'gsc_ranks', 'gsc_appearance'}:
                args = ['gsc_query_v2.py', '--property', property_for(site, 'gsc'), '--days', str(days), *host_args]
                if lane == 'gsc_ranks':
                    args += ['--dimensions', 'query,country,device']
                elif lane == 'gsc_appearance':
                    # The Search Analytics API rejects grouping searchAppearance with any
                    # other dimension ("Cannot group by search appearance dimension
                    # together with another dimension") — it must be queried alone.
                    args += ['--dimensions', 'searchAppearance']
            elif lane == 'ga4':
                args = ['ga4_report.py', '--property', property_for(site, 'ga4'), '--days', str(days), '--json', *host_args]
            elif lane == 'bing':
                args = ['bing_webmaster.py', 'traffic', '--site', property_for(site, 'bing')]
            elif lane == 'crux_history':
                args = ['crux_history.py', url, '--origin', '--json']
            elif lane == 'pagespeed':
                args = ['pagespeed_check.py', url, '--strategy', 'mobile', '--json']
            elif lane == 'serp':
                from serp_collect import collect as collect_serp
                data = collect_serp(root)
                state = data['status']
                error = None if state == 'ok' else 'controlled SERP collection is partial; inspect receipts'
                args = None
            elif lane == 'audit':
                args = ['site_audit.py', '--url', url, '--max', str(max_pages), '--json', str(output)]
            elif lane == 'gsc_sitemaps':
                args = ['gsc_query.py', 'sitemaps', '--property', property_for(site, 'gsc')]
            elif lane == 'gsc_inspect_bulk':
                gsc_prop = property_for(site, 'gsc')
                hosts = set(site_hosts(site))
                top_urls = []
                try:
                    top_raw, top_code = run_json(root, ['gsc_query_v2.py', '--property', gsc_prop,
                        '--days', str(days), '--dimensions', 'page', '--limit', '1000', *host_args], timeout)
                    if top_code == 0 and not top_raw.get('error'):
                        ranked = sorted(top_raw.get('rows', []), key=lambda r: r.get('impressions', 0), reverse=True)
                        top_urls = [r['page'] for r in ranked if r.get('page')]
                except (subprocess.TimeoutExpired, ValueError, OSError):
                    top_urls = []
                sitemap_urls_found = []
                try:
                    import site_audit
                    origin = url.rstrip('/')
                    _, _, robots_txt, _ = site_audit.get(origin + '/robots.txt')
                    found = set()
                    for sm in site_audit.discover_sitemaps(origin, robots_txt):
                        found |= site_audit.sitemap_urls(sm)
                    sitemap_urls_found = sorted(found)
                except Exception:
                    sitemap_urls_found = []

                import urllib.parse as _up

                def in_scope(u):
                    return _up.urlsplit(u).netloc.lower() in hosts
                inspect_cap = site.get('inspect_max_urls', 20)
                if type(inspect_cap) is not int or not 1 <= inspect_cap <= 2000:
                    raise ValueError('inspect_max_urls must be 1..2000 (bounded by the GSC daily quota)')
                ordered = list(dict.fromkeys([u for u in top_urls if in_scope(u)] +
                                             [u for u in sitemap_urls_found if in_scope(u)]))
                targets = ordered[:inspect_cap]
                with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as fh:
                    fh.write('\n'.join(targets))
                    batch_file = fh.name
                try:
                    if targets:
                        raw, code = run_json(root, ['gsc_inspect.py', '--batch', batch_file,
                            '--site-url', gsc_prop, '--delay', '1.0', '--json'], timeout)
                    else:
                        raw, code = {'results': [], 'summary': {'pass': 0, 'fail': 0, 'neutral': 0, 'error': 0},
                                     'error': None}, 0
                finally:
                    Path(batch_file).unlink(missing_ok=True)
                data = {'property': gsc_prop, 'error': raw.get('error'), 'results': raw.get('results', []),
                        'summary': raw.get('summary'),
                        'candidate_sources': {'from_top_impression_pages': len(top_urls),
                            'from_sitemap': len(sitemap_urls_found), 'considered_in_scope': len(ordered),
                            'inspected': len(targets), 'inspect_max_urls': inspect_cap,
                            'daily_quota_note': 'GSC URL Inspection allows 2000/day, 600/min per site'}}
                bad_bulk = bool(raw.get('error')) or code != 0
                state = 'partial' if bad_bulk else 'ok'
                error = 'URL Inspection batch failed or incomplete' if bad_bulk else None
                args = None
            elif lane == 'sitemap_probe':
                # Read-only: does the live site itself serve a sitemap? Never submits to GSC.
                import site_audit
                origin = url.rstrip('/')
                robots_code, _, robots_txt, _ = site_audit.get(origin + '/robots.txt')
                robots_sitemap_lines = [m.strip() for m in re.findall(
                    r'^\s*Sitemap\s*:\s*(\S+)\s*$', robots_txt or '', re.I | re.M)]
                probe_code, _, _, probe_headers = site_audit.get(origin + '/sitemap.xml')
                data = {'url': origin, 'robots_status': robots_code,
                        'robots_declares_sitemap': len(robots_sitemap_lines) > 0,
                        'robots_sitemap_urls': robots_sitemap_lines,
                        'default_sitemap_xml_status': probe_code,
                        'default_sitemap_xml_reachable': probe_code == 200,
                        'measured_zero': robots_code == 200 and not robots_sitemap_lines and probe_code != 200}
                state = 'ok' if robots_code in (200, 404) else 'partial'
                error = None if state == 'ok' else f'robots.txt fetch returned status {robots_code}'
                args = None
            elif lane == 'bing_crawl':
                prop = property_for(site, 'bing')
                try:
                    raw, code = run_json(root, ['bing_webmaster.py', 'crawl', '--site', prop], timeout)
                except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
                    raw, code = {'error': type(exc).__name__, 'method': 'GetCrawlIssues'}, 1
                data = normalize_bing_crawl(prop, raw, code)
                state = data['status']
                error = None if state == 'ok' else data.get('error') or 'crawl issues collection failed or incomplete'
                args = None
            elif lane == 'backlinks':
                targets = backlink_targets(site)  # Validate the entire scope before any request.
                link_pages = site.get('backlink_max_pages', 20)
                if type(link_pages) is not int or not 1 <= link_pages <= 100:
                    raise ValueError('backlink_max_pages must be 1..100 per target')
                prop, start = property_for(site, 'bing'), time.monotonic()
                data = {'provider': 'bing_webmaster', 'property': prop, 'targets': targets,
                        'rows': [], 'target_results': [], 'status': 'ok',
                        'scope': json.dumps(targets, separators=(',', ':')), 'coverage': {'complete': True}}
                for target in targets:
                    remaining = timeout - (time.monotonic() - start)
                    if remaining <= 0:
                        result, code = {'status': 'failed', 'error': 'batch deadline exceeded'}, 1
                    else:
                        try:
                            result, code = run_json(root, ['bing_webmaster.py', 'links', '--site', prop,
                                '--url', target, '--max-pages', str(link_pages)], remaining)
                        except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
                            result, code = {'status': 'failed', 'error': type(exc).__name__}, 1
                    if result.get('property') not in (None, prop) or result.get('target') not in (None, target):
                        result, code = {'error': 'provider target mismatch'}, 1
                    target_ok = not code and not result.get('error') and result.get('status') == 'ok'
                    coverage = result.get('coverage') or {}
                    data['target_results'].append({'target': target, 'status': 'ok' if target_ok else 'failed',
                        'coverage': coverage, 'error': result.get('error')})
                    for row in result.get('rows', []):
                        if row.get('target_url') != target:
                            raise ValueError('backlink response crossed target scope')
                        data['rows'].append(row)
                    if not target_ok or coverage.get('complete') is not True:
                        data['coverage']['complete'] = False
                        data['status'] = 'partial'
                data['coverage'].update(targets_requested=len(targets),
                    targets_succeeded=sum(x['status'] == 'ok' for x in data['target_results']),
                    scope='configured target URLs in Bing; not a web-wide census')
                state = data['status']
                error = None if state == 'ok' else 'some backlink targets failed or reached the configured cap'
                args = None
            else:
                raise ValueError('unknown collector lane')
            if args:
                data, code = run_json(root, args, timeout, output)
                if lane in {'gsc', 'gsc_ranks', 'gsc_appearance', 'ga4'}:
                    provider = 'gsc' if lane.startswith('gsc') else 'ga4'
                    expected = property_for(site, provider).removeprefix('properties/')
                    if str(data.get('property') or '').removeprefix('properties/') != expected:
                        raise ValueError('collector property response mismatch')
                if lane == 'ga4':
                    sanity, sanity_code = run_json(root,
                        ['ga4_report.py', '--property', property_for(site, 'ga4'), '--report', 'sanity',
                         '--days', '7', '--json'], timeout)
                    expected_ga4 = property_for(site, 'ga4').removeprefix('properties/')
                    if str(sanity.get('property') or '').removeprefix('properties/') == expected_ga4:
                        data['all_channels_sanity'] = sanity
                    else:
                        data['all_channels_sanity'] = {'error': 'sanity property response mismatch'}
                bad = data.get('error') or data.get('pages_error') or data.get('status') in {'fail', 'failed', 'partial', 'error'}
                if lane in {'gsc', 'gsc_ranks', 'gsc_appearance'}:
                    bad = bad or data.get('coverage', {}).get('hit_client_cap') is True
                if lane == 'gsc_sitemaps' and property_for(site, 'gsc') != str(data.get('property') or ''):
                    raise ValueError('collector property response mismatch')
                if lane == 'audit':
                    usable = any(x.get('status') == 200 for x in data.get('pages', {}).values())
                    bad = bad or not usable or data.get('coverage', {}).get('collection_failures', 0) > 0
                else:
                    bad = bad or code != 0
                state = 'partial' if bad else 'ok'
                error = 'collector failed or returned incomplete evidence' if bad else None
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        state, error = 'failed', type(exc).__name__
    return {'schema_version': 2, 'site': site['domain'], 'lane': lane,
            'collected_at': datetime.now(timezone.utc).isoformat(), 'status': state, 'error': error,
            'data': data, 'hostname_scope': site_hosts(site), 'collection_route': 'standalone_direct',
            'scope': 'owned site; unavailable data is not zero'}


def persist_observations(root, envelope, snapshot):
    """Wire collected evidence into the same history consumed by reports and CLI."""
    lane, data = envelope['lane'], envelope.get('data') or {}
    if lane == 'gsc_ranks':
        from rank_tracker import ingest
        rows = [dict(row, market=row.get('country') or 'not-reported', language='not-reported',
                     device=row.get('device') or 'all', observed_url=None)
                for row in data.get('rows', []) if envelope.get('status') == 'ok' and
                isinstance(row.get('position'), (int, float)) and row['position'] >= 1]
        # Search Console does not report query language or a single precise SERP position.
        path = ingest(root, rows, {'provider': 'google_gsc', 'observation_type': 'gsc_average_position',
            'market': 'not-reported', 'language': 'not-reported', 'collected_at': envelope['collected_at'],
            'snapshot': snapshot, 'status': envelope.get('status', 'failed'),
            'measurement': measurement_context(envelope), 'coverage': data.get('coverage')})
        return {'rank_snapshot': str(path)}
    if lane == 'serp' and data.get('rows'):
        from rank_tracker import ingest
        path = ingest(root, data['rows'], {'provider': 'dataforseo', 'snapshot': snapshot})
        return {'rank_snapshot': str(path)}
    if lane == 'backlinks' and envelope.get('status') in {'ok', 'partial'} and 'rows' in data:
        from backlink_tracker import ingest
        path = ingest(root, data, 'bing_webmaster', data['scope'], snapshot=snapshot)
        return {'backlink_snapshot': str(path)}
    return {}
