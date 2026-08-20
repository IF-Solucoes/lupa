#!/usr/bin/env python3
"""Rebuilds everything an index derives from `catalog.jsonl`, describing nothing.

`catalog.jsonl` is the only file in an index that costs money: one line per
image, each line a description that was paid for. `INDEX.md`, `MANIFEST.json`,
`by-tag/`, `by-entity/` and `index.db` are all functions of those lines. When a
run dies between writing the catalog and writing the manifest — which is exactly
what an illegal entity name used to do on Windows — the collection is left
described but not indexed, and without a manifest the next `lupa index` sees an
empty index and pays for every image again.

This rebuilds the derived half from the catalog already on disk. It reads no
image, calls no API and is billed nothing.

    python scripts/rebuild_derived.py "C:\\Users\\me\\.lupa\\indexes\\my-collection"
    python scripts/rebuild_derived.py "...\\my-collection" --write

Without --write it only reports what it would do.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# cp1252 is still the console default on Windows and truncates a line at the
# first character it cannot encode, with no error and exit code 0.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def read_catalog(index_dir):
    """Every line of the catalog, refusing anything less than all of them.

    A partial read here would write a manifest listing fewer images than were
    paid for, and the next run would re-describe the difference. Rebuilding from
    a damaged catalog is not a recovery.
    """
    path = Path(index_dir) / "catalog.jsonl"
    if not path.exists():
        raise SystemExit(f"no catalog.jsonl in {index_dir} — nothing to rebuild from")

    items = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise SystemExit(f"catalog.jsonl line {number} is not valid JSON: {error}")
        if not item.get("id"):
            raise SystemExit(f"catalog.jsonl line {number} has no id")
        items.append(item)

    if not items:
        raise SystemExit(f"catalog.jsonl in {index_dir} is empty")
    return items


def model_of(index_dir, fallback=None):
    """The model that wrote these descriptions, from whatever recorded it.

    Only a label: it goes into INDEX.md and the manifest so the index does not
    claim to have been written by something it was not.
    """
    manifest = Path(index_dir) / "MANIFEST.json"
    if manifest.exists():
        try:
            named = json.loads(manifest.read_text(encoding="utf-8")).get("model")
            if named:
                return named
        except (json.JSONDecodeError, OSError):
            pass

    for report in sorted((Path(index_dir) / "runs").glob("*.md"), reverse=True):
        for line in report.read_text(encoding="utf-8").splitlines():
            if "model:" in line:
                return line.split("model:")[-1].strip()

    if fallback:
        return fallback
    from lupa.gemini import DEFAULT_MODEL
    return DEFAULT_MODEL


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("index_dir", help="the index directory to rebuild in place")
    parser.add_argument("--write", action="store_true",
                        help="actually write; without it nothing is touched")
    parser.add_argument("--collection", help="defaults to the directory name")
    parser.add_argument("--model", help="defaults to what the index already records")
    arguments = parser.parse_args(argv)

    index_dir = Path(arguments.index_dir).expanduser()
    items = read_catalog(index_dir)
    collection = arguments.collection or index_dir.name
    model = model_of(index_dir, arguments.model)

    from lupa.build import FORBIDDEN, backup, entity_stems, write_index

    names = {name for item in items for name in (item.get("entities") or [])}
    stems = entity_stems(names)
    print(f"index:      {index_dir}")
    print(f"collection: {collection}")
    print(f"images:     {len(items)} (all of them already described and paid for)")
    print(f"entities:   {len(names)} distinct names → {len(set(stems.values()))} pages")
    print(f"model:      {model}")

    for name in sorted(names):
        if set(name) & FORBIDDEN:
            print(f"  sanitised: {name} → by-entity/{stems[name]}.md")

    print("will write: INDEX.md · MANIFEST.json · by-tag/ · by-entity/ · "
          "runs/ · index.db")
    print("cost:       US$ 0.00 — no image is read and no API is called")

    if not arguments.write:
        print("\ndry run. Re-run with --write to actually rebuild.")
        return 0

    # The same stamp cli.utc_stamp writes, so this run reads like any other in
    # runs/ and in MANIFEST.json rather than like a foreign tool's output.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    backup(index_dir, now=now)
    manifest = write_index(
        index_dir, collection=collection, items=items,
        summary=("Rebuilt from catalog.jsonl. No image was described and nothing "
                 "was billed: only the files derived from the catalog were "
                 "written."),
        model=model, cost_usd=0.0, now=now, usage=None, batch=False)
    print(f"\nwritten. MANIFEST.json now lists {manifest['total']} images "
          f"(run {manifest['runs']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
