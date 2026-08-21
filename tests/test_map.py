"""`lupa map` — step 0: the shape of a collection, before a cent is spent.

Why this file exists at all: `lupa index` lists **only images in a supported
format**. Video, PSD, PDF and Google Docs are not listed, not counted and not
mentioned — they disappear in silence. In a client folder literally named
"4 - Fotos & Vídeos" that silence is the whole problem: the run reports 489
images and says nothing about the 298 mp4 files nobody is ever going to index.

So the map counts **what is ignored** as loudly as what is indexable, and it does
it from names and mime types alone: no download, no model call, no API key.

Nothing here reaches the network. The Drive walk is a double — a generator of
`(prefix, files)` exactly like the real one — and the local walk runs against a
temporary folder.
"""
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from lupa import mapping


# --- the double ---------------------------------------------------------
#
# Shaped after `lupa.drive.walk_entries`: breadth-first, parents before
# children, one tuple per folder INCLUDING the folders that hold no files.
# An empty folder that never showed up would be indistinguishable from one
# full of video, which is the exact confusion this command exists to end.

def drive_walk(tree):
    """tree: {prefix: [(name, mime), ...]} in breadth-first order."""
    def walk(on_folder=None):
        for prefix, files in tree.items():
            entries = [{"name": name, "mime": mime, "size": 0}
                       for name, mime in files]
            if on_folder:
                on_folder(prefix, len(entries))
            yield prefix, entries
    return walk


CLIENT = {
    "": [],
    "4 - Fotos & Vídeos/": [],
    "4 - Fotos & Vídeos/Tratamento de Fotos/": [
        (f"trat-{n}.jpg", "image/jpeg") for n in range(485)],
    "4 - Fotos & Vídeos/Brutas/": (
        [(f"bruta-{n}.JPG", "image/jpeg") for n in range(4)]
        + [(f"clip-{n}.mp4", "video/mp4") for n in range(298)]
        + [(f"clip-{n}.mov", "video/quicktime") for n in range(14)]),
    "2 - Kit Marca/": [
        ("logo.psd", "image/vnd.adobe.photoshop"),
        ("manual.pdf", "application/pdf"),
        ("briefing", "application/vnd.google-apps.document"),
        ("capa.png", "image/png"),
    ],
    "3 - Vazia/": [],
}


class TestClassification(unittest.TestCase):
    """Indexable means: what `lupa index` would actually pick up. Everything
    else is ignored, and the map says so by extension."""

    def test_a_jpeg_on_drive_is_indexable(self):
        self.assertTrue(mapping.is_indexable({"name": "a.jpg", "mime": "image/jpeg"},
                                             kind="drive"))

    def test_an_mp4_is_not(self):
        self.assertFalse(mapping.is_indexable({"name": "a.mp4", "mime": "video/mp4"},
                                              kind="drive"))

    def test_a_google_doc_is_not(self):
        self.assertFalse(mapping.is_indexable(
            {"name": "briefing", "mime": "application/vnd.google-apps.document"},
            kind="drive"))

    def test_a_file_with_no_extension_is_still_grouped(self):
        self.assertEqual(mapping.extension_of("briefing"), "(no ext)")

    def test_the_extension_is_lowercased_so_JPG_and_jpg_are_one_group(self):
        self.assertEqual(mapping.extension_of("BRUTA-1.JPG"), "jpg")


class TestTheTreeCounts(unittest.TestCase):
    def setUp(self):
        self.tree = mapping.build_tree(drive_walk(CLIENT), kind="drive")

    def test_the_totals_split_indexable_from_ignored(self):
        # 485 + 4 jpg, 1 png and — see below — 1 psd Drive calls an image.
        self.assertEqual(mapping.totals(self.tree), (491, 314))

    def test_the_ignored_are_grouped_by_extension(self):
        _, ignored = mapping.extensions(self.tree)
        self.assertEqual(sorted(ignored.items(), key=lambda kv: (-kv[1], kv[0])),
                         [("mp4", 298), ("mov", 14), ("(no ext)", 1), ("pdf", 1)])

    def test_a_folder_carries_the_counts_of_everything_below_it(self):
        fotos = mapping.find(self.tree, "4 - Fotos & Vídeos/")
        self.assertEqual(mapping.totals(fotos), (489, 312))

    def test_an_empty_folder_exists_in_the_tree_and_counts_zero(self):
        vazia = mapping.find(self.tree, "3 - Vazia/")
        self.assertIsNotNone(vazia, "an empty folder that vanishes from the map "
                                    "is indistinguishable from one full of video")
        self.assertEqual(mapping.totals(vazia), (0, 0))

    def test_a_psd_drive_reports_as_an_image_is_counted_where_lupa_would_bill_it(self):
        """Drive answers `image/vnd.adobe.photoshop` for a PSD, so
        `mimeType contains 'image/'` matches it and lupa lists it. The map must
        say what lupa DOES, not what would be sensible."""
        kit = mapping.find(self.tree, "2 - Kit Marca/")
        indexable, _ = mapping.extensions(kit)
        self.assertEqual(indexable["psd"], 1)


class TestRendering(unittest.TestCase):
    def setUp(self):
        self.tree = mapping.build_tree(drive_walk(CLIENT), kind="drive")

    def test_the_first_line_names_the_collection_and_says_it_is_free(self):
        text = mapping.render(self.tree, title="1K6qh1s", depth=2)
        self.assertIn("1K6qh1s", text.splitlines()[0])
        self.assertIn("no model call", text)

    def test_depth_one_folds_the_subfolders_into_their_parent(self):
        text = mapping.render(self.tree, title="x", depth=1)
        self.assertIn("4 - Fotos & Vídeos/", text)
        self.assertNotIn("Tratamento de Fotos/", text)

    def test_depth_two_opens_them(self):
        text = mapping.render(self.tree, title="x", depth=2)
        self.assertIn("Tratamento de Fotos/", text)

    def test_a_folded_level_is_announced_rather_than_dropped_in_silence(self):
        text = mapping.render(self.tree, title="x", depth=1)
        self.assertIn("--depth", text)

    def test_a_display_leaf_shows_what_the_file_types_are(self):
        text = mapping.render(self.tree, title="x", depth=2)
        line = next(l for l in text.splitlines() if "Brutas/" in l)
        self.assertIn("298 mp4", line)
        self.assertIn("14 mov", line)

    def test_the_last_line_totals_the_collection_and_names_the_ignored_types(self):
        text = mapping.render(self.tree, title="x", depth=2)
        self.assertRegex(text, r"total: 491 indexable · 314 ignored")
        self.assertIn("mp4 298", text)

    def test_the_same_extension_on_both_sides_is_not_printed_twice_unlabelled(self):
        """Found on the first real collection: a folder of files with no
        extension at all, most of which Drive calls images and one of which it
        does not. The row read `92 (no ext) · … · 1 (no ext)` — two identical
        labels, one costing money and one invisible."""
        both = mapping.build_tree(drive_walk({
            "": [],
            "Trifold/": [("a", "image/png"), ("b", "application/octet-stream")],
        }), kind="drive")
        line = next(l for l in mapping.render(both, title="x").splitlines()
                    if "Trifold/" in l)
        self.assertIn("ignored:", line)
        self.assertEqual(line.count("(no ext)"), 2)   # once per side, and labelled
        self.assertLess(line.index("(no ext)"), line.index("ignored:"))

    def test_a_folder_lupa_would_index_nothing_of_says_only_ignored(self):
        videos = mapping.build_tree(drive_walk({
            "": [], "Vídeos/": [("a.mp4", "video/mp4")]}), kind="drive")
        line = next(l for l in mapping.render(videos, title="x").splitlines()
                    if "Vídeos/" in l)
        self.assertIn("ignored: 1 mp4", line)

    def test_an_empty_folder_says_so(self):
        text = mapping.render(self.tree, title="x", depth=2)
        line = next(l for l in text.splitlines() if "3 - Vazia/" in l)
        self.assertIn("empty", line)


class TestTheLocalCase(unittest.TestCase):
    """The same command over a folder on disk. No credentials, no network."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "Brutas").mkdir()
        (self.root / "Vazia").mkdir()
        (self.root / "_lupa").mkdir()
        for name in ("a.jpg", "b.PNG"):
            (self.root / name).write_bytes(b"\x00")
        for name in ("c.jpg", "filme.mp4", "arte.psd"):
            (self.root / "Brutas" / name).write_bytes(b"\x00")
        (self.root / "_lupa" / "INDEX.md").write_text("x", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_counts_a_folder_on_disk(self):
        tree = mapping.build_tree(mapping.local_walk(self.root), kind="local")
        self.assertEqual(mapping.totals(tree), (3, 2))

    def test_it_never_walks_into_the_index_folder(self):
        tree = mapping.build_tree(mapping.local_walk(self.root), kind="local")
        self.assertIsNone(mapping.find(tree, "_lupa/"))

    def test_an_empty_folder_on_disk_is_listed_too(self):
        tree = mapping.build_tree(mapping.local_walk(self.root), kind="local")
        self.assertIsNotNone(mapping.find(tree, "Vazia/"))


class TestTheMarkdownArtifact(unittest.TestCase):
    def test_it_writes_utf8_and_keeps_the_accents(self):
        tree = mapping.build_tree(drive_walk(CLIENT), kind="drive")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "MAP.md"
            mapping.write_map(path, tree, title="1K6qh1s", depth=2)
            raw = path.read_bytes()
        self.assertIn("4 - Fotos & Vídeos".encode("utf-8"), raw)
        self.assertIn("MAP", raw.decode("utf-8"))


class TestTheCommand(unittest.TestCase):
    """`map` is its own subcommand: it inherits no indexing flag, it needs no
    GEMINI_API_KEY, and it never opens the index the way `index` does."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.collection = self.root / "Fotos"
        (self.collection / "Brutas").mkdir(parents=True)
        (self.collection / "a.jpg").write_bytes(b"\x00")
        (self.collection / "Brutas" / "filme.mp4").write_bytes(b"\x00")

        self.env_file = self.root / "empty.env"
        self.env_file.write_text("", encoding="utf-8")
        self.saved = {key: os.environ.get(key)
                      for key in ("LUPA_ENV", "LUPA_INDEXES", "GEMINI_API_KEY")}
        os.environ["LUPA_ENV"] = str(self.env_file)
        os.environ["LUPA_INDEXES"] = str(self.root / "indexes")
        os.environ.pop("GEMINI_API_KEY", None)

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def run_map(self, *argv):
        from lupa import cli
        out = StringIO()
        with redirect_stdout(out):
            cli.main(["map", str(self.collection), *argv])
        return out.getvalue()

    def test_it_runs_with_no_gemini_key_at_all(self):
        text = self.run_map()
        self.assertIn("1 indexable", text)
        self.assertIn("mp4", text)

    def test_it_says_out_loud_that_it_costs_nothing(self):
        self.assertIn("no model call", self.run_map())

    def test_it_writes_the_map_next_to_where_the_index_will_live(self):
        self.run_map()
        written = self.root / "indexes" / "fotos" / "MAP.md"
        self.assertTrue(written.exists(), f"no MAP.md at {written}")
        self.assertIn("mp4", written.read_text(encoding="utf-8"))

    def test_it_does_not_make_the_next_index_run_think_an_index_exists(self):
        """MAP.md is a sibling of INDEX.md, but it is not an index. Writing it
        must not trip the guard that refuses to reindex."""
        self.run_map()
        self.assertFalse((self.root / "indexes" / "fotos" / "MANIFEST.json").exists())

    def test_out_puts_the_file_wherever_it_is_told(self):
        elsewhere = self.root / "somewhere" / "MAP.md"
        self.run_map("--out", str(elsewhere))
        self.assertTrue(elsewhere.exists())

    def test_it_refuses_the_indexing_flags_instead_of_pretending_to_honour_them(self):
        with self.assertRaises(SystemExit):
            self.run_map("--rebuild")


class _Captured(Exception):
    def __init__(self, parser):
        super().__init__("captured")
        self.parser = parser


def map_subparser():
    """The `map` subparser argparse really built — asked, not reimplemented.

    Same trick as tests/test_docs_match_the_cli.py, inlined rather than imported:
    `tests/` is not a package, and a cross-import between two test files would
    work under pytest and die under `python -m unittest`.
    """
    import argparse

    from lupa import cli

    original_parse = argparse.ArgumentParser.parse_args
    original_streams = cli.prepare_output_streams
    argparse.ArgumentParser.parse_args = lambda self, *a, **k: (_ for _ in ()).throw(
        _Captured(self))
    cli.prepare_output_streams = lambda: None
    try:
        cli.main([])
    except _Captured as captured:
        parser = captured.parser
    finally:
        argparse.ArgumentParser.parse_args = original_parse
        cli.prepare_output_streams = original_streams

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            if "map" in action.choices:
                return action.choices["map"]
    return None


class TestTheParserKnowsTheCommand(unittest.TestCase):
    def test_map_is_a_subcommand(self):
        self.assertIsNotNone(map_subparser(), "lupa.cli has no `map` subcommand")

    def test_it_carries_no_indexing_flag(self):
        flags = {option
                 for action in map_subparser()._actions
                 for option in action.option_strings if option.startswith("--")}
        self.assertEqual(flags & {"--rebuild", "--no-batch", "--yes", "--workers"},
                         set())


if __name__ == "__main__":
    unittest.main()
