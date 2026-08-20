"""Deterministic classification of an image, from metadata alone.

Nothing here spends model tokens, and nothing here guesses. Geometry and `source`
are settled for free; everything that needs eyes comes back None and is left to the
vision model. That division is deliberate: a heuristic that answers a question it
has no data for does not save money, it writes a wrong answer into the index.
"""
from math import gcd

# Aspect ratios that matter. Order is irrelevant; the tolerance settles ties.
ASPECTS = {
    (1, 1): "1:1", (4, 5): "4:5", (5, 4): "5:4", (9, 16): "9:16", (16, 9): "16:9",
    (2, 3): "2:3", (3, 2): "3:2", (3, 4): "3:4", (4, 3): "4:3",
}
TOLERANCE = 0.02


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


def classify(meta):
    """Takes image metadata, returns what can be asserted for free.

    meta accepts: w, h, exif {Make, Model}. Geometry is arithmetic and `source` is
    a fact stamped by the camera — both are free and both are certain.

    kind and medium always come back None, and that is the honest answer: telling a
    photograph apart from a photographed poster takes eyes. The two branches that
    used to settle them both hinged on `has_text`, which was read out of a Drive
    field that does not exist — so `camera` alone decided `photo/na` for 510 of the
    875 images in the first real collection, a printed banner among them. `has_text`
    is now the vision model's answer, and it arrives after this function has run.
    """
    width, height = int(meta["w"]), int(meta["h"])
    exif = meta.get("exif") or {}

    return {
        "w": width, "h": height,
        "aspect": _aspect(width, height),
        "orientation": _orientation(width, height),
        "source": "camera" if (exif.get("Make") or exif.get("Model")) else "generated",
        "kind": None,
        "medium": None,
    }
