"""Pré-flight: diagnostica o ambiente e ensina o caminho antes de gastar."""
import tempfile
import unittest
from pathlib import Path

from lupa.alvo import Alvo
from lupa.preflight import diagnosticar, BLOQUEIO, AVISO, OK, tem_bloqueio


def alvo_drive():
    return Alvo("drive", "if-editorial", folder_id="ABC123")


def alvo_local(caminho):
    return Alvo("local", "fotos", caminho=Path(caminho))


ENV_COMPLETO = {"GEMINI_API_KEY": "abc", "LUPA_OAUTH_CLIENT": "/existe/oauth.json",
                "LUPA_OAUTH_TOKEN": "/existe/token.json"}


class TestChave(unittest.TestCase):
    def test_sem_chave_do_gemini_bloqueia(self):
        c = diagnosticar(alvo_drive(), env={}, arquivos_existentes=set())
        chave = [x for x in c if x.nome == "chave do Gemini"][0]
        self.assertEqual(chave.status, BLOQUEIO)

    def test_a_mensagem_diz_onde_arrumar_a_chave(self):
        c = diagnosticar(alvo_drive(), env={}, arquivos_existentes=set())
        chave = [x for x in c if x.nome == "chave do Gemini"][0]
        self.assertIn("aistudio.google.com", chave.como_resolver)
        self.assertIn("lupa.env", chave.como_resolver)

    def test_com_chave_passa(self):
        c = diagnosticar(alvo_drive(), env=ENV_COMPLETO,
                         arquivos_existentes={"/existe/oauth.json", "/existe/token.json"})
        chave = [x for x in c if x.nome == "chave do Gemini"][0]
        self.assertEqual(chave.status, OK)


class TestCredencialDoDrive(unittest.TestCase):
    def test_sem_oauth_client_bloqueia_alvo_no_drive(self):
        c = diagnosticar(alvo_drive(), env={"GEMINI_API_KEY": "x"}, arquivos_existentes=set())
        oauth = [x for x in c if x.nome == "acesso ao Google Drive"][0]
        self.assertEqual(oauth.status, BLOQUEIO)
        self.assertIn("console.cloud.google.com", oauth.como_resolver)

    def test_sem_token_apenas_avisa_que_vai_pedir_login(self):
        c = diagnosticar(alvo_drive(), env=ENV_COMPLETO,
                         arquivos_existentes={"/existe/oauth.json"})
        login = [x for x in c if x.nome == "login do Google"][0]
        self.assertEqual(login.status, AVISO)

    def test_alvo_local_nao_exige_credencial_do_drive(self):
        with tempfile.TemporaryDirectory() as d:
            c = diagnosticar(alvo_local(d), env={"GEMINI_API_KEY": "x"},
                             arquivos_existentes=set())
            self.assertFalse(any(x.nome == "acesso ao Google Drive" for x in c))
            self.assertFalse(tem_bloqueio(c))


class TestDriveMontado(unittest.TestCase):
    def test_pasta_montada_do_drive_gera_aviso_explicativo(self):
        c = diagnosticar(alvo_local("/mnt/g/Meu Drive/Clientes"), env={"GEMINI_API_KEY": "x"},
                         arquivos_existentes=set())
        aviso = [x for x in c if x.nome == "origem do acervo"][0]
        self.assertEqual(aviso.status, AVISO)
        self.assertIn("OCR", aviso.como_resolver)

    def test_o_aviso_nao_bloqueia_a_execucao(self):
        c = diagnosticar(alvo_local("/mnt/g/Meu Drive/Clientes"), env={"GEMINI_API_KEY": "x"},
                         arquivos_existentes=set())
        self.assertFalse(tem_bloqueio(c))

    def test_pasta_comum_nao_gera_esse_aviso(self):
        with tempfile.TemporaryDirectory() as d:
            c = diagnosticar(alvo_local(d), env={"GEMINI_API_KEY": "x"}, arquivos_existentes=set())
            origem = [x for x in c if x.nome == "origem do acervo"][0]
            self.assertEqual(origem.status, OK)


class TestIndiceExistente(unittest.TestCase):
    def test_avisa_que_sera_atualizacao_e_nao_criacao(self):
        c = diagnosticar(alvo_drive(), env=ENV_COMPLETO, arquivos_existentes=set(),
                         indice_existe=True)
        estado = [x for x in c if x.nome == "estado do índice"][0]
        self.assertIn("update", estado.mensagem.lower())

    def test_acervo_virgem_diz_que_sera_a_primeira_rodada(self):
        c = diagnosticar(alvo_drive(), env=ENV_COMPLETO, arquivos_existentes=set(),
                         indice_existe=False)
        estado = [x for x in c if x.nome == "estado do índice"][0]
        self.assertIn("primeira", estado.mensagem.lower())


class TestResumo(unittest.TestCase):
    def test_tem_bloqueio_detecta_qualquer_impedimento(self):
        self.assertTrue(tem_bloqueio(diagnosticar(alvo_drive(), env={}, arquivos_existentes=set())))

    def test_ambiente_completo_nao_tem_bloqueio(self):
        c = diagnosticar(alvo_drive(), env=ENV_COMPLETO,
                         arquivos_existentes={"/existe/oauth.json", "/existe/token.json"})
        self.assertFalse(tem_bloqueio(c))


if __name__ == "__main__":
    unittest.main()
