"""Resolves whatever the user typed into a concrete collection.

They may paste a Drive URL, a folder id, or point at a local path. None of these
forms requires prior registration, and none requires knowing what a folder id is.
"""
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# .../folders/<id> — with or without /u/0/, with or without a query string
FOLDER_PATTERN = re.compile(r"/folders/([A-Za-z0-9_-]+)")
# A bare Drive id: long, no slashes, no spaces
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{15,}$")


class InvalidTarget(Exception):
    pass


@dataclass
class Target:
    kind: str              # "drive" or "local"
    name: str              # collection name, used for index directories
    folder_id: str = None  # when kind == "drive"
    path: Path = None      # when kind == "local"


def slugify(raw):
    """Turns any string into a safe collection name: no accents, no spaces."""
    decomposed = unicodedata.normalize("NFKD", str(raw))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", stripped).strip("-") or "collection"


def resolve_target(entry, name=None):
    """Accepts a Drive URL, a folder id, or a local path. Returns a Target."""
    entry = str(entry or "").strip().strip('"').strip("'")
    if not entry:
        raise InvalidTarget(
            "Tell me which collection to index: a Google Drive folder URL "
            "or the path to a local folder.")

    if "drive.google.com" in entry or "docs.google.com" in entry:
        found = FOLDER_PATTERN.search(entry)
        if not found:
            raise InvalidTarget(
                "That URL does not point to a Drive FOLDER.\n"
                "  Open the folder in Drive and copy the URL from the address bar — "
                "it looks like .../drive/folders/<id>.")
        folder_id = found.group(1)
        return Target("drive", name or slugify(folder_id), folder_id=folder_id)

    path = Path(entry).expanduser()
    if path.exists():
        if not path.is_dir():
            raise InvalidTarget(
                f"{path} is a file, not a folder. "
                "Point at the folder that holds the images.")
        return Target("local", name or slugify(path.resolve().name), path=path.resolve())

    if ID_PATTERN.match(entry):
        return Target("drive", name or slugify(entry), folder_id=entry)

    raise InvalidTarget(
        f'I could not make sense of "{entry}".\n'
        "  Use the Drive folder URL (.../drive/folders/<id>)\n"
        "  or the path to a local folder that exists.")
