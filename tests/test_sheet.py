"""Contact sheet geometry: every item gets exactly one cell, and the sheet is
the size those cells add up to."""
import io
import tempfile
import unittest
from pathlib import Path

from lupa.sheet import CELL_PX, LABEL_PX, MAX_CELLS, PAD_PX, layout


class TestLayout(unittest.TestCase):
    def test_twenty_items_land_in_a_five_by_four_grid(self):
        columns, rows, positions, size = layout(20)
        self.assertEqual((columns, rows), (5, 4))
        self.assertEqual(len(positions), 20)
        # 5 * (260 + 8) + 8 = 1348 ; 4 * (260 + 22 + 8) + 8 = 1168
        self.assertEqual(size, (1348, 1168))

    def test_every_count_from_one_to_the_cap_fills_every_cell(self):
        for count in range(1, MAX_CELLS + 1):
            columns, rows, positions, _ = layout(count)
            self.assertEqual(len(positions), count, f"count={count}")
            self.assertLessEqual(count, columns * rows, f"count={count}")
            self.assertEqual(len(set(positions)), count, f"count={count}")

    def test_positions_advance_by_a_cell_plus_padding(self):
        _, _, positions, _ = layout(3)
        self.assertEqual(positions[0], (PAD_PX, PAD_PX))
        self.assertEqual(positions[1], (PAD_PX + CELL_PX + PAD_PX, PAD_PX))

    def test_the_label_strip_is_below_the_cell(self):
        _, _, positions, size = layout(2)
        self.assertEqual(size[1], CELL_PX + LABEL_PX + 2 * PAD_PX)

    def test_more_than_the_cap_is_refused_rather_than_truncated(self):
        with self.assertRaises(ValueError):
            layout(MAX_CELLS + 1)

    def test_nothing_to_lay_out_is_refused(self):
        with self.assertRaises(ValueError):
            layout(0)


def _jpeg(color=(120, 30, 30), size=(400, 300)):
    """Real image bytes, made here. No fixture file and no network."""
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="JPEG")
    return buffer.getvalue()


ITEMS = [{"id": f"id{n}", "caption": f"caption {n}"} for n in range(1, 5)]


class TestBuild(unittest.TestCase):
    def setUp(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow is not installed")
        self.dir = tempfile.TemporaryDirectory()
        self.out = str(Path(self.dir.name) / "sheet.jpg")

    def tearDown(self):
        self.dir.cleanup()

    def test_it_writes_a_sheet_and_maps_every_cell(self):
        from lupa.sheet import build
        report = build(ITEMS, lambda file_id, px: _jpeg(), self.out)

        self.assertTrue(Path(self.out).exists())
        self.assertEqual(report["missing"], 0)
        self.assertEqual([c["celula"] for c in report["cells"]], [1, 2, 3, 4])
        self.assertEqual([c["id"] for c in report["cells"]],
                         ["id1", "id2", "id3", "id4"])
        self.assertTrue(all(c["disponivel"] for c in report["cells"]))

    def test_a_thumbnail_drive_will_not_give_becomes_a_placeholder(self):
        from lupa.sheet import build

        def fetch(file_id, px):
            return None if file_id == "id2" else _jpeg()

        report = build(ITEMS, fetch, self.out)

        # The sheet still exists: one gap must not cost the other nineteen.
        self.assertTrue(Path(self.out).exists())
        self.assertEqual(report["missing"], 1)
        # The map still covers the missing one, so the numbering never shifts.
        self.assertEqual(len(report["cells"]), 4)
        ausente = [c for c in report["cells"] if not c["disponivel"]]
        self.assertEqual([c["id"] for c in ausente], ["id2"])
        self.assertEqual([c["celula"] for c in ausente], [2])

    def test_the_requested_thumbnail_size_reaches_the_fetcher(self):
        from lupa.sheet import build
        pedidos = []

        def fetch(file_id, px):
            pedidos.append(px)
            return _jpeg()

        build(ITEMS, fetch, self.out, thumb_px=800)
        self.assertEqual(set(pedidos), {800})

    def test_no_items_is_refused_before_anything_is_written(self):
        from lupa.sheet import build
        with self.assertRaises(ValueError):
            build([], lambda file_id, px: _jpeg(), self.out)
        self.assertFalse(Path(self.out).exists())


class TestBuildWithoutPillow(unittest.TestCase):
    def test_it_reports_instead_of_raising(self):
        import builtins

        import lupa.sheet as modulo

        real = builtins.__import__

        def sem_pillow(nome, *resto):
            if nome == "PIL" or nome.startswith("PIL."):
                raise ImportError("no PIL here")
            return real(nome, *resto)

        builtins.__import__ = sem_pillow
        try:
            report = modulo.build(ITEMS, lambda i, p: b"", "unused.jpg")
        finally:
            builtins.__import__ = real

        self.assertEqual(report["cells"], [])
        self.assertIn("Pillow", report["skipped"])
