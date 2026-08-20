"""Verb orchestration. No network here: source and model are injected.

That separation is what makes the whole cycle testable without credentials — and
what makes the incremental behavior verifiable rather than merely promised.
"""
import json
from collections import Counter
from pathlib import Path

from lupa import gemini
from lupa.build import backup, write_index
from lupa.caption import estimate_cost, merge
from lupa.classify import classify
from lupa.contact_sheet import build_sheets
from lupa.guards import Lock, check_before_indexing
from lupa.reconcile import reconcile

THUMBS_DIR = ".thumbs"
CURATION_PX = 240
ERROR_EXCERPT = 200


def _one_line(text, limit=ERROR_EXCERPT):
    """An error message flattened to fit on the line that must be read."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


def summarize(plan, described, failures):
    """The counters — counting what happened, not what was intended.

    `added` used to be read straight off the plan. The plan is an intention: on
    2026-08-20 it said 875 added while 875 images had failed and not one
    description existed. An image only counts as added once it has been described.
    """
    added = sum(1 for file_id in plan.added if file_id in described)
    changed = sum(1 for file_id in plan.changed if file_id in described)
    text = (f"+{added} added · ~{changed} changed · "
            f"-{len(plan.removed)} removed · ={len(plan.unchanged)} unchanged")
    if failures:
        text += f" · !{len(failures)} failed"
    return text


def verdict(failures, attempted, report=None):
    """The sentence a total failure deserves — or None, when it is not one.

    Every image failing with the same message is a diagnosis, not a statistic: a
    retired model, a revoked key, a network that is not there. It belongs on the
    FIRST line, because the last line is exactly where the 875-failure run hid it
    while the first line said "Done."
    """
    if not failures or attempted <= 0 or len(failures) < attempted:
        return None

    errors = Counter(str(failure.get("error", "")) for failure in failures)
    common, repeats = errors.most_common(1)[0]
    if attempted == 1:
        head = f"FAILED — the only image failed: {_one_line(common)}"
    elif len(errors) == 1:
        head = (f"FAILED — all {attempted} images failed, every one with the same "
                f"error: {_one_line(common)}")
    else:
        head = (f"FAILED — all {attempted} images failed. Most common error "
                f"({repeats} of {attempted}): {_one_line(common)}")

    lines = [head, "  Nothing was described, so nothing was added to the index."]
    if report:
        lines.append(f"  every failure, one per line: {report}")
    lines.append("  Fix the cause and run again: nothing that failed was recorded, "
                 "so the next run plans it again by itself.")
    return "\n".join(lines)


def _load_manifest(index_dir):
    path = Path(index_dir) / "MANIFEST.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"items": {}}


def _load_catalog(index_dir):
    """Descriptions already paid for. They survive later runs."""
    path = Path(index_dir) / "catalog.jsonl"
    if not path.exists():
        return {}
    stored = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                item = json.loads(line)
                stored[item["id"]] = item
            except (json.JSONDecodeError, KeyError):
                continue
    return stored


def _keep_thumbnail(index_dir, item_id, data):
    """Stores a small copy for the contact sheets. Silent no-op without Pillow."""
    try:
        import io

        from PIL import Image
    except ImportError:
        return

    try:
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((CURATION_PX, CURATION_PX))
            # The directory is created only once an image actually decodes, so a
            # collection of unreadable files leaves no empty folder behind.
            folder = Path(index_dir) / THUMBS_DIR
            folder.mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in str(item_id))[:80]
            image.save(folder / f"{safe}.jpg", quality=75)
    except Exception:
        return  # curation art is optional; the index is not


def _describe_many(source, describe, index_dir, raw_by_id, ids, workers):
    """Describes the pending images, in parallel when it pays off.

    Returns (results_by_id, failures). Order is not preserved here on purpose —
    the caller reassembles deterministically, so the catalog never depends on
    thread scheduling.
    """
    results, failures = {}, []

    def one(file_id):
        raw = raw_by_id[file_id]
        image, mime = source.fetch(file_id)
        _keep_thumbnail(index_dir, file_id, image)
        return file_id, describe(raw, image, mime)

    if workers <= 1 or len(ids) <= 1:
        for file_id in ids:
            try:
                _, response = one(file_id)
                results[file_id] = response
            except Exception as error:
                failures.append({"id": file_id, "file": raw_by_id[file_id].get("file"),
                                 "error": str(error)})
        return results, failures

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, file_id): file_id for file_id in ids}
        for future in as_completed(futures):
            file_id = futures[future]
            try:
                _, response = future.result()
                results[file_id] = response
            except Exception as error:
                failures.append({"id": file_id, "file": raw_by_id[file_id].get("file"),
                                 "error": str(error)})
    return results, failures


def run(collection, index_dir, source, describe, mode="update", now="",
        dry_run=False, rebuild=False, confirm=None, batch=True,
        model=gemini.DEFAULT_MODEL, contact_sheets=True, workers=1):
    """Executes one full run.

    source   — object exposing .list() and .fetch(file_id) -> (bytes, mime)
    describe — callable(item, bytes, mime) -> dict from the vision model
    mode     — "index" (first time) or "update" (incremental)
    """
    index_dir = Path(index_dir)

    if mode == "index":
        check_before_indexing(index_dir, collection=collection,
                              rebuild=rebuild, confirm=confirm)

    remote = source.list()
    manifest = _load_manifest(index_dir)
    plan = reconcile(remote, manifest)
    cost = estimate_cost(len(plan.to_describe), batch=batch)

    if dry_run:
        return {"plan": plan, "estimated_cost": cost, "failures": [],
                "written": False, "summary": plan.summary(), "verdict": None}

    if rebuild:
        backup(index_dir, now=now)

    index_dir.mkdir(parents=True, exist_ok=True)
    with Lock(index_dir):
        stored = _load_catalog(index_dir)
        by_id = {entry["id"]: entry for entry in remote}
        pending = plan.to_describe

        described, failures = _describe_many(source, describe, index_dir,
                                             by_id, pending, workers)

        items = []
        for file_id in plan.added + plan.changed + plan.unchanged:
            if file_id not in described:
                if file_id in stored:       # unchanged: reuse what was already paid for
                    items.append(stored[file_id])
                continue
            meta = {**by_id[file_id], **classify(by_id[file_id])}
            items.append(merge(meta, described[file_id]))

        summary = summarize(plan, described, failures)

        sheets = {"sheets": 0}
        if contact_sheets:
            sheets = build_sheets(items, thumbs_dir=index_dir / THUMBS_DIR,
                                  out_dir=index_dir / "contact-sheets")

        new_manifest = write_index(
            index_dir, collection=collection, items=items, summary=summary,
            model=model, cost_usd=cost, now=now)

        report = None
        if failures:
            report = index_dir / "runs" / f"{str(now).replace(':', '-')}.errors.jsonl"
            report.write_text(
                "\n".join(json.dumps(f, ensure_ascii=False) for f in failures) + "\n",
                encoding="utf-8")

    return {"plan": plan, "estimated_cost": cost, "failures": failures,
            "written": True, "manifest": new_manifest, "total": len(items),
            "contact_sheets": sheets, "summary": summary,
            "verdict": verdict(failures, len(pending), report)}
