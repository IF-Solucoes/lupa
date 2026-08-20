"""EXIF mínimo: só Make e Model, que é o que decide foto vs arte gerada."""
import struct
import unittest
from lupa.imagem import exif_camera


def jpeg_com_exif(make=b"Apple", model=b"iPhone 15", big_endian=True):
    ordem = b"MM" if big_endian else b"II"
    fmt = ">" if big_endian else "<"

    # valores das strings ficam depois do IFD; offsets contam do início do TIFF
    ifd_inicio = 8
    n_tags = 2
    tamanho_ifd = 2 + n_tags * 12 + 4
    off_make = ifd_inicio + tamanho_ifd
    off_model = off_make + len(make) + 1

    tiff = ordem + struct.pack(fmt + "HI", 42, 8)
    tiff += struct.pack(fmt + "H", n_tags)
    tiff += struct.pack(fmt + "HHII", 0x010F, 2, len(make) + 1, off_make)
    tiff += struct.pack(fmt + "HHII", 0x0110, 2, len(model) + 1, off_model)
    tiff += struct.pack(fmt + "I", 0)
    tiff += make + b"\x00" + model + b"\x00"

    payload = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return b"\xff\xd8" + app1 + b"\xff\xd9"


class TestExif(unittest.TestCase):
    def test_le_marca_e_modelo_big_endian(self):
        e = exif_camera(jpeg_com_exif())
        self.assertEqual(e["Make"], "Apple")
        self.assertEqual(e["Model"], "iPhone 15")

    def test_le_little_endian_tambem(self):
        e = exif_camera(jpeg_com_exif(b"Canon", b"EOS R6", big_endian=False))
        self.assertEqual(e["Make"], "Canon")
        self.assertEqual(e["Model"], "EOS R6")

    def test_jpeg_sem_exif_devolve_vazio(self):
        self.assertEqual(exif_camera(b"\xff\xd8\xff\xd9"), {})

    def test_png_nao_tem_exif_e_nao_quebra(self):
        self.assertEqual(exif_camera(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40), {})

    def test_dados_truncados_nao_quebram(self):
        self.assertEqual(exif_camera(jpeg_com_exif()[:20]), {})

    def test_bytes_vazios_nao_quebram(self):
        self.assertEqual(exif_camera(b""), {})


if __name__ == "__main__":
    unittest.main()
