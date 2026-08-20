"""Linha de comando do lupa. Aqui a rede é ligada nas peças puras.

  lupa index  <acervo>   primeira passada — recusa sobrescrever
  lupa update <acervo>   incremental — o verbo do dia a dia
  lupa search "<termos>" consulta o índice local
  lupa status            o que está indexado
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from lupa import caption, config, gemini
from lupa.guards import IndiceJaExiste, LockOcupado, precisa_confirmar_custo
from lupa.mcp import Servidor
from lupa.pipeline import rodar

PASTA_INDICE = "_lupa"


def agora_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


class FonteDrive:
    """Adapta o Drive à interface que o pipeline espera: listar() e baixar()."""

    def __init__(self, servico, folder_id, cache):
        self.servico = servico
        self.folder_id = folder_id
        self.cache = Path(cache)

    def listar(self):
        from lupa.drive import listar_imagens
        return listar_imagens(self.servico, self.folder_id)

    def baixar(self, file_id):
        from lupa.drive import baixar
        destino = self.cache / file_id
        if not destino.exists():
            baixar(self.servico, file_id, destino)
        return destino.read_bytes(), "image/png"


def descritor_sincrono(api_key, modelo):
    """Uma chamada por imagem, resposta imediata."""
    def descrever(item, imagem, mime):
        from lupa.classify import classify
        meta = {**item, **classify(item)}
        return gemini.descrever(api_key, caption.montar_prompt(meta), imagem, mime, modelo)
    return descrever


def _resolver(args):
    env = config.ambiente()
    cfg = config.ler_config()
    acervo = config.achar_acervo(cfg, args.acervo)
    if not acervo:
        nomes = [a.get("nome") for a in cfg.get("acervos") or []]
        sys.exit(f'Acervo "{args.acervo}" não está em ~/.francis/config/lupa.json.\n'
                 f"Cadastrados: {', '.join(nomes) or 'nenhum'}")
    raiz = config.resolver_raiz_indices({}, env)
    return env, acervo, raiz / args.acervo


def comando_indexar(args, modo):
    env, acervo, index_dir = _resolver(args)
    api_key = env.get("GEMINI_API_KEY")
    if not api_key and not args.dry_run:
        sys.exit("GEMINI_API_KEY vazia em ~/.francis/secrets/lupa/lupa.env")

    from lupa.drive import conectar
    servico = conectar(env.get("LUPA_OAUTH_CLIENT"), env.get("LUPA_OAUTH_TOKEN"))
    fonte = FonteDrive(servico, acervo["folder_id"], index_dir.parent / ".cache" / args.acervo)

    if not args.dry_run:
        plano = rodar(acervo=args.acervo, index_dir=index_dir, fonte=fonte,
                      descrever=lambda *a: {}, modo=modo, agora=agora_iso(),
                      dry_run=True, rebuild=args.rebuild, confirm=args.confirm)
        teto = int(env.get("LUPA_CONFIRM_ABOVE") or 200)
        quantos = len(plano["plano"].a_descrever)
        if precisa_confirmar_custo(quantos, teto) and not args.yes:
            print(f"Esta rodada vai descrever {quantos} imagens "
                  f"(~US$ {plano['custo_estimado']}).")
            if input("Confirma? [s/N] ").strip().lower() not in ("s", "sim", "y"):
                sys.exit("cancelado.")

    resultado = rodar(
        acervo=args.acervo, index_dir=index_dir, fonte=fonte,
        descrever=descritor_sincrono(api_key, env.get("LUPA_MODEL") or gemini.MODELO_PADRAO),
        modo=modo, agora=agora_iso(), dry_run=args.dry_run,
        rebuild=args.rebuild, confirm=args.confirm)

    plano = resultado["plano"]
    print(plano.resumo())
    print(f"custo estimado: US$ {resultado['custo_estimado']}")
    if resultado["falhas"]:
        print(f"{len(resultado['falhas'])} imagens falharam — veja runs/*.errors.jsonl")
    if args.dry_run:
        print("(dry-run: nada foi escrito)")
        return

    if not args.no_push:
        _subir(servico, acervo["folder_id"], index_dir)


def _subir(servico, folder_id, index_dir):
    """Publica o índice dentro do acervo, para a face Cowork enxergar."""
    from lupa.drive import enviar_arquivo, garantir_pasta
    raiz = garantir_pasta(servico, folder_id, PASTA_INDICE)
    enviados = 0
    for arquivo in sorted(Path(index_dir).rglob("*")):
        if arquivo.is_dir() or ".backup" in arquivo.parts or arquivo.name == ".lock":
            continue
        relativo = arquivo.relative_to(index_dir)
        pasta = raiz
        for parte in relativo.parts[:-1]:
            pasta = garantir_pasta(servico, pasta, parte)
        enviar_arquivo(servico, pasta, arquivo)
        enviados += 1
    print(f"índice publicado no Drive: {enviados} arquivos em {PASTA_INDICE}/")


def comando_buscar(args):
    env = config.ambiente()
    servidor = Servidor(config.resolver_raiz_indices({}, env))
    filtros = {c: getattr(args, c) for c in ("kind", "medium", "orientation")
               if getattr(args, c, None)}
    print(servidor.ferramenta_search({"consulta": args.consulta, "acervo": args.acervo,
                                      "limite": args.limite, **filtros}))


def comando_status(_args):
    env = config.ambiente()
    print(Servidor(config.resolver_raiz_indices({}, env)).ferramenta_status({}))


def main(argv=None):
    p = argparse.ArgumentParser(prog="lupa", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    for nome, ajuda in (("index", "primeira passada num acervo"),
                        ("update", "atualiza só o que mudou")):
        c = sub.add_parser(nome, help=ajuda)
        c.add_argument("acervo")
        c.add_argument("--dry-run", action="store_true", help="mostra o plano sem gastar")
        c.add_argument("--no-push", action="store_true", help="não publica o índice no Drive")
        c.add_argument("--yes", "-y", action="store_true", help="não pergunta no teto de custo")
        c.add_argument("--rebuild", action="store_true", help="refaz do zero (exige --confirm)")
        c.add_argument("--confirm", help="nome do acervo, digitado, para liberar o --rebuild")

    b = sub.add_parser("search", help="consulta o índice")
    b.add_argument("consulta")
    b.add_argument("--acervo")
    b.add_argument("--kind", choices=caption.KINDS)
    b.add_argument("--medium", choices=caption.MEDIUMS)
    b.add_argument("--orientation", choices=("retrato", "paisagem", "quadrado"))
    b.add_argument("--limite", type=int, default=15)

    sub.add_parser("status", help="acervos indexados")

    args = p.parse_args(argv)
    try:
        if args.cmd in ("index", "update"):
            comando_indexar(args, modo=args.cmd)
        elif args.cmd == "search":
            comando_buscar(args)
        else:
            comando_status(args)
    except IndiceJaExiste as erro:
        sys.exit(f"\n✋ {erro}\n")
    except LockOcupado as erro:
        sys.exit(f"\n⏳ {erro}\n")


if __name__ == "__main__":
    main()
