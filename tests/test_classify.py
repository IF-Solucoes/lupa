"""Classificação determinística: o que dá para decidir sem gastar IA."""
import unittest
from lupa.classify import classify


class TestAspectoEOrientacao(unittest.TestCase):
    def test_post_de_feed_e_retrato_quatro_por_cinco(self):
        r = classify({"w": 1080, "h": 1350})
        self.assertEqual(r["aspect"], "4:5")
        self.assertEqual(r["orientation"], "retrato")

    def test_story_e_nove_por_dezesseis(self):
        self.assertEqual(classify({"w": 1080, "h": 1920})["aspect"], "9:16")

    def test_foto_de_camera_e_tres_por_dois_paisagem(self):
        r = classify({"w": 6000, "h": 4000})
        self.assertEqual(r["aspect"], "3:2")
        self.assertEqual(r["orientation"], "paisagem")

    def test_quadrado(self):
        r = classify({"w": 1080, "h": 1080})
        self.assertEqual(r["aspect"], "1:1")
        self.assertEqual(r["orientation"], "quadrado")


class TestOrigem(unittest.TestCase):
    def test_exif_de_camera_marca_como_capturado(self):
        r = classify({"w": 4032, "h": 3024, "exif": {"Make": "Apple", "Model": "iPhone 15"}})
        self.assertEqual(r["source"], "camera")

    def test_sem_exif_marca_como_gerado(self):
        self.assertEqual(classify({"w": 1080, "h": 1350, "mime": "image/png"})["source"], "gerado")


class TestTextoNaImagem(unittest.TestCase):
    def test_ocr_longo_liga_has_text(self):
        r = classify({"w": 1080, "h": 1350, "ocr_text": "MIGRAÇÃO " * 30})
        self.assertTrue(r["has_text"])

    def test_ocr_vazio_desliga_has_text(self):
        self.assertFalse(classify({"w": 4032, "h": 3024, "ocr_text": ""})["has_text"])

    def test_ocr_residual_nao_conta_como_texto(self):
        # duas palavras soltas são ruído de OCR, não peça gráfica
        self.assertFalse(classify({"w": 4032, "h": 3024, "ocr_text": "Sony A7"})["has_text"])


class TestKindDeterministico(unittest.TestCase):
    def test_camera_sem_texto_e_foto(self):
        r = classify({"w": 4032, "h": 3024, "exif": {"Make": "Canon"}, "ocr_text": ""})
        self.assertEqual(r["kind"], "foto")
        self.assertEqual(r["medium"], "na")

    def test_png_gerado_com_muito_texto_e_peca_digital(self):
        r = classify({"w": 1080, "h": 1350, "mime": "image/png", "ocr_text": "CRITÉRIO " * 40})
        self.assertEqual(r["kind"], "peca")
        self.assertEqual(r["medium"], "digital")

    def test_caso_ambiguo_devolve_none_para_o_vlm_decidir(self):
        # foto de câmera COM muito texto: pode ser peça impressa fotografada
        r = classify({"w": 4032, "h": 3024, "exif": {"Make": "Canon"}, "ocr_text": "PROMOÇÃO " * 40})
        self.assertIsNone(r["kind"])


if __name__ == "__main__":
    unittest.main()
