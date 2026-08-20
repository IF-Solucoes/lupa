"""Writing the index: the artifacts agents read."""
import json
import tempfile
import unittest
from pathlib import Path

from lupa.build import write_index, backup, tag_filename

ITEMS = [
    {"id": "1", "file": "bridge.png", "url": "https://drive/1", "kind": "design",
     "medium": "digital", "orientation": "portrait", "has_text": True, "hash": "h1",
     "caption": "Bridge at night", "tags": ["bridge", "night"], "text": "MIGRATION", "labels": []},
    {"id": "2", "file": "table.jpg", "url": "https://drive/2", "kind": "photo",
     "medium": "na", "orientation": "landscape", "has_text": False, "hash": "h2",
     "caption": "Wooden table", "tags": ["food", "night"], "text": "", "labels": []},
]


class IndexTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, items=None, **kw):
        return write_index(
            self.dir, collection="if-editorial", items=items if items is not None else ITEMS,
            summary=kw.pop("summary", "+2 added"), model="gemini-2.5-flash-lite",
            cost_usd=kw.pop("cost_usd", 0.0001), now=kw.pop("now", "2026-08-20T14:32:00"), **kw)


class TestCatalog(IndexTestCase):
    def test_one_line_per_image(self):
        self.write()
        lines = (self.dir / "catalog.jsonl").read_text().strip().split("\n")
        self.assertEqual(len(lines), 2)

    def test_every_line_is_valid_json(self):
        self.write()
        for line in (self.dir / "catalog.jsonl").read_text().strip().split("\n"):
            self.assertIn("id", json.loads(line))

    def test_non_ascii_survives_unescaped(self):
        self.write()
        self.assertIn("Bridge at night", (self.dir / "catalog.jsonl").read_text())

    def test_a_removed_item_leaves_the_catalog(self):
        self.write()
        self.write(items=[ITEMS[0]])
        lines = (self.dir / "catalog.jsonl").read_text().strip().split("\n")
        self.assertEqual(len(lines), 1)


class TestIndexMarkdown(IndexTestCase):
    def test_it_states_the_image_count(self):
        self.write()
        self.assertIn("2", (self.dir / "INDEX.md").read_text())

    def test_it_warns_the_agent_not_to_open_images(self):
        self.write()
        text = (self.dir / "INDEX.md").read_text().lower()
        self.assertIn("pixels", text)

    def test_it_lists_the_tag_vocabulary_with_counts(self):
        self.write()
        text = (self.dir / "INDEX.md").read_text()
        self.assertIn("night", text)
        self.assertIn("2", text)  # "night" appears on both images


class TestByTag(IndexTestCase):
    def test_it_creates_one_file_per_tag(self):
        self.write()
        tags = sorted(p.stem for p in (self.dir / "by-tag").glob("*.md"))
        self.assertEqual(tags, ["bridge", "food", "night"])

    def test_a_tag_file_lists_its_members(self):
        self.write()
        text = (self.dir / "by-tag" / "night.md").read_text()
        self.assertIn("bridge.png", text)
        self.assertIn("table.jpg", text)

    def test_a_tag_file_carries_the_url(self):
        self.write()
        self.assertIn("https://drive/1", (self.dir / "by-tag" / "bridge.md").read_text())

    def test_an_accented_tag_becomes_a_safe_filename(self):
        self.assertEqual(tag_filename("Café Society"), "cafe-society")

    def test_vanished_tags_leave_no_orphan_file(self):
        self.write()
        self.write(items=[ITEMS[1]])  # "bridge" is gone
        self.assertFalse((self.dir / "by-tag" / "bridge.md").exists())


class TestManifest(IndexTestCase):
    def test_it_stores_a_hash_per_item(self):
        self.write()
        manifest = json.loads((self.dir / "MANIFEST.json").read_text())
        self.assertEqual(manifest["items"]["1"]["hash"], "h1")

    def test_it_stores_the_total_and_the_collection(self):
        self.write()
        manifest = json.loads((self.dir / "MANIFEST.json").read_text())
        self.assertEqual(manifest["total"], 2)
        self.assertEqual(manifest["collection"], "if-editorial")

    def test_it_counts_runs(self):
        self.write()
        self.assertEqual(json.loads((self.dir / "MANIFEST.json").read_text())["runs"], 1)
        self.write()
        self.assertEqual(json.loads((self.dir / "MANIFEST.json").read_text())["runs"], 2)


class TestRunReport(IndexTestCase):
    def test_it_writes_one_report_per_run(self):
        self.write(now="2026-08-20T14:32:00")
        self.assertTrue((self.dir / "runs" / "2026-08-20T14-32-00.md").exists())

    def test_the_report_carries_summary_cost_and_model(self):
        self.write(summary="+40 added · -5 removed", cost_usd=0.004)
        text = list((self.dir / "runs").glob("*.md"))[0].read_text()
        self.assertIn("+40 added", text)
        self.assertIn("0.004", text)
        self.assertIn("gemini-2.5-flash-lite", text)


class TestBackup(IndexTestCase):
    def test_backup_copies_the_previous_index(self):
        self.write()
        destination = backup(self.dir, now="2026-08-20T15-00-00")
        self.assertTrue((destination / "catalog.jsonl").exists())
        self.assertTrue((destination / "MANIFEST.json").exists())

    def test_backup_of_a_missing_index_does_not_crash(self):
        self.assertIsNone(backup(self.dir / "missing", now="x"))

    def test_backup_does_not_remove_the_current_index(self):
        self.write()
        backup(self.dir, now="2026-08-20T15-00-00")
        self.assertTrue((self.dir / "catalog.jsonl").exists())


if __name__ == "__main__":
    unittest.main()


class TestTheRunReportRecordsTheTokens(IndexTestCase):
    """The run report is where a measurement survives the terminal scrollback."""

    def meter(self, *usages):
        from lupa.caption import UsageMeter
        instrument = UsageMeter()
        for usage in usages:
            instrument.record(usage)
        return instrument

    def report(self):
        return list((self.dir / "runs").glob("*.md"))[0].read_text(encoding="utf-8")

    def test_a_caller_that_measures_nothing_still_gets_a_report(self):
        self.write()
        self.assertIn("+2 added", self.report())

    def test_the_tokens_the_api_counted_are_written_down(self):
        self.write(usage=self.meter((588, 103), (600, 120)))
        text = self.report()
        self.assertIn("1188", text)
        self.assertIn("223", text)

    def test_the_report_puts_the_budget_next_to_the_measurement(self):
        self.write(usage=self.meter((589, 103)))
        text = self.report()
        # the constant itself, not a literal that happens to be a substring of it
        from lupa.caption import INPUT_TOKENS_PER_IMAGE
        self.assertIn(str(INPUT_TOKENS_PER_IMAGE), text)
        self.assertIn("1600", text)
        self.assertIn("589", text)

    def test_a_run_that_measured_nothing_says_unknown_in_the_report(self):
        self.write(usage=self.meter(None, None))
        self.assertIn("unknown", self.report().lower())

    def test_the_report_prices_a_synchronous_run_at_full_price(self):
        """Batch halves the bill. A report that always assumes batch halves a
        bill that was never halved — and the whole point here is to stop
        guessing about money.

        The harness writes with gemini-2.5-flash-lite: US$ 0.10 in, US$ 0.40 out
        per 1M tokens, so a million of each is US$ 0.50 undivided."""
        self.write(usage=self.meter((1_000_000, 1_000_000)), batch=False)
        self.assertIn("0.50", self.report())

    def test_the_report_still_halves_a_batch_run(self):
        self.write(usage=self.meter((1_000_000, 1_000_000)), batch=True)
        self.assertIn("0.25", self.report())
