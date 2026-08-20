"""Linha de comando do lupa.

  lupa index  <alvo>     indexa um acervo — o alvo é uma URL do Drive,
  lupa update <alvo>     um id de pasta, um caminho local ou o apelido de
                         um acervo já indexado. Os dois verbos fazem a mesma
                         coisa: o lupa decide se é a primeira rodada ou uma
                         atualização, olhando o índice.

  lupa search "<termos>" consulta
  lupa status            o que está indexado

Toda rodada passa pelo pré-flight: checagem do ambiente, plano e custo, antes
de qualquer gasto.
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from lupa import caption, config, gemini
from lupa.alvo import AlvoInvalido, resolver_alvo
from lupa.guards import IndiceJaExiste, LockOcupado, precisa_confirmar_custo
from lupa.mcp import Servidor
from lupa.pipeline import rodar
from lupa.preflight import diagnosticar, formatar, tem_bloqueio

PASTA_INDICE = "_lupa"


def agora_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def resolver_entrada(entrada, cfg):
    """Apelido cadastrado primeiro; depois URL, id ou caminho."""
    cadastrado = config.achar_acervo(cfg, str(entrada).strip())
    if cadastrado:
        return config.alvo_de_cadastro(cadastrado)
    return resolver_alvo(entrada)


def montar_fonte(alvo, env, cache):
    """Devolve (fonte, servico). O serviço só existe quando o alvo é o Drive."""
    if alvo.tipo == "local":
        from lupa.fonte_local import FonteLocal
        return FonteLocal(alvo.caminho), None

    from lupa.drive import baixar, conectar, listar_imagens

    servico = conectar(env.get("LUPA_OAUTH_CLIENT"), env.get("LUPA_OAUTH_TOKEN"))

    class FonteDrive:
        def listar(self):
            return listar_imagens(servico, alvo.folder_id)

        def baixar(self, file_id):
            destino = Path(cache) / file_id
            if not destino.exists():
                baixar(servico, file_id, destino)
            dados = destino.read_bytes()
            from lupa.imagem import mime_de
            return dados, mime_de(dados, file_id)

    return FonteDrive(), servico


def descritor(api_key, modelo):
    def descrever(item, imagem, mime):
        from lupa.classify import classify
        meta = {**item, **classify(item)}
        return gemini.descrever(api_key, caption.montar_prompt(meta), imagem, mime, modelo)
    return descrever


def comando_indexar(args):
    env = config.ambiente()
    cfg = config.ler_config()

    try:
        alvo = resolver_entrada(args.alvo, cfg)
    except AlvoInvalido as erro:
        sys.exit(f"\n{erro}\n")

    raiz = config.resolver_raiz_indices({}, env)

    # Se dá para perguntar ao Drive como a pasta se chama, o apelido sai de lá —
    # ninguém merece um acervo chamado "15fvulcdmebag7t2tmwuz5kcdd4xf3eah".
    if alvo.tipo == "drive" and Path(str(env.get("LUPA_OAUTH_CLIENT") or "")).expanduser().exists():
        try:
            from lupa.alvo import _apelidar
            from lupa.drive import conectar, nome_da_pasta
            servico_previo = conectar(env.get("LUPA_OAUTH_CLIENT"), env.get("LUPA_OAUTH_TOKEN"))
            alvo.nome = _apelidar(nome_da_pasta(servico_previo, alvo.folder_id))
        except Exception:
            pass  # sem rede ou sem permissão: seguimos com o apelido do id

    index_dir = raiz / alvo.nome
    indice_existe = (index_dir / "MANIFEST.json").exists()

    # --- PRÉ-FLIGHT: sempre, sem exceção ---
    checagens = diagnosticar(alvo, env, arquivos_existentes=None, indice_existe=indice_existe)
    print()
    print(formatar(checagens, alvo))
    print()

    if tem_bloqueio(checagens):
        sys.exit("Resolva os itens marcados com ✗ e rode de novo. Nada foi gasto.\n")

    fonte, servico = montar_fonte(alvo, env, raiz / ".cache" / alvo.nome)

    plano = rodar(acervo=alvo.nome, index_dir=index_dir, fonte=fonte,
                  descrever=lambda *a: {}, modo="update", agora=agora_iso(), dry_run=True)
    p = plano["plano"]
    quantas = len(p.a_descrever)

    print("Plano desta rodada")
    print(f"  {p.resumo()}")
    print(f"  imagens a descrever: {quantas}")
    print(f"  custo estimado: {caption.formatar_custo(plano['custo_estimado'])}")
    print()

    if p.vazio:
        print("Nada mudou desde a última rodada. Nada a fazer, nada a pagar.\n")
        return

    if args.dry_run:
        print("(--dry-run: parando aqui, nada foi escrito)\n")
        return

    teto = int(env.get("LUPA_CONFIRM_ABOVE") or 200)
    precisa = precisa_confirmar_custo(quantas, teto) or sys.stdin.isatty()
    if precisa and not args.yes:
        if not sys.stdin.isatty():
            sys.exit(f"São {quantas} imagens, acima do teto de {teto}. "
                     "Rode com --yes para confirmar sem interação.\n")
        if input("Prosseguir? [s/N] ").strip().lower() not in ("s", "sim", "y", "yes"):
            sys.exit("cancelado. nada foi gasto.\n")

    resultado = rodar(
        acervo=alvo.nome, index_dir=index_dir, fonte=fonte,
        descrever=descritor(env.get("GEMINI_API_KEY"),
                            env.get("LUPA_MODEL") or gemini.MODELO_PADRAO),
        modo="index" if args.rebuild else "update", agora=agora_iso(),
        rebuild=args.rebuild, confirm=args.confirm)

    print()
    print(f"Pronto. {resultado['plano'].resumo()}")
    print(f"  índice local: {index_dir}")
    if resultado["falhas"]:
        print(f"  {len(resultado['falhas'])} imagens falharam — veja runs/*.errors.jsonl")

    config.gravar_config(config.registrar_acervo(cfg, alvo))
    print(f'  acervo salvo como "{alvo.nome}" — da próxima vez basta o apelido')

    if servico and not args.no_push:
        _publicar(servico, alvo.folder_id, index_dir)


def _publicar(servico, folder_id, index_dir):
    """Publica o índice dentro do acervo, para quem só tem o conector do Drive."""
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
    print(f"  publicado no Drive: {enviados} arquivos em {PASTA_INDICE}/")


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

    for verbo in ("index", "update"):
        c = sub.add_parser(verbo, help="indexa ou atualiza um acervo (o lupa decide qual)")
        c.add_argument("alvo", help="URL do Drive, id de pasta, caminho local ou apelido")
        c.add_argument("--dry-run", action="store_true", help="para depois do plano")
        c.add_argument("--yes", "-y", action="store_true", help="não pergunta")
        c.add_argument("--no-push", action="store_true", help="não publica o índice no Drive")
        c.add_argument("--rebuild", action="store_true", help="refaz do zero (exige --confirm)")
        c.add_argument("--confirm", help="apelido do acervo, digitado, para liberar o --rebuild")

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
            comando_indexar(args)
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
