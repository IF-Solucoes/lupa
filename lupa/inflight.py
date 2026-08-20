"""The record of a batch already paid for.

A Gemini batch is charged when it is CREATED, not when its answers are read. The
batch name is therefore the receipt: while it exists, the money is reachable; the
moment it is lost — a process that dies, a wait that times out, a closed terminal
— the images have been paid for and can never be collected.

So the name goes to disk before the waiting starts, into the collection's own
index directory, next to `.lock` and by the same logic: runtime state of one
machine, never part of the published index. Not in MANIFEST.json, which is rebuilt
from scratch at the end of every run and would erase the record exactly when it is
still needed. `publish.SKIPPED_NAMES` keeps it off Drive.

Resuming is only safe while the plan has not moved. Batch answers come back keyed
by file id (see gemini.batch_line): if the collection gained, lost or changed
images since the submission, those keys no longer describe the run being resumed,
and writing them would produce an index that is wrong — or silently short. The
record carries a fingerprint of the exact id set, plus the model and the
collection, and a mismatch refuses the resume instead of corrupting the index.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

from lupa.build import atomic_write

RECORD_NAME = ".batch.json"
RECORD_VERSION = 1


class BatchDrift(Exception):
    """The recorded batch does not describe the run being asked for."""


def record_path(index_dir):
    return Path(index_dir) / RECORD_NAME


def fingerprint(ids):
    """A stable digest of the id set. Order is not information here — the plan
    lists whatever reconcile produced — so it is sorted away before hashing."""
    joined = "\n".join(sorted(str(file_id) for file_id in ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _to_stderr(line):
    print(line, file=sys.stderr, flush=True)


def remember(index_dir, batch_name, collection, model, ids, on_warning=None):
    """Writes the receipt. Called the instant create_batch returns, never later.

    One run submits one batch, so a receipt already on disk naming a DIFFERENT
    batch means a second batch was created while the first was in flight — which
    only happens when something submitted twice. That first batch is paid for and
    this write is about to erase its only name, so the name is said out loud
    before it goes. Not fatal: the new batch is paid for too, and dying here
    would abandon both.

    on_warning — where that line goes. Defaults to stderr, so the warning
    survives a caller that never thought about it.
    """
    ids = list(ids)
    previous = read(index_dir)
    if previous and str(previous.get("batch")) != str(batch_name):
        lost = previous.get("batch")
        say = on_warning or _to_stderr
        say(f"  !! {record_path(index_dir)} already held a receipt for another "
            f"batch: {lost}")
        say(f"  !! it is being overwritten by {batch_name}, which leaves {lost} "
            f"paid for and with no receipt")
        say(f"  !! one run must create one batch — write {lost} down now, this "
            f"line is the only copy left")
    payload = {
        "v": RECORD_VERSION,
        "batch": str(batch_name),
        "collection": str(collection),
        "model": str(model),
        "images": len(ids),
        "fingerprint": fingerprint(ids),
        "created": time.time(),
    }
    atomic_write(record_path(index_dir),
                 json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def read(index_dir):
    """The record, or None. An unreadable record is no record."""
    try:
        data = json.loads(record_path(index_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("batch"):
        return None
    return data


def forget(index_dir):
    """Drops the receipt: the batch was consumed, or died beyond resuming."""
    record_path(index_dir).unlink(missing_ok=True)


def describe(record):
    """One line about a record, for messages the user has to act on."""
    return (f'batch {record.get("batch")} '
            f'({record.get("images", "?")} images, model {record.get("model")})')


def load_for_resume(index_dir, collection, model, ids):
    """Returns the batch name to resume, or raises BatchDrift explaining why not.

    Refusing costs one lost batch. Accepting a drifted one costs a wrong index,
    which is worse: it looks finished.
    """
    record = read(index_dir)
    if not record:
        raise BatchDrift(
            f'No batch is registered as in flight for "{collection}".\n'
            f"  Nothing to resume — there is no receipt at {record_path(index_dir)}.\n"
            f"  Run without --resume-batch to submit a new batch.")

    if int(record.get("v") or 0) != RECORD_VERSION:
        raise BatchDrift(
            f'The in-flight record for "{collection}" is version '
            f'{record.get("v")}, and this lupa writes version {RECORD_VERSION}.\n'
            f"  Refusing to resume a record it cannot be sure it understands.\n"
            f'  The batch name is {record.get("batch")} — recover it by hand, or '
            f"delete {record_path(index_dir)} to start over.")

    if str(record.get("collection")) != str(collection):
        raise BatchDrift(
            f'That batch belongs to "{record.get("collection")}", not '
            f'"{collection}".\n  {describe(record)}\n'
            f"  Resuming it here would write another collection's descriptions "
            f"into this index.")

    if str(record.get("model")) != str(model):
        raise BatchDrift(
            f'The batch in flight was submitted to {record.get("model")}, and this '
            f"run is set to {model}.\n  {describe(record)}\n"
            f"  Resuming would mix two models in one index. Set LUPA_MODEL back to "
            f'{record.get("model")} to collect it, or delete '
            f"{record_path(index_dir)} to give it up.")

    ids = list(ids)
    if record.get("fingerprint") != fingerprint(ids):
        raise BatchDrift(
            f'The images changed since that batch was submitted — then '
            f'{record.get("images", "?")}, now {len(ids)}, and not the same set.\n'
            f"  {describe(record)}\n"
            f"  Batch answers come back keyed by file id: resuming now would write "
            f"an index that is wrong, or silently incomplete. Refusing.\n"
            f"  Either restore the collection to what it was and resume, or delete "
            f"{record_path(index_dir)} and pay for a new batch.")

    return record["batch"]
