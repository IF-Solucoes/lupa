"""Preflight: diagnose the environment and teach the way before spending."""
import tempfile
import unittest
from pathlib import Path

from lupa.target import Target
from lupa.preflight import diagnose, BLOCKER, WARNING, OK, has_blocker


def drive_target():
    return Target("drive", "if-editorial", folder_id="ABC123")


def local_target(path):
    return Target("local", "photos", path=Path(path))


FULL_ENV = {"GEMINI_API_KEY": "abc", "LUPA_OAUTH_CLIENT": "/existe/oauth.json",
                "LUPA_OAUTH_TOKEN": "/existe/token.json"}


class TestKey(unittest.TestCase):
    def test_a_missing_gemini_key_blocks(self):
        c = diagnose(drive_target(), env={}, existing_files=set())
        key_check = [x for x in c if x.name == "Gemini key"][0]
        self.assertEqual(key_check.status, BLOCKER)

    def test_the_message_says_where_to_get_the_key(self):
        c = diagnose(drive_target(), env={}, existing_files=set())
        key_check = [x for x in c if x.name == "Gemini key"][0]
        self.assertIn("aistudio.google.com", key_check.how_to_fix)
        self.assertIn("lupa.env", key_check.how_to_fix)

    def test_with_a_key_it_passes(self):
        c = diagnose(drive_target(), env=FULL_ENV,
                         existing_files={"/existe/oauth.json", "/existe/token.json"})
        key_check = [x for x in c if x.name == "Gemini key"][0]
        self.assertEqual(key_check.status, OK)


class TestDriveCredentials(unittest.TestCase):
    def test_a_missing_oauth_client_blocks_a_drive_target(self):
        c = diagnose(drive_target(), env={"GEMINI_API_KEY": "x"}, existing_files=set())
        oauth = [x for x in c if x.name == "Google Drive access"][0]
        self.assertEqual(oauth.status, BLOCKER)
        self.assertIn("console.cloud.google.com", oauth.how_to_fix)

    def test_a_missing_token_only_warns_about_sign_in(self):
        c = diagnose(drive_target(), env=FULL_ENV,
                         existing_files={"/existe/oauth.json"})
        signin = [x for x in c if x.name == "Google sign-in"][0]
        self.assertEqual(signin.status, WARNING)

    def test_a_local_target_needs_no_drive_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            c = diagnose(local_target(d), env={"GEMINI_API_KEY": "x"},
                             existing_files=set())
            self.assertFalse(any(x.name == "Google Drive access" for x in c))
            self.assertFalse(has_blocker(c))


class TestMountedDrive(unittest.TestCase):
    def test_a_mounted_drive_folder_raises_an_explanatory_warning(self):
        c = diagnose(local_target("/mnt/g/My Drive/Clients"), env={"GEMINI_API_KEY": "x"},
                         existing_files=set())
        warning = [x for x in c if x.name == "collection source"][0]
        self.assertEqual(warning.status, WARNING)
        self.assertIn("OCR", warning.how_to_fix)

    def test_the_warning_does_not_block_the_run(self):
        c = diagnose(local_target("/mnt/g/My Drive/Clients"), env={"GEMINI_API_KEY": "x"},
                         existing_files=set())
        self.assertFalse(has_blocker(c))

    def test_an_ordinary_folder_raises_no_such_warning(self):
        with tempfile.TemporaryDirectory() as d:
            c = diagnose(local_target(d), env={"GEMINI_API_KEY": "x"}, existing_files=set())
            source = [x for x in c if x.name == "collection source"][0]
            self.assertEqual(source.status, OK)


class TestExistingIndex(unittest.TestCase):
    def test_it_says_this_will_be_an_update(self):
        c = diagnose(drive_target(), env=FULL_ENV, existing_files=set(),
                         index_exists=True)
        state = [x for x in c if x.name == "index state"][0]
        self.assertIn("update", state.message.lower())

    def test_an_untouched_collection_says_first_run(self):
        c = diagnose(drive_target(), env=FULL_ENV, existing_files=set(),
                         index_exists=False)
        state = [x for x in c if x.name == "index state"][0]
        self.assertIn("first run", state.message.lower())


class TestSummary(unittest.TestCase):
    def test_has_blocker_detects_any_impediment(self):
        self.assertTrue(has_blocker(diagnose(drive_target(), env={}, existing_files=set())))

    def test_ambiente_completo_nao_has_blocker(self):
        c = diagnose(drive_target(), env=FULL_ENV,
                         existing_files={"/existe/oauth.json", "/existe/token.json"})
        self.assertFalse(has_blocker(c))


if __name__ == "__main__":
    unittest.main()
