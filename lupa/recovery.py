"""Recovering images that failed in an earlier run.

A failure leaves the image out of the catalog but keeps nothing in the manifest,
so the next run treats it as new and retries it. That works — unless the manifest
already carried it from a run before the failure. Dropping those ids from the
manifest is what makes a retry deterministic.
"""
import json
from pathlib import Path


def read_failures(index_dir):
    """Every id that failed in any recorded run."""
    runs = Path(index_dir) / "runs"
    if not runs.exists():
        return []

    failed = []
    for report in sorted(runs.glob("*.errors.jsonl")):
        for line in report.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                failed.append(json.loads(line)["id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return failed


def forget_failed(index_dir, ids):
    """Drops ids from the manifest so the next run describes them again."""
    if not ids:
        return 0

    from lupa.build import atomic_write

    path = Path(index_dir) / "MANIFEST.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0

    items = manifest.get("items") or {}
    removed = [item_id for item_id in ids if items.pop(item_id, None) is not None]
    if removed:
        manifest["items"] = items
        atomic_write(path, json.dumps(manifest, ensure_ascii=False, indent=2))
    return len(removed)
