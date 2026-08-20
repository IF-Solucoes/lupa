"""Contact sheets — visual grids for human curation.

One sheet per frequent tag, not one giant grid of the whole collection: nobody
opens a hundred pages of thumbnails, but "show me the food photos" is useful.

Requires Pillow. Without it the run reports that sheets were skipped rather than
failing — the index itself never depends on them.
"""
import math
from collections import Counter
from pathlib import Path

MAX_PER_SHEET = 30
CELL_PX = 240
PADDING_PX = 6
DEFAULT_TAG_LIMIT = 12
MIN_ITEMS_PER_TAG = 4


def pick_tags(catalog, limit=DEFAULT_TAG_LIMIT, minimum=MIN_ITEMS_PER_TAG):
    """The tags worth a sheet: frequent enough to be a theme."""
    counts = Counter(tag for item in catalog for tag in (item.get("tags") or []))
    return [tag for tag, count in counts.most_common(limit) if count >= minimum]


def grid_size(count):
    """Columns and rows for `count` images, capped at one sheet."""
    if count <= 0:
        return 0, 0
    count = min(count, MAX_PER_SHEET)
    columns = math.ceil(math.sqrt(count))
    rows = math.ceil(count / columns)
    return columns, rows


def build_sheets(catalog, thumbs_dir, out_dir, tag_limit=DEFAULT_TAG_LIMIT):
    """Writes one sheet per frequent tag. Returns a small report."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return {"sheets": 0, "skipped": "Pillow is not installed"}

    thumbs_dir, out_dir = Path(thumbs_dir), Path(out_dir)
    if not thumbs_dir.exists():
        return {"sheets": 0, "skipped": "no thumbnails cached yet"}

    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0

    for tag in pick_tags(catalog, limit=tag_limit):
        members = [item for item in catalog if tag in (item.get("tags") or [])]
        available = [(item, thumbs_dir / f"{_safe(item['id'])}.jpg") for item in members]
        available = [(item, path) for item, path in available if path.exists()]
        if not available:
            continue

        available = available[:MAX_PER_SHEET]
        columns, rows = grid_size(len(available))
        width = columns * (CELL_PX + PADDING_PX) + PADDING_PX
        height = rows * (CELL_PX + PADDING_PX) + PADDING_PX + 24

        sheet = Image.new("RGB", (width, height), (24, 24, 26))
        draw = ImageDraw.Draw(sheet)
        draw.text((PADDING_PX, 6), f"{tag} — {len(members)} images", fill=(200, 200, 200))

        for position, (_, path) in enumerate(available):
            try:
                with Image.open(path) as thumb:
                    thumb = thumb.convert("RGB")
                    thumb.thumbnail((CELL_PX, CELL_PX))
                    column, row = position % columns, position // columns
                    x = PADDING_PX + column * (CELL_PX + PADDING_PX)
                    y = 24 + PADDING_PX + row * (CELL_PX + PADDING_PX)
                    sheet.paste(thumb, (x, y))
            except Exception:
                continue  # one unreadable thumbnail must not lose the sheet

        sheet.save(out_dir / f"{_safe(tag)}.jpg", quality=80)
        written += 1

    return {"sheets": written}


def _safe(name):
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in str(name))[:80]
