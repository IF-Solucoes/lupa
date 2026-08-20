"""Montagem das requisições ao Gemini e leitura do resultado em lote."""
import base64
import json
import unittest
from lupa.gemini import montar_conteudo, linha_de_lote, ler_resultado_de_lote

IMG = b"\x89PNG\r\n\x1a\n-bytes-de-teste"


class TestConteudo(unittest.TestCase):
    def test_manda_a_imagem_em_base64(self):
        c = montar_conteudo("descreva", IMG, "image/png")
        dados = c["contents"][0]["parts"][1]["inline_data"]
        self.assertEqual(dados["mime_type"], "image/png")
        self.assertEqual(base64.b64decode(dados["data"]), IMG)

    def test_manda_o_prompt_junto(self):
        c = montar_conteudo("descreva isso", IMG, "image/png")
        self.assertEqual(c["contents"][0]["parts"][0]["text"], "descreva isso")

    def test_pede_json_ao_modelo(self):
        c = montar_conteudo("x", IMG, "image/png")
        self.assertEqual(c["generationConfig"]["responseMimeType"], "application/json")


class TestLote(unittest.TestCase):
    def test_cada_linha_carrega_a_chave_de_volta(self):
        linha = json.loads(linha_de_lote("id-42", "prompt", IMG, "image/png"))
        self.assertEqual(linha["key"], "id-42")

    def test_cada_linha_e_json_de_uma_linha_so(self):
        self.assertNotIn("\n", linha_de_lote("id-42", "p", IMG, "image/png"))

    def test_resultado_volta_indexado_pela_chave(self):
        bruto = "\n".join([
            json.dumps({"key": "a", "response": {"candidates": [
                {"content": {"parts": [{"text": '{"caption": "primeira"}'}]}}]}}),
            json.dumps({"key": "b", "response": {"candidates": [
                {"content": {"parts": [{"text": '{"caption": "segunda"}'}]}}]}}),
        ])
        r = ler_resultado_de_lote(bruto)
        self.assertEqual(r["a"]["caption"], "primeira")
        self.assertEqual(r["b"]["caption"], "segunda")

    def test_item_que_falhou_no_lote_nao_derruba_os_outros(self):
        bruto = "\n".join([
            json.dumps({"key": "a", "error": {"message": "quota"}}),
            json.dumps({"key": "b", "response": {"candidates": [
                {"content": {"parts": [{"text": '{"caption": "ok"}'}]}}]}}),
        ])
        r = ler_resultado_de_lote(bruto)
        self.assertNotIn("a", r)
        self.assertEqual(r["b"]["caption"], "ok")

    def test_linha_em_branco_no_meio_do_lote_e_ignorada(self):
        bruto = '\n\n{"key": "b", "response": {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}}\n\n'
        self.assertEqual(list(ler_resultado_de_lote(bruto)), ["b"])


if __name__ == "__main__":
    unittest.main()
