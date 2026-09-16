import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import seo_collect
import google_auth
import search_ops
from qualify_package import validate,smoke

class QualityTests(unittest.TestCase):
    def test_package_paths_and_independence(self):
        self.assertEqual(validate(),[])
    def test_standalone_installed_smoke(self):
        self.assertEqual(smoke()['status'],'pass')
    def test_oauth_is_readonly_by_default(self):
        self.assertIn('webmasters.readonly',google_auth.OAUTH_SCOPES)
        self.assertNotIn('/auth/indexing',google_auth.OAUTH_SCOPES)
    def test_token_save_roundtrip_and_private_mode(self):
        with tempfile.TemporaryDirectory() as td, patch.object(google_auth,'TOKEN_PATH',str(Path(td)/'credentials/token.json')):
            google_auth._save_oauth_token({'access_token':'fixture'})
            p=Path(google_auth.TOKEN_PATH)
            self.assertEqual(json.loads(p.read_text())['access_token'],'fixture')
            if os.name!='nt': self.assertEqual(p.stat().st_mode&0o777,0o600)
    def test_performance_nested_failure_is_not_success(self):
        result=seo_collect.envelope({'domain':'example.com'},'pagespeed',{'psi':{'mobile':{'error':'timeout'},'desktop':{'lighthouse_scores':{'performance':90}}}})
        self.assertEqual(result['status'],'partial')
        self.assertFalse(result['runtime_verified'])
    def test_crawl_replay_preserves_duplicate_and_broken_link_findings(self):
        site={'domain':'example.com','base_url':'https://example.com/','allowed_hosts':['example.com'],'policy':{}}
        html='<html><head><title>Same</title><meta name="description" content="Same"><link rel="canonical" href="/"></head><body><h1>A</h1><a href="/two">two</a><a href="/broken">broken</a><img src="a.png"></body></html>'
        def fake(url,allowed,**kwargs):
            body='User-agent: *\nAllow: /' if url.endswith('/robots.txt') else '<urlset/>' if url.endswith('/sitemap.xml') else html
            code=404 if url.endswith('/broken') else 200
            return {'url':url,'body':body.encode(),'status':code,'headers':{},'chain':[{'url':url,'status':code}]}
        with patch.object(seo_collect,'fetch',side_effect=fake): result=seo_collect.crawl(site,10)
        rules={x['observed'] for x in result['issues']}
        self.assertIn('duplicate_title',rules)
        self.assertIn('broken_internal_link',rules)
        self.assertIn('image_alt_missing',rules)
        self.assertFalse(result['coverage']['site_complete'])
    def test_deployment_idempotency_conflict(self):
        row={'id':'a','status':'verified','deployment':{'idempotency_key':'key','identity':'commit:1','effect_receipt':'receipt:1'}}
        state={'interventions':[row]}
        args=NS(id='a',idempotency_key='key',identity='commit:1',effect_receipt='receipt:1')
        self.assertEqual(search_ops.cmd_deploy(args,state),row)
        args.identity='commit:2'
        with self.assertRaises(SystemExit): search_ops.cmd_deploy(args,state)
    def test_safe_fetch_follows_only_revalidated_host(self):
        from seo_io import public_target
        with self.assertRaises(ValueError): public_target('https://user:pass@example.com',{'example.com'})

if __name__=='__main__': unittest.main()
