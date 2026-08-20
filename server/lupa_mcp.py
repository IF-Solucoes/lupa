#!/usr/bin/env python3
"""Entrada do servidor MCP do lupa — transporte stdio, JSON por linha.

Zero dependências: sobe em qualquer máquina onde o cliente MCP rode, sem venv,
sem instalação, sem bootstrap. Só lê índices já escritos.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lupa.config import ler_env, resolver_raiz_indices  # noqa: E402
from lupa.mcp import Servidor  # noqa: E402


def main():
    raiz = resolver_raiz_indices(os.environ, ler_env())
    servidor = Servidor(raiz)

    for linha in sys.stdin:
        linha = linha.strip()
        if not linha:
            continue
        try:
            pedido = json.loads(linha)
        except json.JSONDecodeError:
            continue

        resposta = servidor.despachar(pedido)
        if resposta is not None:
            sys.stdout.write(json.dumps(resposta, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
