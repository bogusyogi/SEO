import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.link_import import import_rows


class LinkImportTests(unittest.TestCase):
    def write_csv(self, root: Path, name: str, rows: list[dict], encoding: str = "utf-8-sig") -> Path:
        path = root / name
        with path.open("w", encoding=encoding, newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_links_preserve_unknown_target_deduplicate_and_write_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".seo").mkdir()
            (root / ".seo" / "site.yaml").write_text(json.dumps({"domain": "example.com"}), encoding="utf-8")
            source = self.write_csv(root, "links.csv", [
                {"Source URL": "https://news.example/story", "Target URL": "", "Anchor Text": "=cmd"},
                {"Source URL": "https://news.example/story", "Target URL": "", "Anchor Text": "duplicate"},
                {"Source URL": "https://blog.example/post", "Target URL": "https://example.com/page", "Anchor Text": "Read"},
            ])
            result = import_rows(root, source, "auto", collected_at="2026-09-22T00:00:00Z")
            self.assertEqual(result["site"], "example.com")
            self.assertEqual(result["collected_at"], "2026-09-22T00:00:00Z")
            self.assertEqual(result["coverage"], {"complete": False, "scope": "gsc-links", "source_rows": 3})
            self.assertEqual(len(result["rows"]), 2)
            self.assertIsNone(result["rows"][0]["target_url"])
            self.assertIsNone(result["rows"][0]["anchor"])
            self.assertEqual(result["domains"], [{"domain": "blog.example", "links": 1}, {"domain": "news.example", "links": 1}])
            saved = json.loads((root / ".seo" / "reports" / "gsc-links.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["rows"], result["rows"])

    def test_domains_preserve_measured_zero_and_unknown_collection_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.write_csv(root, "domains.csv", [
                {"Top linking sites": "zero.example", "Links": "0"},
                {"Top linking sites": "one.example", "Links": "1,200"},
            ])
            result = import_rows(root, source, "auto")
            self.assertEqual(result["coverage"]["scope"], "gsc-domains")
            self.assertEqual(result["collected_at"], "unknown")
            self.assertEqual(result["rows"], [])
            self.assertEqual(result["domains"], [{"domain": "one.example", "links": 1200}, {"domain": "zero.example", "links": 0}])
            self.assertEqual(result["referring_domains"], 2)

    def test_rejects_unsafe_url_and_row_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unsafe = self.write_csv(root, "unsafe.csv", [{"Source URL": "javascript:alert(1)", "Target URL": ""}])
            with self.assertRaises(ValueError):
                import_rows(root, unsafe, "gsc-links")
            many = self.write_csv(root, "many.csv", [{"Source URL": "https://example.com/1", "Target URL": ""}, {"Source URL": "https://example.com/2", "Target URL": ""}])
            with self.assertRaises(ValueError):
                import_rows(root, many, "gsc-links", max_rows=1)


if __name__ == "__main__":
    unittest.main()
