"""Search over the written catalog. No network, no model, no embeddings.

The query is textual and the filters are exact. Results carry `_score` and
`_reason` — a consumer has to know WHY something matched in order to trust the list.
"""
import unicodedata

DEFAULT_LIMIT = 15

# Where a term matched matters: a tag is curation, the text baked into the image is
# incidental. `text` is the model's transcription — it used to be a Drive field that
# never existed, so it was empty in every index written before that was fixed.
#
# `labels` is not scored, and is no longer written: it came out of the same phantom
# field. Indexes written earlier still carry the key, empty; reading it costs nothing
# and scoring it would only invite false positives.
WEIGHTS = {"tags": 5, "caption": 3, "file": 2, "text": 1}


def _normalize(text):
    """Lowercase and accent-free, on both sides of the comparison."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _fields(item):
    return {
        "tags": " ".join(item.get("tags") or []),
        "caption": item.get("caption") or "",
        "file": item.get("file") or "",
        "text": item.get("text") or "",
    }


def _passes_filters(item, filters):
    return all(item.get(key) == value for key, value in (filters or {}).items())


def _score(item, terms):
    """Sums the weight of every field where a term appears."""
    fields = {name: _normalize(value) for name, value in _fields(item).items()}
    total, reasons, matched = 0, [], set()

    for term in terms:
        for name, content in fields.items():
            if term in content:
                total += WEIGHTS[name]
                reasons.append(f"{name}:{term}")
                matched.add(term)

    # Matching more distinct terms beats matching one term in many fields.
    total += 10 * len(matched)
    return total, reasons, matched


def search(catalog, query, filters=None, limit=DEFAULT_LIMIT):
    """Returns up to `limit` items ranked by relevance, each with _score/_reason."""
    terms = [_normalize(t) for t in str(query).split() if t.strip()]
    results = []

    for item in catalog:
        if not _passes_filters(item, filters):
            continue

        if not terms:  # filter-only query: everything that passed
            results.append(dict(item, _score=0, _reason="filter"))
            continue

        total, reasons, matched = _score(item, terms)
        if not matched:
            continue
        if total:
            results.append(dict(item, _score=total, _reason=", ".join(reasons)))

    results.sort(key=lambda r: (-r["_score"], r.get("id", "")))
    return results[:limit]
