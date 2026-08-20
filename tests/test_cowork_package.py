"""The Cowork face ships as a zip: Claude.ai and Cowork install skills that way."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.build_cowork_skill import build

REPO = Path(__file__).resolve().parent.parent


class TestCoworkPackage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.zip_path = build(REPO, Path(self.tmp.name) / "lupa-cowork.zip")
        self.archive = zipfile.ZipFile(self.zip_path)

    def tearDown(self):
        self.archive.close()
        self.tmp.cleanup()

    def test_the_archive_exists(self):
        self.assertTrue(self.zip_path.exists())

    def test_it_contains_a_single_top_level_folder(self):
        roots = {name.split("/")[0] for name in self.archive.namelist()}
        self.assertEqual(len(roots), 1)

    def test_the_skill_file_sits_inside_that_folder(self):
        self.assertIn("lupa-cowork/SKILL.md", self.archive.namelist())

    def test_the_skill_keeps_its_frontmatter(self):
        body = self.archive.read("lupa-cowork/SKILL.md").decode("utf-8")
        self.assertTrue(body.startswith("---"))
        self.assertIn("name:", body)
        self.assertIn("description:", body)

    def test_it_carries_the_schema_so_the_agent_can_read_the_catalog(self):
        self.assertIn("lupa-cowork/index-v1.json", self.archive.namelist())

    def test_it_does_not_ship_code_the_cowork_face_cannot_run(self):
        names = self.archive.namelist()
        self.assertFalse([n for n in names if n.endswith(".py")])

    def test_the_archive_is_small_enough_to_upload(self):
        self.assertLess(self.zip_path.stat().st_size, 100_000)


if __name__ == "__main__":
    unittest.main()
