"""Step 0: the shape of a collection, before a cent is spent.

`lupa index` lists **only images in a format it supports**. Video, PSD, PDF and
Google Docs are not listed, not counted and not mentioned — they vanish in
silence. In a folder named "4 - Fotos & Vídeos" that silence is the whole
problem: the run reports 489 images and never says that 298 mp4 files are
sitting next to them, outside everything the index will ever know.

So this module counts **what is ignored** as loudly as what is indexable, from
names and mime types alone. It downloads nothing, describes nothing, and calls
no model — the command that uses it does not even need a GEMINI_API_KEY.

Nothing here talks to the network. A "walk" is any zero-argument callable
yielding `(relative_prefix, files)` per folder, breadth-first, parents before
children, **including folders that hold no files at all** — an empty folder that
disappeared from the map would be indistinguishable from one full of video,
which is exactly the confusion this command exists to end.
"""
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from lupa.local_source import EXTENSIONS as LOCAL_EXTENSIONS
from lupa.local_source import INDEX_FOLDER

# Files with no extension still need a bucket. Google Docs, Sheets and Slides
# all arrive this way — no extension, no bytes, and no chance of being indexed.
NO_EXTENSION = "(no ext)"

# What is allowed to pass for an extension. "logo.final version" is not a psd,
# and a folder-ish name with a dot in it must not invent a file type.
EXTENSION_CAP = 10

# Said out loud in every rendering, because "how much will this cost" is the
# first question anyone asks a lupa command, and here the answer is nothing.
FREE = "free · names and types only — no download, no model call, no API key"


def extension_of(name):
    """The lowercase extension, grouped so that JPG and jpg are one bucket."""
    stem = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    head, dot, tail = stem.rpartition(".")
    if not dot or not head.strip("."):      # "briefing", ".gitignore"
        return NO_EXTENSION
    if not tail or len(tail) > EXTENSION_CAP or not tail.replace("-", "").isalnum():
        return NO_EXTENSION
    return tail.lower()


def is_indexable(entry, kind):
    """True when `lupa index` would pick this file up — not when it should.

    The map exists to predict a real run, so it copies the real rule, warts and
    all. On Drive that rule is the listing query, `mimeType contains 'image/'`;
    on disk it is the extension whitelist LocalSource walks with. They do not
    agree — a PSD is `image/vnd.adobe.photoshop` to Drive and would be listed
    and billed, while the same file on disk is skipped — and pretending they do
    would make the map lie about the very run it is supposed to preview.
    """
    if kind == "drive":
        return str(entry.get("mime") or "").startswith("image/")
    extension = extension_of(entry.get("name") or "")
    return f".{extension}" in LOCAL_EXTENSIONS


@dataclass
class Node:
    """One folder. `indexable` and `ignored` count only its own files."""
    name: str = ""
    path: str = ""
    children: dict = field(default_factory=dict)
    indexable: Counter = field(default_factory=Counter)
    ignored: Counter = field(default_factory=Counter)


def _descend(root, prefix):
    """The node at `prefix`, creating the folders on the way.

    Ancestors are created rather than assumed: a walk is breadth-first in
    practice, but a map that silently dropped a folder because its parent had
    not been announced yet would be wrong in the one way nobody would check.
    """
    node = root
    for part in [p for p in str(prefix).split("/") if p]:
        if part not in node.children:
            node.children[part] = Node(name=part, path=f"{node.path}{part}/")
        node = node.children[part]
    return node


def build_tree(walk, kind, on_progress=None):
    """Consumes a walk into a folder tree. `on_progress(folders, files)` per folder."""
    root = Node()
    folders = files = 0
    for prefix, entries in walk():
        node = _descend(root, prefix)
        for entry in entries:
            bucket = node.indexable if is_indexable(entry, kind) else node.ignored
            bucket[extension_of(entry.get("name") or "")] += 1
        folders += 1
        files += len(entries)
        if on_progress:
            on_progress(folders, files)
    return root


def find(root, path):
    """The node at a relative path ("a/b/"), or None."""
    node = root
    for part in [p for p in str(path).split("/") if p]:
        node = node.children.get(part)
        if node is None:
            return None
    return node


def extensions(node):
    """(indexable, ignored) counters for the whole subtree."""
    indexable, ignored = Counter(node.indexable), Counter(node.ignored)
    for child in node.children.values():
        below_indexable, below_ignored = extensions(child)
        indexable += below_indexable
        ignored += below_ignored
    return indexable, ignored


def totals(node):
    """(indexable, ignored) file counts for the whole subtree."""
    indexable, ignored = extensions(node)
    return sum(indexable.values()), sum(ignored.values())


def count_folders(node):
    return len(node.children) + sum(count_folders(c) for c in node.children.values())


# --- rendering ----------------------------------------------------------
#
# A map that does not fit on a screen is not a map. Two levels is what a person
# can take in at a glance; everything deeper is folded into the row above it and
# the folding is announced, never silent.

DEFAULT_DEPTH = 2
NAME_WIDTH = 46
TOP_TYPES = 6          # per row, before "+N more"
ELLIPSIS = "…"


def _display(text):
    """NFC, because these names come off a Mac.

    A file copied from macOS carries its accents decomposed — "Vídeos" is `i`
    plus a combining acute. Padded as-is, the combining mark counts as a column
    that is not there and the whole table goes crooked.
    """
    return unicodedata.normalize("NFC", str(text))


def _pad(label, width=NAME_WIDTH):
    label = _display(label)
    if len(label) > width:
        label = label[:width - 1] + ELLIPSIS
    return label.ljust(width)


def _group(counter, cap=TOP_TYPES):
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    text = " · ".join(f"{count} {name}" for name, count in ordered[:cap])
    if len(ordered) > cap:
        text += f" · +{len(ordered) - cap} more"
    return text


def _types(indexable, ignored, cap=TOP_TYPES):
    """"489 jpg · ignored: 53 mp4 · 21 mov" — what you get, then what you lose.

    The word "ignored" is in there rather than implied, because the same
    extension can land on both sides and did on the first real collection: a
    folder of 92 files with no extension at all, of which Drive calls 91 images
    and one something else. Two identical labels on one line, one of them
    costing money and one of them invisible, is not a map.
    """
    left, right = _group(indexable, cap), _group(ignored, cap)
    if not left and not right:
        return "empty"
    if not right:
        return left
    right = f"ignored: {right}"
    return f"{left} · {right}" if left else right


def _counts(indexable, ignored):
    if not indexable and not ignored:
        return "empty"
    if not ignored:
        return f"{indexable} indexable"
    return f"{indexable} indexable · {ignored} ignored"


def _rows(node, depth, level=1):
    """(level, node, is_display_leaf) for every folder that gets printed."""
    for child in node.children.values():
        leaf = level >= depth or not child.children
        yield level, child, leaf
        if not leaf:
            yield from _rows(child, depth, level + 1)


def _row_line(level, node, leaf):
    label = "  " * level + _display(node.name) + "/"
    indexable, ignored = extensions(node)
    tail = _types(indexable, ignored) if leaf else _counts(
        sum(indexable.values()), sum(ignored.values()))
    return f"  {_pad(label)} {tail}"


def _folded(root, depth):
    """How many folders sit below the printed depth."""
    printed = sum(1 for _ in _rows(root, depth))
    return count_folders(root) - printed


def render(tree, title, depth=DEFAULT_DEPTH, heading="Drive map", empty_hint=""):
    """The screen version. This is what a person reads before deciding.

    `empty_hint` is the caller's explanation for a collection that came back
    with nothing at all — on Drive the likeliest cause is a folder never shared
    with this account, because Drive answers a listing you may not see with an
    empty list rather than an error. On disk that sentence would be nonsense,
    which is why it is handed in rather than assumed.
    """
    depth = max(1, int(depth or DEFAULT_DEPTH))
    lines = [f"{heading} · {title}", FREE, ""]

    loose = _types(tree.indexable, tree.ignored)
    if tree.indexable or tree.ignored:
        lines.append(f"  {_pad('  ./')} {loose}")

    for level, node, leaf in _rows(tree, depth):
        lines.append(_row_line(level, node, leaf))

    if not tree.children and not (tree.indexable or tree.ignored):
        lines.append("  (nothing here: no files, no subfolders)")
        if empty_hint:
            lines.append(f"  {empty_hint}")

    hidden = _folded(tree, depth)
    if hidden:
        lines.append("")
        lines.append(f"  {hidden} folders deeper than {depth} "
                     f"{'level' if depth == 1 else 'levels'} are folded into the "
                     f"rows above — --depth {depth + 2} opens them")

    indexable, ignored = extensions(tree)
    total = f"  total: {sum(indexable.values())} indexable · {sum(ignored.values())} ignored"
    if ignored:
        listed = sorted(ignored.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
        total += " (" + " · ".join(f"{name} {count}" for name, count in listed) + ")"
    lines += ["", total,
              f"  {count_folders(tree)} folders scanned"]
    return "\n".join(lines) + "\n"


def markdown(tree, title, depth=None, heading="Drive map"):
    """The artifact. A sibling of INDEX.md, and read the same way: whole.

    No depth limit by default — this one is a file, not a screen, and the search
    agent that reads it has no scrollback to run out of.
    """
    indexable, ignored = extensions(tree)
    lines = [f"# MAP · {_display(title)}", "",
             f"_{FREE}. Nothing here was indexed._", "",
             f"- **{sum(indexable.values())}** files lupa would index",
             f"- **{sum(ignored.values())}** files lupa ignores completely",
             f"- **{count_folders(tree)}** folders", ""]

    if ignored:
        lines += ["## What lupa would NOT index", "",
                  "These files are invisible to an index: they are never listed, "
                  "never described, never counted in a plan and never billed. "
                  "Nothing in `INDEX.md` will ever mention them.", "",
                  "| type | files |", "|---|---|"]
        for name, count in sorted(ignored.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| `{name}` | {count} |")
        lines.append("")

    if indexable:
        lines += ["## What lupa WOULD index", "",
                  "| type | files |", "|---|---|"]
        for name, count in sorted(indexable.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| `{name}` | {count} |")
        lines.append("")

    lines += ["## Folders", "", "| folder | indexable | ignored | types |",
              "|---|---:|---:|---|"]
    if tree.indexable or tree.ignored:
        lines.append(f"| `./` | {sum(tree.indexable.values())} | "
                     f"{sum(tree.ignored.values())} | {_types(tree.indexable, tree.ignored)} |")
    limit = depth if depth else 10 ** 6
    for level, node, _leaf in _rows(tree, limit):
        below_indexable, below_ignored = extensions(node)
        lines.append(
            f"| `{_display(node.path)}` | {sum(below_indexable.values())} | "
            f"{sum(below_ignored.values())} | "
            f"{_types(below_indexable, below_ignored)} |")
    return "\n".join(lines) + "\n"


def write_map(path, tree, title, depth=None, heading="Drive map"):
    """Writes MAP.md. utf-8, out loud: these are the client's own folder names."""
    from lupa.build import atomic_write

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, markdown(tree, title, depth=depth, heading=heading),
                 encoding="utf-8")
    return path


# --- the two walks ------------------------------------------------------

def local_walk(root):
    """A folder on disk. No credentials, no network, no Pillow."""
    root = Path(root).expanduser().resolve()

    def walk():
        queue = [(root, "")]
        while queue:
            folder, prefix = queue.pop(0)
            files, subfolders = [], []
            try:
                entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                entries = []           # unreadable folder: reported as empty, not fatal
            for entry in entries:
                if entry.is_dir():
                    # Same rule LocalSource walks with: never map our own index,
                    # never map a dotfolder.
                    if entry.name == INDEX_FOLDER or entry.name.startswith("."):
                        continue
                    subfolders.append(entry)
                elif entry.is_file():
                    files.append({"name": entry.name, "mime": None})
            yield prefix, files
            queue += [(sub, f"{prefix}{sub.name}/") for sub in subfolders]

    return walk


def drive_walk(service, root_id):
    """A Drive folder. One listing per folder — see drive.walk_entries."""
    from lupa.drive import walk_entries
    return lambda: walk_entries(service, root_id)
