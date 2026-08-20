"""The user says it any way they like; lupa figures it out."""
import os
import tempfile
import unittest
from pathlib import Path
from lupa.target import resolve_target, InvalidTarget


class TestDriveUrl(unittest.TestCase):
    def test_folder_url(self):
        t = resolve_target("https://drive.google.com/drive/folders/15fvulCdmeBAG7T2Tm")
        self.assertEqual(t.kind, "drive")
        self.assertEqual(t.folder_id, "15fvulCdmeBAG7T2Tm")

    def test_url_with_query_string(self):
        t = resolve_target("https://drive.google.com/drive/folders/ABC123?usp=sharing")
        self.assertEqual(t.folder_id, "ABC123")

    def test_shared_url_with_account_segment(self):
        t = resolve_target("https://drive.google.com/drive/u/0/folders/XYZ789")
        self.assertEqual(t.folder_id, "XYZ789")

    def test_bare_id_is_treated_as_a_drive_folder(self):
        t = resolve_target("15fvulCdmeBAG7T2Tmwuz5KcDD4XF3eah")
        self.assertEqual(t.kind, "drive")
        self.assertEqual(t.folder_id, "15fvulCdmeBAG7T2Tmwuz5KcDD4XF3eah")

    def test_name_falls_back_to_the_id(self):
        self.assertTrue(resolve_target("https://drive.google.com/drive/folders/ABC123").name)

    def test_explicit_name_wins(self):
        t = resolve_target("https://drive.google.com/drive/folders/ABC123", name="if-editorial")
        self.assertEqual(t.name, "if-editorial")


class TestLocalFolder(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "Client Photos"
        self.folder.mkdir()

    def tearDown(self):
        try:
            os.chdir(self.cwd)
        except OSError:
            os.chdir(tempfile.gettempdir())
        self.tmp.cleanup()

    def test_existing_path_becomes_a_local_target(self):
        t = resolve_target(str(self.folder))
        self.assertEqual(t.kind, "local")
        self.assertEqual(t.path, self.folder)

    def test_collection_name_comes_from_the_folder_name(self):
        self.assertEqual(resolve_target(str(self.folder)).name, "client-photos")

    def test_tilde_is_expanded(self):
        self.assertEqual(resolve_target("~").kind, "local")

    def test_relative_path_works(self):
        os.chdir(self.folder.parent)
        self.assertEqual(resolve_target("Client Photos").kind, "local")

    def test_a_single_file_is_not_a_collection(self):
        single = self.folder / "photo.png"
        single.write_bytes(b"x")
        with self.assertRaises(InvalidTarget):
            resolve_target(str(single))


class TestBadInput(unittest.TestCase):
    def test_empty_input_is_rejected(self):
        with self.assertRaises(InvalidTarget):
            resolve_target("")

    def test_non_folder_url_is_rejected_with_a_hint(self):
        with self.assertRaises(InvalidTarget) as ctx:
            resolve_target("https://drive.google.com/file/d/ABC/view")
        self.assertIn("folder", str(ctx.exception).lower())

    def test_missing_path_is_rejected(self):
        with self.assertRaises(InvalidTarget):
            resolve_target("/path/that/really/does/not/exist")


if __name__ == "__main__":
    unittest.main()
