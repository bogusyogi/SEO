"""Portable local I/O and bounded public HTTP. No agent-framework dependencies."""
from __future__ import annotations
import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urljoin

MAX_BYTES = 8 * 1024 * 1024

def digest(value) -> str:
    data = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()

def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def confined(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts:
        raise ValueError('path must be relative and contained in project')
    root = root.resolve()
    path = root
    for component in rel.parts:
        path = path / component
        if path.is_symlink():
            raise ValueError('symlinked paths are not permitted for managed state or edits')
    if not path.resolve().is_relative_to(root):
        raise ValueError('path escapes project')
    return path

def public_target(url: str, allowed_hosts: set[str]) -> tuple:
    p = urlsplit(url)
    if p.scheme not in {'https', 'http'} or not p.hostname or p.username or p.password:
        raise ValueError('only unauthenticated HTTP(S) target URLs are accepted')
    host = p.hostname.encode('idna').decode().lower().rstrip('.')
    if host not in {x.lower().rstrip('.') for x in allowed_hosts}:
        raise ValueError('URL host is outside the explicit site allowlist')
    port = p.port or (443 if p.scheme == 'https' else 80)
    if port not in {80, 443}:
        raise ValueError('only public web ports 80/443 are allowed')
    addresses = list(dict.fromkeys(x[4][0] for x in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError('private, loopback, link-local, reserved and mixed DNS targets are forbidden')
    return p, host, port, addresses

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self.address = address
    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)

class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout)
        self.address = address
    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)

def fetch(url: str, allowed_hosts: set[str], *, method='GET', redirects=5, limit=MAX_BYTES, follow_redirects=True) -> dict:
    """Pin validated DNS to the connection; revalidate every redirect. No cookies/proxy auth."""
    if method not in ('GET', 'HEAD'):
        raise ValueError('public evidence fetch is read-only')
    chain = []
    for hop in range(redirects + 1):
        p, host, port, addresses = public_target(url, allowed_hosts)
        conn = (PinnedHTTPS if p.scheme == 'https' else PinnedHTTP)(host, port, addresses[0], 20)
        try:
            target = (p.path or '/') + ('?' + p.query if p.query else '')
            conn.request(method, target, headers={'User-Agent': 'SEO/0.2 (+owned-site evidence)', 'Accept-Encoding': 'identity'})
            response = conn.getresponse()
            headers = {k.lower(): v for k, v in response.getheaders()}
            code = response.status
            body = b'' if method == 'HEAD' else response.read(limit + 1)
            if len(body) > limit:
                raise ValueError('response exceeds configured byte limit')
        finally:
            conn.close()
        chain.append({'url': url, 'status': code})
        if follow_redirects and code in (301, 302, 303, 307, 308) and headers.get('location'):
            if hop == redirects:
                raise ValueError('redirect budget exhausted')
            url = urljoin(url, headers['location'])
            continue
        return {'url': url, 'status': code, 'headers': headers, 'body': body, 'chain': chain}
    raise ValueError('redirect budget exhausted')
