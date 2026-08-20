"""Image dimensions read from the header, with no external dependency."""
import struct
import unittest
from lupa.image import dimensions, mime_of


def png(w, h):
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
            + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00")


def gif(w, h):
    return b"GIF89a" + struct.pack("<HH", w, h) + b"\x00\x00\x00"


def jpeg(w, h):
    return (b"\xff\xd8"                       # SOI
            + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
            + b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
            + struct.pack(">HH", h, w) + b"\x03" + b"\x00" * 9
            + b"\xff\xd9")


def webp(w, h):
    # VP8X: flags(1) + reserved(3) + width-1 (3 bytes LE) + height-1 (3 bytes LE)
    payload = b"\x00\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    corpo = b"VP8X" + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", len(corpo) + 4) + b"WEBP" + corpo


class TestDimensions(unittest.TestCase):
    def test_png(self):
        self.assertEqual(dimensions(png(1080, 1350)), (1080, 1350))

    def test_gif(self):
        self.assertEqual(dimensions(gif(640, 480)), (640, 480))

    def test_jpeg(self):
        self.assertEqual(dimensions(jpeg(4032, 3024)), (4032, 3024))

    def test_webp(self):
        self.assertEqual(dimensions(webp(800, 600)), (800, 600))

    def test_unknown_format_returns_zeros(self):
        self.assertEqual(dimensions(b"not an image"), (0, 0))

    def test_truncated_file_does_not_crash(self):
        self.assertEqual(dimensions(png(100, 100)[:12]), (0, 0))

    def test_empty_bytes_do_not_crash(self):
        self.assertEqual(dimensions(b""), (0, 0))


class TestMime(unittest.TestCase):
    def test_content_wins_over_extension(self):
        self.assertEqual(mime_of(png(1, 1), "foto.jpg"), "image/png")

    def test_falls_back_to_extension(self):
        self.assertEqual(mime_of(b"???", "foto.jpeg"), "image/jpeg")

    def test_unknown_becomes_octet_stream(self):
        self.assertEqual(mime_of(b"???", "file.xyz"), "application/octet-stream")


if __name__ == "__main__":
    unittest.main()
