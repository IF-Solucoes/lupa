"""Integração: o ciclo index → update → update sem rede e sem gastar modelo."""
import json
import tempfile
import unittest
from pathlib import Path

from lupa.guards import IndiceJaExiste
from lupa.pipeline import rodar


class AcervoFake:
    """Um Drive de mentira: devolve metadados e bytes de imagem."""

    def __init__(self, arquivos):
        self.arquivos = arquivos
        self.baixados = []

    def listar(self):
        return list(self.arquivos)

    def baixar(self, file_id):
        self.baixados.append(file_id)
        return b"bytes", "image/png"


class ModeloFake:
    """Conta quantas vezes foi chamado — é a métrica que prova o incremental."""

    def __init__(self):
        self.chamadas = []

    def __call__(self, item, imagem, mime):
        self.chamadas.append(item["id"])
        return {"caption": f"desc de {item['file']}", "tags": ["tag-comum", item["id"]],
                "scene": "interior", "people": 0, "palette": ["#000000"]}


def arquivo(id_, hash_, nome=None):
    return {"id": id_, "file": nome or f"{id_}.png", "hash": hash_, "mime": "image/png",
            "w": 1080, "h": 1350, "exif": {}, "ocr_text": "TEXTO " * 10, "labels": [],
            "url": f"https://drive/{id_}", "trashed": False, "size": 100}


class BasePipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "_lupa"
        self.modelo = ModeloFake()

    def tearDown(self):
        self.tmp.cleanup()

    def rodar(self, acervo_fake, modo="update", **kw):
        return rodar(acervo="if-editorial", index_dir=self.dir, fonte=acervo_fake,
                     descrever=self.modelo, modo=modo, agora=kw.pop("agora", "2026-08-20T10-00-00"),
                     **kw)

    def catalogo(self):
        linhas = (self.dir / "catalog.jsonl").read_text().strip().splitlines()
        return [json.loads(l) for l in linhas if l.strip()]


class TestPrimeiraRodada(BasePipeline):
    def test_indexa_tudo_e_escreve_o_indice(self):
        fonte = AcervoFake([arquivo("a", "1"), arquivo("b", "2")])
        r = self.rodar(fonte, modo="index")
        self.assertEqual(sorted(self.modelo.chamadas), ["a", "b"])
        self.assertEqual(len(self.catalogo()), 2)
        self.assertEqual(r["plano"].novas, ["a", "b"])

    def test_index_em_acervo_ja_indexado_recusa(self):
        fonte = AcervoFake([arquivo("a", "1")])
        self.rodar(fonte, modo="index")
        with self.assertRaises(IndiceJaExiste):
            self.rodar(fonte, modo="index")


class TestIncremental(BasePipeline):
    def setUp(self):
        super().setUp()
        self.fonte = AcervoFake([arquivo("a", "1"), arquivo("b", "2")])
        self.rodar(self.fonte, modo="index")
        self.modelo.chamadas.clear()

    def test_rodada_sem_mudanca_nao_chama_o_modelo(self):
        self.rodar(self.fonte)
        self.assertEqual(self.modelo.chamadas, [])

    def test_rodada_sem_mudanca_nao_baixa_imagem(self):
        self.fonte.baixados.clear()
        self.rodar(self.fonte)
        self.assertEqual(self.fonte.baixados, [])

    def test_arquivo_novo_e_descrito_sozinho(self):
        self.fonte.arquivos.append(arquivo("c", "3"))
        self.rodar(self.fonte)
        self.assertEqual(self.modelo.chamadas, ["c"])
        self.assertEqual(len(self.catalogo()), 3)

    def test_arquivo_alterado_e_redescrito(self):
        self.fonte.arquivos[0] = arquivo("a", "HASH-NOVO")
        self.rodar(self.fonte)
        self.assertEqual(self.modelo.chamadas, ["a"])

    def test_arquivo_apagado_some_do_catalogo_sem_custo(self):
        self.fonte.arquivos.pop(0)  # "a" foi embora
        self.rodar(self.fonte)
        self.assertEqual(self.modelo.chamadas, [])
        self.assertEqual([i["id"] for i in self.catalogo()], ["b"])

    def test_descricao_antiga_sobrevive_a_rodada(self):
        self.fonte.arquivos.append(arquivo("c", "3"))
        self.rodar(self.fonte)
        antigo = [i for i in self.catalogo() if i["id"] == "a"][0]
        self.assertEqual(antigo["caption"], "desc de a.png")


class TestPlanoSemGastar(BasePipeline):
    def test_dry_run_nao_chama_o_modelo(self):
        fonte = AcervoFake([arquivo("a", "1")])
        r = self.rodar(fonte, modo="index", dry_run=True)
        self.assertEqual(self.modelo.chamadas, [])
        self.assertEqual(r["plano"].novas, ["a"])

    def test_dry_run_nao_escreve_indice(self):
        fonte = AcervoFake([arquivo("a", "1")])
        self.rodar(fonte, modo="index", dry_run=True)
        self.assertFalse((self.dir / "catalog.jsonl").exists())

    def test_dry_run_estima_o_custo(self):
        fonte = AcervoFake([arquivo(str(i), "h") for i in range(10)])
        r = self.rodar(fonte, modo="index", dry_run=True)
        self.assertGreater(r["custo_estimado"], 0)


class TestFalhaIsolada(BasePipeline):
    def test_imagem_que_falha_nao_derruba_a_rodada(self):
        def modelo_que_falha(item, imagem, mime):
            if item["id"] == "b":
                raise RuntimeError("imagem corrompida")
            return {"caption": "ok", "tags": ["t"]}

        fonte = AcervoFake([arquivo("a", "1"), arquivo("b", "2")])
        r = rodar(acervo="x", index_dir=self.dir, fonte=fonte, descrever=modelo_que_falha,
                  modo="index", agora="2026-08-20T10-00-00")
        self.assertEqual([i["id"] for i in self.catalogo()], ["a"])
        self.assertEqual(len(r["falhas"]), 1)
        self.assertIn("corrompida", r["falhas"][0]["erro"])


if __name__ == "__main__":
    unittest.main()
