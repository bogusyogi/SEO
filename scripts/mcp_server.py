"""Small stdio MCP adapter over the same standalone SEO functions.

No HTTP listener or background service. Explicit SEO_PROJECT_ROOTS allowlists local
projects (os.pathsep separated). No publication, shell, credential or approval tools.
Protocol: JSON-RPC newline-delimited UTF-8, MCP 2025-06-18 with older-version negotiation.
"""
from __future__ import annotations
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from collector import collect
from provider_doctor import doctor
from seo_state import state_dir
from rank_tracker import compare as rank_compare
from backlink_tracker import latest as backlink_latest

VERSIONS=('2025-06-18','2025-03-26','2024-11-05')
TOOLS=[
    {'name':'seo_doctor','description':'Inspect configured site access; optional live bounded reads.',
     'inputSchema':{'type':'object','properties':{'root':{'type':'string'},'live':{'type':'boolean'}},'required':['root'],'additionalProperties':False}},
    {'name':'seo_collect','description':'Collect site-bound owned evidence, never publish or spend on paid providers.',
     'inputSchema':{'type':'object','properties':{'root':{'type':'string'},'lane':{'type':'string','enum':['audit','gsc','ga4','bing','backlinks','gsc_ranks']}},'required':['root','lane'],'additionalProperties':False}},
    {'name':'seo_report','description':'Read the latest persisted operator report, or explicitly return no report.',
     'inputSchema':{'type':'object','properties':{'root':{'type':'string'}},'required':['root'],'additionalProperties':False}},
    {'name':'seo_rank_changes','description':'Compare provider-scoped saved rank observations without collection.',
     'inputSchema':{'type':'object','properties':{'root':{'type':'string'}},'required':['root'],'additionalProperties':False}},
    {'name':'seo_backlink_changes','description':'Compare scoped backlink snapshots; candidates are not confirmed losses.',
     'inputSchema':{'type':'object','properties':{'root':{'type':'string'}},'required':['root'],'additionalProperties':False}},
]
for t in TOOLS:
    t['annotations']={'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True,'openWorldHint':t['name'] in {'seo_doctor','seo_collect'}}


def permitted_root(value):
    roots={Path(x).expanduser().resolve() for x in os.environ.get('SEO_PROJECT_ROOTS','').split(os.pathsep) if x}
    root=Path(value).expanduser().resolve()
    if root not in roots:
        raise PermissionError('project not in operator-configured SEO_PROJECT_ROOTS')
    return root


def call(name,args):
    tool=next((t for t in TOOLS if t['name']==name),None)
    if not tool or not isinstance(args,dict):raise ValueError('unknown tool or invalid arguments')
    schema=tool['inputSchema']
    if set(args)-schema['properties'].keys() or any(x not in args for x in schema['required']):
        raise ValueError('unexpected or missing tool arguments')
    if not isinstance(args['root'],str) or ('live' in args and not isinstance(args['live'],bool)):
        raise ValueError('invalid root/live type')
    if 'lane' in args and args['lane'] not in schema['properties']['lane']['enum']:
        raise ValueError('MCP collection supports only declared free read lanes')
    root=permitted_root(args['root'])
    if name=='seo_doctor':return doctor(root,args.get('live',False))
    if name=='seo_collect':return collect(root,args['lane'])
    if name=='seo_rank_changes':return rank_compare(root)
    if name=='seo_backlink_changes':return backlink_latest(root)
    path=state_dir(root)/'reports/latest-run.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'status':'no_report'}


def serve(input_stream=sys.stdin,output_stream=sys.stdout):
    initialized=False
    while True:
        line=input_stream.readline(1024*1024+1)
        if not line:break
        try:
            if len(line)>1024*1024:raise ValueError('message limit')
            msg=json.loads(line)
            if not isinstance(msg,dict) or msg.get('jsonrpc')!='2.0':raise ValueError('invalid JSON-RPC')
        except (ValueError,TypeError):
            output_stream.write(json.dumps({'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'invalid request'}})+'\n');output_stream.flush();continue
        if 'id' not in msg:continue
        method=msg.get('method');params=msg.get('params') or {}
        answer={'jsonrpc':'2.0','id':msg['id']}
        if method=='initialize':
            version=params.get('protocolVersion')
            answer['result']={'protocolVersion':version if version in VERSIONS else VERSIONS[0],
                              'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'seo','version':'0.3.0'}}
            initialized=True
        elif not initialized:
            answer['error']={'code':-32002,'message':'initialize first'}
        elif method=='ping':answer['result']={}
        elif method=='tools/list':answer['result']={'tools':TOOLS}
        elif method=='tools/call':
            try:
                # Protect stdout from legacy collector/auth diagnostic output.
                with contextlib.redirect_stdout(io.StringIO()):
                    result=call(params.get('name'),params.get('arguments') or {})
                answer['result']={'content':[{'type':'text','text':json.dumps(result)}],
                                  'isError':result.get('status') in {'failed','partial','unavailable','unconfigured'}}
            except (Exception,SystemExit) as exc:
                answer['result']={'content':[{'type':'text','text':json.dumps({'status':'failed','error':type(exc).__name__})}],'isError':True}
        else:answer['error']={'code':-32601,'message':'method not supported'}
        output_stream.write(json.dumps(answer)+'\n');output_stream.flush()

if __name__=='__main__':serve()
