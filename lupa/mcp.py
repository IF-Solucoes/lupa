"""Servidor MCP do lupa — JSON-RPC 2.0, biblioteca padrão apenas.

Sem dependências de propósito: o MCP precisa subir em qualquer máquina onde o
cliente rode, sem venv, sem instalação, sem bootstrap. Ele só LÊ índices já
escritos — nunca indexa, nunca chama rede, nunca gasta token.
"""
import json
from pathlib import Path

from lupa.search import search

PROTOCOLO = "2024-11-05"
VERSAO = "0.1.0"

FERRAMENTAS = [
    {
        "name": "lupa_search",
        "description": (
            "Busca imagens no índice de um acervo visual e devolve os melhores "
            "candidatos com link e o motivo do casamento. Use SEMPRE isto em vez "
            "de abrir as imagens: o índice é texto e custa quase nada."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "consulta": {"type": "string", "description": "termos livres, ex.: 'ponte noturno azul'"},
                "acervo": {"type": "string", "description": "nome do acervo; vazio busca em todos"},
                "kind": {"type": "string", "enum": ["foto", "peca", "captura", "grafico", "logo", "outro"]},
                "medium": {"type": "string", "enum": ["fisico", "digital", "na"]},
                "orientation": {"type": "string", "enum": ["retrato", "paisagem", "quadrado"]},
                "has_text": {"type": "boolean", "description": "false exclui peças com texto embutido"},
                "limite": {"type": "integer", "default": 15},
            },
            "required": ["consulta"],
        },
    },
    {
        "name": "lupa_status",
        "description": "Lista os acervos indexados, com total de imagens e data da última rodada.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

FILTROS_ACEITOS = ("kind", "medium", "orientation", "has_text")


class Servidor:
    def __init__(self, raiz_indices):
        self.raiz = Path(raiz_indices)

    # --- leitura dos índices no disco ---

    def acervos(self):
        if not self.raiz.exists():
            return []
        return sorted(p.name for p in self.raiz.iterdir()
                      if (p / "catalog.jsonl").exists())

    def _carregar(self, acervo):
        caminho = self.raiz / acervo / "catalog.jsonl"
        if not caminho.exists():
            return []
        itens = []
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha:
                try:
                    itens.append(dict(json.loads(linha), _acervo=acervo))
                except json.JSONDecodeError:
                    continue
        return itens

    def _manifesto(self, acervo):
        caminho = self.raiz / acervo / "MANIFEST.json"
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    # --- ferramentas ---

    def ferramenta_search(self, args):
        acervo = args.get("acervo")
        disponiveis = self.acervos()

        if acervo and acervo not in disponiveis:
            return (f'Acervo "{acervo}" não está indexado.\n'
                    f"Disponíveis: {', '.join(disponiveis) or 'nenhum'}")

        alvos = [acervo] if acervo else disponiveis
        catalogo = [i for a in alvos for i in self._carregar(a)]
        filtros = {c: args[c] for c in FILTROS_ACEITOS if args.get(c) is not None}

        achados = search(catalogo, args.get("consulta", ""), filtros=filtros,
                         limite=int(args.get("limite") or 15))
        if not achados:
            return ("Nenhum resultado. Tente termos mais gerais, ou rode "
                    "`lupa_status` para ver o vocabulário de cada acervo.")

        plural = "candidato" if len(achados) == 1 else "candidatos"
        linhas = [f"{len(achados)} {plural} (de {len(catalogo)} imagens):", ""]
        for r in achados:
            tipo = f"{r.get('kind')}/{r.get('medium')}"
            linhas.append(
                f"- **{r.get('file')}** [{tipo}, {r.get('orientation')}] — "
                f"{r.get('caption', '')}\n"
                f"  tags: {', '.join(r.get('tags') or [])}\n"
                f"  {r.get('url', '')}\n"
                f"  _casou por: {r.get('_motivo')}_")
        return "\n".join(linhas)

    def ferramenta_status(self, _args):
        disponiveis = self.acervos()
        if not disponiveis:
            return f"Nenhum acervo indexado em {self.raiz}. Rode `lupa index <acervo>`."

        linhas = ["Acervos indexados:", ""]
        for a in disponiveis:
            m = self._manifesto(a)
            linhas.append(f"- **{a}** — {m.get('total', '?')} imagens · "
                          f"atualizado {m.get('atualizado_em', '?')} · "
                          f"{m.get('rodadas', '?')} rodadas")
        return "\n".join(linhas)

    # --- despacho JSON-RPC ---

    def despachar(self, pedido):
        metodo = pedido.get("method")
        pedido_id = pedido.get("id")

        if pedido_id is None:  # notificação: processa e cala
            return None

        def ok(resultado):
            return {"jsonrpc": "2.0", "id": pedido_id, "result": resultado}

        if metodo == "initialize":
            return ok({"protocolVersion": PROTOCOLO,
                       "capabilities": {"tools": {}},
                       "serverInfo": {"name": "lupa", "version": VERSAO}})

        if metodo == "tools/list":
            return ok({"tools": FERRAMENTAS})

        if metodo == "tools/call":
            params = pedido.get("params") or {}
            nome = params.get("name")
            args = params.get("arguments") or {}
            funcoes = {"lupa_search": self.ferramenta_search,
                       "lupa_status": self.ferramenta_status}
            if nome not in funcoes:
                return {"jsonrpc": "2.0", "id": pedido_id,
                        "error": {"code": -32602, "message": f"ferramenta desconhecida: {nome}"}}
            try:
                texto = funcoes[nome](args)
            except Exception as erro:  # o cliente precisa do motivo, não de um crash
                return ok({"content": [{"type": "text", "text": f"Erro: {erro}"}],
                           "isError": True})
            return ok({"content": [{"type": "text", "text": texto}]})

        return {"jsonrpc": "2.0", "id": pedido_id,
                "error": {"code": -32601, "message": f"método não suportado: {metodo}"}}
