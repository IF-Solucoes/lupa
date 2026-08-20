"""Incremental reconciliation: what changed since the last run."""
import unittest
from lupa.reconcile import reconcile


def remote(*pairs):
    return [{"id": i, "hash": h, "name": f"{i}.png"} for i, h in pairs]


def manifest(*pairs):
    return {"items": {i: {"hash": h} for i, h in pairs}}


class TestReconcile(unittest.TestCase):
    def test_a_new_collection_is_all_new(self):
        p = reconcile(remote(("a", "1"), ("b", "2")), {"items": {}})
        self.assertEqual(sorted(p.added), ["a", "b"])
        self.assertEqual(p.changed, [])
        self.assertEqual(p.removed, [])

    def test_no_change_means_nothing_to_do(self):
        p = reconcile(remote(("a", "1"), ("b", "2")), manifest(("a", "1"), ("b", "2")))
        self.assertEqual(sorted(p.unchanged), ["a", "b"])
        self.assertEqual(p.to_describe, [])
        self.assertTrue(p.empty)

    def test_a_new_file_comes_in_alone(self):
        p = reconcile(remote(("a", "1"), ("b", "2")), manifest(("a", "1")))
        self.assertEqual(p.added, ["b"])
        self.assertEqual(p.unchanged, ["a"])

    def test_a_different_hash_marks_the_file_as_changed(self):
        p = reconcile(remote(("a", "9")), manifest(("a", "1")))
        self.assertEqual(p.changed, ["a"])
        self.assertEqual(p.added, [])

    def test_a_file_missing_from_drive_is_removed(self):
        p = reconcile(remote(("a", "1")), manifest(("a", "1"), ("z", "8")))
        self.assertEqual(p.removed, ["z"])

    def test_a_trashed_file_counts_as_removed(self):
        r = [{"id": "a", "hash": "1", "name": "a.png", "trashed": True}]
        p = reconcile(r, manifest(("a", "1")))
        self.assertEqual(p.removed, ["a"])
        self.assertEqual(p.unchanged, [])

    def test_to_describe_joins_added_and_changed(self):
        p = reconcile(remote(("a", "9"), ("b", "2")), manifest(("a", "1")))
        self.assertEqual(sorted(p.to_describe), ["a", "b"])
        self.assertFalse(p.empty)

    def test_a_removal_alone_is_not_an_empty_run(self):
        # nothing to describe, but the catalog still has to be rewritten
        p = reconcile(remote(("a", "1")), manifest(("a", "1"), ("z", "8")))
        self.assertEqual(p.to_describe, [])
        self.assertFalse(p.empty)


if __name__ == "__main__":
    unittest.main()
