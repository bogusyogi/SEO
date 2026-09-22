"""Site-specific execution scope. Configuration is operator-owned, never fetched-page input."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlsplit
from seo_project import load_site

READ_ACTIONS = {'audit', 'gsc', 'ga4', 'bing', 'backlinks', 'rank', 'report', 'verify', 'gsc_ranks', 'serp'}
CONTENT_ACTIONS = {'draft', 'publish', 'outreach', 'campaign'}


def host(value: str) -> str:
    p = urlsplit(value if '://' in value else 'https://' + value)
    if p.username or p.password or not p.hostname:
        raise ValueError('invalid site identity')
    return p.hostname.lower().rstrip('.')


def load(root: str | Path) -> dict:
    site = load_site(root)
    if not site.get('domain'):
        raise ValueError('site is not configured; run project setup first')
    domain = host(site['domain'])
    policy = site.get('policy') or {}
    mode = policy.get('mode', 'read_only')
    # Preserve the historical passive-only boundary unless the operator explicitly
    # records a replacement policy with an approval reference.
    if domain.removeprefix('www.') == 'stunningstrangers.com' and not policy.get('restriction_override_approval'):
        mode = 'technical_only'
    if mode not in {'read_only', 'technical_only', 'approved'}:
        raise ValueError('unknown site policy mode')
    return {**site, 'domain': domain, 'policy': {**policy, 'mode': mode}}


def authorize(site: dict, action: str, *, url: str | None = None, path: str | None = None) -> None:
    if action == 'cms_read':
        raise PermissionError('direct backend access is not an SEO capability')
    policy = site['policy']
    allowed_hosts = {site['domain'], *(host(x) for x in policy.get('allowed_hosts', []))}
    if url and host(url) not in allowed_hosts:
        raise PermissionError('target is outside configured site hosts')
    if action in READ_ACTIONS:
        return
    if policy['mode'] == 'technical_only' and action in CONTENT_ACTIONS:
        raise PermissionError('technical-only site prohibits content/acquisition actions')
    if policy['mode'] == 'read_only' or not policy.get('approval_ref'):
        raise PermissionError('writes require an operator-approved site policy')
    if action not in policy.get('allowed_actions', []):
        raise PermissionError('action is not allowed by site policy')
    if path is not None:
        p = Path(path)
        if p.is_absolute() or '..' in p.parts or not p.parts or any(x.startswith('.') for x in p.parts):
            raise PermissionError('unsafe publication path')
        prefixes = policy.get('write_prefixes') or []
        if not any(p.as_posix().startswith(str(x).rstrip('/') + '/') for x in prefixes):
            raise PermissionError('path is not under an approved write prefix')


def property_for(site: dict, provider: str) -> str:
    value = str((site.get('properties') or {}).get(provider) or '')
    if not value:
        raise ValueError(f'{provider} property mapping is missing')
    if provider == 'gsc':
        target = value.removeprefix('sc-domain:')
        # A domain property may cover a configured subdomain, never an unrelated site.
        if not (site['domain'] == host(target) or value.startswith('sc-domain:') and site['domain'].endswith('.' + host(target))):
            raise PermissionError('GSC property does not cover this site')
    if provider == 'gsc' and not value.startswith('sc-domain:'):
        base_url = site.get('base_url') or 'https://' + site['domain'] + '/'
        if not base_url.startswith(value):
            raise PermissionError('URL-prefix property does not cover the configured base URL')
    if provider == 'ga4' and not value.removeprefix('properties/').isdigit():
        raise ValueError('GA4 requires the numeric property ID, not a measurement ID')
    if provider == 'bing' and host(value) != site['domain']:
        raise PermissionError('Bing property must match site')
    return value
