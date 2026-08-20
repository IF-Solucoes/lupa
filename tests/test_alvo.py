"""O usuário diz de qualquer jeito; o lupa entende."""
import tempfile
import unittest
from pathlib import Path
from lupa.alvo import resolver_alvo, AlvoInvalido


class TestUrlDoDrive(unittest.TestCase):
    def test_url_de_pasta(self):
        a = resolver_alvo("https://drive.google.com/drive/folders/15fvulCdmeBAG7T2Tm")
        self.assertEqual(a.tipo, "drive")
        self.assertEqual(a.folder_id, "15fvulCdmeBAG7T2Tm")

    def test_url_com_parametros_extras(self):
        a = resolver_alvo("https://drive.google.com/drive/folders/ABC123?usp=sharing")
        self.assertEqual(a.folder_id, "ABC123")

    def test_url_de_pasta_compartilhada_com_u_zero(self):
        a = resolver_alvo("https://drive.google.com/drive/u/0/folders/XYZ789")
        self.assertEqual(a.folder_id, "XYZ789")

    def test_id_solto_e_aceito_como_pasta_do_drive(self):
        a = resolver_alvo("15fvulCdmeBAG7T2Tmwuz5KcDD4XF3eah")
        self.assertEqual(a.tipo, "drive")
        self.assertEqual(a.folder_id, "15fvulCdmeBAG7T2Tmwuz5KcDD4XF3eah")

    def test_nome_do_acervo_vem_do_id_quando_nao_ha_outro(self):
        a = resolver_alvo("https://drive.google.com/drive/folders/ABC123")
        self.assertTrue(a.nome)

    def test_nome_explicito_vence(self):
        a = resolver_alvo("https://drive.google.com/drive/folders/ABC123", nome="if-editorial")
        self.assertEqual(a.nome, "if-editorial")


class TestPastaLocal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name) / "Fotos Do Cliente"
        self.pasta.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_caminho_existente_vira_alvo_local(self):
        a = resolver_alvo(str(self.pasta))
        self.assertEqual(a.tipo, "local")
        self.assertEqual(a.caminho, self.pasta)

    def test_nome_do_acervo_sai_do_nome_da_pasta(self):
        self.assertEqual(resolver_alvo(str(self.pasta)).nome, "fotos-do-cliente")

    def test_til_e_expandido(self):
        a = resolver_alvo("~")
        self.assertEqual(a.tipo, "local")

    def test_caminho_relativo_funciona(self):
        import os
        os.chdir(self.pasta.parent)
        self.assertEqual(resolver_alvo("Fotos Do Cliente").tipo, "local")

    def test_arquivo_solto_nao_e_acervo(self):
        arquivo = self.pasta / "foto.png"
        arquivo.write_bytes(b"x")
        with self.assertRaises(AlvoInvalido):
            resolver_alvo(str(arquivo))


class TestEntradaRuim(unittest.TestCase):
    def test_vazio_recusa(self):
        with self.assertRaises(AlvoInvalido):
            resolver_alvo("")

    def test_url_que_nao_e_de_pasta_recusa_com_dica(self):
        with self.assertRaises(AlvoInvalido) as ctx:
            resolver_alvo("https://drive.google.com/file/d/ABC/view")
        self.assertIn("pasta", str(ctx.exception).lower())

    def test_caminho_inexistente_recusa(self):
        with self.assertRaises(AlvoInvalido):
            resolver_alvo("/caminho/que/nao/existe/mesmo")


if __name__ == "__main__":
    unittest.main()
