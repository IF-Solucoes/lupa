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


def prepare_streams():
    """The MCP stdio transport is UTF-8. A Windows default is cp1252.

    In `lupa/cli.py` the same mismatch cost a tick mark in a report. Here it
    costs data: cp1252 encodes these characters happily, nothing raises, and the
    client decodes the bytes as UTF-8 anyway — so `Clínica Veterinária NOROESTE`
    reaches the agent as replacement characters, and so does the file path next
    to it. The tool description promises that entities are the sharpest query
    available; a corrupted vocabulary is the opposite of that.

    Both directions: a query arrives with accents too.

    A replaced stream — a pipe, a test double — may not offer reconfigure. Then
    there is nothing to do, and nothing to say about it.
    """
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def main():
    prepare_streams()
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
