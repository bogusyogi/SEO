"""Small authenticated JSON transport: explicit TLS origin, DNS pinning, no redirects."""
from __future__ import annotations
import json
from urllib.parse import urlsplit
from safe_http import public_address, PinnedHTTPS


def request(origin, method, path, *, headers=None, payload=None, timeout=30):
    p = urlsplit(origin)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443) or p.path not in ('', '/') or p.query or p.fragment:
        raise ValueError('an explicit HTTPS API origin without path/userinfo is required')
    if method not in {'GET', 'POST', 'PATCH'} or not path.startswith('/') or path.startswith('//') or any(ord(c) < 32 for c in path):
        raise ValueError('invalid API request')
    raw = json.dumps(payload, allow_nan=False).encode('utf-8') if payload is not None else None
    if raw and len(raw) > 1024 * 1024:
        raise ValueError('API payload exceeds 1 MiB')
    hs = {'Accept': 'application/json', 'Content-Type': 'application/json', 'Accept-Encoding': 'identity'}
    hs.update(headers or {})
    if any('\r' in str(v) or '\n' in str(v) for v in hs.values()):
        raise ValueError('invalid request header')
    hs['Host'] = p.netloc
    conn = PinnedHTTPS(p.hostname, public_address(p.hostname, 443), 443, min(max(timeout, 1), 60))
    try:
        conn.request(method, path, body=raw, headers=hs)
        response = conn.getresponse()
        body = response.read(5 * 1024 * 1024 + 1)
        if len(body) > 5 * 1024 * 1024:
            raise ValueError('API response exceeds 5 MiB')
        if not 200 <= response.status < 300:
            # Never follow redirects carrying a session token.
            raise RuntimeError('API request failed: HTTP ' + str(response.status))
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError('API response must be an object')
        return result
    finally:
        conn.close()
