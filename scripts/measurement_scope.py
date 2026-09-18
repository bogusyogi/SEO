"""Explicit measured-host scope, shared by first-party collectors (no SDK dependency)."""
from __future__ import annotations
import re
from urllib.parse import urlsplit


def hosts(values):
    result = []
    for value in values or []:
        if not isinstance(value, str) or not value or any(c in value for c in '/:@?#\\'):
            raise ValueError('measurement hosts must be bare hostnames')
        value = value.lower().rstrip('.')
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value) or '..' in value:
            raise ValueError('invalid measured hostname')
        if value not in result:
            result.append(value)
    return sorted(result)


def site_hosts(site):
    return hosts([site['domain'], *(site.get('policy', {}).get('allowed_hosts') or [])])


def gsc_host_filter(values):
    names = hosts(values)
    if not names:
        raise ValueError('at least one measured host required')
    return {'dimension': 'page', 'operator': 'includingRegex',
            'expression': '^https?://(' + '|'.join(re.escape(x) for x in names) + ')(/|$)'}


def owned_url(site, url):
    from site_policy import authorize
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('an owned HTTP(S) URL without credentials or fragment is required')
    authorize(site, 'audit', url=url)
    return url


# Only non-secret measurement identity is retained; never copy provider configuration.
CONTEXT_FIELDS = ('property', 'search_type', 'dimensions', 'filters', 'aggregation_type',
                  'data_state', 'time_zone', 'currency')


def measurement_context(envelope):
    """Carry the collection's scope, not the site's possibly changed current settings."""
    data = envelope.get('data') or {}
    return {'site': envelope.get('site'), 'hostname_scope': envelope.get('hostname_scope'),
            'collection_route': envelope.get('collection_route'),
            **{field: data.get(field) for field in CONTEXT_FIELDS},
            'date_range': data.get('date_range')}


def compare_periods(previous, current, *, required=True):
    """Inclusive calendar periods. Overlap is descriptive, not independent evidence."""
    from datetime import date
    if not previous or not current:
        return {'status': 'not_testable', 'reason': 'measurement dates missing'} if required else {
            'status': 'ok', 'qualification': 'legacy dates unavailable'}
    try:
        a, b = date.fromisoformat(previous['start']), date.fromisoformat(previous['end'])
        c, d = date.fromisoformat(current['start']), date.fromisoformat(current['end'])
        if a > b or c > d:
            raise ValueError('reversed measurement dates')
    except (ValueError, KeyError, TypeError):
        return {'status': 'not_testable', 'reason': 'invalid measurement dates'}
    context = {'previous_window': previous, 'current_window': current}
    if (b-a).days != (d-c).days:
        return dict(context, status='not_comparable', reason='measured window lengths changed')
    if (a, b) == (c, d):
        return dict(context, status='not_comparable', reason='same measurement window; refresh is not movement')
    if c <= a or d <= b:
        return dict(context, status='not_comparable', reason='measurement window did not advance')
    overlap = max(0, (min(b, d)-max(a, c)).days+1)
    return dict(context, status='ok', window_days=(b-a).days+1, overlap_days=overlap,
                gap_days=max(0, (c-b).days-1), interpretation=(
                    f'Descriptive snapshot comparison; {overlap} overlapping days. '
                    'Not causal uplift or an independent experiment.'))


def compare_contexts(previous, current):
    """Require like-for-like scope before calculating any movement."""
    import json
    if previous is None or current is None:
        if previous is current:
            return {'status': 'ok', 'qualification': 'legacy_unqualified',
                    'interpretation': 'Legacy snapshots lack property/host/date context; not live qualification.'}
        return {'status': 'not_comparable', 'reason': 'measurement context missing from one snapshot'}
    for field in ('site', 'hostname_scope', 'collection_route', *CONTEXT_FIELDS):
        old, new = previous.get(field), current.get(field)
        if field == 'hostname_scope':
            old, new = hosts(old), hosts(new)
        elif field == 'dimensions':
            old, new = sorted(old or []), sorted(new or [])
        elif field == 'filters':
            old, new = (sorted(json.dumps(x, sort_keys=True) for x in (v or [])) for v in (old, new))
        if old != new:
            return {'status': 'not_comparable', 'reason': field + ' changed'}
    periods = compare_periods(previous.get('date_range'), current.get('date_range'))
    if periods['status'] != 'ok':
        return periods
    if not current.get('site') or not current.get('property') or not current.get('hostname_scope'):
        return {'status': 'not_testable', 'reason': 'measurement identity incomplete'}
    return periods
