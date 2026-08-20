"""Leitura do .env e do config de acervos."""
import tempfile
import unittest
from pathlib import Path
from lupa.config import ler_env, achar_acervo


class TestEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False)
        self.tmp.write(
            "# comentário\n"
            "GEMINI_API_KEY=abc123\n"
            "\n"
            "LUPA_BATCH=1\n"
            'LUPA_MODEL="gemini-2.5-flash-lite"\n'
            "LUPA_STATE_DIR=~/.francis/state/lupa\n"
            "VAZIA=\n"
        )
        self.tmp.close()

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_le_par_simples(self):
        self.assertEqual(ler_env(self.tmp.name)["GEMINI_API_KEY"], "abc123")

    def test_ignora_comentario_e_linha_vazia(self):
        env = ler_env(self.tmp.name)
        self.assertNotIn("# comentário", env)
        self.assertEqual(len([k for k in env if k]), 5)

    def test_tira_aspas_do_valor(self):
        self.assertEqual(ler_env(self.tmp.name)["LUPA_MODEL"], "gemini-2.5-flash-lite")

    def test_expande_o_til_de_caminho(self):
        self.assertNotIn("~", ler_env(self.tmp.name)["LUPA_STATE_DIR"])

    def test_valor_vazio_vira_string_vazia(self):
        self.assertEqual(ler_env(self.tmp.name)["VAZIA"], "")

    def test_arquivo_inexistente_devolve_vazio(self):
        self.assertEqual(ler_env("/nao/existe/.env"), {})


class TestAcervo(unittest.TestCase):
    CFG = {"acervos": [
        {"nome": "if-editorial", "folder_id": "ABC"},
        {"nome": "cliente-x", "folder_id": "DEF"},
    ]}

    def test_acha_pelo_nome(self):
        self.assertEqual(achar_acervo(self.CFG, "cliente-x")["folder_id"], "DEF")

    def test_nome_desconhecido_devolve_none(self):
        self.assertIsNone(achar_acervo(self.CFG, "inexistente"))

    def test_config_sem_acervos_nao_quebra(self):
        self.assertIsNone(achar_acervo({}, "x"))


if __name__ == "__main__":
    unittest.main()


class TestRaizDeIndices(unittest.TestCase):
    def test_variavel_explicita_vence(self):
        from lupa.config import resolver_raiz_indices
        r = resolver_raiz_indices({"LUPA_INDICES": "/tmp/x"}, {})
        self.assertEqual(str(r), "/tmp/x")

    def test_state_dir_do_env_vira_subpasta_indices(self):
        from lupa.config import resolver_raiz_indices
        r = resolver_raiz_indices({}, {"LUPA_STATE_DIR": "/home/u/.francis/state/lupa"})
        self.assertEqual(str(r), "/home/u/.francis/state/lupa/indices")

    def test_sem_nada_cai_no_padrao_portatil(self):
        from lupa.config import resolver_raiz_indices
        self.assertTrue(str(resolver_raiz_indices({}, {})).endswith(".lupa/indices"))
