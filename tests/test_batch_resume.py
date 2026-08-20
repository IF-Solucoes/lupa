"""A Gemini batch is charged when it is CREATED, not when it is read.

Losing the batch name — a process that dies, a wait that times out — loses the
money with it. These tests cover the record that makes a batch resumable: written
before the wait begins, cleared once the answers land, refused when the collection
drifted underneath it, and never published to Drive.
"""
import json
import tempfile
import unittest
from pathlib import Path

from lupa import cli, gemini, inflight

IDS = ["a", "b"]
MODEL = "gemini-2.5-flash-lite"
COLLECTION = "if-editorial"


def an_item(file_id):
    return {"id": file_id, "file": f"{file_id}.png", "hash": f"h-{file_id}",
            "mime": "image/png", "w": 1080, "h": 1350, "exif": {},
            "ocr_text": "", "labels": [], "trashed": False, "size": 100,
            "url": f"https://example.invalid/{file_id}"}


def a_result(keys):
    return "\n".join(
        json.dumps({"key": key, "response": {"candidates": [
            {"content": {"parts": [{"text": json.dumps({"caption": f"about {key}"})}]}}]}})
        for key in keys)


class FakeSource:
    """Only .fetch is exercised here: the describer never lists."""

    def fetch(self, _file_id):
        return b"\x89PNG\r\n\x1a\n-bytes", "image/png"


class FakeCreate:
    """Stands in for gemini.create_batch. Counts submissions — the number that
    tells a resume apart from a second purchase."""

    def __init__(self, name="batches/xyz-789"):
        self.name = name
        self.calls = []

    def __call__(self, api_key, lines, model=None, name="lupa-batch"):
        self.calls.append(list(lines))
        return self.name


class FakeAwait:
    """Stands in for gemini.await_batch. Peeks at the record on disk before
    answering, which is how the ordering ("written first") gets proven."""

    def __init__(self, raw="", error=None, peek_at=None):
        self.raw, self.error, self.peek_at = raw, error, peek_at
        self.names = []
        self.seen_on_disk = None

    def __call__(self, api_key, batch_name, **_kw):
        self.names.append(batch_name)
        if self.peek_at is not None:
            self.seen_on_disk = inflight.read(self.peek_at)
        if self.error is not None:
            raise self.error
        return self.raw


class DescriberTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "_lupa"
        self.dir.mkdir(parents=True)
        self.saved = (gemini.create_batch, gemini.await_batch, inflight.remember)
        self.printed = []

    def tearDown(self):
        gemini.create_batch, gemini.await_batch, inflight.remember = self.saved
        self.tmp.cleanup()

    def describer(self, resume_batch=None):
        made = cli.make_batch_describer(
            "api-key", MODEL, "pt-BR", FakeSource(), IDS,
            on_progress=self.printed.append, index_dir=self.dir,
            collection=COLLECTION, resume_batch=resume_batch)
        made.items_by_id = {file_id: an_item(file_id) for file_id in IDS}
        return made

    @property
    def output(self):
        return "\n".join(self.printed)


class TestTheNameIsWrittenBeforeTheWait(DescriberTestCase):
    def test_the_record_is_on_disk_before_await_batch_is_entered(self):
        gemini.create_batch = FakeCreate()
        waiting = FakeAwait(error=gemini.BatchTimeout("timed out"), peek_at=self.dir)
        gemini.await_batch = waiting

        with self.assertRaises(gemini.GeminiError):
            self.describer()(an_item("a"), b"x", "image/png")

        self.assertIsNotNone(waiting.seen_on_disk,
                             "nothing was recorded before the wait began")
        self.assertEqual("batches/xyz-789", waiting.seen_on_disk["batch"])

    def test_the_record_survives_the_run_that_died_waiting(self):
        gemini.create_batch = FakeCreate()
        gemini.await_batch = FakeAwait(error=gemini.BatchTimeout("timed out"))

        with self.assertRaises(gemini.GeminiError):
            self.describer()(an_item("a"), b"x", "image/png")

        left = inflight.read(self.dir)
        self.assertIsNotNone(left, "the batch name died with the process")
        self.assertEqual("batches/xyz-789", left["batch"])
        self.assertEqual(1, left["v"])
        self.assertEqual(COLLECTION, left["collection"])
        self.assertEqual(MODEL, left["model"])


class RefusingDisk:
    """Stands in for inflight.remember when the disk says no — full, read-only,
    or plain I/O failure. Counts calls so the attempt itself stays observable."""

    def __init__(self, error=None):
        self.error = error or OSError(28, "No space left on device")
        self.calls = 0

    def __call__(self, *_args, **_kw):
        self.calls += 1
        raise self.error


class TestBookkeepingNeverCostsThePaidBatch(DescriberTestCase):
    """The batch is charged the instant create_batch returns. From that point on
    the name is the money, and neither printing it nor keeping the run alive may
    depend on a disk that can refuse."""

    def test_the_name_is_printed_even_when_the_record_cannot_be_written(self):
        gemini.create_batch = FakeCreate()
        gemini.await_batch = FakeAwait(raw=a_result(IDS))
        inflight.remember = RefusingDisk()

        self.describer()(an_item("a"), b"x", "image/png")

        self.assertIn("batches/xyz-789", self.output,
                      "the batch name never reached the screen: the receipt is gone")

    def test_a_failed_write_does_not_kill_the_run(self):
        gemini.create_batch = FakeCreate()
        waiting = FakeAwait(raw=a_result(IDS))
        gemini.await_batch = waiting
        refusing = RefusingDisk()
        inflight.remember = refusing

        described = self.describer()(an_item("a"), b"x", "image/png")

        self.assertEqual(1, refusing.calls, "the record was never even attempted")
        self.assertEqual(["batches/xyz-789"], waiting.names,
                         "the run died of bookkeeping and abandoned a paid batch")
        self.assertEqual("about a", described["caption"])

    def test_a_failed_write_is_announced_loudly(self):
        gemini.create_batch = FakeCreate()
        gemini.await_batch = FakeAwait(raw=a_result(IDS))
        inflight.remember = RefusingDisk()

        self.describer()(an_item("a"), b"x", "image/png")

        warning = "\n".join(line for line in self.printed if "!!" in line)
        self.assertTrue(warning, "a lost receipt passed in silence")
        self.assertIn("batches/xyz-789", warning)
        self.assertRegex(warning, r"(?i)receipt")
        self.assertRegex(warning, r"(?i)resume")

    def test_a_write_that_works_says_nothing_alarming(self):
        gemini.create_batch = FakeCreate()
        gemini.await_batch = FakeAwait(raw=a_result(IDS))

        self.describer()(an_item("a"), b"x", "image/png")

        self.assertNotIn("!!", self.output)
        self.assertIn("batches/xyz-789", self.output)


class TestResumeDoesNotPayTwice(DescriberTestCase):
    def test_resuming_never_calls_create_batch(self):
        creating = FakeCreate()
        gemini.create_batch = creating
        waiting = FakeAwait(raw=a_result(IDS))
        gemini.await_batch = waiting

        described = self.describer(resume_batch="batches/old-42")(
            an_item("a"), b"x", "image/png")

        self.assertEqual([], creating.calls,
                         "the resume submitted — and paid for — a second batch")
        self.assertEqual(["batches/old-42"], waiting.names)
        self.assertEqual("about a", described["caption"])


class TestTheRecordIsClearedOnSuccess(DescriberTestCase):
    def test_a_consumed_batch_leaves_no_record_behind(self):
        gemini.create_batch = FakeCreate()
        gemini.await_batch = FakeAwait(raw=a_result(IDS))

        self.describer()(an_item("a"), b"x", "image/png")

        self.assertIsNone(inflight.read(self.dir),
                          "a batch already consumed can still be resumed by mistake")

    def test_a_batch_that_died_on_the_remote_side_leaves_no_record_either(self):
        gemini.create_batch = FakeCreate()
        gemini.await_batch = FakeAwait(
            error=gemini.GeminiError("batch ended in JOB_STATE_FAILED"))

        with self.assertRaises(gemini.GeminiError):
            self.describer()(an_item("a"), b"x", "image/png")

        self.assertIsNone(inflight.read(self.dir),
                          "a dead batch stayed registered as resumable")


class TestDriftRefusal(unittest.TestCase):
    """Results come back keyed by file id. Resuming a batch whose keys no longer
    match the plan writes a wrong — or silently short — index."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "_lupa"
        self.dir.mkdir(parents=True)
        inflight.remember(self.dir, "batches/xyz-789", COLLECTION, MODEL, IDS)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_same_plan_resumes(self):
        self.assertEqual("batches/xyz-789",
                         inflight.load_for_resume(self.dir, COLLECTION, MODEL, list(IDS)))

    def test_order_of_the_ids_is_not_drift(self):
        self.assertEqual("batches/xyz-789",
                         inflight.load_for_resume(self.dir, COLLECTION, MODEL, ["b", "a"]))

    def test_an_added_image_refuses_the_resume(self):
        with self.assertRaises(inflight.BatchDrift) as caught:
            inflight.load_for_resume(self.dir, COLLECTION, MODEL, ["a", "b", "c"])
        self.assertIn("batches/xyz-789", str(caught.exception))

    def test_a_removed_image_refuses_the_resume(self):
        with self.assertRaises(inflight.BatchDrift):
            inflight.load_for_resume(self.dir, COLLECTION, MODEL, ["a"])

    def test_another_model_refuses_the_resume(self):
        with self.assertRaises(inflight.BatchDrift):
            inflight.load_for_resume(self.dir, COLLECTION, "gemini-3-pro", list(IDS))

    def test_another_collection_refuses_the_resume(self):
        with self.assertRaises(inflight.BatchDrift):
            inflight.load_for_resume(self.dir, "outra-colecao", MODEL, list(IDS))

    def test_a_record_from_a_future_version_refuses_the_resume(self):
        path = inflight.record_path(self.dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["v"] = 99
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(inflight.BatchDrift):
            inflight.load_for_resume(self.dir, COLLECTION, MODEL, list(IDS))

    def test_nothing_in_flight_is_refused_too(self):
        inflight.forget(self.dir)
        with self.assertRaises(inflight.BatchDrift):
            inflight.load_for_resume(self.dir, COLLECTION, MODEL, list(IDS))


class Args:
    def __init__(self, resume_batch=False, no_batch=False, dry_run=False):
        self.resume_batch = resume_batch
        self.no_batch = no_batch
        self.dry_run = dry_run


class Plan:
    def __init__(self, ids):
        self.to_describe = list(ids)


class TestAnInFlightBatchIsNeverIgnored(unittest.TestCase):
    """Running `index` on top of a registered batch would pay twice, in silence."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "_lupa"
        self.dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def settle(self, args):
        return cli._settle_inflight_batch(args, self.dir, COLLECTION, MODEL, Plan(IDS))

    def test_without_a_record_nothing_happens(self):
        self.assertIsNone(self.settle(Args()))

    def test_a_registered_batch_stops_the_run_and_says_how_to_resume(self):
        inflight.remember(self.dir, "batches/xyz-789", COLLECTION, MODEL, IDS)
        with self.assertRaises(SystemExit) as caught:
            self.settle(Args())
        message = str(caught.exception)
        self.assertIn("batches/xyz-789", message)
        self.assertIn("--resume-batch", message)

    def test_resuming_returns_the_recorded_name(self):
        inflight.remember(self.dir, "batches/xyz-789", COLLECTION, MODEL, IDS)
        self.assertEqual("batches/xyz-789", self.settle(Args(resume_batch=True)))

    def test_resuming_with_nothing_in_flight_stops(self):
        with self.assertRaises(SystemExit):
            self.settle(Args(resume_batch=True))

    def test_drift_stops_the_resume(self):
        inflight.remember(self.dir, "batches/xyz-789", COLLECTION, MODEL, ["z"])
        with self.assertRaises(SystemExit) as caught:
            self.settle(Args(resume_batch=True))
        self.assertIn("batches/xyz-789", str(caught.exception))


class TestTheRecordNeverLeavesTheMachine(unittest.TestCase):
    """SKIPPED_NAMES is a denylist: a new private file lands in Drive by default."""

    def test_publish_does_not_upload_the_record(self):
        from lupa.publish import plan_uploads

        with tempfile.TemporaryDirectory() as tmp:
            index_dir = Path(tmp) / "_lupa"
            index_dir.mkdir()
            (index_dir / "catalog.jsonl").write_text("{}\n", encoding="utf-8")
            inflight.remember(index_dir, "batches/xyz-789", COLLECTION, MODEL, IDS)

            names = [Path(path).name for path, _ in plan_uploads(index_dir)]

        self.assertIn("catalog.jsonl", names)
        self.assertNotIn(inflight.RECORD_NAME, names)


if __name__ == "__main__":
    unittest.main()
