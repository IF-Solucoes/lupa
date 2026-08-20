"""Reconciliação incremental: o que mudou desde a última rodada."""
import unittest
from lupa.reconcile import reconcile


def remoto(*pares):
    return [{"id": i, "hash": h, "name": f"{i}.png"} for i, h in pares]


def manifesto(*pares):
    return {"itens": {i: {"hash": h} for i, h in pares}}


class TestReconcile(unittest.TestCase):
    def test_acervo_novo_e_tudo_novo(self):
        p = reconcile(remoto(("a", "1"), ("b", "2")), {"itens": {}})
        self.assertEqual(sorted(p.novas), ["a", "b"])
        self.assertEqual(p.alteradas, [])
        self.assertEqual(p.sumidas, [])

    def test_sem_mudanca_nao_ha_nada_a_fazer(self):
        r, m = remoto(("a", "1"), ("b", "2")), manifesto(("a", "1"), ("b", "2"))
        p = reconcile(r, m)
        self.assertEqual(sorted(p.intactas), ["a", "b"])
        self.assertEqual(p.a_descrever, [])
        self.assertTrue(p.vazio)

    def test_arquivo_novo_entra_sozinho(self):
        p = reconcile(remoto(("a", "1"), ("b", "2")), manifesto(("a", "1")))
        self.assertEqual(p.novas, ["b"])
        self.assertEqual(p.intactas, ["a"])

    def test_hash_diferente_marca_como_alterada(self):
        p = reconcile(remoto(("a", "9")), manifesto(("a", "1")))
        self.assertEqual(p.alteradas, ["a"])
        self.assertEqual(p.novas, [])

    def test_arquivo_ausente_no_drive_e_removido(self):
        p = reconcile(remoto(("a", "1")), manifesto(("a", "1"), ("z", "8")))
        self.assertEqual(p.sumidas, ["z"])

    def test_arquivo_na_lixeira_conta_como_sumido(self):
        r = [{"id": "a", "hash": "1", "name": "a.png", "trashed": True}]
        p = reconcile(r, manifesto(("a", "1")))
        self.assertEqual(p.sumidas, ["a"])
        self.assertEqual(p.intactas, [])

    def test_a_descrever_junta_novas_e_alteradas(self):
        p = reconcile(remoto(("a", "9"), ("b", "2")), manifesto(("a", "1")))
        self.assertEqual(sorted(p.a_descrever), ["a", "b"])
        self.assertFalse(p.vazio)

    def test_remocao_sozinha_nao_e_rodada_vazia(self):
        # nada a descrever, mas o catálogo precisa ser reescrito
        p = reconcile(remoto(("a", "1")), manifesto(("a", "1"), ("z", "8")))
        self.assertEqual(p.a_descrever, [])
        self.assertFalse(p.vazio)


if __name__ == "__main__":
    unittest.main()
