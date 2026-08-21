"""`lupa fetch` fecha o ciclo que a busca abre.

Antes disto, `search` devolvia a URL do arquivo e parava ali: quem quisesse a
imagem tinha que extrair o id com regex e chamar a API por fora. O caminho em
`file` e do Drive, nao do sistema de arquivos local — ele nao resolve em disco e
nao deveria, porque um segmento pode terminar em espaco, coisa que o Drive aceita
e o Windows nao. Quem resolve e o id.

Os testes aqui nao tocam a rede: exercitam o reconhecimento do alvo e a busca no
catalogo, que e onde as decisoes moram.
"""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from lupa import cli


class TestReconhecimentoDoAlvo(unittest.TestCase):
    """Tres formas chegam pela busca, e as tres tem que ser aceitas."""

    def test_url_de_compartilhamento(self):
        self.assertEqual(
            cli._file_id_de("https://drive.google.com/file/d/1N-pGXyxA4IzbOm2B-hPabzZ6i8B53C6T/view?usp=drivesdk"),
            "1N-pGXyxA4IzbOm2B-hPabzZ6i8B53C6T")

    def test_url_com_id_na_query(self):
        self.assertEqual(
            cli._file_id_de("https://drive.google.com/open?id=1N-pGXyxA4IzbOm2B-hPabzZ6i8B53C6T"),
            "1N-pGXyxA4IzbOm2B-hPabzZ6i8B53C6T")

    def test_id_cru(self):
        self.assertEqual(cli._file_id_de("1N-pGXyxA4IzbOm2B-hPabzZ6i8B53C6T"),
                         "1N-pGXyxA4IzbOm2B-hPabzZ6i8B53C6T")

    def test_um_caminho_nao_e_id(self):
        """Se o caminho virasse id, o fetch pediria a Drive um arquivo inexistente."""
        self.assertIsNone(cli._file_id_de("2 - Kit Marca/Logotipo/PNG/logo.png"))

    def test_um_nome_curto_nao_e_id(self):
        self.assertIsNone(cli._file_id_de("capa.png"))


class TestBuscaNoCatalogo(unittest.TestCase):
    """O alvo tambem pode ser o caminho, que e o que a busca imprime."""

    def setUp(self):
        self.raiz = tempfile.mkdtemp()
        colecao = Path(self.raiz) / "acme"
        colecao.mkdir(parents=True)
        fichas = [
            {"id": "aaa", "file": "2 - Kit Marca/logo.png",
             "url": "https://drive.google.com/file/d/1AAAAAAAAAAAAAAAAAAAAAA/view"},
            # Espaco antes da barra: e assim que o Drive nomeia, e e assim que o
            # catalogo grava. Ninguem digita esse espaco.
            {"id": "bbb", "file": "4 - Fotos & Videos /Tratamento/foto.jpg",
             "url": "https://drive.google.com/file/d/1BBBBBBBBBBBBBBBBBBBBBB/view"},
        ]
        io.open(colecao / "catalog.jsonl", "w", encoding="utf-8").write(
            "\n".join(json.dumps(f) for f in fichas))
        self.env = {"LUPA_INDEXES": self.raiz}
        self._antes = dict(os.environ)
        os.environ["LUPA_INDEXES"] = self.raiz

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._antes)

    def test_acha_pelo_caminho_exato(self):
        achado = cli._por_caminho(self.env, "2 - Kit Marca/logo.png", "acme")
        self.assertEqual(achado, ("1AAAAAAAAAAAAAAAAAAAAAA", "logo.png"))

    def test_acha_mesmo_sem_o_espaco_invisivel(self):
        """Quem le a busca digita sem o espaco. Nao achar por isso seria cruel."""
        achado = cli._por_caminho(
            self.env, "4 - Fotos & Videos/Tratamento/foto.jpg", "acme")
        self.assertEqual(achado, ("1BBBBBBBBBBBBBBBBBBBBBB", "foto.jpg"))

    def test_acha_so_pelo_nome_do_arquivo(self):
        achado = cli._por_caminho(self.env, "logo.png", "acme")
        self.assertEqual(achado, ("1AAAAAAAAAAAAAAAAAAAAAA", "logo.png"))

    def test_o_que_nao_existe_devolve_nada(self):
        self.assertIsNone(cli._por_caminho(self.env, "nao/existe.png", "acme"))

    def test_nome_do_arquivo_a_partir_do_id(self):
        """Sem isto o download grava com o id por nome e a pasta fica ilegivel."""
        self.assertEqual(
            cli._nome_do_id(self.env, "1BBBBBBBBBBBBBBBBBBBBBB", "acme"),
            "foto.jpg")

    def test_id_desconhecido_nao_inventa_nome(self):
        self.assertIsNone(cli._nome_do_id(self.env, "1ZZZZZZZZZZZZZZZZZZZZZZ", "acme"))

    def test_procura_em_todas_as_colecoes_quando_nenhuma_e_dita(self):
        achado = cli._por_caminho(self.env, "logo.png")
        self.assertEqual(achado, ("1AAAAAAAAAAAAAAAAAAAAAA", "logo.png"))


class TestOComandoEstaLigado(unittest.TestCase):
    def test_fetch_e_um_subcomando(self):
        parser = cli.build_parser() if hasattr(cli, "build_parser") else None
        if parser is None:
            self.skipTest("o parser nao e exposto isoladamente")
        args = parser.parse_args(["fetch", "abc", "--out", "x"])
        self.assertEqual(args.command, "fetch")

    def test_o_dispatch_conhece_fetch(self):
        fonte = Path(cli.__file__).read_text(encoding="utf-8")
        self.assertIn('args.command == "fetch"', fonte)
        self.assertIn("command_fetch(args)", fonte)


if __name__ == "__main__":
    unittest.main()
