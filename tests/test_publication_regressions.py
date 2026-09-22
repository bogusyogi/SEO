"""Focused multi-file publication regressions."""
from __future__ import annotations
import json
import unittest

import content_queue as queue
import github_publication as gh
import remote_actions as actions
from seo_state import atomic_json
from seo_project import save_site
import test_github_publication as github_fixtures


class MultiFilePublicationTests(unittest.TestCase):
    def setUp(self):
        github_fixtures.PublicationTests.setUp(self)

    def add_supporting(self, identifier='page-file-0', *, url='https://example.com/page', kind='metadata'):
        path = self.root / 'content' / 'routes.xml'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('old route', encoding='utf-8')
        proposal = queue.propose(self.root, identifier, path='content/routes.xml',
            content='new route', url=url, kind=kind, evidence='approved-review')
        queue.approve(self.root, identifier, content_sha256=proposal['content_sha256'], approval_ref='operator')
        queue.apply(self.root, identifier)
        self.api.entries['content/routes.xml'] = {'sha': gh.git_blob(b'old route'), 'mode': '100644', 'type': 'blob'}

    def test_supporting_queue_items_share_url_and_publish_one_tree(self):
        self.add_supporting()
        proposal = gh.prepare(self.root, 'multi', 'page', supporting_task_ids=['page-file-0'],
            evidence='approved-review', transport=self.api)
        row = actions.read(self.root, 'multi')
        self.assertEqual(row['payload']['task_ids'], ['page', 'page-file-0'])
        self.assertEqual({item['path'] for item in row['payload']['files']},
                         {'content/page.html', 'content/routes.xml'})
        actions.approve(self.root, 'multi', proposal['request_sha256'], 'operator')
        self.assertEqual(gh.apply(self.root, 'multi', transport=self.api)['state'], 'succeeded')

    def test_supporting_queue_item_with_different_url_is_rejected(self):
        self.add_supporting(url='https://example.com/other')
        with self.assertRaises(ValueError):
            gh.prepare(self.root, 'multi', 'page', supporting_task_ids=['page-file-0'],
                       evidence='approved-review', transport=self.api)

    def test_supporting_queue_item_with_different_kind_is_rejected(self):
        self.add_supporting(kind='content')
        with self.assertRaises(ValueError):
            gh.prepare(self.root, 'multi', 'page', supporting_task_ids=['page-file-0'],
                       evidence='approved-review', transport=self.api)

    def test_tampered_supporting_content_is_rejected(self):
        self.add_supporting()
        path = queue.item_path(self.root, 'page-file-0')
        row = json.loads(path.read_text(encoding='utf-8'))
        row['content'] = 'tampered route'
        atomic_json(path, row)
        with self.assertRaises(ValueError):
            gh.prepare(self.root, 'multi', 'page', supporting_task_ids=['page-file-0'],
                       evidence='approved-review', transport=self.api)

    def test_repository_subdir_maps_local_sources_to_remote_tree(self):
        self.site['deployment']['repository_subdir'] = 'coderight'
        save_site(self.site, self.root)
        page = self.root / 'content' / 'page.html'
        page.write_text('old content', encoding='utf-8')
        queue.item_path(self.root, 'page').unlink()
        proposal = queue.propose(self.root, 'page', path='content/page.html',
            content='new reviewed content', url='https://example.com/page', kind='metadata', evidence='approved-review')
        queue.approve(self.root, 'page', content_sha256=proposal['content_sha256'], approval_ref='operator')
        queue.apply(self.root, 'page')
        self.add_supporting()
        self.api.entries = {
            'coderight/content/page.html': {'sha': gh.git_blob(b'old content'), 'mode': '100644', 'type': 'blob'},
            'coderight/content/routes.xml': {'sha': gh.git_blob(b'old route'), 'mode': '100644', 'type': 'blob'},
            'coderight/content/other.html': {'sha': gh.git_blob(b'unrelated'), 'mode': '100644', 'type': 'blob'},
        }
        proposal = gh.prepare(self.root, 'subdir', 'page', supporting_task_ids=['page-file-0'],
                              evidence='approved-review', transport=self.api)
        payload = actions.read(self.root, 'subdir')['payload']
        self.assertEqual({item['path'] for item in payload['files']},
                         {'coderight/content/page.html', 'coderight/content/routes.xml'})
        self.assertEqual(payload['files'][0]['source_path'], 'content/page.html')
        actions.approve(self.root, 'subdir', proposal['request_sha256'], 'operator')
        self.assertEqual(gh.apply(self.root, 'subdir', transport=self.api)['state'], 'succeeded')

    def test_invalid_repository_subdir_is_rejected(self):
        self.site['deployment']['repository_subdir'] = '../coderight'
        save_site(self.site, self.root)
        with self.assertRaises(ValueError):
            gh.GitHub(self.site, self.api)

    def test_multi_file_rollback_restores_sources_and_keeps_unrelated_file(self):
        self.add_supporting()
        proposal = gh.prepare(self.root, 'multi', 'page', supporting_task_ids=['page-file-0'],
            evidence='approved-review', transport=self.api)
        actions.approve(self.root, 'multi', proposal['request_sha256'], 'operator')
        gh.apply(self.root, 'multi', transport=self.api)
        self.merge_id = 'multi-merge'
        merge = gh.prepare_merge(self.root, self.merge_id, 'multi', evidence='passing build', transport=self.api)
        actions.approve(self.root, self.merge_id, merge['request_sha256'], 'operator-merge')
        gh.apply(self.root, self.merge_id, transport=self.api)
        self.api.entries['content/other.html']['sha'] = gh.git_blob(b'new unrelated change')
        rollback = gh.prepare_rollback(self.root, 'multi', 'restore', evidence='operator recovery', transport=self.api)
        payload = actions.read(self.root, 'restore')['payload']
        self.assertEqual({item['path'] for item in payload['files']},
                         {'content/page.html', 'content/routes.xml'})
        actions.approve(self.root, 'restore', rollback['request_sha256'], 'operator')
        self.assertEqual(gh.apply(self.root, 'restore', transport=self.api)['state'], 'succeeded')
        self.assertEqual(self.api.new_entries['content/page.html']['sha'], gh.git_blob(b'old content'))
        self.assertEqual(self.api.new_entries['content/routes.xml']['sha'], gh.git_blob(b'old route'))
        self.assertEqual(self.api.new_entries['content/other.html']['sha'], gh.git_blob(b'new unrelated change'))


if __name__ == '__main__':
    unittest.main()
