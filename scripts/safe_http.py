"""Bounded public HTTP reads, with DNS-pinned connections and redirect revalidation.

Intentionally ignores proxy environment variables. No private-network opt-out: use a
separate trusted local test adapter for staging rather than weakening production reads.
"""
from __future__ import annotations
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit, urljoin

MAX_BYTES = 5 * 1024 * 1024


def public_address(host: str, port: int) -> str:
    if not host or host.lower() == 'localhost' or host.lower().endswith(('.localhost', '.local')):
        raise ValueError('private/local targets are not allowed')
    addresses = sorted({info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError('target resolves to a non-public address')
    return addresses[0]


def validate_url(url: str):
    p = urlsplit(url)
    if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password:
        raise ValueError('public http(s) URL without userinfo required')
    if any(ord(ch) < 32 for ch in url):
        raise ValueError('control character in URL')
    port = p.port or (443 if p.scheme == 'https' else 80)
    if port not in {80, 443}:
        raise ValueError('only public web ports 80/443 are allowed')
    return p, port


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, port, timeout):
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def fetch(url: str, *, method: str = 'GET', max_bytes: int = MAX_BYTES,
          timeout: float = 20, redirects: int = 5, headers: dict | None = None) -> dict:
    if method not in {'GET', 'HEAD'} or not 0 < max_bytes <= MAX_BYTES:
        raise ValueError('invalid bounded read')
    current = url
    chain = []
    for step in range(redirects + 1):
        p, port = validate_url(current)
        address = public_address(p.hostname, port)
        conn = (PinnedHTTPS(p.hostname, address, port, timeout) if p.scheme == 'https'
                else http.client.HTTPConnection(address, port=port, timeout=timeout))
        request_headers = {'Host': p.netloc, 'User-Agent': 'SEO/0.2 (+owned-site-audit)',
                           'Accept-Encoding': 'identity'}
        request_headers.update(headers or {})
        # Caller cannot alter routing or smuggle credentials to redirected hosts.
        request_headers['Host'] = p.netloc
        if step:
            request_headers.pop('Authorization', None)
            request_headers.pop('Cookie', None)
        try:
            conn.request(method, (p.path or '/') + ('?' + p.query if p.query else ''), headers=request_headers)
            response = conn.getresponse()
            hs = {k.lower(): v for k, v in response.getheaders()}
            status = response.status
            if status in {301, 302, 303, 307, 308} and hs.get('location') and redirects:
                chain.append({'url': current, 'status': status})
                if step == redirects:
                    raise ValueError('redirect limit exceeded')
                current = urljoin(current, hs['location'])
                continue
            body = response.read(max_bytes + 1) if method != 'HEAD' else b''
            if len(body) > max_bytes:
                raise ValueError('response body limit exceeded')
            if hs.get('content-encoding', 'identity') not in {'identity', ''}:
                raise ValueError('server ignored identity encoding; compressed response not decoded')
            return {'url': current, 'requested_url': url, 'status': status,
                    'headers': hs, 'body': body.decode('utf-8', 'replace'), 'redirects': chain}
        finally:
            conn.close()
    raise ValueError('redirect loop')
