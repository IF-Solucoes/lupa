"""Gemini client over REST. No SDK — urllib only, to keep the repository light.

Two modes: synchronous (immediate) and batch (half price, asynchronous). Batch is
the default, because indexing a collection is never urgent.
"""
import base64
import json
import time
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash-lite"


class GeminiError(Exception):
    pass


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
            raise GeminiError(f"HTTP {error.code}: {error.read()[:300]!r}") from error
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


def await_batch(api_key, batch_name, interval=20, timeout_s=3 * 3600, on_update=None):
    """Waits for the batch to finish. Returns the raw results JSONL."""
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
    raise GeminiError(f"batch did not finish within {timeout_s}s")
