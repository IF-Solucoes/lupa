#!/usr/bin/env python3
"""Validates a lupa index. Exits 1 when something is broken.

  python3 scripts/postcheck.py example/_lupa
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REQUIRED = ("id", "file", "url", "kind", "medium", "caption", "tags", "hash", "v")
KINDS = ("photo", "design", "screenshot", "diagram", "logo", "other")
MEDIUMS = ("physical", "digital", "na")


def check(index_dir):
    index_dir = Path(index_dir)
    errors, warnings = [], []

    for name in ("INDEX.md", "catalog.jsonl", "MANIFEST.json"):
        if not (index_dir / name).exists():
            errors.append(f"missing {name}")
    if errors:
        return errors, warnings

    items, ids = [], set()
    for number, line in enumerate((index_dir / "catalog.jsonl").read_text(
            encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            errors.append(f"catalog.jsonl line {number}: invalid JSON ({error})")
            continue

        missing = [field for field in REQUIRED if field not in item]
        if missing:
            errors.append(f"line {number}: missing {', '.join(missing)}")
        if item.get("kind") not in KINDS:
            errors.append(f"line {number}: kind outside the taxonomy ({item.get('kind')!r})")
        if item.get("medium") not in MEDIUMS:
            errors.append(f"line {number}: medium outside the taxonomy ({item.get('medium')!r})")
        if item.get("id") in ids:
            errors.append(f"line {number}: duplicate id ({item.get('id')})")
        ids.add(item.get("id"))
        if not (item.get("caption") or "").strip():
            warnings.append(f"line {number}: empty caption ({item.get('file')})")
        items.append(item)

    manifest = json.loads((index_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("total") != len(items):
        errors.append(f"MANIFEST claims {manifest.get('total')} items, "
                      f"catalog holds {len(items)}")
    if set(manifest.get("items", {})) != ids:
        errors.append("MANIFEST and catalog disagree on which ids exist")

    index_text = (index_dir / "INDEX.md").read_text(encoding="utf-8").lower()
    if "pixels" not in index_text:
        errors.append("INDEX.md does not warn the agent against opening the images")

    catalog_tags = {tag for item in items for tag in (item.get("tags") or [])}
    if catalog_tags and not (index_dir / "by-tag").exists():
        errors.append("the catalog has tags but there is no by-tag/ directory")

    return errors, warnings


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "example/_lupa"
    errors, warnings = check(target)

    for warning in warnings:
        print(f"  warning: {warning}")
    if errors:
        print(f"\nFAILED — {len(errors)} problems in {target}:")
        for error in errors:
            print(f"  ✗ {error}")
        sys.exit(1)
    print(f"PASS — index is valid at {target}"
          + (f" ({len(warnings)} warnings)" if warnings else ""))


if __name__ == "__main__":
    main()
