#!/usr/bin/env python3
"""JSON-LD syntax/structure gate. PostToolUse reports after an edit; it cannot undo it.

CLI usage: python validate-schema.py page.html (exit 2 on malformed markup).
Hook usage: read standard tool_input.file_path from JSON on stdin.
Schema.org vocabulary validity and Google rich-result eligibility are different questions.
"""
from __future__ import annotations
import argparse
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

class Blocks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False); self.active=False; self.parts=[]; self.blocks=[]
    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'script':
            self.active = dict(attrs).get('type','').lower() == 'application/ld+json'
            if self.active: self.parts=[]
    def handle_data(self, data):
        if self.active: self.parts.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == 'script' and self.active:
            self.blocks.append(''.join(self.parts)); self.active=False


def validate_jsonld(content: str) -> list[str]:
    parser=Blocks(); parser.feed(content)
    errors=[]
    if parser.active: errors.append('Unterminated JSON-LD script')
    for n, raw in enumerate(parser.blocks,1):
        try:
            value=json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        except (ValueError,TypeError) as exc:
            errors.append(f'Block {n}: Invalid JSON: {exc}'); continue
        values=value if isinstance(value,list) else [value]
        for obj in values:
            if not isinstance(obj,dict):
                errors.append(f'Block {n}: JSON-LD node must be an object'); continue
            context=obj.get('@context')
            if context is None: errors.append(f'Block {n}: Missing @context')
            elif not isinstance(context,(str,dict,list)): errors.append(f'Block {n}: Invalid @context')
            nodes=obj.get('@graph',[obj])
            if not isinstance(nodes,list):
                errors.append(f'Block {n}: @graph must be an array'); continue
            for node in nodes:
                if not isinstance(node,dict): errors.append(f'Block {n}: graph node must be an object'); continue
                kind=node.get('@type')
                if kind is None and not node.get('@id'): errors.append(f'Block {n}: node needs @type or @id')
                elif kind is not None and not (isinstance(kind,str) or isinstance(kind,list) and all(isinstance(x,str) for x in kind)):
                    errors.append(f'Block {n}: Invalid @type')
            for token in ('[Business Name]','[INSERT','[URL]','REPLACE_ME'):
                if token.lower() in raw.lower(): errors.append(f'Block {n}: unresolved placeholder {token}')
    return errors


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('path',nargs='?')
    args=parser.parse_args(argv)
    event={}
    if not args.path:
        try: event=json.load(sys.stdin)
        except (ValueError,OSError):
            print('Schema hook: expected event JSON or a file path',file=sys.stderr); return 2
        args.path=(event.get('tool_input') or {}).get('file_path')
        if not args.path: return 0  # Event is not an applicable file operation.
    path=Path(args.path)
    if path.suffix.lower() not in {'.html','.htm','.jsx','.tsx','.vue','.svelte','.php','.ejs'}: return 0
    try: errors=validate_jsonld(path.read_text(encoding='utf-8'))
    except (OSError,UnicodeError) as exc:
        print(f'Schema validation unavailable: {type(exc).__name__}',file=sys.stderr); return 2
    if errors:
        print(json.dumps({'status':'fail','path':str(path),'errors':errors,'phase':'post_edit' if event else 'gate'}))
        return 2
    print(json.dumps({'status':'pass','path':str(path),'scope':'JSON-LD syntax and basic structure only; not rich-result eligibility'}))
    return 0

if __name__ == '__main__': raise SystemExit(main())
