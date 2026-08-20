"""Keeping the vision model from receiving 24-megapixel originals.

Sending a full-resolution photograph costs several times what a thumbnail costs
and buys nothing: the model is describing composition, light and subject, not
counting pixels. Two paths:

  Drive  — ask Google for the thumbnail it already generated. Free, no dependency.
  local  — downscale with Pillow when it is installed; otherwise send the original
           and let preflight warn about the cost.
"""
import re

MAX_EDGE_PX = 768

# Google's image links end in a size directive: =s220, =w200-h150, =s512-c ...
SIZE_SUFFIX = re.compile(r"=[swh]\d+(-[a-z0-9]+)*$")


def thumbnail_url(link, size=MAX_EDGE_PX):
    """Rewrites a Drive thumbnail link to the size we actually want."""
    if not link:
        return None
    return f"{SIZE_SUFFIX.sub('', str(link))}=s{size}"


def needs_downscale(width, height, limit=MAX_EDGE_PX):
    """Unknown dimensions count as large — better to shrink than to overpay."""
    if not width or not height:
        return True
    return max(width, height) > limit


def downscale(data, mime, limit=MAX_EDGE_PX):
    """Shrinks image bytes to `limit` on the longest edge.

    Returns the original bytes when Pillow is absent or the image cannot be read —
    correctness first; the cost warning is preflight's job.
    """
    try:
        import io

        from PIL import Image
    except ImportError:
        return data

    try:
        with Image.open(io.BytesIO(data)) as image:
            if max(image.size) <= limit:
                return data
            image.thumbnail((limit, limit))
            if image.mode in ("RGBA", "P", "LA"):
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
            return buffer.getvalue()
    except Exception:
        return data


def pillow_available():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False
