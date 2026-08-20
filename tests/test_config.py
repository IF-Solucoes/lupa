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
