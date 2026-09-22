"""Actual queue/public verifier regressions; only HTTP is simulated."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import content_queue as queue
import public_verify
from seo_project import setup_project, save_site


class IntendedRepairVerification(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        site = setup_project(self.root, domain='example.com', market='IN', language='en')
        site['policy'] = {'mode': 'approved', 'approval_ref': 'fixture',
                          'allowed_actions': ['metadata', 'rollback'], 'write_prefixes': ['content']}
        save_site(site, self.root)
        self.url = 'https://example.com/page'
        self.old = self.html('Old title', 'Old description', 'Old heading')
        self.new = self.html('New title', 'New description', 'New heading')
        (self.root / 'content').mkdir()
        (self.root / 'content/page.html').write_text(self.old, encoding='utf-8')
        proposal = queue.propose(self.root, 'repair', path='content/page.html', content=self.new,
                                 url=self.url, kind='metadata', evidence='reviewed metadata repair')
        queue.approve(self.root, 'repair', content_sha256=proposal['content_sha256'], approval_ref='fixture')
        queue.apply(self.root, 'repair')
        self.plan = {'content': self.new, 'expected_text': 'Unchanged factual body.'}

    def html(self, title, description, heading):
        return (f'<html><head><title>{title}</title><meta name="description" content="{description}">'
                f'<link rel="canonical" href="{self.url}"></head><body><h1>{heading}</h1>'
                '<p>Unchanged factual body.</p></body></html>')

    def verify(self, body):
        return public_verify.verify(self.root, 'repair', self.plan,
            fetcher=lambda url: {'url': url, 'status': 200, 'body': body, 'headers': {}})

    def test_unchanged_body_does_not_prove_metadata_repair(self):
        result = self.verify(self.old)
        self.assertTrue(result['assertions']['visible_expected_text'])
        self.assertFalse(result['passed'])
        self.assertFalse(result['assertions']['approved_titles'])
        self.assertFalse(result['assertions']['approved_descriptions'])
        self.assertFalse(result['assertions']['approved_headings'])
        self.assertEqual(json.loads(queue.item_path(self.root, 'repair').read_text())['status'], 'applied')

    def test_exact_metadata_repair_passes(self):
        self.assertTrue(self.verify(self.new)['passed'])

    def test_content_cli_verifier_also_checks_repaired_metadata(self):
        result = queue.verify(self.root, 'repair', expected_text=self.plan['expected_text'],
            fetcher=lambda url: {'url': url, 'status': 200, 'body': self.old})
        self.assertFalse(result['passed'])

    def test_head_text_does_not_count_as_visible_body(self):
        page = public_verify.Page(); page.feed('<head><title>Hidden title</title></head><body>Visible</body>')
        self.assertEqual(' '.join(page.text), 'Visible')

    def test_duplicate_title_cannot_mask_old_metadata(self):
        self.assertFalse(self.verify(self.new.replace('</head>', '<title>Old title</title></head>'))['passed'])

    def test_metadata_removal_is_checked(self):
        previous = '<meta name="description" content="Removed">'
        observed = public_verify.Page(); observed.feed(previous)
        self.assertFalse(public_verify.metadata_assertions('<p>Body</p>', previous, observed)['approved_descriptions'])

    def test_verification_rejects_changed_content_material(self):
        path = queue.item_path(self.root, 'repair')
        row = json.loads(path.read_text(encoding='utf-8')); row['content'] = self.old
        path.write_text(json.dumps(row), encoding='utf-8')
        with self.assertRaises(PermissionError):
            self.verify(self.old)

    def test_native_title_and_supporting_sitemap_have_specific_public_checks(self):
        plan = {'path': 'content/page.tsx', 'content': "export const head = {title: 'New title'}; // Unchanged factual body.",
                'supporting_changes': [{'path': 'content/sitemap.xml',
                    'content': '<urlset><url><loc>https://example.com/page</loc></url></urlset>'}],
                'verification': [
                    {'path': 'content/page.tsx', 'url': self.url, 'kind': 'title', 'value': 'New title'},
                    {'path': 'content/sitemap.xml', 'url': 'https://example.com/sitemap.xml',
                     'kind': 'sitemap_url', 'value': self.url}]}
        checks = public_verify.validate_contract(self.root, plan, self.url)
        self.assertFalse(public_verify.check_response(checks[0], {'url': self.url, 'status': 200, 'body': self.old}))
        self.assertTrue(public_verify.check_response(checks[0], {'url': self.url, 'status': 200, 'body': self.new}))
        response = {'url': checks[1]['url'], 'status': 200, 'body': '<urlset><url><loc>https://example.com/old</loc></url></urlset>'}
        self.assertFalse(public_verify.check_response(checks[1], response))
        response['body'] = plan['supporting_changes'][0]['content']
        self.assertTrue(public_verify.check_response(checks[1], response))
        plan['verification'].pop()
        with self.assertRaises(ValueError):
            public_verify.validate_contract(self.root, plan, self.url)


if __name__ == '__main__':
    unittest.main()
