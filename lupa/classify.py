"""Classificação determinística de uma imagem, a partir de metadados apenas.

Nada aqui gasta IA. O que o metadado não decide volta como None — e só esses
casos ambíguos custam uma opinião do modelo de visão.
"""
from math import gcd

# Proporções que importam. Ordem não conta; a tolerância abaixo resolve empates.
ASPECTOS = {
    (1, 1): "1:1", (4, 5): "4:5", (5, 4): "5:4", (9, 16): "9:16", (16, 9): "16:9",
    (2, 3): "2:3", (3, 2): "3:2", (3, 4): "3:4", (4, 3): "4:3",
}
TOLERANCIA = 0.02

# Abaixo disto, o OCR é ruído (marca d'água, plaquinha, nome de equipamento),
# não uma peça gráfica.
MIN_PALAVRAS_PARA_TEXTO = 5


def _aspecto(w: int, h: int) -> str:
    razao = w / h
    for (a, b), rotulo in ASPECTOS.items():
        if abs(razao - a / b) <= TOLERANCIA:
            return rotulo
    d = gcd(w, h)
    return f"{w // d}:{h // d}"


def _orientacao(w: int, h: int) -> str:
    if w == h:
        return "quadrado"
    return "paisagem" if w > h else "retrato"


def _tem_texto(ocr: str) -> bool:
    return len(ocr.split()) >= MIN_PALAVRAS_PARA_TEXTO


def classify(meta: dict) -> dict:
    """Recebe metadados de uma imagem, devolve o que dá para afirmar de graça.

    meta aceita: w, h, mime, exif {Make, Model}, ocr_text, name.
    kind/medium vêm None quando o metadado não basta — aí quem decide é o VLM.
    """
    w, h = int(meta["w"]), int(meta["h"])
    exif = meta.get("exif") or {}
    ocr = meta.get("ocr_text") or ""

    source = "camera" if (exif.get("Make") or exif.get("Model")) else "gerado"
    has_text = _tem_texto(ocr)

    kind = medium = None
    if source == "camera" and not has_text:
        kind, medium = "foto", "na"
    elif source == "gerado" and has_text:
        kind, medium = "peca", "digital"

    return {
        "w": w, "h": h,
        "aspect": _aspecto(w, h),
        "orientation": _orientacao(w, h),
        "source": source,
        "has_text": has_text,
        "kind": kind,
        "medium": medium,
    }
