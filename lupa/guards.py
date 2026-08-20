"""Guardrails. Rebuilding an index costs money and destroys history.

Rule: `index` never overwrites. It detects the existing index and points the user
at `update`. Rebuilding requires typed intent.
"""
import json
import os
import time
from pathlib import Path

MAX_LOCK_AGE_S = 30 * 60  # half an hour: past that, the lock owner is gone


class IndexAlreadyExists(Exception):
    pass


class LockBusy(Exception):
    pass


def check_before_indexing(index_dir, collection, rebuild=False, confirm=None):
    """Raises IndexAlreadyExists unless the collection is untouched, or the user
    typed the exact name alongside --rebuild."""
    manifest = Path(index_dir) / "MANIFEST.json"
    if not manifest.exists():
        return

    if rebuild and confirm == collection:
        return

    try:
        data = json.loads(manifest.read_text())
    except (json.JSONDecodeError, OSError):
        data = {}
    total = data.get("total", "?")
    runs = data.get("runs", "?")

    if not rebuild:
        raise IndexAlreadyExists(
            f"This collection is already indexed: {total} images, {runs} runs.\n"
            f"  You probably want:   lupa update {collection}\n"
            f'  To rebuild from scratch: lupa index {collection} --rebuild --confirm "{collection}"'
        )
    raise IndexAlreadyExists(
        f'Rebuilding discards {runs} runs of history for "{collection}".\n'
        f'  Confirm by typing the collection name:  --confirm "{collection}"'
    )


def needs_cost_confirmation(count, ceiling):
    """True when the run would describe more images than the ceiling allows
    without asking. A ceiling of 0 disables the check."""
    return bool(ceiling) and count > ceiling


class Lock:
    """Keeps two runs from scrambling the manifest. A stale lock is reclaimed."""

    def __init__(self, index_dir):
        self.path = Path(index_dir) / ".lock"

    def __enter__(self):
        if self.path.exists() and not self._stale():
            raise LockBusy(
                f"Another run is using this index ({self.path}). "
                "Wait for it to finish, or delete the file if you are sure."
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"pid": os.getpid(), "started": time.time()}))
        return self

    def __exit__(self, *_):
        self.path.unlink(missing_ok=True)
        return False

    def _stale(self):
        try:
            started = json.loads(self.path.read_text()).get("started", 0)
        except (json.JSONDecodeError, OSError):
            return True  # an unreadable lock is a dead lock
        return (time.time() - started) > MAX_LOCK_AGE_S
