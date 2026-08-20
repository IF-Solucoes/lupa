"""Image header reading — just enough to know size, type and camera.

Deliberately free of Pillow: lupa's core must work over a local folder without
requiring an installation.
"""
import struct

SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),
    (b"BM", "image/bmp"),
)

BY_EXTENSION = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
    "heic": "image/heic", "tif": "image/tiff", "tiff": "image/tiff",
}

# JPEG markers that carry frame dimensions, excluding the differential ones.
SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
               0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def mime_of(data, name=""):
    """Content decides; the extension is the fallback."""
    for signature, mime in SIGNATURES:
        if data.startswith(signature):
            if signature == b"RIFF" and data[8:12] != b"WEBP":
                continue
            return mime
    extension = str(name).rsplit(".", 1)[-1].lower()
    return BY_EXTENSION.get(extension, "application/octet-stream")


def _png(data):
    return struct.unpack(">II", data[16:24])


def _gif(data):
    return struct.unpack("<HH", data[6:10])


def _webp(data):
    if data[12:16] == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    if data[12:16] == b"VP8 ":
        return struct.unpack("<HH", data[26:30])
    if data[12:16] == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise ValueError("webp without a recognized header")


def _jpeg(data):
    i, end = 2, len(data)
    while i < end - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in SOF_MARKERS:
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return width, height
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        segment = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + segment
    raise ValueError("jpeg without an SOF marker")


def dimensions(data):
    """(width, height) — (0, 0) for unknown formats or truncated files."""
    if not data:
        return 0, 0
    try:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return _png(data)
        if data.startswith((b"GIF87a", b"GIF89a")):
            return _gif(data)
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return _webp(data)
        if data.startswith(b"\xff\xd8"):
            return _jpeg(data)
    except (struct.error, ValueError, IndexError):
        return 0, 0
    return 0, 0


# --- Minimal EXIF: Make and Model only ---
# Enough to tell "captured by a camera" from "produced in an editor". Reading the
# full EXIF table would require a dependency that does not pay for itself.

TAG_MAKE = 0x010F
TAG_MODEL = 0x0110
TYPE_ASCII = 2


def _find_app1(data):
    """Locates the Exif segment inside a JPEG."""
    i, end = 2, len(data)
    while i < end - 4:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xE1 and data[i + 4:i + 10] == b"Exif\x00\x00":
            return i + 10
        if marker in (0xD8, 0xD9, 0xDA):
            return None
        segment = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + segment
    return None


def camera_exif(data):
    """{'Make': ..., 'Model': ...} — empty when there is no camera EXIF."""
    if not data or not data.startswith(b"\xff\xd8"):
        return {}
    try:
        base = _find_app1(data)
        if base is None:
            return {}

        byte_order = data[base:base + 2]
        if byte_order not in (b"MM", b"II"):
            return {}
        fmt = ">" if byte_order == b"MM" else "<"

        ifd_offset = struct.unpack(fmt + "I", data[base + 4:base + 8])[0]
        pos = base + ifd_offset
        count = struct.unpack(fmt + "H", data[pos:pos + 2])[0]
        pos += 2

        found = {}
        for _ in range(count):
            tag, tag_type, length, value = struct.unpack(fmt + "HHII", data[pos:pos + 12])
            pos += 12
            if tag not in (TAG_MAKE, TAG_MODEL) or tag_type != TYPE_ASCII:
                continue
            if length <= 4:  # short values live in the offset field itself
                raw = struct.pack(fmt + "I", value)[:length]
            else:
                raw = data[base + value:base + value + length]
            text = raw.split(b"\x00")[0].decode("utf-8", errors="replace").strip()
            if text:
                found["Make" if tag == TAG_MAKE else "Model"] = text
        return found
    except (struct.error, ValueError, IndexError, UnicodeDecodeError):
        return {}
