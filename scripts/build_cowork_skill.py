#!/usr/bin/env python3
"""Packages the Cowork face as a zip.

Claude.ai and Cowork install skills as a zip holding one folder with a SKILL.md
inside — a different mechanism from a Claude Code plugin, which is why this face
ships separately. It carries no code: that face reads files through the Drive
connector and executes nothing.

  python3 scripts/build_cowork_skill.py            # writes dist/lupa-cowork.zip
"""
import shutil
import sys
import zipfile
from pathlib import Path

FOLDER = "lupa-cowork"


def build(repo_root, destination=None):
    repo_root = Path(repo_root)
    destination = Path(destination or repo_root / "dist" / "lupa-cowork.zip")
    destination.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        repo_root / "skills" / "cowork" / "SKILL.md": f"{FOLDER}/SKILL.md",
        repo_root / "schema" / "index-v1.json": f"{FOLDER}/index-v1.json",
    }

    missing = [str(path) for path in payload if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing from the repository: {', '.join(missing)}")

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for source, arcname in payload.items():
            archive.write(source, arcname)

    return destination


def main():
    repo_root = Path(__file__).resolve().parent.parent
    written = build(repo_root)
    size = written.stat().st_size
    print(f"wrote {written.relative_to(repo_root)} ({size / 1024:.1f} KB)")
    print("Upload it in Claude: Settings → Capabilities → Skills → + → upload zip")


if __name__ == "__main__":
    sys.exit(main())
