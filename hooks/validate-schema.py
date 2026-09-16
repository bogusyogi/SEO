#!/usr/bin/env python3
"""JSON-LD validation for files or hook event JSON on stdin.

PostToolUse supplies feedback AFTER an edit, not a transactional edit veto.
Use the same validator before publishing. Valid Schema.org vocabulary and Google
rich-result eligibility are distinct: HowTo/FAQPage are not syntax errors.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

class Blocks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active = False
        self.parts = []
        self.blocks = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'script':
            self.active = dict(attrs).get('type', '').lower() == 'application/ld+json'
            self.parts = []
    def handle_data(self, data):
        if self.active:
            self.parts.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == 'script' and self.active:
            self.blocks.append(''.join(self.parts))
            self.active = False

def _validate_schema_object(obj, block_num, inherited_context=False):
    errors = []
    prefix = f'Block {block_num}'
    if not isinstance(obj, dict):
        return [f'{prefix}: JSON-LD node must be an object']
    context = obj.get('@context')
    has_context = inherited_context or context is not None
    if not has_context:
        errors.append(f'{prefix}: missing @context')
    if '@graph' in obj:
        graph = obj['@graph']
        if not isinstance(graph, list):
            errors.append(f'{prefix}: @graph must be an array')
        else:
            for node in graph:
                errors.extend(_validate_schema_object(node, block_num, has_context))
    elif not obj.get('@type') and not obj.get('@id'):
        errors.append(f'{prefix}: node needs @type or @id')
    kind = obj.get('@type')
    if kind is not None and not (isinstance(kind, str) and kind or isinstance(kind, list) and kind and all(isinstance(x, str) and x for x in kind)):
        errors.append(f'{prefix}: @type must be a nonempty string or string array')
    if re.search(r'\[(?:INSERT|Business Name|City|State|Phone|Address|Your[^\]]*|URL|Email)\]|\bREPLACE_ME\b', json.dumps(obj), re.I):
        errors.append(f'{prefix}: unresolved placeholder')
    return errors

def validate_jsonld(content: str) -> list[str]:
    parser = Blocks()
    parser.feed(content)
    errors = []
    for number, raw in enumerate(parser.blocks, 1):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f'Block {number}: invalid JSON at line {exc.lineno}, column {exc.colno}')
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            errors.extend(_validate_schema_object(node, number))
    return errors

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('file', nargs='?')
    ap.add_argument('--require-schema', action='store_true')
    args = ap.parse_args()
    filename = args.file
    if not filename:
        try:
            event = json.load(sys.stdin)
        except (ValueError, OSError):
            print('Schema hook: invalid or missing event JSON', file=sys.stderr)
            return 2
        filename = (event.get('tool_input') or {}).get('file_path')
        if not filename:
            return 0  # a non-file tool event
    path = Path(filename)
    if path.suffix.lower() not in {'.html', '.htm', '.jsx', '.tsx', '.vue', '.svelte', '.php', '.ejs', '.mdx'}:
        return 0
    try:
        content = path.read_text(encoding='utf-8')
    except OSError:
        print('Schema validation: target is unreadable', file=sys.stderr)
        return 2
    errors = validate_jsonld(content)
    parser = Blocks()
    parser.feed(content)
    if args.require_schema and not parser.blocks:
        errors.append('Required JSON-LD was not found in rendered HTML')
    if errors:
        print(json.dumps({'status': 'fail', 'errors': errors, 'scope': 'JSON-LD structure, not rich-result eligibility'}))
        return 2
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
