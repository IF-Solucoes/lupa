#!/usr/bin/env python3
"""Valida um índice do lupa. Sai com 1 se algo estiver quebrado.

  python3 scripts/postcheck.py exemplo/_lupa
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OBRIGATORIOS = ("id", "file", "url", "kind", "medium", "caption", "tags", "hash", "v")
KINDS = ("foto", "peca", "captura", "grafico", "logo", "outro")
MEDIUMS = ("fisico", "digital", "na")


def checar(index_dir):
    index_dir = Path(index_dir)
    erros, avisos = [], []

    for nome in ("INDEX.md", "catalog.jsonl", "MANIFEST.json"):
        if not (index_dir / nome).exists():
            erros.append(f"falta {nome}")
    if erros:
        return erros, avisos

    itens, ids = [], set()
    for numero, linha in enumerate((index_dir / "catalog.jsonl").read_text(
            encoding="utf-8").splitlines(), start=1):
        linha = linha.strip()
        if not linha:
            continue
        try:
            item = json.loads(linha)
        except json.JSONDecodeError as erro:
            erros.append(f"catalog.jsonl linha {numero}: JSON inválido ({erro})")
            continue

        faltando = [c for c in OBRIGATORIOS if c not in item]
        if faltando:
            erros.append(f"linha {numero}: sem {', '.join(faltando)}")
        if item.get("kind") not in KINDS:
            erros.append(f"linha {numero}: kind fora da taxonomia ({item.get('kind')!r})")
        if item.get("medium") not in MEDIUMS:
            erros.append(f"linha {numero}: medium fora da taxonomia ({item.get('medium')!r})")
        if item.get("id") in ids:
            erros.append(f"linha {numero}: id repetido ({item.get('id')})")
        ids.add(item.get("id"))
        if not (item.get("caption") or "").strip():
            avisos.append(f"linha {numero}: caption vazia ({item.get('file')})")
        itens.append(item)

    manifesto = json.loads((index_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    if manifesto.get("total") != len(itens):
        erros.append(f"MANIFEST diz {manifesto.get('total')} itens, catálogo tem {len(itens)}")
    if set(manifesto.get("itens", {})) != ids:
        erros.append("MANIFEST e catálogo discordam sobre quais ids existem")

    texto_index = (index_dir / "INDEX.md").read_text(encoding="utf-8").lower()
    if "pixels" not in texto_index:
        erros.append("INDEX.md não avisa o agente para não abrir as imagens")

    tags_no_catalogo = {t for i in itens for t in (i.get("tags") or [])}
    if tags_no_catalogo and not (index_dir / "by-tag").exists():
        erros.append("há tags no catálogo mas não existe by-tag/")

    return erros, avisos


def main():
    alvo = sys.argv[1] if len(sys.argv) > 1 else "exemplo/_lupa"
    erros, avisos = checar(alvo)

    for aviso in avisos:
        print(f"  aviso: {aviso}")
    if erros:
        print(f"\nFALHOU — {len(erros)} problemas em {alvo}:")
        for erro in erros:
            print(f"  ✗ {erro}")
        sys.exit(1)
    print(f"PASS — índice válido em {alvo}"
          + (f" ({len(avisos)} avisos)" if avisos else ""))


if __name__ == "__main__":
    main()
