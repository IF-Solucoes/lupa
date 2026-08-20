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


class GeminiError(Exception):
    pass


class BatchTimeout(GeminiError):
    """The wait gave up; the batch did not. It is still running, and already paid.

    Its own type because the two outcomes call for opposite handling: a batch that
    ended badly is dead and its record must go, while this one is alive, resumable,
    and its record is the only thing keeping the money reachable.
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


def read_batch_results(raw):
    """Output JSONL → {key: dict}. A failed item drops out without taking the rest."""
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


def describe(api_key, prompt, image_bytes, mime, model=DEFAULT_MODEL):
    """Describes ONE image, now. Used by the synchronous mode and by retries."""
    from lupa.caption import parse_response

    url = f"{BASE}/models/{model}:generateContent"
    response = _post(url, build_content(prompt, image_bytes, mime), api_key)
    text = _response_text(response)
    if not text:
        raise GeminiError("response had no content")
    return parse_response(text)


# --- batch mode: half price, asynchronous ---

TERMINAL_STATES = ("JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED",
                   "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED")


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


def await_batch(api_key, batch_name, interval=20, timeout_s=3 * 3600, on_update=None,
                resume_hint=None):
    """Waits for the batch to finish. Returns the raw results JSONL.

    resume_hint — the exact command that picks this batch back up, printed in the
    timeout message. The billing happened at create_batch; giving up on the wait
    refunds nothing, so the message has to say so and hand back the name.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = json.loads(_get(f"{BASE}/{batch_name}", api_key))
        state = (job.get("metadata") or {}).get("state") or job.get("state")
        if on_update:
            on_update(state)

        if state == "JOB_STATE_SUCCEEDED":
            results = ((job.get("response") or {}).get("responsesFile")
                       or (job.get("metadata") or {}).get(
                           "output_config", {}).get("responses_file"))
            if not results:
                raise GeminiError("batch finished without a results file")
            raw = _get(f"https://generativelanguage.googleapis.com/download/v1beta/"
                       f"{results}:download?alt=media", api_key)
            return raw.decode("utf-8", errors="replace")

        if state in TERMINAL_STATES:
            raise GeminiError(f"batch ended in {state}")

        time.sleep(interval)

    raise BatchTimeout(
        f"batch did not finish within {timeout_s}s — but it is STILL RUNNING and "
        f"was ALREADY CHARGED. Giving up here refunds nothing; submitting it again "
        f"would pay for the same images twice.\n"
        f"  batch name: {batch_name}\n"
        f"  resume with: {resume_hint or 'lupa update <collection> --resume-batch'}")
