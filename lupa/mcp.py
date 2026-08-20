"""lupa's MCP server — JSON-RPC 2.0, standard library only.

Deliberately dependency-free: the MCP has to start on any machine where the
client runs, with no venv, no install, no bootstrap. It only READS indexes that
were already written — it never indexes, never touches the network, never spends.
"""
import json
from pathlib import Path

from lupa.search import search

PROTOCOL = "2024-11-05"
VERSION = "0.2.0"

TOOLS = [
    {
        "name": "lupa_search",
        "description": (
            "Search images in a visual collection index and return the best "
            "candidates with links and the reason each one matched. Always use this "
            "instead of opening the images: the index is text and costs almost nothing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "free terms, e.g. 'bridge night blue'"},
                "collection": {"type": "string",
                               "description": "collection name; empty searches all of them"},
                "kind": {"type": "string",
                         "enum": ["photo", "design", "screenshot", "diagram", "logo", "other"]},
                "medium": {"type": "string", "enum": ["physical", "digital", "na"]},
                "orientation": {"type": "string",
                                "enum": ["portrait", "landscape", "square"]},
                "has_text": {"type": "boolean",
                             "description": "false excludes pieces with baked-in text"},
                "limit": {"type": "integer", "default": 15},
            },
            "required": ["query"],
        },
    },
    {
        "name": "lupa_status",
        "description": "List indexed collections, with image counts and last run date.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

ACCEPTED_FILTERS = ("kind", "medium", "orientation", "has_text")


class Server:
    def __init__(self, index_root):
        self.root = Path(index_root)

    # --- reading indexes from disk ---

    def collections(self):
        if not self.root.exists():
            return []
        return sorted(entry.name for entry in self.root.iterdir()
                      if (entry / "catalog.jsonl").exists())

    def _load(self, collection):
        path = self.root / collection / "catalog.jsonl"
        if not path.exists():
            return []
        items = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    items.append(dict(json.loads(line), _collection=collection))
                except json.JSONDecodeError:
                    continue
        return items

    def _manifest(self, collection):
        path = self.root / collection / "MANIFEST.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    # --- tools ---

    def tool_search(self, args):
        collection = args.get("collection")
        available = self.collections()

        if collection and collection not in available:
            return (f'Collection "{collection}" is not indexed.\n'
                    f"Available: {', '.join(available) or 'none'}")

        targets = [collection] if collection else available
        catalog = [item for name in targets for item in self._load(name)]
        filters = {key: args[key] for key in ACCEPTED_FILTERS if args.get(key) is not None}

        results = search(catalog, args.get("query", ""), filters=filters,
                         limit=int(args.get("limit") or 15))
        if not results:
            return ("No results. Try broader terms, or call `lupa_status` to see "
                    "the vocabulary of each collection.")

        noun = "candidate" if len(results) == 1 else "candidates"
        lines = [f"{len(results)} {noun} (out of {len(catalog)} images):", ""]
        for result in results:
            kind = f"{result.get('kind')}/{result.get('medium')}"
            lines.append(
                f"- **{result.get('file')}** [{kind}, {result.get('orientation')}] — "
                f"{result.get('caption', '')}\n"
                f"  tags: {', '.join(result.get('tags') or [])}\n"
                f"  {result.get('url', '')}\n"
                f"  _matched on: {result.get('_reason')}_")
        return "\n".join(lines)

    def tool_status(self, _args):
        available = self.collections()
        if not available:
            return f"No collections indexed under {self.root}. Run `lupa index <target>`."

        lines = ["Indexed collections:", ""]
        for name in available:
            manifest = self._manifest(name)
            lines.append(f"- **{name}** — {manifest.get('total', '?')} images · "
                         f"updated {manifest.get('updated_at', '?')} · "
                         f"{manifest.get('runs', '?')} runs")
        return "\n".join(lines)

    # --- JSON-RPC dispatch ---

    def dispatch(self, request):
        method = request.get("method")
        request_id = request.get("id")

        if request_id is None:  # a notification: handle it and stay quiet
            return None

        def ok(result):
            return {"jsonrpc": "2.0", "id": request_id, "result": result}

        if method == "initialize":
            return ok({"protocolVersion": PROTOCOL,
                       "capabilities": {"tools": {}},
                       "serverInfo": {"name": "lupa", "version": VERSION}})

        if method == "tools/list":
            return ok({"tools": TOOLS})

        if method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            handlers = {"lupa_search": self.tool_search, "lupa_status": self.tool_status}
            if name not in handlers:
                return {"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": -32602, "message": f"unknown tool: {name}"}}
            try:
                text = handlers[name](args)
            except Exception as error:  # the client needs the reason, not a crash
                return ok({"content": [{"type": "text", "text": f"Error: {error}"}],
                           "isError": True})
            return ok({"content": [{"type": "text", "text": text}]})

        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": f"unsupported method: {method}"}}
