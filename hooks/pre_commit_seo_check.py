#!/usr/bin/env python3
"""Validate staged HTML-like blobs using the shared schema validator.

Run from the site repository, not the SEO package. No working-tree substitutions:
partially staged files are checked exactly as they would enter the commit.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

EXTENSIONS = {'.html', '.htm', '.php', '.jsx', '.tsx', '.vue', '.svelte', '.ejs'}


def staged_checks(root: str | Path = '.') -> dict:
    root = Path(root).resolve()
    listed = subprocess.run(
        ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACM', '-z'],
        cwd=root, capture_output=True, check=False,
    )
    if listed.returncode:
        return {'status': 'failed', 'error': 'cannot read Git index', 'checked': 0}
    spec = importlib.util.spec_from_file_location(
        'seo_staged_schema', Path(__file__).with_name('validate-schema.py'))
    if spec is None or spec.loader is None:
        raise RuntimeError('packaged schema validator is unavailable')
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    errors = []
    checked = 0
    for raw in listed.stdout.split(b'\0'):
        if not raw:
            continue
        name = raw.decode('utf-8', errors='surrogateescape')
        if Path(name).suffix.lower() not in EXTENSIONS:
            continue
        blob = subprocess.run(
            ['git', 'show', ':' + name], cwd=root, capture_output=True, check=False)
        if blob.returncode:
            errors.append({'path': name, 'error': 'cannot read staged blob'})
            continue
        try:
            text = blob.stdout.decode('utf-8-sig')
        except UnicodeDecodeError:
            errors.append({'path': name, 'error': 'staged content is not UTF-8'})
            continue
        checked += 1
        errors.extend({'path': name, 'error': error}
                      for error in validator.validate_jsonld(text))
    return {'status': 'failed' if errors else 'ok', 'checked': checked,
            'errors': errors, 'scope': 'staged JSON-LD validation; not a full SEO audit'}


def main() -> int:
    try:
        result = staged_checks()
    except (OSError, RuntimeError) as exc:
        result = {'status': 'failed', 'error': str(exc), 'checked': 0}
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'ok' else 2


if __name__ == '__main__':
    raise SystemExit(main())
