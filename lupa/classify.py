"""Deterministic classification of an image, from metadata alone.

Nothing here spends model tokens. Whatever the metadata cannot settle comes back
as None — and only those ambiguous cases cost a vision-model opinion.
"""
from math import gcd

# Aspect ratios that matter. Order is irrelevant; the tolerance settles ties.
ASPECTS = {
    (1, 1): "1:1", (4, 5): "4:5", (5, 4): "5:4", (9, 16): "9:16", (16, 9): "16:9",
    (2, 3): "2:3", (3, 2): "3:2", (3, 4): "3:4", (4, 3): "4:3",
}
TOLERANCE = 0.02

# Below this, OCR is noise (a watermark, a nameplate, an equipment label)
# rather than a designed piece.
MIN_WORDS_FOR_TEXT = 5


def _aspect(width, height):
    ratio = width / height
    for (a, b), label in ASPECTS.items():
        if abs(ratio - a / b) <= TOLERANCE:
            return label
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _orientation(width, height):
    if width == height:
        return "square"
    return "landscape" if width > height else "portrait"


def _has_text(ocr):
    return len(ocr.split()) >= MIN_WORDS_FOR_TEXT


def classify(meta):
    """Takes image metadata, returns what can be asserted for free.

    meta accepts: w, h, mime, exif {Make, Model}, ocr_text, name.
    kind/medium come back None when metadata is not enough — the vision model decides those.
    """
    width, height = int(meta["w"]), int(meta["h"])
    exif = meta.get("exif") or {}
    ocr = meta.get("ocr_text") or ""

    source = "camera" if (exif.get("Make") or exif.get("Model")) else "generated"
    has_text = _has_text(ocr)

    kind = medium = None
    if source == "camera" and not has_text:
        kind, medium = "photo", "na"
    elif source == "generated" and has_text:
        kind, medium = "design", "digital"

    return {
        "w": width, "h": height,
        "aspect": _aspect(width, height),
        "orientation": _orientation(width, height),
        "source": source,
        "has_text": has_text,
        "kind": kind,
        "medium": medium,
    }
