"""Descrição por VLM: prompt, parsing e a fusão com o que já se sabia de graça."""
import unittest
from lupa.caption import montar_prompt, parse_resposta, mesclar, estimar_custo, RespostaInvalida

META_FOTO = {"file": "mesa.jpg", "kind": "foto", "medium": "na", "source": "camera",
             "has_text": False, "aspect": "3:2", "orientation": "paisagem",
             "ocr_text": "", "labels": []}
META_AMBIGUA = {"file": "banner.jpg", "kind": None, "medium": None, "source": "camera",
                "has_text": True, "aspect": "3:2", "orientation": "paisagem",
                "ocr_text": "PROMOÇÃO", "labels": []}

VLM = {"caption": "Mesa de madeira com pão", "tags": ["Comida", "MADEIRA", "comida"],
       "scene": "interior", "people": 0, "palette": ["#c8a06a"],
       "kind": "peca", "medium": "digital"}


class TestPrompt(unittest.TestCase):
    def test_proibe_explicitamente_transcrever_porque_o_drive_ja_deu_o_ocr(self):
        p = montar_prompt(META_FOTO).lower()
        self.assertIn("não transcreva", p)

    def test_nao_gasta_o_modelo_pedindo_lista_de_objetos(self):
        # os labels do Google já vêm de graça; pedir de novo é pagar duas vezes
        p = montar_prompt(META_FOTO).lower()
        self.assertNotIn("liste os objetos", p)
        self.assertNotIn("identifique os objetos", p)

    def test_pede_json_e_lista_a_taxonomia_fechada(self):
        p = montar_prompt(META_AMBIGUA)
        self.assertIn("JSON", p)
        for k in ("foto", "peca", "captura", "grafico", "logo", "outro"):
            self.assertIn(k, p)

    def test_quando_o_tipo_ja_e_conhecido_o_prompt_nao_pergunta_de_novo(self):
        self.assertNotIn("kind", montar_prompt(META_FOTO))

    def test_quando_o_tipo_e_ambiguo_o_prompt_pergunta(self):
        self.assertIn("kind", montar_prompt(META_AMBIGUA))


class TestParse(unittest.TestCase):
    def test_json_limpo(self):
        self.assertEqual(parse_resposta('{"caption": "oi"}')["caption"], "oi")

    def test_json_dentro_de_cerca_markdown(self):
        self.assertEqual(parse_resposta('```json\n{"caption": "oi"}\n```')["caption"], "oi")

    def test_json_com_texto_em_volta(self):
        self.assertEqual(parse_resposta('Claro!\n{"caption": "oi"}\nEspero ter ajudado')["caption"], "oi")

    def test_resposta_sem_json_levanta_erro_claro(self):
        with self.assertRaises(RespostaInvalida):
            parse_resposta("desculpe, não consigo ver a imagem")


class TestMesclagem(unittest.TestCase):
    def test_o_deterministico_vence_o_modelo(self):
        # metadado disse foto/na; o VLM chutou peca/digital e deve ser ignorado
        r = mesclar(META_FOTO, VLM)
        self.assertEqual(r["kind"], "foto")
        self.assertEqual(r["medium"], "na")

    def test_o_modelo_preenche_o_que_o_metadado_nao_sabia(self):
        r = mesclar(META_AMBIGUA, VLM)
        self.assertEqual(r["kind"], "peca")
        self.assertEqual(r["medium"], "digital")

    def test_kind_invento_do_modelo_vira_outro(self):
        r = mesclar(META_AMBIGUA, dict(VLM, kind="fotografia-artistica"))
        self.assertEqual(r["kind"], "outro")

    def test_medium_invento_do_modelo_vira_na(self):
        r = mesclar(META_AMBIGUA, dict(VLM, medium="impresso-digital"))
        self.assertEqual(r["medium"], "na")

    def test_tags_ficam_minusculas_e_sem_repeticao(self):
        self.assertEqual(sorted(mesclar(META_FOTO, VLM)["tags"]), ["comida", "madeira"])

    def test_o_ocr_do_drive_entra_no_campo_text(self):
        r = mesclar(META_AMBIGUA, VLM)
        self.assertEqual(r["text"], "PROMOÇÃO")

    def test_caption_ausente_no_modelo_nao_quebra(self):
        self.assertEqual(mesclar(META_FOTO, {})["caption"], "")


class TestCusto(unittest.TestCase):
    def test_lote_em_batch_custa_menos_que_sincrono(self):
        self.assertLess(estimar_custo(1000, batch=True), estimar_custo(1000, batch=False))

    def test_mil_imagens_custam_centavos(self):
        self.assertLess(estimar_custo(1000, batch=True), 0.50)

    def test_acervo_vazio_custa_zero(self):
        self.assertEqual(estimar_custo(0, batch=True), 0.0)


if __name__ == "__main__":
    unittest.main()


class TestFormatoDoCusto(unittest.TestCase):
    def test_valor_minusculo_nao_vira_notacao_cientifica(self):
        from lupa.caption import formatar_custo
        self.assertNotIn("e-", formatar_custo(0.00007))

    def test_valor_abaixo_de_um_centavo_e_dito_por_extenso(self):
        from lupa.caption import formatar_custo
        self.assertIn("menos de", formatar_custo(0.00007))

    def test_valor_normal_sai_com_duas_casas(self):
        from lupa.caption import formatar_custo
        self.assertEqual(formatar_custo(1.234), "US$ 1.23")

    def test_zero_e_dito_como_zero(self):
        from lupa.caption import formatar_custo
        self.assertIn("0", formatar_custo(0))
