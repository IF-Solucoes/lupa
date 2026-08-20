"""Catalog search: no embeddings, no network, over the index already written."""
import unittest
from lupa.search import search

CATALOG = [
    {"id": "1", "file": "ponte.png", "kind": "design", "medium": "digital",
     "orientation": "portrait", "has_text": True,
     "caption": "Cable-stayed bridge at night under cold blue light",
     "tags": ["bridge", "night", "blue"], "text": "MIGRATION evolve module by module",
     "labels": ["Bridge"]},
    {"id": "2", "file": "mesa.jpg", "kind": "photo", "medium": "na",
     "orientation": "landscape", "has_text": False,
     "caption": "Rustic wooden table with artisan bread in a warm café",
     "tags": ["food", "bread", "wood", "natural-light"], "text": "", "labels": ["Food"]},
    {"id": "3", "file": "banner.jpg", "kind": "design", "medium": "physical",
     "orientation": "landscape", "has_text": True,
     "caption": "Printed standing banner at an event, blue background",
     "tags": ["banner", "event", "blue"], "text": "MINDTEC", "labels": []},
]


class TestMatching(unittest.TestCase):
    def test_a_term_in_a_tag_matches(self):
        self.assertEqual([r["id"] for r in search(CATALOG, "bridge")], ["1"])

    def test_a_term_in_the_caption_matches(self):
        self.assertIn("2", [r["id"] for r in search(CATALOG, "artisan")])

    def test_a_term_in_the_ocr_matches(self):
        self.assertIn("1", [r["id"] for r in search(CATALOG, "module")])

    def test_an_absent_term_returns_nothing(self):
        self.assertEqual(search(CATALOG, "helicopter"), [])

    def test_case_does_not_matter(self):
        self.assertIn("1", [r["id"] for r in search(CATALOG, "night")])
        self.assertIn("1", [r["id"] for r in search(CATALOG, "NIGHT")])

    def test_an_unaccented_query_finds_an_accented_term(self):
        self.assertIn("2", [r["id"] for r in search(CATALOG, "cafe")])
        self.assertIn("2", [r["id"] for r in search(CATALOG, "café")])


class TestRanking(unittest.TestCase):
    def test_a_tag_weighs_more_than_ocr(self):
        r = search(CATALOG, "blue")
        self.assertEqual(r[0]["id"], "1")  # tag "blue" + caption; item 3 has the tag too
        self.assertTrue(r[0]["_score"] >= r[-1]["_score"])

    def test_matching_two_terms_ranks_first(self):
        r = search(CATALOG, "blue banner")
        self.assertEqual(r[0]["id"], "3")

    def test_the_result_explains_why_it_matched(self):
        r = search(CATALOG, "bridge")
        self.assertIn("tag", r[0]["_reason"])


class TestFilters(unittest.TestCase):
    def test_the_kind_filter_excludes_designs(self):
        r = search(CATALOG, "light", filters={"kind": "photo"})
        self.assertEqual([x["id"] for x in r], ["2"])

    def test_the_medium_filter_isolates_physical_material(self):
        r = search(CATALOG, "blue", filters={"medium": "physical"})
        self.assertEqual([x["id"] for x in r], ["3"])

    def test_has_text_false_drops_pieces_with_text(self):
        r = search(CATALOG, "light", filters={"has_text": False})
        self.assertEqual([x["id"] for x in r], ["2"])

    def test_the_orientation_filter(self):
        r = search(CATALOG, "blue", filters={"orientation": "portrait"})
        self.assertEqual([x["id"] for x in r], ["1"])

    def test_a_filter_alone_lists_everything_that_matches(self):
        r = search(CATALOG, "", filters={"kind": "design"})
        self.assertEqual(sorted(x["id"] for x in r), ["1", "3"])


class TestLimit(unittest.TestCase):
    def test_the_limit_truncates_the_result(self):
        self.assertEqual(len(search(CATALOG, "blue light bread", limit=1)), 1)

    def test_the_default_limit_is_fifteen(self):
        many = [dict(CATALOG[1], id=str(i)) for i in range(50)]
        self.assertEqual(len(search(many, "wood")), 15)


if __name__ == "__main__":
    unittest.main()
