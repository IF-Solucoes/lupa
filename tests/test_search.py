"""Busca no catálogo: sem embeddings, sem rede, sobre o índice já escrito."""
import unittest
from lupa.search import search

CATALOGO = [
    {"id": "1", "file": "ponte.png", "kind": "peca", "medium": "digital",
     "orientation": "retrato", "has_text": True,
     "caption": "Ponte estaiada à noite com luz azul fria",
     "tags": ["ponte", "noturno", "azul"], "text": "MIGRAÇÃO evoluir por módulos",
     "labels": ["Bridge"]},
    {"id": "2", "file": "mesa.jpg", "kind": "foto", "medium": "na",
     "orientation": "paisagem", "has_text": False,
     "caption": "Mesa de madeira rústica com pão artesanal e luz natural quente",
     "tags": ["comida", "pao", "madeira", "luz-natural"], "text": "", "labels": ["Food"]},
    {"id": "3", "file": "banner.jpg", "kind": "peca", "medium": "fisico",
     "orientation": "paisagem", "has_text": True,
     "caption": "Banner impresso em pé de evento, fundo azul",
     "tags": ["banner", "evento", "azul"], "text": "MINDTEC", "labels": []},
]


class TestCasamento(unittest.TestCase):
    def test_termo_em_tag_encontra(self):
        self.assertEqual([r["id"] for r in search(CATALOGO, "ponte")], ["1"])

    def test_termo_em_caption_encontra(self):
        self.assertIn("2", [r["id"] for r in search(CATALOGO, "artesanal")])

    def test_termo_no_ocr_encontra(self):
        self.assertIn("1", [r["id"] for r in search(CATALOGO, "módulos")])

    def test_termo_inexistente_devolve_vazio(self):
        self.assertEqual(search(CATALOGO, "helicóptero"), [])

    def test_acento_na_consulta_nao_atrapalha(self):
        self.assertIn("1", [r["id"] for r in search(CATALOGO, "noite")])
        self.assertIn("1", [r["id"] for r in search(CATALOGO, "NOITE")])

    def test_consulta_sem_acento_acha_termo_acentuado(self):
        self.assertIn("2", [r["id"] for r in search(CATALOGO, "pao")])
        self.assertIn("2", [r["id"] for r in search(CATALOGO, "pão")])


class TestRanking(unittest.TestCase):
    def test_tag_pesa_mais_que_ocr(self):
        r = search(CATALOGO, "azul")
        self.assertEqual(r[0]["id"], "1")  # tag "azul" + caption; o 3 tem tag também
        self.assertTrue(r[0]["_score"] >= r[-1]["_score"])

    def test_quem_casa_dois_termos_vem_antes(self):
        r = search(CATALOGO, "azul banner")
        self.assertEqual(r[0]["id"], "3")

    def test_resultado_explica_por_que_casou(self):
        r = search(CATALOGO, "ponte")
        self.assertIn("tag", r[0]["_motivo"])


class TestFiltros(unittest.TestCase):
    def test_filtro_de_kind_exclui_pecas(self):
        r = search(CATALOGO, "luz", filtros={"kind": "foto"})
        self.assertEqual([x["id"] for x in r], ["2"])

    def test_filtro_de_medium_isola_material_fisico(self):
        r = search(CATALOGO, "azul", filtros={"medium": "fisico"})
        self.assertEqual([x["id"] for x in r], ["3"])

    def test_filtro_has_text_false_tira_pecas_com_texto(self):
        r = search(CATALOGO, "luz", filtros={"has_text": False})
        self.assertEqual([x["id"] for x in r], ["2"])

    def test_filtro_de_orientacao(self):
        r = search(CATALOGO, "azul", filtros={"orientation": "retrato"})
        self.assertEqual([x["id"] for x in r], ["1"])

    def test_filtro_sozinho_sem_consulta_lista_tudo_que_bate(self):
        r = search(CATALOGO, "", filtros={"kind": "peca"})
        self.assertEqual(sorted(x["id"] for x in r), ["1", "3"])


class TestLimite(unittest.TestCase):
    def test_limite_corta_o_resultado(self):
        self.assertEqual(len(search(CATALOGO, "azul luz pao", limite=1)), 1)

    def test_limite_padrao_e_quinze(self):
        grande = [dict(CATALOGO[1], id=str(i)) for i in range(50)]
        self.assertEqual(len(search(grande, "madeira")), 15)


if __name__ == "__main__":
    unittest.main()
