"""Escrita do índice. Estes arquivos são o contrato com quem consome.

Três níveis de leitura, do barato ao caro:
  INDEX.md      → sempre (~2 KB)
  by-tag/*.md   → só as tags relevantes
  catalog.jsonl → só quando precisa cruzar campos
"""
import json
import shutil
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA_VERSAO = 1


def nome_de_arquivo_de_tag(tag):
    """Tag vira nome de arquivo seguro em qualquer sistema de arquivos."""
    sem_acento = unicodedata.normalize("NFKD", str(tag))
    limpo = "".join(c for c in sem_acento if not unicodedata.combining(c)).lower()
    return "-".join(limpo.replace("/", " ").replace("_", " ").split())


def fazer_backup(index_dir, agora):
    """Copia o índice atual para .backup/<agora>/ antes de uma escrita destrutiva."""
    origem = Path(index_dir)
    if not (origem / "MANIFEST.json").exists():
        return None
    destino = origem / ".backup" / str(agora)
    destino.mkdir(parents=True, exist_ok=True)
    for item in origem.iterdir():
        if item.name == ".backup":
            continue
        alvo = destino / item.name
        if item.is_dir():
            shutil.copytree(item, alvo, dirs_exist_ok=True)
        else:
            shutil.copy2(item, alvo)
    return destino


def _escrever_catalogo(index_dir, itens):
    linhas = [json.dumps(dict(i, v=SCHEMA_VERSAO), ensure_ascii=False) for i in itens]
    (index_dir / "catalog.jsonl").write_text("\n".join(linhas) + "\n", encoding="utf-8")


def _escrever_by_tag(index_dir, itens):
    """Índice invertido em Markdown — permite busca sem executar código."""
    pasta = index_dir / "by-tag"
    pasta.mkdir(exist_ok=True)

    por_tag = defaultdict(list)
    for item in itens:
        for tag in item.get("tags") or []:
            por_tag[nome_de_arquivo_de_tag(tag)].append(item)

    for obsoleto in pasta.glob("*.md"):  # tag que sumiu não deixa arquivo órfão
        if obsoleto.stem not in por_tag:
            obsoleto.unlink()

    for tag, membros in por_tag.items():
        linhas = [f"# {tag} — {len(membros)} imagens", ""]
        linhas += ["| arquivo | tipo | orientação | descrição | link |",
                   "|---|---|---|---|---|"]
        for m in sorted(membros, key=lambda x: x.get("file", "")):
            tipo = f"{m.get('kind') or '?'}/{m.get('medium') or '?'}"
            linhas.append(
                f"| {m.get('file')} | {tipo} | {m.get('orientation')} | "
                f"{m.get('caption', '')} | {m.get('url', '')} |")
        (pasta / f"{tag}.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")


def _escrever_index_md(index_dir, acervo, itens, agora, modelo):
    tags = Counter(t for i in itens for t in (i.get("tags") or []))
    kinds = Counter(i.get("kind") or "indefinido" for i in itens)
    mediums = Counter(i.get("medium") or "indefinido" for i in itens)

    vocabulario = " · ".join(f"`{t}` ({n})" for t, n in tags.most_common(40))
    por_kind = " · ".join(f"{k}: {n}" for k, n in kinds.most_common())
    por_medium = " · ".join(f"{m}: {n}" for m, n in mediums.most_common())

    texto = f"""# Índice visual — {acervo}

**{len(itens)} imagens** · atualizado em {agora} · descrito por `{modelo}` · schema v{SCHEMA_VERSAO}

> **Leia texto, nunca pixels.** Este índice existe para que você NÃO precise abrir
> as imagens. Abrir imagem custa caro e é o que este arquivo evita. Se precisar
> confirmar visualmente, abra apenas os finalistas que a busca devolveu.

## O que tem aqui

- **Por tipo:** {por_kind}
- **Por material:** {por_medium}

`kind`: foto · peca · captura · grafico · logo · outro
`medium`: fisico · digital · na — um mockup impresso é `peca` + `fisico`.

## Vocabulário

{vocabulario}

## Como consultar

1. **Achou a tag acima?** Leia `by-tag/<tag>.md`. É uma tabela pronta, com link. Pare aqui.
2. **Precisa cruzar campos** (tipo + orientação + sem texto)? Filtre `catalog.jsonl`.
   Uma linha por imagem, JSON, campos em `schema/index-v1.json`.
3. **Tem o MCP do lupa?** Chame `lupa_search` e receba os finalistas já ranqueados.

## Arquivos

| arquivo | para quê |
|---|---|
| `INDEX.md` | este mapa — leia sempre primeiro |
| `by-tag/*.md` | índice invertido, leitura barata sem código |
| `catalog.jsonl` | uma linha por imagem, para filtrar por campo |
| `contact-sheets/` | grades visuais, para curadoria humana |
| `MANIFEST.json` | estado interno: hashes que tornam a atualização incremental |
| `runs/` | o que cada rodada mudou |
"""
    (index_dir / "INDEX.md").write_text(texto, encoding="utf-8")


def _escrever_manifesto(index_dir, acervo, itens, modelo, agora):
    caminho = index_dir / "MANIFEST.json"
    rodadas = 0
    if caminho.exists():
        try:
            rodadas = json.loads(caminho.read_text()).get("rodadas", 0)
        except (json.JSONDecodeError, OSError):
            rodadas = 0

    manifesto = {
        "acervo": acervo,
        "schema": SCHEMA_VERSAO,
        "total": len(itens),
        "rodadas": rodadas + 1,
        "atualizado_em": agora,
        "modelo": modelo,
        "itens": {i["id"]: {"hash": i.get("hash"), "file": i.get("file")} for i in itens},
    }
    caminho.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifesto


def _escrever_relatorio(index_dir, acervo, itens, resumo, custo_usd, modelo, agora):
    pasta = index_dir / "runs"
    pasta.mkdir(exist_ok=True)
    nome = str(agora).replace(":", "-")
    texto = f"""# Rodada {agora} · acervo "{acervo}"

Total no acervo: {len(itens)} imagens

{resumo}

Custo estimado: US$ {custo_usd} · modelo: {modelo}
"""
    (pasta / f"{nome}.md").write_text(texto, encoding="utf-8")


def escrever_indice(index_dir, acervo, itens, resumo, modelo, custo_usd, agora):
    """Escreve todos os artefatos do índice. Idempotente: reescreve o conjunto."""
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    itens = sorted(itens, key=lambda i: i.get("file", ""))

    _escrever_catalogo(index_dir, itens)
    _escrever_by_tag(index_dir, itens)
    _escrever_index_md(index_dir, acervo, itens, agora, modelo)
    _escrever_relatorio(index_dir, acervo, itens, resumo, custo_usd, modelo, agora)
    return _escrever_manifesto(index_dir, acervo, itens, modelo, agora)
