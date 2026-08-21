"""lupa command line.

  lupa index  <target>     index a collection — the target is a Drive URL, a
  lupa update <target>     folder id, a local path, or the name of a collection
                           already indexed. Both verbs do the same thing: lupa
                           reads the index and decides whether this is a first
                           run or an update.

  lupa map    <target>     step 0: what is in there — how many files lupa can
                           index, and how many it will ignore in silence
                           (video, PSD, PDF, Google Docs). Costs nothing, needs
                           no API key, and is not part of preflight: it is a
                           full walk of the collection.

  lupa search "<terms>"    query
  lupa status              what is indexed

Every run goes through preflight: environment checks, plan and cost, before any
spending.
"""
import argparse
import os
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from lupa import caption, config, gemini, inflight
from lupa.build import writing_atomically
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


def shell_quote(value):
    """Quotes an argument so the printed command survives a copy and a paste.

    On Windows the target is a path, and a path has a space in it more often
    than not: unquoted, C:\\Users\\me\\Minhas Fotos reaches argparse as two
    arguments and the command dies on the second one.
    """
    text = str(value)
    if text and not any(character.isspace() for character in text):
        return text
    return '"' + text.replace('"', '\\"') + '"'


def resume_command(target_as_typed, collection=""):
    """The line to paste to collect a batch that has already been paid for.

    It names the target the person actually typed — the one that resolved a
    moment ago, in this very run — and not the collection name on its own.

    The distinction is the whole point. A collection reaches the registry at the
    END of a run that finished (`config.register_collection`, last thing in
    command_index), and the run that has to be rescued is by definition the run
    that did not finish: it was killed, or the terminal was closed, while it
    waited on a batch already charged. Reproduced live with a real paid batch —
    the run printed `lupa update lote-prova --resume-batch`, and that command
    answered `I could not make sense of "lote-prova"`. The instruction that
    exists to recover money sent the user into a dead end.

    command_index now also registers the collection before it spends, so the
    short name resolves too; this stays as it is anyway, because it does not
    depend on a write to disk having worked.
    """
    typed = str(target_as_typed or "").strip() or str(collection or "").strip()
    if not typed:
        return None
    return f"lupa update {shell_quote(typed)} --resume-batch"


class LocksByKey:
    """One lock per key, alive only for as long as somebody is holding it.

    Two subtleties, both of which bite:

    Creating the lock must itself be atomic. `locks.setdefault(key, Lock())`
    reads as safe but builds a Lock on every call and, worse, a plain
    `if key not in locks` check lets two threads install two different locks for
    the same key — a lock that protects nothing, which is the bug it was added
    to prevent.

    The table must not grow with the collection. An acervo of thousands of
    images would otherwise leave one dead Lock per image in memory for the whole
    run. Refcounting the entry and dropping it on the way out bounds the table
    by the number of fetches IN FLIGHT (at most --workers), not by the number of
    images ever fetched.
    """

    def __init__(self):
        self._guard = threading.Lock()
        self._held = {}

    @contextmanager
    def __call__(self, key):
        with self._guard:
            entry = self._held.get(key)
            if entry is None:
                entry = self._held[key] = [threading.Lock(), 0]
            entry[1] += 1
        try:
            with entry[0]:
                yield
        finally:
            with self._guard:
                entry[1] -= 1
                if entry[1] <= 0:
                    self._held.pop(key, None)


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
            # In batch mode the same file_id arrives here from two concurrent
            # paths — the pipeline worker (which wants the thumbnail) and the
            # batch assembly loop. Without this lock both find the cache empty
            # and both download the same bytes.
            self.downloading = LocksByKey()

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
            with self.downloading(file_id):
                if not local.exists():
                    # Downloaded to <file_id>.part and renamed into place. The
                    # rename is atomic, so `local` is either absent or whole and
                    # no thread can ever read a file that is still arriving —
                    # reading one meant a TRUNCATED image going to the model,
                    # being paid for, and landing in the index looking exactly
                    # like a legitimate description. A transfer that dies takes
                    # its .part with it instead of poisoning the cache.
                    with writing_atomically(local, suffix=".part") as partial:
                        download(service, file_id, partial)
                data = local.read_bytes()
            mime = mime_of(data, file_id)
            return downscale(data, mime), mime

    return DriveSource(), service


def make_describer(api_key, model, language, on_usage=None):
    """One call per image, immediate. Used when batch mode is off or unavailable.

    on_usage — where the token counts the API reports are handed off, one call per
    answer. Optional so nothing that only wants descriptions has to know about it.
    """
    def describe(item, image, mime):
        from lupa.classify import classify
        meta = {**item, **classify(item)}
        prompt = caption.build_prompt(meta, language=language)
        return gemini.describe(api_key, prompt, image, mime, model, on_usage=on_usage)
    return describe


def make_batch_describer(api_key, model, language, source, ids, on_progress=print,
                         index_dir=None, collection="", resume_batch=None,
                         on_usage=None, target_as_typed=None):
    """Half the price: every image goes up in one job, answers come back keyed.

    The batch is submitted on the first call and then served from memory, so the
    pipeline keeps its one-image-at-a-time shape without paying per request.

    resume_batch — the name of a batch already submitted and already charged. Given
    one, nothing is uploaded and nothing is created: the job is only waited on.

    on_usage — the token counts, one call per item in the results file. A resumed
    batch reports too: the answers being already paid for does not make them free
    to measure, and the numbers are in the file either way.

    target_as_typed — what the user wrote on the command line. It is what the
    timeout message tells them to type again, because it is the one form that is
    certain to resolve: it just did. See resume_command.
    """
    from lupa.classify import classify

    state = {"results": None, "error": None}
    hint = resume_command(target_as_typed, collection)
    # One run, one batch. The pipeline calls describe() from a pool of --workers
    # threads (8 by default) and every one of them arrives here before the first
    # has an answer to store, so a guard that only reads a flag lets all eight
    # build and PAY FOR their own batch — and each one re-downloads every image
    # to do it. This lock is what makes the submission happen once.
    gate = threading.Lock()

    def _submit(items_by_id):
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
                    inflight.remember(index_dir, job, collection, model, ids,
                                      on_warning=on_progress)
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
        except gemini.BatchTimeout as timed_out:
            # Said here, whole, before anything downstream can trim it. The
            # pipeline files a timeout as one failed image among others and the
            # run report flattens every error to 200 characters — which cut the
            # batch name in half ("batches/xyz-7…") and dropped the resume
            # command off the end altogether. That command and that name are the
            # only way back to money already spent; the last place they may
            # appear is a file nobody reads while the screen says FAILED.
            on_progress("")
            for line in str(timed_out).splitlines():
                on_progress(f"  {line}")
            raise                       # still running, still resumable: keep the record
        except gemini.GeminiError:
            if index_dir is not None:   # ended badly: there is nothing left to resume
                inflight.forget(index_dir)
            raise

        state["results"] = gemini.read_batch_results(raw, on_usage=on_usage)
        if index_dir is not None:
            inflight.forget(index_dir)  # consumed: it must not be resumable again
        on_progress(f"  batch returned {len(state['results'])} descriptions")

    def ensure_submitted(items_by_id):
        """Double-checked: the flag is read outside the lock, so once the answers
        are in memory the other workers never queue at all.

        The lock is held across the whole of _submit — assembly, create_batch AND
        await_batch — not just around the create call. Everything in there is one
        indivisible purchase: a thread that took the lock only for the creation
        would still be building its own set of lines, re-fetching every image, and
        would still find results empty when it came back. Holding it through the
        long wait costs nothing real either: the other workers have no work until
        the answers exist, so they would be blocked on the same thing anyway. A
        second of dumb waiting is cheaper than a second batch.
        """
        if state["results"] is not None:
            return
        with gate:
            if state["results"] is not None:
                return
            # A submission that failed stays failed for everyone. Retrying under
            # the lock would create a second batch out of the first one's timeout
            # — the exact bill this lock exists to prevent.
            if state["error"] is not None:
                raise state["error"]
            try:
                _submit(items_by_id)
            except BaseException as failure:
                state["error"] = failure
                raise

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
    # Every way out of here is printed as a command to paste, so it names the
    # target the user just typed rather than the collection name: the run whose
    # batch is in flight is a run that died before registering anything.
    resume = resume_command(getattr(args, "target", None), collection)

    if getattr(args, "dry_run", False):
        if record:
            print(f"  note: {inflight.describe(record)} is registered as in flight "
                  f"for this collection — it was already charged.")
            print(f"  collect it with:  {resume}\n")
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
                f"  Collect it:            {resume}\n"
                f"  Or give it up (the money stays spent, the images get paid for "
                f"again):\n"
                f"      delete {inflight.record_path(index_dir)}\n")
        return None

    try:
        return inflight.load_for_resume(index_dir, collection, model, plan.to_describe)
    except inflight.BatchDrift as error:
        sys.exit(f"\n✋ {error}\n")


def _nothing_found(target, recursive=True):
    """What a FIRST run with an empty plan actually means, said out loud.

    An empty plan reads two completely different ways depending on whether an
    index already exists, and until now both got the same line — "Nothing changed
    since the last run" — including on a collection that had never had a run.

    The silent case is the expensive one. Drive answers `files.list` for a folder
    the account is not allowed to see with an empty list, not with an error: point
    lupa at a client folder nobody shared with you and it looked, character for
    character, like a successful incremental no-op. Same for the wrong subfolder.
    """
    from lupa.local_source import EXTENSIONS

    if target.kind == "drive":
        subfolder = ("the right folder, wrong level — the images live in a "
                     "subfolder and the walk was told not to descend "
                     "(--no-recursive)"
                     if not recursive else
                     "the right folder, wrong level — this is a subfolder that "
                     "holds nothing itself, or a folder whose images are all in "
                     "Drive's trash")
        causes = [
            "the wrong folder — the URL points at another folder, or at a "
            "shortcut rather than the folder itself",
            subfolder,
            "no permission to read it — Drive answers a listing you are not "
            "allowed to see with an EMPTY LIST, never with an error, so a folder "
            "that was never shared with this account looks exactly like this",
            "the folder really has nothing to describe — only files whose type "
            "is a supported image get listed, so documents, videos and Google "
            "Docs stay invisible even when the folder looks full",
        ]
    else:
        formats = " · ".join(sorted(extension.lstrip(".") for extension in EXTENSIONS))
        causes = [
            "the wrong folder — the path points somewhere else",
            "the right folder, wrong level — the images live in a subfolder"
            + ("" if recursive else ", and --no-recursive was passed"),
            "no permission to read it, or a Google Drive folder mounted on disk "
            "that has not synced this folder yet — either way the listing comes "
            "back empty instead of failing",
            f"the folder really has no image in a supported format ({formats})",
        ]

    lines = [
        "✋ Nothing found to index — this is NOT a success.",
        "",
        f'  This is the first run for "{target.name}", and the collection came '
        f"back with no image at all.",
        "  Nothing was indexed, nothing was described, nothing was spent.",
        "",
        "  What causes this, most common first:",
    ]
    lines += [f"    · {cause}" for cause in causes]
    lines += ["", "  Check what the folder actually contains, then run again.", ""]
    return "\n".join(lines)


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
                      env_file=config.env_path(), rebuild=args.rebuild)
    print()
    print(format_report(checks, target))
    print()

    if has_blocker(checks):
        sys.exit("Fix the items marked ✗ and run again. Nothing was spent.\n")

    if args.retry_failed and args.rebuild:
        # Not a contradiction, but not a no-op either, and that is the problem:
        # --retry-failed EDITS MANIFEST.json, here, before the pipeline takes the
        # backup that is supposed to preserve it. Under --rebuild the manifest is
        # ignored anyway — every image is described again — so the edit buys
        # nothing and damages the copy. Skipped, out loud.
        print("  --retry-failed does nothing under --rebuild: a rebuild describes "
              "every image again.\n  Skipping it, so the backup keeps the manifest "
              "exactly as it is now.\n")
    elif args.retry_failed:
        from lupa.recovery import forget_failed, read_failures
        retried = forget_failed(index_dir, read_failures(index_dir))
        print(f"  retrying {retried} images that failed in earlier runs\n"
              if retried else "  no earlier failures to retry\n")

    source, service = build_source(target, env, root / ".cache" / target.name,
                                  recursive=not args.no_recursive)

    # Both hoisted above the preview, because the preview is what produces the
    # only total on the screen. Resolved lower down, the preview quoted batch
    # price for the default model no matter what this run was about to do: a
    # --no-batch run was quoted at half of what it charges, and LUPA_MODEL
    # pointing at a pricier model was quoted at the cheap one's price.
    model = env.get("LUPA_MODEL") or gemini.DEFAULT_MODEL
    use_batch = str(env.get("LUPA_BATCH", "1")).strip() not in ("0", "false", "no")

    # rebuild travels with the preview, or the plan and the price printed below
    # describe a run nobody asked for: without it the preview reconciles against
    # the manifest that --rebuild discards, and an unchanged collection prints
    # "0 images to describe · US$ 0.00" for a run about to re-describe all of it.
    preview = run_pipeline(collection=target.name, index_dir=index_dir, source=source,
                           describe=lambda *a: {}, mode="update", now=utc_stamp(),
                           dry_run=True, rebuild=args.rebuild,
                           batch=use_batch and not args.no_batch,
                           model=model, env=env)
    plan = preview["plan"]
    pending = len(plan.to_describe)

    print("Plan for this run")
    print(f"  {plan.summary()}")
    print(f"  images to describe: {pending}")
    print(f"  estimated cost: {caption.format_cost(preview['estimated_cost'])}")
    print()

    # Registered here, before a cent is spent, and not only at the end of a run
    # that finished. A run that dies waiting on a batch already charged is the
    # one run whose name has to resolve afterwards — and the registration at the
    # bottom of this function is exactly the line it never reaches. An entry
    # whose index does not exist yet costs nothing: only resolve_entry and
    # `lupa forget` read the registry, so the worst case is that a name resolves
    # to a collection with nothing indexed in it, which is what the next run
    # would build anyway. --dry-run is excluded because it promises to write
    # nothing.
    if not args.dry_run:
        registry = config.register_collection(registry, target)
        config.write_config(registry, file_env=env)

    # Before anything this run might spend: money it may have spent already.
    resume_batch = _settle_inflight_batch(args, index_dir, target.name, model, plan)

    if plan.empty:
        # Two different events wore the same sentence. With an index on disk an
        # empty plan is the incremental working — the promise of the tool. Without
        # one, nothing was found at all, and saying "since the last run" about a
        # run that never happened is how a folder nobody had permission to read
        # got reported as a successful indexing.
        if index_exists:
            print("Nothing changed since the last run. "
                  "Nothing to do, nothing to pay.\n")
            return

        print(_nothing_found(target, recursive=not args.no_recursive))
        # --dry-run keeps its 0: it inspected, and it never claimed to have done
        # anything. A real run must not, because the exit code is the only part
        # of this a script — or an agent following the skill — actually reads.
        if args.dry_run:
            print("(--dry-run: stopping here, nothing was written)\n")
            return
        raise SystemExit(1)

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
    # A resume is never a per-image run: those answers are already bought and
    # waiting, and describing again would pay full price for the same images.
    batch_mode = bool(resume_batch) or (use_batch and not args.no_batch)

    # One meter for the whole run, filled by whichever describer ends up spending.
    # It exists so the estimate printed above can be checked against the bill
    # instead of being taken on faith, as it has been until now.
    meter = caption.UsageMeter()

    if batch_mode:
        remote = {item["id"]: item for item in source.list()}
        describer = make_batch_describer(api_key, model, language, source,
                                         plan.to_describe, index_dir=index_dir,
                                         collection=target.name,
                                         resume_batch=resume_batch,
                                         on_usage=meter.record,
                                         target_as_typed=args.target)
        describer.items_by_id = remote
    else:
        describer = make_describer(api_key, model, language, on_usage=meter.record)

    result = run_pipeline(
        collection=target.name, index_dir=index_dir, source=source,
        describe=describer, batch=batch_mode,
        mode="index" if args.rebuild else "update", now=utc_stamp(),
        rebuild=args.rebuild, confirm=args.confirm, model=model,
        contact_sheets=not args.no_contact_sheets, workers=max(1, args.workers),
        usage=meter)

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


    # Already written before the spending started; repeated here because it is
    # idempotent and because this is where the user is told about it.
    config.write_config(config.register_collection(registry, target), file_env=env)
    print(f'  saved as "{target.name}" — next time the name alone is enough')

    # Last of everything the run says, because it is what the run came back to
    # answer. Above this point every figure was a promise made before spending;
    # this is the only place the API's own count is put next to it.
    measured = caption.usage_lines(result.get("usage"),
                                   estimated_cost=result.get("estimated_cost"),
                                   batch=batch_mode, model=model, env=env)
    if measured:
        print()
        for line in measured:
            print(line)

    # Publishing is how a run leaves the machine, and it is the one step that
    # touches somebody else's Drive. The exit code below says the run failed, but
    # it is only read by whatever comes next — by then the push already happened,
    # and an index with holes has overwritten one that had none. So the failure
    # holds the push back here, where it can still be held.
    if service and not args.no_push:
        if result["failures"]:
            print()
            print(f"  not published: {len(result['failures'])} images failed, "
                  "and a partial index must not overwrite the one on Drive.")
            print(f"    lupa index {args.target} --retry-failed")
        else:
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


def scan_progress(stream=None):
    """Something on the screen while a large collection is being listed.

    Listing the 875 images of the first real collection took ninety-five seconds
    in total silence, and the honest reading of a silent terminal is that the
    thing has hung.

    On a terminal the line is rewritten in place. When stderr is a file or a
    pipe there is no cursor to move, so it prints a line every so often instead:
    a log full of carriage returns is worse than no log.
    """
    stream = stream or sys.stderr
    started = time.monotonic()
    state = {"drawn": 0.0, "in_place": False}

    def report(folders, files):
        now = time.monotonic()
        interactive = bool(getattr(stream, "isatty", lambda: False)())
        if interactive:
            if now - state["drawn"] < 0.2:
                return
            state["in_place"] = True
        elif folders % 25:
            return
        state["drawn"] = now
        text = f"  scanning… {folders} folders · {files} files · {now - started:.0f}s"
        stream.write(f"\r{text}" if interactive else f"{text}\n")
        stream.flush()

    def done():
        if state["in_place"]:
            stream.write("\r" + " " * 72 + "\r")
            stream.flush()

    return report, done


def command_map(args):
    """Step 0: what is in there, before anything is indexed or paid for.

    Deliberately NOT part of preflight. Preflight runs before every indexing run
    and has to be quick; mapping a collection is a full walk of it. And it is
    deliberately not an indexing verb — it needs no GEMINI_API_KEY, reaches no
    model, and this function must never grow a code path that does.
    """
    from lupa import mapping

    env = config.environment()
    registry = config.read_config(file_env=env)

    try:
        target = resolve_entry(args.target, registry)
    except InvalidTarget as error:
        sys.exit(f"\n{error}\n")

    if target.kind == "drive":
        client = env.get("LUPA_OAUTH_CLIENT")
        if not (client and Path(client).expanduser().exists()):
            sys.exit(
                f"\nNo Google Drive access: no OAuth client at "
                f"{client or '(not configured)'}\n"
                "  At https://console.cloud.google.com :\n"
                "    1. enable the Google Drive API on your project\n"
                "    2. Credentials → Create → OAuth client ID → Desktop app\n"
                "    3. download the JSON and save it as the LUPA_OAUTH_CLIENT path\n"
                "  A local folder needs none of this — pass a path instead.\n")
        from lupa.drive import connect, folder_name
        from lupa.target import slugify
        service = connect(client, env.get("LUPA_OAUTH_TOKEN"))
        try:
            target.name = slugify(folder_name(service, target.folder_id))
        except Exception:
            pass                     # no permission to read the name: keep the id
        walk = mapping.drive_walk(service, target.folder_id)
        heading, title = "Drive map", f'"{target.name}" · {target.folder_id}'
        # Drive answers a listing you are not allowed to see with an empty list
        # rather than an error, so "empty" and "not shared with you" arrive
        # identical. Same sentence the index skill already relays.
        empty_hint = ("Drive answers a folder you cannot see with an empty list, "
                      "not an error — check it was shared with this account.")
    else:
        walk = mapping.local_walk(target.path)
        heading, title = "Folder map", f'"{target.name}" · {target.path}'
        empty_hint = ""

    report, done = scan_progress()
    try:
        tree = mapping.build_tree(walk, kind=target.kind, on_progress=report)
    finally:
        done()

    print()
    print(mapping.render(tree, title, depth=args.depth, heading=heading,
                         empty_hint=empty_hint))

    # Written where INDEX.md will live, so the search agent finds it in the one
    # place it already looks. `map` runs BEFORE any index exists, so this may be
    # the first file in that directory — which is fine: MANIFEST.json is what
    # marks a collection as indexed, and MAP.md is not it.
    destination = (Path(args.out).expanduser() if args.out else
                   config.resolve_index_root(os.environ, env) / target.name / "MAP.md")
    mapping.write_map(destination, tree, title, heading=heading)
    print(f"  written to {destination}")
    print("  nothing was indexed and nothing was spent — to index it: "
          f"python -m lupa index {shell_quote(args.target)}\n")


def command_search(args):
    env = config.environment()
    server = Server(config.resolve_index_root(os.environ, env))
    filters = {key: getattr(args, key) for key in ("kind", "medium", "orientation")
               if getattr(args, key, None)}
    # The catalog stores has_text as a JSON boolean and the filter is an equality
    # test, so the string "false" would quietly match nothing at all.
    if getattr(args, "has_text", None) is not None:
        filters["has_text"] = args.has_text == "true"
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
    # Two spellings on purpose: `has_text` is how the field is written in the
    # catalog, in the schema and in the MCP, and hyphens are what every other
    # flag here uses. Whoever copies either one gets a search, not a parse error.
    finder.add_argument("--has-text", "--has_text", dest="has_text",
                        choices=("true", "false"),
                        help="true keeps only images with text baked in, "
                             "false only the clean ones")
    finder.add_argument("--limit", type=int, default=15)

    # Its own subcommand, sharing nothing with the loop above on purpose. `map`
    # spends no money and describes no image, so every flag that guards spending
    # would be a lie here — and inheriting them is how a command ends up
    # accepting --rebuild and quietly doing nothing with it.
    mapper = sub.add_parser(
        "map", help="what is in a collection, before indexing any of it (free)")
    mapper.add_argument("target",
                        help="Drive URL, folder id, local path, or a saved name")
    mapper.add_argument("--depth", type=int, default=2,
                        help="how many folder levels to print (default 2); "
                             "anything deeper is folded into the row above it")
    mapper.add_argument("--out", metavar="PATH",
                        help="where to write MAP.md "
                             "(default: <index root>/<collection>/MAP.md)")

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
        elif args.command == "map":
            command_map(args)
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
