"""Escrita do índice: os artefatos que os agentes leem."""
import json
import tempfile
import unittest
from pathlib import Path

from lupa.build import escrever_indice, fazer_backup, nome_de_arquivo_de_tag

ITENS = [
    {"id": "1", "file": "ponte.png", "url": "https://drive/1", "kind": "peca",
     "medium": "digital", "orientation": "retrato", "has_text": True, "hash": "h1",
     "caption": "Ponte à noite", "tags": ["ponte", "noturno"], "text": "MIGRAÇÃO", "labels": []},
    {"id": "2", "file": "mesa.jpg", "url": "https://drive/2", "kind": "foto",
     "medium": "na", "orientation": "paisagem", "has_text": False, "hash": "h2",
     "caption": "Mesa de madeira", "tags": ["comida", "noturno"], "text": "", "labels": []},
]


class BaseIndice(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def escrever(self, itens=None, **kw):
        return escrever_indice(
            self.dir, acervo="if-editorial", itens=itens if itens is not None else ITENS,
            resumo=kw.pop("resumo", "+2 novas"), modelo="gemini-2.5-flash-lite",
            custo_usd=kw.pop("custo_usd", 0.0001), agora=kw.pop("agora", "2026-08-20T14:32:00"), **kw)


class TestCatalogo(BaseIndice):
    def test_uma_linha_por_imagem(self):
        self.escrever()
        linhas = (self.dir / "catalog.jsonl").read_text().strip().split("\n")
        self.assertEqual(len(linhas), 2)

    def test_cada_linha_e_json_valido(self):
        self.escrever()
        for linha in (self.dir / "catalog.jsonl").read_text().strip().split("\n"):
            self.assertIn("id", json.loads(linha))

    def test_acentos_sobrevivem_sem_escapar(self):
        self.escrever()
        self.assertIn("Ponte à noite", (self.dir / "catalog.jsonl").read_text())

    def test_item_removido_some_do_catalogo(self):
        self.escrever()
        self.escrever(itens=[ITENS[0]])
        linhas = (self.dir / "catalog.jsonl").read_text().strip().split("\n")
        self.assertEqual(len(linhas), 1)


class TestIndexMd(BaseIndice):
    def test_traz_o_total_de_imagens(self):
        self.escrever()
        self.assertIn("2", (self.dir / "INDEX.md").read_text())

    def test_avisa_o_agente_para_nao_abrir_as_imagens(self):
        self.escrever()
        texto = (self.dir / "INDEX.md").read_text().lower()
        self.assertIn("pixels", texto)

    def test_lista_o_vocabulario_de_tags_com_contagem(self):
        self.escrever()
        texto = (self.dir / "INDEX.md").read_text()
        self.assertIn("noturno", texto)
        self.assertIn("2", texto)  # noturno aparece nas duas imagens


class TestByTag(BaseIndice):
    def test_cria_um_arquivo_por_tag(self):
        self.escrever()
        tags = sorted(p.stem for p in (self.dir / "by-tag").glob("*.md"))
        self.assertEqual(tags, ["comida", "noturno", "ponte"])

    def test_arquivo_de_tag_lista_os_membros(self):
        self.escrever()
        texto = (self.dir / "by-tag" / "noturno.md").read_text()
        self.assertIn("ponte.png", texto)
        self.assertIn("mesa.jpg", texto)

    def test_arquivo_de_tag_traz_a_url(self):
        self.escrever()
        self.assertIn("https://drive/1", (self.dir / "by-tag" / "ponte.md").read_text())

    def test_tag_com_acento_e_espaco_vira_nome_seguro(self):
        self.assertEqual(nome_de_arquivo_de_tag("Pão Artesanal"), "pao-artesanal")

    def test_tags_que_sumiram_nao_deixam_arquivo_orfao(self):
        self.escrever()
        self.escrever(itens=[ITENS[1]])  # "ponte" deixou de existir
        self.assertFalse((self.dir / "by-tag" / "ponte.md").exists())


class TestManifesto(BaseIndice):
    def test_guarda_hash_de_cada_item(self):
        self.escrever()
        m = json.loads((self.dir / "MANIFEST.json").read_text())
        self.assertEqual(m["itens"]["1"]["hash"], "h1")

    def test_guarda_total_e_acervo(self):
        self.escrever()
        m = json.loads((self.dir / "MANIFEST.json").read_text())
        self.assertEqual(m["total"], 2)
        self.assertEqual(m["acervo"], "if-editorial")

    def test_conta_as_rodadas(self):
        self.escrever()
        self.assertEqual(json.loads((self.dir / "MANIFEST.json").read_text())["rodadas"], 1)
        self.escrever()
        self.assertEqual(json.loads((self.dir / "MANIFEST.json").read_text())["rodadas"], 2)


class TestRelatorioDaRodada(BaseIndice):
    def test_escreve_um_relatorio_por_rodada(self):
        self.escrever(agora="2026-08-20T14:32:00")
        self.assertTrue((self.dir / "runs" / "2026-08-20T14-32-00.md").exists())

    def test_relatorio_traz_resumo_custo_e_modelo(self):
        self.escrever(resumo="+40 novas · -5 removidas", custo_usd=0.004)
        texto = list((self.dir / "runs").glob("*.md"))[0].read_text()
        self.assertIn("+40 novas", texto)
        self.assertIn("0.004", texto)
        self.assertIn("gemini-2.5-flash-lite", texto)


class TestBackup(BaseIndice):
    def test_backup_copia_o_indice_anterior(self):
        self.escrever()
        destino = fazer_backup(self.dir, agora="2026-08-20T15-00-00")
        self.assertTrue((destino / "catalog.jsonl").exists())
        self.assertTrue((destino / "MANIFEST.json").exists())

    def test_backup_em_indice_inexistente_nao_quebra(self):
        self.assertIsNone(fazer_backup(self.dir / "vazio", agora="x"))

    def test_backup_nao_apaga_o_indice_atual(self):
        self.escrever()
        fazer_backup(self.dir, agora="2026-08-20T15-00-00")
        self.assertTrue((self.dir / "catalog.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
