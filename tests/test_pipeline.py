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
                "scene": "indoor", "people": 0, "palette": ["#000000"]}


def a_file(file_id, digest, name=None):
    return {"id": file_id, "file": name or f"{file_id}.png", "hash": digest,
            "mime": "image/png", "w": 1080, "h": 1350, "exif": {},
            "ocr_text": "TEXT " * 10, "labels": [],
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
                   describe=self.model, mode=mode,
                   now=kw.pop("now", "2026-08-20T10-00-00"), **kw)

    def catalog(self):
        lines = (self.dir / "catalog.jsonl").read_text().strip().splitlines()
        return [json.loads(line) for line in lines if line.strip()]


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
