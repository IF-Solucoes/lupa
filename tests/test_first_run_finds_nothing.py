"""An empty plan on a FIRST run is not a success — it is a folder with no images.

Regression: `lupa index <folder that was never indexed>` printed

    Nothing changed since the last run. Nothing to do, nothing to pay.

and exited 0. There was no last run — the preflight three lines above had just
said so. Worse, the two likeliest real mistakes both arrive here disguised as
success: a Google Drive folder the account cannot read answers `files.list` with
an empty list rather than an error, and the wrong subfolder simply holds no
image. In both cases the owner was told the indexing worked when it never ran.

Behavioral on purpose: an exit code is only observable by running the command.
The incremental path — an existing collection with nothing to do — is the thing
these tests most have to protect, because it is the tool's central promise.
"""
import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from lupa import cli

# Every variable that could leak a real installation into this test.
KEYS = ("LUPA_ENV", "LUPA_CONFIG", "LUPA_INDEXES", "LUPA_STATE_DIR",
        "GEMINI_API_KEY", "LUPA_MODEL", "LUPA_BATCH", "LUPA_LANG",
        "LUPA_CONFIRM_ABOVE", "LUPA_OAUTH_CLIENT", "LUPA_OAUTH_TOKEN")


class Source:
    """The collection lupa is pointed at. Zero images is the case under test."""

    def __init__(self, names=()):
        self.names = list(names)

    def list(self):
        return [{"id": name, "file": f"{name}.png", "hash": name,
                 "mime": "image/png", "w": 1080, "h": 1350, "exif": {},
                 "url": f"https://example.invalid/{name}",
                 "trashed": False, "size": 100}
                for name in self.names]

    def fetch(self, _file_id):
        return b"bytes", "image/png"


def a_working_model(item, image, mime):
    return {"caption": "ok", "tags": ["t"]}


class IndexRun(unittest.TestCase):
    """Drives the real CLI over an injected source. No credentials, no network,
    no money: the describer is a function and the source is a list."""

    def setUp(self):
        self.saved = {key: os.environ.pop(key, None) for key in KEYS}
        self.home = Path(tempfile.mkdtemp(prefix="lupa-nothing-found-"))
        self.collection = self.home / "photos"
        self.collection.mkdir()

        env_file = self.home / "lupa.env"
        env_file.write_text("GEMINI_API_KEY=abc\n", encoding="utf-8")
        os.environ["LUPA_ENV"] = str(env_file)
        os.environ["LUPA_CONFIG"] = str(self.home / "collections.json")
        os.environ["LUPA_INDEXES"] = str(self.home / "indexes")

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.home, ignore_errors=True)

    def run_index(self, source, *extra):
        """Returns (exit code, everything printed)."""
        original_source, original_describer = cli.build_source, cli.make_describer
        cli.build_source = lambda *a, **k: (source, None)
        cli.make_describer = lambda *a, **k: a_working_model

        printed, code = io.StringIO(), 0
        try:
            with contextlib.redirect_stdout(printed), \
                    contextlib.redirect_stderr(printed):
                try:
                    cli.main(["index", str(self.collection), "--yes", "--no-push",
                              "--no-batch", "--no-contact-sheets", *extra])
                except SystemExit as stop:
                    code = stop.code if isinstance(stop.code, int) else 1
        finally:
            cli.build_source, cli.make_describer = original_source, original_describer
        return code, printed.getvalue()

    @property
    def manifest(self):
        return Path(os.environ["LUPA_INDEXES"]) / "photos" / "MANIFEST.json"


class TestAFirstRunThatFindsNothing(IndexRun):
    """The empty folder, never indexed. This is the defect."""

    def test_it_does_not_exit_zero(self):
        code, printed = self.run_index(Source())
        self.assertNotEqual(0, code,
                            f"a first run that indexed nothing exited 0:\n{printed}")

    def test_it_does_not_invent_a_last_run(self):
        _, printed = self.run_index(Source())
        self.assertNotIn("since the last run", printed,
                         "there was no last run — the preflight just said so")

    def test_it_says_the_folder_has_no_images(self):
        _, printed = self.run_index(Source())
        lowered = printed.lower()
        self.assertIn("no image", lowered,
                      "the run must name what actually happened: no images")
        self.assertIn("not a success", lowered,
                      "it must refuse to be read as a success")

    def test_it_names_the_causes_the_owner_will_actually_hit(self):
        _, printed = self.run_index(Source())
        lowered = printed.lower()
        for clue in ("wrong folder", "subfolder", "permission", "supported"):
            self.assertIn(clue, lowered,
                          f'the likely cause "{clue}" is missing from the message')

    def test_nothing_was_indexed(self):
        self.run_index(Source())
        self.assertFalse(
            self.manifest.exists(),
            "an index was written for a collection with no images in it")


class TestAnExistingCollectionWithNothingToDo(IndexRun):
    """The incremental path. It worked, it is the point of the tool, and it must
    keep working exactly as it did — same sentence, same exit code."""

    def setUp(self):
        super().setUp()
        code, printed = self.run_index(Source(["a", "b"]))
        self.assertEqual(0, code, f"the seeding run failed:\n{printed}")
        self.assertTrue(self.manifest.exists(), f"no index was written:\n{printed}")

    def test_the_second_run_exits_zero(self):
        code, printed = self.run_index(Source(["a", "b"]))
        self.assertEqual(0, code, f"a legitimate no-op run failed:\n{printed}")

    def test_the_second_run_still_says_nothing_changed_since_the_last_run(self):
        _, printed = self.run_index(Source(["a", "b"]))
        self.assertIn("Nothing changed since the last run", printed)
        self.assertIn("nothing to pay", printed)

    def test_the_second_run_does_not_accuse_the_folder_of_being_empty(self):
        _, printed = self.run_index(Source(["a", "b"]))
        self.assertNotIn("not a success", printed.lower())


class TestDryRunAlwaysExitsZero(IndexRun):
    """--dry-run inspects and promises nothing, so it keeps its 0 in both cases.
    The MESSAGE still has to be true."""

    def test_dry_run_over_a_first_run_that_finds_nothing_exits_zero(self):
        code, printed = self.run_index(Source(), "--dry-run")
        self.assertEqual(0, code, f"--dry-run must not fail:\n{printed}")

    def test_dry_run_over_a_first_run_still_tells_the_truth(self):
        _, printed = self.run_index(Source(), "--dry-run")
        self.assertNotIn("since the last run", printed)
        self.assertIn("no image", printed.lower())

    def test_dry_run_over_an_existing_collection_exits_zero(self):
        seeded, printed = self.run_index(Source(["a", "b"]))
        self.assertEqual(0, seeded, f"the seeding run failed:\n{printed}")

        code, printed = self.run_index(Source(["a", "b"]), "--dry-run")
        self.assertEqual(0, code, f"--dry-run must not fail:\n{printed}")
        self.assertIn("Nothing changed since the last run", printed)


if __name__ == "__main__":
    unittest.main()
