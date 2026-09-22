"""Public HTML and image-byte verification, not a browser-render or search-outcome claim."""
from __future__ import annotations
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
import content_queue as queue
import media_assets
from safe_http import fetch
from seo_state import atomic_json, transaction_lock, state_dir
from site_policy import load, authorize


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.canonical, self.robots, self.images, self.og, self.ld = [], [], [], [], [], []
        self.hidden = []; self.json_script = False; self.script = []
        self.titles, self.descriptions, self.headings = [], [], []
        self.links = []
        self.capture = None
        self.capture_text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a' and a.get('href'):
            self.links.append(a['href'])
        if tag in {'title', 'h1'}:
            self.capture, self.capture_text = tag, []
        if tag in {'head', 'script', 'style', 'template', 'noscript'}:
            self.hidden.append(tag)
            if tag == 'script' and a.get('type', '').lower() == 'application/ld+json':
                self.json_script = True; self.script = []
        if tag == 'link' and 'canonical' in a.get('rel', '').lower().split():
            self.canonical.append(a.get('href', ''))
        if tag == 'meta':
            if a.get('name', '').lower() == 'description':
                self.descriptions.append(a.get('content', ''))
            if a.get('name', '').lower() in {'robots', 'googlebot', 'bingbot'}:
                self.robots.append(a.get('content', ''))
            if a.get('property', '').lower() == 'og:image':
                self.og.append(a.get('content', ''))
        if tag == 'img':
            self.images.append(a)

    def handle_endtag(self, tag):
        if tag == self.capture:
            value = whitespace(''.join(self.capture_text))
            (self.titles if tag == 'title' else self.headings).append(value)
            self.capture, self.capture_text = None, []
        if tag in {'head', 'script', 'style', 'template', 'noscript'} and tag in self.hidden:
            self.hidden.remove(tag)
        if tag == 'script' and self.json_script:
            try:
                self.ld.append(json.loads(''.join(self.script)))
            except ValueError:
                self.ld.append({'invalid_jsonld': True})
            self.json_script = False

    def handle_data(self, data):
        if self.capture:
            self.capture_text.append(data)
        if self.json_script:
            self.script.append(data)
        if not self.hidden:
            self.text.append(data)


def normalize(url):
    return url.rstrip('/')


def whitespace(value):
    return re.sub(r'\s+', ' ', value).strip()


def metadata_assertions(content, baseline, observed):
    """Compare rendered metadata with approved literal HTML, including removals.

    This supports literal HTML metadata in native source; dynamically generated
    metadata still requires a separately qualified rendering contract.
    """
    intended, previous = Page(), Page()
    intended.feed(content)
    previous.feed(baseline or '')
    checks = {}
    for name in ('titles', 'descriptions', 'headings'):
        expected = [whitespace(x) for x in getattr(intended, name)]
        old = getattr(previous, name)
        if expected or old:
            checks['approved_' + name] = [whitespace(x) for x in getattr(observed, name)] == expected
    return checks


CHECK_KINDS = {'title', 'description', 'h1', 'text', 'link', 'sitemap_url', 'robots_rule'}


def validate_contract(root, plan, target):
    """Bind native-source checks to exact proposed files and owned public URLs."""
    checks = plan.get('verification', [])
    if not isinstance(checks, list) or len(checks) > 30:
        raise ValueError('verification must be a list of at most 30 assertions')
    sources = {plan['path']: plan['content']}
    sources.update({x['path']: x['content'] for x in plan.get('supporting_changes', [])})
    site = load(root)
    covered = set()
    for check in checks:
        if not isinstance(check, dict) or set(check) != {'path', 'url', 'kind', 'value'}:
            raise ValueError('verification requires path, url, kind and value')
        if check['path'] not in sources or check['kind'] not in CHECK_KINDS:
            raise ValueError('verification source or kind is unsupported')
        if not isinstance(check['value'], str) or not check['value'].strip() or len(check['value']) > 10000:
            raise ValueError('verification requires bounded nonempty value')
        if check['value'] not in sources[check['path']]:
            raise ValueError('verification value must occur in its approved source file')
        authorize(site, 'verify', url=check['url'])
        from safe_http import validate_url
        validate_url(check['url'])
        covered.add(check['path'])
    if any(x['path'] not in covered for x in plan.get('supporting_changes', [])):
        raise ValueError('each supporting file requires an explicit public verification assertion')
    if Path(plan['path']).suffix.lower() not in {'.html', '.htm'} and plan['path'] not in covered:
        raise ValueError('native source requires an explicit rendered verification assertion')
    return checks


def check_response(check, response):
    if response['status'] != 200 or normalize(response['url']) != normalize(check['url']):
        return False
    page = Page(); page.feed(response['body'])
    kind, value = check['kind'], check['value']
    if kind == 'title': return page.titles == [whitespace(value)]
    if kind == 'description': return [whitespace(x) for x in page.descriptions] == [whitespace(value)]
    if kind == 'h1': return page.headings == [whitespace(value)]
    if kind == 'text': return whitespace(value) in whitespace(' '.join(page.text))
    if kind == 'link': return value in [urljoin(response['url'], x) for x in page.links]
    if kind == 'robots_rule':
        return value.strip() in [line.split('#', 1)[0].strip() for line in response['body'].splitlines()]
    try:
        document = ET.fromstring(response['body'])
    except ET.ParseError:
        return False
    return value in [element.text for element in document.iter() if element.tag.rsplit('}', 1)[-1] == 'loc']


def article_images(value):
    result = []
    if isinstance(value, list):
        for item in value: result.extend(article_images(item))
    elif isinstance(value, dict):
        kinds = value.get('@type', [])
        if isinstance(kinds, str): kinds = [kinds]
        if set(kinds) & {'Article', 'BlogPosting', 'NewsArticle'}:
            images = value.get('image', [])
            if not isinstance(images, list): images = [images]
            for image in images:
                if isinstance(image, str): result.append(image)
                elif isinstance(image, dict): result.append(image.get('url') or image.get('contentUrl') or '')
        result.extend(article_images(value.get('@graph', [])))
    return result


def verify(root, task_id, plan, *, fetcher=fetch):
    site = load(root)
    with transaction_lock(state_dir(root)/'queue'):
        row = json.loads(queue.item_path(root, task_id).read_text(encoding='utf-8'))
        queue.check_binding(row, site)
        if queue.digest(row['content'].encode('utf-8')) != row['content_sha256']:
            raise PermissionError('approved content material was altered')
        if 'content' in plan and plan['content'] != row['content']:
            raise PermissionError('verification plan does not match approved content')
        if row['site'] != site['domain'] or row['status'] not in {'applied', 'deployed_verified'}:
            raise ValueError('verification requires this site\'s exact applied content')
        expected = plan.get('expected_text')
        if not isinstance(expected, str) or not expected or expected not in row['content']:
            raise ValueError('assertion not bound to approved content')
        authorize(site, 'verify', url=row['url'])
        response = fetcher(row['url'])
        authorize(site, 'verify', url=response['url'])
        page = Page(); page.feed(response['body'])
        visible = re.sub(r'\s+', ' ', ' '.join(page.text)).strip()
        wanted = re.sub(r'\s+', ' ', expected).strip()
        directives = ','.join(page.robots+[response.get('headers', {}).get('x-robots-tag', '')]).lower()
        assertions = {'http_200': response['status'] == 200,
            'intended_url': normalize(response['url']) == normalize(row['url']),
            'visible_expected_text': wanted in visible,
            'canonical': len(page.canonical) == 1 and normalize(urljoin(response['url'], page.canonical[0])) == normalize(row['url']),
            'indexable_directives': not re.search(r'\b(noindex|none)\b', directives)}
        if Path(row['path']).suffix.lower() in {'.html', '.htm'}:
            assertions.update(metadata_assertions(row['content'], row.get('baseline'), page))
        explicit = []
        if plan.get('verification') or plan.get('supporting_changes'):
            for check in validate_contract(root, plan, row['url']):
                observed = response if check['url'] == row['url'] else fetcher(check['url'])
                authorize(site, 'verify', url=observed['url'])
                passed = check_response(check, observed)
                explicit.append({**check, 'passed': passed,
                                 'body_sha256': queue.digest(observed['body'].encode('utf-8'))})
        assets = []
        for identifier in plan.get('media_ids', []):
            asset = media_assets.read(root, identifier)
            tags = [a for a in page.images if urljoin(response['url'], a.get('src', '')) == asset['public_url']]
            attributes = any(a.get('alt') == asset['alt'] and a.get('width') == str(asset['width']) and
                             a.get('height') == str(asset['height']) for a in tags)
            featured = asset.get('role', 'featured') == 'featured'
            og = not featured or asset['public_url'] in [urljoin(response['url'], x) for x in page.og]
            ld = not featured or asset['public_url'] in [urljoin(response['url'], x) for value in page.ld for x in article_images(value)]
            observed = fetcher(asset['public_url'], binary=True)
            authorize(site, 'verify', url=observed['url'])
            raw = observed['body']
            binary_match = isinstance(raw, bytes) and hashlib.sha256(raw).hexdigest() == asset['sha256']
            result = {'id': identifier, 'role': asset.get('role', 'featured'), 'attributes': attributes, 'og_image': og, 'article_image': ld,
                      'http_200': observed['status'] == 200, 'approved_bytes': binary_match,
                      'intended_url': observed['url'] == asset['public_url']}
            result['passed'] = all(result[k] for k in ('attributes', 'og_image', 'article_image', 'http_200', 'approved_bytes', 'intended_url'))
            assets.append(result)
        result = {'passed': all(assertions.values()) and all(a['passed'] for a in assets) and all(x['passed'] for x in explicit),
            'url': response['url'], 'assertions': assertions, 'verification': explicit, 'media': assets,
            'body_sha256': queue.digest(response['body'].encode('utf-8')),
            'scope': 'public HTTP HTML, visible text, approved literal title/description/H1, canonical/indexability directives and exact image bytes; not JavaScript/browser rendering or SEO outcome'}
        row['verification'] = result
        row['status'] = 'deployed_verified' if result['passed'] else 'applied'
        atomic_json(queue.item_path(root, task_id), row)
        return result
