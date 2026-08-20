"""Contact sheets: visual grids for human curation, one per frequent tag."""
import unittest
from lupa.contact_sheet import grid_size, pick_tags, MAX_PER_SHEET


def item(tag_list):
    return {"id": "x", "tags": tag_list}


class TestTagSelection(unittest.TestCase):
    CATALOG = ([item(["food", "bread"])] * 30 + [item(["food", "team"])] * 20
               + [item(["logo"])] * 2)

    def test_it_picks_the_most_frequent_tags(self):
        self.assertEqual(pick_tags(self.CATALOG, limit=2), ["food", "bread"])

    def test_it_respects_the_limit(self):
        self.assertEqual(len(pick_tags(self.CATALOG, limit=1)), 1)

    def test_a_rare_tag_is_not_worth_a_sheet(self):
        self.assertNotIn("logo", pick_tags(self.CATALOG, limit=3, minimum=5))

    def test_an_empty_catalog_yields_no_sheets(self):
        self.assertEqual(pick_tags([], limit=10), [])


class TestGrid(unittest.TestCase):
    def test_a_full_sheet_is_square_ish(self):
        columns, rows = grid_size(30)
        self.assertEqual(columns * rows >= 30, True)
        self.assertLessEqual(abs(columns - rows), 3)

    def test_a_single_image_is_one_cell(self):
        self.assertEqual(grid_size(1), (1, 1))

    def test_it_never_exceeds_the_sheet_cap(self):
        columns, rows = grid_size(MAX_PER_SHEET * 4)
        self.assertLessEqual(columns * rows, MAX_PER_SHEET + columns)

    def test_zero_images_is_an_empty_grid(self):
        self.assertEqual(grid_size(0), (0, 0))


class TestGracefulWithoutPillow(unittest.TestCase):
    def test_building_without_pillow_reports_instead_of_crashing(self):
        from lupa.contact_sheet import build_sheets
        result = build_sheets([], thumbs_dir="/nonexistent", out_dir="/tmp/x")
        self.assertIn("sheets", result)
        self.assertEqual(result["sheets"], 0)


if __name__ == "__main__":
    unittest.main()
