"""Detecção de pasta local que é, na verdade, um Google Drive montado."""
import unittest
from lupa.montagem import parece_drive_montado


class TestDetecta(unittest.TestCase):
    def test_windows_meu_drive(self):
        self.assertTrue(parece_drive_montado(r"G:\Meu Drive\Clientes\IF"))

    def test_windows_my_drive_em_ingles(self):
        self.assertTrue(parece_drive_montado(r"G:\My Drive\Clients"))

    def test_wsl_apontando_para_a_unidade_montada(self):
        self.assertTrue(parece_drive_montado("/mnt/g/Meu Drive/Clientes/IF"))

    def test_macos_cloudstorage(self):
        self.assertTrue(parece_drive_montado(
            "/Users/v/Library/CloudStorage/GoogleDrive-v@if.com/My Drive/Fotos"))

    def test_pasta_google_drive_no_home(self):
        self.assertTrue(parece_drive_montado("/home/v/Google Drive/Fotos"))

    def test_drives_compartilhados(self):
        self.assertTrue(parece_drive_montado("/mnt/g/Drives compartilhados/Marketing"))

    def test_pasta_comum_nao_e_drive(self):
        self.assertFalse(parece_drive_montado("/home/v/projetos/fotos"))

    def test_pasta_com_a_palavra_drive_no_meio_nao_conta(self):
        self.assertFalse(parece_drive_montado("/home/v/hard-drive-backup/fotos"))

    def test_dropbox_nao_e_google_drive(self):
        self.assertFalse(parece_drive_montado("/home/v/Dropbox/Fotos"))


if __name__ == "__main__":
    unittest.main()
