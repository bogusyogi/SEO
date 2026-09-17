"""Explicit measured-host scope, shared by first-party collectors (no SDK dependency)."""
from __future__ import annotations
import re
from urllib.parse import urlsplit


def hosts(values):
    result = []
    for value in values or []:
        if not isinstance(value, str) or not value or any(c in value for c in '/:@?#\\'):
            raise ValueError('measurement hosts must be bare hostnames')
        value = value.lower().rstrip('.')
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value) or '..' in value:
            raise ValueError('invalid measured hostname')
        if value not in result:
            result.append(value)
    return sorted(result)


def site_hosts(site):
    return hosts([site['domain'], *(site.get('policy', {}).get('allowed_hosts') or [])])


def gsc_host_filter(values):
    names = hosts(values)
    if not names:
        raise ValueError('at least one measured host required')
    return {'dimension': 'page', 'operator': 'includingRegex',
            'expression': '^https?://(' + '|'.join(re.escape(x) for x in names) + ')(/|$)'}


def owned_url(site, url):
    from site_policy import authorize
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('an owned HTTP(S) URL without credentials or fragment is required')
    authorize(site, 'audit', url=url)
    return url
