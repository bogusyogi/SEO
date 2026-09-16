"""Independent SEO jobs, schedules, policy, evidence and reversible file edits.

Trusted project configuration chooses adapters. Fetched content cannot create
commands or authority. SQLite transactions serialize claims; expired mutation
leases become uncertain, never automatically replayed. Native host roles are
optional adapters, not dependencies.
"""
from __future__ import annotations
import json
import os
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from seo_io import atomic_write, confined, digest, fetch
from seo_collect import collect, run_json, stamp

READ = {'collect', 'report', 'draft'}
WRITE = {'patch', 'publish', 'rollback', 'deliver'}
KINDS = READ | WRITE

class Blocked(ValueError):
    pass

def load_site(root):
    root = Path(root).resolve()
    directory = confined(root, '.seo')
    if not (directory / 'site.yaml').exists():
        if (root / '.legion' / 'seo' / 'site.yaml').exists():
            raise Blocked('Legacy state found. Run migrate-state explicitly; source state will be preserved.')
        raise Blocked('Site is not initialized. Run init with explicit domain, market and language.')
    site = json.loads(confined(root, '.seo/site.yaml').read_text(encoding='utf-8'))
    domain = site.get('domain', '').lower().rstrip('.')
    if not domain or '/' in domain or ':' in domain:
        raise Blocked('site domain must be a hostname, not a URL')
    site['domain'] = domain
    site.setdefault('base_url', 'https://' + domain + '/')
    site.setdefault('allowed_hosts', [domain])
    p = urlsplit(site['base_url'])
    if p.scheme not in ('https', 'http') or p.hostname != domain or p.username:
        raise Blocked('base_url and site domain disagree')
    if domain not in site['allowed_hosts']:
        raise Blocked('site domain missing from host allowlist')
    for host in site['allowed_hosts']:
        if host != domain and host not in (f'www.{domain}', domain.removeprefix('www.')):
            raise Blocked('additional hosts must be the same site www/apex pair; use a separate project otherwise')
    props = site.get('properties') or {}
    gsc = props.get('gsc')
    if gsc:
        if gsc.startswith('sc-domain:'):
            valid = gsc[10:] in (domain, domain.removeprefix('www.'))
        else:
            valid = urlsplit(gsc).hostname in site['allowed_hosts'] and site['base_url'].startswith(gsc)
        if not valid:
            raise Blocked('GSC property does not match this site')
    if props.get('ga4') and not str(props['ga4']).removeprefix('properties/').isdigit():
        raise Blocked('GA4 property must be a numeric property ID')
    if props.get('bing') and urlsplit(props['bing']).hostname not in site['allowed_hosts']:
        raise Blocked('Bing property does not match this site')
    site.setdefault('policy', {'allowed_actions': ['collect', 'report', 'draft'], 'auto_actions': ['collect', 'report', 'draft'],
                               'allowed_paths': [], 'monthly_budget_usd': 0, 'max_change_bytes': 100000})
    return site

def init_site(root, domain, market, language, **properties):
    from seo_project import setup_project
    root = Path(root).resolve()
    if (root / '.legion' / 'seo').exists() and not (root / '.seo').exists():
        raise Blocked('Legacy state exists: migrate-state before init')
    confined(root, '.seo')
    existing_path = root / '.seo' / 'site.yaml'
    if existing_path.exists():
        existing = json.loads(existing_path.read_text())
        if existing.get('domain') != domain:
            raise Blocked('Refusing to repurpose another site project')
    site = setup_project(root, domain=domain, market=market, language=language, **properties)
    site.setdefault('base_url', 'https://' + domain + '/')
    site.setdefault('allowed_hosts', [domain])
    site.setdefault('policy', {'allowed_actions': ['collect', 'report', 'draft'], 'auto_actions': ['collect', 'report', 'draft'],
        'allowed_paths': [], 'monthly_budget_usd': 0, 'max_change_bytes': 100000,
        'technical_only': domain.removeprefix('www.') == 'stunningstrangers.com'})
    atomic_write(existing_path, (json.dumps(site, indent=2) + '\n').encode())
    return load_site(root)

def migrate_state(root):
    root = Path(root).resolve()
    old, new = confined(root, '.legion/seo'), confined(root, '.seo')
    if not old.is_dir() or new.exists():
        raise Blocked('migration requires existing legacy state and an absent .seo destination')
    for p in old.rglob('*'):
        if p.is_symlink():
            raise Blocked('legacy state contains a symlink; inspect before migration')
    staging = root / ('.seo-migrate-' + uuid.uuid4().hex)
    try:
        shutil.copytree(old, staging)
        for p in old.rglob('*'):
            if p.is_file() and digest(p.read_bytes()) != digest((staging / p.relative_to(old)).read_bytes()):
                raise Blocked('migration checksum mismatch')
        os.rename(staging, new)
    finally:
        if staging.exists(): shutil.rmtree(staging)
    return {'status': 'ok', 'destination': str(new), 'source_preserved': True}

class Runtime:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.site = load_site(self.root)
        self.state = confined(self.root, '.seo')
        self.db_path = confined(self.root, '.seo/runtime.sqlite3')
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
                  config_digest TEXT NOT NULL, approved TEXT, state TEXT NOT NULL,
                  due REAL NOT NULL, lease REAL, claim TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                  result TEXT, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS schedules (
                  name TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
                  interval REAL NOT NULL, next_due REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS spend (
                  job_id TEXT PRIMARY KEY, month TEXT NOT NULL, reserved REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                  sequence INTEGER PRIMARY KEY, job_id TEXT, state TEXT, recorded REAL);
            ''')
    def connection(self):
        db = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA busy_timeout=30000')
        return db
    def config(self):
        self.site = load_site(self.root)
        return self.site
    def row(self, job_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None: raise Blocked('unknown job')
        out = dict(row)
        out['payload'] = json.loads(out['payload'])
        out['result'] = json.loads(out['result']) if out['result'] else None
        return out
    def enqueue(self, kind, payload, due=None, key=None):
        if kind not in KINDS or not isinstance(payload, dict):
            raise Blocked('unsupported job kind or payload')
        site = self.config()
        identity = digest({'site': site['domain'], 'kind': kind, 'payload': payload, 'key': key})
        moment = time.time()
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO jobs(id,kind,payload,config_digest,state,due,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                (identity, kind, json.dumps(payload, sort_keys=True), digest(site), 'pending', due if due is not None else moment, moment, moment))
        return self.row(identity)
    def approve(self, job_id):
        row = self.row(job_id)
        site = self.config()
        if row['state'] not in ('pending', 'blocked') or row['config_digest'] != digest(site):
            raise Blocked('job or configuration changed; create a fresh reviewed job')
        if row['kind'] not in site['policy'].get('allowed_actions', []):
            raise Blocked('action is not allowed by site policy')
        token = digest([row['id'], row['config_digest'], row['payload']])
        with self.connection() as db:
            db.execute("UPDATE jobs SET approved=?,state='pending',updated=? WHERE id=?", (token, time.time(), job_id))
        return self.row(job_id)
    def add_schedule(self, name, provider_payload, hours=24, kind='collect'):
        if kind not in ('collect', 'report') or not isinstance(hours, (int, float)) or hours < 1:
            raise Blocked('recurrence is restricted to collection/reporting at intervals of at least one hour')
        with self.connection() as db:
            db.execute('INSERT INTO schedules VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET kind=excluded.kind,payload=excluded.payload,interval=excluded.interval',
                       (name, kind, json.dumps(provider_payload), hours * 3600, time.time()))
        return {'status': 'scheduled', 'name': name, 'interval_hours': hours, 'requires_running_tick_or_serve': True}
    def due_schedules(self):
        now = time.time()
        site = self.config()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                for s in db.execute('SELECT * FROM schedules WHERE next_due<=?', (now,)).fetchall():
                    payload = json.loads(s['payload'])
                    identity = digest([site['domain'], s['name'], s['next_due']])
                    db.execute('INSERT OR IGNORE INTO jobs(id,kind,payload,config_digest,state,due,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                        (identity, s['kind'], s['payload'], digest(site), 'pending', now, now, now))
                    next_due = s['next_due'] + (int((now-s['next_due']) // s['interval']) + 1) * s['interval']
                    db.execute('UPDATE schedules SET next_due=? WHERE name=?', (next_due, s['name']))
                db.execute('COMMIT')
            except Exception:
                db.execute('ROLLBACK'); raise
    def claim(self):
        now, token = time.time(), uuid.uuid4().hex
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                # A killed process might have completed a remote write. Never replay it.
                for old in db.execute("SELECT id,kind FROM jobs WHERE state='running' AND lease<?", (now,)).fetchall():
                    state = 'uncertain' if old['kind'] in WRITE else 'retry'
                    db.execute('UPDATE jobs SET state=?,claim=NULL,updated=? WHERE id=?', (state, now, old['id']))
                row = db.execute("SELECT * FROM jobs WHERE state IN ('pending','retry') AND due<=? ORDER BY due,created LIMIT 1", (now,)).fetchone()
                if row:
                    db.execute("UPDATE jobs SET state='running',lease=?,claim=?,attempts=attempts+1,updated=? WHERE id=?", (now+900, token, now, row['id']))
                db.execute('COMMIT')
            except Exception:
                db.execute('ROLLBACK'); raise
        return (self.row(row['id']), token) if row else (None, None)
    def authorize(self, job):
        site = self.config()
        policy = site['policy']
        if digest(site) != job['config_digest']:
            raise Blocked('configuration changed since queueing; replan before executing')
        kind, payload = job['kind'], job['payload']
        if kind not in policy.get('allowed_actions', []):
            raise Blocked('action denied by site policy')
        if policy.get('technical_only') and (kind in {'draft', 'publish'} or payload.get('category') in {'content', 'marketing', 'outreach', 'acquisition'}):
            raise Blocked('technical-only policy denies content and acquisition work')
        approved = job['approved'] == digest([job['id'], job['config_digest'], payload])
        if kind not in policy.get('auto_actions', []) and not approved:
            raise Blocked('this exact job requires approval or a configured standing policy')
    def adapter(self, name, effect, job):
        config = (self.site.get('adapters') or {}).get(name)
        if not config or config.get('effect') != effect:
            raise Blocked('required trusted adapter is not configured: ' + name)
        argv = config.get('argv')
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
            raise Blocked('adapter argv must be a nonempty string array; shell commands are not accepted')
        cost = float(config.get('max_cost_usd', 0))
        if cost < 0 or cost != cost or cost == float('inf'):
            raise Blocked('invalid adapter cost ceiling')
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                existing = db.execute('SELECT reserved FROM spend WHERE job_id=?', (job['id'],)).fetchone()
                if not existing:
                    used = db.execute('SELECT COALESCE(SUM(reserved),0) FROM spend WHERE month=?', (month,)).fetchone()[0]
                    if used + cost > float(self.site['policy'].get('monthly_budget_usd', 0)):
                        raise Blocked('monthly adapter budget exceeded')
                    db.execute('INSERT INTO spend VALUES(?,?,?)', (job['id'], month, cost))
                db.execute('COMMIT')
            except Exception:
                db.execute('ROLLBACK'); raise
        result = run_json(argv, root=self.root, timeout=min(600, int(config.get('timeout_seconds', 180))),
            payload={'schema_version': 1, 'job_id': job['id'], 'idempotency_key': job['id'],
                     'site': self.site['domain'], 'base_url': self.site['base_url'], 'max_cost_usd': cost,
                     'input': job['payload']})
        if float(result.get('actual_cost_usd', 0) or 0) > cost:
            result['error'] = 'adapter exceeded its declared budget; investigate provider billing'
            result['status'] = 'failed'
        return result
    def local_patch(self, job):
        p = job['payload']
        relative = p.get('path', '')
        path = confined(self.root, relative)
        allowed = self.site['policy'].get('allowed_paths', [])
        if not any(relative == prefix.rstrip('/') or relative.startswith(prefix.rstrip('/') + '/') for prefix in allowed):
            raise Blocked('edit path is not allowlisted')
        if relative.startswith(('.seo/', '.git/', '.github/')) or path.is_dir():
            raise Blocked('managed state and repository control paths cannot be patched')
        before = path.read_bytes() if path.exists() else None
        before_hash = digest(before) if before is not None else 'absent'
        if p.get('expected_sha256') != before_hash:
            raise Blocked('baseline mismatch; file changed since proposal')
        if not isinstance(p.get('content'), str): raise Blocked('UTF-8 replacement content required')
        after = p['content'].encode('utf-8')
        if len(after) > int(self.site['policy'].get('max_change_bytes', 100000)):
            raise Blocked('change exceeds configured byte limit')
        backup = self.state / 'backups' / (job['id'] + '.bin')
        if before is not None: atomic_write(backup, before)
        record = {'job_id': job['id'], 'path': relative, 'before_sha256': before_hash,
                  'after_sha256': digest(after), 'backup': str(backup.relative_to(self.root)) if before is not None else None,
                  'recorded_at': stamp(), 'status': 'prepared'}
        journal = self.state / 'changes' / (job['id'] + '.json')
        atomic_write(journal, json.dumps(record, indent=2).encode())
        atomic_write(path, after)
        if digest(path.read_bytes()) != record['after_sha256']:
            raise RuntimeError('post-write verification failed')
        record.update(status='ok', verification='local file hash', deployed=False)
        atomic_write(journal, json.dumps(record, indent=2).encode())
        return record
    def rollback(self, job):
        original = self.row(job['payload'].get('job_id', ''))
        if original['kind'] != 'patch':
            raise Blocked('built-in rollback handles local patches; remote rollback needs the configured CMS/deploy adapter')
        journal = confined(self.root, '.seo/changes/' + original['id'] + '.json')
        if not journal.exists(): raise Blocked('no observed change journal')
        record = json.loads(journal.read_text())
        path = confined(self.root, record['path'])
        if not path.exists() or digest(path.read_bytes()) != record['after_sha256']:
            raise Blocked('rollback would overwrite a subsequent edit')
        if record['before_sha256'] == 'absent':
            path.unlink()
        else:
            backup = confined(self.root, record['backup'])
            data = backup.read_bytes()
            if digest(data) != record['before_sha256']: raise Blocked('backup digest mismatch')
            atomic_write(path, data)
        return {'status': 'ok', 'rolled_back_job': original['id'], 'verification': 'baseline file restored', 'deployed': False}
    def draft(self, job):
        p = job['payload']
        if not p.get('title') or not p.get('query') or not p.get('sources'):
            raise Blocked('draft needs title, intended query and source inventory')
        sources = {s.get('id') for s in p['sources'] if s.get('id') and (s.get('url') or s.get('evidence_ref'))}
        for claim in p.get('claims', []):
            if not claim.get('source_id') in sources:
                raise Blocked('draft claim has no supplied source')
        body = p.get('body')
        if body is None:
            result = self.adapter('writer', 'writer', job)
            if result.get('error') or not isinstance(result.get('body'), str):
                raise Blocked('writer unavailable or did not produce a draft; no content fabricated')
            body = result['body']
        if not isinstance(body, str) or not body.strip(): raise Blocked('empty draft')
        path = self.state / 'drafts' / (job['id'] + '.md')
        atomic_write(path, body.encode())
        return {'status': 'ok', 'artifact': str(path.relative_to(self.root)), 'sha256': digest(body.encode()),
            'editorial_state': 'requires_review', 'facts_automatically_verified': False,
            'sources': p['sources'], 'title': p['title'], 'query': p['query']}
    def publish(self, job):
        p = job['payload']
        artifact = confined(self.root, p.get('artifact', ''))
        if not str(artifact).startswith(str(self.state / 'drafts') + os.sep):
            raise Blocked('publish only accepts an immutable draft artifact')
        if not p.get('sha256') or digest(artifact.read_bytes()) != p['sha256']:
            raise Blocked('approved artifact digest mismatch')
        if not p.get('rollback_plan') or not p.get('verification', {}).get('contains'):
            raise Blocked('publish requires a rollback plan and nonempty deployed verification assertions')
        verify = p['verification']
        if urlsplit(verify.get('url', '')).hostname not in self.site['allowed_hosts']:
            raise Blocked('verification URL outside site')
        result = self.adapter('publish', 'publish', job)
        if result.get('error') or result.get('job_id') != job['id'] or not result.get('receipt'):
            return {'status': 'uncertain', 'error': 'publication response missing or ambiguous; reconcile before retry', 'adapter_result': result}
        receipt_path = self.state / 'receipts' / (job['id'] + '.json')
        atomic_write(receipt_path, json.dumps(result, indent=2).encode())
        observed = fetch(verify['url'], set(self.site['allowed_hosts']))
        text = observed['body'].decode('utf-8', 'replace')
        matched = observed['status'] == 200 and all(part in text for part in verify['contains'])
        return {'status': 'ok' if matched else 'verification_failed', 'receipt': result['receipt'],
            'receipt_artifact': str(receipt_path.relative_to(self.root)), 'deployed': True, 'verified': matched,
            'observed_sha256': digest(observed['body']), 'observed_status': observed['status'],
            'outcome': 'not_evaluated', 'rollback_plan': p['rollback_plan']}
    def report(self, job):
        with self.connection() as db:
            rows = db.execute("SELECT id,payload,state,result,updated FROM jobs WHERE kind='collect' AND result IS NOT NULL ORDER BY updated DESC").fetchall()
        latest = {}
        for row in rows:
            provider = json.loads(row['payload']).get('provider', 'unknown')
            if provider not in latest:
                latest[provider] = {'job_id': row['id'], 'job_state': row['state'], 'result': json.loads(row['result']), 'updated': row['updated']}
        lines = ['# SEO operator brief', '', f"Site: {self.site['domain']}", f'Generated: {stamp()}', '',
                 '## Evidence health', '']
        for provider, row in sorted(latest.items()):
            data = row['result']
            lines.append(f"- {provider}: {row['job_state']}; evidence job `{row['job_id']}`")
            result = data.get('data', data)
            if result.get('error'): lines.append('  Collection problem: ' + str(result['error']))
            totals = result.get('aggregate') or result.get('totals')
            if totals: lines.append('  Observed metrics: ' + json.dumps(totals, ensure_ascii=False))
            if result.get('date_range'): lines.append('  Measured window: ' + json.dumps(result['date_range']))
            for finding in result.get('issues', [])[:10]:
                lines.append(f"  {finding.get('severity')}: {finding.get('observed')} — {finding.get('target')}")
        if not latest: lines.append('No collection evidence. This is not zero traffic or a passing audit.')
        lines += ['', '## Next action', '', 'Resolve failed evidence lanes and confirm indexability intent before proposing content changes.',
                  'Use the SEO domain references to interpret measured findings; no publication is implied by this report.',
                  '', 'Metrics are observations, not causal proof. Provider estimates and first-party measurements must remain separate.']
        path = self.state / 'reports' / (job['id'] + '.md')
        atomic_write(path, ('\n'.join(lines) + '\n').encode())
        return {'status': 'ok', 'artifact': str(path.relative_to(self.root)), 'providers': latest}
    def execute(self, job):
        self.authorize(job)
        kind = job['kind']
        if kind == 'collect':
            provider = job['payload'].get('provider')
            if isinstance(provider, str) and provider.startswith('adapter:'):
                result = self.adapter(provider[8:], 'read', job)
                result = {'site': self.site['domain'], 'provider': provider, 'collected_at': stamp(), 'status': result.get('status', 'ok'), 'data': result}
            else:
                result = collect(self.root, self.site, provider, job['payload'].get('options'))
            path = self.state / 'evidence' / (job['id'] + '.json')
            atomic_write(path, json.dumps(result, indent=2).encode())
            result['artifact'] = str(path.relative_to(self.root))
            return result
        if kind == 'patch': return self.local_patch(job)
        if kind == 'rollback': return self.rollback(job)
        if kind == 'draft': return self.draft(job)
        if kind == 'publish': return self.publish(job)
        if kind == 'report': return self.report(job)
        if kind == 'deliver':
            report_job = self.row(job['payload'].get('report_job', ''))
            if report_job['kind'] != 'report' or report_job['state'] != 'succeeded':
                raise Blocked('delivery needs a completed report from this site')
            return self.adapter('deliver', 'deliver', job)
        raise Blocked('unsupported action')
    def tick(self, limit=10):
        self.due_schedules()
        finished = []
        for _ in range(min(max(1, limit), 100)):
            job, token = self.claim()
            if not job: break
            try:
                result = self.execute(job)
                status = result.get('status', 'failed' if result.get('error') else 'ok')
                state = {'ok': 'succeeded', 'partial': 'partial', 'verification_failed': 'verification_failed', 'uncertain': 'uncertain'}.get(status, 'failed')
                if result.get('error') and state == 'succeeded': state = 'failed'
            except Blocked as exc:
                state, result = 'blocked', {'status': 'blocked', 'error': str(exc)}
            except Exception as exc:
                state = 'uncertain' if job['kind'] in WRITE else 'failed'
                result = {'status': state, 'error': f'operation failed ({type(exc).__name__}); inspect local evidence'}
            due = time.time()
            if state == 'failed' and job['kind'] in WRITE: state = 'uncertain'
            if state == 'failed' and job['kind'] in READ and job['attempts'] < 3:
                state, due = 'retry', due + 30 * 2 ** job['attempts']
            with self.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                cursor = db.execute('UPDATE jobs SET state=?,result=?,due=?,lease=NULL,claim=NULL,updated=? WHERE id=? AND claim=?',
                    (state, json.dumps(result), due, time.time(), job['id'], token))
                if cursor.rowcount:
                    db.execute('INSERT INTO events(job_id,state,recorded) VALUES(?,?,?)', (job['id'], state, time.time()))
                db.execute('COMMIT')
            finished.append({'id': job['id'], 'state': state, 'result': result})
        return {'status': 'ok', 'jobs': finished}
    def jobs(self, limit=20):
        with self.connection() as db:
            rows = db.execute('SELECT id,kind,state,due,attempts,updated FROM jobs ORDER BY created DESC LIMIT ?', (min(max(1, limit), 1000),)).fetchall()
        return [dict(r) for r in rows]
