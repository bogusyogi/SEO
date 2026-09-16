#!/usr/bin/env python3
"""Optional external audit adapter. Never installs tools or treats lab scores as rankings.

Reads reports from an explicitly installed SEOMator or Unlighthouse executable,
or normalizes a supplied export. Unknown shapes fail closed instead of becoming
an empty passing audit. Tool installation/version pinning is an operator choice.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from seo_io import digest, public_target

def normalize(payload, vendor, version):
    findings = []
    def walk(value, path='$', context=None):
        if isinstance(value, list):
            for i, item in enumerate(value): walk(item, f'{path}[{i}]', context)
        elif isinstance(value, dict):
            target = value.get('finalUrl') or value.get('url') or context
            if isinstance(value.get('audits'), dict):
                for key, rule in value['audits'].items():
                    mode, score = rule.get('scoreDisplayMode'), rule.get('score')
                    state = 'na' if mode == 'notApplicable' else 'not_testable' if score is None or mode in ('manual','informative') else 'pass' if score == 1 else 'fail' if score == 0 else 'partial'
                    findings.append({'id': f'{vendor}:{key}:{target}', 'provider_rule': key, 'status': state, 'target': target,
                        'observed': rule.get('title'), 'raw_locator': path + '.audits.' + key, 'source_kind': 'lab_or_mechanical',
                        'provider_score': score, 'provider_mode': mode})
                return
            rule_id = value.get('ruleId') or value.get('rule_id') or value.get('id')
            status = value.get('status')
            if rule_id and status in ('pass','warn','fail','not-measured'):
                state = {'pass':'pass','warn':'partial','fail':'fail','not-measured':'not_testable'}[status]
                if status == 'warn' and value.get('weight') == 0: state = 'not_testable'
                findings.append({'id':f'{vendor}:{rule_id}:{target}', 'provider_rule':rule_id, 'status':state,
                    'target':target, 'observed':value.get('message') or value.get('description') or value.get('name'),
                    'raw_locator':path, 'provider_status':status, 'source_kind':'external_mechanical'})
                return
            for key, item in value.items():
                if isinstance(item, (dict,list)): walk(item,path+'.'+str(key),target)
    walk(payload)
    if not findings:
        return {'status':'failed','error':'no recognized audit records; export schema is not qualified','provider':vendor,'tool_version':version,'raw_sha256':digest(payload)}
    return {'status':'partial' if any(f['status']=='not_testable' for f in findings) else 'ok',
        'provider':vendor,'tool_version':version,'findings':findings,'raw_sha256':digest(payload),
        'coverage':{'imported_rules':len(findings),'unmeasured':sum(f['status']=='not_testable' for f in findings),'site_complete':False},
        'rule':'Lab audits are not field CrUX, indexation, rankings or causal outcome proof.'}

def execute(vendor, executable, packet, maximum=50):
    path=Path(executable)
    if not path.is_absolute() or not path.is_file(): raise ValueError('use an explicitly installed absolute executable path')
    site=packet['base_url']; host=packet['site']
    public_target(site,{host})
    version=subprocess.run([str(path),'--version'],capture_output=True,text=True,timeout=20,check=True).stdout.strip()
    with tempfile.TemporaryDirectory() as td:
        if vendor=='seomator':
            args=[str(path),'audit',site,'--format','json','--crawl','--max-pages',str(min(max(1,maximum),300))]
        elif vendor=='unlighthouse':
            args=[str(path),'--site',site,'--reporter','jsonExpanded','--output-path',td,'--root',td]
        else: raise ValueError('unsupported executable adapter')
        done=subprocess.run(args,capture_output=True,timeout=600,cwd=td)
        if vendor=='seomator':
            data=json.loads(done.stdout)
        else:
            data=[]
            for p in Path(td).rglob('*.json'):
                if p.stat().st_size <= 16*1024*1024:
                    try: data.append(json.loads(p.read_text(encoding='utf-8')))
                    except (ValueError,UnicodeError): pass
        result=normalize(data,vendor,version)
        result['exit_code']=done.returncode
        if done.returncode not in (0,1): result.update(status='failed',error='external audit execution failed')
        return result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--vendor',required=True,choices=['seomator','unlighthouse','lighthouse'])
    ap.add_argument('--report'); ap.add_argument('--version',default='operator-supplied export')
    ap.add_argument('--executable'); ap.add_argument('--max-pages',type=int,default=50)
    args=ap.parse_args()
    try:
        result=normalize(json.loads(Path(args.report).read_text(encoding='utf-8')),args.vendor,args.version) if args.report else execute(args.vendor,args.executable,json.load(sys.stdin),args.max_pages)
    except Exception as exc: result={'status':'failed','error':f'external audit unavailable or invalid ({type(exc).__name__})'}
    print(json.dumps(result,indent=2))
    return 1 if result.get('error') else 0
if __name__=='__main__': raise SystemExit(main())
