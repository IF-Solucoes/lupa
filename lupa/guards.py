"""Guarda-corpos. Refazer um índice custa dinheiro e apaga histórico.

Regra: o verbo `index` nunca sobrescreve. Ele detecta o índice existente e
manda o usuário para o `update`. Refazer exige intenção digitada.
"""
import json
import os
import time
from pathlib import Path

IDADE_MAXIMA_LOCK_S = 30 * 60  # meia hora: acima disso, o dono do lock sumiu


class IndiceJaExiste(Exception):
    pass


class LockOcupado(Exception):
    pass


def checar_antes_de_indexar(index_dir, acervo, rebuild=False, confirm=None):
    """Levanta IndiceJaExiste a menos que o acervo seja virgem, ou que o
    usuário tenha digitado o nome exato junto de --rebuild."""
    manifesto = Path(index_dir) / "MANIFEST.json"
    if not manifesto.exists():
        return

    if rebuild and confirm == acervo:
        return

    try:
        dados = json.loads(manifesto.read_text())
    except (json.JSONDecodeError, OSError):
        dados = {}
    total = dados.get("total", "?")
    rodadas = dados.get("rodadas", "?")

    if not rebuild:
        raise IndiceJaExiste(
            f"Este acervo já tem índice: {total} imagens, {rodadas} rodadas.\n"
            f"  Você provavelmente quer:  lupa update {acervo}\n"
            f'  Para refazer do zero:     lupa index {acervo} --rebuild --confirm "{acervo}"'
        )
    raise IndiceJaExiste(
        f'Refazer o índice apaga {rodadas} rodadas de histórico de "{acervo}".\n'
        f'  Confirme digitando o nome do acervo:  --confirm "{acervo}"'
    )


def precisa_confirmar_custo(quantidade, teto):
    """True quando a rodada vai descrever mais imagens do que o teto permite
    sem perguntar. Teto 0 desliga a checagem."""
    return bool(teto) and quantidade > teto


class Lock:
    """Impede que duas execuções embaralhem o manifesto. Lock órfão é reciclado."""

    def __init__(self, index_dir):
        self.caminho = Path(index_dir) / ".lock"

    def __enter__(self):
        if self.caminho.exists() and not self._orfao():
            raise LockOcupado(
                f"Outra execução está usando este índice ({self.caminho}). "
                "Espere ela terminar, ou apague o arquivo se tiver certeza."
            )
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho.write_text(json.dumps({"pid": os.getpid(), "iniciado": time.time()}))
        return self

    def __exit__(self, *_):
        self.caminho.unlink(missing_ok=True)
        return False

    def _orfao(self):
        try:
            iniciado = json.loads(self.caminho.read_text()).get("iniciado", 0)
        except (json.JSONDecodeError, OSError):
            return True  # lock ilegível é lock morto
        return (time.time() - iniciado) > IDADE_MAXIMA_LOCK_S
