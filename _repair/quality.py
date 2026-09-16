"""Final source-only qualification edits; removed after successful tests."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent.parent

def edit(name,old,new):
    p=ROOT/name; t=p.read_text()
    if old not in t:
        if new in t: return
        raise ValueError('missing anchor '+name+': '+old[:90])
    p.write_text(t.replace(old,new))

# Generic bare dict has no MCP structured schema. Require a string-keyed JSON object.
edit('scripts/seo_mcp.py','from pathlib import Path','from pathlib import Path\nfrom typing import Any')
edit('scripts/seo_mcp.py','@server.tool()', '@server.tool(structured_output=True)')
edit('scripts/seo_mcp.py','-> dict:', '-> dict[str, Any]:')

# Read-only default OAuth scopes; existing broader grants are not revoked.
p=ROOT/'scripts/google_auth.py'; t=p.read_text()
a=t.index('OAUTH_SCOPES = ('); b=t.index('\nOAUTH_REDIRECT_URI',a)
t=t[:a]+'''OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/webmasters.readonly "
    "https://www.googleapis.com/auth/analytics.readonly"
)
'''+t[b:]
a=t.index('def _save_oauth_token('); b=t.index('\ndef _refresh_oauth_token(',a)
t=t[:a]+'''def _save_oauth_token(token_data: dict):
    """Atomically replace private token storage without world-readable intermediate files."""
    from seo_io import atomic_write
    from pathlib import Path
    directory = Path(TOKEN_PATH).parent
    directory.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        os.chmod(directory, 0o700)
    atomic_write(Path(TOKEN_PATH), (json.dumps(token_data, indent=2) + '\\n').encode())
    if os.name != 'nt':
        os.chmod(TOKEN_PATH, 0o600)

'''+t[b:]
t=t.replace('def main():\n', 'def main():\n    global OAUTH_SCOPES\n')
t=t.replace('    args = parser.parse_args()', '''    parser.add_argument('--allow-write-scopes', action='store_true', help='Explicit opt-in to Search Console/indexing write scopes during OAuth setup; not needed for reporting')
    args = parser.parse_args()
    if args.allow_write_scopes:
        OAUTH_SCOPES = OAUTH_SCOPES.replace('webmasters.readonly', 'webmasters') + ' https://www.googleapis.com/auth/indexing'
''')
t=t.replace('Google API credential management for Claude SEO', 'Google API credential management for SEO')
# Preserve only the literal legacy fallback; all setup guidance uses the neutral directory.
t=t.replace('mkdir -p ~/.config/claude-seo', 'mkdir -p ~/.config/seo')
t=t.replace('Save to ~/.config/claude-seo/google-api.json:', 'Save to ~/.config/seo/google-api.json:')
t=t.replace('   - Web Search Indexing API (for Indexing API)', '   - Optional: Indexing API only for eligible content and explicitly authorized submissions')
p.write_text(t)

# Compatibility ledger serializes load-modify-save across processes.
p=ROOT/'scripts/search_ops.py'; t=p.read_text()
old="    state = load_state(path)\n    fn = globals()[f\"cmd_{args.command.replace('-', '_')}\"]\n    result = fn(args, state)\n    if args.command != 'brief':\n        save_state(path, state)"
new="    from state_lock import state_lock\n    with state_lock(path):\n        state = load_state(path)\n        fn = globals()[f\"cmd_{args.command.replace('-', '_')}\"]\n        result = fn(args, state)\n        if args.command != 'brief':\n            save_state(path, state)"
assert old in t
t=t.replace(old,new)
anchor="    row = find_intervention(state, args.id)\n    if row.get('status') not in {'proposed', 'deployed'}:"
replacement="    row = find_intervention(state, args.id)\n    previous = row.get('deployment')\n    if previous and previous.get('idempotency_key') == args.idempotency_key:\n        if previous.get('identity') != args.identity or previous.get('effect_receipt') != args.effect_receipt:\n            raise SystemExit('conflicting deployment reuse of idempotency key')\n        return row\n    if previous:\n        raise SystemExit('deployment already recorded; create a new intervention for a new deployment')\n    if row.get('status') not in {'proposed', 'deployed'}:"
assert anchor in t
t=t.replace(anchor,replacement)
p.write_text(t)

# Keep all root metadata portable and honest about readiness.
p=ROOT/'agents/openai.yaml'
p.write_text((ROOT/'skills/seo/agents/openai.yaml').read_text())
# PageSpeed must not hide failure inside a nested PSI/CrUX result.
p=ROOT/'scripts/seo_collect.py';t=p.read_text()
old="    status = data.get('status', 'failed' if data.get('error') else 'ok')"
new="    if provider == 'pagespeed':\n        lanes = list((data.get('psi') or {}).values())\n        if data.get('crux') is not None: lanes.append(data['crux'])\n        failures = [lane.get('error') for lane in lanes if isinstance(lane, dict) and lane.get('error')]\n        if failures:\n            data['status'] = 'partial' if len(failures) < len(lanes) else 'failed'\n            data['error'] = 'One or more performance evidence lanes failed'\n            data['lane_errors'] = failures\n    status = data.get('status', 'failed' if data.get('error') else 'ok')"
assert old in t
t=t.replace(old,new)
# Stronger raw crawl findings without arbitrary Google ranking thresholds.
anchor="            for rule, severity in conditions:"
extra="""            if not signals.get('h1'): conditions.append(('missing_h1', 'medium'))
            elif len(signals['h1']) > 1: conditions.append(('multiple_h1', 'low'))
            if signals.get('mixed_content'): conditions.append(('mixed_content', 'high'))
            if signals.get('img_no_alt', 0): conditions.append(('image_alt_missing', 'medium'))
            if not signals.get('viewport'): conditions.append(('missing_viewport', 'medium'))
            if signals.get('canonical') and urljoin(data['url'], signals['canonical']) != data['url']:
                conditions.append(('canonical_differs_review_intent', 'medium'))
            if len(data['chain']) > 1: conditions.append(('redirected_url', 'low'))
            for rule, severity in conditions:"""
assert anchor in t
t=t.replace(anchor,extra)
anchor="    return {'status': 'partial' if errors or queue or maps else 'ok', 'pages': pages, 'issues': issues,"
extra="""    from collections import defaultdict
    for field in ('title', 'meta_desc'):
        groups = defaultdict(list)
        for page in pages:
            if page.get(field): groups[page[field]].append(page['url'])
        for value, urls in groups.items():
            if len(urls) > 1:
                for url in urls:
                    issues.append({'id': digest(['duplicate_' + field, url]), 'severity': 'medium', 'target': url,
                        'observed': 'duplicate_' + field, 'state': 'observed', 'same_value_urls': urls})
    fetched = {p['url']: p for p in pages}
    for edge in edges:
        target = fetched.get(edge['to'])
        if target and target['status'] >= 400:
            issues.append({'id': digest(['broken_internal_link', edge]), 'severity': 'high', 'target': edge['from'],
                'observed': 'broken_internal_link', 'state': 'observed', 'link_target': edge['to'], 'http_status': target['status']})
    return {'status': 'partial' if errors or queue or maps else 'ok', 'pages': pages, 'issues': issues,"""
assert anchor in t
t=t.replace(anchor,extra)
p.write_text(t)
print('Qualified structured MCP, private read-only auth, serialized intervention ledger and crawl/report semantics.')
