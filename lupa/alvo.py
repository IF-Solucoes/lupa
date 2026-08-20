"""Resolve o que o usuário disse num acervo concreto.

Ele pode colar a URL do Drive, o id da pasta, ou apontar um caminho local.
Nenhuma dessas formas exige cadastro prévio nem que ele saiba o que é folder_id.
"""
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# .../folders/<id>  — com ou sem /u/0/, com ou sem query
PADRAO_PASTA = re.compile(r"/folders/([A-Za-z0-9_-]+)")
# um id solto do Drive: longo, sem barra, sem espaço
PADRAO_ID = re.compile(r"^[A-Za-z0-9_-]{15,}$")


class AlvoInvalido(Exception):
    pass


@dataclass
class Alvo:
    tipo: str              # "drive" ou "local"
    nome: str              # nome do acervo, usado nas pastas de índice
    folder_id: str = None  # quando tipo == "drive"
    caminho: Path = None   # quando tipo == "local"


def _apelidar(bruto):
    """Vira um nome de acervo seguro: sem acento, sem espaço, minúsculo."""
    sem_acento = unicodedata.normalize("NFKD", str(bruto))
    limpo = "".join(c for c in sem_acento if not unicodedata.combining(c)).lower()
    limpo = re.sub(r"[^a-z0-9]+", "-", limpo).strip("-")
    return limpo or "acervo"


def resolver_alvo(entrada, nome=None):
    """Aceita URL do Drive, id de pasta ou caminho local. Devolve um Alvo."""
    entrada = str(entrada or "").strip().strip('"').strip("'")
    if not entrada:
        raise AlvoInvalido(
            "Diga qual acervo indexar: uma URL de pasta do Google Drive "
            "ou o caminho de uma pasta local.")

    if "drive.google.com" in entrada or "docs.google.com" in entrada:
        achado = PADRAO_PASTA.search(entrada)
        if not achado:
            raise AlvoInvalido(
                "Essa URL não aponta para uma PASTA do Drive.\n"
                "  Abra a pasta no Drive e copie a URL da barra de endereço — "
                "ela tem o formato .../drive/folders/<id>.")
        fid = achado.group(1)
        return Alvo("drive", nome or _apelidar(fid), folder_id=fid)

    caminho = Path(entrada).expanduser()
    if caminho.exists():
        if not caminho.is_dir():
            raise AlvoInvalido(
                f"{caminho} é um arquivo, não uma pasta. "
                "Aponte a pasta que contém as imagens.")
        return Alvo("local", nome or _apelidar(caminho.resolve().name),
                    caminho=caminho.resolve())

    if PADRAO_ID.match(entrada):
        return Alvo("drive", nome or _apelidar(entrada), folder_id=entrada)

    raise AlvoInvalido(
        f'Não entendi "{entrada}".\n'
        "  Use a URL da pasta no Google Drive (.../drive/folders/<id>)\n"
        "  ou o caminho de uma pasta local que exista.")
