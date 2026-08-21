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


def retire_stale(service, root, planned):
    """Trashes what sits under the index folder and is no longer in the index.

    Publishing used to only ever add and update, so an index that shrank left
    its old pages behind. On the first client archive that was 85 by-tag pages
    from a superseded description pass: every one of them opened, every link in
    them worked, and together they advertised 621 tags over an index that knew
    536. Nothing was broken — the folder simply made a promise about the index
    that the search would never keep, with nothing to tell the two apart.

    Walks the whole remote tree rather than only the folders this run touched: a
    page whose entire folder left the index is exactly the one nobody revisits.
    """
    from lupa.drive import FOLDER_MIME, list_children, retire_file

    expected = {(folder, path.name) for path, folder in planned}
    retired, stack = 0, [(root, "")]
    while stack:
        parent, prefix = stack.pop()
        for child in list_children(service, parent):
            if child.get("mimeType") == FOLDER_MIME:
                stack.append((child["id"],
                              f"{prefix}/{child['name']}".strip("/")))
            elif (prefix, child["name"]) not in expected:
                retire_file(service, child["id"])
                retired += 1
    return retired


def publish(service, folder_id, index_dir, index_folder="_lupa", report=print):
    """Uploads the planned files and retires what the index no longer has."""
    from lupa.drive import ensure_folder, upload_file

    planned = plan_uploads(index_dir)
    root = ensure_folder(service, folder_id, index_folder)
    folders = {"": root}
    uploaded = 0

    for path, relative_folder in planned:
        if relative_folder not in folders:
            current, prefix = root, ""
            for part in relative_folder.split("/"):
                prefix = f"{prefix}/{part}" if prefix else part
                if prefix not in folders:
                    folders[prefix] = ensure_folder(service, current, part)
                current = folders[prefix]
        upload_file(service, folders[relative_folder], path)
        uploaded += 1

    # Never on an empty plan. Whatever emptied it — a read that failed, an index
    # that was never written — the answer is never "then all of Drive is stale".
    retired = retire_stale(service, root, planned) if planned else 0

    report(f"  published to Drive: {uploaded} files under {index_folder}/")
    if retired:
        report(f"  retired {retired} page{'s' if retired != 1 else ''} "
               f"the index no longer has (moved to the Drive trash)")
    return uploaded
