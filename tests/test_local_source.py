"""Local folder source: same interface as Drive, with no credentials at all."""
import struct
import tempfile
import unittest
from pathlib import Path
from lupa.local_source import LocalSource


def png(w=1080, h=1350):
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
            + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00" + b"resto")


class TestLocalSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        (self.folder / "a.png").write_bytes(png(1080, 1350))
        (self.folder / "b.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        (self.folder / "readme.txt").write_text("not an image")
        (self.folder / "sub").mkdir()
        (self.folder / "sub" / "c.png").write_bytes(png(800, 600))
        (self.folder / "_lupa").mkdir()
        (self.folder / "_lupa" / "contact.png").write_bytes(png(100, 100))
        self.source = LocalSource(self.folder)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_images_only(self):
        names = sorted(f["file"] for f in self.source.list())
        self.assertNotIn("readme.txt", names)

    def test_walks_subfolders(self):
        self.assertIn("sub/c.png", [f["id"] for f in self.source.list()])

    def test_skips_its_own_index_folder(self):
        ids = [f["id"] for f in self.source.list()]
        self.assertFalse(any(i.startswith("_lupa") for i in ids))

    def test_reads_dimensions_from_the_file(self):
        a = [f for f in self.source.list() if f["file"] == "a.png"][0]
        self.assertEqual((a["w"], a["h"]), (1080, 1350))

    def test_hash_changes_when_the_file_changes(self):
        before = {f["id"]: f["hash"] for f in self.source.list()}
        (self.folder / "a.png").write_bytes(png(1080, 1350) + b"mais bytes")
        after = {f["id"]: f["hash"] for f in self.source.list()}
        self.assertNotEqual(before["a.png"], after["a.png"])

    def test_hash_is_stable_when_nothing_changes(self):
        self.assertEqual([f["hash"] for f in self.source.list()],
                         [f["hash"] for f in self.source.list()])

    def test_url_points_at_the_file_on_disk(self):
        a = [f for f in self.source.list() if f["file"] == "a.png"][0]
        self.assertTrue(a["url"].startswith("file://"))

    def test_no_ocr_because_a_local_folder_has_none(self):
        self.assertEqual(self.source.list()[0]["ocr_text"], "")

    def test_fetch_returns_bytes_and_mime(self):
        data, mime = self.source.fetch("a.png")
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertEqual(mime, "image/png")

    def test_empty_folder_returns_an_empty_list(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(LocalSource(empty).list(), [])


if __name__ == "__main__":
    unittest.main()


class TestRecursionSwitch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        (self.folder / "top.png").write_bytes(png())
        (self.folder / "sub").mkdir()
        (self.folder / "sub" / "deep.png").write_bytes(png())

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_branches_by_default(self):
        ids = [f["id"] for f in LocalSource(self.folder).list()]
        self.assertEqual(sorted(ids), ["sub/deep.png", "top.png"])

    def test_recursion_can_be_turned_off(self):
        ids = [f["id"] for f in LocalSource(self.folder, recursive=False).list()]
        self.assertEqual(ids, ["top.png"])
