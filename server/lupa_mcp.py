#!/usr/bin/env python3
"""lupa MCP server entry point — stdio transport, one JSON message per line.

Zero dependencies: it starts on any machine where an MCP client runs, with no
venv, no install, no bootstrap. It only reads indexes that already exist.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lupa.config import read_env, resolve_index_root  # noqa: E402
from lupa.mcp import Server  # noqa: E402


def main():
    server = Server(resolve_index_root(os.environ, read_env()))

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = server.dispatch(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
