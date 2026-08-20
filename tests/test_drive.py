"""Reading Drive: parsing the metadata the API returns."""
import unittest
from lupa.drive import split_ocr_and_labels, normalize_file, folder_query

REAL_SNIPPET = (
    "MIGRATION\n\nPutting off modernization\n\nout of fear of downtime is also a risk.\n"
    "\n  \n  \nImage labels: \\[Bridge; Cable-stayed bridge; Technology; Diagram\\]"
)


class TestSnippet(unittest.TestCase):
    def test_it_extracts_the_ocr_text_without_the_labels(self):
        ocr, _ = split_ocr_and_labels(REAL_SNIPPET)
        self.assertIn("MIGRATION", ocr)
        self.assertNotIn("Image labels", ocr)
        self.assertNotIn("Bridge", ocr)

    def test_it_extracts_the_label_list(self):
        _, labels = split_ocr_and_labels(REAL_SNIPPET)
        self.assertEqual(labels, ["Bridge", "Cable-stayed bridge", "Technology", "Diagram"])

    def test_a_snippet_without_labels_returns_an_empty_list(self):
        ocr, labels = split_ocr_and_labels("just text here")
        self.assertEqual(ocr, "just text here")
        self.assertEqual(labels, [])

    def test_an_empty_snippet_does_not_crash(self):
        self.assertEqual(split_ocr_and_labels(""), ("", []))

    def test_a_missing_snippet_does_not_crash(self):
        self.assertEqual(split_ocr_and_labels(None), ("", []))

    def test_unescaped_labels_work_too(self):
        _, labels = split_ocr_and_labels("txt\nImage labels: [Food; Table]")
        self.assertEqual(labels, ["Food", "Table"])


class TestNormalization(unittest.TestCase):
    def test_it_maps_the_api_fields(self):
        raw = {
            "id": "1a2B", "name": "post-24.png", "mimeType": "image/png",
            "md5Checksum": "abc123", "size": "4321764",
            "imageMediaMetadata": {"width": 1080, "height": 1350},
            "webViewLink": "https://drive.google.com/file/d/1a2B/view",
        }
        entry = normalize_file(raw)
        self.assertEqual(entry["id"], "1a2B")
        self.assertEqual(entry["file"], "post-24.png")
        self.assertEqual(entry["hash"], "abc123")
        self.assertEqual((entry["w"], entry["h"]), (1080, 1350))
        self.assertEqual(entry["url"], "https://drive.google.com/file/d/1a2B/view")

    def test_without_md5_it_fingerprints_size_and_date(self):
        # Google Docs and some formats carry no md5Checksum
        entry = normalize_file({"id": "x", "name": "a.png", "size": "100",
                                "modifiedTime": "2026-08-20T10:00:00Z"})
        self.assertTrue(entry["hash"])

    def test_it_extracts_the_camera_exif(self):
        raw = {"id": "x", "name": "f.jpg", "imageMediaMetadata": {
            "width": 4032, "height": 3024, "cameraMake": "Apple", "cameraModel": "iPhone 15"}}
        self.assertEqual(normalize_file(raw)["exif"]["Make"], "Apple")

    def test_missing_dimensions_become_zero(self):
        entry = normalize_file({"id": "x", "name": "a.png"})
        self.assertEqual((entry["w"], entry["h"]), (0, 0))

    def test_a_trashed_file_is_flagged(self):
        self.assertTrue(normalize_file({"id": "x", "name": "a.png", "trashed": True})["trashed"])

    def test_it_carries_ocr_and_labels_from_the_snippet(self):
        entry = normalize_file({"id": "x", "name": "a.png", "contentSnippet": REAL_SNIPPET})
        self.assertIn("MIGRATION", entry["ocr_text"])
        self.assertIn("Bridge", entry["labels"])


class TestQuery(unittest.TestCase):
    def test_it_restricts_to_the_folder_and_to_images(self):
        query = folder_query("FOLDER123")
        self.assertIn("'FOLDER123' in parents", query)
        self.assertIn("image/", query)

    def test_it_excludes_the_trash(self):
        self.assertIn("trashed = false", folder_query("X"))


if __name__ == "__main__":
    unittest.main()


class FakeDriveService:
    """A Drive stand-in: answers files().list() from a folder tree in memory.

    tree: {folder_id: {"folders": [(id, name)], "images": [(id, name)]}}
    """

    def __init__(self, tree):
        self.tree = tree
        self.queries = []

    def files(self):
        return self

    def list(self, q=None, **_):
        self.queries.append(q)
        parent = q.split("'")[1]
        node = self.tree.get(parent, {})
        if "mimeType = 'application/vnd.google-apps.folder'" in q:
            entries = [{"id": fid, "name": name,
                        "mimeType": "application/vnd.google-apps.folder"}
                       for fid, name in node.get("folders", [])]
        else:
            entries = [{"id": fid, "name": name, "mimeType": "image/png",
                        "md5Checksum": f"hash-{fid}",
                        "imageMediaMetadata": {"width": 100, "height": 100}}
                       for fid, name in node.get("images", [])]
        return FakeRequest({"files": entries})


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


TREE = {
    "root": {"folders": [("sub", "Campaigns"), ("idx", "_lupa")],
             "images": [("a", "cover.png")]},
    "sub": {"folders": [("deep", "2026")], "images": [("b", "post.png")]},
    "deep": {"folders": [], "images": [("c", "story.png")]},
    "idx": {"folders": [], "images": [("z", "contact-sheet.png")]},
}


class TestRecursiveListing(unittest.TestCase):
    def setUp(self):
        from lupa.drive import list_images
        self.service = FakeDriveService(TREE)
        self.found = list_images(self.service, "root")

    def test_it_reaches_images_in_subfolders(self):
        self.assertIn("b", [f["id"] for f in self.found])

    def test_it_reaches_images_several_levels_down(self):
        self.assertIn("c", [f["id"] for f in self.found])

    def test_it_still_lists_the_root(self):
        self.assertIn("a", [f["id"] for f in self.found])

    def test_the_file_name_carries_the_relative_path(self):
        deep = [f for f in self.found if f["id"] == "c"][0]
        self.assertEqual(deep["file"], "Campaigns/2026/story.png")

    def test_a_root_file_keeps_its_bare_name(self):
        root = [f for f in self.found if f["id"] == "a"][0]
        self.assertEqual(root["file"], "cover.png")

    def test_it_never_descends_into_its_own_index_folder(self):
        self.assertNotIn("z", [f["id"] for f in self.found])

    def test_a_flat_collection_still_works(self):
        from lupa.drive import list_images
        flat = FakeDriveService({"only": {"folders": [], "images": [("x", "a.png")]}})
        self.assertEqual([f["id"] for f in list_images(flat, "only")], ["x"])

    def test_recursion_can_be_turned_off(self):
        from lupa.drive import list_images
        shallow = list_images(FakeDriveService(TREE), "root", recursive=False)
        self.assertEqual([f["id"] for f in shallow], ["a"])


class TestCycleSafety(unittest.TestCase):
    def test_a_folder_loop_does_not_hang(self):
        from lupa.drive import list_images
        looping = {
            "a": {"folders": [("b", "B")], "images": [("i1", "1.png")]},
            "b": {"folders": [("a", "A")], "images": [("i2", "2.png")]},
        }
        found = list_images(FakeDriveService(looping), "a")
        self.assertEqual(sorted(f["id"] for f in found), ["i1", "i2"])
