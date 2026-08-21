"""Guardrails: the index does not rebuild itself by accident."""
import io
import json
import contextlib
import shutil
import subprocess
import sys
import time
import os
import tempfile
import unittest
from pathlib import Path

from lupa.guards import (
    IndexAlreadyExists, LockBusy, check_before_indexing,
    needs_cost_confirmation, Lock, MAX_LOCK_AGE_S,
)


class TestIndexDoesNotOverwrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _with_index(self, total=3412):
        (self.dir / "MANIFEST.json").write_text(
            '{"collection": "if-editorial", "total": %d, "runs": 6}' % total)

    def test_an_untouched_collection_can_be_indexed(self):
        check_before_indexing(self.dir, collection="if-editorial")  # does not raise

    def test_an_indexed_collection_is_refused(self):
        self._with_index()
        with self.assertRaises(IndexAlreadyExists):
            check_before_indexing(self.dir, collection="if-editorial")

    def test_the_refusal_points_at_update(self):
        self._with_index()
        with self.assertRaises(IndexAlreadyExists) as ctx:
            check_before_indexing(self.dir, collection="if-editorial")
        self.assertIn("lupa update", str(ctx.exception))

    def test_rebuild_without_confirmation_is_refused(self):
        self._with_index()
        with self.assertRaises(IndexAlreadyExists):
            check_before_indexing(self.dir, collection="if-editorial", rebuild=True)

    def test_rebuild_with_the_wrong_name_is_refused(self):
        self._with_index()
        with self.assertRaises(IndexAlreadyExists):
            check_before_indexing(self.dir, collection="if-editorial",
                                    rebuild=True, confirm="other-collection")

    def test_rebuild_with_the_exact_name_passes(self):
        self._with_index()
        check_before_indexing(self.dir, collection="if-editorial",
                                rebuild=True, confirm="if-editorial")


class TestCostCeiling(unittest.TestCase):
    def test_below_the_ceiling_it_does_not_ask(self):
        self.assertFalse(needs_cost_confirmation(199, ceiling=200))

    def test_above_the_ceiling_it_asks(self):
        self.assertTrue(needs_cost_confirmation(201, ceiling=200))

    def test_a_zero_ceiling_disables_the_question(self):
        self.assertFalse(needs_cost_confirmation(9999, ceiling=0))


class TestLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.corpses = []
        self.notices = []

    def tearDown(self):
        self.tmp.cleanup()

    def _a_pid_that_is_certainly_dead(self):
        """A real child process, run to completion. Its pid existed for sure, and
        by the time this returns it is gone for sure. A made-up number like 999999
        proves nothing: on someone else's machine it may well be in use."""
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        # The Popen object is kept alive on purpose: while its handle is open
        # Windows will not hand the pid to anyone else, so the test cannot flake.
        self.corpses.append(child)
        return child.pid

    def _write_lock(self, pid, started):
        (self.dir / ".lock").write_text(json.dumps({"pid": pid, "started": started}))

    def test_a_second_concurrent_run_is_blocked(self):
        with Lock(self.dir):
            with self.assertRaises(LockBusy):
                with Lock(self.dir):
                    pass

    def test_the_lock_is_released_on_exit(self):
        with Lock(self.dir):
            pass
        with Lock(self.dir):  # does not raise
            pass

    def test_a_stale_lock_is_reclaimed(self):
        stale = time.time() - MAX_LOCK_AGE_S - 60
        self._write_lock(self._a_pid_that_is_certainly_dead(), stale)
        with Lock(self.dir, on_notice=self.notices.append):  # does not raise
            pass

    def test_a_lock_whose_owner_is_dead_is_reclaimed_however_fresh_it_is(self):
        """The defect this file exists for: a killed run leaves a .lock behind, and
        for half an hour the recovery lupa itself recommends (--resume-batch) is
        refused by the corpse of the run that failed. The pid is right there."""
        dead = self._a_pid_that_is_certainly_dead()
        self._write_lock(dead, time.time())      # seconds old: age alone would keep it
        with contextlib.redirect_stderr(io.StringIO()):
            with Lock(self.dir):                 # does not raise
                pass

    def test_reclaiming_a_dead_owner_is_announced_with_the_pid(self):
        dead = self._a_pid_that_is_certainly_dead()
        self._write_lock(dead, time.time())
        with Lock(self.dir, on_notice=self.notices.append):
            pass
        said = " ".join(self.notices)
        self.assertIn(str(dead), said)
        self.assertIn("no longer exists", said)

    def test_the_announcement_lands_on_stderr_when_nobody_is_listening(self):
        dead = self._a_pid_that_is_certainly_dead()
        self._write_lock(dead, time.time())
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with Lock(self.dir):
                pass
        self.assertIn(str(dead), stderr.getvalue())

    def test_a_live_owner_still_blocks(self):
        self._write_lock(os.getpid(), time.time())   # this very process is alive
        with self.assertRaises(LockBusy):
            with Lock(self.dir):
                pass

    def test_a_recycled_pid_does_not_pass_for_the_owner(self):
        """The pid is alive, but it belongs to a process that started AFTER the
        lock was written, so it cannot be the one that wrote it."""
        from lupa.guards import process_started_at
        born = process_started_at(os.getpid())
        if born is None:
            self.skipTest("process creation time is not readable on this platform")
        self._write_lock(os.getpid(), born - 60)     # young enough to survive the age rule
        with Lock(self.dir, on_notice=self.notices.append):   # does not raise
            pass

    def test_age_still_reclaims_a_lock_whose_owner_is_alive(self):
        """The safety net for the hung-but-breathing run."""
        self._write_lock(os.getpid(), time.time() - MAX_LOCK_AGE_S - 60)
        with Lock(self.dir, on_notice=self.notices.append):   # does not raise
            pass

    def test_an_unreadable_lock_is_still_reclaimed(self):
        (self.dir / ".lock").write_text("{not json at all")
        with Lock(self.dir, on_notice=self.notices.append):   # does not raise
            pass

    def test_a_lock_without_a_pid_falls_back_to_age(self):
        (self.dir / ".lock").write_text(json.dumps({"started": time.time()}))
        with self.assertRaises(LockBusy):
            with Lock(self.dir):
                pass

    def test_this_process_reads_as_alive(self):
        from lupa.guards import owner_is_alive
        self.assertTrue(owner_is_alive(os.getpid()))

    def test_a_dead_child_reads_as_dead(self):
        from lupa.guards import owner_is_alive
        self.assertFalse(owner_is_alive(self._a_pid_that_is_certainly_dead()))

    def test_a_nonsense_pid_is_never_alive(self):
        from lupa.guards import owner_is_alive
        for pid in (0, -1, None, "17"):
            self.assertFalse(owner_is_alive(pid), pid)

    def test_a_run_does_not_delete_a_lock_that_was_taken_from_it(self):
        """A run whose lock was reclaimed under it (the 30 min rule firing during
        a 3 h batch) must not delete the file on its way out: it belongs to
        whoever took it, and removing it would open the index to a third run."""
        outer = Lock(self.dir, on_notice=self.notices.append)
        outer.__enter__()
        self._write_lock(os.getpid(), time.time())   # somebody else took it over
        outer.__exit__(None, None, None)
        self.assertTrue((self.dir / ".lock").exists())
        self.assertIn("Not releasing", " ".join(self.notices))

    def test_the_lock_is_removed_even_on_error(self):
        with self.assertRaises(ValueError):
            with Lock(self.dir):
                raise ValueError("failure mid-run")
        self.assertFalse((self.dir / ".lock").exists())


if __name__ == "__main__":
    unittest.main()


class TestTheLockOutlivesTheLongestLegitimateRun(unittest.TestCase):
    """A lock must not expire while its owner is doing exactly what it should.

    MAX_LOCK_AGE_S was half an hour, guessed. A batch run waits on Gemini for up
    to BATCH_TIMEOUT_S — three hours — so from minute thirty onward a run that
    was working perfectly had its lock reclaimed out from under it, and a second
    run was free to walk into the index it was writing.

    The two numbers were written in different files by different hands and never
    compared. The lock's lifetime is not a preference: it is a consequence of the
    longest thing a run is allowed to do, so it is derived from it now.
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.notices = []

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_it_outlasts_the_batch_it_is_protecting(self):
        from lupa.gemini import BATCH_TIMEOUT_S
        self.assertGreater(
            MAX_LOCK_AGE_S, BATCH_TIMEOUT_S,
            "the lock expires before the batch it is supposed to protect")

    @contextlib.contextmanager
    def owner_that_is_really_alive(self):
        """Holds the liveness check True so the age rule is what gets tested.

        `owner_is_alive` also refuses a pid whose process started AFTER the lock
        did, which is how a recycled pid is caught — and it means this process
        cannot honestly pretend to have held a lock for an hour. Stubbing it is
        the only way to reach the age branch, and the age branch is the defect.
        """
        import lupa.guards as guards
        original = guards.owner_is_alive
        guards.owner_is_alive = lambda pid, started: True
        try:
            yield
        finally:
            guards.owner_is_alive = original

    def write_lock(self, age_s):
        (self.dir / ".lock").write_text(
            json.dumps({"pid": os.getpid(), "started": time.time() - age_s}),
            encoding="utf-8")

    def test_a_live_run_waiting_on_a_batch_keeps_its_lock(self):
        """Behavioural: the exact window the old half-hour limit got wrong."""
        from lupa.gemini import BATCH_TIMEOUT_S
        from lupa.guards import LockBusy

        self.assertLess(3600, BATCH_TIMEOUT_S, "fixture no longer inside a batch wait")
        self.write_lock(3600)
        with self.owner_that_is_really_alive():
            with self.assertRaises(LockBusy):
                with Lock(self.dir, on_notice=self.notices.append):
                    pass

    def test_a_run_older_than_any_legitimate_one_is_still_reclaimed(self):
        """Anti-tautology: the ceiling still exists, it just moved to the right
        place. Same stub, opposite verdict — which is what proves the stub is not
        the thing deciding the outcome."""
        self.write_lock(MAX_LOCK_AGE_S + 60)
        with self.owner_that_is_really_alive():
            with Lock(self.dir, on_notice=self.notices.append):
                pass
        self.assertTrue(any("limit" in line for line in self.notices), self.notices)
