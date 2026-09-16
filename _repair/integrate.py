"""One-time integration codemod. Materializes source and removes itself after qualification."""
from pathlib import Path
import ast
import json
ROOT = Path(__file__).resolve().parent.parent

def change(name, old, new):
    p = ROOT / name
    text = p.read_text()
    if old not in text:
        if new in text: return
        raise ValueError('missing source anchor: ' + name + ': ' + old[:100])
    p.write_text(text.replace(old, new))

# Keep resource lifetime explicit, and allow read commands to execute only their own job.
change('scripts/seo_runtime.py', 'import json\n', 'import json\nimport math\nfrom contextlib import contextmanager\n')
change('scripts/seo_runtime.py', '    def connection(self):', '    @contextmanager\n    def connection(self):')
change('scripts/seo_runtime.py', "        return db\n    def config(self):", "        try:\n            yield db\n        finally:\n            db.close()\n    def config(self):")
change('scripts/seo_runtime.py', "valid = gsc[10:] in (domain, domain.removeprefix('www.'))", "valid = domain == gsc[10:] or domain.endswith('.' + gsc[10:])")
change('scripts/seo_runtime.py', '    def claim(self):', '    def claim(self, only_id=None):')
change('scripts/seo_runtime.py', '''                row = db.execute("SELECT * FROM jobs WHERE state IN ('pending','retry') AND due<=? ORDER BY due,created LIMIT 1", (now,)).fetchone()''', '''                row = db.execute("SELECT * FROM jobs WHERE state IN ('pending','retry') AND due<=? AND (? IS NULL OR id=?) AND (kind IN ('collect','report','draft') OR NOT EXISTS(SELECT 1 FROM jobs WHERE state='running' AND kind IN ('patch','publish','rollback','deliver'))) ORDER BY due,created LIMIT 1", (now, only_id, only_id)).fetchone()''')
change('scripts/seo_runtime.py', '    def tick(self, limit=10):\n        self.due_schedules()', '    def tick(self, limit=10, only_id=None):\n        if only_id is None:\n            self.due_schedules()')
change('scripts/seo_runtime.py', 'job, token = self.claim()', 'job, token = self.claim(only_id)')
change('scripts/seo_runtime.py', "        moment = time.time()\n        with self.connection() as db:", "        moment = time.time()\n        if due is not None and not math.isfinite(due):\n            raise Blocked('job due time must be finite')\n        with self.connection() as db:")
change('scripts/seo_runtime.py', "hours < 1:", "not math.isfinite(hours) or hours < 1:")
# Reserve the full ceiling for EVERY adapter invocation, including read retries.
change('scripts/seo_runtime.py', "        month = datetime.now(timezone.utc).strftime('%Y-%m')", "        reservation = job['id'] + ':' + str(job['attempts'])\n        month = datetime.now(timezone.utc).strftime('%Y-%m')")
change('scripts/seo_runtime.py', "(job['id'],)).fetchone()\n                if not existing:", "(reservation,)).fetchone()\n                if not existing:")
change('scripts/seo_runtime.py', "(job['id'], month, cost)", "(reservation, month, cost)")
# Validate public identity before writing initial configuration.
change('scripts/seo_runtime.py', "    from seo_project import setup_project\n    root", "    from seo_project import setup_project\n    if not domain or '/' in domain or ':' in domain or not market or not language:\n        raise Blocked('explicit hostname, market and language are required')\n    root")

# Scope GA4 to the actual site even when a property spans multiple hostnames.
p = ROOT / 'scripts/ga4_report.py'
t = p.read_text()
t = t.replace('        FilterExpression,\n', '        FilterExpression,\n        FilterExpressionList,\n')
t = t.replace('    limit: int = 100,\n', '    limit: int = 100,\n    hostname: Optional[str] = None,\n')
t = t.replace('    limit: int = 50,\n', '    limit: int = 50,\n    hostname: Optional[str] = None,\n')
t = t.replace('    limit: int = 20,\n', '    limit: int = 20,\n    hostname: Optional[str] = None,\n')
t = t.replace('    days: int = 28,\n) -> dict:', '    days: int = 28,\n    hostname: Optional[str] = None,\n) -> dict:')
# Replace only the exact channel-filter ASTs, not unrelated FilterExpressions.
lines = t.splitlines(keepends=True)
offsets = [0]
for line in lines: offsets.append(offsets[-1] + len(line))
patches = []
for node in ast.walk(ast.parse(t)):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'FilterExpression':
        inner = next((kw.value for kw in node.keywords if kw.arg == 'filter'), None)
        if isinstance(inner, ast.Call) and any(kw.arg == 'field_name' and isinstance(kw.value, ast.Constant) and kw.value.value == 'sessionDefaultChannelGroup' for kw in inner.keywords):
            patches.append((offsets[node.lineno-1]+node.col_offset, offsets[node.end_lineno-1]+node.end_col_offset, '_organic_filter(hostname)'))
assert len(patches) == 5, len(patches)
for a,b,s in sorted(patches, reverse=True): t = t[:a] + s + t[b:]
helper = '''\ndef _organic_filter(hostname=None):
    expressions = [FilterExpression(filter=Filter(field_name='sessionDefaultChannelGroup',
        string_filter=Filter.StringFilter(match_type=Filter.StringFilter.MatchType.EXACT, value='Organic Search')))]
    if hostname:
        expressions.append(FilterExpression(filter=Filter(field_name='hostName',
            string_filter=Filter.StringFilter(match_type=Filter.StringFilter.MatchType.EXACT, value=hostname))))
    return FilterExpression(and_group=FilterExpressionList(expressions=expressions))

'''
t = t.replace('\ndef _build_ga4_client', helper + '\ndef _build_ga4_client')
t = t.replace('organic_traffic_report(property_id, days, limit)', 'organic_traffic_report(property_id, days, limit, hostname)')
t = t.replace('report.get("totals", {}).get("sessions", 0)', 'report.get("totals", {}).get("sessions")')
t = t.replace('    args = parser.parse_args()', '    parser.add_argument("--hostname", help="scope a multi-host property to this exact hostname")\n    args = parser.parse_args()\n    if args.days < 1 or args.limit < 1:\n        parser.error("days and limit must be positive")')
t = t.replace('top_pages_report(prop, args.days, args.limit)', 'top_pages_report(prop, args.days, args.limit, args.hostname)')
t = t.replace('device_breakdown(prop, args.days)', 'device_breakdown(prop, args.days, args.hostname)')
t = t.replace('country_breakdown(prop, args.days, args.limit)', 'country_breakdown(prop, args.days, args.limit, args.hostname)')
t = t.replace('organic_traffic_report(prop, args.days, args.limit)', 'organic_traffic_report(prop, args.days, args.limit, args.hostname)')
t = t.replace('    # Daily organic sessions', "    result['hostname_filter'] = hostname\n    # Daily organic sessions")
p.write_text(t)

# GSC: explicit URL-prefix scope, comparable date window, and filter provenance.
p = ROOT / 'scripts/gsc_query_v2.py'
t = p.read_text().replace('import os\n', 'import os\nimport re\n')
t = t.replace('    svc = service()\n', "    try:\n        svc = service()\n    except Exception as exc:\n        return {'error': f'cannot build GSC service ({type(exc).__name__})', 'property': site_url}\n")
t = t.replace("    return normalize_result(\n", "    result = normalize_result(\n")
anchor = '\n\ndef main() -> int:'
assert anchor in t
t = t.replace(anchor, "\n    result['filters'] = filters or []\n    result['aggregation_type'] = aggregate.get('responseAggregationType')\n    return result\n" + anchor)
t = t.replace("    ap.add_argument('--out')", "    ap.add_argument('--out')\n    ap.add_argument('--page-prefix')")
t = t.replace('    args = ap.parse_args()', "    args = ap.parse_args()\n    if args.days < 1 or args.max_rows < 1:\n        ap.error('days and max-rows must be positive')\n    if args.country and (len(args.country) != 3 or not args.country.isalpha()):\n        ap.error('GSC country must be an ISO 3166-1 alpha-3 code')")
t = t.replace("start = args.start_date or (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')", "start = args.start_date or (datetime.fromisoformat(end) - timedelta(days=args.days - 1)).strftime('%Y-%m-%d')\n    if datetime.fromisoformat(start) > datetime.fromisoformat(end):\n        ap.error('start date is after end date')")
t = t.replace('    filters = []\n', "    filters = []\n    if args.page_prefix:\n        filters.append({'dimension': 'page', 'operator': 'includingRegex', 'expression': '^' + re.escape(args.page_prefix)})\n")
p.write_text(t)

# Audit helper no longer follows arbitrary private endpoints or unbounded redirects.
p = ROOT / 'scripts/site_audit.py'
t = p.read_text()
a, b = t.index('def get(url,'), t.index('\ndef normalize(', t.index('def get(url,'))
t = t[:a] + '''AUDIT_ALLOWED_HOSTS = None

def get(url, method='GET'):
    from seo_io import fetch
    host = urllib.parse.urlsplit(url).hostname
    allowed = AUDIT_ALLOWED_HOSTS or {host}
    try:
        response = fetch(url, allowed, method=method)
        return response['status'], response['url'], response['body'].decode('utf-8', 'replace'), response['headers']
    except Exception as exc:
        return 0, url, type(exc).__name__, {}

def status_only(url):
    from seo_io import fetch
    host = urllib.parse.urlsplit(url).hostname
    try:
        response = fetch(url, AUDIT_ALLOWED_HOSTS or {host}, method='HEAD', follow_redirects=False)
        if response['status'] == 405:
            response = fetch(url, AUDIT_ALLOWED_HOSTS or {host}, follow_redirects=False)
        return response['status'], response['headers'].get('location')
    except Exception:
        return 0, None

''' + t[b:]
t = t.replace('def audit(start, maxpages):\n', 'def audit(start, maxpages):\n    global AUDIT_ALLOWED_HOSTS\n    AUDIT_ALLOWED_HOSTS = {urllib.parse.urlsplit(start).hostname}\n')
p.write_text(t)
change('scripts/seo_io.py', "method='GET', redirects=5, limit=MAX_BYTES", "method='GET', redirects=5, limit=MAX_BYTES, follow_redirects=True")
change('scripts/seo_io.py', "        if code in (301, 302, 303, 307, 308) and headers.get('location'):", "        if follow_redirects and code in (301, 302, 303, 307, 308) and headers.get('location'):")

# Intervention outcomes must have verified deployment and a mature evidence window.
p = ROOT / 'scripts/search_ops.py'
t = p.read_text()
t = t.replace('def cmd_outcome(args, state):\n', "def cmd_outcome(args, state):\n")
anchor = "    if not row.get('deployment'):\n        raise SystemExit('outcome cannot be recorded before deployment')"
replacement = anchor + "\n    if args.verdict != 'immature':\n        if (row.get('verification') or {}).get('result') != 'pass':\n            raise SystemExit('outcome requires verified deployment')\n        earliest = (row.get('evaluation') or {}).get('earliest_date')\n        if not earliest or datetime.now(timezone.utc).date() < datetime.fromisoformat(earliest.replace('Z', '+00:00')).date():\n            raise SystemExit('outcome observation window is not mature')\n        if not args.evidence:\n            raise SystemExit('outcome requires evidence')"
assert anchor in t
t = t.replace(anchor, replacement)
p.write_text(t)
change('tests/test_seo_kernel.py', "'--evaluate-after','2026-10-01'", "'--evaluate-after','2020-01-01'")

# Remove remaining active ownership/locator assumptions, preserving source provenance.
for folder in ('references', 'extensions', 'pdf'):
    for p in (ROOT / folder).rglob('*.md'):
        t = p.read_text()
        t = t.replace('legion-skill://seo/', '${SEO_ROOT}/')
        t = t.replace('Legion owns', 'The independent SEO runtime owns')
        t = t.replace('Legion authority/effect', 'SEO authority/effect')
        t = t.replace('legion-skill://', 'optional-host-resource://')
        p.write_text(t)
print('Integrated independent runtime, scoped collectors and mature outcomes.')
