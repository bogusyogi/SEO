"""Page-scoped, fixed-window follow-up collection for existing intervention records."""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from measurement_scope import site_hosts, gsc_host_filter
from reporting import metric_changes
from site_policy import load, authorize, property_for
from seo_state import atomic_json, state_dir
import gsc_query_v2


def window_before(today, days=28):
    # Four full UTC days avoid using an incomplete Pacific-time GSC day. Providers
    # still determine data finality; this is not proof of complete query coverage.
    end = today - timedelta(days=4)
    return {'start': (end-timedelta(days=days-1)).isoformat(), 'end': end.isoformat()}


def schedule_after(today, days=28):
    start = today + timedelta(days=2)  # Entire measured period is after deployment.
    end = start + timedelta(days=days-1)
    return {'window': {'start': start.isoformat(), 'end': end.isoformat()},
            'due_at': datetime.combine(end+timedelta(days=4), datetime.min.time(), timezone.utc).isoformat()}


def measure(root, target, window):
    site = load(root)
    authorize(site, 'gsc', url=target)
    names = site_hosts(site)
    filters = [gsc_host_filter(names), {'dimension': 'page', 'operator': 'equals', 'expression': target}]
    try:
        prop = property_for(site, 'gsc')
        data = gsc_query_v2.query(prop, window['start'], window['end'], ['query'], 'web', 25000, 25000,
                                  filters, 'final')
        if data.get('property') != prop:
            raise ValueError('GSC property mismatch')
        state = 'partial' if data.get('error') or data.get('coverage', {}).get('hit_client_cap') else 'ok'
    except Exception as error:
        state, data = 'failed', {'error': type(error).__name__, 'date_range': window}
    return {'schema_version': 2, 'site': site['domain'], 'lane': 'gsc', 'status': state,
            'target': target, 'collected_at': datetime.now(timezone.utc).isoformat(),
            'hostname_scope': names, 'collection_route': 'standalone_direct', 'data': data}


def evaluate(before, after, *, metric='clicks', minimum_impressions=100):
    if before.get('target') != after.get('target'):
        return {'verdict': 'not_measurable', 'reason': 'target changed'}
    result = metric_changes(before, after)
    if result['status'] != 'ok' or metric not in result.get('metrics', {}):
        return {'verdict': 'not_measurable', 'comparison': result,
                'reason': 'usable, matching page baselines and follow-up evidence are required'}
    impressions = result['metrics'].get('impressions') or {}
    if min(impressions.get('previous', 0), impressions.get('current', 0)) < minimum_impressions:
        return {'verdict': 'inconclusive', 'comparison': result, 'reason': 'below configured impression threshold'}
    delta = result['metrics'][metric]['delta'] * (-1 if metric == 'position' else 1)
    return {'verdict': 'improved' if delta > 0 else 'declined' if delta < 0 else 'inconclusive',
            'comparison': result, 'causal_strength': 'observational',
            'reason': 'page-specific descriptive movement, not attribution to the intervention'}
