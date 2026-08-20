"""The uploadable package: Cowork also accepts a plugin as a file."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.build_plugin_package import build

REPO = Path(__file__).resolve().parent.parent


class TestPluginPackage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.zip_path = build(REPO, Path(self.tmp.name) / "lupa.zip")
        self.archive = zipfile.ZipFile(self.zip_path)
        self.names = self.archive.namelist()

    def tearDown(self):
        self.archive.close()
        self.tmp.cleanup()

    def test_it_contains_a_single_top_level_folder(self):
        self.assertEqual({name.split("/")[0] for name in self.names}, {"lupa"})

    def test_it_carries_the_manifest_where_the_runtime_looks(self):
        self.assertIn("lupa/.claude-plugin/plugin.json", self.names)

    def test_it_carries_every_skill(self):
        for skill in ("index", "search", "cowork"):
            self.assertIn(f"lupa/skills/{skill}/SKILL.md", self.names)

    def test_it_carries_the_mcp_declaration_and_its_server(self):
        self.assertIn("lupa/.mcp.json", self.names)
        self.assertIn("lupa/server/lupa_mcp.py", self.names)

    def test_it_carries_the_code_the_server_imports(self):
        self.assertIn("lupa/lupa/mcp.py", self.names)
        self.assertIn("lupa/lupa/search.py", self.names)

    def test_it_leaves_out_tests_and_local_junk(self):
        self.assertFalse([n for n in self.names if "/tests/" in n])
        self.assertFalse([n for n in self.names if "__pycache__" in n])
        self.assertFalse([n for n in self.names if n.endswith(".db")])

    def test_it_stays_well_under_the_upload_limits(self):
        self.assertLess(self.zip_path.stat().st_size, 5_000_000)
        self.assertLess(len(self.names), 5_000)

    def test_the_manifest_is_valid_json_with_a_name(self):
        import json
        manifest = json.loads(self.archive.read("lupa/.claude-plugin/plugin.json"))
        self.assertEqual(manifest["name"], "lupa")


if __name__ == "__main__":
    unittest.main()
