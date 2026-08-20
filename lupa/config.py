"""Configuration. Secrets and collection registry live outside any repository.

Paths default to a portable location and can be pointed anywhere with environment
variables — nobody has to edit a config file by hand.
"""
import json
import os
from pathlib import Path

DEFAULT_ENV = "~/.lupa/lupa.env"
DEFAULT_CONFIG = "~/.lupa/collections.json"
DEFAULT_INDEX_ROOT = "~/.lupa/indexes"

# Where the settings file is looked for, in order. A shared file comes first so
# that one .env can serve several tools belonging to the same person; the
# tool-specific path is the fallback and the portable default. `LUPA_ENV`
# overrides the whole chain.
ENV_SEARCH_CHAIN = (
    Path("~/.francis/.env").expanduser(),
    Path(DEFAULT_ENV).expanduser(),
)

SETTINGS = ("GEMINI_API_KEY", "LUPA_MODEL", "LUPA_BATCH", "LUPA_LANG", "LUPA_STATE_DIR",
            "LUPA_CONFIRM_ABOVE", "LUPA_OAUTH_CLIENT", "LUPA_OAUTH_TOKEN",
            "LUPA_ENV", "LUPA_CONFIG", "LUPA_INDEXES")


def first_existing(candidates):
    """The first path that exists; otherwise the last candidate, so callers always
    get something to report in an error message."""
    candidates = list(candidates)
    if not candidates:
        return None
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def env_path():
    """Where the settings file lives. LUPA_ENV overrides the search chain."""
    if os.environ.get("LUPA_ENV"):
        return Path(os.environ["LUPA_ENV"]).expanduser()
    return first_existing(ENV_SEARCH_CHAIN)


def config_path(file_env=None):
    """Where the collection registry lives.

    Order: process environment > the env file > portable default. When no env is
    handed in, the file is read here — otherwise a caller that passes nothing and a
    caller that passes the env would resolve to different files, and one of them
    would silently write to the wrong place.
    """
    chosen = (os.environ.get("LUPA_CONFIG")
              or (file_env if file_env is not None else read_env()).get("LUPA_CONFIG")
              or DEFAULT_CONFIG)
    return Path(chosen).expanduser()


def read_env(path=None):
    """A .env parser — no dependency for a ten-line job."""
    source = Path(str(path)).expanduser() if path else env_path()
    if not source.exists():
        return {}

    values = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value.startswith("~"):
            value = str(Path(value).expanduser())
        values[key.strip()] = value
    return values


def environment(path=None):
    """Values from the file, with the process environment layered on top."""
    values = read_env(path)
    for key in SETTINGS:
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def read_config(path=None, file_env=None):
    source = Path(str(path)).expanduser() if path else config_path(file_env)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"collections": []}


def write_config(config, path=None, file_env=None):
    destination = Path(str(path)).expanduser() if path else config_path(file_env)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(config, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def find_collection(config, name):
    for collection in (config or {}).get("collections") or []:
        if collection.get("name") == name:
            return collection
    return None


def register_collection(config, target):
    """Stores the collection so that next time the short name is enough.

    Nobody edits the file by hand: the first successful run registers it.
    """
    config = dict(config or {})
    collections = [dict(entry) for entry in config.get("collections") or []]

    entry = {"name": target.name}
    if target.kind == "drive":
        entry["folder_id"] = target.folder_id
    else:
        entry["path"] = str(target.path)

    for index, existing in enumerate(collections):
        if existing.get("name") == target.name:
            collections[index] = {**existing, **entry}
            break
    else:
        collections.append(entry)

    config["collections"] = collections
    return config


def target_from_registry(entry):
    """Turns a registry entry back into a Target."""
    from lupa.target import Target
    if entry.get("folder_id"):
        return Target("drive", entry["name"], folder_id=entry["folder_id"])
    return Target("local", entry["name"], path=Path(entry["path"]).expanduser())


def resolve_index_root(process_env, file_env):
    """Where the local mirror of the indexes lives — what the MCP reads.

    The canonical index lives with the collection. This is the working mirror.
    Order: explicit variable > LUPA_STATE_DIR from the env file > portable default.
    """
    if process_env.get("LUPA_INDEXES"):
        return Path(process_env["LUPA_INDEXES"]).expanduser()
    if file_env.get("LUPA_STATE_DIR"):
        return Path(file_env["LUPA_STATE_DIR"]).expanduser() / "indexes"
    return Path(DEFAULT_INDEX_ROOT).expanduser()
