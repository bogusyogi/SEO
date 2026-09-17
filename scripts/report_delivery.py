"""TLS SMTP report delivery with immutable content, explicit recipients and no blind resend."""
from __future__ import annotations
import argparse
import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from site_policy import load, authorize
from seo_state import state_dir
import remote_actions as actions


def address(value):
    if not isinstance(value, str) or '\n' in value or '\r' in value:
        raise ValueError('invalid mail address')
    _, parsed = parseaddr(value)
    if parsed != value or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', parsed):
        raise ValueError('explicit plain email address required')
    return value


def config(site):
    cfg = site.get('delivery') or {}
    if cfg.get('provider') != 'smtp' or cfg.get('security') not in {'ssl', 'starttls'}:
        raise ValueError('configure SMTP with ssl or starttls; plaintext is not supported')
    if not isinstance(cfg.get('host'), str) or not re.fullmatch(r'[A-Za-z0-9.-]+', cfg['host']):
        raise ValueError('explicit SMTP hostname required')
    if type(cfg.get('port')) is not int or not 1 <= cfg['port'] <= 65535:
        raise ValueError('invalid SMTP port')
    sender = address(cfg.get('from'))
    recipients = cfg.get('to')
    if not isinstance(recipients, list) or not 1 <= len(recipients) <= 10:
        raise ValueError('configure 1..10 explicit report recipients')
    for value in recipients:
        address(value)
    for key in ('username_env', 'password_env'):
        if cfg.get(key) and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', cfg[key]):
            raise ValueError('mail credential references must be environment-variable names')
    if bool(cfg.get('username_env')) != bool(cfg.get('password_env')):
        raise ValueError('both SMTP credential environment references are required together')
    return cfg


def prepare(root, action_id, report_path, evidence):
    site = load(root)
    authorize(site, 'deliver')
    cfg = config(site)
    base = (state_dir(root) / 'reports').resolve()
    path = Path(report_path).resolve()
    if base not in path.parents or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError('delivery accepts at most 1 MiB of this site\'s report artifacts')
    body = path.read_text(encoding='utf-8')
    return actions.propose(root, action_id, 'delivery', {'body': body, 'report': path.name,
        'from': cfg['from'], 'to': cfg['to'], 'subject': 'SEO report: ' + site['domain']}, evidence)


def preflight(site, payload):
    cfg = config(site)
    if payload['from'] != cfg['from'] or payload['to'] != cfg['to']:
        raise PermissionError('report recipients differ from operator configuration')
    for key in ('username_env', 'password_env'):
        if cfg.get(key) and not os.environ.get(cfg[key]):
            raise ValueError('SMTP credentials are not configured')


def smtp_send(site, payload, action_id):
    cfg = config(site)
    message = EmailMessage()
    message['From'], message['To'], message['Subject'] = payload['from'], ', '.join(payload['to']), payload['subject']
    message['Message-ID'] = '<seo-' + actions.digest([site['domain'], action_id]) + '@' + site['domain'] + '>'
    message.set_content(payload['body'])
    context = ssl.create_default_context()
    if cfg['security'] == 'ssl':
        server = smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=30, context=context)
    else:
        server = smtplib.SMTP(cfg['host'], cfg['port'], timeout=30)
    try:
        server.ehlo()
        if cfg['security'] == 'starttls':
            server.starttls(context=context)
            server.ehlo()
        if cfg.get('username_env'):
            server.login(os.environ[cfg['username_env']], os.environ[cfg['password_env']])
        refused = server.send_message(message, from_addr=payload['from'], to_addrs=payload['to'])
        return {'kind': 'smtp_server_acceptance', 'status': 'partial' if refused else 'accepted',
                'message_id': str(message['Message-ID']), 'recipients_requested': len(payload['to']),
                'recipients_refused': len(refused), 'inbox_delivery_confirmed': False}
    finally:
        # QUIT failure after DATA acknowledgement must not invalidate an accepted receipt.
        try:
            server.quit()
        except (OSError, smtplib.SMTPException):
            try:
                server.close()
            except (OSError, smtplib.SMTPException):
                pass


def send(root, action_id, sender=smtp_send):
    return actions.execute(root, action_id, 'delivery', sender, preflight=preflight)



def deliver_latest(root):
    site = load(root)
    if (site.get('delivery') or {}).get('auto_send_reports') is not True:
        return {'state': 'not_configured'}
    authorize(site, 'deliver')
    report = state_dir(root) / 'reports/latest-run.md'
    action_id = 'report-' + actions.digest([site, report.read_text(encoding='utf-8')])[:40]
    if not actions.path_for(root, action_id).exists():
        prepared = prepare(root, action_id, report, 'standing operator report-delivery policy')
    # Recover a crash between prepare and approve, but never replay an uncertain send.
    prepared = actions.read(root, action_id)
    if prepared['state'] == 'proposed':
        actions.approve(root, action_id, prepared['request_sha256'], site['policy']['approval_ref'])
    return send(root, action_id)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', default='.')
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('id'); p.add_argument('--report', required=True); p.add_argument('--evidence', required=True)
    p = sub.add_parser('approve'); p.add_argument('id'); p.add_argument('--digest', required=True); p.add_argument('--approval-ref', required=True)
    p = sub.add_parser('send'); p.add_argument('id')
    a = ap.parse_args()
    try:
        if a.command == 'prepare': result = prepare(a.root, a.id, a.report, a.evidence)
        elif a.command == 'approve': result = actions.approve(a.root, a.id, a.digest, a.approval_ref)
        else: result = send(a.root, a.id)
    except (ValueError, OSError, PermissionError) as exc:
        result = {'state': 'blocked', 'error': str(exc)}
    print(json.dumps(result, indent=2))
    return 2 if result.get('state') in {'blocked', 'uncertain', 'partial'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
