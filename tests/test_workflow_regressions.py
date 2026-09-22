"""Focused interruption regressions for resumable workflow advancement."""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import seo_workflow as workflow
import media_assets
from seo_project import save_site, setup_project


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


class WorkflowInterruptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        site = setup_project(self.root, domain='example.com', market='IN', language='en',
                             gsc_property='sc-domain:example.com')
        site.update({
            'policy': {'mode': 'approved', 'approval_ref': 'operator-policy',
                       'allowed_actions': ['metadata', 'publish'],
                       'write_prefixes': ['content']},
            'workflow': {'enabled': True, 'approval_ref': 'operator-workflow',
                         'auto_approve_kinds': ['metadata']},
        })
        save_site(site, self.root)
        (self.root / 'content').mkdir()
        (self.root / 'content' / 'page.html').write_text('old', encoding='utf-8')
        self.task = workflow.enqueue(self.root, target='https://example.com/page',
                                     kind='metadata', issue='missing title', evidence='audit',
                                     now=NOW)['id']
        self.plan = {
            'schema_version': 1, 'task_id': self.task, 'decision': 'change',
            'reason': 'repair title', 'path': 'content/page.html',
            'content': '<title>New</title>visible', 'expected_text': 'visible',
            'review': {'facts': 'pass', 'intent': 'pass', 'links': 'pass',
                       'preview': 'pass', 'evidence': 'review'},
            'media_ids': [],
            'verification': [{'path': 'content/page.html', 'url': 'https://example.com/page',
                              'kind': 'text', 'value': 'visible'}],
        }

    def test_deployed_receipt_is_reused_after_ledger_crash(self):
        receipt = {'state': 'deployed', 'identity': 'revision-1',
                   'effect_receipt': 'remote-effect-1', 'rollback': 'reverse-1'}
        calls = []

        def publish(*args):
            calls.append('publish')
            return copy.deepcopy(receipt)

        def crash(*args, **kwargs):
            raise KeyboardInterrupt('process interruption')

        with patch.object(workflow.ops, 'cmd_deploy', side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                workflow.advance(self.root, self.task, now=NOW,
                                 host=lambda *a: self.plan,
                                 publisher=publish,
                                 verifier=lambda *a: {'passed': True},
                                 measurer=lambda *a: {'status': 'ok', 'target': a[1],
                                                       'lane': 'gsc', 'data': {}})

        row = workflow.find(workflow.ops.load_state(workflow.ledger(self.root)), self.task)
        self.assertEqual(row['workflow']['stage'], 'applied')
        self.assertEqual(row['workflow']['publication'], receipt)

        result = workflow.advance(self.root, self.task, now=NOW,
                                  publisher=lambda *a: self.fail('remote publication must not repeat'),
                                  verifier=lambda *a: {'passed': True},
                                  measurer=lambda *a: {'status': 'ok', 'target': a[1],
                                                        'lane': 'gsc', 'data': {}})
        self.assertEqual(result['stage'], 'awaiting_outcome')
        self.assertEqual(calls, ['publish'])

    def test_supporting_changes_use_bound_queue_items_and_apply_together(self):
        plan = copy.deepcopy(self.plan)
        plan['supporting_changes'] = [{'path': 'content/sitemap.xml',
                                       'content': '<urlset><url><loc>https://example.com/page</loc></url></urlset>'}]
        plan['verification'].append({'path': 'content/sitemap.xml',
                                     'url': 'https://example.com/sitemap.xml',
                                     'kind': 'sitemap_url', 'value': 'https://example.com/page'})
        result = workflow.advance(self.root, self.task, now=NOW,
                                  host=lambda *a: plan,
                                  publisher=lambda *a: {'state': 'deployed', 'identity': 'r1',
                                                        'effect_receipt': 'e1', 'rollback': 'b1'},
                                  verifier=lambda *a: {'passed': True},
                                  measurer=lambda *a: {'status': 'ok', 'target': a[1],
                                                        'lane': 'gsc', 'data': {}})
        self.assertEqual(result['stage'], 'awaiting_outcome')
        self.assertEqual((self.root / 'content' / 'sitemap.xml').read_text(encoding='utf-8'),
                         '<urlset><url><loc>https://example.com/page</loc></url></urlset>')
        row = workflow.find(workflow.ops.load_state(workflow.ledger(self.root)), self.task)
        self.assertEqual(row['workflow']['supporting_tasks'][0]['id'], self.task + '-file-0')

    def test_primary_media_assertion_is_not_shadowed_by_supporting_content(self):
        plan = copy.deepcopy(self.plan)
        plan['media_ids'] = ['hero']
        plan['content'] += ' https://example.com/hero.png Actual hero'
        plan['supporting_changes'] = [{'path': 'content/sitemap.xml',
                                       'content': '<urlset><url><loc>https://example.com/page</loc></url></urlset>'}]
        plan['verification'].append({'path': 'content/sitemap.xml',
                                     'url': 'https://example.com/sitemap.xml',
                                     'kind': 'sitemap_url', 'value': 'https://example.com/page'})
        with patch.object(media_assets, 'read', return_value={
                'public_url': 'https://example.com/hero.png', 'alt': 'Actual hero',
                'role': 'featured'}):
            row = workflow.find(workflow.ops.load_state(workflow.ledger(self.root)), self.task)
            workflow.validate_plan(self.root, row, plan, now=NOW)

    def test_resume_after_supporting_apply_interruption_finishes_before_publish(self):
        plan = copy.deepcopy(self.plan)
        plan['supporting_changes'] = [{'path': 'content/sitemap.xml',
                                       'content': '<urlset><url><loc>https://example.com/page</loc></url></urlset>'}]
        plan['verification'].append({'path': 'content/sitemap.xml',
                                     'url': 'https://example.com/sitemap.xml',
                                     'kind': 'sitemap_url', 'value': 'https://example.com/page'})
        original_apply = workflow.queue.apply
        calls = []

        def apply_then_interrupt(root, item_id):
            calls.append(item_id)
            result = original_apply(root, item_id)
            if len(calls) == 2:
                raise KeyboardInterrupt('process interruption')
            return result

        with patch.object(workflow.queue, 'apply', side_effect=apply_then_interrupt):
            with self.assertRaises(KeyboardInterrupt):
                workflow.advance(self.root, self.task, now=NOW, host=lambda *a: plan,
                                 measurer=lambda *a: {'status': 'ok', 'target': a[1],
                                                       'lane': 'gsc', 'data': {}})
        result = workflow.advance(self.root, self.task, now=NOW,
                                  publisher=lambda *a: {'state': 'deployed', 'identity': 'r1',
                                                        'effect_receipt': 'e1', 'rollback': 'b1'},
                                  verifier=lambda *a: {'passed': True},
                                  measurer=lambda *a: {'status': 'ok', 'target': a[1],
                                                        'lane': 'gsc', 'data': {}})
        self.assertEqual(result['stage'], 'awaiting_outcome')
        self.assertEqual(calls[:2], [self.task, self.task + '-file-0'])


if __name__ == '__main__':
    unittest.main()
