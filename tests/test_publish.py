"""Publishing the index to Drive: round trips are the cost here."""
import tempfile
import unittest
from pathlib import Path

from lupa.publish import plan_uploads


class TestUploadPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "INDEX.md").write_text("x")
        (self.dir / "catalog.jsonl").write_text("x")
        (self.dir / "by-tag").mkdir()
        (self.dir / "by-tag" / "food.md").write_text("x")
        (self.dir / "runs").mkdir()
        (self.dir / "runs" / "r.md").write_text("x")
        (self.dir / ".backup").mkdir()
        (self.dir / ".backup" / "old.md").write_text("x")
        (self.dir / ".thumbs").mkdir()
        (self.dir / ".thumbs" / "a.jpg").write_text("x")
        (self.dir / ".lock").write_text("x")
        (self.dir / "index.db").write_text("x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_uploads_the_index_files(self):
        names = {path.name for path, _ in plan_uploads(self.dir)}
        self.assertIn("INDEX.md", names)
        self.assertIn("catalog.jsonl", names)

    def test_it_keeps_the_folder_structure(self):
        folders = {folder for _, folder in plan_uploads(self.dir)}
        self.assertIn("by-tag", folders)
        self.assertIn("", folders)

    def test_it_never_uploads_the_backup(self):
        self.assertNotIn(".backup", {folder for _, folder in plan_uploads(self.dir)})

    def test_it_never_uploads_the_lock(self):
        self.assertNotIn(".lock", {path.name for path, _ in plan_uploads(self.dir)})

    def test_it_never_uploads_derived_data(self):
        # the database and the curation thumbnails are rebuildable locally
        names = {path.name for path, _ in plan_uploads(self.dir)}
        self.assertNotIn("index.db", names)
        folders = {folder for _, folder in plan_uploads(self.dir)}
        self.assertNotIn(".thumbs", folders)

    def test_the_plan_is_deterministic(self):
        self.assertEqual(plan_uploads(self.dir), plan_uploads(self.dir))


if __name__ == "__main__":
    unittest.main()
