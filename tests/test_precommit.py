from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / 'hooks' / 'pre_commit_seo_check.py'
spec = importlib.util.spec_from_file_location('seo_precommit_tests', HOOK)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
VALID = '<script type="application/ld+json">{"@context":"https://schema.org","@type":"HowTo","name":"Steps"}</script>'
INVALID = '<script type="application/ld+json">{invalid}</script>'


class PrecommitTests(unittest.TestCase):
    def git(self, root: Path, *args: str) -> None:
        subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)

    def test_staged_valid_schema_with_spaces_and_unstaged_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.git(root, 'init')
            page = root / 'page with spaces.html'
            page.write_text(VALID, encoding='utf-8')
            self.git(root, 'add', '--', page.name)
            page.write_text(INVALID, encoding='utf-8')
            result = module.staged_checks(root)
            self.assertEqual(result['status'], 'ok', result)
            self.assertEqual(result['checked'], 1)

    def test_staged_invalid_schema_cannot_hide_behind_unstaged_fix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.git(root, 'init')
            page = root / 'page.html'
            page.write_text(INVALID, encoding='utf-8')
            self.git(root, 'add', '--', page.name)
            page.write_text(VALID, encoding='utf-8')
            result = module.staged_checks(root)
            self.assertEqual(result['status'], 'failed')
            self.assertTrue(result['errors'])

    def test_no_staged_html_reports_zero_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.git(root, 'init')
            result = module.staged_checks(root)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['checked'], 0)

    def test_missing_repository_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            result = module.staged_checks(temp)
            self.assertEqual(result['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
