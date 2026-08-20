#!/usr/bin/env python3
"""Packages the plugin as an uploadable zip.

Cowork and Code both install this plugin from the marketplace
(`IF-Solucoes/lupa`), which is the normal path. This package exists for the other
one: Cowork's Plugins page also accepts a plugin as a file, which is handy behind
a proxy, for an offline install, or when a marketplace refresh misbehaves.

  python3 scripts/build_plugin_package.py       # writes dist/lupa.zip
"""
import sys
import zipfile
from pathlib import Path

FOLDER = "lupa"

# What a running plugin needs: the manifest, the skills, the MCP server and the
# code it imports, plus the schema and the docs a reader will want.
INCLUDED = (
    ".claude-plugin/plugin.json",
    ".mcp.json",
    "README.md",
    "LICENSE",
    "schema/index-v1.json",
)
INCLUDED_TREES = ("skills", "server", "lupa", "docs")

EXCLUDED_PARTS = {"__pycache__", ".git", "tests", "dist", ".thumbs", ".backup"}
EXCLUDED_SUFFIXES = {".pyc", ".db", ".tmp", ".zip"}


def _wanted(path, root):
    relative = path.relative_to(root)
    if set(relative.parts) & EXCLUDED_PARTS:
        return False
    return path.suffix not in EXCLUDED_SUFFIXES


def build(repo_root, destination=None):
    repo_root = Path(repo_root)
    destination = Path(destination or repo_root / "dist" / "lupa.zip")
    destination.parent.mkdir(parents=True, exist_ok=True)

    files = []
    for name in INCLUDED:
        path = repo_root / name
        if path.exists():
            files.append(path)
    for tree in INCLUDED_TREES:
        for path in sorted((repo_root / tree).rglob("*")):
            if path.is_file() and _wanted(path, repo_root):
                files.append(path)

    manifest = repo_root / ".claude-plugin" / "plugin.json"
    if manifest not in files:
        raise FileNotFoundError(".claude-plugin/plugin.json is missing — "
                                "the runtime reads the manifest from there and nowhere else")

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, f"{FOLDER}/{path.relative_to(repo_root).as_posix()}")

    return destination


def main():
    repo_root = Path(__file__).resolve().parent.parent
    written = build(repo_root)
    with zipfile.ZipFile(written) as archive:
        count = len(archive.namelist())
    print(f"wrote {written.relative_to(repo_root)} "
          f"({written.stat().st_size / 1024:.1f} KB, {count} files)")
    print("Upload it in Cowork: Customize → Plugins → upload")


if __name__ == "__main__":
    sys.exit(main())
