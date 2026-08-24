"""Contact sheet built from a query — a grid the agent reads in one look.

Different from `contact_sheet.py`, which builds one sheet per frequent tag from
the thumbnail cache at indexing time. This one builds from a SEARCH, live, and
never reads the cache: the cache is a by-product of indexing and can drift from
Drive, while Drive cannot drift from itself.

The geometry here is pure. The network arrives by injection, so the tests never
reach for it.
"""
import io
import math
from pathlib import Path

CELL_PX = 260
PAD_PX = 8
LABEL_PX = 22

BACKGROUND = (24, 24, 24)
LABEL_COLOR = (255, 210, 90)
MISSING_COLOR = (200, 60, 60)

# Above this the cell is too small to judge light and framing, which is the whole
# point of looking. Refused rather than truncated: a silently dropped candidate
# is a candidate nobody knows they never saw.
MAX_CELLS = 24

# What folha.save() below can actually write. Checked by the CLI before a
# single request runs -- `--out folha` used to pay for every download and
# only then die inside Pillow with `ValueError: unknown file extension:`.
VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


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


def build(items, fetch, out_path, thumb_px=None, cell=CELL_PX):
    """Writes a numbered contact sheet. `fetch(file_id, px) -> bytes | None`.

    The fetcher is injected rather than imported: it is the only part that needs
    the network, and a test that had to reach Drive would be a test nobody runs.

    A cell the fetcher cannot fill becomes a marked placeholder. It stays in the
    map, keeping the numbering stable — renumbering around a gap would silently
    change what "cell 7" means between the sheet and the answer.
    """
    from lupa.thumbnail import DEFAULT_THUMB_PX

    if thumb_px is None:
        thumb_px = DEFAULT_THUMB_PX

    # Refused before the fetcher runs, so an empty query costs no request.
    columns, rows, positions, size = layout(len(items), cell=cell)

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return {"skipped": "Pillow is not installed", "cells": [], "missing": 0}

    folha = Image.new("RGB", size, BACKGROUND)
    desenho = ImageDraw.Draw(folha)
    celulas, faltando = [], 0

    for indice, (item, (x, y)) in enumerate(zip(items, positions), start=1):
        dados = fetch(item.get("id"), thumb_px)
        disponivel = False
        if dados:
            # `drive.google.com/thumbnail` is a web endpoint, not the API: a
            # file the account cannot see, or one Google never rendered a
            # thumbnail for, answers HTTP 200 with an HTML page instead of an
            # error. Those bytes are truthy, so without this guard Image.open
            # raises UnidentifiedImageError here -- after every other
            # candidate already paid for its download, and past main's
            # try/except, which only knows IndexAlreadyExists and LockBusy.
            # Caught and folded into the same placeholder path as a `None`
            # from fetch: a sheet with a hole in it beats no sheet at all.
            try:
                miniatura = Image.open(io.BytesIO(dados)).convert("RGB")
                miniatura.thumbnail((cell, cell))
                folha.paste(miniatura, (x + (cell - miniatura.width) // 2,
                                        y + (cell - miniatura.height) // 2))
                disponivel = True
            except Exception:
                pass

        if not disponivel:
            faltando += 1
            desenho.rectangle([x, y, x + cell, y + cell],
                              outline=MISSING_COLOR, width=2)
            desenho.text((x + 8, y + cell // 2), "indisponivel no Drive",
                         fill=MISSING_COLOR)

        desenho.text((x + 4, y + cell + 4), f"{indice:02d}", fill=LABEL_COLOR)
        celulas.append({"celula": indice, "id": item.get("id"),
                        "caption": item.get("caption", ""),
                        "disponivel": disponivel})

    destino = Path(out_path)
    destino.parent.mkdir(parents=True, exist_ok=True)
    folha.save(destino, quality=88)
    return {"out": str(destino), "cells": celulas, "missing": faltando}
