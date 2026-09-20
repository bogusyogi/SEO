"""Public HTML and image-byte verification, not a browser-render or search-outcome claim."""
from __future__ import annotations
import hashlib
from html.parser import HTMLParser
import json
import re
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

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in {'script', 'style', 'template', 'noscript'}:
            self.hidden.append(tag)
            if tag == 'script' and a.get('type', '').lower() == 'application/ld+json':
                self.json_script = True; self.script = []
        if tag == 'link' and 'canonical' in a.get('rel', '').lower().split():
            self.canonical.append(a.get('href', ''))
        if tag == 'meta':
            if a.get('name', '').lower() in {'robots', 'googlebot', 'bingbot'}:
                self.robots.append(a.get('content', ''))
            if a.get('property', '').lower() == 'og:image':
                self.og.append(a.get('content', ''))
        if tag == 'img':
            self.images.append(a)

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'template', 'noscript'} and tag in self.hidden:
            self.hidden.remove(tag)
        if tag == 'script' and self.json_script:
            try:
                self.ld.append(json.loads(''.join(self.script)))
            except ValueError:
                self.ld.append({'invalid_jsonld': True})
            self.json_script = False

    def handle_data(self, data):
        if self.json_script:
            self.script.append(data)
        if not self.hidden:
            self.text.append(data)


def normalize(url):
    return url.rstrip('/')


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
        result = {'passed': all(assertions.values()) and all(a['passed'] for a in assets),
            'url': response['url'], 'assertions': assertions, 'media': assets,
            'body_sha256': queue.digest(response['body'].encode('utf-8')),
            'scope': 'public HTTP HTML, visible text, canonical/indexability directives and exact image bytes; not JavaScript/browser rendering or SEO outcome'}
        row['verification'] = result
        row['status'] = 'deployed_verified' if result['passed'] else 'applied'
        atomic_json(queue.item_path(root, task_id), row)
        return result
