"""Fonte de pasta local: mesma interface do Drive, sem credencial nenhuma."""
import struct
import tempfile
import unittest
from pathlib import Path
from lupa.fonte_local import FonteLocal


def png(w=1080, h=1350):
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
            + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00" + b"resto")


class TestFonteLocal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name)
        (self.pasta / "a.png").write_bytes(png(1080, 1350))
        (self.pasta / "b.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        (self.pasta / "leiame.txt").write_text("não sou imagem")
        (self.pasta / "sub").mkdir()
        (self.pasta / "sub" / "c.png").write_bytes(png(800, 600))
        (self.pasta / "_lupa").mkdir()
        (self.pasta / "_lupa" / "contact.png").write_bytes(png(100, 100))
        self.fonte = FonteLocal(self.pasta)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lista_so_imagens(self):
        nomes = sorted(f["file"] for f in self.fonte.listar())
        self.assertNotIn("leiame.txt", nomes)

    def test_varre_subpastas(self):
        self.assertIn("sub/c.png", [f["id"] for f in self.fonte.listar()])

    def test_ignora_a_propria_pasta_de_indice(self):
        ids = [f["id"] for f in self.fonte.listar()]
        self.assertFalse(any(i.startswith("_lupa") for i in ids))

    def test_le_as_dimensoes_do_arquivo(self):
        a = [f for f in self.fonte.listar() if f["file"] == "a.png"][0]
        self.assertEqual((a["w"], a["h"]), (1080, 1350))

    def test_hash_muda_quando_o_arquivo_muda(self):
        antes = {f["id"]: f["hash"] for f in self.fonte.listar()}
        (self.pasta / "a.png").write_bytes(png(1080, 1350) + b"mais bytes")
        depois = {f["id"]: f["hash"] for f in self.fonte.listar()}
        self.assertNotEqual(antes["a.png"], depois["a.png"])

    def test_hash_estavel_quando_nada_muda(self):
        self.assertEqual([f["hash"] for f in self.fonte.listar()],
                         [f["hash"] for f in self.fonte.listar()])

    def test_url_aponta_para_o_arquivo_no_disco(self):
        a = [f for f in self.fonte.listar() if f["file"] == "a.png"][0]
        self.assertTrue(a["url"].startswith("file://"))

    def test_sem_ocr_porque_pasta_local_nao_tem_esse_brinde(self):
        self.assertEqual(self.fonte.listar()[0]["ocr_text"], "")

    def test_baixar_devolve_bytes_e_mime(self):
        dados, mime = self.fonte.baixar("a.png")
        self.assertTrue(dados.startswith(b"\x89PNG"))
        self.assertEqual(mime, "image/png")

    def test_pasta_vazia_devolve_lista_vazia(self):
        with tempfile.TemporaryDirectory() as vazia:
            self.assertEqual(FonteLocal(vazia).listar(), [])


if __name__ == "__main__":
    unittest.main()
