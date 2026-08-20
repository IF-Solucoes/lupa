"""Descrição por modelo de visão.

O modelo só é perguntado sobre o que o metadado não resolveu. Ele nunca
transcreve texto (o Drive já fez OCR de graça) nem redefine o que já se sabe.
"""
import json
import re

KINDS = ("foto", "peca", "captura", "grafico", "logo", "outro")
MEDIUMS = ("fisico", "digital", "na")

# Gemini 2.5 Flash-Lite, preço por 1M de tokens. Batch corta 50%.
PRECO_ENTRADA = 0.10
PRECO_SAIDA = 0.40
TOKENS_ENTRADA_POR_IMAGEM = 600   # miniatura de 768px + prompt
TOKENS_SAIDA_POR_IMAGEM = 200


class RespostaInvalida(Exception):
    pass


def montar_prompt(meta):
    """Pergunta só o que falta. Prompt curto é prompt barato."""
    linhas = [
        "Você cataloga imagens para um acervo de referências visuais.",
        "Responda APENAS um objeto JSON, sem comentários e sem cercas de código.",
        "",
        "Campos obrigatórios:",
        '  "caption": uma frase objetiva descrevendo a imagem (máx. 20 palavras).',
        '  "tags": 3 a 8 termos curtos em português, minúsculos, sem acento.',
        '  "scene": "interior", "exterior" ou "na".',
        '  "people": número de pessoas visíveis (0 se nenhuma).',
        '  "palette": 2 a 4 cores dominantes em hexadecimal.',
    ]

    # Só perguntamos o tipo quando o metadado não decidiu sozinho.
    if meta.get("kind") is None:
        linhas += [
            f'  "kind": um de {list(KINDS)}.',
            '     foto = fotografia capturada · peca = arte/design finalizado',
            '     captura = screenshot de tela · grafico = diagrama ou slide',
            '     logo = marca isolada · outro = nenhum acima',
            f'  "medium": um de {list(MEDIUMS)}.',
            '     fisico = material impresso ou objeto real fotografado',
            '     digital = arte de tela · na = não se aplica',
        ]

    linhas += [
        "",
        "NÃO transcreva o texto da imagem — ele já foi extraído.",
        "Descreva composição, luz, cores e estilo. Seja concreto, não poético.",
    ]
    return "\n".join(linhas)


def parse_resposta(texto):
    """Extrai o JSON da resposta, tolerando cercas de código e conversa em volta."""
    if not texto:
        raise RespostaInvalida("resposta vazia do modelo")

    limpo = re.sub(r"```(?:json)?|```", "", str(texto)).strip()
    try:
        return json.loads(limpo)
    except json.JSONDecodeError:
        pass

    inicio, fim = limpo.find("{"), limpo.rfind("}")
    if inicio == -1 or fim <= inicio:
        raise RespostaInvalida(f"nenhum JSON na resposta: {limpo[:120]!r}")
    try:
        return json.loads(limpo[inicio:fim + 1])
    except json.JSONDecodeError as erro:
        raise RespostaInvalida(f"JSON malformado: {erro}") from erro


def _limpar_tags(brutas):
    vistas, saida = set(), []
    for tag in brutas or []:
        limpa = str(tag).strip().lower()
        if limpa and limpa not in vistas:
            vistas.add(limpa)
            saida.append(limpa)
    return saida


def mesclar(meta, vlm):
    """Funde metadado e modelo. O metadado vence sempre que já tinha resposta."""
    vlm = vlm or {}

    kind = meta.get("kind")
    if kind is None:
        kind = vlm.get("kind")
        kind = kind if kind in KINDS else "outro"

    medium = meta.get("medium")
    if medium is None:
        medium = vlm.get("medium")
        medium = medium if medium in MEDIUMS else "na"

    return {
        "id": meta.get("id"),
        "file": meta.get("file"),
        "url": meta.get("url"),
        "w": meta.get("w"), "h": meta.get("h"),
        "aspect": meta.get("aspect"), "orientation": meta.get("orientation"),
        "kind": kind, "medium": medium, "source": meta.get("source"),
        "caption": str(vlm.get("caption") or ""),
        "tags": _limpar_tags(vlm.get("tags")),
        "scene": vlm.get("scene") or "na",
        "people": int(vlm.get("people") or 0),
        "palette": list(vlm.get("palette") or []),
        "has_text": bool(meta.get("has_text")),
        "text": meta.get("ocr_text") or "",       # OCR do Drive, de graça
        "labels": list(meta.get("labels") or []),  # labels crus do Google
        "hash": meta.get("hash"),
    }


def estimar_custo(quantidade, batch=True):
    """Custo aproximado em dólares. Serve ao aviso antes de gastar, não à contabilidade."""
    if quantidade <= 0:
        return 0.0
    entrada = quantidade * TOKENS_ENTRADA_POR_IMAGEM / 1_000_000 * PRECO_ENTRADA
    saida = quantidade * TOKENS_SAIDA_POR_IMAGEM / 1_000_000 * PRECO_SAIDA
    total = entrada + saida
    return round(total * (0.5 if batch else 1.0), 6)


def formatar_custo(valor):
    """Custo para ler, não para contabilizar. Centavo de dólar não merece 6 casas."""
    if not valor:
        return "US$ 0.00"
    if valor < 0.01:
        return "menos de US$ 0.01"
    return f"US$ {valor:.2f}"
