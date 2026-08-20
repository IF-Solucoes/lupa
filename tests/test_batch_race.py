"""One run, one batch — even with eight threads asking at once.

A Gemini batch is charged when it is CREATED. `make_batch_describer` submits it
lazily, on the first call, and `pipeline._describe_many` makes that first call
from a ThreadPoolExecutor with `--workers` threads (default 8). With a guard that
only reads a flag, all eight threads walked past it before any of them had an
answer to store, so all eight built and paid for their own batch — confirmed in
production: 9 images indexed, 8 batches created inside 1.5 seconds.

The same window multiplies the network: the assembly loop calls `source.fetch()`
for every id in the plan, so N threads download every image N times.

These tests reproduce the window on purpose — the create_batch stand-in sleeps —
so they fail on scheduling luck rather than passing on it.
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from lupa import cli, gemini, inflight, pipeline

MODEL = "gemini-2.5-flash-lite"
COLLECTION = "lote-prova"
WORKERS = 8
IDS = [f"img-{n:02d}" for n in range(20)]


def an_item(file_id):
    return {"id": file_id, "file": f"{file_id}.png", "hash": f"h-{file_id}",
            "mime": "image/png", "w": 1080, "h": 1350, "exif": {},
            "trashed": False, "size": 100,
            "url": f"https://example.invalid/{file_id}"}


def a_result(keys):
    return "\n".join(
        json.dumps({"key": key, "response": {"candidates": [
            {"content": {"parts": [{"text": json.dumps({"caption": f"about {key}"})}]}}]}})
        for key in keys)


class PlainSource:
    """What the pipeline itself fetches — one download per image, by design."""

    def fetch(self, _file_id):
        return b"\x89PNG\r\n\x1a\n-bytes", "image/png"


class CountingSource:
    """The source handed to the describer: it only ever sees the batch assembly
    loop, so one fetch per id is the whole correct count."""

    def __init__(self):
        self.counts = {}
        self.guard = threading.Lock()

    def fetch(self, file_id):
        with self.guard:
            self.counts[file_id] = self.counts.get(file_id, 0) + 1
        return b"\x89PNG\r\n\x1a\n-bytes", "image/png"

    @property
    def total(self):
        return sum(self.counts.values())


class SlowCreate:
    """gemini.create_batch, counted — and slow, which is what holds the race
    window open long enough for every worker to walk into it."""

    def __init__(self, name="batches/one-and-only", delay=0.05):
        self.name, self.delay = name, delay
        self.calls = 0
        self.guard = threading.Lock()

    def __call__(self, api_key, lines, model=None, name="lupa-batch"):
        with self.guard:
            self.calls += 1
        time.sleep(self.delay)
        return self.name


class CountingAwait:
    def __init__(self, raw="", delay=0.02):
        self.raw, self.delay = raw, delay
        self.names = []
        self.guard = threading.Lock()

    def __call__(self, api_key, batch_name, **_kw):
        with self.guard:
            self.names.append(batch_name)
        time.sleep(self.delay)
        return self.raw


class CountingForget:
    def __init__(self, real):
        self.real, self.calls = real, 0
        self.guard = threading.Lock()

    def __call__(self, index_dir):
        with self.guard:
            self.calls += 1
        return self.real(index_dir)


class RaceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "_lupa"
        self.dir.mkdir(parents=True)
        self.saved = (gemini.create_batch, gemini.await_batch, inflight.forget)
        self.printed = []
        self.echo = threading.Lock()

    def tearDown(self):
        gemini.create_batch, gemini.await_batch, inflight.forget = self.saved
        self.tmp.cleanup()

    def say(self, line):
        with self.echo:
            self.printed.append(line)

    def run_the_pipeline(self, source, resume_batch=None):
        """The real describer, driven by the real _describe_many, on a real pool."""
        describer = cli.make_batch_describer(
            "api-key", MODEL, "pt-BR", source, IDS, on_progress=self.say,
            index_dir=self.dir, collection=COLLECTION, resume_batch=resume_batch)
        by_id = {file_id: an_item(file_id) for file_id in IDS}
        describer.items_by_id = by_id
        return pipeline._describe_many(PlainSource(), describer, self.dir,
                                       by_id, IDS, WORKERS)


class TestOneRunBuysOneBatch(RaceTestCase):
    def test_eight_workers_create_exactly_one_batch(self):
        creating = SlowCreate()
        gemini.create_batch = creating
        gemini.await_batch = CountingAwait(raw=a_result(IDS))
        source = CountingSource()

        described, failures = self.run_the_pipeline(source)

        self.assertEqual([], failures)
        self.assertEqual(len(IDS), len(described))
        self.assertEqual(1, creating.calls,
                         f"{creating.calls} batches were created and paid for, "
                         f"for one run of {len(IDS)} images")

    def test_every_image_is_downloaded_once_for_the_batch(self):
        gemini.create_batch = SlowCreate()
        gemini.await_batch = CountingAwait(raw=a_result(IDS))
        source = CountingSource()

        self.run_the_pipeline(source)

        repeated = {k: v for k, v in source.counts.items() if v != 1}
        self.assertEqual({}, repeated,
                         f"{source.total} fetches for {len(IDS)} images — "
                         f"the assembly loop ran more than once")
        self.assertEqual(len(IDS), source.total)

    def test_only_one_receipt_is_written_and_it_is_cleared(self):
        gemini.create_batch = SlowCreate()
        gemini.await_batch = CountingAwait(raw=a_result(IDS))
        forgetting = CountingForget(self.saved[2])
        inflight.forget = forgetting

        self.run_the_pipeline(CountingSource())

        self.assertIsNone(inflight.read(self.dir),
                          "a consumed batch stayed resumable")
        self.assertEqual(1, forgetting.calls,
                         "the receipt was cleared more than once — more than one "
                         "batch went through this run")


class TestAFailedSubmissionIsNotRetriedByTheOtherWorkers(RaceTestCase):
    """The gate makes the workers queue. If the first one comes out of the wait
    empty-handed, the second must not read "no results yet" as "buy another"."""

    def test_a_timeout_does_not_buy_a_second_batch(self):
        creating = SlowCreate()
        gemini.create_batch = creating

        def timing_out(api_key, batch_name, **_kw):
            raise gemini.BatchTimeout("still running")

        gemini.await_batch = timing_out

        described, failures = self.run_the_pipeline(CountingSource())

        self.assertEqual({}, described)
        self.assertEqual(len(IDS), len(failures))
        self.assertEqual(1, creating.calls,
                         f"{creating.calls} batches were paid for while the first "
                         f"one was still running")
        self.assertEqual("batches/one-and-only", inflight.read(self.dir)["batch"],
                         "a timed-out batch lost its receipt")


class TestResumeStaysCorrectUnderConcurrency(RaceTestCase):
    """Serializing must not turn one resume into N waits on the same batch."""

    def setUp(self):
        super().setUp()
        inflight.remember(self.dir, "batches/already-paid", COLLECTION, MODEL, IDS)

    def test_resume_never_creates_and_waits_once(self):
        creating = SlowCreate()
        gemini.create_batch = creating
        waiting = CountingAwait(raw=a_result(IDS))
        gemini.await_batch = waiting
        forgetting = CountingForget(self.saved[2])
        inflight.forget = forgetting
        source = CountingSource()

        described, failures = self.run_the_pipeline(
            source, resume_batch="batches/already-paid")

        self.assertEqual([], failures)
        self.assertEqual(len(IDS), len(described))
        self.assertEqual(0, creating.calls, "a resume paid for a new batch")
        self.assertEqual(["batches/already-paid"], waiting.names,
                         f"the resumed batch was waited on {len(waiting.names)} times")
        self.assertEqual({}, source.counts,
                         "a resume downloaded images it does not need")
        self.assertEqual(1, forgetting.calls)
        self.assertIsNone(inflight.read(self.dir))


class TestASecondBatchNeverErasesAReceiptInSilence(unittest.TestCase):
    """Overwriting a receipt that names another batch is a bug's fingerprint:
    that other batch is paid for and about to lose its only name."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "_lupa"
        self.dir.mkdir(parents=True)
        self.said = []

    def tearDown(self):
        self.tmp.cleanup()

    def test_overwriting_another_batch_is_announced_loudly(self):
        inflight.remember(self.dir, "batches/first-paid", COLLECTION, MODEL, IDS,
                          on_warning=self.said.append)
        self.assertEqual([], self.said, "a first receipt cried wolf")

        inflight.remember(self.dir, "batches/second-paid", COLLECTION, MODEL, IDS,
                          on_warning=self.said.append)

        warning = "\n".join(self.said)
        self.assertTrue(warning, "a paid batch lost its receipt in silence")
        self.assertIn("batches/first-paid", warning,
                      "the warning does not name the batch being lost")
        self.assertIn("batches/second-paid", warning)
        self.assertIn("!!", warning)

    def test_rewriting_the_same_batch_says_nothing(self):
        inflight.remember(self.dir, "batches/same", COLLECTION, MODEL, IDS,
                          on_warning=self.said.append)
        inflight.remember(self.dir, "batches/same", COLLECTION, MODEL, IDS,
                          on_warning=self.said.append)
        self.assertEqual([], self.said)

    def test_the_new_batch_is_still_the_one_recorded(self):
        inflight.remember(self.dir, "batches/first-paid", COLLECTION, MODEL, IDS)
        inflight.remember(self.dir, "batches/second-paid", COLLECTION, MODEL, IDS,
                          on_warning=self.said.append)
        self.assertEqual("batches/second-paid", inflight.read(self.dir)["batch"],
                         "the warning was not allowed to stop the write")


if __name__ == "__main__":
    unittest.main()
