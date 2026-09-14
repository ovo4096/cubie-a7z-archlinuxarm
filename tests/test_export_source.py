"""Small source-export policy tests; inspect categories, never secret values."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("export_source", Path(__file__).resolve().parents[1] / "tools/export_source.py")
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


class ExportSourceTests(unittest.TestCase):
    def test_plan_missing_required_file_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = exporter.export(root, root / "export", ("THIRD-PARTY-LICENSES.zh-CN.md",), plan=True)
            self.assertFalse(report["ready"])
            self.assertEqual(report["missing_files"], ["THIRD-PARTY-LICENSES.zh-CN.md"])
            self.assertFalse((root / "export").exists())

    def test_whitelist_excludes_unrelated_files_and_source_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("Public source\n")
            (root / "private-data.txt").write_text("must stay local")
            output = root / "export"
            result = exporter.export(root, output, ("README.md",))
            self.assertTrue(result["ready"])
            self.assertEqual(sorted(p.name for p in output.iterdir()), ["README.md", "SHA256SUMS", "SOURCE-MANIFEST.json"])
            self.assertNotIn(str(root), (output / "SOURCE-MANIFEST.json").read_text())
            with self.assertRaises(ValueError):
                exporter.export(root, output, ("README.md",))
            self.assertEqual((output / "README.md").read_text(), "Public source\n")

    def test_secrets_are_reported_by_category_without_value(self):
        # Construct artificial values so no credential/private host is embedded
        # as an actual exportable source literal.
        fixture = ".".join(("192", "168", "99", "9"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(fixture)
            result = exporter.export(root, root / "export", ("README.md",))
            self.assertFalse(result["ready"])
            serialized = json.dumps(result)
            self.assertNotIn(fixture, serialized)
            self.assertIn("private-ipv4", serialized)
            self.assertFalse((root / "export").exists())

    def test_excluded_local_links_block_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("[private report](diagnostics/report.json)\n")
            report = exporter.export(root, root / "export", ("README.md",))
            self.assertFalse(report["ready"])
            self.assertEqual(report["findings"][0]["category"], "local-link-outside-source-allowlist")

    def test_symlink_and_binary_payload_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "actual").write_bytes(b"\x00payload")
            report = exporter.export(root, root / "export", ("actual",))
            self.assertFalse(report["ready"])
            try:
                (root / "link").symlink_to(root / "actual")
            except OSError:
                return
            report = exporter.export(root, root / "export", ("link",))
            self.assertEqual(report["findings"][0]["category"], "not-a-contained-regular-file")


if __name__ == "__main__":
    unittest.main()
