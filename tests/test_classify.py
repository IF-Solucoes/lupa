"""Deterministic classification: what can be decided without spending on AI."""
import unittest
from lupa.classify import classify


class TestAspectAndOrientation(unittest.TestCase):
    def test_feed_post_is_portrait_four_by_five(self):
        r = classify({"w": 1080, "h": 1350})
        self.assertEqual(r["aspect"], "4:5")
        self.assertEqual(r["orientation"], "portrait")

    def test_story_is_nine_by_sixteen(self):
        self.assertEqual(classify({"w": 1080, "h": 1920})["aspect"], "9:16")

    def test_camera_photo_is_three_by_two_landscape(self):
        r = classify({"w": 6000, "h": 4000})
        self.assertEqual(r["aspect"], "3:2")
        self.assertEqual(r["orientation"], "landscape")

    def test_square(self):
        r = classify({"w": 1080, "h": 1080})
        self.assertEqual(r["aspect"], "1:1")
        self.assertEqual(r["orientation"], "square")


class TestSource(unittest.TestCase):
    def test_camera_exif_marks_it_as_captured(self):
        r = classify({"w": 4032, "h": 3024, "exif": {"Make": "Apple", "Model": "iPhone 15"}})
        self.assertEqual(r["source"], "camera")

    def test_no_exif_marks_it_as_generated(self):
        self.assertEqual(classify({"w": 1080, "h": 1350, "mime": "image/png"})["source"],
                         "generated")


class TestTextInImage(unittest.TestCase):
    def test_long_ocr_sets_has_text(self):
        self.assertTrue(classify({"w": 1080, "h": 1350, "ocr_text": "MIGRATION " * 30})["has_text"])

    def test_empty_ocr_clears_has_text(self):
        self.assertFalse(classify({"w": 4032, "h": 3024, "ocr_text": ""})["has_text"])

    def test_residual_ocr_does_not_count_as_text(self):
        # two stray words are OCR noise, not a designed piece
        self.assertFalse(classify({"w": 4032, "h": 3024, "ocr_text": "Sony A7"})["has_text"])


class TestDeterministicKind(unittest.TestCase):
    def test_camera_without_text_is_a_photo(self):
        r = classify({"w": 4032, "h": 3024, "exif": {"Make": "Canon"}, "ocr_text": ""})
        self.assertEqual(r["kind"], "photo")
        self.assertEqual(r["medium"], "na")

    def test_generated_png_with_lots_of_text_is_a_digital_design(self):
        r = classify({"w": 1080, "h": 1350, "mime": "image/png", "ocr_text": "CRITERIA " * 40})
        self.assertEqual(r["kind"], "design")
        self.assertEqual(r["medium"], "digital")

    def test_ambiguous_case_returns_none_for_the_model_to_settle(self):
        # a camera photo WITH lots of text: could be a printed piece photographed
        r = classify({"w": 4032, "h": 3024, "exif": {"Make": "Canon"}, "ocr_text": "SALE " * 40})
        self.assertIsNone(r["kind"])


if __name__ == "__main__":
    unittest.main()
