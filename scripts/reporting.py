"""Deterministic operator brief from collected evidence, not self-reported completion."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from measurement_scope import measurement_context, compare_contexts
from pathlib import Path
from seo_state import state_dir


METRICS = ('clicks', 'impressions', 'ctr', 'position', 'sessions', 'users', 'key_events', 'revenue')


def metric_changes(previous, current):
    if previous.get('lane') != current.get('lane'):
        return {'status': 'not_comparable', 'reason': 'measurement lane changed'}
    context = compare_contexts(measurement_context(previous), measurement_context(current))
    if context['status'] != 'ok':
        return context
    if previous.get('status') != 'ok' or current.get('status') != 'ok':
        return {'status': 'not_testable', 'reason': 'failed or partial collection'}
    old, new = previous.get('data', {}), current.get('data', {})
    a, b = old.get('aggregate', old.get('totals', {})), new.get('aggregate', new.get('totals', {}))
    changes = {}
    for name in METRICS:
        if type(a.get(name)) in (int, float) and type(b.get(name)) in (int, float):
            changes[name] = {'previous': a[name], 'current': b[name], 'delta': b[name]-a[name],
                             'relative_percent': round((b[name]-a[name])/a[name]*100, 2) if a[name] else None}
    return dict(context, metrics=changes)


def freshness(collected_at, *, now=None, max_age_seconds=7*86400):
    """Observation age, not a claim that the provider's underlying data is current."""
    now = now or datetime.now(timezone.utc)
    try:
        stamp = datetime.fromisoformat(collected_at.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('timestamp has no timezone')
        age = (now-stamp).total_seconds()
        if age < -300:
            return {'status': 'invalid', 'reason': 'collection timestamp is in the future'}
    except (ValueError, TypeError, AttributeError):
        return {'status': 'unknown', 'reason': 'valid collection timestamp missing'}
    return {'status': 'stale' if age > max_age_seconds else 'current',
            'age_seconds': max(0, round(age)), 'max_age_seconds': max_age_seconds}


def analyze(root, *, now=None, max_age_seconds=None):
    if max_age_seconds is None:
        from seo_project import load_site
        hours = (load_site(root).get('reporting') or {}).get('max_age_hours', 168)
        if type(hours) not in (int, float) or not 1 <= hours <= 8760:
            raise ValueError('reporting.max_age_hours must be within 1..8760')
        max_age_seconds = hours * 3600
    base=state_dir(root);out={'lanes':{},'critical':[],'opportunities':[],'missing':[]}
    for lane in ('audit','gsc','ga4','bing','backlinks','gsc_ranks','serp'):
        snapshots=[]
        for path in (base/lane).glob('*.json'):
            try:
                envelope=json.loads(path.read_text(encoding='utf-8'))
                if envelope.get('lane')==lane:snapshots.append((envelope.get('collected_at',''),envelope))
            except (OSError,ValueError):continue
        if not snapshots:
            if lane != 'serp': out['missing'].append(lane)
            continue
        snapshots.sort(key=lambda x:x[0]);current=snapshots[-1][1]
        data=current.get('data',{})
        age = freshness(current.get('collected_at'), now=now, max_age_seconds=max_age_seconds)
        out['lanes'][lane] = {'status': current.get('status'), 'collected_at': current.get('collected_at'),
            'freshness': age, 'measurement': measurement_context(current), 'coverage': data.get('coverage'),
            'metrics': {name: data.get('aggregate', data.get('totals', {})).get(name) for name in METRICS
                        if name in data.get('aggregate', data.get('totals', {}))}}
        if current.get('status')!='ok' or age['status'] != 'current':
            out['missing'].append(lane);continue
        if lane=='audit':
            for issue in data.get('severity',{}).get('errors',[]):
                out['critical'].append({'issue':issue,'targets':data.get('issues',{}).get(issue,[])[:10],'source':'audit'})
        if lane=='gsc':
            out['opportunities']=[{'query':r.get('query'),'page':r.get('page'),'position':r.get('position'),
                                  'impressions':r.get('impressions'),'state':'opportunity_hypothesis'} for r in data.get('quick_wins',[])[:10]]
        if len(snapshots)>=2 and lane in {'gsc','ga4'}:
            out['lanes'][lane]['movement']=metric_changes(snapshots[-2][1],current)
    from backlink_tracker import latest
    from rank_tracker import compare
    out['backlink_movement'] = latest(root)
    out['rank_movement'] = compare(root)
    # Historical rank evidence remains available, but stale/failed latest lanes must
    # not be promoted to current movement in the operator brief.
    ranks = out['rank_movement']
    streams = ranks.get('streams', [])
    for stream in streams:
        provider = stream.get('stream', ['', '', '', ''])[3]
        lane = 'gsc_ranks' if provider in {'gsc', 'google_gsc'} else 'serp' if provider == 'dataforseo' else None
        age = freshness(stream.get('collected_at'), now=now, max_age_seconds=max_age_seconds)
        if age['status'] != 'current' or lane and lane in out['missing']:
            stream.update(status='not_testable', reason='latest evidence is missing, failed, partial or stale', changes=[])
    if streams:
        usable = [s for s in streams if s['status'] == 'ok']
        ranks.update(status='ok' if usable else 'not_testable',
                     changes=[c for s in usable for c in s.get('changes', [])],
                     unqualified_streams=len(streams)-len(usable))
    return out


def render(site,analysis):
    lines=[f'# SEO evidence brief: {site}','', 'This report distinguishes observations, missing evidence and hypotheses.','']
    if analysis['critical']:
        lines+=['## Fix first','']
        for row in analysis['critical'][:10]:lines.append(f"- {row['issue']}: {len(row['targets'])} displayed targets; {', '.join(row['targets'][:3])}")
    for lane,row in analysis['lanes'].items():
        lines += ['',f'## {lane.upper()}: {row["status"]}',f'Collected: {row["collected_at"]}']
        measurement = row.get('measurement') or {}
        lines.append('Observation freshness: ' + row.get('freshness', {}).get('status', 'unknown') + '.')
        lines.append('Measurement: ' + json.dumps(measurement, sort_keys=True) + '.')
        for metric, value in row.get('metrics', {}).items():
            lines.append(f'{metric}: {value if value is not None else "unavailable"} (recorded value; see collection status).')
        if row.get('coverage'):
            lines.append('Coverage: ' + json.dumps(row['coverage'], sort_keys=True) + '.')
        movement = row.get('movement', {})
        if movement.get('status') and movement['status'] != 'ok':
            lines.append('Movement: ' + movement['status'] + ' — ' + movement.get('reason', 'unqualified') + '.')
        for metric,values in movement.get('metrics',{}).items():
            lines.append(f"{metric}: {values['previous']} → {values['current']} (delta {values['delta']:+g}).")
        if row.get('movement',{}).get('metrics'):lines.append(row['movement']['interpretation'])
    if analysis['opportunities']:
        lines+=['','## Queries to investigate','']
        for row in analysis['opportunities']:lines.append(f"- {row['query']}: position {row['position']}, impressions {row['impressions']}; validate intent and page quality before changing it.")
    ranks = analysis.get('rank_movement', {})
    links = analysis.get('backlink_movement', {})
    lines += ['', '## Rank and backlink movement', '',
        'Rank history: ' + ranks.get('status', 'not_testable') + '.',
        'GSC positions are impression-weighted averages, not controlled SERP checks. Missing observations are not ranking losses.']
    for stream in ranks.get('streams', []):
        context = stream.get('comparison_context', {})
        lines.append('Rank stream: ' + '/'.join(str(x) for x in stream.get('stream', [])) +
                     '; ' + stream.get('status', 'not_testable') + '; collected ' + str(stream.get('collected_at')) + '.')
        lines.append(stream.get('reason') or context.get('interpretation') or 'No qualified period comparison.')
    for change in ranks.get('changes', [])[:15]:
        if change.get('position_improvement') is not None:
            lines.append(f"- {change['keyword']}: {change['previous_position']} → {change['current_position']} ({change.get('observation_type')}).")
    lines += ['Backlink history: ' + links.get('status', 'not_testable') + '.',
        'Newly observed links: ' + str(len(links.get('newly_observed', []))) + '.',
        'Missing link observations: ' + str(len(links.get('missing', []))) + '; none is automatically confirmed lost.']
    lines+=['','Missing/unusable lanes: '+(', '.join(analysis['missing']) or 'none'),'',
            'Primary next action: '+('resolve the first critical technical blocker.' if analysis['critical'] else
                                     'restore missing measurement before intervention.' if analysis['missing'] else
                                     'validate the strongest query opportunity or retain the current page.'),
            'No ranking, citation or revenue improvement is inferred from deployment alone.']
    return '\n'.join(lines)+'\n'
