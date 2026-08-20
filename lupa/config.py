"""Leitura da configuração: segredos em ~/.francis/secrets, acervos em ~/.francis/config."""
import json
import os
from pathlib import Path

ENV_PADRAO = "~/.francis/secrets/lupa/lupa.env"
CONFIG_PADRAO = "~/.francis/config/lupa.json"


def ler_env(caminho=ENV_PADRAO):
    """Parser de .env — sem dependência externa para uma tarefa de dez linhas."""
    arquivo = Path(str(caminho)).expanduser()
    if not arquivo.exists():
        return {}

    valores = {}
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        valor = valor.strip().strip('"').strip("'")
        if valor.startswith("~"):
            valor = str(Path(valor).expanduser())
        valores[chave.strip()] = valor
    return valores


def ler_config(caminho=CONFIG_PADRAO):
    arquivo = Path(str(caminho)).expanduser()
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"acervos": []}


def achar_acervo(config, nome):
    for acervo in (config or {}).get("acervos") or []:
        if acervo.get("nome") == nome:
            return acervo
    return None


def ambiente(env_path=ENV_PADRAO):
    """Env do arquivo, com o ambiente do processo por cima (útil em CI)."""
    valores = ler_env(env_path)
    for chave in ("GEMINI_API_KEY", "LUPA_MODEL", "LUPA_BATCH", "LUPA_STATE_DIR",
                  "LUPA_CONFIRM_ABOVE", "LUPA_OAUTH_CLIENT", "LUPA_OAUTH_TOKEN"):
        if os.environ.get(chave):
            valores[chave] = os.environ[chave]
    return valores


RAIZ_INDICES_PADRAO = "~/.lupa/indices"


def resolver_raiz_indices(processo_env, arquivo_env):
    """Onde vive o espelho local dos índices, que é o que o MCP lê.

    O índice canônico fica no Drive. Este é o espelho de trabalho.
    Ordem: variável explícita > LUPA_STATE_DIR do .env > padrão portátil.
    """
    if processo_env.get("LUPA_INDICES"):
        return Path(processo_env["LUPA_INDICES"]).expanduser()
    if arquivo_env.get("LUPA_STATE_DIR"):
        return Path(arquivo_env["LUPA_STATE_DIR"]).expanduser() / "indices"
    return Path(RAIZ_INDICES_PADRAO).expanduser()


def registrar_acervo(config, alvo):
    """Guarda o acervo para que da próxima vez baste o apelido.

    O usuário nunca precisa editar o arquivo à mão: quem cadastra é a primeira
    execução bem-sucedida.
    """
    config = dict(config or {})
    acervos = [dict(a) for a in config.get("acervos") or []]

    registro = {"nome": alvo.nome}
    if alvo.tipo == "drive":
        registro["folder_id"] = alvo.folder_id
    else:
        registro["caminho"] = str(alvo.caminho)

    for i, existente in enumerate(acervos):
        if existente.get("nome") == alvo.nome:
            acervos[i] = {**existente, **registro}
            break
    else:
        acervos.append(registro)

    config["acervos"] = acervos
    return config


def alvo_de_cadastro(registro):
    """Converte uma entrada do config de volta num Alvo."""
    from lupa.alvo import Alvo
    if registro.get("folder_id"):
        return Alvo("drive", registro["nome"], folder_id=registro["folder_id"])
    return Alvo("local", registro["nome"], caminho=Path(registro["caminho"]).expanduser())


def gravar_config(config, caminho=CONFIG_PADRAO):
    arquivo = Path(str(caminho)).expanduser()
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
