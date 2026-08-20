"""Dimensões de imagem lidas do cabeçalho, sem dependência externa."""
import struct
import unittest
from lupa.imagem import dimensoes, mime_de


def png(w, h):
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
            + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00")


def gif(w, h):
    return b"GIF89a" + struct.pack("<HH", w, h) + b"\x00\x00\x00"


def jpeg(w, h):
    return (b"\xff\xd8"                       # SOI
            + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
            + b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
            + struct.pack(">HH", h, w) + b"\x03" + b"\x00" * 9
            + b"\xff\xd9")


def webp(w, h):
    # VP8X: flags(1) + reservado(3) + largura-1 (3 bytes LE) + altura-1 (3 bytes LE)
    payload = b"\x00\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    corpo = b"VP8X" + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", len(corpo) + 4) + b"WEBP" + corpo


class TestDimensoes(unittest.TestCase):
    def test_png(self):
        self.assertEqual(dimensoes(png(1080, 1350)), (1080, 1350))

    def test_gif(self):
        self.assertEqual(dimensoes(gif(640, 480)), (640, 480))

    def test_jpeg(self):
        self.assertEqual(dimensoes(jpeg(4032, 3024)), (4032, 3024))

    def test_webp(self):
        self.assertEqual(dimensoes(webp(800, 600)), (800, 600))

    def test_formato_desconhecido_devolve_zeros(self):
        self.assertEqual(dimensoes(b"nao sou imagem"), (0, 0))

    def test_arquivo_truncado_nao_quebra(self):
        self.assertEqual(dimensoes(png(100, 100)[:12]), (0, 0))

    def test_bytes_vazios_nao_quebram(self):
        self.assertEqual(dimensoes(b""), (0, 0))


class TestMime(unittest.TestCase):
    def test_deduz_do_conteudo_nao_da_extensao(self):
        self.assertEqual(mime_de(png(1, 1), "foto.jpg"), "image/png")

    def test_cai_na_extensao_quando_o_conteudo_nao_diz(self):
        self.assertEqual(mime_de(b"???", "foto.jpeg"), "image/jpeg")

    def test_desconhecido_vira_octet_stream(self):
        self.assertEqual(mime_de(b"???", "arquivo.xyz"), "application/octet-stream")


if __name__ == "__main__":
    unittest.main()
