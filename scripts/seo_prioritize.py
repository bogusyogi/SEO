"""Bounded evidence-backed next-action selection. Recommendations never grant authority."""
from datetime import datetime, timezone

def prioritize(latest, max_age_hours=72):
    candidates=[]
    now=datetime.now(timezone.utc).timestamp()
    for provider,row in latest.items():
        envelope=row.get('result') or {}
        data=envelope.get('data',envelope)
        evidence=row.get('job_id')
        age=max(0,(now-float(row.get('updated',now)))/3600)
        if row.get('job_state') not in ('succeeded','partial') or data.get('error'):
            candidates.append({'priority':0,'action':'restore_measurement','provider':provider,'target':None,
                'reason':data.get('error') or 'Latest evidence job did not succeed','evidence_job':evidence,
                'confidence':'high','claim_state':'observed','effect':'none'})
        elif age>max_age_hours:
            candidates.append({'priority':1,'action':'refresh_stale_evidence','provider':provider,'target':None,
                'reason':f'Latest collection is {age:.1f} hours old','evidence_job':evidence,
                'confidence':'high','claim_state':'observed','effect':'none'})
        for finding in data.get('issues',[]) if isinstance(data.get('issues'),list) else []:
            severity=finding.get('severity')
            if severity not in ('critical','high','medium'): continue
            candidates.append({'priority':{'critical':2,'high':3,'medium':4}[severity],
                'action':'investigate_then_propose_fix','target':finding.get('target'),
                'reason':finding.get('observed'),'evidence_job':evidence,'provider':provider,
                'confidence':'high','claim_state':'observed','effect':'none',
                'guardrail':'Verify intended indexability/canonical state before changing it.'})
        if provider=='gsc' and not data.get('error') and age<=max_age_hours:
            for query in data.get('rows',[]):
                impressions=float(query.get('impressions') or 0)
                position=float(query.get('position') or 0)
                if impressions>=100 and 4<=position<=20 and query.get('page'):
                    candidates.append({'priority':5,'action':'review_existing_page_opportunity','target':query['page'],
                        'query':query.get('query'),'reason':'Observed impressions with a mid-range average position',
                        'evidence_job':evidence,'provider':provider,'confidence':'medium','claim_state':'hypothesis',
                        'effect':'none','guardrail':'Internal prioritization heuristic, not promised uplift; check query intent, existing ownership and business value.'})
    candidates.sort(key=lambda x:(x['priority'],x.get('provider') or '',x.get('target') or ''))
    if not candidates:
        return {'primary_action':{'action':'retain_and_measure' if latest else 'collect_baseline',
            'reason':'No evidence-backed intervention identified' if latest else 'No evidence has been collected',
            'effect':'none'},'candidates':[]}
    return {'primary_action':candidates[0],'candidates':candidates[:20]}
