"""Drive does not always report the geometry, and a missing field is not a zero.

Drive fills `imageMediaMetadata` only for files it has processed. On a real
collection of 181 images, owned by a different account than the one running
lupa, it came back empty for every single one. `normalize_file` turned the
absent field into 0, `classify` divided width by height, and all 181 failed
with "division by zero" — the index came out empty and the run cost nothing but
gave nothing.

Two layers answer that here: the bytes are already downloaded, so the real size
is free to read; and geometry that stays unknown is one empty field, never a
lost image.
"""
import io
import unittest

from lupa.classify import classify
from lupa.pipeline import _fill_dimensions


def _png(width, height):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buffer, "PNG")
    return buffer.getvalue()


class TestClassifySurvivesUnknownGeometry(unittest.TestCase):
    def test_zero_height_does_not_raise(self):
        entry = classify({"w": 0, "h": 0})
        self.assertIsNone(entry["aspect"])
        self.assertIsNone(entry["orientation"])

    def test_zero_height_still_answers_the_free_questions(self):
        entry = classify({"w": 0, "h": 0, "exif": {"Make": "Canon"}})
        self.assertEqual(entry["source"], "camera")

    def test_known_geometry_is_untouched(self):
        entry = classify({"w": 1080, "h": 1920})
        self.assertEqual(entry["aspect"], "9:16")
        self.assertEqual(entry["orientation"], "portrait")


class TestFillDimensions(unittest.TestCase):
    def test_it_reads_the_size_from_the_bytes(self):
        raw = {"w": 0, "h": 0}
        _fill_dimensions(raw, _png(1620, 2880))
        self.assertEqual((raw["w"], raw["h"]), (1620, 2880))

    def test_it_does_not_overwrite_what_drive_reported(self):
        raw = {"w": 800, "h": 600}
        _fill_dimensions(raw, _png(1620, 2880))
        self.assertEqual((raw["w"], raw["h"]), (800, 600))

    def test_unreadable_bytes_leave_the_entry_alone(self):
        raw = {"w": 0, "h": 0}
        _fill_dimensions(raw, b"not an image")
        self.assertEqual((raw["w"], raw["h"]), (0, 0))

    def test_recovered_geometry_classifies_normally(self):
        raw = {"w": 0, "h": 0}
        _fill_dimensions(raw, _png(1620, 2880))
        self.assertEqual(classify(raw)["aspect"], "9:16")


if __name__ == "__main__":
    unittest.main()
