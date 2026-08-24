"""Contact sheet built from a query — a grid the agent reads in one look.

Different from `contact_sheet.py`, which builds one sheet per frequent tag from
the thumbnail cache at indexing time. This one builds from a SEARCH, live, and
never reads the cache: the cache is a by-product of indexing and can drift from
Drive, while Drive cannot drift from itself.

The geometry here is pure. The network arrives by injection, so the tests never
reach for it.
"""
import math

CELL_PX = 260
PAD_PX = 8
LABEL_PX = 22

# Above this the cell is too small to judge light and framing, which is the whole
# point of looking. Refused rather than truncated: a silently dropped candidate
# is a candidate nobody knows they never saw.
MAX_CELLS = 24


def layout(count, cell=CELL_PX, pad=PAD_PX, label=LABEL_PX):
    """Columns, rows, one (x, y) per item, and the sheet size."""
    if count < 1:
        raise ValueError("a contact sheet needs at least one image")
    if count > MAX_CELLS:
        raise ValueError(f"{count} images is more than a sheet holds ({MAX_CELLS})")

    columns = math.ceil(math.sqrt(count))
    rows = math.ceil(count / columns)

    positions = [(pad + (i % columns) * (cell + pad),
                  pad + (i // columns) * (cell + label + pad))
                 for i in range(count)]

    size = (columns * (cell + pad) + pad, rows * (cell + label + pad) + pad)
    return columns, rows, positions, size
