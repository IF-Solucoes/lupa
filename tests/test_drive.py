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
