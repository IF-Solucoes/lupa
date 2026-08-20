"""Orquestração dos verbos. Sem rede aqui: fonte e modelo entram injetados.

É esta separação que torna o ciclo testável de ponta a ponta sem credencial —
e é ela que garante que o incremental seja verificável, não prometido.
"""
import json
from pathlib import Path

from lupa.build import escrever_indice, fazer_backup
from lupa.caption import estimar_custo, mesclar
from lupa.classify import classify
from lupa.guards import Lock, checar_antes_de_indexar
from lupa.reconcile import reconcile


def _carregar_manifesto(index_dir):
    caminho = Path(index_dir) / "MANIFEST.json"
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"itens": {}}


def _carregar_catalogo(index_dir):
    """Descrições já pagas. Elas sobrevivem às rodadas seguintes."""
    caminho = Path(index_dir) / "catalog.jsonl"
    if not caminho.exists():
        return {}
    guardados = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha:
            try:
                item = json.loads(linha)
                guardados[item["id"]] = item
            except (json.JSONDecodeError, KeyError):
                continue
    return guardados


def rodar(acervo, index_dir, fonte, descrever, modo="update", agora="",
          dry_run=False, rebuild=False, confirm=None, batch=True):
    """Executa uma rodada completa.

    fonte     — objeto com .listar() e .baixar(file_id) -> (bytes, mime)
    descrever — callable(item, bytes, mime) -> dicionário do modelo de visão
    modo      — "index" (primeira vez) ou "update" (incremental)
    """
    index_dir = Path(index_dir)

    if modo == "index":
        checar_antes_de_indexar(index_dir, acervo=acervo, rebuild=rebuild, confirm=confirm)

    remoto = fonte.listar()
    manifesto = _carregar_manifesto(index_dir)
    plano = reconcile(remoto, manifesto)
    custo = estimar_custo(len(plano.a_descrever), batch=batch)

    if dry_run:
        return {"plano": plano, "custo_estimado": custo, "falhas": [], "escrito": False}

    if rebuild:
        fazer_backup(index_dir, agora=agora)

    index_dir.mkdir(parents=True, exist_ok=True)
    with Lock(index_dir):
        guardados = _carregar_catalogo(index_dir)
        por_id = {f["id"]: f for f in remoto}
        a_descrever = set(plano.a_descrever)
        itens, falhas = [], []

        for fid in plano.novas + plano.alteradas + plano.intactas:
            bruto = por_id[fid]

            if fid not in a_descrever:      # intacta: reaproveita o que já foi pago
                itens.append(guardados[fid])
                continue

            meta = {**bruto, **classify(bruto)}
            try:
                imagem, mime = fonte.baixar(fid)
                resposta = descrever(bruto, imagem, mime)
            except Exception as erro:       # uma imagem ruim não derruba a rodada
                falhas.append({"id": fid, "file": bruto.get("file"), "erro": str(erro)})
                continue
            itens.append(mesclar(meta, resposta))

        manifesto_novo = escrever_indice(
            index_dir, acervo=acervo, itens=itens, resumo=plano.resumo(),
            modelo="gemini-2.5-flash-lite", custo_usd=custo, agora=agora)

        if falhas:
            (index_dir / "runs" / f"{str(agora).replace(':', '-')}.errors.jsonl").write_text(
                "\n".join(json.dumps(f, ensure_ascii=False) for f in falhas) + "\n",
                encoding="utf-8")

    return {"plano": plano, "custo_estimado": custo, "falhas": falhas,
            "escrito": True, "manifesto": manifesto_novo, "total": len(itens)}
