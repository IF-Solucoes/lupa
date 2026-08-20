"""Acervo numa pasta do disco. Mesma interface da fonte do Drive.

Não exige credencial, mas também não ganha o OCR de brinde — na pasta local o
modelo de visão trabalha um pouco mais.
"""
import hashlib
from pathlib import Path

from lupa.imagem import dimensoes, exif_camera, mime_de

EXTENSOES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic"}
PASTA_INDICE = "_lupa"
BYTES_DE_CABECALHO = 128 * 1024  # basta para dimensões e EXIF


class FonteLocal:
    def __init__(self, caminho):
        self.raiz = Path(caminho).expanduser().resolve()

    def _relevantes(self):
        for arquivo in sorted(self.raiz.rglob("*")):
            if not arquivo.is_file() or arquivo.suffix.lower() not in EXTENSOES:
                continue
            relativo = arquivo.relative_to(self.raiz)
            if any(parte.startswith((PASTA_INDICE, ".")) for parte in relativo.parts):
                continue
            yield arquivo, relativo

    def listar(self):
        achados = []
        for arquivo, relativo in self._relevantes():
            info = arquivo.stat()
            cabecalho = arquivo.open("rb").read(BYTES_DE_CABECALHO)
            largura, altura = dimensoes(cabecalho)

            # tamanho + data de modificação: o mesmo critério que o rsync usa.
            # Tocar o arquivo sem alterar o conteúdo força uma reindexação — é
            # conservador de propósito, e mais barato que somar md5 de gigabytes.
            impressao = hashlib.md5(
                f"{info.st_size}|{int(info.st_mtime)}".encode()).hexdigest()

            achados.append({
                "id": relativo.as_posix(),
                "file": relativo.as_posix(),
                "mime": mime_de(cabecalho, arquivo.name),
                "hash": impressao,
                "size": info.st_size,
                "w": largura, "h": altura,
                "exif": exif_camera(cabecalho),
                "ocr_text": "",   # sem o brinde do Drive
                "labels": [],
                "url": arquivo.as_uri(),
                "trashed": False,
            })
        return achados

    def baixar(self, item_id):
        arquivo = self.raiz / item_id
        dados = arquivo.read_bytes()
        return dados, mime_de(dados, arquivo.name)
