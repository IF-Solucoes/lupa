"""SQLite FTS5: a disposable projection of the catalog, for ranking that holds up."""
import tempfile
import unittest
from pathlib import Path

from lupa.fts import build, query, available

CATALOG = [
    {"id": "1", "file": "bridge.png", "kind": "design", "medium": "digital",
     "orientation": "portrait", "has_text": True,
     "caption": "Cable-stayed bridge at night under cold blue light",
     "tags": ["bridge", "night", "blue"], "text": "MIGRATION evolve module by module"},
    {"id": "2", "file": "table.jpg", "kind": "photo", "medium": "na",
     "orientation": "landscape", "has_text": False,
     "caption": "Rustic wooden table with artisan bread and blue linen",
     "tags": ["food", "bread", "wood", "blue"], "text": ""},
    {"id": "3", "file": "banner.jpg", "kind": "design", "medium": "physical",
     "orientation": "landscape", "has_text": True,
     "caption": "Printed standing banner at an event, blue background",
     "tags": ["banner", "event", "blue"], "text": "LUPA"},
]


@unittest.skipUnless(available(), "sqlite without FTS5")
class FtsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "index.db"
        build(CATALOG, self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def ids(self, *args, **kw):
        return [item["id"] for item in query(self.db, *args, **kw)]


class TestMatching(FtsTestCase):
    def test_it_finds_by_tag(self):
        self.assertEqual(self.ids("bridge"), ["1"])

    def test_it_finds_by_caption(self):
        self.assertIn("2", self.ids("artisan"))

    def test_it_finds_by_ocr_text(self):
        self.assertIn("1", self.ids("migration"))

    def test_an_absent_term_returns_nothing(self):
        self.assertEqual(self.ids("helicopter"), [])

    def test_a_prefix_matches(self):
        self.assertIn("3", self.ids("bann"))

    def test_a_plural_still_matches_the_singular(self):
        self.assertIn("1", self.ids("bridges"))


class TestRanking(FtsTestCase):
    def test_a_rare_term_outranks_a_common_one(self):
        # "blue" is on all three; "banner" is on one. The rare term must decide.
        self.assertEqual(self.ids("blue banner")[0], "3")

    def test_matching_every_term_beats_matching_one(self):
        results = self.ids("printed banner event")
        self.assertEqual(results[0], "3")


class TestConjunction(FtsTestCase):
    def test_all_terms_are_required_when_something_matches_them_all(self):
        self.assertEqual(self.ids("blue bread"), ["2"])

    def test_it_falls_back_to_any_term_when_nothing_matches_all(self):
        # no item has both "bridge" and "bread"; better to answer than to stonewall
        self.assertTrue(set(self.ids("bridge bread")) >= {"1", "2"})


class TestFilters(FtsTestCase):
    def test_the_kind_filter_is_applied(self):
        self.assertEqual(self.ids("blue", filters={"kind": "photo"}), ["2"])

    def test_the_medium_filter_is_applied(self):
        self.assertEqual(self.ids("blue", filters={"medium": "physical"}), ["3"])

    def test_the_boolean_filter_is_applied(self):
        self.assertEqual(self.ids("blue", filters={"has_text": False}), ["2"])

    def test_a_filter_alone_lists_matching_items(self):
        self.assertEqual(sorted(self.ids("", filters={"kind": "design"})), ["1", "3"])


class TestProjection(FtsTestCase):
    def test_rebuilding_replaces_the_previous_projection(self):
        build(CATALOG[:1], self.db)
        self.assertEqual(sorted(self.ids("blue")), ["1"])

    def test_the_full_item_survives_the_round_trip(self):
        item = query(self.db, "bridge")[0]
        self.assertEqual(item["file"], "bridge.png")
        self.assertEqual(item["tags"], ["bridge", "night", "blue"])

    def test_results_carry_a_reason(self):
        self.assertIn("_reason", query(self.db, "bridge")[0])

    def test_the_limit_is_honored(self):
        self.assertEqual(len(query(self.db, "blue", limit=1)), 1)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(available(), "sqlite without FTS5")
class TestTheProjectionCarriesTheProperNouns(unittest.TestCase):
    """The FTS5 database is the fast path, so a field absent from it is a field
    that cannot be found in any collection that has one."""

    CATALOG = [
        {"id": "a", "file": "post.jpg", "kind": "design", "medium": "digital",
         "orientation": "portrait", "has_text": True, "caption": "A campaign piece",
         "tags": ["dog"], "text": "", "entities": ["Castracao Solidaria"]},
        {"id": "b", "file": "cat.jpg", "kind": "photo", "medium": "na",
         "orientation": "landscape", "has_text": False, "caption": "A cat",
         "tags": ["cat"], "text": "", "entities": []},
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "index.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_name_only_in_entities_is_found(self):
        build(self.CATALOG, self.db)
        self.assertEqual([r["id"] for r in query(self.db, "solidaria")], ["a"])

    def test_a_catalog_without_the_field_still_builds(self):
        old = [{k: v for k, v in item.items() if k != "entities"}
               for item in self.CATALOG]
        build(old, self.db)
        self.assertEqual([r["id"] for r in query(self.db, "cat")], ["b"])

    def test_a_database_built_before_the_column_existed_is_still_queryable(self):
        """index.db is derived and gitignored, but it is NOT rebuilt until the
        next indexing run — and indexing is what costs money. Every database on
        disk today has four columns; ranking must not ask for five."""
        import sqlite3

        connection = sqlite3.connect(self.db)
        connection.executescript("""
            CREATE TABLE items (rowid INTEGER PRIMARY KEY, id TEXT UNIQUE,
                payload TEXT NOT NULL, kind TEXT, medium TEXT, orientation TEXT,
                has_text INTEGER);
            CREATE VIRTUAL TABLE fts USING fts5(file, caption, tags, text,
                tokenize = "porter unicode61 remove_diacritics 2");
        """)
        with connection:
            connection.execute(
                "INSERT INTO items (rowid, id, payload, kind, medium, orientation,"
                " has_text) VALUES (1,'b','{\"id\": \"b\"}','photo','na','landscape',0)")
            connection.execute(
                "INSERT INTO fts (rowid, file, caption, tags, text)"
                " VALUES (1,'cat.jpg','A cat','cat','')")
        connection.close()

        self.assertEqual([r["id"] for r in query(self.db, "cat")], ["b"])
