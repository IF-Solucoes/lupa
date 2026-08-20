"""A collection in a folder on disk. Same interface as the Drive source.

It needs no credentials, but it also gets no free OCR — over a local folder the
vision model has to work a little harder.
"""
import hashlib
from pathlib import Path

from lupa.image import camera_exif, dimensions, mime_of

EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic"}
INDEX_FOLDER = "_lupa"
HEADER_BYTES = 128 * 1024  # enough for dimensions and EXIF


class LocalSource:
    def __init__(self, path):
        self.root = Path(path).expanduser().resolve()

    def _candidates(self):
        for entry in sorted(self.root.rglob("*")):
            if not entry.is_file() or entry.suffix.lower() not in EXTENSIONS:
                continue
            relative = entry.relative_to(self.root)
            if any(part.startswith((INDEX_FOLDER, ".")) for part in relative.parts):
                continue
            yield entry, relative

    def list(self):
        found = []
        for entry, relative in self._candidates():
            info = entry.stat()
            header = entry.open("rb").read(HEADER_BYTES)
            width, height = dimensions(header)

            # Size plus modification time — the same test rsync uses by default.
            # Touching a file without changing its content forces a reindex; that
            # is deliberately conservative, and cheaper than hashing gigabytes.
            fingerprint = hashlib.md5(
                f"{info.st_size}|{int(info.st_mtime)}".encode()).hexdigest()

            found.append({
                "id": relative.as_posix(),
                "file": relative.as_posix(),
                "mime": mime_of(header, entry.name),
                "hash": fingerprint,
                "size": info.st_size,
                "w": width, "h": height,
                "exif": camera_exif(header),
                "ocr_text": "",   # no free lunch from Drive here
                "labels": [],
                "url": entry.as_uri(),
                "trashed": False,
            })
        return found

    def fetch(self, item_id):
        entry = self.root / item_id
        data = entry.read_bytes()
        return data, mime_of(data, entry.name)
