"""Materialize explicit UTF-8 and final package qualification cleanup."""
import ast
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

# Path source/data reads must not depend on a Windows legacy code page.
for folder in ('scripts','tests'):
    for p in (ROOT/folder).rglob('*.py'):
        text=p.read_text(encoding='utf-8')
        text=text.replace('.read_text()', ".read_text(encoding='utf-8')")
        lines=text.splitlines(keepends=True); offsets=[0]
        for line in lines: offsets.append(offsets[-1]+len(line))
        changes=[]
        for node in ast.walk(ast.parse(text)):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='write_text' and not any(k.arg=='encoding' for k in node.keywords):
                # AST columns are UTF-8 byte offsets; convert the last line prefix.
                prefix=lines[node.end_lineno-1].encode('utf-8')[:node.end_col_offset].decode('utf-8')
                end=offsets[node.end_lineno-1]+len(prefix)-1
                changes.append((end,", encoding='utf-8'"))
        for end,addition in sorted(changes,reverse=True): text=text[:end]+addition+text[end:]
        p.write_text(text,encoding='utf-8')

p=ROOT/'scripts/seo_collect.py';t=p.read_text(encoding='utf-8')
t=t.replace('stdout=output, stderr=errors, cwd=root, timeout=timeout, shell=False)', "stdout=output, stderr=errors, cwd=root, timeout=timeout, shell=False, env={**os.environ, 'PYTHONIOENCODING':'utf-8', 'PYTHONUTF8':'1'})")
p.write_text(t,encoding='utf-8')
p=ROOT/'seo.py';t=p.read_text(encoding='utf-8')
t=t.replace("VERSION = '0.2.0'", "VERSION = '0.2.0'\nif hasattr(sys.stdout, 'reconfigure'):\n    sys.stdout.reconfigure(encoding='utf-8')")
p.write_text(t,encoding='utf-8')

# GSC query-only snapshots cover all devices/countries; never mislabel them as desktop/IN.
p=ROOT/'scripts/seo_runtime.py';t=p.read_text(encoding='utf-8')
t=t.replace("{'market': self.site['market'], 'language': self.site['language'], 'provider': 'google_gsc', 'measurement': 'gsc_average_position', 'collected_at': result['collected_at']}", "{'market': 'all-countries', 'language': 'not-reported', 'device': 'all', 'provider': 'google_gsc', 'measurement': 'gsc_average_position', 'collected_at': result['collected_at']}")
old="        lines += ['', '## Movement and backlinks', '', 'Rank observations: ' + json.dumps(ranks, ensure_ascii=False), '', 'Backlink observations: ' + json.dumps(backlinks, ensure_ascii=False)]"
new="        lines += ['', '## Movement and backlinks', '', 'Rank comparison: ' + ranks.get('status', 'unknown'), 'Missing rank observations: ' + str(ranks.get('missing_observations', 0)), 'Backlink comparison: ' + backlinks.get('status', 'unknown'), 'New backlink observations: ' + str(len(backlinks.get('new_observations', []))), 'Lost candidates (unconfirmed): ' + str(len(backlinks.get('lost_candidates', [])))]"
assert old in t;t=t.replace(old,new)
a=t.index("        lines += ['', '## Next action',");b=t.index("        path = self.state / 'reports'",a)
t=t[:a]+'''        from seo_prioritize import prioritize
        selection = prioritize(latest)
        primary = selection['primary_action']
        lines += ['', '## Next action', '', primary['action'] + ': ' + primary['reason']]
        if primary.get('target'): lines.append('Target: ' + primary['target'])
        if primary.get('evidence_job'): lines.append('Evidence job: ' + primary['evidence_job'])
        lines += ['', 'This recommendation does not authorize a mutation. Metrics are observations, not causal proof.']
'''+t[b:]
t=t.replace("return {'status': 'ok', 'artifact': str(path.relative_to(self.root)), 'providers': latest}", "return {'status': 'ok', 'artifact': str(path.relative_to(self.root)), 'providers': {name: {'job_id': row['job_id'], 'state': row['job_state'], 'updated': row['updated']} for name, row in latest.items()}, 'selection': selection, 'rank_comparison': ranks, 'backlink_comparison': backlinks}")
p.write_text(t,encoding='utf-8')

# Retain only observed donor identifiers; do not imply an unrecorded full commit pin.
p=ROOT/'docs/DONOR-REVIEW.md';t=p.read_text(encoding='utf-8')
t=t.replace('src/types.ts (962336e036054e316520f95a8a1ce3353f65d60c)', 'src/types.ts (inspected default-branch source)')
p.write_text(t,encoding='utf-8')
print('Portable UTF-8, correct observation scope and bounded operator recommendations materialized.')
