"""Writing the index. These files are the contract with whoever consumes it.

Three reading levels, cheapest first:
  INDEX.md      → always (~2 KB)
  by-tag/*.md   → only the relevant tags
  catalog.jsonl → only when fields must be crossed
"""
import json
import os
import shutil
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA_VERSION = 1


def atomic_write(path, text, encoding="utf-8"):
    """Writes through a temporary file and renames it into place.

    A crash mid-write would otherwise leave a truncated catalog — and a truncated
    catalog costs a full reindex to repair.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with open(temporary, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def tag_filename(tag):
    """Turns a tag into a filename that is safe on any filesystem."""
    decomposed = unicodedata.normalize("NFKD", str(tag))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return "-".join(stripped.replace("/", " ").replace("_", " ").split())


def backup(index_dir, now):
    """Copies the current index into .backup/<now>/ before a destructive write."""
    source = Path(index_dir)
    if not (source / "MANIFEST.json").exists():
        return None
    destination = source / ".backup" / str(now)
    destination.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        if entry.name == ".backup":
            continue
        target = destination / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)
    return destination


def _write_catalog(index_dir, items):
    lines = [json.dumps(dict(item, v=SCHEMA_VERSION), ensure_ascii=False) for item in items]
    atomic_write(index_dir / "catalog.jsonl", "\n".join(lines) + "\n")


def _write_by_tag(index_dir, items):
    """Inverted index in Markdown — search without running any code."""
    folder = index_dir / "by-tag"
    folder.mkdir(exist_ok=True)

    by_tag = defaultdict(list)
    for item in items:
        for tag in item.get("tags") or []:
            by_tag[tag_filename(tag)].append(item)

    for stale in folder.glob("*.md"):  # a tag that vanished leaves no orphan file
        if stale.stem not in by_tag:
            stale.unlink()

    for tag, members in by_tag.items():
        lines = [f"# {tag} — {len(members)} images", ""]
        lines += ["| file | type | orientation | caption | link |", "|---|---|---|---|---|"]
        for member in sorted(members, key=lambda x: x.get("file", "")):
            kind = f"{member.get('kind') or '?'}/{member.get('medium') or '?'}"
            lines.append(
                f"| {member.get('file')} | {kind} | {member.get('orientation')} | "
                f"{member.get('caption', '')} | {member.get('url', '')} |")
        atomic_write(folder / f"{tag}.md", "\n".join(lines) + "\n")


def _write_index_md(index_dir, collection, items, now, model):
    tags = Counter(tag for item in items for tag in (item.get("tags") or []))
    kinds = Counter(item.get("kind") or "undetermined" for item in items)
    mediums = Counter(item.get("medium") or "undetermined" for item in items)

    vocabulary = " · ".join(f"`{tag}` ({n})" for tag, n in tags.most_common(40))
    by_kind = " · ".join(f"{kind}: {n}" for kind, n in kinds.most_common())
    by_medium = " · ".join(f"{medium}: {n}" for medium, n in mediums.most_common())

    text = f"""# Visual index — {collection}

**{len(items)} images** · updated {now} · described by `{model}` · schema v{SCHEMA_VERSION}

> **Read text, never pixels.** This index exists so that you do NOT have to open
> the images. Opening an image is expensive, and avoiding it is the whole point of
> this file. If you need visual confirmation, open only the finalists that the
> search returned.

## What is here

- **By type:** {by_kind}
- **By material:** {by_medium}

`kind`: photo · design · screenshot · diagram · logo · other
`medium`: physical · digital · na — a printed mockup is `design` + `physical`.

## Vocabulary

{vocabulary}

## How to query

1. **Found a tag above?** Read `by-tag/<tag>.md`. It is a ready-made table with
   links. Stop there.
2. **Need to cross fields** (type + orientation + no text)? Filter `catalog.jsonl`.
   One line per image; fields are defined in `schema/index-v1.json`.
3. **Have the lupa MCP?** Call `lupa_search` and get ranked finalists directly.

## Files

| file | purpose |
|---|---|
| `INDEX.md` | this map — always read it first |
| `by-tag/*.md` | inverted index, cheap to read without code |
| `catalog.jsonl` | one line per image, for field-level filtering |
| `contact-sheets/` | visual grids, for human curation |
| `MANIFEST.json` | internal state: the hashes that make updates incremental |
| `runs/` | what each run changed |
"""
    atomic_write(index_dir / "INDEX.md", text)


def _write_manifest(index_dir, collection, items, model, now):
    path = index_dir / "MANIFEST.json"
    runs = 0
    if path.exists():
        try:
            runs = json.loads(path.read_text()).get("runs", 0)
        except (json.JSONDecodeError, OSError):
            runs = 0

    manifest = {
        "collection": collection,
        "schema": SCHEMA_VERSION,
        "total": len(items),
        "runs": runs + 1,
        "updated_at": now,
        "model": model,
        "items": {item["id"]: {"hash": item.get("hash"), "file": item.get("file")}
                  for item in items},
    }
    atomic_write(path, json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def _write_run_report(index_dir, collection, items, summary, cost_usd, model, now):
    folder = index_dir / "runs"
    folder.mkdir(exist_ok=True)
    name = str(now).replace(":", "-")
    text = f"""# Run {now} · collection "{collection}"

Images in collection: {len(items)}

{summary}

Estimated cost: US$ {cost_usd} · model: {model}
"""
    atomic_write(folder / f"{name}.md", text)


def _write_search_projection(index_dir, items):
    """Rebuilds the SQLite/FTS5 projection. Derived data — never the source of truth."""
    from lupa import fts

    if not fts.available():
        return
    try:
        fts.build(items, index_dir / "index.db")
    except Exception:
        return  # the flat catalog still answers; the projection is an accelerator


def write_index(index_dir, collection, items, summary, model, cost_usd, now):
    """Writes every index artifact. Idempotent: it rewrites the whole set."""
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    items = sorted(items, key=lambda item: item.get("file", ""))

    _write_catalog(index_dir, items)
    _write_search_projection(index_dir, items)
    _write_by_tag(index_dir, items)
    _write_index_md(index_dir, collection, items, now, model)
    _write_run_report(index_dir, collection, items, summary, cost_usd, model, now)
    return _write_manifest(index_dir, collection, items, model, now)
