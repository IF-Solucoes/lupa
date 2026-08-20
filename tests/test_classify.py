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


class TestNothingIsTypedWithoutLookingAtIt(unittest.TestCase):
    def test_every_kind_is_left_for_the_model_to_settle(self):
        # a camera photo may be a printed piece photographed; metadata cannot tell
        r = classify({"w": 4032, "h": 3024, "exif": {"Make": "Canon"}})
        self.assertIsNone(r["kind"])
        self.assertIsNone(r["medium"])


class TestTextIsNoLongerMetadata(unittest.TestCase):
    """`has_text` used to be decided here, from a field Drive never sent.

    It came out False for all 875 images of the first real collection. The vision
    model decides it now — it is the only party that can actually see the image — so
    the heuristic must not answer a question it has no data for.
    """

    def test_it_does_not_claim_to_know_whether_there_is_text(self):
        self.assertNotIn("has_text", classify({"w": 1080, "h": 1350}))

    def test_a_camera_photo_is_no_longer_typed_without_anyone_looking_at_it(self):
        # 510 of 875 images went straight to photo/na on this branch alone, which is
        # also how a photographed printed banner became a photo.
        settled = classify({"w": 4032, "h": 3024, "exif": {"Make": "Canon"}})
        self.assertIsNone(settled["kind"])
        self.assertIsNone(settled["medium"])

    def test_a_generated_png_is_not_typed_either(self):
        settled = classify({"w": 1080, "h": 1350, "mime": "image/png"})
        self.assertIsNone(settled["kind"])
        self.assertIsNone(settled["medium"])

    def test_a_leftover_ocr_text_key_changes_nothing(self):
        # an old caller may still pass it; it must not resurrect the dead branch
        settled = classify({"w": 1080, "h": 1350, "ocr_text": "SALE " * 40})
        self.assertNotIn("has_text", settled)
        self.assertIsNone(settled["kind"])

    def test_what_stays_free_stays_free(self):
        settled = classify({"w": 6000, "h": 4000, "exif": {"Make": "Canon"}})
        self.assertEqual(settled["source"], "camera")
        self.assertEqual(settled["aspect"], "3:2")
        self.assertEqual(settled["orientation"], "landscape")


if __name__ == "__main__":
    unittest.main()
