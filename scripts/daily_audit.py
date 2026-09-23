#!/usr/bin/env python3
"""Deterministic daily SEO audit across a portfolio.

Writes <reports>/audit-YYYY-MM-DD/findings.json (same finding contract as manual audits) plus a
short REPORT.md. Every check is mechanical; nothing here judges content quality. Finding ids are
stable (site:control:target) so consecutive days can be diffed and resolutions carried forward.

Checks per site:
  sitemap       child sitemaps reachable; URLs on foreign/placeholder hosts; count drop vs last audit
  pages         status, noindex, canonical present/self, missing/duplicate titles (capped sample)
  availability  Product schema availability vs live Vendure stock (when site.yaml has stock_api)
  duplicates    near-identical server HTML between sampled product pages
  indexing      latest gsc_inspect_bulk lane: sampled sitemap URLs Google hasn't indexed
  decay         GSC page impressions, last 28d vs previous 28d (needs Google credentials)
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seo_project import load_site  # noqa: E402

UA = 'Mozilla/5.0 (compatible; seo-daily-audit/1.0)'
PAGE_CAP = 60
SEV = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}


def fetch(url, timeout=25, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={'User-Agent': UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.geturl(), r.read(3_000_000).decode('utf-8', 'ignore')
    except urllib.error.HTTPError as e:
        return e.code, url, ''
    except Exception as e:  # network failure is evidence, not a crash
        return None, url, f'{type(e).__name__}: {e}'


def locs(xml):
    return [html.unescape(u.strip()) for u in re.findall(r'<loc>\s*([^<]+?)\s*</loc>', xml)]


def sitemap_urls(domain, hosts):
    status, _, body = fetch(f'https://{domain}/sitemap.xml')
    if status != 200:
        return None, [f'/sitemap.xml returned {status}']
    urls, problems = [], []
    if '<sitemapindex' in body:
        for child in locs(body)[:20]:
            st, _, cb = fetch(child)
            if st != 200:
                problems.append(f'child sitemap {child} returned {st}')
                continue
            urls += locs(cb)
    else:
        urls = locs(body)
    return urls, problems


def finding(site, control, target, severity, observed, recommendation, category='technical', status='fail', evidence=()):
    key = hashlib.sha1(f'{site}|{control}|{target}'.encode()).hexdigest()[:10]
    return {'id': f'{site.split(".")[0]}:{control}:{key}', 'site': site, 'control': control, 'category': category,
            'status': status, 'severity': severity, 'target': target, 'evidence': list(evidence), 'observed': observed,
            'hypothesis': '', 'recommendation': recommendation, 'confidence': 'high', 'limitations': []}


def page_facts(url):
    status, final, body = fetch(url)
    facts = {'url': url, 'status': status, 'final': final}
    if status != 200:
        return facts
    head = body[:200_000]
    t = re.search(r'<title[^>]*>(.*?)</title>', head, re.S)
    facts['title'] = html.unescape(t.group(1)).strip() if t else ''
    robots = re.search(r'<meta[^>]*name="robots"[^>]*content="([^"]*)"', head, re.I)
    facts['noindex'] = bool(robots and 'noindex' in robots.group(1).lower())
    # Attribute order varies (Qwik emits href before rel), so inspect each <link> tag whole.
    facts['canonical'] = None
    for tag in re.findall(r'<link[^>]*>', head, re.I):
        if re.search(r'rel="canonical"', tag, re.I):
            href = re.search(r'href="([^"]+)"', tag, re.I)
            facts['canonical'] = href.group(1) if href else None
            break
    avail = []
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', body, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for node in data if isinstance(data, list) else data.get('@graph', [data]) if isinstance(data, dict) else []:
            if isinstance(node, dict) and node.get('@type') == 'Product':
                offers = node.get('offers')
                for o in offers if isinstance(offers, list) else [offers] if offers else []:
                    if isinstance(o, dict) and o.get('availability'):
                        avail.append(str(o['availability']).rsplit('/', 1)[-1])
    facts['availability'] = avail
    text = re.sub(r'<[^>]+>', ' ', re.sub(r'<script.*?</script>|<style.*?</style>', '', body, flags=re.S)).lower()
    words = re.findall(r'[a-z]{3,}', text)
    facts['shingles'] = {hashlib.md5(' '.join(words[i:i + 3]).encode()).hexdigest()[:12] for i in range(len(words) - 2)}
    return facts


def vendure_expected(stock_api, slug):
    """stock_api is a shop-api URL, or 'ssh:<host>:<url>' when the API is only reachable on the server."""
    result = _vendure_stock(stock_api, slug, pre_order_field=True)
    # Stores without the isPreOrder custom field reject the whole query; retry without it.
    return result if result is not None else _vendure_stock(stock_api, slug, pre_order_field=False)


def _vendure_stock(stock_api, slug, pre_order_field):
    fields = 'stockLevel customFields { isPreOrder }' if pre_order_field else 'stockLevel'
    query = '{ product(slug: %s) { variants { %s } } }' % (json.dumps(slug), fields)
    payload = json.dumps({'query': query})
    if stock_api.startswith('ssh:'):
        import os
        import subprocess
        _, host, url = stock_api.split(':', 2)
        cmd = ['ssh', '-F', os.path.expanduser('~/.ssh/config.dd'), '-o', 'BatchMode=yes', host,
               'curl -s -X POST -H "Content-Type: application/json" --data-binary @- ' + url]
        try:
            done = subprocess.run(cmd, input=payload, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        status, body = (200 if done.returncode == 0 else None), done.stdout
    else:
        status, _, body = fetch(stock_api, data=payload.encode(), headers={'Content-Type': 'application/json'})
    if status != 200:
        return None
    try:
        variants = json.loads(body)['data']['product']['variants']
    except (ValueError, KeyError, TypeError):
        return None
    def qty(v):
        s = str(v.get('stockLevel') or '0')
        return 1 if s in ('IN_STOCK', 'LOW_STOCK') else int(s) if s.isdigit() else 0
    regular = any(qty(v) > 0 and not (v.get('customFields') or {}).get('isPreOrder') for v in variants)
    pre = any(qty(v) > 0 and (v.get('customFields') or {}).get('isPreOrder') for v in variants)
    return 'InStock' if regular else 'PreOrder' if pre else 'OutOfStock'


def latest_lane(root, lane):
    files = sorted((Path(root) / '.seo' / lane).glob('*.json'), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding='utf-8'))
    except ValueError:
        return None


def gsc_decay(prop, host_filter):
    try:
        from gsc_query_v2 import query
    except Exception:
        return None
    end = date.today() - timedelta(days=3)
    cur = query(prop, str(end - timedelta(days=27)), str(end), ['page'], 'web', 25000, 25000)
    prev = query(prop, str(end - timedelta(days=55)), str(end - timedelta(days=28)), ['page'], 'web', 25000, 25000)
    if cur.get('error') or prev.get('error'):
        return None
    c = {r['page']: r for r in cur.get('rows', []) if host_filter(r['page'])}
    p = {r['page']: r for r in prev.get('rows', []) if host_filter(r['page'])}
    return c, p


def audit_site(root, previous):
    site = load_site(root)
    domain = site['domain']
    hosts = {domain, f'www.{domain}'}
    out = []
    urls, problems = sitemap_urls(domain, hosts)
    for p in problems:
        out.append(finding(domain, 'sitemap-fetch', p.split(' returned')[0], 'high', p, 'Restore the sitemap endpoint.'))
    if urls is None:
        out.append(finding(domain, 'sitemap-fetch', '/sitemap.xml', 'critical', problems[0] if problems else 'unreachable',
                           'Restore /sitemap.xml.'))
        urls = []
    foreign = [u for u in urls if (urllib.parse.urlsplit(u).hostname or '') not in hosts]
    if foreign:
        out.append(finding(domain, 'sitemap-foreign-hosts', '/sitemap.xml', 'critical',
                           f'{len(foreign)} of {len(urls)} sitemap URLs are on other hosts, e.g. {foreign[0]}',
                           'Sitemaps must list only this site\'s canonical URLs (check build-generated sitemap files).'))
    prev_count = (previous or {}).get('sitemap_counts', {}).get(domain)
    if prev_count and urls and len(urls) < prev_count * 0.7:
        out.append(finding(domain, 'sitemap-count-drop', '/sitemap.xml', 'high',
                           f'Sitemap URLs fell {prev_count} -> {len(urls)} since the previous audit.',
                           'Check whether pages were removed on purpose or the sitemap generator regressed.'))
    own = [u for u in urls if u not in foreign]
    products = [u for u in own if re.search(r'/(products|shop)/[^/?#]+/?$', u)]
    sample = list(dict.fromkeys(products + own))[:PAGE_CAP]
    pages = [page_facts(u) for u in sample]
    titles = {}
    for f in pages:
        if f['status'] != 200:
            out.append(finding(domain, 'sitemap-url-status', f['url'], 'high', f'Sitemap URL returned {f["status"]}.',
                               'Fix the page or remove it from the sitemap.'))
            continue
        if f['noindex']:
            out.append(finding(domain, 'sitemap-url-noindex', f['url'], 'high', 'Sitemap URL carries noindex.',
                               'Remove noindex or drop the URL from the sitemap.'))
        canon = f.get('canonical')
        if not canon:
            out.append(finding(domain, 'canonical-missing', f['url'], 'medium', 'No canonical link in server HTML.',
                               'Emit a self-referencing canonical server-side.'))
        elif canon.rstrip('/') != f['url'].rstrip('/'):
            out.append(finding(domain, 'canonical-elsewhere', f['url'], 'medium', f'Canonical points to {canon}.',
                               'Confirm this URL should be in the sitemap if it canonicalises elsewhere.', status='partial'))
        if not f.get('title'):
            out.append(finding(domain, 'title-missing', f['url'], 'medium', 'Empty <title>.', 'Add a descriptive title.'))
        else:
            titles.setdefault(f['title'], []).append(f['url'])
    for title, group in titles.items():
        if len(group) > 1:
            out.append(finding(domain, 'title-duplicate', title, 'low', f'{len(group)} URLs share the title: {", ".join(group[:4])}',
                               'Give distinct pages distinct titles.', category='content', status='partial'))
    stock_api = site.get('stock_api')
    if stock_api:
        unreachable = []
        for f in pages:
            if f['status'] != 200 or not f.get('availability'):
                continue
            slug = f['url'].rstrip('/').rsplit('/', 1)[-1]
            expected = vendure_expected(stock_api, slug)
            if expected is None:
                unreachable.append(f['url'])
            elif expected not in f['availability']:
                out.append(finding(domain, 'schema-availability', f['url'], 'critical',
                                   f'Product schema says {"/".join(f["availability"])}; live stock implies {expected}.',
                                   'Make Product availability follow real stock.'))
        if unreachable:
            out.append(finding(domain, 'schema-availability', 'stock source', 'medium',
                               f'Live stock unreachable for {len(unreachable)} product pages; availability not verified.',
                               'Restore stock_api access for the audit.', status='not_testable'))
    prods = [f for f in pages if f['url'] in products and f.get('shingles')]
    for i, a in enumerate(prods):
        for b in prods[i + 1:]:
            overlap = len(a['shingles'] & b['shingles']) / max(1, min(len(a['shingles']), len(b['shingles'])))
            if overlap > 0.95:
                out.append(finding(domain, 'near-duplicate-html', f'{a["url"]} ~ {b["url"]}', 'low',
                                   f'Server HTML {overlap:.0%} identical.', 'Differentiate or consolidate if both should rank.',
                                   category='content', status='partial'))
    inspect = latest_lane(root, 'gsc_inspect_bulk')
    results = ((inspect or {}).get('data') or {}).get('results') or []
    states = {}
    for r in results:
        state = (r.get('index_status') or {}).get('coverage_state') or 'error'
        states.setdefault(state, []).append(r.get('url'))
    not_indexed = {s: u for s, u in states.items() if 'submitted and indexed' not in s.lower()}
    if results and not_indexed:
        n = sum(len(u) for u in not_indexed.values())
        sev = 'high' if n > len(results) / 2 else 'medium'
        detail = '; '.join(f'{s}: {len(u)}' for s, u in not_indexed.items())
        out.append(finding(domain, 'indexing-coverage', 'sampled sitemap URLs', sev,
                           f'{n} of {len(results)} inspected URLs not indexed ({detail}), inspected {(inspect or {}).get("collected_at", "")[:10]}.',
                           'Diagnose by state: unknown = discovery/links; discovered-not-crawled = priority/duplication; crawled-not-indexed = quality.',
                           evidence=['gsc_inspect_bulk lane']))
    prop = (site.get('properties') or {}).get('gsc')
    decay = gsc_decay(prop, lambda u: (urllib.parse.urlsplit(u).hostname or '') in hosts) if prop else None
    if decay:
        cur, prev = decay
        for url, p in prev.items():
            if p['impressions'] >= 200:
                c = cur.get(url, {'impressions': 0, 'clicks': 0})
                if c['impressions'] < p['impressions'] * 0.5:
                    out.append(finding(domain, 'page-decay', url, 'medium',
                                       f'Impressions {p["impressions"]:.0f} -> {c["impressions"]:.0f}, clicks {p["clicks"]:.0f} -> {c["clicks"]:.0f} (28d vs previous 28d).',
                                       'Check indexing, ranking and intent changes before editing.', category='content', status='partial'))
    # Conversion tracking is out of scope by owner decision (2026-09-23): SEO is judged on clicks/rankings.
    # No inbound-link control: Bing's GetUrlLinks/GetLinkCounts return empty even for damneddesigns.com,
    # which has known backlinks (2026-09-23), so an empty Bing result cannot distinguish "none" from "no data".
    return domain, out, own


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--portfolio', required=True)
    ap.add_argument('--reports-dir', required=True)
    ap.add_argument('--date', default=str(date.today()))
    args = ap.parse_args(argv)
    reports = Path(args.reports_dir)
    prev_dirs = sorted(d for d in reports.glob('audit-*') if d.name != f'audit-{args.date}' and (d / 'findings.json').exists())
    previous = json.loads((prev_dirs[-1] / 'findings.json').read_text(encoding='utf-8')) if prev_dirs else None
    prev_ids = {f['id']: f for f in (previous or {}).get('findings', [])}
    findings, counts, primary, url_sets, new_urls = [], {}, {}, {}, {}
    for root in json.loads(Path(args.portfolio).read_text(encoding='utf-8'))['roots']:
        try:
            domain, rows, own_urls = audit_site(Path(root), previous)
        except Exception as e:  # one site failing must not hide the others
            findings.append(finding(str(root), 'audit-error', str(root), 'high', f'{type(e).__name__}: {e}', 'Fix the audit input.'))
            continue
        counts[domain] = len(own_urls)
        url_sets[domain] = own_urls
        seen = set(((previous or {}).get('sitemap_urls') or {}).get(domain) or [])
        # No previous set = first run: nothing is "new" yet (avoids re-submitting whole sites).
        new_urls[domain] = [u for u in own_urls if seen and u not in seen]
        for r in rows:
            r['new'] = r['id'] not in prev_ids
        rows.sort(key=lambda r: SEV.get(r['severity'], 5))
        top = next((r for r in rows if r['status'] == 'fail'), None)
        primary[domain] = top['id'] if top else None
        findings += rows
    resolved = [dict(f, resolution='no_longer_detected') for fid, f in prev_ids.items()
                if ':' in fid and fid not in {f['id'] for f in findings}]
    out_dir = reports / f'audit-{args.date}'
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = {'audit_date': args.date, 'kind': 'daily_deterministic', 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
           'scope': 'portfolio', 'sitemap_counts': counts, 'sitemap_urls': url_sets, 'new_sitemap_urls': new_urls,
           'primary_action': primary, 'findings': findings,
           'resolved_since_previous': resolved}
    (out_dir / 'findings.json').write_text(json.dumps(doc, indent=1), encoding='utf-8')
    lines = [f'# Daily SEO audit {args.date}', '', '| Site | Critical | High | New | Primary |', '|---|---|---|---|---|']
    for domain in counts:
        rows = [f for f in findings if f['site'] == domain]
        lines.append(f"| {domain} | {sum(r['severity'] == 'critical' for r in rows)} | {sum(r['severity'] == 'high' for r in rows)} | "
                     f"{sum(r.get('new', False) for r in rows)} | {primary.get(domain) or '—'} |")
    lines += ['', f'Resolved since previous audit: {len(resolved)}']
    (out_dir / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'event': 'seo.daily_audit', 'date': args.date, 'findings': len(findings), 'resolved': len(resolved)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
