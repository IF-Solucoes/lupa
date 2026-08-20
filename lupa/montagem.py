"""Reconhece uma pasta local que na verdade é o Google Drive montado no disco.

Indexar por ali funciona, mas perde três coisas que só a API entrega: o OCR de
graça, o link compartilhável e o id imutável do arquivo. O pré-flight avisa —
não bloqueia.
"""
import re

# Raízes que o Google Drive for Desktop cria, nas plataformas que importam.
MARCAS = (
    r"[/\\](meu drive|my drive)([/\\]|$)",
    r"[/\\](drives compartilhados|shared drives)([/\\]|$)",
    r"[/\\]google ?drive([/\\]|$)",
    r"cloudstorage[/\\]googledrive",
)


def parece_drive_montado(caminho):
    """True quando o caminho tem cara de Drive sincronizado no disco."""
    texto = str(caminho).lower()
    return any(re.search(marca, texto) for marca in MARCAS)
