"""Archive qualification must compare canonical roots without accepting other sites."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
from qualify_package import validate_discovery


class PackagePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.site = self.root / 'site'
        self.site.mkdir()
        (self.root / 'intermediate').mkdir()
        self.result = {'status': 'ok', 'roots': [str(self.site)]}

    def test_canonical_root_passes(self):
        validate_discovery(self.result, self.site)

    def test_expected_path_alias_is_resolved(self):
        alias = self.root / 'intermediate' / '..' / 'site'
        self.assertNotEqual(str(alias), str(self.site))
        validate_discovery(self.result, alias)

    def test_incomplete_wrong_or_extra_roots_remain_rejected(self):
        cases = [
            {'status': 'partial', 'roots': [str(self.site)]},
            {'status': 'ok', 'roots': [str(self.root / 'other')]},
            {'status': 'ok', 'roots': [str(self.site), str(self.site)]},
            {'status': 'ok', 'roots': []},
        ]
        for result in cases:
            with self.subTest(result=result), self.assertRaises(AssertionError):
                validate_discovery(result, self.site)

    def test_noncanonical_returned_root_is_not_silently_accepted(self):
        alias = self.root / 'intermediate' / '..' / 'site'
        with self.assertRaises(AssertionError):
            validate_discovery({'status': 'ok', 'roots': [str(alias)]}, self.site)


if __name__ == '__main__':
    unittest.main()
