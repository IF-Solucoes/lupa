"""Servidor MCP: despacho JSON-RPC sobre o índice já escrito."""
import json
import tempfile
import unittest
from pathlib import Path

from lupa.mcp import Servidor

ITEM = {"id": "1", "file": "ponte.png", "url": "https://drive/1", "kind": "peca",
        "medium": "digital", "orientation": "retrato", "has_text": True,
        "caption": "Ponte à noite", "tags": ["ponte", "noturno"], "text": "", "labels": []}


class BaseMcp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name)
        acervo = self.raiz / "if-editorial"
        acervo.mkdir()
        (acervo / "catalog.jsonl").write_text(json.dumps(ITEM, ensure_ascii=False) + "\n")
        (acervo / "MANIFEST.json").write_text(json.dumps({"acervo": "if-editorial", "total": 1}))
        self.servidor = Servidor(self.raiz)

    def tearDown(self):
        self.tmp.cleanup()

    def chamar(self, metodo, params=None, id_=1):
        return self.servidor.despachar({"jsonrpc": "2.0", "id": id_,
                                        "method": metodo, "params": params or {}})


class TestHandshake(BaseMcp):
    def test_initialize_anuncia_o_servidor(self):
        r = self.chamar("initialize")
        self.assertIn("protocolVersion", r["result"])
        self.assertEqual(r["result"]["serverInfo"]["name"], "lupa")

    def test_metodo_desconhecido_devolve_erro_padrao(self):
        self.assertEqual(self.chamar("tools/inexistente")["error"]["code"], -32601)

    def test_notificacao_sem_id_nao_gera_resposta(self):
        self.assertIsNone(self.servidor.despachar(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}))


class TestFerramentas(BaseMcp):
    def test_lista_as_duas_ferramentas(self):
        nomes = [t["name"] for t in self.chamar("tools/list")["result"]["tools"]]
        self.assertEqual(sorted(nomes), ["lupa_search", "lupa_status"])

    def test_toda_ferramenta_tem_schema_de_entrada(self):
        for t in self.chamar("tools/list")["result"]["tools"]:
            self.assertIn("inputSchema", t)


class TestBusca(BaseMcp):
    def _buscar(self, **args):
        r = self.chamar("tools/call", {"name": "lupa_search", "arguments": args})
        return r["result"]["content"][0]["text"]

    def test_encontra_por_tag(self):
        self.assertIn("ponte.png", self._buscar(consulta="ponte", acervo="if-editorial"))

    def test_resultado_traz_o_link(self):
        self.assertIn("https://drive/1", self._buscar(consulta="ponte", acervo="if-editorial"))

    def test_busca_sem_resultado_explica_em_vez_de_quebrar(self):
        self.assertIn("nenhum", self._buscar(consulta="helicoptero", acervo="if-editorial").lower())

    def test_acervo_inexistente_lista_os_disponiveis(self):
        saida = self._buscar(consulta="x", acervo="nao-existe")
        self.assertIn("if-editorial", saida)

    def test_filtro_de_kind_e_respeitado(self):
        self.assertIn("nenhum", self._buscar(
            consulta="ponte", acervo="if-editorial", kind="foto").lower())

    def test_sem_acervo_busca_em_todos(self):
        self.assertIn("ponte.png", self._buscar(consulta="ponte"))


class TestStatus(BaseMcp):
    def test_status_lista_os_acervos_e_o_total(self):
        r = self.chamar("tools/call", {"name": "lupa_status", "arguments": {}})
        texto = r["result"]["content"][0]["text"]
        self.assertIn("if-editorial", texto)
        self.assertIn("1", texto)


if __name__ == "__main__":
    unittest.main()
