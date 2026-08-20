"""Leitura do Drive: parsing dos metadados que a API devolve."""
import unittest
from lupa.drive import separar_ocr_e_labels, normalizar_arquivo, query_da_pasta

SNIPPET_REAL = (
    "MIGRAÇÃO\n\nAdiar a modernização\n\npor medo de parar também é decisão de risco.\n"
    "\n  \n  \nImage labels: \\[Bridge; Cable-stayed bridge; Technology; Diagram\\]"
)


class TestSnippet(unittest.TestCase):
    def test_extrai_o_texto_ocr_sem_os_labels(self):
        ocr, _ = separar_ocr_e_labels(SNIPPET_REAL)
        self.assertIn("MIGRAÇÃO", ocr)
        self.assertNotIn("Image labels", ocr)
        self.assertNotIn("Bridge", ocr)

    def test_extrai_a_lista_de_labels(self):
        _, labels = separar_ocr_e_labels(SNIPPET_REAL)
        self.assertEqual(labels, ["Bridge", "Cable-stayed bridge", "Technology", "Diagram"])

    def test_snippet_sem_labels_devolve_lista_vazia(self):
        ocr, labels = separar_ocr_e_labels("só texto aqui")
        self.assertEqual(ocr, "só texto aqui")
        self.assertEqual(labels, [])

    def test_snippet_vazio_nao_quebra(self):
        self.assertEqual(separar_ocr_e_labels(""), ("", []))

    def test_snippet_ausente_nao_quebra(self):
        self.assertEqual(separar_ocr_e_labels(None), ("", []))

    def test_labels_sem_escape_tambem_funcionam(self):
        _, labels = separar_ocr_e_labels("txt\nImage labels: [Food; Table]")
        self.assertEqual(labels, ["Food", "Table"])


class TestNormalizacao(unittest.TestCase):
    def test_mapeia_os_campos_da_api(self):
        bruto = {
            "id": "1a2B", "name": "post-24.png", "mimeType": "image/png",
            "md5Checksum": "abc123", "size": "4321764",
            "imageMediaMetadata": {"width": 1080, "height": 1350},
            "webViewLink": "https://drive.google.com/file/d/1a2B/view",
        }
        f = normalizar_arquivo(bruto)
        self.assertEqual(f["id"], "1a2B")
        self.assertEqual(f["file"], "post-24.png")
        self.assertEqual(f["hash"], "abc123")
        self.assertEqual((f["w"], f["h"]), (1080, 1350))
        self.assertEqual(f["url"], "https://drive.google.com/file/d/1a2B/view")

    def test_sem_md5_usa_tamanho_e_data_como_hash(self):
        # Google Docs e alguns formatos não têm md5Checksum
        f = normalizar_arquivo({"id": "x", "name": "a.png", "size": "100",
                                "modifiedTime": "2026-08-20T10:00:00Z"})
        self.assertTrue(f["hash"])
        self.assertNotEqual(f["hash"], "")

    def test_extrai_exif_da_camera(self):
        bruto = {"id": "x", "name": "f.jpg", "imageMediaMetadata": {
            "width": 4032, "height": 3024, "cameraMake": "Apple", "cameraModel": "iPhone 15"}}
        f = normalizar_arquivo(bruto)
        self.assertEqual(f["exif"]["Make"], "Apple")

    def test_sem_dimensoes_usa_zero(self):
        f = normalizar_arquivo({"id": "x", "name": "a.png"})
        self.assertEqual((f["w"], f["h"]), (0, 0))

    def test_arquivo_na_lixeira_e_marcado(self):
        self.assertTrue(normalizar_arquivo({"id": "x", "name": "a.png", "trashed": True})["trashed"])

    def test_traz_ocr_e_labels_do_snippet(self):
        f = normalizar_arquivo({"id": "x", "name": "a.png", "contentSnippet": SNIPPET_REAL})
        self.assertIn("MIGRAÇÃO", f["ocr_text"])
        self.assertIn("Bridge", f["labels"])


class TestQuery(unittest.TestCase):
    def test_restringe_a_pasta_e_a_imagens(self):
        q = query_da_pasta("PASTA123")
        self.assertIn("'PASTA123' in parents", q)
        self.assertIn("image/", q)

    def test_exclui_a_lixeira(self):
        self.assertIn("trashed = false", query_da_pasta("X"))


if __name__ == "__main__":
    unittest.main()
