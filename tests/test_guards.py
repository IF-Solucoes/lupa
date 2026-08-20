"""Guardrails: the index does not rebuild itself by accident."""
import time
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

    def tearDown(self):
        self.tmp.cleanup()

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
        (self.dir / ".lock").write_text('{"pid": 999999, "started": %f}' % stale)
        with Lock(self.dir):  # does not raise: o dono sumiu faz tempo
            pass

    def test_the_lock_is_removed_even_on_error(self):
        with self.assertRaises(ValueError):
            with Lock(self.dir):
                raise ValueError("failure mid-run")
        self.assertFalse((self.dir / ".lock").exists())


if __name__ == "__main__":
    unittest.main()
