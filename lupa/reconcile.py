"""Reconciliação incremental entre o acervo remoto e o que já foi indexado.

Cada imagem é descrita uma vez na vida. O que a rodada seguinte faz é comparar
identificadores e hashes — operação de metadado, sem baixar bytes nem gastar IA.
"""
from dataclasses import dataclass, field


@dataclass
class Plano:
    novas: list = field(default_factory=list)
    alteradas: list = field(default_factory=list)
    sumidas: list = field(default_factory=list)
    intactas: list = field(default_factory=list)

    @property
    def a_descrever(self) -> list:
        """Ids que custam uma chamada ao modelo de visão."""
        return self.novas + self.alteradas

    @property
    def vazio(self) -> bool:
        """True quando não há nada a fazer — nem descrever, nem reescrever."""
        return not (self.novas or self.alteradas or self.sumidas)

    def resumo(self) -> str:
        return (f"+{len(self.novas)} novas · ~{len(self.alteradas)} alteradas · "
                f"-{len(self.sumidas)} removidas · ={len(self.intactas)} intactas")


def reconcile(remoto: list, manifesto: dict) -> Plano:
    """remoto: [{id, hash, name, trashed?}] · manifesto: {"itens": {id: {hash}}}"""
    indexado = manifesto.get("itens", {})
    vivos = {f["id"]: f for f in remoto if not f.get("trashed")}
    plano = Plano()

    for fid, f in vivos.items():
        anterior = indexado.get(fid)
        if anterior is None:
            plano.novas.append(fid)
        elif anterior.get("hash") != f.get("hash"):
            plano.alteradas.append(fid)
        else:
            plano.intactas.append(fid)

    plano.sumidas = [fid for fid in indexado if fid not in vivos]
    return plano
