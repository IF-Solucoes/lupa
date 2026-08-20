"""Integration: the index → update → update cycle, no network, no model spend."""
import json
import tempfile
import unittest
from pathlib import Path

from lupa.guards import IndexAlreadyExists
from lupa.pipeline import run


class FakeSource:
    """A pretend Drive: returns metadata and image bytes."""

    def __init__(self, files):
        self.files = files
        self.fetched = []

    def list(self):
        return list(self.files)

    def fetch(self, file_id):
        self.fetched.append(file_id)
        return b"bytes", "image/png"


class FakeModel:
    """Counts its calls — the metric that proves the incremental behavior."""

    def __init__(self):
        self.calls = []

    def __call__(self, item, image, mime):
        self.calls.append(item["id"])
        return {"caption": f"description of {item['file']}",
                "tags": ["shared-tag", item["id"]],
                "scene": "indoor", "people": 0, "palette": ["#000000"],
                "has_text": True, "text": f"words on {item['id']}"}


def a_file(file_id, digest, name=None):
    return {"id": file_id, "file": name or f"{file_id}.png", "hash": digest,
            "mime": "image/png", "w": 1080, "h": 1350, "exif": {},
            "url": f"https://example.invalid/{file_id}", "trashed": False, "size": 100}


class PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "_lupa"
        self.model = FakeModel()

    def tearDown(self):
        self.tmp.cleanup()

    def execute(self, source, mode="update", **kw):
        return run(collection="if-editorial", index_dir=self.dir, source=source,
                   describe=kw.pop("describe", self.model), mode=mode,
                   now=kw.pop("now", "2026-08-20T10-00-00"), **kw)

    def catalog(self):
        # encoding spelled out: a Windows default of cp1252 cannot even read
        # back a catalog holding an accented word, which is most of them here.
        lines = (self.dir / "catalog.jsonl").read_text(
            encoding="utf-8").strip().splitlines()
        return [json.loads(line) for line in lines if line.strip()]


class TestTheTextReachesTheCatalog(PipelineTestCase):
    """The whole path, end to end: model → merge → catalog.jsonl.

    Every unit on this route was fixed separately; this is the one that would have
    caught the original defect from the outside, where it actually hurt — 875 rows
    written with has_text false and text empty, and nobody looking at a unit.
    """

    def test_what_the_model_read_in_the_image_is_what_gets_written(self):
        self.execute(FakeSource([a_file("a", "1")]), mode="index")
        row = self.catalog()[0]
        self.assertIs(row["has_text"], True)
        self.assertEqual(row["text"], "words on a")

    def test_a_model_that_sees_no_text_writes_a_false_and_an_empty_string(self):
        quiet = lambda item, image, mime: {"caption": "c", "tags": ["t"]}
        self.execute(FakeSource([a_file("a", "1")]), mode="index", describe=quiet)
        row = self.catalog()[0]
        self.assertIs(row["has_text"], False)
        self.assertEqual(row["text"], "")

    def test_the_two_fields_keep_the_types_every_reader_already_expects(self):
        self.execute(FakeSource([a_file("a", "1")]), mode="index")
        row = self.catalog()[0]
        self.assertIsInstance(row["has_text"], bool)
        self.assertIsInstance(row["text"], str)


class TestFirstRun(PipelineTestCase):
    def test_it_indexes_everything_and_writes_the_index(self):
        source = FakeSource([a_file("a", "1"), a_file("b", "2")])
        result = self.execute(source, mode="index")
        self.assertEqual(sorted(self.model.calls), ["a", "b"])
        self.assertEqual(len(self.catalog()), 2)
        self.assertEqual(result["plan"].added, ["a", "b"])

    def test_indexing_an_already_indexed_collection_is_refused(self):
        source = FakeSource([a_file("a", "1")])
        self.execute(source, mode="index")
        with self.assertRaises(IndexAlreadyExists):
            self.execute(source, mode="index")


class TestIncremental(PipelineTestCase):
    def setUp(self):
        super().setUp()
        self.source = FakeSource([a_file("a", "1"), a_file("b", "2")])
        self.execute(self.source, mode="index")
        self.model.calls.clear()

    def test_a_run_without_changes_never_calls_the_model(self):
        self.execute(self.source)
        self.assertEqual(self.model.calls, [])

    def test_a_run_without_changes_downloads_nothing(self):
        self.source.fetched.clear()
        self.execute(self.source)
        self.assertEqual(self.source.fetched, [])

    def test_a_new_file_is_described_on_its_own(self):
        self.source.files.append(a_file("c", "3"))
        self.execute(self.source)
        self.assertEqual(self.model.calls, ["c"])
        self.assertEqual(len(self.catalog()), 3)

    def test_a_changed_file_is_described_again(self):
        self.source.files[0] = a_file("a", "NEW-HASH")
        self.execute(self.source)
        self.assertEqual(self.model.calls, ["a"])

    def test_a_deleted_file_leaves_the_catalog_for_free(self):
        self.source.files.pop(0)  # "a" is gone
        self.execute(self.source)
        self.assertEqual(self.model.calls, [])
        self.assertEqual([item["id"] for item in self.catalog()], ["b"])

    def test_an_old_description_survives_the_run(self):
        self.source.files.append(a_file("c", "3"))
        self.execute(self.source)
        previous = [i for i in self.catalog() if i["id"] == "a"][0]
        self.assertEqual(previous["caption"], "description of a.png")


class TestPlanWithoutSpending(PipelineTestCase):
    def test_dry_run_never_calls_the_model(self):
        source = FakeSource([a_file("a", "1")])
        result = self.execute(source, mode="index", dry_run=True)
        self.assertEqual(self.model.calls, [])
        self.assertEqual(result["plan"].added, ["a"])

    def test_dry_run_writes_no_index(self):
        self.execute(FakeSource([a_file("a", "1")]), mode="index", dry_run=True)
        self.assertFalse((self.dir / "catalog.jsonl").exists())

    def test_dry_run_estimates_the_cost(self):
        source = FakeSource([a_file(str(i), "h") for i in range(10)])
        result = self.execute(source, mode="index", dry_run=True)
        self.assertGreater(result["estimated_cost"], 0)


class TestIsolatedFailure(PipelineTestCase):
    def test_a_failing_image_does_not_sink_the_run(self):
        def failing_model(item, image, mime):
            if item["id"] == "b":
                raise RuntimeError("corrupted image")
            return {"caption": "ok", "tags": ["t"]}

        source = FakeSource([a_file("a", "1"), a_file("b", "2")])
        result = run(collection="x", index_dir=self.dir, source=source,
                     describe=failing_model, mode="index", now="2026-08-20T10-00-00")
        self.assertEqual([item["id"] for item in self.catalog()], ["a"])
        self.assertEqual(len(result["failures"]), 1)
        self.assertIn("corrupted", result["failures"][0]["error"])


if __name__ == "__main__":
    unittest.main()


class TestContactSheets(PipelineTestCase):
    def test_the_run_reports_on_contact_sheets(self):
        result = self.execute(FakeSource([a_file("a", "1")]), mode="index")
        self.assertIn("contact_sheets", result)

    def test_sheets_can_be_switched_off(self):
        result = self.execute(FakeSource([a_file("a", "1")]), mode="index",
                              contact_sheets=False)
        self.assertEqual(result["contact_sheets"]["sheets"], 0)

    def test_a_missing_pillow_does_not_fail_the_run(self):
        # fake bytes are not a real image; thumbnailing must stay silent
        result = self.execute(FakeSource([a_file("a", "1")]), mode="index")
        self.assertTrue(result["written"])


class SlowSource(FakeSource):
    """Simulates network latency, so parallelism is measurable rather than assumed."""

    def fetch(self, file_id):
        import time
        time.sleep(0.02)
        return super().fetch(file_id)


class TestParallelism(PipelineTestCase):
    def test_workers_do_not_change_the_result(self):
        source = FakeSource([a_file(str(i), "h") for i in range(6)])
        self.execute(source, mode="index", workers=4)
        self.assertEqual(len(self.catalog()), 6)

    def test_the_catalog_order_is_stable_regardless_of_workers(self):
        files = [a_file(str(i), "h") for i in range(6)]
        self.execute(FakeSource(files), mode="index", workers=4)
        parallel_order = [item["id"] for item in self.catalog()]

        import shutil
        shutil.rmtree(self.dir)
        self.model.calls.clear()
        self.execute(FakeSource(files), mode="index", workers=1)
        self.assertEqual([item["id"] for item in self.catalog()], parallel_order)

    def test_parallel_is_faster_when_fetching_is_slow(self):
        import time
        files = [a_file(str(i), "h") for i in range(8)]

        start = time.perf_counter()
        self.execute(SlowSource(files), mode="index", workers=1)
        serial = time.perf_counter() - start

        import shutil
        shutil.rmtree(self.dir)
        start = time.perf_counter()
        self.execute(SlowSource(files), mode="index", workers=8)
        parallel = time.perf_counter() - start

        self.assertLess(parallel, serial)

    def test_a_failure_in_one_worker_does_not_lose_the_others(self):
        def flaky(item, image, mime):
            if item["id"] == "3":
                raise RuntimeError("bad image")
            return {"caption": "ok", "tags": ["t"]}

        from lupa.pipeline import run
        source = FakeSource([a_file(str(i), "h") for i in range(6)])
        result = run(collection="x", index_dir=self.dir, source=source,
                     describe=flaky, mode="index", now="2026-08-20T10-00-00", workers=4)
        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(len(self.catalog()), 5)


class TestFailuresAreNotSuccess(PipelineTestCase):
    """A run that failed must not read like a run that worked.

    Regression, 2026-08-20: 875 of 875 images failed with the same HTTP 404 (the
    model had been retired) and the run reported `+875 added`, printed `Done.`
    first and the failure last, and exited 0.
    """

    RETIRED = ("HTTP 404: gemini-2.5-flash-lite is no longer available; "
               "use gemini-3.5-flash-lite instead")

    def always_fails(self, message=RETIRED):
        def describe(item, image, mime):
            raise RuntimeError(message)
        return describe

    def half_fails(self, message=RETIRED):
        def describe(item, image, mime):
            if item["id"] == "b":
                raise RuntimeError(message)
            return {"caption": "ok", "tags": ["t"]}
        return describe

    def test_a_failed_image_is_not_counted_as_added(self):
        source = FakeSource([a_file("a", "1"), a_file("b", "2")])
        result = self.execute(source, mode="index", describe=self.half_fails())
        self.assertIn("+1 added", result["summary"])
        self.assertNotIn("+2 added", result["summary"])

    def test_the_failures_are_counted_where_they_belong(self):
        source = FakeSource([a_file("a", "1"), a_file("b", "2")])
        result = self.execute(source, mode="index", describe=self.half_fails())
        self.assertIn("!1 failed", result["summary"])

    def test_a_failed_image_reaches_neither_catalog_nor_manifest(self):
        """What --retry-failed depends on: a failure leaves no state behind."""
        source = FakeSource([a_file("a", "1"), a_file("b", "2")])
        self.execute(source, mode="index", describe=self.half_fails())
        manifest = json.loads((self.dir / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(manifest["items"]), ["a"])
        self.assertEqual([item["id"] for item in self.catalog()], ["a"])

    def test_a_total_failure_is_announced_on_the_first_line(self):
        source = FakeSource([a_file(letter, "1") for letter in "abc"])
        result = self.execute(source, mode="index", describe=self.always_fails())
        first = result["verdict"].splitlines()[0]
        self.assertIn("3", first)
        self.assertIn("failed", first.lower())

    def test_the_repeated_error_is_named_on_that_first_line(self):
        source = FakeSource([a_file(letter, "1") for letter in "abc"])
        result = self.execute(source, mode="index", describe=self.always_fails())
        first = result["verdict"].splitlines()[0]
        self.assertIn("no longer available", first)

    def test_a_total_failure_adds_nothing(self):
        source = FakeSource([a_file(letter, "1") for letter in "abc"])
        result = self.execute(source, mode="index", describe=self.always_fails())
        self.assertIn("+0 added", result["summary"])

    def test_a_partial_failure_is_not_a_total_one(self):
        source = FakeSource([a_file("a", "1"), a_file("b", "2")])
        result = self.execute(source, mode="index", describe=self.half_fails())
        self.assertIsNone(result["verdict"])

    def test_a_healthy_run_keeps_the_counters_it_always_had(self):
        source = FakeSource([a_file("a", "1"), a_file("b", "2")])
        result = self.execute(source, mode="index")
        self.assertEqual(result["summary"], result["plan"].summary())
        self.assertEqual(result["summary"],
                         "+2 added · ~0 changed · -0 removed · =0 unchanged")
        self.assertIsNone(result["verdict"])

    def test_a_dry_run_reports_the_plan_and_no_verdict(self):
        source = FakeSource([a_file("a", "1")])
        result = self.execute(source, mode="index", dry_run=True)
        self.assertEqual(result["summary"], result["plan"].summary())
        self.assertIsNone(result["verdict"])

    def test_a_failed_re_description_keeps_the_paid_one_and_its_old_hash(self):
        """Why --retry-failed still works: a failure records no new state.

        The old description stays in the catalog, the OLD hash stays in the
        manifest, and the next run therefore plans the image again on its own.
        """
        source = FakeSource([a_file("a", "1")])
        self.execute(source, mode="index")
        source.files[0] = a_file("a", "SECOND-VERSION")
        result = self.execute(source, describe=self.always_fails())

        self.assertEqual("+0 added · ~0 changed · -0 removed · =0 unchanged · !1 failed",
                         result["summary"])
        manifest = json.loads((self.dir / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual("1", manifest["items"]["a"]["hash"],
                         "a failed re-description must not stamp the new hash")
        again = self.execute(source, dry_run=True)
        self.assertEqual(["a"], again["plan"].changed)

    def test_a_lone_failure_is_not_written_as_all_1_images(self):
        source = FakeSource([a_file("a", "1")])
        result = self.execute(source, mode="index", describe=self.always_fails())
        self.assertNotIn("1 images", result["verdict"])


class TestTheRunAccountsForItsTokens(PipelineTestCase):
    """The meter is filled by the describer and has to survive to the report.

    Injected, like source and describe: the pipeline must stay network-free and
    the accounting must still be verifiable without credentials.
    """

    def meter(self, *usages):
        from lupa.caption import UsageMeter
        instrument = UsageMeter()
        for usage in usages:
            instrument.record(usage)
        return instrument

    def report(self):
        return list((self.dir / "runs").glob("*.md"))[0].read_text(encoding="utf-8")

    def test_the_meter_comes_back_in_the_result(self):
        instrument = self.meter((588, 103))
        result = self.execute(FakeSource([a_file("a", "1")]), mode="index",
                              usage=instrument)
        self.assertIs(result["usage"], instrument)

    def test_what_the_meter_counted_reaches_the_run_report(self):
        self.execute(FakeSource([a_file("a", "1")]), mode="index",
                     usage=self.meter((588, 103)))
        text = self.report()
        self.assertIn("588", text)
        self.assertIn("103", text)

    def test_a_describer_that_reports_usage_fills_the_meter_through_the_run(self):
        from lupa.caption import UsageMeter

        instrument = UsageMeter()

        def describe(item, image, mime):
            instrument.record((588, 103))
            return {"caption": "ok", "tags": ["t"]}

        self.execute(FakeSource([a_file("a", "1"), a_file("b", "2")]), mode="index",
                     describe=describe, usage=instrument)
        self.assertEqual(instrument.input_tokens, 1176)
        self.assertIn("1176", self.report())

    def test_a_run_without_a_meter_is_still_a_run(self):
        result = self.execute(FakeSource([a_file("a", "1")]), mode="index")
        self.assertTrue(result["written"])
        self.assertIsNone(result.get("usage"))


class TestTheNamesReachTheCatalog(PipelineTestCase):
    """The whole path for `entities`, from the model's reply to the files an
    agent reads. Every unit on this route is tested apart; this is the one that
    would catch the field being dropped somewhere between them — which is
    exactly how 875 rows once got written with an empty `text`.
    """

    class NamingModel:
        """Names the designs, and stays silent about the photographs — the real
        distribution, where most images carry no name at all."""

        def __call__(self, item, image, mime):
            named = item["file"].startswith("post")
            return {"caption": f"description of {item['file']}",
                    "tags": ["dog", "clinic"], "scene": "indoor", "people": 0,
                    "palette": ["#000000"], "has_text": named,
                    "text": "CASTRAÇÃO SOLIDÁRIA" if named else "",
                    "entities": ["Castração Solidária"] if named else []}

    def index_md(self):
        return (self.dir / "INDEX.md").read_text(encoding="utf-8")

    def run_it(self):
        source = FakeSource([a_file("a", "h1", name="post-01.png"),
                             a_file("b", "h2", name="gato.png")])
        self.execute(source, mode="index", describe=self.NamingModel())

    def test_the_name_lands_on_the_line_of_the_image_that_carries_it(self):
        self.run_it()
        rows = {item["file"]: item for item in self.catalog()}
        self.assertEqual(rows["post-01.png"]["entities"], ["Castração Solidária"])

    def test_an_image_that_names_nothing_carries_an_empty_list(self):
        self.run_it()
        rows = {item["file"]: item for item in self.catalog()}
        self.assertEqual(rows["gato.png"]["entities"], [])

    def test_the_index_publishes_the_name(self):
        self.run_it()
        self.assertIn("## Entities", self.index_md())
        self.assertIn("Castração Solidária", self.index_md())

    def test_the_name_gets_a_file_of_its_own(self):
        self.run_it()
        page = self.dir / "by-entity" / "castracao-solidaria.md"
        self.assertTrue(page.exists())
        self.assertIn("post-01.png", page.read_text(encoding="utf-8"))

    def test_a_model_that_never_mentions_the_field_still_indexes(self):
        """The old double, unchanged: a reply with no `entities` key at all."""
        source = FakeSource([a_file("a", "h1")])
        self.execute(source, mode="index")
        self.assertEqual(self.catalog()[0]["entities"], [])
        self.assertIn("## Entities", self.index_md())
        self.assertFalse((self.dir / "by-entity").exists())


class TestRebuildActuallyRebuilds(PipelineTestCase):
    """`--rebuild` has to describe every image again — or it is not a rebuild.

    Regression, 2026-08-20: run over a collection of 15 images already indexed and
    unchanged, `lupa index <url> --rebuild --confirm "<name>"` loaded the previous
    MANIFEST.json, reconciled against it, found nothing different, printed
    "Nothing changed since the last run" and exited 0. It had taken a backup and
    described nothing. The schema had just gained `entities`, and the documented
    way to pick that up ("when the schema changed") was exactly this command.
    """

    def setUp(self):
        super().setUp()
        self.source = FakeSource([a_file("a", "1"), a_file("b", "2")])
        self.execute(self.source, mode="index")
        self.model.calls.clear()
        self.source.fetched.clear()

    def rebuild(self, **kw):
        return self.execute(self.source, mode="index", rebuild=True,
                            confirm="if-editorial", **kw)

    def test_every_image_is_described_again(self):
        self.rebuild()
        self.assertEqual(sorted(self.model.calls), ["a", "b"])

    def test_the_plan_counts_them_all_as_work(self):
        result = self.rebuild(dry_run=True)
        self.assertEqual(sorted(result["plan"].to_describe), ["a", "b"])
        self.assertEqual(result["plan"].unchanged, [])
        self.assertFalse(result["plan"].empty)

    def test_the_estimate_is_the_price_of_the_whole_collection(self):
        from lupa.caption import estimate_cost

        result = self.rebuild(dry_run=True)
        self.assertEqual(estimate_cost(2, batch=True), result["estimated_cost"])
        self.assertGreater(result["estimated_cost"], 0)

    def test_the_old_description_is_replaced_not_reused(self):
        def second_pass(item, image, mime):
            return {"caption": "rebuilt", "tags": ["t"],
                    "entities": ["Castração Solidária"]}

        self.rebuild(describe=second_pass)
        captions = {item["id"]: item["caption"] for item in self.catalog()}
        self.assertEqual({"a": "rebuilt", "b": "rebuilt"}, captions)

    def test_a_failed_rebuild_does_not_silently_empty_the_catalog(self):
        """No description, no row — the backup is what holds the old ones."""
        def always_fails(item, image, mime):
            raise RuntimeError("model retired")

        result = self.rebuild(describe=always_fails)
        self.assertEqual([], self.catalog())
        self.assertIn("FAILED", result["verdict"])

    def test_the_backup_is_taken_before_anything_is_overwritten(self):
        def second_pass(item, image, mime):
            return {"caption": "rebuilt", "tags": ["t"]}

        self.rebuild(describe=second_pass, now="2026-08-21T09-00-00")
        kept = self.dir / ".backup" / "2026-08-21T09-00-00" / "catalog.jsonl"
        self.assertTrue(kept.exists(), "the previous index must be copied first")
        self.assertIn("description of a.png", kept.read_text(encoding="utf-8"))


class TestWithoutRebuildTheIncrementalIsUntouched(PipelineTestCase):
    """The promise of the tool. Making rebuild work may not cost it anything."""

    def setUp(self):
        super().setUp()
        self.source = FakeSource([a_file("a", "1"), a_file("b", "2")])
        self.execute(self.source, mode="index")
        self.model.calls.clear()
        self.source.fetched.clear()

    def test_an_unchanged_collection_still_describes_nothing(self):
        result = self.execute(self.source)
        self.assertEqual([], self.model.calls)
        self.assertEqual([], self.source.fetched)
        self.assertEqual(sorted(result["plan"].unchanged), ["a", "b"])

    def test_an_unchanged_collection_still_costs_nothing(self):
        result = self.execute(self.source, dry_run=True)
        self.assertEqual(0.0, result["estimated_cost"])

    def test_only_the_changed_image_is_paid_for_again(self):
        self.source.files[0] = a_file("a", "NEW-HASH")
        self.execute(self.source)
        self.assertEqual(["a"], self.model.calls)

    def test_the_descriptions_already_paid_for_survive(self):
        self.source.files.append(a_file("c", "3"))
        self.execute(self.source)
        kept = {item["id"]: item["caption"] for item in self.catalog()}
        self.assertEqual("description of a.png", kept["a"])
