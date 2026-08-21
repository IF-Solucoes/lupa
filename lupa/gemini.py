"""Gemini client over REST. No SDK — urllib only, to keep the repository light.

Two modes: synchronous (immediate) and batch (half price, asynchronous). Batch is
the default, because indexing a collection is never urgent.
"""
import base64
import json
import re
import time
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"

# Pinned on purpose, not the floating `-latest` alias: a default that changes
# under you turns "the descriptions got worse" into an unanswerable question, and
# the price table below could never keep up with it.
DEFAULT_MODEL = "gemini-3.5-flash-lite"

# The longest a run is allowed to wait on a batch. Named rather than buried in a
# default argument because it is not only await_batch's business: the index lock
# has to outlast it, and lupa.guards derives its own ceiling from this one so the
# two cannot drift apart again.
BATCH_TIMEOUT_S = 3 * 3600


# What the timeout message says when the caller gave it no command to print.
# It names the target the person typed, never "<collection>": a collection only
# enters the registry when a run finishes, and the run that has to be rescued is
# the one that did not. See cli.resume_command.
GENERIC_RESUME_HINT = "lupa update <the same target you just used> --resume-batch"


class GeminiError(Exception):
    pass


class BatchTimeout(GeminiError):
    """The wait gave up; the batch did not. It is still running, and already paid.

    Its own type because the two outcomes call for opposite handling: a batch that
    ended badly is dead and its record must go, while this one is alive, resumable,
    and its record is the only thing keeping the money reachable.
    """


class UnknownBatchState(BatchTimeout):
    """The API answered with a state this version of lupa cannot read.

    A kind of BatchTimeout, deliberately: the money is in exactly the same place.
    The batch was charged at creation and, for all this code knows, is still
    working — not understanding a state is not knowing that it died. Callers throw
    the resume record away when a batch ends badly, and doing that here would
    delete the only pointer to work already paid for.
    """


class ModelRetired(GeminiError):
    """The model was withdrawn and the key is too new to be grandfathered in.

    Its own type because the failure is total and uniform: not some images, all of
    them, every run, forever, until the model changes. Google's refusal already
    names the successor — the whole job here is to not throw that away, because a
    404 body pasted into a log is how this defect stayed invisible for 875 images.
    """

    def __init__(self, message, retired=None, replacement=None):
        super().__init__(message)
        self.retired = retired
        self.replacement = replacement


# Google's wording, seen on 2026-08-20. Matched loosely — the sentence will be
# reworded eventually, and half a match beats going back to an opaque HTTP 404.
RETIREMENT_SIGNS = ("no longer available", "has been retired", "is retired",
                    "no longer supported", "discontinued")


def _error_message(body):
    """The human sentence inside an API error body, whatever shape it arrived in."""
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
    if isinstance(parsed, list) and parsed:
        parsed = parsed[0]
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or text)
    return text


def _first(pattern, text):
    found = re.search(pattern, text, re.IGNORECASE)
    return found.group(1) if found else None


def retirement_error(status, body, url=""):
    """Turns a retired-model refusal into an error that explains itself.

    Returns None when the failure is anything else — an ordinary 404 must keep
    reading like an ordinary 404.
    """
    if status not in (400, 404):
        return None
    said = _error_message(body)
    if not any(sign in said.lower() for sign in RETIREMENT_SIGNS):
        return None

    # Google names both models: the dead one first, the live one after "use".
    # `models/x` is tried before the bare `model x`, or "model models/x" would
    # hand back the literal word "models".
    retired = (_first(r"\bmodels/([\w.\-]+)", said)
               or _first(r"\bmodel\s+([\w.\-]+)", said)
               or _first(r"/models/([\w.\-]+):", str(url)))
    replacement = _first(r"\buse\s+(?:models?/)?([\w.\-]+)", said)
    if replacement == retired:      # only one model named: no successor was offered
        replacement = None

    lines = [f"the model {retired or '(unnamed)'} has been retired by Google and no "
             f"longer accepts keys created recently — every image would fail the same "
             f"way, so nothing was spent."]
    if replacement:
        lines.append(f"  Google says to use {replacement} instead.")
        lines.append(f"  fix: set LUPA_MODEL={replacement} in your settings file, "
                     f"or upgrade lupa (its own default is {DEFAULT_MODEL}).")
    else:
        lines.append(f"  fix: set LUPA_MODEL to a model that is still served. "
                     f"lupa's own default is {DEFAULT_MODEL}.")
    lines.append(f"  Google's exact words: {said.strip()}")
    return ModelRetired("\n".join(lines), retired=retired, replacement=replacement)


def build_content(prompt, image_bytes, mime):
    """Body of a single vision request."""
    return {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime,
                             "data": base64.b64encode(image_bytes).decode()}},
        ]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }


def batch_line(key, prompt, image_bytes, mime):
    """One line of the batch input JSONL. The key comes back in the results."""
    return json.dumps({"key": str(key), "request": build_content(prompt, image_bytes, mime)},
                      ensure_ascii=False)


def _response_text(response):
    candidates = (response or {}).get("candidates") or []
    if not candidates:
        return None
    parts = candidates[0].get("content", {}).get("parts") or []
    return parts[0].get("text") if parts else None


# The names Google writes, not the ones one would guess: these are the properties
# of GenerateContentResponse.usageMetadata, the same block in the synchronous answer
# and inside each line of the batch output.
USAGE_FIELD = "usageMetadata"
INPUT_FIELD = "promptTokenCount"
OUTPUT_FIELDS = ("candidatesTokenCount", "thoughtsTokenCount")


def usage_of(response):
    """(input, output) tokens the API says it charged — or None when it said nothing.

    None, never (0, 0): a model that does not report is not a model that ran for
    free, and a zero here would quietly deflate the very total this measurement
    exists to produce.

    Thinking tokens are added to the output because that is where they are billed.
    Leaving them out would under-count exactly the models most likely to spend them.
    """
    meta = (response or {}).get(USAGE_FIELD) or {}
    if not any(field in meta for field in (INPUT_FIELD,) + OUTPUT_FIELDS):
        return None
    output = sum(int(meta.get(field) or 0) for field in OUTPUT_FIELDS)
    return int(meta.get(INPUT_FIELD) or 0), output


def read_batch_results(raw, on_usage=None):
    """Output JSONL → {key: dict}. A failed item drops out without taking the rest.

    on_usage — called once per item with usage_of(...), for the items that failed
    or came back unreadable too. They were attempted all the same, and an item left
    out of the accounting is a token that vanishes from the total.
    """
    from lupa.caption import InvalidResponse, parse_response

    out = {}
    for line in str(raw).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if on_usage is not None:
            on_usage(usage_of(record.get("response")))
        if record.get("error"):
            continue
        text = _response_text(record.get("response"))
        if not text:
            continue
        try:
            out[record.get("key")] = parse_response(text)
        except InvalidResponse:
            continue
    return out


# --- network below this line ---

def _post(url, body, api_key, attempts=3):
    payload = json.dumps(body).encode()
    request = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503) and attempt < attempts - 1:
                time.sleep(2 ** attempt)
                continue
            # Read once: the body is a stream, and the retirement notice lives in it.
            body = error.read()
            retired = retirement_error(error.code, body, url)
            if retired:
                raise retired from error
            raise GeminiError(f"HTTP {error.code}: {body[:300]!r}") from error
        except urllib.error.URLError as error:
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
                continue
            raise GeminiError(f"network unavailable: {error}") from error


def _get(url, api_key):
    request = urllib.request.Request(url, headers={"x-goog-api-key": api_key})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def describe(api_key, prompt, image_bytes, mime, model=DEFAULT_MODEL, on_usage=None):
    """Describes ONE image, now. Used by the synchronous mode and by retries.

    on_usage — called with usage_of(response) before anything else can go wrong.
    The charge happens when the answer arrives, not when it turns out to be
    usable; reporting only on success is how a run full of failures looks free.
    """
    from lupa.caption import parse_response

    url = f"{BASE}/models/{model}:generateContent"
    response = _post(url, build_content(prompt, image_bytes, mime), api_key)
    if on_usage is not None:
        on_usage(usage_of(response))
    text = _response_text(response)
    if not text:
        raise GeminiError("response had no content")
    return parse_response(text)


# --- batch mode: half price, asynchronous ---

# What the API actually answers is BATCH_STATE_*. Checked twice on 2026-08-20:
# in the live discovery document (v1beta, revision 20260816, the enum of
# GenerateContentBatch.state) and against a real batch, which reported
# BATCH_STATE_SUCCEEDED. This module used to compare against JOB_STATE_*, a
# prefix the API never sends, so no batch could ever be seen finishing: every run
# polled to the three-hour ceiling and died of BatchTimeout on work that had
# succeeded in two minutes.
#
# So the match is on the SUFFIX, not on the whole name. The prefix is the part
# Google renamed; the suffix is the part that carries the meaning, and it came
# through the rename untouched (JOB_STATE_SUCCEEDED -> BATCH_STATE_SUCCEEDED).
# Freezing whole strings from a contract somebody else owns is what turned a
# rename into a three-hour hang, and the next rename must not be able to do it
# again. Both spellings of CANCELLED are listed because that one is a coin toss
# in Google's APIs and the cost of guessing wrong is a wait that never ends.
TERMINAL_SUFFIXES = ("SUCCEEDED", "FAILED", "CANCELLED", "CANCELED", "EXPIRED")

# Not finished, and not a problem: these mean "keep waiting". Listed so that a
# state which is neither terminal nor one of these can be told apart from one
# that merely means the work is still going.
PENDING_SUFFIXES = ("PENDING", "RUNNING", "QUEUED", "UNSPECIFIED")

# How many polls in a row may report a state nobody here understands before the
# wait gives up. Three reads is a few seconds of doubt; the alternative it
# replaces is three hours of it, ending in a message about a timeout that was
# never the real cause.
UNKNOWN_STATE_LIMIT = 3

# Kept for callers that read it: the whole names, both prefixes, spelled out.
TERMINAL_STATES = tuple(f"{prefix}{suffix}" for suffix in TERMINAL_SUFFIXES
                        for prefix in ("BATCH_STATE_", "JOB_STATE_"))


def state_suffix(state):
    """The meaning-bearing tail of a state name.

    BATCH_STATE_SUCCEEDED -> SUCCEEDED, and so would ANY_NEW_PREFIX_STATE_SUCCEEDED.
    """
    text = str(state or "").strip().upper()
    return text.rsplit("STATE_", 1)[-1] if "STATE_" in text else text


def is_succeeded(state):
    return state_suffix(state) == "SUCCEEDED"


def is_terminal(state):
    """The batch is over, one way or another."""
    return state_suffix(state) in TERMINAL_SUFFIXES


def is_recognised(state):
    """This code knows what the state means — whether or not it is over."""
    return state_suffix(state) in TERMINAL_SUFFIXES + PENDING_SUFFIXES


def _upload_file(api_key, content, display_name):
    """Uploads the input JSONL through the File API (resumable protocol, two steps)."""
    payload = content.encode()
    start = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/upload/v1beta/files",
        data=json.dumps({"file": {"display_name": display_name}}).encode(),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(payload)),
            "X-Goog-Upload-Header-Content-Type": "application/jsonl",
        })
    with urllib.request.urlopen(start, timeout=60) as response:
        upload_url = response.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise GeminiError("the File API did not return an upload URL")

    finish = urllib.request.Request(
        upload_url, data=payload,
        headers={"X-Goog-Upload-Command": "upload, finalize",
                 "X-Goog-Upload-Offset": "0",
                 "Content-Length": str(len(payload))})
    with urllib.request.urlopen(finish, timeout=300) as response:
        return json.loads(response.read())["file"]["name"]


def create_batch(api_key, jsonl_lines, model=DEFAULT_MODEL, name="lupa-batch"):
    """Uploads the requests and creates the job. Returns the batch name to poll."""
    uploaded = _upload_file(api_key, "\n".join(jsonl_lines) + "\n", name)
    body = {"batch": {"display_name": name, "input_config": {"file_name": uploaded}}}
    response = _post(f"{BASE}/models/{model}:batchGenerateContent", body, api_key)
    return response.get("name") or response.get("metadata", {}).get("name")


def await_batch(api_key, batch_name, interval=20, timeout_s=BATCH_TIMEOUT_S, on_update=None,
                resume_hint=None):
    """Waits for the batch to finish. Returns the raw results JSONL.

    resume_hint — the exact command that picks this batch back up, printed in the
    timeout message. The billing happened at create_batch; giving up on the wait
    refunds nothing, so the message has to say so and hand back the name.
    """
    deadline = time.time() + timeout_s
    unreadable = 0
    while time.time() < deadline:
        job = json.loads(_get(f"{BASE}/{batch_name}", api_key))
        metadata = job.get("metadata") or {}
        state = metadata.get("state") or job.get("state")
        if on_update:
            on_update(state)

        if is_succeeded(state):
            # Three places, most reliable first. The real answer carries the file
            # in both `response.responsesFile` and `metadata.output.responsesFile`;
            # the snake_case one is a leftover kept in case an older shape shows up.
            results = ((job.get("response") or {}).get("responsesFile")
                       or (metadata.get("output") or {}).get("responsesFile")
                       or (metadata.get("output_config") or {}).get("responses_file"))
            if not results:
                raise GeminiError("batch finished without a results file")
            raw = _get(f"https://generativelanguage.googleapis.com/download/v1beta/"
                       f"{results}:download?alt=media", api_key)
            return raw.decode("utf-8", errors="replace")

        if is_terminal(state):
            raise GeminiError(f"batch ended in {state}")

        if is_recognised(state):
            unreadable = 0
        else:
            # Not knowing what the API is saying must be loud and short. Silently
            # waiting out the ceiling on an unreadable state is precisely how the
            # JOB_STATE_* defect hid for as long as it did: the only symptom was a
            # timeout, three hours after the batch had actually finished.
            unreadable += 1
            if on_update:
                on_update(f"!! unrecognised batch state {state!r} "
                          f"({unreadable}/{UNKNOWN_STATE_LIMIT}) -- lupa cannot tell "
                          f"whether this batch is running, finished or dead")
            if unreadable >= UNKNOWN_STATE_LIMIT:
                known = ", ".join(TERMINAL_SUFFIXES + PENDING_SUFFIXES)
                raise UnknownBatchState(
                    f"the API reported the batch state {state!r} {unreadable} times "
                    f"in a row, and this version of lupa does not know what it "
                    f"means. Waiting on a state nobody can read would be a silent "
                    f"wait until the {timeout_s}s ceiling, so it stops here.\n"
                    f"  the batch was ALREADY CHARGED and may still be running: "
                    f"nothing here says it failed.\n"
                    f"  state endings this version understands: {known}\n"
                    f"  batch name: {batch_name}\n"
                    f"  check it by hand: GET {BASE}/{batch_name}\n"
                    f"  resume with: "
                    f"{resume_hint or GENERIC_RESUME_HINT}")

        time.sleep(interval)

    raise BatchTimeout(
        f"batch did not finish within {timeout_s}s — but it is STILL RUNNING and "
        f"was ALREADY CHARGED. Giving up here refunds nothing; submitting it again "
        f"would pay for the same images twice.\n"
        f"  batch name: {batch_name}\n"
        f"  resume with: {resume_hint or GENERIC_RESUME_HINT}")
