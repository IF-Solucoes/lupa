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


class TestAutoCadastro(unittest.TestCase):
    def test_acervo_novo_e_registrado(self):
        from lupa.config import registrar_acervo
        from lupa.alvo import Alvo
        cfg = registrar_acervo({"acervos": []}, Alvo("drive", "if", folder_id="ABC"))
        self.assertEqual(cfg["acervos"][0]["nome"], "if")
        self.assertEqual(cfg["acervos"][0]["folder_id"], "ABC")

    def test_acervo_local_guarda_o_caminho(self):
        from lupa.config import registrar_acervo
        from lupa.alvo import Alvo
        from pathlib import Path
        cfg = registrar_acervo({}, Alvo("local", "fotos", caminho=Path("/tmp/fotos")))
        self.assertEqual(cfg["acervos"][0]["caminho"], "/tmp/fotos")

    def test_registrar_duas_vezes_nao_duplica(self):
        from lupa.config import registrar_acervo
        from lupa.alvo import Alvo
        a = Alvo("drive", "if", folder_id="ABC")
        cfg = registrar_acervo(registrar_acervo({}, a), a)
        self.assertEqual(len(cfg["acervos"]), 1)

    def test_mesmo_nome_com_alvo_diferente_atualiza_o_registro(self):
        from lupa.config import registrar_acervo
        from lupa.alvo import Alvo
        cfg = registrar_acervo({}, Alvo("drive", "if", folder_id="ABC"))
        cfg = registrar_acervo(cfg, Alvo("drive", "if", folder_id="NOVO"))
        self.assertEqual(len(cfg["acervos"]), 1)
        self.assertEqual(cfg["acervos"][0]["folder_id"], "NOVO")

    def test_alvo_a_partir_de_acervo_cadastrado(self):
        from lupa.config import alvo_de_cadastro
        a = alvo_de_cadastro({"nome": "if", "folder_id": "ABC"})
        self.assertEqual(a.tipo, "drive")
        self.assertEqual(a.folder_id, "ABC")

    def test_alvo_local_a_partir_de_cadastro(self):
        from lupa.config import alvo_de_cadastro
        a = alvo_de_cadastro({"nome": "fotos", "caminho": "/tmp/fotos"})
        self.assertEqual(a.tipo, "local")
