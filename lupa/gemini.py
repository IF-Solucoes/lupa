"""Cliente do Gemini via REST. Sem SDK — só urllib, para não pesar o repositório.

Dois modos: síncrono (imediato) e lote (metade do preço, assíncrono). O lote é
o padrão porque indexar acervo não tem pressa.
"""
import base64
import json
import time
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"
MODELO_PADRAO = "gemini-2.5-flash-lite"


class ErroGemini(Exception):
    pass


def montar_conteudo(prompt, bytes_imagem, mime):
    """Corpo de uma requisição de visão."""
    return {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime,
                             "data": base64.b64encode(bytes_imagem).decode()}},
        ]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }


def linha_de_lote(chave, prompt, bytes_imagem, mime):
    """Uma linha do JSONL de entrada do Batch. A chave volta no resultado."""
    return json.dumps({"key": str(chave), "request": montar_conteudo(prompt, bytes_imagem, mime)},
                      ensure_ascii=False)


def _texto_da_resposta(resposta):
    candidatos = (resposta or {}).get("candidates") or []
    if not candidatos:
        return None
    partes = candidatos[0].get("content", {}).get("parts") or []
    return partes[0].get("text") if partes else None


def ler_resultado_de_lote(bruto):
    """JSONL de saída → {chave: dicionário}. Item que falhou some, sem derrubar o resto."""
    from lupa.caption import parse_resposta, RespostaInvalida

    saida = {}
    for linha in str(bruto).splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            registro = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if registro.get("error"):
            continue
        texto = _texto_da_resposta(registro.get("response"))
        if not texto:
            continue
        try:
            saida[registro.get("key")] = parse_resposta(texto)
        except RespostaInvalida:
            continue
    return saida


# --- daqui para baixo há rede ---

def _post(url, corpo, api_key, tentativas=3):
    dados = json.dumps(corpo).encode()
    pedido = urllib.request.Request(
        url, data=dados,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
    for tentativa in range(tentativas):
        try:
            with urllib.request.urlopen(pedido, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as erro:
            if erro.code in (429, 500, 502, 503) and tentativa < tentativas - 1:
                time.sleep(2 ** tentativa)
                continue
            raise ErroGemini(f"HTTP {erro.code}: {erro.read()[:300]!r}") from erro
        except urllib.error.URLError as erro:
            if tentativa < tentativas - 1:
                time.sleep(2 ** tentativa)
                continue
            raise ErroGemini(f"rede indisponível: {erro}") from erro


def descrever(api_key, prompt, bytes_imagem, mime, modelo=MODELO_PADRAO):
    """Descreve UMA imagem, agora. Usado no modo síncrono e nos reprocessamentos."""
    from lupa.caption import parse_resposta

    url = f"{BASE}/models/{modelo}:generateContent"
    resposta = _post(url, montar_conteudo(prompt, bytes_imagem, mime), api_key)
    texto = _texto_da_resposta(resposta)
    if not texto:
        raise ErroGemini("resposta sem conteúdo")
    return parse_resposta(texto)


# --- modo lote: metade do preço, assíncrono ---

ESTADOS_FINAIS = ("JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED",
                  "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED")


def _enviar_arquivo(api_key, conteudo, nome_exibicao):
    """Sobe o JSONL de entrada pela File API (protocolo resumable, duas etapas)."""
    dados = conteudo.encode()
    inicio = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/upload/v1beta/files",
        data=json.dumps({"file": {"display_name": nome_exibicao}}).encode(),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(dados)),
            "X-Goog-Upload-Header-Content-Type": "application/jsonl",
        })
    with urllib.request.urlopen(inicio, timeout=60) as r:
        url_upload = r.headers.get("X-Goog-Upload-URL")
    if not url_upload:
        raise ErroGemini("a File API não devolveu a URL de upload")

    envio = urllib.request.Request(
        url_upload, data=dados,
        headers={"X-Goog-Upload-Command": "upload, finalize",
                 "X-Goog-Upload-Offset": "0",
                 "Content-Length": str(len(dados))})
    with urllib.request.urlopen(envio, timeout=300) as r:
        return json.loads(r.read())["file"]["name"]


def criar_lote(api_key, linhas_jsonl, modelo=MODELO_PADRAO, nome="lupa-batch"):
    """Sobe as requisições e cria o job. Devolve o nome do lote para acompanhar."""
    arquivo = _enviar_arquivo(api_key, "\n".join(linhas_jsonl) + "\n", nome)
    corpo = {"batch": {"display_name": nome, "input_config": {"file_name": arquivo}}}
    resposta = _post(f"{BASE}/models/{modelo}:batchGenerateContent", corpo, api_key)
    return resposta.get("name") or resposta.get("metadata", {}).get("name")


def _get(url, api_key):
    pedido = urllib.request.Request(url, headers={"x-goog-api-key": api_key})
    with urllib.request.urlopen(pedido, timeout=120) as r:
        return r.read()


def acompanhar_lote(api_key, nome_lote, intervalo=20, timeout_s=3 * 3600, ao_atualizar=None):
    """Aguarda o lote terminar. Devolve o JSONL de resultados, cru."""
    limite = time.time() + timeout_s
    while time.time() < limite:
        estado = json.loads(_get(f"{BASE}/{nome_lote}", api_key))
        situacao = (estado.get("metadata") or {}).get("state") or estado.get("state")
        if ao_atualizar:
            ao_atualizar(situacao)

        if situacao == "JOB_STATE_SUCCEEDED":
            saida = ((estado.get("response") or {}).get("responsesFile")
                     or (estado.get("metadata") or {}).get("output_config", {}).get("responses_file"))
            if not saida:
                raise ErroGemini("lote concluído sem arquivo de resultados")
            bruto = _get(f"https://generativelanguage.googleapis.com/download/v1beta/"
                         f"{saida}:download?alt=media", api_key)
            return bruto.decode("utf-8", errors="replace")

        if situacao in ESTADOS_FINAIS:
            raise ErroGemini(f"lote terminou em {situacao}")

        time.sleep(intervalo)
    raise ErroGemini(f"lote não terminou em {timeout_s}s")
