"""Vision-model description.

The model is asked only about what metadata could not settle. It never
transcribes text (Drive already did OCR for free) and never overrides what is
already known.
"""
import json
import re

KINDS = ("photo", "design", "screenshot", "diagram", "logo", "other")
MEDIUMS = ("physical", "digital", "na")

DEFAULT_LANGUAGE = "en"
LANGUAGE_NAMES = {"en": "English", "pt": "Brazilian Portuguese", "es": "Spanish",
                  "fr": "French", "de": "German", "it": "Italian"}

# Gemini 2.5 Flash-Lite, price per 1M tokens. Batch mode halves it.
INPUT_PRICE = 0.10
OUTPUT_PRICE = 0.40
INPUT_TOKENS_PER_IMAGE = 600   # 768px thumbnail plus prompt
OUTPUT_TOKENS_PER_IMAGE = 200


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


def estimate_cost(count, batch=True):
    """Approximate dollar cost. It serves the warning before spending, not accounting."""
    if count <= 0:
        return 0.0
    inbound = count * INPUT_TOKENS_PER_IMAGE / 1_000_000 * INPUT_PRICE
    outbound = count * OUTPUT_TOKENS_PER_IMAGE / 1_000_000 * OUTPUT_PRICE
    total = inbound + outbound
    return round(total * (0.5 if batch else 1.0), 6)


def format_cost(value):
    """Cost to read, not to audit. A fraction of a cent needs no six decimals."""
    if not value:
        return "US$ 0.00"
    if value < 0.01:
        return "under US$ 0.01"
    return f"US$ {value:.2f}"
