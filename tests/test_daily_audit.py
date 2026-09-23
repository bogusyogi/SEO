import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import daily_audit as audit  # noqa: E402

PAGE = ('<html><head><title>Oni | DD</title><link href="https://x.com/products/oni/" : rel="canonical">'
        '<script type="application/ld+json">{"@type":"Product","offers":{"availability":"https://schema.org/OutOfStock"}}</script>'
        '</head><body>blade steel handle</body></html>')


class DailyAuditTests(unittest.TestCase):
    def test_canonical_found_regardless_of_attribute_order(self):
        with patch.object(audit, 'fetch', return_value=(200, 'https://x.com/products/oni/', PAGE)):
            facts = audit.page_facts('https://x.com/products/oni/')
        self.assertEqual(facts['canonical'], 'https://x.com/products/oni/')
        self.assertEqual(facts['availability'], ['OutOfStock'])
        self.assertEqual(facts['title'], 'Oni | DD')

    def test_link_findings_flags_broken_and_redirect_but_skips_cdn_cgi_and_intentional(self):
        body = ('<a href="/gone/">x</a><a href="/old/">x</a><a href="/ok/">x</a><a href="/downloads/">x</a>'
                '<a href="/cdn-cgi/l/email-protection#abc">x</a><a href="https://other.com/">x</a>'
                '<script>var u="/build/"+f;</script>')
        with patch.object(audit, 'fetch', return_value=(200, 'https://x.com/', body)):
            facts = audit.page_facts('https://x.com/')
        facts.update(url='https://x.com/', final='https://x.com/', status=200)
        statuses = {'https://x.com/gone/': (404, None), 'https://x.com/old/': (301, 'https://x.com/new/'),
                    'https://x.com/ok/': (200, None)}
        with patch.object(audit, 'link_status', side_effect=lambda u: statuses[u]) as ls:
            out = audit.link_findings('x.com', [facts], intentional_redirects=('/downloads/',))
        self.assertEqual(sorted(c[0][0] for c in ls.call_args_list), sorted(statuses))
        self.assertEqual({(f['control'], f['target']) for f in out},
                         {('internal-link-broken', 'https://x.com/gone/'), ('internal-link-redirect', 'https://x.com/old/')})

    def test_finding_ids_are_stable(self):
        a = audit.finding('x.com', 'c', 't', 'low', 'o', 'r')
        b = audit.finding('x.com', 'c', 't', 'high', 'other', 'other')
        self.assertEqual(a['id'], b['id'])
        self.assertNotEqual(a['id'], audit.finding('x.com', 'c', 't2', 'low', 'o', 'r')['id'])

    def test_vendure_stock_classification_and_field_fallback(self):
        calls = []

        def fake_fetch(url, data=None, headers=None, timeout=25):
            q = json.loads(data)['query']
            calls.append(q)
            if 'isPreOrder' in q:
                return 200, url, json.dumps({'errors': [{'message': 'unknown field'}]})
            return 200, url, json.dumps({'data': {'product': {'variants': [{'stockLevel': '0'}, {'stockLevel': '4'}]}}})
        with patch.object(audit, 'fetch', side_effect=fake_fetch):
            self.assertEqual(audit.vendure_expected('https://x.com/shop-api', 'shirt'), 'InStock')
        self.assertEqual(len(calls), 2)
        pre = json.dumps({'data': {'product': {'variants': [{'stockLevel': '9', 'customFields': {'isPreOrder': True}},
                                                             {'stockLevel': '0', 'customFields': {'isPreOrder': False}}]}}})
        with patch.object(audit, 'fetch', return_value=(200, 'u', pre)):
            self.assertEqual(audit.vendure_expected('https://x.com/shop-api', 'bead'), 'PreOrder')

    def test_foreign_sitemap_hosts_and_new_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'site'
            (root / '.seo').mkdir(parents=True)
            (root / '.seo' / 'site.yaml').write_text(json.dumps({'domain': 'x.com', 'primary_conversions': ['purchase']}))
            sitemap = ('<urlset><url><loc>https://x.com/a/</loc></url><url><loc>https://x.com/b/</loc></url>'
                       '<url><loc>https://yoursitename.qwik.dev/c/</loc></url></urlset>')

            def fake_fetch(url, **kw):
                return (200, url, sitemap) if url.endswith('sitemap.xml') else (200, url, PAGE.replace('https://x.com/products/oni/', url))
            portfolio = Path(tmp) / 'portfolio.json'
            portfolio.write_text(json.dumps({'roots': [str(root)]}))
            reports = Path(tmp) / 'reports'
            prev = reports / 'audit-2026-01-01'
            prev.mkdir(parents=True)
            (prev / 'findings.json').write_text(json.dumps({'findings': [], 'sitemap_urls': {'x.com': ['https://x.com/a/']}}))
            with patch.object(audit, 'fetch', side_effect=fake_fetch):
                audit.main(['--portfolio', str(portfolio), '--reports-dir', str(reports), '--date', '2026-01-02'])
            doc = json.loads((reports / 'audit-2026-01-02' / 'findings.json').read_text())
        controls = {f['control'] for f in doc['findings']}
        self.assertIn('sitemap-foreign-hosts', controls)
        self.assertNotIn('canonical-missing', controls)
        self.assertEqual(doc['new_sitemap_urls']['x.com'], ['https://x.com/b/'])
        self.assertTrue(all(f['new'] for f in doc['findings']))


if __name__ == '__main__':
    unittest.main()
