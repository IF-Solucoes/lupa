"""Publishing the index into the collection, for clients that only read files.

The cost here is round trips, not bytes: a naive implementation asks Drive for a
folder listing once per file. This module plans the whole upload first, then walks
it with one listing per folder.
"""
from pathlib import Path

# Derived or private artifacts never leave the machine: the database and curation
# thumbnails rebuild from the catalog, the backup is local history, and the lock and
# the in-flight batch receipt (lupa.inflight) are runtime details of one machine.
SKIPPED_FOLDERS = {".backup", ".thumbs"}
SKIPPED_NAMES = {".lock", ".batch.json"}
SKIPPED_SUFFIXES = {".db", ".tmp"}


def plan_uploads(index_dir):
    """[(local_path, relative_folder)] — sorted, so a run is reproducible."""
    index_dir = Path(index_dir)
    planned = []

    for path in sorted(index_dir.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(index_dir)
        if set(relative.parts) & SKIPPED_FOLDERS:
            continue
        if path.name in SKIPPED_NAMES or path.suffix in SKIPPED_SUFFIXES:
            continue
        planned.append((path, "/".join(relative.parts[:-1])))

    return planned


def publish(service, folder_id, index_dir, index_folder="_lupa", report=print):
    """Uploads the planned files, resolving each remote folder exactly once."""
    from lupa.drive import ensure_folder, upload_file

    root = ensure_folder(service, folder_id, index_folder)
    folders = {"": root}
    uploaded = 0

    for path, relative_folder in plan_uploads(index_dir):
        if relative_folder not in folders:
            current, prefix = root, ""
            for part in relative_folder.split("/"):
                prefix = f"{prefix}/{part}" if prefix else part
                if prefix not in folders:
                    folders[prefix] = ensure_folder(service, current, part)
                current = folders[prefix]
        upload_file(service, folders[relative_folder], path)
        uploaded += 1

    report(f"  published to Drive: {uploaded} files under {index_folder}/")
    return uploaded
