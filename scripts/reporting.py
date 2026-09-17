"""Deterministic operator brief from collected evidence, not self-reported completion."""
from __future__ import annotations
import json
from pathlib import Path
from seo_state import state_dir


def metric_changes(previous, current):
    if previous.get('site') != current.get('site') or previous.get('lane') != current.get('lane'):
        return {'status':'not_comparable'}
    old,new=previous.get('data',{}),current.get('data',{})
    for field in ('property','search_type','dimensions','filters'):
        if old.get(field)!=new.get(field):return {'status':'not_comparable','reason':field+' changed'}
    if previous.get('status')!='ok' or current.get('status')!='ok':
        return {'status':'not_testable','reason':'failed or partial collection'}
    a=old.get('aggregate',old.get('totals',{}));b=new.get('aggregate',new.get('totals',{}))
    changes={}
    for key in ('clicks','impressions','ctr','position','sessions','users','key_events','revenue'):
        if key in a and key in b and isinstance(a[key],(int,float)) and isinstance(b[key],(int,float)):
            changes[key]={'previous':a[key],'current':b[key],'delta':b[key]-a[key],
                          'relative_percent':round((b[key]-a[key])/a[key]*100,2) if a[key] else None}
    return {'status':'ok','metrics':changes,'previous_window':old.get('date_range'),'current_window':new.get('date_range'),
            'interpretation':'Snapshot comparison; rolling windows may overlap. Not causal uplift or a controlled experiment.'}


def analyze(root):
    base=state_dir(root);out={'lanes':{},'critical':[],'opportunities':[],'missing':[]}
    for lane in ('audit','gsc','ga4','bing','backlinks'):
        snapshots=[]
        for path in (base/lane).glob('*.json'):
            try:
                envelope=json.loads(path.read_text())
                if envelope.get('lane')==lane:snapshots.append((envelope.get('collected_at',''),envelope))
            except (OSError,ValueError):continue
        if not snapshots:out['missing'].append(lane);continue
        snapshots.sort(key=lambda x:x[0]);current=snapshots[-1][1]
        out['lanes'][lane]={'status':current.get('status'),'collected_at':current.get('collected_at')}
        if current.get('status')!='ok':out['missing'].append(lane);continue
        data=current.get('data',{})
        if lane=='audit':
            for issue in data.get('severity',{}).get('errors',[]):
                out['critical'].append({'issue':issue,'targets':data.get('issues',{}).get(issue,[])[:10],'source':'audit'})
        if lane=='gsc':
            out['opportunities']=[{'query':r.get('query'),'page':r.get('page'),'position':r.get('position'),
                                  'impressions':r.get('impressions'),'state':'opportunity_hypothesis'} for r in data.get('quick_wins',[])[:10]]
        if len(snapshots)>=2 and lane in {'gsc','ga4'}:
            out['lanes'][lane]['movement']=metric_changes(snapshots[-2][1],current)
    return out


def render(site,analysis):
    lines=[f'# SEO evidence brief: {site}','', 'This report distinguishes observations, missing evidence and hypotheses.','']
    if analysis['critical']:
        lines+=['## Fix first','']
        for row in analysis['critical'][:10]:lines.append(f"- {row['issue']}: {len(row['targets'])} displayed targets; {', '.join(row['targets'][:3])}")
    for lane,row in analysis['lanes'].items():
        lines += ['',f'## {lane.upper()}: {row["status"]}',f'Collected: {row["collected_at"]}']
        for metric,values in row.get('movement',{}).get('metrics',{}).items():
            lines.append(f"{metric}: {values['previous']} → {values['current']} (delta {values['delta']:+g}).")
        if row.get('movement',{}).get('metrics'):lines.append(row['movement']['interpretation'])
    if analysis['opportunities']:
        lines+=['','## Queries to investigate','']
        for row in analysis['opportunities']:lines.append(f"- {row['query']}: position {row['position']}, impressions {row['impressions']}; validate intent and page quality before changing it.")
    lines+=['','Missing/unusable lanes: '+(', '.join(analysis['missing']) or 'none'),'',
            'Primary next action: '+('resolve the first critical technical blocker.' if analysis['critical'] else
                                     'restore missing measurement before intervention.' if analysis['missing'] else
                                     'validate the strongest query opportunity or retain the current page.'),
            'No ranking, citation or revenue improvement is inferred from deployment alone.']
    return '\n'.join(lines)+'\n'
