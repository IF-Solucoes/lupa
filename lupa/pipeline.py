"""Verb orchestration. No network here: source and model are injected.

That separation is what makes the whole cycle testable without credentials — and
what makes the incremental behavior verifiable rather than merely promised.
"""
import json
from pathlib import Path

from lupa.build import backup, write_index
from lupa.caption import estimate_cost, merge
from lupa.classify import classify
from lupa.guards import Lock, check_before_indexing
from lupa.reconcile import reconcile


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


def run(collection, index_dir, source, describe, mode="update", now="",
        dry_run=False, rebuild=False, confirm=None, batch=True,
        model="gemini-2.5-flash-lite"):
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
        return {"plan": plan, "estimated_cost": cost, "failures": [], "written": False}

    if rebuild:
        backup(index_dir, now=now)

    index_dir.mkdir(parents=True, exist_ok=True)
    with Lock(index_dir):
        stored = _load_catalog(index_dir)
        by_id = {entry["id"]: entry for entry in remote}
        pending = set(plan.to_describe)
        items, failures = [], []

        for file_id in plan.added + plan.changed + plan.unchanged:
            raw = by_id[file_id]

            if file_id not in pending:      # unchanged: reuse what was already paid for
                items.append(stored[file_id])
                continue

            meta = {**raw, **classify(raw)}
            try:
                image, mime = source.fetch(file_id)
                response = describe(raw, image, mime)
            except Exception as error:      # one bad image must not sink the run
                failures.append({"id": file_id, "file": raw.get("file"),
                                 "error": str(error)})
                continue
            items.append(merge(meta, response))

        new_manifest = write_index(
            index_dir, collection=collection, items=items, summary=plan.summary(),
            model=model, cost_usd=cost, now=now)

        if failures:
            report = index_dir / "runs" / f"{str(now).replace(':', '-')}.errors.jsonl"
            report.write_text(
                "\n".join(json.dumps(f, ensure_ascii=False) for f in failures) + "\n",
                encoding="utf-8")

    return {"plan": plan, "estimated_cost": cost, "failures": failures,
            "written": True, "manifest": new_manifest, "total": len(items)}
