"""Preflight: diagnose the environment and teach the way before spending."""
import tempfile
import unittest
from pathlib import Path

from lupa.target import Target
from lupa.preflight import (diagnose, format_report, BLOCKER, WARNING, OK,
                            has_blocker)
from lupa.gemini import DEFAULT_MODEL


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
        self.assertIn("GEMINI_API_KEY", key_check.how_to_fix)

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


class TestNothingPromisesOcrThatDriveNeverGave(unittest.TestCase):
    """The preflight is the last screen before money is spent. It cannot lie there.

    It told everyone that a Drive collection arrives "with OCR", and advised moving a
    local folder to Drive to get it. Drive returns no OCR — the field it was supposed
    to come from is not in the API — so the advice bought nothing and the promise was
    the defect repeated at the checkout.
    """

    def _every_sentence(self, checks):
        return " ".join(f"{c.name} {c.message or ''} {c.how_to_fix or ''}"
                        for c in checks).lower()

    def test_a_drive_collection_is_not_advertised_as_carrying_ocr(self):
        c = diagnose(drive_target(), env={"GEMINI_API_KEY": "x"}, existing_files={"a"})
        self.assertNotIn("ocr", self._every_sentence(c))

    def test_a_local_folder_is_not_told_it_is_missing_ocr(self):
        with tempfile.TemporaryDirectory() as d:
            c = diagnose(local_target(d), env={"GEMINI_API_KEY": "x"}, existing_files=set())
        self.assertNotIn("ocr", self._every_sentence(c))

    def test_the_mounted_drive_advice_no_longer_sells_ocr(self):
        c = diagnose(local_target("/mnt/g/My Drive/Clients"), env={"GEMINI_API_KEY": "x"},
                     existing_files=set())
        self.assertNotIn("ocr", self._every_sentence(c))

    def test_but_the_reasons_that_are_real_survive(self):
        c = diagnose(local_target("/mnt/g/My Drive/Clients"), env={"GEMINI_API_KEY": "x"},
                     existing_files=set())
        advice = [x for x in c if x.name == "collection source"][0].how_to_fix
        self.assertIn("link", advice.lower())
        self.assertIn("id", advice.lower())


class TestMountedDrive(unittest.TestCase):
    def test_a_mounted_drive_folder_raises_an_explanatory_warning(self):
        c = diagnose(local_target("/mnt/g/My Drive/Clients"), env={"GEMINI_API_KEY": "x"},
                         existing_files=set())
        warning = [x for x in c if x.name == "collection source"][0]
        self.assertEqual(warning.status, WARNING)
        self.assertIn("shareable", warning.how_to_fix)

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


class TestItNamesTheActualFile(unittest.TestCase):
    """A fix instruction that names no path makes the reader hunt for the file."""

    def test_the_key_blocker_names_the_settings_file_in_use(self):
        checks = diagnose(drive_target(), env={}, existing_files=set(),
                          env_file="/home/someone/.francis/.env")
        key = [c for c in checks if c.name == "Gemini key"][0]
        self.assertIn("/home/someone/.francis/.env", key.how_to_fix)

    def test_without_a_known_path_it_still_explains_the_fix(self):
        checks = diagnose(drive_target(), env={}, existing_files=set())
        key = [c for c in checks if c.name == "Gemini key"][0]
        self.assertIn("aistudio.google.com", key.how_to_fix)


class TestCostHonesty(unittest.TestCase):
    """An estimate with no stated basis is the defect itself, wearing a number.

    Whatever appears on screen has to name the model it was computed for and say
    where the price came from — or admit it cannot price this run at all.
    """

    def check(self, env=None, **kw):
        merged = dict(FULL_ENV)
        merged.update(env or {})
        checks = diagnose(drive_target(), env=merged,
                          existing_files={"/existe/oauth.json", "/existe/token.json"}, **kw)
        return [c for c in checks if c.name == "cost estimate"][0]

    def test_the_default_model_is_priced_from_the_table(self):
        check = self.check()
        self.assertEqual(check.status, OK)
        self.assertIn(DEFAULT_MODEL, check.message)

    def test_the_number_never_appears_without_the_model_beside_it(self):
        check = self.check({"LUPA_MODEL": "gemini-2.5-flash-lite"})
        self.assertIn("gemini-2.5-flash-lite", check.message)
        self.assertIn("0.10", check.message)
        self.assertIn("0.40", check.message)

    def test_a_model_outside_the_table_warns_instead_of_quoting(self):
        check = self.check({"LUPA_MODEL": "gemini-9-imagined"})
        self.assertEqual(check.status, WARNING)
        self.assertIn("gemini-9-imagined", check.message)
        self.assertIn("not reliable", check.message.lower())

    def test_an_unpriceable_model_still_does_not_block_the_run(self):
        checks = diagnose(drive_target(), env={**FULL_ENV, "LUPA_MODEL": "gemini-9-imagined"},
                          existing_files={"/existe/oauth.json", "/existe/token.json"})
        self.assertFalse(has_blocker(checks))

    def test_the_unpriced_warning_teaches_the_two_ways_out(self):
        check = self.check({"LUPA_MODEL": "gemini-9-imagined"})
        self.assertIn("LUPA_INPUT_PRICE", check.how_to_fix)
        self.assertIn("LUPA_MODEL", check.how_to_fix)

    def test_a_price_from_the_env_declares_that_it_came_from_the_env(self):
        check = self.check({"LUPA_INPUT_PRICE": "0.99", "LUPA_OUTPUT_PRICE": "1.99"})
        self.assertIn("LUPA_INPUT_PRICE", check.message)
        self.assertIn("0.99", check.message)

    def test_a_junk_price_in_the_env_is_reported_not_swallowed(self):
        check = self.check({"LUPA_INPUT_PRICE": "barato"})
        self.assertEqual(check.status, WARNING)
        self.assertIn("LUPA_INPUT_PRICE", check.message)

    def test_a_junk_price_does_not_block_the_run_either(self):
        checks = diagnose(drive_target(), env={**FULL_ENV, "LUPA_INPUT_PRICE": "barato"},
                          existing_files={"/existe/oauth.json", "/existe/token.json"})
        self.assertFalse(has_blocker(checks))

    def test_batch_being_half_price_is_still_stated(self):
        self.assertIn("batch", self.check().message.lower())

    def test_the_check_survives_the_report_formatter(self):
        checks = diagnose(drive_target(), env={**FULL_ENV, "LUPA_MODEL": "gemini-9-imagined"},
                          existing_files=set())
        self.assertIn("gemini-9-imagined", format_report(checks, drive_target()))
