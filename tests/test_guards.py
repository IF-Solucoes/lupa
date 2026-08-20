"""Guarda-corpos: o índice não se refaz por acidente."""
import time
import tempfile
import unittest
from pathlib import Path

from lupa.guards import (
    IndiceJaExiste, LockOcupado, checar_antes_de_indexar,
    precisa_confirmar_custo, Lock, IDADE_MAXIMA_LOCK_S,
)


class TestIndexNaoSobrescreve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _com_indice(self, total=3412):
        (self.dir / "MANIFEST.json").write_text(
            '{"acervo": "if-editorial", "total": %d, "rodadas": 6}' % total)

    def test_acervo_virgem_pode_indexar(self):
        checar_antes_de_indexar(self.dir, acervo="if-editorial")  # não levanta

    def test_acervo_ja_indexado_recusa(self):
        self._com_indice()
        with self.assertRaises(IndiceJaExiste):
            checar_antes_de_indexar(self.dir, acervo="if-editorial")

    def test_recusa_aponta_para_o_update(self):
        self._com_indice()
        with self.assertRaises(IndiceJaExiste) as ctx:
            checar_antes_de_indexar(self.dir, acervo="if-editorial")
        self.assertIn("lupa update", str(ctx.exception))

    def test_rebuild_sem_confirmacao_recusa(self):
        self._com_indice()
        with self.assertRaises(IndiceJaExiste):
            checar_antes_de_indexar(self.dir, acervo="if-editorial", rebuild=True)

    def test_rebuild_com_nome_errado_recusa(self):
        self._com_indice()
        with self.assertRaises(IndiceJaExiste):
            checar_antes_de_indexar(self.dir, acervo="if-editorial",
                                    rebuild=True, confirm="outro-acervo")

    def test_rebuild_com_nome_exato_passa(self):
        self._com_indice()
        checar_antes_de_indexar(self.dir, acervo="if-editorial",
                                rebuild=True, confirm="if-editorial")


class TestTetoDeCusto(unittest.TestCase):
    def test_abaixo_do_teto_segue_sem_perguntar(self):
        self.assertFalse(precisa_confirmar_custo(199, teto=200))

    def test_acima_do_teto_pede_confirmacao(self):
        self.assertTrue(precisa_confirmar_custo(201, teto=200))

    def test_teto_zero_desliga_a_pergunta(self):
        self.assertFalse(precisa_confirmar_custo(9999, teto=0))


class TestLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_segunda_execucao_simultanea_e_barrada(self):
        with Lock(self.dir):
            with self.assertRaises(LockOcupado):
                with Lock(self.dir):
                    pass

    def test_lock_e_liberado_ao_sair(self):
        with Lock(self.dir):
            pass
        with Lock(self.dir):  # não levanta
            pass

    def test_lock_orfao_e_reaproveitado(self):
        velho = time.time() - IDADE_MAXIMA_LOCK_S - 60
        (self.dir / ".lock").write_text('{"pid": 999999, "iniciado": %f}' % velho)
        with Lock(self.dir):  # não levanta: o dono sumiu faz tempo
            pass

    def test_lock_e_removido_mesmo_se_der_erro_dentro(self):
        with self.assertRaises(ValueError):
            with Lock(self.dir):
                raise ValueError("falha no meio da rodada")
        self.assertFalse((self.dir / ".lock").exists())


if __name__ == "__main__":
    unittest.main()
