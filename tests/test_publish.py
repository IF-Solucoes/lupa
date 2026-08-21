"""Publishing the index to Drive: round trips are the cost here."""
import tempfile
import unittest
from pathlib import Path

from lupa.publish import plan_uploads


class TestUploadPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "INDEX.md").write_text("x")
        (self.dir / "catalog.jsonl").write_text("x")
        (self.dir / "by-tag").mkdir()
        (self.dir / "by-tag" / "food.md").write_text("x")
        (self.dir / "runs").mkdir()
        (self.dir / "runs" / "r.md").write_text("x")
        (self.dir / ".backup").mkdir()
        (self.dir / ".backup" / "old.md").write_text("x")
        (self.dir / ".thumbs").mkdir()
        (self.dir / ".thumbs" / "a.jpg").write_text("x")
        (self.dir / ".lock").write_text("x")
        (self.dir / "index.db").write_text("x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_uploads_the_index_files(self):
        names = {path.name for path, _ in plan_uploads(self.dir)}
        self.assertIn("INDEX.md", names)
        self.assertIn("catalog.jsonl", names)

    def test_it_keeps_the_folder_structure(self):
        folders = {folder for _, folder in plan_uploads(self.dir)}
        self.assertIn("by-tag", folders)
        self.assertIn("", folders)

    def test_it_never_uploads_the_backup(self):
        self.assertNotIn(".backup", {folder for _, folder in plan_uploads(self.dir)})

    def test_it_never_uploads_the_lock(self):
        self.assertNotIn(".lock", {path.name for path, _ in plan_uploads(self.dir)})

    def test_it_never_uploads_derived_data(self):
        # the database and the curation thumbnails are rebuildable locally
        names = {path.name for path, _ in plan_uploads(self.dir)}
        self.assertNotIn("index.db", names)
        folders = {folder for _, folder in plan_uploads(self.dir)}
        self.assertNotIn(".thumbs", folders)

    def test_the_plan_is_deterministic(self):
        self.assertEqual(plan_uploads(self.dir), plan_uploads(self.dir))


if __name__ == "__main__":
    unittest.main()


BS = chr(92)
FOLDER_MIME = "application/vnd.google-apps.folder"


class FakeDrive:
    """A Drive stand-in with real state: files, parents, and a trash flag.

    It answers the three calls publish makes — list, create, update — so a test
    can assert on what ended up in the trash instead of on which methods were
    called.
    """

    def __init__(self):
        self.items, self.serial = {}, 0

    # --- helpers for the test, not part of the API ---
    def add(self, name, parent, mime="text/markdown"):
        self.serial += 1
        key = f"id{self.serial}"
        self.items[key] = {"name": name, "parents": [parent], "mimeType": mime,
                           "trashed": False}
        return key

    def live(self, parent):
        return {item["name"] for item in self.items.values()
                if parent in item["parents"] and not item["trashed"]}

    def trashed(self):
        return {item["name"] for item in self.items.values() if item["trashed"]}

    # --- the slice of the Drive API publish uses ---
    def files(self):
        return self

    def list(self, q=None, fields=None, **_):
        import re
        parent = re.search(r"'([^']+)' in parents", q).group(1)
        wanted = None
        if "name = '" in q:
            # First "' and ", not the last: the query goes on to name a mimeType
            # that carries its own quotes, and rsplit swallowed the name whole —
            # so ensure_folder never matched and built a second _lupa instead.
            rest = q.split("name = '", 1)[1]
            wanted = rest.split("' and ", 1)[0].replace(BS, "")
        only_folders = f"mimeType = '{FOLDER_MIME}'" in q

        found = []
        for key, item in self.items.items():
            if parent not in item["parents"] or item["trashed"]:
                continue
            if wanted is not None and item["name"] != wanted:
                continue
            if only_folders and item["mimeType"] != FOLDER_MIME:
                continue
            found.append({"id": key, "name": item["name"],
                          "mimeType": item["mimeType"]})
        return FakeCall({"files": found})

    def create(self, body=None, media_body=None, **_):
        body = body or {}
        key = self.add(body["name"], body["parents"][0],
                       body.get("mimeType", "text/markdown"))
        return FakeCall({"id": key})

    def update(self, fileId=None, body=None, media_body=None, **_):
        if body and body.get("trashed"):
            self.items[fileId]["trashed"] = True
        return FakeCall({"id": fileId})

    def get_media(self, **_):
        return FakeCall({})


class FakeCall:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class TestPublishRetiresWhatLeftTheIndex(unittest.TestCase):
    """An index that shrinks must not leave its old pages behind.

    Regression, 2026-08-20: publishing the CVN index left 85 by-tag pages from
    an earlier description pass sitting in the client's Drive. publish() only
    ever added and updated, so `_lupa/by-tag/` advertised 621 tags while the
    index knew 536. Nothing was broken — every page opened, every link worked —
    and that is the problem: the folder made a promise about the index that the
    search would never keep, with nothing to tell the two apart.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "INDEX.md").write_text("x", encoding="utf-8")
        (self.dir / "by-tag").mkdir()
        (self.dir / "by-tag" / "dog.md").write_text("x", encoding="utf-8")
        self.service = FakeDrive()
        self.root = self.service.add("ROOT", "-", mime=FOLDER_MIME)

    def tearDown(self):
        self.tmp.cleanup()

    def seed_remote(self):
        """A previous publish, with one tag the index no longer has."""
        index_folder = self.service.add("_lupa", self.root, mime=FOLDER_MIME)
        by_tag = self.service.add("by-tag", index_folder, mime=FOLDER_MIME)
        self.service.add("INDEX.md", index_folder)
        self.service.add("dog.md", by_tag)
        self.service.add("blob.md", by_tag)
        return by_tag

    def test_a_page_the_index_no_longer_has_is_retired(self):
        from lupa.publish import publish
        by_tag = self.seed_remote()
        publish(self.service, self.root, self.dir, report=lambda *a: None)
        self.assertNotIn("blob.md", self.service.live(by_tag),
                         "a page from a superseded index stayed in the client's Drive")

    def test_a_page_still_in_the_index_is_kept(self):
        """Anti-tautology: reconciling must not empty the folder."""
        from lupa.publish import publish
        by_tag = self.seed_remote()
        publish(self.service, self.root, self.dir, report=lambda *a: None)
        self.assertIn("dog.md", self.service.live(by_tag))

    def test_it_goes_to_the_trash_and_is_not_destroyed(self):
        from lupa.publish import publish
        self.seed_remote()
        publish(self.service, self.root, self.dir, report=lambda *a: None)
        self.assertIn("blob.md", self.service.trashed())

    def test_an_empty_plan_retires_nothing(self):
        """A publish with nothing to say must not speak for the whole folder.

        Whatever makes the plan empty — a broken read, an index that never got
        written — the answer is never "then everything on Drive is stale".
        """
        from lupa.publish import publish
        by_tag = self.seed_remote()
        empty = Path(tempfile.mkdtemp())
        publish(self.service, self.root, empty, report=lambda *a: None)
        self.assertIn("blob.md", self.service.live(by_tag))
        self.assertIn("dog.md", self.service.live(by_tag))

    def test_it_says_what_it_retired(self):
        from lupa.publish import publish
        self.seed_remote()
        said = []
        publish(self.service, self.root, self.dir, report=said.append)
        self.assertTrue(any("1" in line and "retired" in line.lower()
                            for line in said),
                        f"the removal was silent: {said}")
