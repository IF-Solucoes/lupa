"""Minimal EXIF: Make and Model only — what tells a photo from generated art."""
import struct
import unittest
from lupa.image import camera_exif


def jpeg_with_exif(make=b"Apple", model=b"iPhone 15", big_endian=True):
    byte_order = b"MM" if big_endian else b"II"
    fmt = ">" if big_endian else "<"

    # string values follow the IFD; offsets count from the start of the TIFF header
    ifd_start = 8
    tag_count = 2
    ifd_size = 2 + tag_count * 12 + 4
    make_offset = ifd_start + ifd_size
    model_offset = make_offset + len(make) + 1

    tiff = byte_order + struct.pack(fmt + "HI", 42, 8)
    tiff += struct.pack(fmt + "H", tag_count)
    tiff += struct.pack(fmt + "HHII", 0x010F, 2, len(make) + 1, make_offset)
    tiff += struct.pack(fmt + "HHII", 0x0110, 2, len(model) + 1, model_offset)
    tiff += struct.pack(fmt + "I", 0)
    tiff += make + b"\x00" + model + b"\x00"

    payload = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return b"\xff\xd8" + app1 + b"\xff\xd9"


class TestExif(unittest.TestCase):
    def test_reads_make_and_model_big_endian(self):
        e = camera_exif(jpeg_with_exif())
        self.assertEqual(e["Make"], "Apple")
        self.assertEqual(e["Model"], "iPhone 15")

    def test_reads_little_endian_too(self):
        e = camera_exif(jpeg_with_exif(b"Canon", b"EOS R6", big_endian=False))
        self.assertEqual(e["Make"], "Canon")
        self.assertEqual(e["Model"], "EOS R6")

    def test_jpeg_without_exif_returns_empty(self):
        self.assertEqual(camera_exif(b"\xff\xd8\xff\xd9"), {})

    def test_png_has_no_exif_and_does_not_crash(self):
        self.assertEqual(camera_exif(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40), {})

    def test_truncated_data_does_not_crash(self):
        self.assertEqual(camera_exif(jpeg_with_exif()[:20]), {})

    def test_empty_bytes_do_not_crash(self):
        self.assertEqual(camera_exif(b""), {})


if __name__ == "__main__":
    unittest.main()
