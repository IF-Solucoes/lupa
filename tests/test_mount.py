"""Detecting a local folder that is actually a mounted Google Drive."""
import unittest
from lupa.mount import looks_like_mounted_drive


class TestDetection(unittest.TestCase):
    def test_windows_my_drive(self):
        self.assertTrue(looks_like_mounted_drive(r"G:\My Drive\Clients"))

    def test_windows_localized_my_drive(self):
        self.assertTrue(looks_like_mounted_drive(r"G:\Meu Drive\Clientes\IF"))

    def test_wsl_pointing_at_the_mounted_letter(self):
        self.assertTrue(looks_like_mounted_drive("/mnt/g/Meu Drive/Clientes/IF"))

    def test_macos_cloudstorage(self):
        self.assertTrue(looks_like_mounted_drive(
            "/Users/v/Library/CloudStorage/GoogleDrive-v@if.com/My Drive/Photos"))

    def test_google_drive_folder_in_home(self):
        self.assertTrue(looks_like_mounted_drive("/home/v/Google Drive/Photos"))

    def test_shared_drives(self):
        self.assertTrue(looks_like_mounted_drive("/mnt/g/Shared drives/Marketing"))

    def test_an_ordinary_folder_is_not_drive(self):
        self.assertFalse(looks_like_mounted_drive("/home/v/projects/photos"))

    def test_the_word_drive_mid_path_does_not_count(self):
        self.assertFalse(looks_like_mounted_drive("/home/v/hard-drive-backup/photos"))

    def test_dropbox_is_not_google_drive(self):
        self.assertFalse(looks_like_mounted_drive("/home/v/Dropbox/Photos"))


if __name__ == "__main__":
    unittest.main()
