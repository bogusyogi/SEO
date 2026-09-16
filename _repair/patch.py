"""One-time source-only migration, never invoked by installed SEO."""
from pathlib import Path
import json
import re
ROOT = Path(__file__).resolve().parent.parent

def edit(name, old, new):
    p = ROOT / name
    text = p.read_text(encoding='utf-8')
    if old not in text:
        if new in text:
            return
        raise RuntimeError('migration anchor missing: ' + name + ': ' + old[:90])
    p.write_text(text.replace(old, new), encoding='utf-8')

edit('scripts/seo_closure.py', 'REPO_ROOT = SEO_ROOT.parent.parent', 'REPO_ROOT = SEO_ROOT')
edit('scripts/seo_closure.py', "test_runner = REPO_ROOT / 'scripts' / 'test-python.mjs'", "test_runner = REPO_ROOT / '.github' / 'workflows' / 'ci.yml'")
edit('scripts/seo_closure.py', "'skills/seo/tests' not in test_runner.read_text(encoding='utf-8')", "'unittest discover -s tests' not in test_runner.read_text(encoding='utf-8')")

# Retain all existing tests; change only the deliberate state-path contract.
for folder in ('scripts', 'tests', 'references'):
    for p in (ROOT / folder).rglob('*'):
        if p.suffix not in ('.py', '.mjs', '.md', '.json'):
            continue
        text = p.read_text(encoding='utf-8')
        text = text.replace("Path('.legion') / 'seo'", "Path('.seo')")
        text = text.replace("/ '.legion' / 'seo'", "/ '.seo'")
        text = text.replace('.legion/seo', '.seo')
        text = text.replace('Legion SEO', 'Standalone SEO')
        text = text.replace('Legion-native Page Engine', 'SEO Page Engine')
        if p.suffix == '.md':
            text = re.sub(r'legion-skill://seo/([^\s`\"\']+)', r'${SEO_ROOT}/\1', text)
            text = text.replace('Legion—not this capability—owns', 'The independent SEO runtime and its host own')
            text = text.replace("Legion's normal lifecycle", "the independent SEO policy and execution lifecycle")
            text = text.replace('Legion keeps its own ownership, evidence and effect model.', 'SEO keeps its own ownership, evidence and effect model.')
            text = text.replace("Legion's", "the host's")
            text = text.replace('Legion historically absorbed', 'The historical source package absorbed')
            text = text.replace('incorporated into Legion', 'incorporated into SEO')
        p.write_text(text, encoding='utf-8')
q = ROOT / 'config/qualification.json'
data = json.loads(q.read_text())
data['repository_gates'] = ['seo_closure', 'seo_python_tests', 'standalone_install', 'third_party_notices']
data['claim_rule'] = 'Repository tests certify their exact tested scope. Live credentials, host installation and real-site outcomes require separately observed evidence. No Legion dependency.'
q.write_text(json.dumps(data, indent=2) + '\n')

edit('scripts/google_auth.py',
    'CONFIG_PATH = os.path.expanduser("~/.config/claude-seo/google-api.json")\nTOKEN_PATH = os.path.expanduser("~/.config/claude-seo/oauth-token.json")',
    'CONFIG_DIR = os.path.expanduser(os.environ.get("SEO_CONFIG_DIR", "~/.config/seo"))\nLEGACY_CONFIG_DIR = os.path.expanduser("~/.config/claude-seo")\nif not os.environ.get("SEO_CONFIG_DIR") and not os.path.exists(CONFIG_DIR) and os.path.exists(LEGACY_CONFIG_DIR):\n    CONFIG_DIR = LEGACY_CONFIG_DIR  # compatibility only; no Claude runtime dependency\nCONFIG_PATH = os.path.join(CONFIG_DIR, "google-api.json")\nTOKEN_PATH = os.path.join(CONFIG_DIR, "oauth-token.json")')
edit('scripts/google_auth.py', 'with urllib.request.urlopen(req) as resp:', 'with urllib.request.urlopen(req, timeout=30) as resp:')
edit('scripts/google_auth.py', 'json.dump(token_data, f, indent=2)', 'json.dump(token_data, f, indent=2)\n    if os.name != "nt":\n        os.chmod(TOKEN_PATH, 0o600)')

# Preserve corrected aggregates, restoring old renderer and Python API compatibility.
p = ROOT / 'scripts/gsc_query_v2.py'
t = p.read_text()
t = t.replace("    return {\n        'property': site_url,", "    result = {\n        'schema_version': 2,\n        'property': site_url,")
anchor = '\n\ndef query(site_url:'
assert anchor in t
t = t.replace(anchor, "\n    result['totals'] = dict(result['aggregate'])\n    result['row_count'] = len(processed)\n    result['quick_wins'] = []\n    result['quick_wins_state'] = 'not_computed; use opportunity analysis'\n    return result\n\ndef query(site_url:")
p.write_text(t)
p = ROOT / 'scripts/gsc_query.py'
t = p.read_text()
compat = '''\ndef query_search_analytics(site_url, start_date=None, end_date=None, dimensions=None, search_type='web', row_limit=1000, filters=None, data_state='final'):
    """Compatibility API: authoritative totals, never a sum of dimension rows."""
    end = end_date or (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    start = start_date or (datetime.now() - timedelta(days=28)).strftime('%Y-%m-%d')
    return query_v2(site_url, start, end, dimensions if dimensions is not None else ['query', 'page'], search_type, max(1, min(row_limit, 25000)), 100000, filters, data_state)

'''
assert '\ndef main()' in t
p.write_text(t.replace('\ndef main()', compat + '\ndef main()'))

p = ROOT / 'scripts/ga4_report.py'
t = p.read_text()
start = t.index('    # Calculate totals\n')
end = t.index('\n    return result', start)
t = t[:start] + '''    # Query period totals separately. Daily distinct-user counts are not additive.
    try:
        names = ['sessions', 'totalUsers', 'screenPageViews', 'keyEvents', 'totalRevenue', 'ecommercePurchases']
        response = client.run_report(RunReportRequest(
            property=prop, dimensions=[], metrics=[Metric(name=n) for n in names],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimension_filter=FilterExpression(filter=Filter(
                field_name='sessionDefaultChannelGroup',
                string_filter=Filter.StringFilter(match_type=Filter.StringFilter.MatchType.EXACT, value='Organic Search'))),
            return_property_quota=True))
        raw = dict(zip(names, [float(v.value) for v in response.rows[0].metric_values])) if response.rows else dict.fromkeys(names, 0)
        result['totals'] = {'sessions': int(raw['sessions']), 'users': int(raw['totalUsers']),
            'pageviews': int(raw['screenPageViews']), 'key_events': raw['keyEvents'],
            'revenue': raw['totalRevenue'], 'purchases': raw['ecommercePurchases'],
            'avg_daily_sessions': round(raw['sessions'] / max(1, days), 1),
            'provenance': 'dimensionless GA4 period request'}
        meta = getattr(response, 'metadata', None)
        result['measurement'] = {'channel': 'Organic Search', 'currency': getattr(meta, 'currency_code', None),
            'timezone': getattr(meta, 'time_zone', None),
            'thresholded': getattr(meta, 'subject_to_thresholding', None),
            'data_loss_from_other_row': getattr(meta, 'data_loss_from_other_row', None)}
    except Exception as e:
        result['totals'] = {}
        result['error'] = f'GA4 aggregate query failed: {e}'
    result['status'] = 'failed' if result.get('error') else ('partial' if result.get('pages_error') else 'ok')
''' + t[end:]
t = t.replace('"error": report.get("error"),', '"error": report.get("error") or report.get("pages_error"),\n        "status": report.get("status"),\n        "pages_error": report.get("pages_error"),')
t = t.replace('choices=["organic", "top-pages", "device", "country"]', 'choices=["organic", "outcomes", "top-pages", "device", "country"]')
t = t.replace('\n\nif __name__ == "__main__":\n    main()', '\n    return 1 if result.get("error") or result.get("pages_error") else 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())')
p.write_text(t)

p = ROOT / 'scripts/provider_registry.py'
t = p.read_text().replace("return 'available' if vals and all(vals)", "return 'configured' if vals and all(vals)")
t = t.replace("return 'available' if any(vals) else 'unavailable'", "return 'configured' if any(vals) else 'unavailable'")
t = t.replace("{'available', 'manual'}", "{'available', 'configured', 'manual'}")
t = t.replace("'availability': availability(provider, host_tools),", "'availability': availability(provider, host_tools),\n            'runtime_verified': False,\n            'verification': 'run seo.py doctor --live for this site',")
t = t.replace("'availability': state,", "'availability': state,\n        'runtime_verified': False,")
p.write_text(t)

p = ROOT / 'SKILL.md'
t = p.read_text().replace('SEO owns search diagnosis and search-specific methods. Legion owns orchestration across capabilities; this skill does not spawn agents or invoke other skills. Writing owns prose, Marketing owns broader commercial strategy, Designer owns presentation/UX work, and authorized execution follows Legion\'s normal effect/verification lifecycle.', 'SEO is fully standalone. Its runtime owns project state, scheduling, provider calls, policy, execution records and verification. The harness may optionally use writing, coding or design roles, including Legion roles when installed; none is required by SEO. Never install or invoke Legion to run SEO. Use seo.py for bounded operations and references/standalone-operations.md for the executable interface.')
p.write_text(t.replace('.legion/seo', '.seo'))
print('Standalone source migration complete. Original tests retained.')
