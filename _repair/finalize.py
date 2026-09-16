from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def change(name,old,new):
    p=ROOT/name; t=p.read_text()
    assert old in t,(name,old[:100])
    p.write_text(t.replace(old,new))

# A successful process exit does not turn a provider error object into success.
change('scripts/seo_collect.py', "    result['exit_code'] = done.returncode\n    return result", "    if result.get('error') and result.get('status') not in ('partial','unconfigured','unauthorized'):\n        result['status'] = 'failed'\n    result['exit_code'] = done.returncode\n    return result")
change('scripts/setup_runtime.py', "'mcp>=1.12,<2'", "'mcp>=2,<3'")
# First-party rank collection is explicitly labelled GSC average position, not SERP rank.
change('scripts/seo_collect.py', "    if provider == 'gsc':", "    if provider in ('gsc', 'gsc_ranks'):")
change('scripts/seo_collect.py', "    elif provider == 'ga4':", "        if provider == 'gsc_ranks':\n            command += ['--dimensions', 'query']\n    elif provider == 'ga4':")
change('seo.py', "choices=['gsc', 'ga4', 'bing_links', 'crawl', 'pagespeed']", "choices=['gsc', 'gsc_ranks', 'ga4', 'bing_links', 'crawl', 'pagespeed']")
change('scripts/seo_runtime.py', "            path = self.state / 'evidence' / (job['id'] + '.json')", "            if provider == 'gsc_ranks' and not (result.get('data') or {}).get('error'):\n                import rank_tracker\n                data = result['data']\n                rows = [dict(row, state='ranked') for row in data.get('rows', []) if row.get('position', 0) > 0]\n                result['rank_snapshot'] = str(rank_tracker.ingest(self.root, rows, {'market': self.site['market'], 'language': self.site['language'], 'provider': 'google_gsc', 'measurement': 'gsc_average_position', 'collected_at': result['collected_at']}))\n            if provider == 'bing_links' and isinstance((result.get('data') or {}).get('rows'), list):\n                import backlink_history\n                result['backlink_snapshot'] = str(backlink_history.ingest(self.root, {**result['data'], 'collected_at': result['collected_at']}))\n            path = self.state / 'evidence' / (job['id'] + '.json')")
change('scripts/seo_runtime.py', "        if not latest: lines.append('No collection evidence. This is not zero traffic or a passing audit.')", "        if not latest: lines.append('No collection evidence. This is not zero traffic or a passing audit.')\n        import rank_tracker\n        import backlink_history\n        ranks = rank_tracker.compare(self.root)\n        backlinks = backlink_history.latest(self.root)\n        lines += ['', '## Movement and backlinks', '', 'Rank observations: ' + json.dumps(ranks, ensure_ascii=False), '', 'Backlink observations: ' + json.dumps(backlinks, ensure_ascii=False)]")
print('Finalized fail-closed adapter states and linked first-party observation histories.')
