#!/usr/bin/env python3
"""Bing Webmaster evidence client. URL backlinks are paginated, scoped evidence.

GetUrlLinks: https://learn.microsoft.com/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi.geturllinks
No claim of complete web-wide backlink coverage is made. Submission requires
explicit CLI authority and is never performed by a read-only collection.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

BASE = 'https://ssl.bing.com/webmaster/api.svc/json'
MAX_BYTES = 16 * 1024 * 1024
SUBCOMMANDS = {'traffic': 'GetRankAndTrafficStats', 'queries': 'GetQueryStats',
               'pages': 'GetPageStats', 'crawl': 'GetCrawlIssues'}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None

def call(method: str, params: dict | None = None, body: dict | None = None) -> dict:
    key = os.environ.get('BING_API_KEY')
    if not key:
        return {'error': 'BING_API_KEY is not configured', 'status': 'unconfigured', 'method': method}
    query = {'apikey': key, **(params or {})}
    request = Request(f'{BASE}/{method}?{urlencode(query)}',
        data=json.dumps(body).encode() if body is not None else None,
        headers={'User-Agent': 'SEO/0.2', 'Content-Type': 'application/json; charset=utf-8'},
        method='POST' if body is not None else 'GET')
    try:
        with build_opener(NoRedirect).open(request, timeout=30) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return {'error': 'provider response exceeds size limit', 'method': method, 'status': 'failed'}
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise ValueError('expected provider object')
        value = parsed.get('d', parsed)
        if isinstance(value, dict) and ('ErrorCode' in value or 'error' in value):
            return {'error': 'provider returned a fault', 'method': method, 'status': 'failed'}
        return {'method': method, 'd': value, 'error': None}
    except HTTPError as exc:
        return {'error': f'HTTP {exc.code}', 'http_status': exc.code, 'method': method,
                'status': 'unauthorized' if exc.code in (401, 403) else 'failed'}
    except Exception as exc:
        # Do not print exception URLs: the provider puts its API key in the query.
        return {'error': f'provider transport/format failure ({type(exc).__name__})',
                'method': method, 'status': 'failed'}

def url_links(site: str, link: str, max_pages: int = 100) -> dict:
    a, b = urlsplit(site), urlsplit(link)
    if a.scheme not in ('https', 'http') or a.netloc != b.netloc or b.scheme not in ('https', 'http'):
        raise ValueError('backlink target must belong to the verified site host')
    if a.username or b.username or not a.hostname or not 1 <= max_pages <= 32767:
        raise ValueError('invalid URL or pagination budget')
    if a.path.rstrip('/') and not (b.path == a.path.rstrip('/') or b.path.startswith(a.path.rstrip('/') + '/')):
        raise ValueError('backlink target is outside verified site path')
    rows, seen, total_pages = [], set(), None
    result = {'provider': 'bing_webmaster', 'property': site, 'target': link, 'rows': rows,
              'status': 'partial', 'complete': False, 'pages_fetched': 0, 'error': None,
              'coverage_note': 'Bing observations for this target only, not all links on the web'}
    for page in range(max_pages):
        response = call('GetUrlLinks', {'siteUrl': site, 'link': link, 'page': page})
        if response.get('error'):
            result.update(error=response['error'], status='partial' if page else response.get('status', 'failed'))
            break
        data = response.get('d')
        if not isinstance(data, dict) or not isinstance(data.get('Details'), list):
            result['error'] = 'unsupported backlink response shape'
            break
        count = data.get('TotalPages')
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            result['error'] = 'missing or invalid TotalPages; coverage cannot be certified'
            break
        if total_pages is not None and count != total_pages:
            result['error'] = 'pagination changed during collection; retry a fresh snapshot'
            break
        total_pages = count
        result['pages_fetched'] += 1
        for item in data['Details']:
            source = item.get('Url') if isinstance(item, dict) else None
            if not source:
                result['error'] = 'malformed backlink item'
                continue
            anchor = item.get('AnchorText', '')
            identity = (source, link, anchor)
            if identity not in seen:
                seen.add(identity)
                rows.append({'source_url': source, 'target_url': link, 'anchor': anchor, 'provider': 'bing_webmaster'})
        if page + 1 >= total_pages:
            result['complete'] = not bool(result['error'])
            result['status'] = 'ok' if result['complete'] else 'partial'
            break
    result['total_pages'] = total_pages
    if not result['complete'] and not result['error']:
        result['error'] = 'pagination budget reached'
    return result

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=[*SUBCOMMANDS, 'links', 'submit'])
    ap.add_argument('--site', required=True)
    ap.add_argument('--url', help='required target URL for links or submit')
    ap.add_argument('--max-pages', type=int, default=100)
    ap.add_argument('--authorize-write', action='store_true')
    ap.add_argument('--json', dest='out', help='optional JSON output filename')
    args = ap.parse_args()
    if args.command == 'links':
        if not args.url:
            ap.error('links requires --url; this API is per URL, not a whole-site backlink report')
        result = url_links(args.site, args.url, args.max_pages)
    elif args.command == 'submit':
        if not args.url or not args.authorize_write:
            ap.error('submit requires --url and --authorize-write')
        if urlsplit(args.site).netloc != urlsplit(args.url).netloc:
            ap.error('submission URL must belong to the site')
        result = call('SubmitUrl', body={'siteUrl': args.site, 'url': args.url})
    else:
        result = call(SUBCOMMANDS[args.command], {'siteUrl': args.site})
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(text + '\n', encoding='utf-8')
    print(text)
    return 1 if result.get('error') else 0

if __name__ == '__main__':
    raise SystemExit(main())
