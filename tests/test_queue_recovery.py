"""Crash recovery preserves both original bytes and unrelated later edits."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import content_queue as queue
from seo_project import setup_project, save_site


class QueueRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        site = setup_project(self.root, domain='example.com', market='IN', language='en')
        site['policy'] = {'mode': 'approved', 'approval_ref': 'fixture',
                         'allowed_actions': ['metadata', 'rollback'], 'write_prefixes': ['content']}
        save_site(site, self.root)
        self.target = self.root / 'content/page.html'
        self.target.parent.mkdir(); self.target.write_text('old', encoding='utf-8')

    def propose(self):
        return queue.propose(self.root, 'repair', path='content/page.html', content='new',
                             kind='metadata', url='https://example.com/page', evidence='review')

    def apply(self):
        proposal = self.propose()
        queue.approve(self.root, 'repair', content_sha256=proposal['content_sha256'], approval_ref='fixture')
        queue.apply(self.root, 'repair')

    def test_approval_rejects_concurrent_edit(self):
        proposal = self.propose(); self.target.write_text('other', encoding='utf-8')
        with self.assertRaises(ValueError):
            queue.approve(self.root, 'repair', content_sha256=proposal['content_sha256'], approval_ref='fixture')
        self.assertEqual(json.loads(queue.item_path(self.root, 'repair').read_text())['status'], 'proposed')

    def interrupt_rollback(self):
        original = queue.atomic_json
        def save(path, row):
            if row.get('status') == 'rolled_back':
                raise KeyboardInterrupt('crash after filesystem mutation')
            return original(path, row)
        with patch.object(queue, 'atomic_json', side_effect=save):
            with self.assertRaises(KeyboardInterrupt):
                queue.rollback(self.root, 'repair')

    def test_existing_file_rollback_resumes_after_restore(self):
        self.apply(); self.interrupt_rollback()
        self.assertEqual(self.target.read_text(), 'old')
        self.assertEqual(queue.rollback(self.root, 'repair')['kind'], 'local_file_rollback')
        self.assertEqual(queue.rollback(self.root, 'repair')['kind'], 'local_file_rollback')

    def test_new_file_rollback_resumes_after_unlink(self):
        self.target.unlink(); self.apply(); self.interrupt_rollback()
        self.assertFalse(self.target.exists())
        queue.rollback(self.root, 'repair')
        self.assertFalse(self.target.exists())

    def test_interrupted_rollback_never_overwrites_later_edit(self):
        self.apply(); self.interrupt_rollback(); self.target.write_text('other', encoding='utf-8')
        with self.assertRaises(ValueError):
            queue.rollback(self.root, 'repair')
        self.assertEqual(self.target.read_text(), 'other')


if __name__ == '__main__':
    unittest.main()
