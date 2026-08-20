"""Vision-model description.

The model is asked only about what metadata could not settle, and never overrides
what is already known. Transcribing the text in the image is part of the job: it
used to be forbidden here, on the belief that Drive had already done OCR for free,
and Drive never did — the field that was supposed to carry it does not exist in the
API. The only party that can read the words is the one looking at the picture.
"""
import json
import re
from dataclasses import dataclass

KINDS = ("photo", "design", "screenshot", "diagram", "logo", "other")
MEDIUMS = ("physical", "digital", "na")

DEFAULT_LANGUAGE = "en"
LANGUAGE_NAMES = {"en": "English", "pt": "Brazilian Portuguese", "es": "Spanish",
                  "fr": "French", "de": "German", "it": "Italian"}

# --- the two budgets, and the measurement they came from ---
#
# MEASURED on 2026-08-20, not estimated. One real batch run of 9 images through
# gemini-3.5-flash-lite, read off the usageMetadata the API itself returned:
#
#     12741 input · 1970 output tokens over 9 responses
#     per image: 1415.7 input · 218.9 output
#
# The input side was then split with the free countTokens endpoint, same model,
# same day:
#
#     prompt, with the kind/medium block classify() never settles ...... 333
#     the image part .......................................... 1080 to 1107
#
# The image part is FLAT: the same photograph counts 1080 tokens whether it goes
# up at 1536px, 768px, 384px or 256px. Pixels are not what is charged, so the
# 768px cap in thumbnail.py saves upload bandwidth and not one token. Every
# number quoted here before came from the tiling rule in Google's docs (~258
# tokens for one 768px tile), which this model does not follow — that mistaken
# rule is the whole of the 2.4x under-quote this replaces.
#
# 1600 covers the dearest request measured (333 + 1107 = 1440) with 11% to spare,
# and the average with 13%.
#
# Worth re-measuring when: the model changes (the flat charge is a property of
# the model, and 9 images of one collection is a small sample), the prompt below
# is rewritten, or classify() starts settling kind/medium — that last one alone
# would drop the prompt from 333 tokens to 246.
#
# The prompt HAS since been rewritten: `entities` was added to it, and the
# instruction section grew from 1325 to 1831 characters. Scaled off the 333-token
# measurement that same text produced, the prompt is now ~460 tokens, so the
# dearest request measured goes from 1440 to ~1567 and the average from 1416 to
# ~1543. Both still fit under 1600, with 2% and 4% to spare instead of 11% and
# 13%. The number is deliberately left where it is: it was set by measurement and
# moving it on an estimate would replace a measured budget with a guessed one.
# The next real run measures itself — usage_lines() below says out loud when the
# count exceeds the budget, and that is the moment to move this, with the API's
# own figure in hand.
INPUT_TOKENS_PER_IMAGE = 1600

# Same run: 218.9 output tokens per image, against the 200 guessed here before —
# the only one of the two that was nearly right. The margin is wider than the
# input's on purpose, because this is the axis that actually varies. Those same 9
# responses, re-counted through countTokens, spread from ~115 tokens for a bare
# photograph to ~416 for a text-heavy piece being transcribed, and output is
# priced 8x input on the default model, so text-heavy designs are where an
# under-quote would hurt. 275 covers the measured average with 26%.
#
# Deliberately not sized for that 416-token worst case: a budget is multiplied by
# every image in the collection, and quoting the dearest image 875 times over is
# its own kind of lie.
#
# `entities` adds to this side too, but barely: an empty list is about 6 tokens of
# JSON and the common answer, and a piece that does name two services costs some
# 15. Against a last measured average of 145.5, the field is worth single digits
# per image — the 275 here covered a 89% overshoot before and still covers one.
OUTPUT_TOKENS_PER_IMAGE = 275

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
        '  "has_text": true when words are part of the image — a headline, a caption',
        "     bar, a printed piece. false for incidental text: a small logo, a street",
        "     sign, a nameplate, a label on equipment.",
        '  "text": the words visible in the image, transcribed exactly.',
        '     Stop at 60 words: transcribe the largest and most prominent first.',
        '     "" when there are none. Never invent what you cannot read.',
        '  "entities": proper names the image carries — services, products,',
        "     campaigns, brands, people — copied as written, not translated.",
        "     [] when there are none, and that is the usual answer.",
        "     Do not invent and do not infer from context: only a name legible in",
        "     the image, or one you recognise beyond doubt. An empty list beats a",
        "     plausible name.",
        '     Names also present in "text" belong here as well: that is wanted, not',
        '     redundant — "text" is prose, this is a list to count and filter.',
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


def _as_bool(value):
    """A boolean out of whatever JSON the model felt like writing.

    `bool("false")` is True, which is how a model that answers in strings turns every
    image into one with text. The words are checked before the fallback.
    """
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)


# What a model writes into a field it has nothing to put in. Any of these would
# become a proper name of the collection — counted in INDEX.md, given a file of
# its own under by-entity/ — and would be indistinguishable from a real one.
NON_ANSWERS = {
    "none", "n/a", "na", "null", "nil", "nan", "-", "--", "?", "unknown",
    "nenhum", "nenhuma", "nada", "desconhecido", "sem nome", "no name",
    "not applicable", "no text", "sem texto", "ninguno", "aucun",
}


def _clean_entities(raw):
    """The proper names, exactly as the model wrote them.

    Case is preserved, unlike tags: `tags` are keywords and lowercase is right
    for them, while these are names, and "SESI" and "Sesi" are not the same
    string on a poster. Deduplication still ignores case, because one image
    naming a service twice is not two services.

    A model that answers with a bare string instead of a list is taken at its
    word rather than exploded into letters, and a non-answer ("none", "N/A")
    is dropped: empty is a legitimate, frequent and honest result here.
    """
    if isinstance(raw, str):
        raw = [raw]
    seen, out = set(), []
    for entity in raw or []:
        cleaned = " ".join(str(entity).split())
        key = cleaned.lower()
        if not cleaned or key in NON_ANSWERS or key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


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
        # Both from the model, and only from the model: metadata cannot see.
        "has_text": _as_bool(vision.get("has_text")),
        "text": str(vision.get("text") or "").strip(),
        # Kept out of `tags` on purpose. "what does THIS client have" and "what
        # scenes are in here" are different questions, and one list cannot be
        # sorted back into two once they are mixed.
        "entities": _clean_entities(vision.get("entities")),
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


# --- what the API actually counted, as opposed to what we budgeted for ---

class UsageMeter:
    """Adds up the token counts the API reports, over one whole run.

    The two budgets at the top of this module were written by hand and, until
    this class existed, were never once compared with the bill. This is the
    instrument that makes the comparison possible — it measures, and deliberately
    changes nothing: the budgets stay exactly where they are until somebody
    decides to move them with the numbers in hand.

    Thread-safe on purpose: the synchronous path describes up to --workers images
    at a time, and an increment lost to a race is a token nobody can ever find.
    """

    def __init__(self):
        import threading

        self._lock = threading.Lock()
        self.input_tokens = 0
        self.output_tokens = 0
        self.counted = 0      # responses that carried usageMetadata
        self.unknown = 0      # responses that did not — never counted as free

    def record(self, usage):
        """One response's (input, output), or None when it reported nothing."""
        with self._lock:
            if usage is None:
                self.unknown += 1
                return
            inbound, outbound = usage
            self.input_tokens += int(inbound)
            self.output_tokens += int(outbound)
            self.counted += 1

    @property
    def known(self):
        return self.counted > 0

    @property
    def responses(self):
        return self.counted + self.unknown

    @property
    def per_image(self):
        """Average over the responses that reported. None when none did."""
        if not self.counted:
            return None
        return (round(self.input_tokens / self.counted, 1),
                round(self.output_tokens / self.counted, 1))

    def cost(self, batch=True, model=None, env=None):
        """Dollars for the tokens actually counted. None when that cannot be known.

        None rather than zero, for the same reason estimate_cost returns None: a
        number here is a claim about money, and there is nothing to claim when
        either the price or the measurement is missing.
        """
        if not self.known:
            return None
        pricing = resolve_pricing(model, env)
        if not pricing.known:
            return None
        total = (self.input_tokens / 1_000_000 * pricing.input_price
                 + self.output_tokens / 1_000_000 * pricing.output_price)
        return round(total * (0.5 if batch else 1.0), 6)


def _money(value):
    """Cost to audit, not merely to read — this is the line that checks the quote.

    format_cost collapses everything below a cent into "under US$ 0.01", which is
    right for a warning and useless for a comparison: two numbers that both read
    "under US$ 0.01" compare to nothing.
    """
    if value is None:
        return "unknown"
    if not value:
        return "US$ 0.00"
    if value < 0.01:
        return f"US$ {value:.6f}"
    return f"US$ {value:.2f}"


def _gap(counted, budget):
    """How far the measurement sits from the budget, in words."""
    if not budget:
        return "no budget on record"
    share = abs(counted - budget) / budget * 100
    return f"{share:.1f}% {'over' if counted > budget else 'under'} budget"


def usage_lines(usage, estimated_cost=None, batch=True, model=None, env=None):
    """The lines that close the cycle: what was quoted, against what was charged.

    Returned as a list so the same measurement can be printed on the screen and
    written into the run report without either one paraphrasing the other.

    An empty list means there was nothing to measure at all — no meter was wired
    in. A meter that heard nothing is different, and says so out loud: silence
    from the API is a fact worth reporting, never a zero.
    """
    if usage is None:
        return []

    if not usage.known:
        from lupa.gemini import USAGE_FIELD      # lazy: gemini reads caption too

        lines = [f"Tokens the API counted: unknown — no response carried "
                 f"{USAGE_FIELD}"]
        if usage.unknown:
            lines.append(f"  {usage.unknown} responses arrived without it, so this "
                         f"run could not be measured")
        lines.append(f"  the estimate of {_money(estimated_cost)} therefore stands "
                     f"unchecked against the bill")
        return lines

    inbound, outbound = usage.per_image
    lines = [
        f"Tokens the API counted: {usage.input_tokens} input · "
        f"{usage.output_tokens} output, over {usage.counted} responses",
        f"  per image: {inbound} input · {outbound} output",
        f"  input:  {inbound} counted vs {INPUT_TOKENS_PER_IMAGE} budgeted — "
        f"{_gap(inbound, INPUT_TOKENS_PER_IMAGE)}",
        f"  output: {outbound} counted vs {OUTPUT_TOKENS_PER_IMAGE} budgeted — "
        f"{_gap(outbound, OUTPUT_TOKENS_PER_IMAGE)}",
    ]
    if usage.unknown:
        lines.append(f"  {usage.unknown} of {usage.responses} responses did not "
                     f"report usage — they are not in the totals above")

    actual = usage.cost(batch=batch, model=model, env=env)
    mode = "batch, half price" if batch else "synchronous, full price"
    lines.append(f"  estimated before spending: {_money(estimated_cost)} · "
                 f"actually counted: {_money(actual)} ({mode})")

    # Two different alarms, kept apart on purpose. A budget can be exceeded on one
    # axis while the run still costs less than it quoted — input and output are
    # priced an order of magnitude apart — and conflating the two would raise a
    # false alarm about money, the exact failure this measurement exists to end.
    breached = [name for name, counted, budget in
                (("input", inbound, INPUT_TOKENS_PER_IMAGE),
                 ("output", outbound, OUTPUT_TOKENS_PER_IMAGE))
                if counted > budget]
    if breached:
        lines.append(f"  the {' and '.join(breached)} budget on record no longer "
                     f"covers what the API counted per image")
    if actual is not None and estimated_cost is not None and actual > estimated_cost:
        lines.append("  this run cost more than it quoted before spending")
    return lines
