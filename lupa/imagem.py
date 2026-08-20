"""Leitura de cabeçalho de imagem — só o suficiente para saber tamanho e tipo.

Sem Pillow de propósito: o núcleo do lupa não deve exigir instalação para
funcionar sobre uma pasta local.
"""
import struct

ASSINATURAS = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),
    (b"BM", "image/bmp"),
)

POR_EXTENSAO = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
    "heic": "image/heic", "tif": "image/tiff", "tiff": "image/tiff",
}

# Marcadores JPEG que carregam as dimensões (SOF), fora dos SOF diferenciais.
SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def mime_de(dados, nome=""):
    """O conteúdo manda; a extensão é o plano B."""
    for assinatura, mime in ASSINATURAS:
        if dados.startswith(assinatura):
            if assinatura == b"RIFF" and dados[8:12] != b"WEBP":
                continue
            return mime
    extensao = str(nome).rsplit(".", 1)[-1].lower()
    return POR_EXTENSAO.get(extensao, "application/octet-stream")


def _png(dados):
    return struct.unpack(">II", dados[16:24])


def _gif(dados):
    return struct.unpack("<HH", dados[6:10])


def _webp(dados):
    if dados[12:16] == b"VP8X":
        largura = int.from_bytes(dados[24:27], "little") + 1
        altura = int.from_bytes(dados[27:30], "little") + 1
        return largura, altura
    if dados[12:16] == b"VP8 ":
        return struct.unpack("<HH", dados[26:30])
    if dados[12:16] == b"VP8L":
        bits = int.from_bytes(dados[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise ValueError("webp sem cabeçalho conhecido")


def _jpeg(dados):
    i, limite = 2, len(dados)
    while i < limite - 9:
        if dados[i] != 0xFF:
            i += 1
            continue
        marcador = dados[i + 1]
        if marcador in SOF:
            altura, largura = struct.unpack(">HH", dados[i + 5:i + 9])
            return largura, altura
        if marcador in (0xD8, 0xD9) or 0xD0 <= marcador <= 0xD7:
            i += 2
            continue
        tamanho = struct.unpack(">H", dados[i + 2:i + 4])[0]
        i += 2 + tamanho
    raise ValueError("jpeg sem marcador SOF")


def dimensoes(dados):
    """(largura, altura) — (0, 0) quando o formato é desconhecido ou o arquivo está truncado."""
    if not dados:
        return 0, 0
    try:
        if dados.startswith(b"\x89PNG\r\n\x1a\n"):
            return _png(dados)
        if dados.startswith((b"GIF87a", b"GIF89a")):
            return _gif(dados)
        if dados.startswith(b"RIFF") and dados[8:12] == b"WEBP":
            return _webp(dados)
        if dados.startswith(b"\xff\xd8"):
            return _jpeg(dados)
    except (struct.error, ValueError, IndexError):
        return 0, 0
    return 0, 0


# --- EXIF mínimo: só Make e Model ---
# É o bastante para separar "foi capturado por uma câmera" de "foi gerado num
# editor". Ler a tabela EXIF inteira exigiria uma dependência que não se paga.

TAG_MAKE = 0x010F
TAG_MODEL = 0x0110
TIPO_STRING = 2


def _achar_app1(dados):
    """Localiza o bloco Exif dentro do JPEG."""
    i, limite = 2, len(dados)
    while i < limite - 4:
        if dados[i] != 0xFF:
            i += 1
            continue
        marcador = dados[i + 1]
        if marcador == 0xE1 and dados[i + 4:i + 10] == b"Exif\x00\x00":
            return i + 10
        if marcador in (0xD8, 0xD9) or 0xDA == marcador:
            return None
        tamanho = struct.unpack(">H", dados[i + 2:i + 4])[0]
        i += 2 + tamanho
    return None


def exif_camera(dados):
    """{'Make': ..., 'Model': ...} — vazio quando não há EXIF de câmera."""
    if not dados or not dados.startswith(b"\xff\xd8"):
        return {}
    try:
        base = _achar_app1(dados)
        if base is None:
            return {}

        ordem = dados[base:base + 2]
        if ordem not in (b"MM", b"II"):
            return {}
        fmt = ">" if ordem == b"MM" else "<"

        offset_ifd = struct.unpack(fmt + "I", dados[base + 4:base + 8])[0]
        pos = base + offset_ifd
        quantas = struct.unpack(fmt + "H", dados[pos:pos + 2])[0]
        pos += 2

        achados = {}
        for _ in range(quantas):
            tag, tipo, quantidade, valor = struct.unpack(fmt + "HHII", dados[pos:pos + 12])
            pos += 12
            if tag not in (TAG_MAKE, TAG_MODEL) or tipo != TIPO_STRING:
                continue
            if quantidade <= 4:  # cabe no próprio campo do offset
                cru = struct.pack(fmt + "I", valor)[:quantidade]
            else:
                cru = dados[base + valor:base + valor + quantidade]
            texto = cru.split(b"\x00")[0].decode("utf-8", errors="replace").strip()
            if texto:
                achados["Make" if tag == TAG_MAKE else "Model"] = texto
        return achados
    except (struct.error, ValueError, IndexError, UnicodeDecodeError):
        return {}
