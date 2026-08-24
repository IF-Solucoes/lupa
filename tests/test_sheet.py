"""Contact sheet geometry: every item gets exactly one cell, and the sheet is
the size those cells add up to."""
import unittest

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
