"""Bounded, site-bound collection into typed evidence envelopes."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urljoin, urldefrag
from urllib.robotparser import RobotFileParser
from seo_io import fetch, digest

HERE = Path(__file__).resolve().parent

def stamp():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def redact(text):
    for name, value in os.environ.items():
        if len(value) >= 6 and any(x in name.upper() for x in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY')):
            text = text.replace(value, '[REDACTED]')
    return text

def run_json(argv, *, root, timeout=180, payload=None):
    """Trusted argv only. stdout/stderr are bounded in files, not held without limits."""
    import tempfile
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            done = subprocess.run(argv, input=json.dumps(payload).encode() if payload is not None else None,
                stdout=output, stderr=errors, cwd=root, timeout=timeout, shell=False, env={**os.environ, 'PYTHONIOENCODING':'utf-8', 'PYTHONUTF8':'1'})
        except subprocess.TimeoutExpired:
            return {'status': 'failed', 'error': 'adapter timeout; reconcile before retrying any mutation', 'timed_out': True}
        except OSError as exc:
            return {'status': 'unconfigured', 'error': f'adapter unavailable ({type(exc).__name__})'}
        output.seek(0); errors.seek(0)
        raw, err = output.read(16 * 1024 * 1024 + 1), errors.read(65536)
    if len(raw) > 16 * 1024 * 1024:
        return {'status': 'failed', 'error': 'adapter output exceeded limit', 'exit_code': done.returncode}
    try:
        result = json.loads(redact(raw.decode('utf-8')))
        if not isinstance(result, dict):
            raise ValueError('object required')
    except (ValueError, UnicodeError):
        return {'status': 'failed', 'error': 'adapter did not emit one JSON object', 'exit_code': done.returncode,
                'stderr': redact(err.decode('utf-8', 'replace'))}
    if done.returncode:
        result.setdefault('error', f'adapter exited {done.returncode}')
        result['status'] = 'failed'
    if result.get('error') and result.get('status') not in ('partial','unconfigured','unauthorized'):
        result['status'] = 'failed'
    result['exit_code'] = done.returncode
    return result

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a' and dict(attrs).get('href'):
            self.urls.append(dict(attrs)['href'])

def crawl(site, maximum=100):
    from site_audit import parse
    base = site['base_url']
    allowed = set(site['allowed_hosts'])
    maximum = min(max(1, maximum), int(site.get('policy', {}).get('max_pages', 300)))
    pages, issues, errors, seen, queue = [], [], [], set(), [base]
    robots = RobotFileParser()
    robots_url = urljoin(base, '/robots.txt')
    response = fetch(robots_url, allowed)
    if response['status'] == 200:
        robots.parse(response['body'].decode('utf-8', 'replace').splitlines())
    elif response['status'] in (404, 410):
        robots.parse([])
    else:
        return {'status': 'failed', 'error': 'robots.txt unavailable; crawl not authorized by readable policy', 'http_status': response['status']}
    # XML discovery is bounded separately; target URLs are filtered before fetch.
    import xml.etree.ElementTree as ET
    maps = robots.site_maps() or [urljoin(base, '/sitemap.xml')]
    map_seen = set()
    sitemap_urls = set()
    for _ in range(20):
        if not maps:
            break
        sm = maps.pop(0)
        if sm in map_seen or urlsplit(sm).hostname not in allowed:
            continue
        map_seen.add(sm)
        try:
            data = fetch(sm, allowed)
            if data['status'] != 200:
                continue
            tree = ET.fromstring(data['body'])
            locs = [n.text.strip() for n in tree.iter() if n.tag.split('}')[-1] == 'loc' and n.text]
            if tree.tag.split('}')[-1] == 'sitemapindex':
                maps.extend(locs[:20])
            else:
                sitemap_urls.update(u for u in locs if urlsplit(u).hostname in allowed)
        except Exception as exc:
            errors.append({'url': sm, 'error': type(exc).__name__})
    queue.extend(sorted(sitemap_urls)[:maximum])
    edges = []
    while queue and len(pages) < maximum:
        url = urldefrag(queue.pop(0))[0]
        if url in seen or urlsplit(url).hostname not in allowed:
            continue
        seen.add(url)
        if not robots.can_fetch('SEO', url):
            issues.append({'id': digest(['robots', url]), 'severity': 'high', 'target': url, 'observed': 'robots_disallowed', 'state': 'not_testable'})
            continue
        try:
            data = fetch(url, allowed)
            html = data['body'].decode('utf-8', 'replace')
            signals, _ = parse(html)
            item = {'url': url, 'final_url': data['url'], 'status': data['status'], 'sha256': digest(data['body']), **signals}
            pages.append(item)
            conditions = []
            if data['status'] >= 400: conditions.append(('http_error', 'critical'))
            if signals.get('noindex') or 'noindex' in data['headers'].get('x-robots-tag', '').lower(): conditions.append(('noindex', 'high'))
            if not signals.get('title'): conditions.append(('missing_title', 'medium'))
            if not signals.get('canonical'): conditions.append(('missing_canonical', 'medium'))
            if not signals.get('meta_desc'): conditions.append(('missing_description', 'low'))
            if not signals.get('h1'): conditions.append(('missing_h1', 'medium'))
            elif len(signals['h1']) > 1: conditions.append(('multiple_h1', 'low'))
            if signals.get('mixed_content'): conditions.append(('mixed_content', 'high'))
            if signals.get('img_no_alt', 0): conditions.append(('image_alt_missing', 'medium'))
            if not signals.get('viewport'): conditions.append(('missing_viewport', 'medium'))
            if signals.get('canonical') and urljoin(data['url'], signals['canonical']) != data['url']:
                conditions.append(('canonical_differs_review_intent', 'medium'))
            if len(data['chain']) > 1: conditions.append(('redirected_url', 'low'))
            for rule, severity in conditions:
                issues.append({'id': digest([rule, url]), 'severity': severity, 'target': url, 'observed': rule, 'state': 'observed'})
            parser = Links(); parser.feed(html)
            for href in parser.urls:
                target = urldefrag(urljoin(data['url'], href))[0]
                if urlsplit(target).scheme in ('http', 'https') and urlsplit(target).hostname in allowed:
                    edges.append({'from': url, 'to': target})
                    if target not in seen and len(queue) < maximum * 10:
                        queue.append(target)
        except Exception as exc:
            errors.append({'url': url, 'error': type(exc).__name__})
    from collections import defaultdict
    for field in ('title', 'meta_desc'):
        groups = defaultdict(list)
        for page in pages:
            if page.get(field): groups[page[field]].append(page['url'])
        for value, urls in groups.items():
            if len(urls) > 1:
                for url in urls:
                    issues.append({'id': digest(['duplicate_' + field, url]), 'severity': 'medium', 'target': url,
                        'observed': 'duplicate_' + field, 'state': 'observed', 'same_value_urls': urls})
    fetched = {p['url']: p for p in pages}
    for edge in edges:
        target = fetched.get(edge['to'])
        if target and target['status'] >= 400:
            issues.append({'id': digest(['broken_internal_link', edge]), 'severity': 'high', 'target': edge['from'],
                'observed': 'broken_internal_link', 'state': 'observed', 'link_target': edge['to'], 'http_status': target['status']})
    return {'status': 'partial' if errors or queue or maps else 'ok', 'pages': pages, 'issues': issues,
        'errors': errors, 'edges': edges, 'coverage': {'pages_fetched': len(pages), 'budget': maximum,
        'discovered_sitemap_urls': len(sitemap_urls), 'remaining_queue': len(queue), 'site_complete': False},
        'note': 'Bounded raw HTML crawl. Rendering, field performance and indexation are separate evidence.'}

def collect(root, site, provider, options=None):
    options = options or {}
    properties = site.get('properties') or {}
    command = [sys.executable]
    if provider in ('gsc', 'gsc_ranks'):
        prop = properties.get('gsc')
        if not prop: return {'status': 'unconfigured', 'error': 'GSC property mapping missing'}
        command += [str(HERE / 'gsc_query_v2.py'), '--property', prop, '--days', str(options.get('days', 28)), '--max-rows', str(min(int(options.get('max_rows', 25000)), 100000)), '--page-prefix', site['base_url']]
        if provider == 'gsc_ranks':
            command += ['--dimensions', 'query']
    elif provider == 'ga4':
        prop = properties.get('ga4')
        if not prop: return {'status': 'unconfigured', 'error': 'GA4 property mapping missing'}
        command += [str(HERE / 'ga4_report.py'), '--property', str(prop), '--days', str(options.get('days', 28)), '--hostname', site['domain'], '--json']
    elif provider == 'bing_links':
        prop = properties.get('bing')
        if not prop: return {'status': 'unconfigured', 'error': 'Bing site mapping missing'}
        target = options.get('target', site['base_url'])
        if urlsplit(target).hostname not in site['allowed_hosts']:
            raise ValueError('backlink target is outside site')
        command += [str(HERE / 'bing_webmaster.py'), 'links', '--site', prop, '--url', target, '--max-pages', str(min(int(options.get('max_pages', 10)), 100))]
    elif provider == 'crawl':
        result = crawl(site, int(options.get('max_pages', 100)))
        return envelope(site, provider, result)
    elif provider == 'pagespeed':
        command += [str(HERE / 'pagespeed_check.py'), '--url', site['base_url'], '--json']
    else:
        raise ValueError('unsupported built-in collector; register a trusted adapter for this provider')
    return envelope(site, provider, run_json(command, root=root))

def envelope(site, provider, data):
    if provider == 'pagespeed':
        lanes = list((data.get('psi') or {}).values())
        if data.get('crux') is not None: lanes.append(data['crux'])
        failures = [lane.get('error') for lane in lanes if isinstance(lane, dict) and lane.get('error')]
        if failures:
            data['status'] = 'partial' if len(failures) < len(lanes) else 'failed'
            data['error'] = 'One or more performance evidence lanes failed'
            data['lane_errors'] = failures
    status = data.get('status', 'failed' if data.get('error') else 'ok')
    if data.get('error') and status == 'ok': status = 'failed'
    return {'schema_version': 1, 'site': site['domain'], 'provider': provider, 'collected_at': stamp(),
        'status': status, 'data': data, 'digest': digest(data), 'runtime_verified': not bool(data.get('error')),
        'source': 'owned-site first-party or local evidence', 'not_a_ranking_outcome': True}
