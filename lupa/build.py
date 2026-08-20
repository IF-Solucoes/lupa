"""Writing the index. These files are the contract with whoever consumes it.

Three reading levels, cheapest first:
  INDEX.md      → always (~2 KB)
  by-tag/*.md   → only the relevant tags
  catalog.jsonl → only when fields must be crossed
"""
import hashlib
import json
import os
import shutil
import time
import unicodedata
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

# Written explicitly: every artifact here is a text file with LF endings, and
# atomic_write translates on the way out. A literal in a f-string cannot carry it.
NEWLINE = chr(10)

# On Windows, os.replace over a destination another handle still holds open
# fails with PermissionError. The usual culprits — an antivirus scan, the search
# indexer, a reader in another process — let go within milliseconds, so a few
# short retries close the window instead of failing a whole run over it.
REPLACE_ATTEMPTS = 5
REPLACE_PAUSE = 0.05


def replace_when_windows_lets_go(temporary, path):
    """os.replace, retried while Windows still has the destination open.

    Gives up only when the destination is still not there: if the retries ran
    out but a complete file has appeared meanwhile (another process won the
    race), that file is as good as ours and the temporary is simply dropped.
    """
    temporary, path = Path(temporary), Path(path)
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                if path.exists():
                    temporary.unlink(missing_ok=True)
                    return
                raise
            time.sleep(REPLACE_PAUSE * (attempt + 1))


@contextmanager
def writing_atomically(path, suffix=".tmp"):
    """Yields a temporary path to write, then renames it over `path`.

    Nothing ever observes the destination half-written: it either is the old
    file or is the new one, because os.replace is atomic. A writer that raises
    leaves no temporary behind either — an orphan .tmp/.part in a cache that
    lives for thousands of files is litter that accumulates forever.

    Shared on purpose with the download cache in cli.build_source: the index and
    the cache need the exact same guarantee, and one of them learning it the
    hard way is enough.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + suffix)
    try:
        yield temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    try:
        replace_when_windows_lets_go(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write(path, text, encoding="utf-8"):
    """Writes through a temporary file and renames it into place.

    A crash mid-write would otherwise leave a truncated catalog — and a truncated
    catalog costs a full reindex to repair.
    """
    with writing_atomically(path) as temporary:
        with open(temporary, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())


# The nine characters Windows refuses in a path component. POSIX only refuses
# "/", but an index written on one machine is read on another all the time here,
# so the stricter rule is the portable one — and it is the one that was missing.
FORBIDDEN = set(chr(c) for c in (92, 47, 58, 42, 63, 34, 60, 62, 124))

# Still devices, extension or not: CON.md is the console, not a file. The write
# appears to succeed and nothing is on disk afterwards, which is the worst of
# the two failure modes because it is silent.
RESERVED_DEVICES = ({"con", "prn", "aux", "nul"}
                    | {f"com{n}" for n in range(1, 10)}
                    | {f"lpt{n}" for n in range(1, 10)})

# A name read off a piece can be a whole slogan. 80 characters leave room for
# the directory, the ".md" and a tie-breaker well inside the 260 that the
# non-Unicode Windows APIs still enforce. Truncation can make two names collide;
# entity_stems is what notices, so nothing has to be special-cased here.
STEM_CAP = 80


def tag_filename(tag):
    """Turns a tag or a proper name into a file stem legal on any filesystem.

    Shared by `by-tag/` and `by-entity/`, and the tag side is why it was too
    permissive for the entity side. A tag comes from a controlled vocabulary and
    is a lowercase word, so the only separators it ever needed were "/" and "_";
    a proper name arrives written the way somebody wrote it on a piece, and
    "Pão Dourado | Noroeste" walked straight through into a file name that
    Windows rejects. The hole was always in this function — entities are simply
    the first field that reaches it with punctuation in hand.

    Every forbidden character becomes a separator instead of being deleted:
    "A|B" must not read as "ab", which is the address of a different name.
    """
    decomposed = unicodedata.normalize("NFKD", str(tag))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    cleaned = "".join(
        " " if (c in FORBIDDEN or c == "_" or ord(c) < 32 or ord(c) == 127) else c
        for c in stripped)
    # Windows silently drops a trailing dot or space from a name, so a stem that
    # ends in one is stored under a name we would never find again — and the
    # orphan sweep would delete, every run, the page it had just written.
    return "-".join(cleaned.split())[:STEM_CAP].rstrip("-. ")


def _discriminator(name, length=6):
    """A short, stable digest of the exact name — the tie-breaker between slugs.

    Derived from the name alone, so the same name lands on the same file on
    every run regardless of what else is in the collection or of the order the
    items arrived in.
    """
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:length]


def entity_stems(names):
    """Gives every proper name a file stem that is legal, and is its own.

    Sanitising makes distinct names converge: "A|B" and "A/B" both reduce to
    "a-b", and so do a long name and its truncation. Until now the second one
    simply inherited the first one's page and its title — no crash, no warning,
    and an index quietly claiming that one client's images belong to another.
    For a generic tag that folding is harmless; for a proper name it is the
    index lying about whose archive this is.

    The rule: among the names sharing a stem, the one that sorts first keeps the
    clean stem and the others carry their own digest. Reserved device names and
    names that sanitise down to nothing keep no clean stem at all — there the
    digest goes in front, because Windows reads the device name from the start
    of the file name and a suffix would not save it.
    """
    grouped = defaultdict(list)
    for name in names:
        grouped[tag_filename(name)].append(name)

    stems = {}
    for stem, group in grouped.items():
        unusable = not stem or stem.split(".")[0] in RESERVED_DEVICES
        for position, name in enumerate(sorted(set(group))):
            if unusable:
                stems[name] = f"{_discriminator(name)}-{stem}".rstrip("-")
            elif position:
                stems[name] = f"{stem}-{_discriminator(name)}"
            else:
                stems[name] = stem
    return stems


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


def _write_by_entity(index_dir, items):
    """The same inverted index, for the proper names.

    Worth its own directory rather than a corner of `by-tag/`: a tag answers
    "what scenes are in this collection", an entity answers "what does THIS
    client have", and an agency is paid for the second question. Mixing them
    into one folder would make the second unanswerable without reading all 547
    file names. They are also far fewer, so the directory stays browsable.

    Nothing is written when nothing is named, and a directory left over from a
    run that did find names is cleared: an empty `by-entity/` would read as a
    writer that failed, which is a different claim from a collection that names
    nothing.
    """
    folder = index_dir / "by-entity"

    # Grouped by the name as written, never by the slug: the slug is an address,
    # and two different names are allowed to want the same one. entity_stems is
    # where that is settled, once, for the whole collection.
    named = defaultdict(list)
    for item in items:
        for entity in item.get("entities") or []:
            named[entity].append(item)

    stems = entity_stems(named)
    by_entity = {stems[name]: name for name in named}

    if not by_entity:
        if folder.exists():
            for stale in folder.glob("*.md"):
                stale.unlink()
            try:
                folder.rmdir()
            except OSError:      # something else lives in there; leave it alone
                pass
        return

    folder.mkdir(exist_ok=True)
    for stale in folder.glob("*.md"):   # a name that vanished leaves no orphan
        if stale.stem not in by_entity:
            stale.unlink()

    for slug, name in by_entity.items():
        members = named[name]
        lines = [f"# {name} — {len(members)} images", ""]
        lines += ["| file | type | orientation | caption | link |", "|---|---|---|---|---|"]
        for member in sorted(members, key=lambda x: x.get("file", "")):
            kind = f"{member.get('kind') or '?'}/{member.get('medium') or '?'}"
            lines.append(
                f"| {member.get('file')} | {kind} | {member.get('orientation')} | "
                f"{member.get('caption', '')} | {member.get('url', '')} |")
        atomic_write(folder / f"{slug}.md", NEWLINE.join(lines) + NEWLINE)


def _frequency_list(counter, cap, complete_in):
    """A frequency list that never presents a cut as if it were the whole.

    This function exists because the vocabulary section did exactly that: it
    printed the 40 most frequent of 547 tags and said nothing about it, so an
    agent reading INDEX.md end to end — which is what INDEX.md asks it to do —
    took those 40 for the vocabulary of the collection, and came one sentence
    from telling a client the archive held no printed material. It held thirteen
    tags about printed material, all of them below the cut.

    The cut itself stays. INDEX.md is read whole on every query and is budgeted
    at about 2 KB; 547 tags with their counts is four times the size of the
    entire file, paid on every read by every agent. What was missing was never
    the other 507 words — those are one directory listing away — it was the
    sentence saying they exist and where.
    """
    entries = counter.most_common(cap)
    listing = " · ".join(f"`{name}` ({n})" for name, n in entries)
    if len(counter) <= cap:
        return listing
    return (f"The **{len(entries)} most frequent** of **{len(counter)}** distinct — "
            f"the complete list is the file names under `{complete_in}`."
            + NEWLINE + NEWLINE + listing)


# 40 tags is roughly 600 bytes of a file budgeted at ~2 KB and read in full on
# every query. The names get a far higher ceiling: there are few of them (a name
# is on the pieces that carry it, not on every photo) and they are the whole
# reason one client's archive differs from another's, so truncating them would
# cut exactly the part that cannot be guessed. Both caps declare themselves when
# they bite.
VOCABULARY_CAP = 40
ENTITIES_CAP = 300

NO_ENTITIES = ("_No proper name is legible in this collection: no service, product, "
               "campaign, brand or person is named on any of these images. That is an "
               "answer about the collection, not a gap in the index — most "
               "photographs name nothing._")


def _write_index_md(index_dir, collection, items, now, model):
    tags = Counter(tag for item in items for tag in (item.get("tags") or []))
    kinds = Counter(item.get("kind") or "undetermined" for item in items)
    mediums = Counter(item.get("medium") or "undetermined" for item in items)
    # `or []`, never a bare `[]`: every index written before this field existed
    # carries no key here at all, and has to keep building.
    entities = Counter(entity for item in items
                       for entity in (item.get("entities") or []))

    vocabulary = _frequency_list(tags, VOCABULARY_CAP, "by-tag/") or "_none yet_"
    named = (_frequency_list(entities, ENTITIES_CAP, "by-entity/") if entities
             else NO_ENTITIES)
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

Generic terms — what kind of scene each image is. Any collection on this subject
would share most of them.

{vocabulary}

## Entities

Proper names read off the pieces themselves: services, products, campaigns, brands,
people. This is what belongs to THIS collection and to no other. Empty on most
images, and never inferred — a name is here only when it is written on the image
or unmistakable in it.

{named}

## How to query

1. **Looking for what this client specifically does, sells or ran?** Start at
   **Entities**, then read `by-entity/<name>.md`.
2. **Found a tag above?** Read `by-tag/<tag>.md`. It is a ready-made table with
   links. Stop there.
3. **Need to cross fields** (type + orientation + no text)? Filter `catalog.jsonl`.
   One line per image; fields are defined in `schema/index-v1.json`.
4. **Have the lupa MCP?** Call `lupa_search` and get ranked finalists directly.

## Files

| file | purpose |
|---|---|
| `INDEX.md` | this map — always read it first |
| `by-tag/*.md` | inverted index by generic term, cheap to read without code |
| `by-entity/*.md` | the same, by proper name — absent when nothing is named |
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
            # utf-8, said out loud: without it Windows decodes cp1252, and a
            # client folder called "4 - Fotos & Vídeos" ends the run here —
            # after every image in it was described and billed.
            runs = json.loads(path.read_text(encoding="utf-8")).get("runs", 0)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            # UnicodeDecodeError is caught for the same reason: this read only
            # carries a counter forward, and no counter is worth killing a paid
            # run over. Everything else in the manifest is rewritten below.
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


def _write_run_report(index_dir, collection, items, summary, cost_usd, model, now,
                      usage=None, batch=True):
    """Prose, and the only place a measurement outlives the terminal scrollback.

    usage — a caption.UsageMeter, or None when nothing measured this run. What the
    API counted is written here next to what was budgeted, so the two can be
    compared later without having watched the run happen.
    batch — how the run was billed. Batch is half price, so assuming it either way
    would halve, or double, a figure whose only purpose is to be exact.
    """
    from lupa.caption import usage_lines

    folder = index_dir / "runs"
    folder.mkdir(exist_ok=True)
    name = str(now).replace(":", "-")
    text = f"""# Run {now} · collection "{collection}"

Images in collection: {len(items)}

{summary}

Estimated cost: US$ {cost_usd} · model: {model}
"""
    measured = usage_lines(usage, estimated_cost=cost_usd, model=model, batch=batch)
    if measured:
        section = ["", "## Token usage", ""] + list(measured) + [""]
        text += NEWLINE.join(section)
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


class DerivedIndexError(RuntimeError):
    """A directory derived from the catalog could not be written.

    Raised only after catalog.jsonl, INDEX.md and MANIFEST.json are on disk, so
    it always means the same thing: the index is incomplete and nothing that
    cost money was lost.
    """


def write_index(index_dir, collection, items, summary, model, cost_usd, now,
                usage=None, batch=True):
    """Writes every index artifact. Idempotent: it rewrites the whole set.

    usage — optional caption.UsageMeter. Only the run report reads it: the
    published contract (catalog.jsonl, MANIFEST.json) does not change shape
    because a run was measured.
    batch — whether this run was billed at the half-price batch rate.
    """
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    items = sorted(items, key=lambda item: item.get("file", ""))

    # The order below is about money, not taste. Above the line is what was
    # bought image by image and cannot be recomputed; MANIFEST.json belongs
    # there because it is the file that makes the next run incremental. Below
    # the line is derived: every byte of by-tag/ and by-entity/ comes out of
    # catalog.jsonl and costs nothing to write again.
    #
    # It used to be the other way round. A single proper name with a "|" in it
    # raised in _write_by_entity, which ran BEFORE INDEX.md and MANIFEST.json,
    # on a real collection of 99 images that had already been described and
    # billed. No manifest meant the next run would have seen an empty index and
    # paid for all 99 a second time. The exception was right; its position was
    # not.
    _write_catalog(index_dir, items)
    _write_index_md(index_dir, collection, items, now, model)
    manifest = _write_manifest(index_dir, collection, items, model, now)
    _write_run_report(index_dir, collection, items, summary, cost_usd, model, now,
                      usage=usage, batch=batch)

    # Derived, and still not allowed to fail quietly — a directory the index
    # points at and does not have is a broken index, and postcheck says so.
    # What changes is only the blast radius: the failure is collected, the other
    # directory is still attempted, and the raise happens once everything that
    # cost money is durable. The rerun that fixes it describes nothing and is
    # billed nothing.
    broken = []
    for name, write in (("by-tag", _write_by_tag), ("by-entity", _write_by_entity)):
        try:
            write(index_dir, items)
        except Exception as error:
            broken.append(f"{name}/ ({type(error).__name__}: {error})")
    _write_search_projection(index_dir, items)

    if broken:
        raise DerivedIndexError(
            "could not write " + " and ".join(broken) + ". catalog.jsonl, "
            "INDEX.md and MANIFEST.json are already on disk: the descriptions "
            "are paid for and kept, and running lupa again rebuilds these "
            "directories from the catalog without describing a single image.")
    return manifest
