"""Camada do Google Drive.

O parsing é puro e testado. A rede fica isolada nas funções do fim do arquivo,
que só são importadas quando há credencial — assim o núcleo roda sem depender
de bibliotecas do Google.
"""
import hashlib
import re

MARCADOR_LABELS = "Image labels:"

# Campos pedidos à API. Cada um evita uma chamada extra depois.
CAMPOS = ("files(id,name,mimeType,md5Checksum,size,modifiedTime,trashed,"
          "webViewLink,imageMediaMetadata(width,height,cameraMake,cameraModel)),nextPageToken")


def query_da_pasta(folder_id):
    """Só imagens, só desta pasta, sem lixeira."""
    return (f"'{folder_id}' in parents and mimeType contains 'image/' "
            f"and trashed = false")


def separar_ocr_e_labels(snippet):
    """O Drive entrega OCR e labels grudados no mesmo campo. Aqui eles se separam.

    O OCR é útil e sai de graça. Os labels são ruído genérico do Google — guardamos
    crus, sem confiar neles para classificar.
    """
    if not snippet:
        return "", []

    partes = snippet.split(MARCADOR_LABELS, 1)
    ocr = partes[0].strip()
    if len(partes) == 1:
        return ocr, []

    bruto = partes[1].strip().strip("\\").strip()
    bruto = re.sub(r"^\\?\[|\\?\]$", "", bruto).strip()
    labels = [l.strip().strip("\\").strip() for l in bruto.split(";")]
    return ocr, [l for l in labels if l]


def _hash_de(bruto):
    """md5 quando a API dá; senão, uma impressão digital de tamanho + data."""
    if bruto.get("md5Checksum"):
        return bruto["md5Checksum"]
    semente = f"{bruto.get('size', '')}|{bruto.get('modifiedTime', '')}"
    return hashlib.md5(semente.encode()).hexdigest()


def normalizar_arquivo(bruto):
    """Converte a resposta da API no formato que o resto do lupa consome."""
    midia = bruto.get("imageMediaMetadata") or {}
    ocr, labels = separar_ocr_e_labels(bruto.get("contentSnippet"))

    exif = {}
    if midia.get("cameraMake"):
        exif["Make"] = midia["cameraMake"]
    if midia.get("cameraModel"):
        exif["Model"] = midia["cameraModel"]

    return {
        "id": bruto.get("id"),
        "file": bruto.get("name"),
        "mime": bruto.get("mimeType"),
        "hash": _hash_de(bruto),
        "size": int(bruto.get("size") or 0),
        "w": int(midia.get("width") or 0),
        "h": int(midia.get("height") or 0),
        "exif": exif,
        "ocr_text": ocr,
        "labels": labels,
        "url": bruto.get("webViewLink") or f"https://drive.google.com/file/d/{bruto.get('id')}/view",
        "trashed": bool(bruto.get("trashed")),
    }


# --- daqui para baixo há rede. Nada disso é importado pelo núcleo. ---

ESCOPOS = [
    "https://www.googleapis.com/auth/drive.readonly",  # ler o acervo
    "https://www.googleapis.com/auth/drive.file",      # escrever SÓ o que criamos
]


def conectar(client_secret, token_path):
    """Devolve o serviço do Drive, pedindo login só na primeira vez."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from pathlib import Path

    token_path = Path(token_path).expanduser()
    cred = None
    if token_path.exists():
        cred = Credentials.from_authorized_user_file(str(token_path), ESCOPOS)

    if not cred or not cred.valid:
        if cred and cred.expired and cred.refresh_token:
            cred.refresh(Request())
        else:
            fluxo = InstalledAppFlow.from_client_secrets_file(
                str(Path(client_secret).expanduser()), ESCOPOS)
            cred = fluxo.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(cred.to_json())

    return build("drive", "v3", credentials=cred, cache_discovery=False)


def listar_imagens(servico, folder_id):
    """Metadados de todas as imagens da pasta. Sem baixar bytes."""
    arquivos, token = [], None
    while True:
        resposta = servico.files().list(
            q=query_da_pasta(folder_id), fields=CAMPOS, pageSize=1000,
            pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        arquivos += [normalizar_arquivo(f) for f in resposta.get("files", [])]
        token = resposta.get("nextPageToken")
        if not token:
            return arquivos


def baixar(servico, file_id, destino):
    """Baixa um arquivo para o disco local (miniatura de trabalho)."""
    from googleapiclient.http import MediaIoBaseDownload
    from pathlib import Path

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    pedido = servico.files().get_media(fileId=file_id)
    with open(destino, "wb") as saida:
        baixador = MediaIoBaseDownload(saida, pedido)
        concluido = False
        while not concluido:
            _, concluido = baixador.next_chunk()
    return destino


def garantir_pasta(servico, pai_id, nome):
    """Acha (ou cria) uma subpasta. É assim que o _lupa/ nasce dentro do acervo."""
    q = (f"'{pai_id}' in parents and name = '{nome}' and "
         f"mimeType = 'application/vnd.google-apps.folder' and trashed = false")
    achados = servico.files().list(q=q, fields="files(id)", supportsAllDrives=True).execute()
    if achados.get("files"):
        return achados["files"][0]["id"]

    corpo = {"name": nome, "mimeType": "application/vnd.google-apps.folder", "parents": [pai_id]}
    return servico.files().create(body=corpo, fields="id", supportsAllDrives=True).execute()["id"]


def enviar_arquivo(servico, pasta_id, caminho_local, nome_remoto=None):
    """Cria ou atualiza um arquivo do índice. Nunca toca arquivo que não criamos."""
    from googleapiclient.http import MediaFileUpload
    from pathlib import Path

    caminho_local = Path(caminho_local)
    nome = nome_remoto or caminho_local.name
    midia = MediaFileUpload(str(caminho_local), resumable=False)

    q = f"'{pasta_id}' in parents and name = '{nome}' and trashed = false"
    existentes = servico.files().list(q=q, fields="files(id)", supportsAllDrives=True).execute()
    if existentes.get("files"):
        fid = existentes["files"][0]["id"]
        return servico.files().update(fileId=fid, media_body=midia,
                                      supportsAllDrives=True).execute()["id"]

    corpo = {"name": nome, "parents": [pasta_id]}
    return servico.files().create(body=corpo, media_body=midia, fields="id",
                                  supportsAllDrives=True).execute()["id"]


def nome_da_pasta(servico, folder_id):
    """O nome que a pessoa vê no Drive — vira o apelido do acervo."""
    info = servico.files().get(fileId=folder_id, fields="name",
                               supportsAllDrives=True).execute()
    return info.get("name") or folder_id
