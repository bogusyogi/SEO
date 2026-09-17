"""Optional installed scanners. No downloads, shell interpolation, or implicit npm installs."""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
from pathlib import Path
from site_policy import load, authorize
from seo_state import state_dir, atomic_json


def scan(root, scanner, timeout=600):
    site=load(root);url='https://'+site['domain']+'/'
    authorize(site,'audit',url=url)
    if scanner not in {'unlighthouse','seomator'} or not 1<=timeout<=1800:
        raise ValueError('unsupported scanner or timeout')
    binary=shutil.which('unlighthouse-ci' if scanner=='unlighthouse' else 'seomator')
    if not binary:
        return {'status':'unavailable','scanner':scanner,'reason':'install and qualify the optional scanner explicitly; no software installed automatically'}
    out=state_dir(root)/'external-scans'/scanner;out.mkdir(parents=True,exist_ok=True)
    args=([binary,'--site',url,'--reporter','jsonExpanded','--output-path',str(out)] if scanner=='unlighthouse' else
          [binary,'audit',url,'--crawl','--max-pages','100','--format','json','-o',str(out/'report.json')])
    try:
        run=subprocess.run(args,cwd=root,capture_output=True,text=True,timeout=timeout,check=False)
        result={'status':'ok' if run.returncode==0 else 'failed','scanner':scanner,'site':site['domain'],
                'exit_code':run.returncode,'output':str(out),'measurement':'external audit/lab evidence; not field CWV',
                'note':'Native output retained; do not promote unavailable checks to passes.'}
        (out/'stdout.log').write_text(run.stdout);(out/'stderr.log').write_text(run.stderr)
    except (OSError,subprocess.TimeoutExpired) as exc:
        result={'status':'failed','scanner':scanner,'error':type(exc).__name__}
    atomic_json(out/'receipt.json',result);return result


def main():
    ap=argparse.ArgumentParser();ap.add_argument('scanner',choices=['unlighthouse','seomator']);ap.add_argument('--root',default='.')
    a=ap.parse_args();r=scan(a.root,a.scanner);print(json.dumps(r,indent=2));return 0 if r['status']=='ok' else 2

if __name__=='__main__':
    raise SystemExit(main())
