"""lupa command line.

  lupa index  <target>     index a collection — the target is a Drive URL, a
  lupa update <target>     folder id, a local path, or the name of a collection
                           already indexed. Both verbs do the same thing: lupa
                           reads the index and decides whether this is a first
                           run or an update.

  lupa search "<terms>"    query
  lupa status              what is indexed

Every run goes through preflight: environment checks, plan and cost, before any
spending.
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from lupa import caption, config, gemini, inflight
from lupa.guards import IndexAlreadyExists, LockBusy, needs_cost_confirmation
from lupa.mcp import Server
from lupa.pipeline import run as run_pipeline
from lupa.preflight import diagnose, format_report, has_blocker
from lupa.target import InvalidTarget, resolve_target

INDEX_FOLDER = "_lupa"


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def resolve_entry(entry, registry):
    """A registered name first; then a URL, an id, or a path."""
    known = config.find_collection(registry, str(entry).strip())
    if known:
        return config.target_from_registry(known)
    return resolve_target(entry)


def build_source(target, env, cache, recursive=True):
    """Returns (source, service). The service exists only for Drive targets."""
    if target.kind == "local":
        from lupa.local_source import LocalSource
        return LocalSource(target.path, recursive=recursive), None

    from lupa.drive import connect, download, fetch_thumbnail, list_images
    from lupa.image import mime_of
    from lupa.thumbnail import downscale

    service, credentials = connect(env.get("LUPA_OAUTH_CLIENT"),
                                   env.get("LUPA_OAUTH_TOKEN"), with_credentials=True)

    class DriveSource:
        def __init__(self):
            self.thumbnails = {}

        def list(self):
            items = list_images(service, target.folder_id, recursive=recursive)
            self.thumbnails = {item["id"]: item.get("thumbnail") for item in items}
            return items

        def fetch(self, file_id):
            # Cheap path: the thumbnail Google already made. Full download is the
            # fallback, and even then the bytes get downscaled before they cost tokens.
            link = self.thumbnails.get(file_id)
            if link:
                try:
                    data = fetch_thumbnail(credentials, link)
                    if data:
                        return data, "image/jpeg"
                except Exception:
                    pass

            local = Path(cache) / file_id
            if not local.exists():
                download(service, file_id, local)
            data = local.read_bytes()
            mime = mime_of(data, file_id)
            return downscale(data, mime), mime

    return DriveSource(), service


def make_describer(api_key, model, language):
    """One call per image, immediate. Used when batch mode is off or unavailable."""
    def describe(item, image, mime):
        from lupa.classify import classify
        meta = {**item, **classify(item)}
        prompt = caption.build_prompt(meta, language=language)
        return gemini.describe(api_key, prompt, image, mime, model)
    return describe


def make_batch_describer(api_key, model, language, source, ids, on_progress=print,
                         index_dir=None, collection="", resume_batch=None):
    """Half the price: every image goes up in one job, answers come back keyed.

    The batch is submitted on the first call and then served from memory, so the
    pipeline keeps its one-image-at-a-time shape without paying per request.

    resume_batch — the name of a batch already submitted and already charged. Given
    one, nothing is uploaded and nothing is created: the job is only waited on.
    """
    from lupa.classify import classify

    state = {"results": None}
    hint = f"lupa update {collection} --resume-batch" if collection else None

    def ensure_submitted(items_by_id):
        if state["results"] is not None:
            return

        job = resume_batch
        if job:
            on_progress(f"  resuming batch {job} — already paid for, "
                        "not submitting a new one")
        else:
            lines = []
            for file_id in ids:
                item = items_by_id[file_id]
                image, mime = source.fetch(file_id)
                meta = {**item, **classify(item)}
                prompt = caption.build_prompt(meta, language=language)
                lines.append(gemini.batch_line(file_id, prompt, image, mime))

            on_progress(f"  submitting {len(lines)} images as one batch job...")
            job = gemini.create_batch(api_key, lines, model=model)
            # Charged from here on, and the name is the receipt. It reaches the
            # screen first — the screen is the user's last resort and must never
            # depend on a disk — and disk immediately after, so a process killed
            # one second later is still recoverable.
            on_progress(f"  batch {job} accepted; waiting (this is the half-price path)")
            if index_dir is not None:
                try:
                    inflight.remember(index_dir, job, collection, model, ids)
                except Exception as failure:   # full disk, read-only folder, I/O
                    # The money is already spent, and waiting is the only way to
                    # collect it. Dying over bookkeeping would throw that away, so
                    # this says so loudly and then goes on waiting.
                    on_progress(f"  !! the batch receipt could not be written to "
                                f"{inflight.record_path(index_dir)}: {failure}")
                    on_progress("  !! automatic resume will NOT be available for "
                                "this batch")
                    on_progress(f"  !! write this name down now, it is the only "
                                f"copy: {job}")

        try:
            raw = gemini.await_batch(api_key, job, resume_hint=hint,
                                     on_update=lambda s: on_progress(f"    {s}"))
        except gemini.BatchTimeout:
            raise                       # still running, still resumable: keep the record
        except gemini.GeminiError:
            if index_dir is not None:   # ended badly: there is nothing left to resume
                inflight.forget(index_dir)
            raise

        state["results"] = gemini.read_batch_results(raw)
        if index_dir is not None:
            inflight.forget(index_dir)  # consumed: it must not be resumable again
        on_progress(f"  batch returned {len(state['results'])} descriptions")

    def describe(item, image, mime):
        ensure_submitted(describe.items_by_id)
        found = state["results"].get(item["id"])
        if found is None:
            raise gemini.GeminiError("no description came back for this image")
        return found

    describe.items_by_id = {}
    return describe


def _settle_inflight_batch(args, index_dir, collection, model, plan):
    """Reconciles this run with a batch that may already be in flight — and paid.

    Returns the batch name to resume, or None to submit a new one. Exits when the
    two do not agree.

    A registered batch is money already spent. Running on top of it without
    --resume-batch would create and pay for a second one, in silence, while the
    first is still alive; the choice here is therefore block-and-instruct rather
    than warn-and-continue. Warning is not enough: the run continues by default
    (and non-interactively there is nobody reading), so the double charge would
    happen anyway. Blocking costs one aborted command and prints both ways out —
    resume it, or delete the receipt and give it up on purpose.
    """
    record = inflight.read(index_dir)

    if getattr(args, "dry_run", False):
        if record:
            print(f"  note: {inflight.describe(record)} is registered as in flight "
                  f"for this collection — it was already charged.")
            print(f"  collect it with:  lupa update {collection} --resume-batch\n")
        return None

    if args.resume_batch and args.no_batch:
        sys.exit("--resume-batch and --no-batch contradict each other: there is a "
                 "batch to collect, and --no-batch would pay per image instead.\n")

    if not args.resume_batch:
        if record:
            sys.exit(
                f'\n✋ A batch for "{collection}" is still registered as in flight, '
                f"and it was ALREADY CHARGED.\n"
                f"  {inflight.describe(record)}\n"
                f"  Running now would submit — and pay for — a second one.\n\n"
                f"  Collect it:            lupa update {collection} --resume-batch\n"
                f"  Or give it up (the money stays spent, the images get paid for "
                f"again):\n"
                f"      delete {inflight.record_path(index_dir)}\n")
        return None

    try:
        return inflight.load_for_resume(index_dir, collection, model, plan.to_describe)
    except inflight.BatchDrift as error:
        sys.exit(f"\n✋ {error}\n")


def command_index(args):
    env = config.environment()
    registry = config.read_config(file_env=env)

    try:
        target = resolve_entry(args.target, registry)
    except InvalidTarget as error:
        sys.exit(f"\n{error}\n")

    root = config.resolve_index_root(os.environ, env)

    # When Drive can be asked what the folder is called, the name comes from
    # there — nobody deserves a collection named "15fvulcdmebag7t2tm". Only when
    # a session is already stored: this probe is cosmetic, and a cosmetic probe
    # may never trigger the interactive login — that would open a browser before
    # preflight has printed the sentence explaining why, and even under --dry-run.
    # Without a stored session the name stays id-derived and the sign-in happens
    # later, in build_source, after the report.
    client = env.get("LUPA_OAUTH_CLIENT")
    token = env.get("LUPA_OAUTH_TOKEN")
    if (target.kind == "drive" and client and Path(client).expanduser().exists()
            and token and Path(token).expanduser().exists()):
        try:
            from lupa.drive import connect, folder_name
            from lupa.target import slugify
            probe = connect(client, env.get("LUPA_OAUTH_TOKEN"))
            target.name = slugify(folder_name(probe, target.folder_id))
        except Exception:
            pass  # no network or no permission: keep the id-derived name

    index_dir = root / target.name
    index_exists = (index_dir / "MANIFEST.json").exists()

    # --- PREFLIGHT: always, no exceptions ---
    checks = diagnose(target, env, existing_files=None, index_exists=index_exists,
                      env_file=config.env_path())
    print()
    print(format_report(checks, target))
    print()

    if has_blocker(checks):
        sys.exit("Fix the items marked ✗ and run again. Nothing was spent.\n")

    if args.retry_failed:
        from lupa.recovery import forget_failed, read_failures
        retried = forget_failed(index_dir, read_failures(index_dir))
        print(f"  retrying {retried} images that failed in earlier runs\n"
              if retried else "  no earlier failures to retry\n")

    source, service = build_source(target, env, root / ".cache" / target.name,
                                  recursive=not args.no_recursive)

    preview = run_pipeline(collection=target.name, index_dir=index_dir, source=source,
                           describe=lambda *a: {}, mode="update", now=utc_stamp(),
                           dry_run=True)
    plan = preview["plan"]
    pending = len(plan.to_describe)

    print("Plan for this run")
    print(f"  {plan.summary()}")
    print(f"  images to describe: {pending}")
    print(f"  estimated cost: {caption.format_cost(preview['estimated_cost'])}")
    print()

    # Before anything this run might spend: money it may have spent already.
    model = env.get("LUPA_MODEL") or gemini.DEFAULT_MODEL
    resume_batch = _settle_inflight_batch(args, index_dir, target.name, model, plan)

    if plan.empty:
        print("Nothing changed since the last run. Nothing to do, nothing to pay.\n")
        return

    if args.dry_run:
        print("(--dry-run: stopping here, nothing was written)\n")
        return

    ceiling = int(env.get("LUPA_CONFIRM_ABOVE") or 200)
    must_ask = needs_cost_confirmation(pending, ceiling) or sys.stdin.isatty()
    if must_ask and not args.yes:
        if not sys.stdin.isatty():
            sys.exit(f"That is {pending} images, above the ceiling of {ceiling}. "
                     "Pass --yes to confirm without interaction.\n")
        if input("Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("cancelled. nothing was spent.\n")

    language = env.get("LUPA_LANG") or caption.DEFAULT_LANGUAGE
    api_key = env.get("GEMINI_API_KEY")
    use_batch = str(env.get("LUPA_BATCH", "1")).strip() not in ("0", "false", "no")
    # A resume is never a per-image run: those answers are already bought and
    # waiting, and describing again would pay full price for the same images.
    batch_mode = bool(resume_batch) or (use_batch and not args.no_batch)

    if batch_mode:
        remote = {item["id"]: item for item in source.list()}
        describer = make_batch_describer(api_key, model, language, source,
                                         plan.to_describe, index_dir=index_dir,
                                         collection=target.name,
                                         resume_batch=resume_batch)
        describer.items_by_id = remote
    else:
        describer = make_describer(api_key, model, language)

    result = run_pipeline(
        collection=target.name, index_dir=index_dir, source=source,
        describe=describer, batch=batch_mode,
        mode="index" if args.rebuild else "update", now=utc_stamp(),
        rebuild=args.rebuild, confirm=args.confirm, model=model,
        contact_sheets=not args.no_contact_sheets, workers=max(1, args.workers))

    print()
    # A total failure is a headline, not a footnote: it goes before everything
    # else, and it takes the word "Done." with it. Reading only the first line has
    # to be enough to know the run did not work.
    if result["verdict"]:
        print(result["verdict"])
    else:
        print(f"Done. {result['summary']}")
    print(f"  local index: {index_dir}")
    if result["failures"] and not result["verdict"]:
        print(f"  {len(result['failures'])} images failed — see runs/*.errors.jsonl")
    sheets = result.get("contact_sheets") or {}
    if sheets.get("sheets"):
        print(f"  {sheets['sheets']} contact sheets written")
    elif sheets.get("skipped"):
        print(f"  contact sheets skipped: {sheets['skipped']}")

    config.write_config(config.register_collection(registry, target), file_env=env)
    print(f'  saved as "{target.name}" — next time the name alone is enough')

    if service and not args.no_push:
        from lupa.publish import publish
        publish(service, target.folder_id, index_dir, index_folder=INDEX_FOLDER)

    _clear_cache(root / ".cache" / target.name)

    # Last, once everything that could be reported has been: a run with failures
    # is a failed run. Exiting 0 is what let `lupa index && lupa publish` publish
    # an index of 875 images that were never described.
    if result["failures"]:
        raise SystemExit(1)


def _clear_cache(path):
    """Downloaded originals are working copies. Keeping them wastes disk forever."""
    import shutil
    shutil.rmtree(Path(path), ignore_errors=True)


def command_forget(args):
    """Removes a collection from the registry, optionally deleting its index."""
    import shutil

    env = config.environment()
    registry = config.read_config(file_env=env)
    entry = config.find_collection(registry, args.name)
    if not entry:
        known = [c.get("name") for c in registry.get("collections") or []]
        sys.exit(f'No collection named "{args.name}". Known: {", ".join(known) or "none"}')

    registry["collections"] = [c for c in registry["collections"]
                               if c.get("name") != args.name]
    config.write_config(registry, file_env=env)
    print(f'Removed "{args.name}" from the registry.')

    index_dir = config.resolve_index_root(os.environ, env) / args.name
    if args.delete_index and index_dir.exists():
        shutil.rmtree(index_dir, ignore_errors=True)
        print(f"  deleted the local index at {index_dir}")
    elif index_dir.exists():
        print(f"  the local index is still at {index_dir} (pass --delete-index to remove it)")


def command_search(args):
    env = config.environment()
    server = Server(config.resolve_index_root(os.environ, env))
    filters = {key: getattr(args, key) for key in ("kind", "medium", "orientation")
               if getattr(args, key, None)}
    print(server.tool_search({"query": args.query, "collection": args.collection,
                              "limit": args.limit, **filters}))


def command_status(_args):
    env = config.environment()
    print(Server(config.resolve_index_root(os.environ, env)).tool_status({}))


def prepare_output_streams():
    """A Windows console is cp1252, and the report is not.

    Without this, `lupa index` dies with UnicodeEncodeError on the first line of
    the preflight report. stderr counts too: the blocker message leaves through
    it. Requiring the person to prefix PYTHONIOENCODING=utf-8 is not a fix.

    A stream that was replaced — a pipe, a StringIO, a test double — may not
    offer reconfigure. Then there is nothing to do, and nothing to say about it.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv=None):
    prepare_output_streams()

    parser = argparse.ArgumentParser(
        prog="lupa", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env", metavar="PATH",
                        help="settings file to use, overriding the search chain "
                             "(same as the LUPA_ENV variable)")
    sub = parser.add_subparsers(dest="command", required=True)

    for verb in ("index", "update"):
        entry = sub.add_parser(verb, help="index or update a collection (lupa decides which)")
        entry.add_argument("target",
                           help="Drive URL, folder id, local path, or a saved name")
        entry.add_argument("--dry-run", action="store_true", help="stop after the plan")
        entry.add_argument("--no-recursive", action="store_true",
                           help="index only the top level, not the subfolders")
        entry.add_argument("--no-batch", action="store_true",
                           help="describe one image at a time instead of one batch job "
                                "(immediate, but twice the price)")
        entry.add_argument("--no-contact-sheets", action="store_true",
                           help="skip the visual curation grids")
        entry.add_argument("--retry-failed", action="store_true",
                           help="describe again the images that failed in earlier runs")
        entry.add_argument("--resume-batch", action="store_true",
                           help="collect the batch left in flight by an earlier run "
                                "instead of submitting (and paying for) a new one")
        entry.add_argument("--workers", type=int, default=8,
                           help="parallel describe calls when not using batch mode")
        entry.add_argument("--yes", "-y", action="store_true", help="do not ask")
        entry.add_argument("--no-push", action="store_true",
                           help="do not publish the index to Drive")
        entry.add_argument("--rebuild", action="store_true",
                           help="rebuild from scratch (requires --confirm)")
        entry.add_argument("--confirm",
                           help="the collection name, typed, to unlock --rebuild")

    finder = sub.add_parser("search", help="query the index")
    finder.add_argument("query")
    finder.add_argument("--collection")
    finder.add_argument("--kind", choices=caption.KINDS)
    finder.add_argument("--medium", choices=caption.MEDIUMS)
    finder.add_argument("--orientation", choices=("portrait", "landscape", "square"))
    finder.add_argument("--limit", type=int, default=15)

    sub.add_parser("status", help="indexed collections")

    forget = sub.add_parser("forget", help="remove a collection from the registry")
    forget.add_argument("name")
    forget.add_argument("--delete-index", action="store_true",
                        help="also delete the local index directory")

    args = parser.parse_args(argv)

    # Applied before any command runs, so every path in this process resolves
    # from the file the caller chose.
    if getattr(args, "env", None):
        os.environ["LUPA_ENV"] = str(Path(args.env).expanduser())

    try:
        if args.command in ("index", "update"):
            command_index(args)
        elif args.command == "search":
            command_search(args)
        elif args.command == "forget":
            command_forget(args)
        else:
            command_status(args)
    except IndexAlreadyExists as error:
        sys.exit(f"\n✋ {error}\n")
    except LockBusy as error:
        sys.exit(f"\n⏳ {error}\n")


if __name__ == "__main__":
    main()
