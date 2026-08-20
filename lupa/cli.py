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
import sys
from datetime import datetime, timezone
from pathlib import Path

from lupa import caption, config, gemini
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

    from lupa.drive import connect, download, list_images
    from lupa.image import mime_of

    service = connect(env.get("LUPA_OAUTH_CLIENT"), env.get("LUPA_OAUTH_TOKEN"))

    class DriveSource:
        def list(self):
            return list_images(service, target.folder_id, recursive=recursive)

        def fetch(self, file_id):
            local = Path(cache) / file_id
            if not local.exists():
                download(service, file_id, local)
            data = local.read_bytes()
            return data, mime_of(data, file_id)

    return DriveSource(), service


def make_describer(api_key, model, language):
    def describe(item, image, mime):
        from lupa.classify import classify
        meta = {**item, **classify(item)}
        prompt = caption.build_prompt(meta, language=language)
        return gemini.describe(api_key, prompt, image, mime, model)
    return describe


def command_index(args):
    env = config.environment()
    registry = config.read_config(file_env=env)

    try:
        target = resolve_entry(args.target, registry)
    except InvalidTarget as error:
        sys.exit(f"\n{error}\n")

    root = config.resolve_index_root({}, env)

    # When Drive can be asked what the folder is called, the name comes from
    # there — nobody deserves a collection named "15fvulcdmebag7t2tm".
    client = env.get("LUPA_OAUTH_CLIENT")
    if target.kind == "drive" and client and Path(client).expanduser().exists():
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
    checks = diagnose(target, env, existing_files=None, index_exists=index_exists)
    print()
    print(format_report(checks, target))
    print()

    if has_blocker(checks):
        sys.exit("Fix the items marked ✗ and run again. Nothing was spent.\n")

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

    model = env.get("LUPA_MODEL") or gemini.DEFAULT_MODEL
    result = run_pipeline(
        collection=target.name, index_dir=index_dir, source=source,
        describe=make_describer(env.get("GEMINI_API_KEY"), model,
                                env.get("LUPA_LANG") or caption.DEFAULT_LANGUAGE),
        mode="index" if args.rebuild else "update", now=utc_stamp(),
        rebuild=args.rebuild, confirm=args.confirm, model=model)

    print()
    print(f"Done. {result['plan'].summary()}")
    print(f"  local index: {index_dir}")
    if result["failures"]:
        print(f"  {len(result['failures'])} images failed — see runs/*.errors.jsonl")

    config.write_config(config.register_collection(registry, target), file_env=env)
    print(f'  saved as "{target.name}" — next time the name alone is enough')

    if service and not args.no_push:
        _publish(service, target.folder_id, index_dir)


def _publish(service, folder_id, index_dir):
    """Publishes the index inside the collection, for clients that only have the connector."""
    from lupa.drive import ensure_folder, upload_file
    root = ensure_folder(service, folder_id, INDEX_FOLDER)
    uploaded = 0
    for entry in sorted(Path(index_dir).rglob("*")):
        if entry.is_dir() or ".backup" in entry.parts or entry.name == ".lock":
            continue
        relative = entry.relative_to(index_dir)
        folder = root
        for part in relative.parts[:-1]:
            folder = ensure_folder(service, folder, part)
        upload_file(service, folder, entry)
        uploaded += 1
    print(f"  published to Drive: {uploaded} files under {INDEX_FOLDER}/")


def command_search(args):
    env = config.environment()
    server = Server(config.resolve_index_root({}, env))
    filters = {key: getattr(args, key) for key in ("kind", "medium", "orientation")
               if getattr(args, key, None)}
    print(server.tool_search({"query": args.query, "collection": args.collection,
                              "limit": args.limit, **filters}))


def command_status(_args):
    env = config.environment()
    print(Server(config.resolve_index_root({}, env)).tool_status({}))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="lupa", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    for verb in ("index", "update"):
        entry = sub.add_parser(verb, help="index or update a collection (lupa decides which)")
        entry.add_argument("target",
                           help="Drive URL, folder id, local path, or a saved name")
        entry.add_argument("--dry-run", action="store_true", help="stop after the plan")
        entry.add_argument("--no-recursive", action="store_true",
                           help="index only the top level, not the subfolders")
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

    args = parser.parse_args(argv)
    try:
        if args.command in ("index", "update"):
            command_index(args)
        elif args.command == "search":
            command_search(args)
        else:
            command_status(args)
    except IndexAlreadyExists as error:
        sys.exit(f"\n✋ {error}\n")
    except LockBusy as error:
        sys.exit(f"\n⏳ {error}\n")


if __name__ == "__main__":
    main()
