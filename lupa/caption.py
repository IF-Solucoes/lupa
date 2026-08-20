"""Vision-model description.

The model is asked only about what metadata could not settle. It never
transcribes text (Drive already did OCR for free) and never overrides what is
already known.
"""
import json
import re
from dataclasses import dataclass

KINDS = ("photo", "design", "screenshot", "diagram", "logo", "other")
MEDIUMS = ("physical", "digital", "na")

DEFAULT_LANGUAGE = "en"
LANGUAGE_NAMES = {"en": "English", "pt": "Brazilian Portuguese", "es": "Spanish",
                  "fr": "French", "de": "German", "it": "Italian"}

INPUT_TOKENS_PER_IMAGE = 600   # 768px thumbnail plus prompt
OUTPUT_TOKENS_PER_IMAGE = 200

# Price per 1M tokens, per model — (input, output). Batch mode is exactly half on
# both, so the halving below is a property of the mode, not of any one model.
#
# Source: https://ai.google.dev/gemini-api/docs/pricing, paid tier, read 2026-08-20.
# One price per model and no global default on purpose: a single hardcoded pair is
# how this repository ended up quoting Flash-Lite 2.5 rates for whatever model the
# person had actually configured.
MODEL_PRICES = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}

INPUT_PRICE_VAR = "LUPA_INPUT_PRICE"
OUTPUT_PRICE_VAR = "LUPA_OUTPUT_PRICE"


@dataclass
class Pricing:
    """What one image-describing token costs, and — just as important — why.

    A number with no stated basis is the defect this class exists to end, so the
    origin travels with the value everywhere it goes.
    """
    model: str = ""
    input_price: float = None
    output_price: float = None
    origin: str = ""
    complaints: tuple = ()

    @property
    def known(self):
        return self.input_price is not None and self.output_price is not None


def _price_from_env(env, key):
    """One overridden price, or a complaint explaining why it was refused.

    A junk value is ignored rather than fatal, and never silently applied: this
    number only ever feeds a warning printed before spending, so crashing the run
    over a typo would be a worse outcome than falling back to the table and saying
    so out loud. Zero is a legitimate price (free tier); negative is not.
    """
    raw = (env or {}).get(key)
    if raw is None or str(raw).strip() == "":
        return None, None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None, f"{key}={raw!r} is not a number — ignored"
    if value < 0:
        return None, f"{key}={raw!r} is negative — ignored"
    return value, None


def resolve_pricing(model=None, env=None):
    """Price for a model, in the order the rest of the settings resolve.

    process environment > settings file > table for this model > unknown.
    The first two arrive already collapsed in `env` (config.environment layers the
    process on top of the file), so this only has to prefer env over table.
    """
    from lupa.gemini import DEFAULT_MODEL      # lazy: gemini reads caption too

    model = model or DEFAULT_MODEL
    table = MODEL_PRICES.get(model)
    prices, sources, complaints = {}, {}, []

    for slot, key, index in (("input", INPUT_PRICE_VAR, 0),
                             ("output", OUTPUT_PRICE_VAR, 1)):
        value, complaint = _price_from_env(env, key)
        if complaint:
            complaints.append(complaint)
        if value is not None:
            prices[slot], sources[slot] = value, key
        elif table:
            prices[slot], sources[slot] = table[index], f"the table for {model}"
        else:
            prices[slot], sources[slot] = None, ""

    if not any(sources.values()):
        origin = f"no price on record for {model}"
    elif sources["input"] == sources["output"]:
        origin = sources["input"]
    else:
        origin = f"{sources['input'] or 'nothing'} (input), " \
                 f"{sources['output'] or 'nothing'} (output)"

    return Pricing(model=model, input_price=prices["input"],
                   output_price=prices["output"], origin=origin,
                   complaints=tuple(complaints))


class InvalidResponse(Exception):
    pass


def build_prompt(meta, language=DEFAULT_LANGUAGE):
    """Asks only for what is missing. A short prompt is a cheap prompt."""
    language_name = LANGUAGE_NAMES.get(language, language)

    lines = [
        "You catalog images for a visual reference library.",
        "Reply with a single JSON object, no commentary and no code fences.",
        f"Write caption and tags in {language_name}.",
        "",
        "Required fields:",
        '  "caption": one factual sentence describing the image (20 words max).',
        '  "tags": 3 to 8 short lowercase terms.',
        '  "scene": "indoor", "outdoor" or "na".',
        '  "people": number of visible people (0 if none).',
        '  "palette": 2 to 4 dominant colors as hex codes.',
    ]

    # The kind is only asked about when metadata could not settle it.
    if meta.get("kind") is None:
        lines += [
            f'  "kind": one of {list(KINDS)}.',
            "     photo = captured photograph · design = finished artwork",
            "     screenshot = capture of a screen · diagram = chart or slide",
            "     logo = isolated brand mark · other = none of the above",
            f'  "medium": one of {list(MEDIUMS)}.',
            "     physical = printed material or a real object photographed",
            "     digital = on-screen artwork · na = not applicable",
        ]

    lines += [
        "",
        "Do NOT transcribe the text in the image — it has already been extracted.",
        "Describe composition, light, color and style. Be concrete, not poetic.",
    ]
    return "\n".join(lines)


def parse_response(text):
    """Extracts the JSON from the reply, tolerating code fences and chatter."""
    if not text:
        raise InvalidResponse("empty response from the model")

    cleaned = re.sub(r"```(?:json)?|```", "", str(text)).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise InvalidResponse(f"no JSON in the response: {cleaned[:120]!r}")
    try:
        return json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as error:
        raise InvalidResponse(f"malformed JSON: {error}") from error


def _clean_tags(raw):
    seen, out = set(), []
    for tag in raw or []:
        cleaned = str(tag).strip().lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def merge(meta, vision):
    """Fuses metadata and model output. Metadata wins wherever it had an answer."""
    vision = vision or {}

    kind = meta.get("kind")
    if kind is None:
        kind = vision.get("kind")
        kind = kind if kind in KINDS else "other"

    medium = meta.get("medium")
    if medium is None:
        medium = vision.get("medium")
        medium = medium if medium in MEDIUMS else "na"

    return {
        "id": meta.get("id"),
        "file": meta.get("file"),
        "url": meta.get("url"),
        "w": meta.get("w"), "h": meta.get("h"),
        "aspect": meta.get("aspect"), "orientation": meta.get("orientation"),
        "kind": kind, "medium": medium, "source": meta.get("source"),
        "caption": str(vision.get("caption") or ""),
        "tags": _clean_tags(vision.get("tags")),
        "scene": vision.get("scene") or "na",
        "people": int(vision.get("people") or 0),
        "palette": list(vision.get("palette") or []),
        "has_text": bool(meta.get("has_text")),
        "text": meta.get("ocr_text") or "",       # OCR from Drive, free
        "labels": list(meta.get("labels") or []),  # raw Google labels
        "hash": meta.get("hash"),
    }


def estimate_cost(count, batch=True, model=None, env=None):
    """Approximate dollar cost. It serves the warning before spending, not accounting.

    Returns None — not zero — when the model cannot be priced. Zero would be a
    quote, and quoting is precisely what a system with no price must not do; the
    preflight check is where that silence gets explained.
    """
    if count <= 0:
        return 0.0
    pricing = resolve_pricing(model, env)
    if not pricing.known:
        return None
    inbound = count * INPUT_TOKENS_PER_IMAGE / 1_000_000 * pricing.input_price
    outbound = count * OUTPUT_TOKENS_PER_IMAGE / 1_000_000 * pricing.output_price
    total = inbound + outbound
    return round(total * (0.5 if batch else 1.0), 6)


def format_cost(value):
    """Cost to read, not to audit. A fraction of a cent needs no six decimals."""
    if value is None:
        return "unknown — this model has no price on record"
    if not value:
        return "US$ 0.00"
    if value < 0.01:
        return "under US$ 0.01"
    return f"US$ {value:.2f}"
