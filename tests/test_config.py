"""Reading the env file and the collection registry."""
import tempfile
import unittest
from pathlib import Path

from lupa.config import (read_env, find_collection, register_collection,
                         target_from_registry, resolve_index_root)
from lupa.target import Target


class TestEnvFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False)
        self.tmp.write(
            "# a comment\n"
            "GEMINI_API_KEY=abc123\n"
            "\n"
            "LUPA_BATCH=1\n"
            'LUPA_MODEL="gemini-2.5-flash-lite"\n'
            "LUPA_STATE_DIR=~/.lupa/state\n"
            "EMPTY=\n"
        )
        self.tmp.close()

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_it_reads_a_simple_pair(self):
        self.assertEqual(read_env(self.tmp.name)["GEMINI_API_KEY"], "abc123")

    def test_it_skips_comments_and_blank_lines(self):
        env = read_env(self.tmp.name)
        self.assertNotIn("# a comment", env)
        self.assertEqual(len([k for k in env if k]), 5)

    def test_it_strips_quotes_from_values(self):
        self.assertEqual(read_env(self.tmp.name)["LUPA_MODEL"], "gemini-2.5-flash-lite")

    def test_it_expands_a_leading_tilde(self):
        self.assertNotIn("~", read_env(self.tmp.name)["LUPA_STATE_DIR"])

    def test_an_empty_value_becomes_an_empty_string(self):
        self.assertEqual(read_env(self.tmp.name)["EMPTY"], "")

    def test_a_missing_file_returns_nothing(self):
        self.assertEqual(read_env("/no/such/.env"), {})


class TestRegistry(unittest.TestCase):
    CONFIG = {"collections": [
        {"name": "if-editorial", "folder_id": "ABC"},
        {"name": "client-x", "folder_id": "DEF"},
    ]}

    def test_it_finds_a_collection_by_name(self):
        self.assertEqual(find_collection(self.CONFIG, "client-x")["folder_id"], "DEF")

    def test_an_unknown_name_returns_none(self):
        self.assertIsNone(find_collection(self.CONFIG, "nonexistent"))

    def test_a_config_without_collections_does_not_crash(self):
        self.assertIsNone(find_collection({}, "x"))

    def test_a_new_collection_is_registered(self):
        config = register_collection({"collections": []}, Target("drive", "if", folder_id="ABC"))
        self.assertEqual(config["collections"][0]["name"], "if")
        self.assertEqual(config["collections"][0]["folder_id"], "ABC")

    def test_a_local_collection_stores_its_path(self):
        config = register_collection({}, Target("local", "photos", path=Path("/tmp/photos")))
        self.assertEqual(config["collections"][0]["path"], "/tmp/photos")

    def test_registering_twice_does_not_duplicate(self):
        target = Target("drive", "if", folder_id="ABC")
        config = register_collection(register_collection({}, target), target)
        self.assertEqual(len(config["collections"]), 1)

    def test_the_same_name_with_a_new_target_updates_the_entry(self):
        config = register_collection({}, Target("drive", "if", folder_id="ABC"))
        config = register_collection(config, Target("drive", "if", folder_id="NEW"))
        self.assertEqual(len(config["collections"]), 1)
        self.assertEqual(config["collections"][0]["folder_id"], "NEW")

    def test_a_registry_entry_becomes_a_drive_target(self):
        target = target_from_registry({"name": "if", "folder_id": "ABC"})
        self.assertEqual(target.kind, "drive")
        self.assertEqual(target.folder_id, "ABC")

    def test_a_registry_entry_becomes_a_local_target(self):
        self.assertEqual(target_from_registry({"name": "photos", "path": "/tmp/photos"}).kind,
                         "local")


class TestIndexRoot(unittest.TestCase):
    def test_an_explicit_variable_wins(self):
        self.assertEqual(str(resolve_index_root({"LUPA_INDEXES": "/tmp/x"}, {})), "/tmp/x")

    def test_the_state_dir_gets_an_indexes_subfolder(self):
        root = resolve_index_root({}, {"LUPA_STATE_DIR": "/home/u/.lupa/state"})
        self.assertEqual(str(root), "/home/u/.lupa/state/indexes")

    def test_with_nothing_set_it_falls_back_to_a_portable_default(self):
        self.assertTrue(str(resolve_index_root({}, {})).endswith(".lupa/indexes"))


if __name__ == "__main__":
    unittest.main()


class TestPathRedirection(unittest.TestCase):
    """The env file must be able to point the registry elsewhere, not only the process env."""

    def test_the_env_file_can_redirect_the_registry(self):
        from lupa.config import config_path
        path = config_path({"LUPA_CONFIG": "/somewhere/collections.json"})
        self.assertEqual(str(path), "/somewhere/collections.json")

    def test_the_process_env_still_wins_over_the_file(self):
        import os
        from lupa.config import config_path
        os.environ["LUPA_CONFIG"] = "/from/process.json"
        try:
            path = config_path({"LUPA_CONFIG": "/from/file.json"})
            self.assertEqual(str(path), "/from/process.json")
        finally:
            del os.environ["LUPA_CONFIG"]

    def test_without_either_it_uses_the_portable_default(self):
        from lupa.config import config_path
        self.assertTrue(str(config_path({})).endswith(".lupa/collections.json"))


class TestPathConsistency(unittest.TestCase):
    """Every caller must land on the same file, with or without an explicit env."""

    def test_config_path_is_the_same_with_and_without_an_explicit_env(self):
        from lupa.config import config_path, read_env
        self.assertEqual(config_path(), config_path(read_env()))

    def test_a_caller_that_passes_nothing_still_honors_the_env_file(self):
        import os
        import tempfile
        from lupa.config import config_path

        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as handle:
            handle.write("LUPA_CONFIG=/from/the/file.json\n")
            env_file = handle.name
        os.environ["LUPA_ENV"] = env_file
        try:
            self.assertEqual(str(config_path()), "/from/the/file.json")
        finally:
            del os.environ["LUPA_ENV"]
            Path(env_file).unlink(missing_ok=True)


class TestEnvSearchChain(unittest.TestCase):
    """The settings file is looked up in order, so one shared .env can serve
    several tools without every tool hardcoding a path."""

    def setUp(self):
        import os
        self.saved = os.environ.pop("LUPA_ENV", None)

    def tearDown(self):
        import os
        if self.saved is not None:
            os.environ["LUPA_ENV"] = self.saved
        else:
            os.environ.pop("LUPA_ENV", None)

    def test_the_chain_has_the_shared_env_before_the_tool_specific_one(self):
        from lupa.config import ENV_SEARCH_CHAIN
        paths = [str(p) for p in ENV_SEARCH_CHAIN]
        self.assertTrue(any(p.endswith(".francis/.env") for p in paths))
        shared = next(i for i, p in enumerate(paths) if p.endswith(".francis/.env"))
        own = next(i for i, p in enumerate(paths) if p.endswith(".lupa/lupa.env"))
        self.assertLess(shared, own)

    def test_an_explicit_variable_still_wins_over_the_chain(self):
        import os
        import tempfile
        from lupa.config import env_path

        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as handle:
            handle.write("GEMINI_API_KEY=explicit\n")
            chosen = handle.name
        os.environ["LUPA_ENV"] = chosen
        try:
            self.assertEqual(str(env_path()), chosen)
        finally:
            Path(chosen).unlink(missing_ok=True)

    def test_it_returns_the_first_file_that_exists(self):
        import tempfile
        from lupa.config import first_existing

        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "nope.env"
            present = Path(folder) / "yes.env"
            present.write_text("X=1\n")
            self.assertEqual(first_existing([missing, present]), present)

    def test_with_nothing_on_disk_it_falls_back_to_the_last_candidate(self):
        from lupa.config import first_existing

        candidates = [Path("/no/such/a.env"), Path("/no/such/b.env")]
        self.assertEqual(first_existing(candidates), candidates[-1])

    def test_an_empty_chain_is_not_a_crash(self):
        from lupa.config import first_existing
        self.assertIsNone(first_existing([]))
