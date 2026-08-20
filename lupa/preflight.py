"""Pré-flight: antes de qualquer rodada, diga à pessoa o que vai acontecer.

Ele não é opcional e não é uma flag. Toda execução passa por aqui: checa o
ambiente, explica o que falta e como resolver, e só então mostra o plano e o
custo. Quem chama o lupa não precisa saber de credencial, de folder_id nem de
qual verbo usar — o pré-flight resolve isso.
"""
from dataclasses import dataclass
from pathlib import Path

from lupa.montagem import parece_drive_montado

OK = "ok"
AVISO = "aviso"
BLOQUEIO = "bloqueio"

SIMBOLO = {OK: "✓", AVISO: "!", BLOQUEIO: "✗"}


@dataclass
class Checagem:
    nome: str
    status: str
    mensagem: str
    como_resolver: str = ""


def tem_bloqueio(checagens):
    return any(c.status == BLOQUEIO for c in checagens)


def _existe(caminho, existentes):
    if not caminho:
        return False
    if existentes is not None:
        return str(caminho) in existentes
    return Path(str(caminho)).expanduser().exists()


def diagnosticar(alvo, env, arquivos_existentes=None, indice_existe=False):
    """Devolve a lista de checagens, em ordem de leitura."""
    checagens = []

    # 1. O acervo
    if alvo.tipo == "drive":
        checagens.append(Checagem(
            "acervo", OK,
            f'pasta do Google Drive · id {alvo.folder_id} · apelido "{alvo.nome}"'))
        checagens.append(Checagem("origem do acervo", OK,
                                  "pela API do Drive — com OCR e link compartilhável"))
    else:
        checagens.append(Checagem(
            "acervo", OK, f'pasta local {alvo.caminho} · apelido "{alvo.nome}"'))

        if parece_drive_montado(alvo.caminho):
            checagens.append(Checagem(
                "origem do acervo", AVISO,
                "esta pasta parece ser o Google Drive montado no disco",
                "Funciona assim mesmo. Mas se você colar a URL da pasta no Drive "
                "(.../drive/folders/<id>), o lupa ganha três coisas de graça:\n"
                "      · o OCR do texto das imagens, que o Google já fez — sem isso, "
                "o texto embutido nas peças não entra na busca\n"
                "      · links https compartilháveis, que o Cowork e outras pessoas abrem\n"
                "      · o id imutável de cada arquivo: renomear a pasta deixa de "
                "forçar reindexação"))
        else:
            checagens.append(Checagem("origem do acervo", OK,
                                      "pasta local — sem OCR de brinde, o modelo trabalha um pouco mais"))

    # 2. Chave do modelo de visão
    if env.get("GEMINI_API_KEY"):
        checagens.append(Checagem("chave do Gemini", OK, "configurada"))
    else:
        checagens.append(Checagem(
            "chave do Gemini", BLOQUEIO, "GEMINI_API_KEY está vazia",
            "Pegue uma chave em https://aistudio.google.com/apikey e escreva em\n"
            "      ~/.francis/secrets/lupa/lupa.env    →    GEMINI_API_KEY=sua-chave"))

    # 3. Credenciais do Drive, só quando o alvo é o Drive
    if alvo.tipo == "drive":
        cliente = env.get("LUPA_OAUTH_CLIENT")
        if _existe(cliente, arquivos_existentes):
            checagens.append(Checagem("acesso ao Google Drive", OK, "cliente OAuth encontrado"))
        else:
            checagens.append(Checagem(
                "acesso ao Google Drive", BLOQUEIO,
                f"não achei o cliente OAuth em {cliente or '(não configurado)'}",
                "Em https://console.cloud.google.com :\n"
                "      1. ative a Google Drive API no seu projeto\n"
                "      2. Credenciais → Criar → ID do cliente OAuth → App para computador\n"
                "      3. baixe o JSON como ~/.francis/secrets/lupa/google-oauth.json"))

        if _existe(env.get("LUPA_OAUTH_TOKEN"), arquivos_existentes):
            checagens.append(Checagem("login do Google", OK, "sessão salva"))
        else:
            checagens.append(Checagem(
                "login do Google", AVISO, "ainda não há sessão salva",
                "Na primeira execução o navegador vai abrir uma vez para você "
                "autorizar. Depois disso, nunca mais."))

    # 4. O que a rodada vai fazer
    if indice_existe:
        checagens.append(Checagem(
            "estado do índice", OK,
            "já existe — será um update, só o que mudou custa"))
    else:
        checagens.append(Checagem(
            "estado do índice", OK,
            "não existe ainda — será a primeira rodada, tudo será descrito"))

    return checagens


def formatar(checagens, alvo):
    """Relatório legível. É o que a pessoa lê antes de decidir."""
    linhas = [f"Pré-flight · acervo \"{alvo.nome}\"", ""]
    for c in checagens:
        linhas.append(f"  {SIMBOLO[c.status]} {c.nome}: {c.mensagem}")
        if c.como_resolver:
            for linha in c.como_resolver.split("\n"):
                linhas.append(f"      {linha}" if not linha.startswith("      ") else linha)
    return "\n".join(linhas)
