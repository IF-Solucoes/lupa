"""Preflight: before any run, tell the person what is about to happen.

It is not optional and not a flag. Every execution goes through it: check the
environment, explain what is missing and how to fix it, then show the plan and the
cost. Whoever calls lupa needs to know nothing about credentials, folder ids, or
which verb to use — preflight settles that.
"""
from dataclasses import dataclass
from pathlib import Path

from lupa.mount import looks_like_mounted_drive

OK = "ok"
WARNING = "warning"
BLOCKER = "blocker"

SYMBOL = {OK: "✓", WARNING: "!", BLOCKER: "✗"}


@dataclass
class Check:
    name: str
    status: str
    message: str
    how_to_fix: str = ""


def has_blocker(checks):
    return any(check.status == BLOCKER for check in checks)


def _exists(path, known):
    if not path:
        return False
    if known is not None:
        return str(path) in known
    return Path(str(path)).expanduser().exists()


def diagnose(target, env, existing_files=None, index_exists=False, env_file=None):
    """Returns the checks, in reading order.

    env_file is the settings file actually in use — naming it beats telling the
    reader to edit "your env file" and leaving them to find which one.
    """
    settings = str(env_file) if env_file else "your settings file"
    checks = []

    # 1. The collection
    if target.kind == "drive":
        checks.append(Check(
            "collection", OK,
            f'Google Drive folder · id {target.folder_id} · named "{target.name}"'))
        checks.append(Check("collection source", OK,
                            "through the Drive API — with OCR and shareable links"))
    else:
        checks.append(Check(
            "collection", OK, f'local folder {target.path} · named "{target.name}"'))

        if looks_like_mounted_drive(target.path):
            checks.append(Check(
                "collection source", WARNING,
                "this folder looks like Google Drive mounted on disk",
                "It works as is. But if you paste the Drive folder URL "
                "(.../drive/folders/<id>), lupa gets three things for free:\n"
                "      · the OCR Google already ran — without it, text baked into "
                "the images never reaches search\n"
                "      · shareable https links, which Cowork and other people can open\n"
                "      · an immutable id per file, so renaming the folder stops "
                "forcing a full reindex"))
        else:
            checks.append(Check(
                "collection source", OK,
                "local folder — no free OCR, so the model works a little harder"))

    # 2. Vision model key
    if env.get("GEMINI_API_KEY"):
        checks.append(Check("Gemini key", OK, "configured"))
    else:
        checks.append(Check(
            "Gemini key", BLOCKER, "GEMINI_API_KEY is empty",
            "Get a key at https://aistudio.google.com/apikey and write it into\n"
            f"      {settings}    →    GEMINI_API_KEY=your-key"))

    # 3. Drive credentials, only when the target is Drive
    if target.kind == "drive":
        client = env.get("LUPA_OAUTH_CLIENT")
        if _exists(client, existing_files):
            checks.append(Check("Google Drive access", OK, "OAuth client found"))
        else:
            checks.append(Check(
                "Google Drive access", BLOCKER,
                f"no OAuth client at {client or '(not configured)'}",
                "At https://console.cloud.google.com :\n"
                "      1. enable the Google Drive API on your project\n"
                "      2. Credentials → Create → OAuth client ID → Desktop app\n"
                "      3. download the JSON and save it as the LUPA_OAUTH_CLIENT path"))

        if _exists(env.get("LUPA_OAUTH_TOKEN"), existing_files):
            checks.append(Check("Google sign-in", OK, "session stored"))
        else:
            checks.append(Check(
                "Google sign-in", WARNING, "no stored session yet",
                "On the first run a browser window opens once for you to authorize. "
                "After that, never again."))

    # 4. What this run will do
    if index_exists:
        checks.append(Check(
            "index state", OK,
            "already exists — this is an update, only changes cost anything"))
    else:
        checks.append(Check(
            "index state", OK,
            "does not exist yet — this is the first run, everything gets described"))

    return checks


def format_report(checks, target):
    """The readable report. This is what a person reads before deciding."""
    lines = [f'Preflight · collection "{target.name}"', ""]
    for check in checks:
        lines.append(f"  {SYMBOL[check.status]} {check.name}: {check.message}")
        if check.how_to_fix:
            for line in check.how_to_fix.split("\n"):
                lines.append(f"      {line}" if not line.startswith("      ") else line)
    return "\n".join(lines)
