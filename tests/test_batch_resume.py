"""A Gemini batch is charged when it is CREATED, not when it is read.

Losing the batch name — a process that dies, a wait that times out — loses the
money with it. These tests cover the record that makes a batch resumable: written
before the wait begins, cleared once the answers land, refused when the collection
drifted underneath it, and never published to Drive.
"""
import contextlib
import io
import json
import os
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path

from lupa import cli, config, gemini, inflight

IDS = ["a", "b"]
MODEL = "gemini-2.5-flash-lite"
COLLECTION = "if-editorial"


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


def pasted_target(message):
    """The argument the printed instruction asks for, as a shell hands it over.

    Quotes are consumed the way a terminal consumes them, so a target with a
    space in it only survives this function if the instruction quoted it — which
    is the point: on Windows the target is a path, and a path has a space in it
    more often than not.
    """
    lines = [line for line in str(message).splitlines()
             if "lupa update" in line and "--resume-batch" in line]
    if not lines:
        raise AssertionError(f"no resume instruction was printed at all:\n{message}")
    words = shlex.split(lines[0].strip(), posix=False)
    token = words[words.index("update") + 1]
    if len(token) > 1 and token[0] == token[-1] and token[0] in "\"'":
        token = token[1:-1]
    return token


class BatchThatNeverFinishes:
    """Stands in for the network, and for nothing else.

    The real gemini.await_batch runs — its own loop, its own deadline, its own
    message — against a job that stays RUNNING, so the instruction under test is
    the one lupa actually writes, not one the test made up.

    kill — the run is killed while it waits, the way a closed terminal or a
    Ctrl-C kills it. KeyboardInterrupt, not an Exception, so it goes straight up
    through the pipeline instead of being filed as a failed image: this is the
    run the receipt on disk exists for, and the run that never reaches the
    registration at the end of command_index.
    """

    def __init__(self, real, kill=False):
        self.real = real
        self.kill = kill
        self.hints = []
        self.message = None
        # The registry as it stood WHILE the instruction was on the screen. The
        # instruction is printed here, not at the end of the run, so this is the
        # registry it has to work against.
        self.registry_while_waiting = None

    def __call__(self, api_key, batch_name, **kw):
        self.hints.append(kw.get("resume_hint"))
        self.registry_while_waiting = config.read_config(file_env=config.environment())
        kw.pop("interval", None)
        kw.pop("timeout_s", None)
        saved = gemini._get
        gemini._get = lambda url, key: json.dumps(
            {"metadata": {"state": "JOB_STATE_RUNNING"}}).encode()
        try:
            return self.real(api_key, batch_name, interval=0.01, timeout_s=0.03, **kw)
        except gemini.BatchTimeout as timed_out:
            self.message = str(timed_out)
            if self.kill:
                raise KeyboardInterrupt() from None
            raise
        finally:
            gemini._get = saved


class TestThePrintedResumeInstructionIsExecutable(unittest.TestCase):
    """The line that rescues money already spent must work pasted, unchanged, at
    the moment it is printed.

    Reproduced live with a real paid batch: a run died waiting, printed
    `lupa update lote-prova --resume-batch`, and that command answered
    `I could not make sense of "lote-prova"`. A collection only enters the
    registry at the END of a run that finished, and a run that dies waiting on
    its batch is precisely the run that never gets there — so the name in the
    instruction resolved to nothing exactly when it was the only way back to the
    money.

    Behavioral on purpose: the whole CLI runs, and the instruction is taken out
    of what it printed and fed back to the resolver the next run would use.
    """

    KEYS = ("LUPA_ENV", "LUPA_CONFIG", "LUPA_INDEXES", "LUPA_STATE_DIR",
            "GEMINI_API_KEY", "LUPA_MODEL", "LUPA_BATCH", "LUPA_LANG",
            "LUPA_CONFIRM_ABOVE", "LUPA_OAUTH_CLIENT", "LUPA_OAUTH_TOKEN")

    class FakeSource:
        def list(self):
            return [{"id": name, "file": f"{name}.png", "hash": name,
                     "mime": "image/png", "w": 1080, "h": 1350, "exif": {},
                     "url": f"https://example.invalid/{name}",
                     "trashed": False, "size": 100}
                    for name in ("a", "b")]

        def fetch(self, _file_id):
            return b"bytes", "image/png"

    def setUp(self):
        self.saved_env = {key: os.environ.pop(key, None) for key in self.KEYS}
        self.home = Path(tempfile.mkdtemp(prefix="lupa-resume-"))
        # A space, on purpose: this is what a Windows target looks like, and an
        # unquoted one reaches argparse as two arguments.
        self.collection = self.home / "Minhas Fotos"
        self.collection.mkdir()

        env_file = self.home / "lupa.env"
        env_file.write_text("GEMINI_API_KEY=abc\n", encoding="utf-8")
        os.environ["LUPA_ENV"] = str(env_file)
        os.environ["LUPA_CONFIG"] = str(self.home / "collections.json")
        os.environ["LUPA_INDEXES"] = str(self.home / "indexes")

        self.saved_cli = (cli.build_source, gemini.create_batch, gemini.await_batch)
        self.real_await = gemini.await_batch
        cli.build_source = lambda *a, **k: (self.FakeSource(), None)
        gemini.create_batch = lambda *a, **k: "batches/xyz-789"
        self.waiting = self.wait_that(kill=False)

    def tearDown(self):
        cli.build_source, gemini.create_batch, gemini.await_batch = self.saved_cli
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.home, ignore_errors=True)

    def wait_that(self, kill):
        waiting = BatchThatNeverFinishes(self.real_await, kill=kill)
        gemini.await_batch = waiting
        return waiting

    def run_lupa(self, *extra):
        """Runs the CLI over the fake source. Returns everything it printed.

        KeyboardInterrupt is let through the same way the real process lets it
        through: the run stops where it stood, and whatever command_index would
        have done afterwards does not happen.
        """
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
            try:
                cli.main(["index", str(self.collection), "--yes", "--no-push",
                          "--no-contact-sheets", *extra])
            except SystemExit as stop:
                if stop.code:
                    printed.write(f"\n{stop.code}\n")
            except KeyboardInterrupt:
                pass
        return printed.getvalue()

    def index_dir(self):
        return self.home / "indexes" / "minhas-fotos"

    def registry_now(self):
        """The registry as it stands on disk — what the next command will read."""
        return config.read_config(file_env=config.environment())

    def resolves(self, message, registry):
        """Does the printed instruction survive being pasted? Raises if not."""
        entry = pasted_target(message)
        try:
            return cli.resolve_entry(entry, registry)
        except Exception as error:
            raise AssertionError(
                f"the instruction says to run `lupa update {entry} --resume-batch`, "
                f"and that command dies with:\n  {error}") from None

    def interrupted_run(self):
        """A run killed while waiting on a batch already paid for.

        This is the state the whole resume machinery exists for: money spent, a
        receipt on disk, and nothing after it in command_index having run.
        """
        self.waiting = self.wait_that(kill=True)
        printed = self.run_lupa()
        self.assertIsNotNone(inflight.read(self.index_dir()),
                             "no receipt was left behind; there is nothing to resume")
        return printed

    def test_a_killed_run_still_leaves_the_short_name_usable(self):
        """The short name is what the tool promises. Registering only at the end
        of a run that finished is what broke that promise for the one run that
        needed it — the run that died holding a paid batch."""
        self.interrupted_run()
        target = cli.resolve_entry("minhas-fotos", self.registry_now())
        self.assertEqual(self.collection, target.path)

    def test_the_wait_really_timed_out_on_a_paid_batch(self):
        self.run_lupa()
        self.assertIn("ALREADY CHARGED", self.waiting.message or "",
                      "the scenario under test did not happen; the rest proves nothing")
        self.assertIn("batches/xyz-789", self.waiting.message)

    def test_the_timeout_instruction_can_be_pasted_while_it_is_on_the_screen(self):
        """The message is printed during the wait — so it is against the registry
        of that moment, not of some later run, that it has to work."""
        self.run_lupa()
        self.resolves(self.waiting.message, self.waiting.registry_while_waiting)

    def test_the_timeout_instruction_reaches_the_screen_whole(self):
        """The pipeline files a timeout as one failed image among others, and the
        run report flattens the error to 200 characters — which cut the batch
        name in half and dropped the resume command off the end entirely. The
        only copy left was runs/*.errors.jsonl, which nobody is looking at while
        the terminal is saying the run failed."""
        printed = self.run_lupa()
        self.assertIn("batches/xyz-789", printed,
                      "the batch name — the receipt — never reached the screen")
        self.resolves(printed, self.waiting.registry_while_waiting)

    def test_the_timeout_instruction_points_at_this_collection(self):
        self.run_lupa()
        target = self.resolves(self.waiting.message,
                               self.waiting.registry_while_waiting)
        self.assertEqual("minhas-fotos", target.name,
                         "the instruction resolves, but to another collection")

    def test_the_block_on_the_next_run_can_be_pasted_and_run(self):
        """After a killed run, the next one refuses to start — a batch is in
        flight and paid for — and prints its own copy of the instruction."""
        self.interrupted_run()
        blocked = self.run_lupa()
        self.assertIn("ALREADY CHARGED", blocked)
        self.resolves(blocked, self.registry_now())

    def test_the_dry_run_note_can_be_pasted_and_run(self):
        self.interrupted_run()
        noted = self.run_lupa("--dry-run")
        self.assertIn("in flight", noted)
        self.resolves(noted, self.registry_now())

    def test_the_instruction_that_was_blocked_actually_resumes_the_batch(self):
        """End to end: paste it, and the paid batch is collected instead of a
        second one being bought."""
        self.interrupted_run()
        blocked = self.run_lupa()
        entry = pasted_target(blocked)

        bought = []
        gemini.create_batch = lambda *a, **k: bought.append(1) or "batches/second"
        gemini.await_batch = lambda api_key, name, **kw: a_result(["a", "b"])

        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
            try:
                cli.main(["update", entry, "--resume-batch", "--yes", "--no-push",
                          "--no-contact-sheets"])
            except SystemExit as stop:
                if stop.code:
                    printed.write(f"\n{stop.code}\n")

        self.assertEqual([], bought, "the resume paid for a second batch")
        self.assertIn("+2 added", printed.getvalue())


if __name__ == "__main__":
    unittest.main()
