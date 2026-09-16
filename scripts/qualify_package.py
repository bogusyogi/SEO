#!/usr/bin/env python3
"""Check package paths, independence and an isolated installed CLI without credentials."""
import ast
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

def validate(root=ROOT):
    errors=[]
    for name in ('.codex-plugin/plugin.json','.claude-plugin/plugin.json'):
        data=json.loads((root/name).read_text())
        if data.get('name')!='seo' or data.get('version')!='0.2.0': errors.append('manifest identity mismatch: '+name)
        for field in ('skills','hooks','mcpServers'):
            value=data.get(field)
            if value is None: continue
            if not isinstance(value,str) or not value.startswith('./') or not (root/value).resolve().is_relative_to(root.resolve()) or not (root/value).exists():
                errors.append('invalid package component: '+name+':'+field)
        if data.get('dependencies'): errors.append('unexpected mandatory plugin dependencies')
    for rel in ('seo.py','scripts/seo_runtime.py','scripts/seo_mcp.py','skills/seo/SKILL.md','docs/THIRD_PARTY_NOTICES.md','LICENSE','extensions/banana/scripts/generate.py','pdf/google-seo-reference.md'):
        if not (root/rel).is_file(): errors.append('missing package file: '+rel)
    if (root/'.chatgpt-plugin').exists(): errors.append('obsolete unofficial ChatGPT manifest directory')
    for p in (root/'scripts').glob('*.py'):
        for node in ast.walk(ast.parse(p.read_text(encoding='utf-8'))):
            modules=[]
            if isinstance(node,ast.Import): modules=[a.name for a in node.names]
            if isinstance(node,ast.ImportFrom): modules=[node.module or '']
            if any(m.lower().startswith('legion') for m in modules): errors.append('forbidden framework import: '+str(p))
    if 'legion-skill://' in (root/'SKILL.md').read_text(): errors.append('canonical skill requires Legion resolver')
    for filename in ('.mcp.json','config/mcp-codex.json'):
        data=json.loads((root/filename).read_text())
        servers=data.get('mcpServers',data)
        if servers['seo']['command']!='python': errors.append('unexpected MCP launcher')
    return errors

def smoke(root=ROOT):
    with tempfile.TemporaryDirectory() as td:
        location=Path(td)
        project=location/'isolated-site'; project.mkdir()
        cli=root/'seo.py'
        def run(*args):
            done=subprocess.run([sys.executable,str(cli),'--root',str(project),*args],cwd=location,capture_output=True,text=True,timeout=30)
            if done.returncode: raise RuntimeError(done.stderr or done.stdout)
            return json.loads(done.stdout)
        run('init','--domain','example.com','--market','IN','--language','en')
        result=run('report')
        assert result['jobs'][0]['state']=='succeeded'
        assert (project/'.seo/runtime.sqlite3').exists()
        assert not (project/'.legion').exists()
        assert not (root/'.seo').exists(), 'runtime wrote into its own installed package'
    return {'status':'pass','cwd_independent':True,'legion_installed':False,'credentials_used':False}

def main():
    errors=validate()
    if errors:
        print(json.dumps({'status':'fail','errors':errors})); return 1
    result=smoke()
    print(json.dumps(result,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
