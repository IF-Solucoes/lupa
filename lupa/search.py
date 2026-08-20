"""Busca sobre o catálogo já indexado. Sem rede, sem modelo, sem embeddings.

A consulta é textual e os filtros são exatos. O resultado vem com `_score` e
`_motivo` — o consumidor precisa saber POR QUE algo casou para confiar na lista.
"""
import unicodedata

LIMITE_PADRAO = 15

# Onde o termo casou importa: uma tag é curadoria, o OCR é acidente.
PESOS = {"tags": 5, "caption": 3, "file": 2, "labels": 1, "text": 1}


def _normalizar(texto):
    """Caixa baixa e sem acento, dos dois lados da comparação."""
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).lower()


def _campos(item):
    return {
        "tags": " ".join(item.get("tags") or []),
        "caption": item.get("caption") or "",
        "file": item.get("file") or "",
        "labels": " ".join(item.get("labels") or []),
        "text": item.get("text") or "",
    }


def _passa_nos_filtros(item, filtros):
    return all(item.get(chave) == valor for chave, valor in (filtros or {}).items())


def _pontuar(item, termos):
    """Soma os pesos de cada campo onde algum termo aparece."""
    campos = {nome: _normalizar(valor) for nome, valor in _campos(item).items()}
    score, motivos, casados = 0, [], set()

    for termo in termos:
        for nome, conteudo in campos.items():
            if termo in conteudo:
                score += PESOS[nome]
                motivos.append(f"{nome}:{termo}")
                casados.add(termo)

    # Casar mais termos distintos vale mais do que casar um termo em vários campos.
    score += 10 * len(casados)
    return score, motivos, casados


def search(catalogo, consulta, filtros=None, limite=LIMITE_PADRAO):
    """Devolve até `limite` itens ordenados por relevância, cada um com _score/_motivo."""
    termos = [_normalizar(t) for t in str(consulta).split() if t.strip()]
    resultados = []

    for item in catalogo:
        if not _passa_nos_filtros(item, filtros):
            continue

        if not termos:  # filtro puro: lista tudo que passou
            resultados.append(dict(item, _score=0, _motivo="filtro"))
            continue

        score, motivos, casados = _pontuar(item, termos)
        if len(casados) < len(termos) and not casados:
            continue
        if score:
            resultados.append(dict(item, _score=score, _motivo=", ".join(motivos)))

    resultados.sort(key=lambda r: (-r["_score"], r.get("id", "")))
    return resultados[:limite]
