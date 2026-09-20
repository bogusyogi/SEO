"""Reviewed immutable site media, published in the same Git tree as its page.

Supports PNG/JPEG/WebP header inspection without installing a decoder. Does not
fetch arbitrary local paths from a model response, generate images or purchase assets.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from seo_state import atomic_json, state_dir, transaction_lock
from site_policy import load, authorize
from content_queue import target_path, replace_bytes
from measurement_scope import owned_url

MAX_BYTES = 4 * 1024 * 1024


def dimensions(raw):
    if raw[:8] == b'\x89PNG\r\n\x1a\n' and len(raw) >= 33 and raw[12:16] == b'IHDR':
        fmt, (width, height) = 'png', struct.unpack('>II', raw[16:24])
    elif raw[:2] == b'\xff\xd8':
        fmt, width, height, offset = 'jpeg', 0, 0, 2
        while offset + 4 <= len(raw):
            if raw[offset] != 255:
                raise ValueError('malformed JPEG marker')
            marker = raw[offset+1]; offset += 2
            if marker == 255:
                offset -= 1; continue
            if marker in {0xD8, 0xD9, 0xDA}:
                break
            size = int.from_bytes(raw[offset:offset+2], 'big')
            if size < 2 or offset+size > len(raw):
                raise ValueError('malformed JPEG segment')
            if marker in {0xC0, 0xC1, 0xC2} and size >= 8:
                height, width = struct.unpack('>HH', raw[offset+3:offset+7]); break
            offset += size
    elif len(raw) >= 30 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        fmt = 'webp'
        if raw[12:16] == b'VP8X':
            width = 1+int.from_bytes(raw[24:27], 'little'); height = 1+int.from_bytes(raw[27:30], 'little')
        elif raw[12:16] == b'VP8 ' and raw[23:26] == b'\x9d\x01\x2a':
            width, height = (v & 0x3FFF for v in struct.unpack('<HH', raw[26:30]))
        elif raw[12:16] == b'VP8L' and raw[20] == 0x2F:
            bits = int.from_bytes(raw[21:25], 'little'); width, height = 1+(bits & 0x3FFF), 1+((bits>>14) & 0x3FFF)
        else:
            raise ValueError('unsupported WebP header')
    else:
        raise ValueError('only PNG, JPEG and WebP media are supported')
    if not 1 <= width <= 20000 or not 1 <= height <= 20000 or width*height > 80000000:
        raise ValueError('invalid/oversized image dimensions')
    return {'format': fmt, 'width': width, 'height': height}


def asset_path(root, identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', identifier):
        raise ValueError('invalid media ID')
    return state_dir(root)/'media'/(identifier+'.json')


def stage(root, identifier, source, *, path, public_url, alt, license_ref, role='featured'):
    site = load(root)
    if role not in {'featured', 'inline'}:
        raise ValueError('media role must be featured or inline')
    authorize(site, 'media', path=path, url=public_url)
    owned_url(site, public_url)
    target_path(root, path)
    if not isinstance(alt, str) or not alt.strip() or len(alt) > 1000 or not isinstance(license_ref, str) or not license_ref.strip():
        raise ValueError('descriptive alt text and actual license/provenance reference required')
    src = Path(source)
    if src.is_symlink() or not src.is_file() or src.stat().st_size > MAX_BYTES:
        raise ValueError('bounded regular media file required')
    raw = src.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError('media exceeded size limit')
    info = dimensions(raw); sha = hashlib.sha256(raw).hexdigest()
    extension = Path(path).suffix.lower()
    if extension not in {'png': {'.png'}, 'jpeg': {'.jpg', '.jpeg'}, 'webp': {'.webp'}}[info['format']]:
        raise ValueError('media format and repository extension disagree')
    manifest = asset_path(root, identifier)
    row = {'id': identifier, 'site': site['domain'], 'path': path, 'public_url': public_url,
           'alt': alt, 'license_ref': license_ref, 'role': role, 'sha256': sha, 'byte_count': len(raw), **info}
    with transaction_lock(state_dir(root)/'media'):
        if manifest.exists():
            if read(root, identifier) != row:
                raise ValueError('media ID is immutable; use a new ID')
            return row
        replace_bytes(state_dir(root)/'media'/(sha+'.bin'), raw)
        atomic_json(manifest, row)
    return row


def read(root, identifier):
    row = json.loads(asset_path(root, identifier).read_text(encoding='utf-8'))
    site = load(root)
    if row.get('id') != identifier or row.get('site') != site['domain'] or not re.fullmatch('[a-f0-9]{64}', row.get('sha256', '')):
        raise ValueError('media identity mismatch')
    authorize(site, 'media', path=row['path'], url=row['public_url'])
    owned_url(site, row['public_url']); target_path(root, row['path'])
    data_path = state_dir(root)/'media'/(row['sha256']+'.bin')
    if data_path.is_symlink() or data_path.stat().st_size > MAX_BYTES:
        raise ValueError('invalid media material')
    raw = data_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != row['sha256'] or len(raw) != row['byte_count'] or any(row.get(k) != v for k, v in dimensions(raw).items()):
        raise ValueError('staged media changed')
    return row


def bytes_for(root, identifier):
    row = read(root, identifier)
    return (state_dir(root)/'media'/(row['sha256']+'.bin')).read_bytes()


def main():
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument('--root', default='.')
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('stage'); p.add_argument('id'); p.add_argument('--source', required=True)
    p.add_argument('--path', required=True); p.add_argument('--url', required=True)
    p.add_argument('--alt', required=True); p.add_argument('--license-ref', required=True)
    p.add_argument('--role', choices=['featured', 'inline'], default='featured')
    p = sub.add_parser('inspect'); p.add_argument('id')
    a = ap.parse_args()
    result = read(a.root, a.id) if a.command == 'inspect' else stage(a.root, a.id, a.source,
        path=a.path, public_url=a.url, alt=a.alt, license_ref=a.license_ref, role=a.role)
    print(json.dumps(result, indent=2)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
