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


def _money(value):
    """A price written the way a price sheet writes it: 0.10, not 0.1 — while a
    third decimal that carries information (0.125) is never rounded away."""
    digits = f"{value:.6f}".rstrip("0")
    whole, _, fraction = digits.partition(".")
    return f"{whole}.{fraction.ljust(2, '0')}"


def _cost_check(env, model):
    """What this run's estimate is worth, and where its number came from.

    The estimate used to be one hardcoded pair of prices printed with full
    confidence for whatever model happened to be configured. So the price now
    reports its own provenance, and an unpriceable model warns instead of quoting:
    a number nobody can trace is worse than an admitted blank.
    """
    from lupa.caption import (INPUT_PRICE_VAR, OUTPUT_PRICE_VAR, MODEL_PRICES,
                              resolve_pricing)

    pricing = resolve_pricing(model, env)
    listed = ", ".join(sorted(MODEL_PRICES))

    if not pricing.known:
        return Check(
            "cost estimate", WARNING,
            f"no price on record for {model} — any estimate shown for this run is "
            f"NOT reliable",
            f"Either point at a model whose price is known:\n"
            f"        LUPA_MODEL=<one of: {listed}>\n"
            f"or state the price yourself, per 1M tokens:\n"
            f"        {INPUT_PRICE_VAR}=0.30\n"
            f"        {OUTPUT_PRICE_VAR}=2.50\n"
            f"Current prices: https://ai.google.dev/gemini-api/docs/pricing")

    money = (f"US$ {_money(pricing.input_price)} in / "
             f"US$ {_money(pricing.output_price)} out per 1M tokens "
             f"for {model} · from {pricing.origin} · batch halves it")

    if pricing.complaints:
        return Check("cost estimate", WARNING,
                     f"{money} — but {'; '.join(pricing.complaints)}",
                     "A price must be a number and cannot be negative. The value "
                     "was ignored and the fallback above used instead.")
    return Check("cost estimate", OK, money)


def diagnose(target, env, existing_files=None, index_exists=False, env_file=None,
             model=None):
    """Returns the checks, in reading order.

    env_file is the settings file actually in use — naming it beats telling the
    reader to edit "your env file" and leaving them to find which one.

    model defaults to the one this run would actually use, resolved exactly as the
    caller resolves it. Passing it explicitly is for tests and for a caller that
    already knows; leaving it out must never report on a different model than the
    one about to be billed.
    """
    from lupa.gemini import DEFAULT_MODEL

    env = env or {}
    model = model or env.get("LUPA_MODEL") or DEFAULT_MODEL
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

    # 4. What the money says
    checks.append(_cost_check(env, model))

    # 5. What this run will do
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
