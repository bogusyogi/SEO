"""Configuration discovery is separate from observed live property access."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
from seo_runtime import load_site
from seo_collect import collect, stamp

def doctor(root, live=False, providers=None):
    site = load_site(root)
    from google_auth import load_config, TOKEN_PATH
    config = load_config()
    sa = config.get('service_account_path')
    oauth = config.get('oauth_client_path')
    candidates = [Path(os.path.expanduser(p)) for p in (sa, oauth) if p]
    credential_state = 'unconfigured'
    if candidates:
        credential_state = 'configured' if all(p.is_file() for p in candidates) else 'broken_configuration'
    if Path(TOKEN_PATH).is_file():
        credential_state = 'configured' if oauth and Path(os.path.expanduser(oauth)).is_file() else 'broken_configuration'
    result = {'site': site['domain'], 'checked_at': stamp(), 'live_checks': live,
              'google_credentials': credential_state, 'secrets_exposed': False, 'providers': {},
              'scope': 'credential presence is not authentication; only live reads prove access at check time'}
    for provider, mapping in (('gsc', 'gsc'), ('ga4', 'ga4'), ('bing_links', 'bing')):
        configured = bool(site.get('properties', {}).get(mapping)) and (bool(os.environ.get('BING_API_KEY')) if provider == 'bing_links' else credential_state == 'configured')
        entry = {'state': 'configured' if configured else 'unconfigured', 'runtime_verified': False,
                 'property_mapped': bool(site.get('properties', {}).get(mapping))}
        if live and (providers is None or provider in providers):
            observation = collect(root, site, provider, {'days': 7, 'max_rows': 10, 'max_pages': 1})
            data = observation.get('data', observation)
            good = not data.get('error')
            entry.update(state='authorized_read_succeeded' if good else 'live_read_failed',
                         runtime_verified=good, evidence=observation)
        result['providers'][provider] = entry
    result['status'] = 'partial' if any(not x['runtime_verified'] for x in result['providers'].values()) else 'ok'
    return result
