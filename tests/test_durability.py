"""Atomic writes, cache hygiene, and recovering from failed images."""
import json
import tempfile
import unittest
from pathlib import Path

from lupa.build import atomic_write
from lupa.recovery import forget_failed, read_failures


class TestAtomicWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "catalog.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_writes_the_content(self):
        atomic_write(self.path, "hello")
        self.assertEqual(self.path.read_text(), "hello")

    def test_it_replaces_previous_content(self):
        atomic_write(self.path, "first")
        atomic_write(self.path, "second")
        self.assertEqual(self.path.read_text(), "second")

    def test_a_crash_mid_write_leaves_the_old_file_intact(self):
        atomic_write(self.path, "good content")
        try:
            atomic_write(self.path, None)  # blows up while serializing
        except Exception:
            pass
        self.assertEqual(self.path.read_text(), "good content")

    def test_it_leaves_no_temporary_file_behind(self):
        atomic_write(self.path, "x")
        leftovers = [p.name for p in self.path.parent.iterdir() if p.name != "catalog.jsonl"]
        self.assertEqual(leftovers, [])

    def test_it_creates_missing_directories(self):
        deep = Path(self.tmp.name) / "a" / "b" / "c.txt"
        atomic_write(deep, "x")
        self.assertTrue(deep.exists())


class TestFailureRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        runs = self.dir / "runs"
        runs.mkdir()
        (runs / "2026-08-20T10-00-00.errors.jsonl").write_text(
            json.dumps({"id": "a", "file": "a.png", "error": "corrupted"}) + "\n")
        (runs / "2026-08-21T10-00-00.errors.jsonl").write_text(
            json.dumps({"id": "b", "file": "b.png", "error": "timeout"}) + "\n"
            + json.dumps({"id": "c", "file": "c.png", "error": "quota"}) + "\n")
        (self.dir / "MANIFEST.json").write_text(json.dumps(
            {"items": {"a": {"hash": "1"}, "b": {"hash": "2"}, "z": {"hash": "9"}}}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_collects_failures_from_every_run(self):
        self.assertEqual(sorted(read_failures(self.dir)), ["a", "b", "c"])

    def test_no_failure_files_means_no_failures(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(read_failures(empty), [])

    def test_forgetting_a_failure_makes_it_new_again(self):
        # dropping the id from the manifest is what turns it back into "added"
        removed = forget_failed(self.dir, ["a", "b"])
        manifest = json.loads((self.dir / "MANIFEST.json").read_text())
        self.assertEqual(sorted(manifest["items"]), ["z"])
        self.assertEqual(removed, 2)

    def test_forgetting_an_unknown_id_is_harmless(self):
        self.assertEqual(forget_failed(self.dir, ["nope"]), 0)

    def test_forgetting_nothing_changes_nothing(self):
        forget_failed(self.dir, [])
        manifest = json.loads((self.dir / "MANIFEST.json").read_text())
        self.assertEqual(sorted(manifest["items"]), ["a", "b", "z"])


if __name__ == "__main__":
    unittest.main()
