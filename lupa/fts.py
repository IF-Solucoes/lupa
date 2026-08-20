"""SQLite FTS5 — a disposable projection of the catalog.

`catalog.jsonl` stays the source of truth: it is what the no-code face reads and
what survives in the collection. This database is derived, gitignored, and can be
thrown away and rebuilt at any moment. It exists for two things the flat file
cannot do well:

  · **BM25 ranking** — a term appearing in 3 images outweighs one appearing in
    3,000. Flat scoring treats them alike, which is how a good match gets buried.
  · **Conjunction and prefixes** — "printed banner blue" means all three, and
    "bann" finds "banner".

Standard library only: sqlite3 ships with Python and FTS5 is compiled into it.
"""
import json
import sqlite3
from pathlib import Path

FILTER_COLUMNS = ("kind", "medium", "orientation", "has_text")

SCHEMA = """
CREATE TABLE items (
    rowid       INTEGER PRIMARY KEY,
    id          TEXT UNIQUE,
    payload     TEXT NOT NULL,
    kind        TEXT,
    medium      TEXT,
    orientation TEXT,
    has_text    INTEGER
);
CREATE INDEX items_kind ON items(kind);
CREATE INDEX items_medium ON items(medium);
CREATE INDEX items_orientation ON items(orientation);

-- porter gives English stemming; remove_diacritics makes "café" match "cafe".
CREATE VIRTUAL TABLE fts USING fts5(
    file, caption, tags, text,
    tokenize = "porter unicode61 remove_diacritics 2"
);
"""

# Tags are curation, captions are description, OCR is incidental. FTS5 takes the
# weights in column order: file, caption, tags, text.
BM25_WEIGHTS = (2.0, 3.0, 5.0, 1.0)


def available():
    """True when this Python's sqlite3 was compiled with FTS5."""
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        connection.close()
        return True
    except sqlite3.OperationalError:
        return False


def build(catalog, db_path):
    """Rebuilds the projection from scratch. Cheap, and always consistent."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = db_path.with_suffix(".db.tmp")
    temporary.unlink(missing_ok=True)

    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(SCHEMA)
        with connection:
            for position, item in enumerate(catalog, start=1):
                connection.execute(
                    "INSERT INTO items (rowid, id, payload, kind, medium, orientation, has_text)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (position, item.get("id"), json.dumps(item, ensure_ascii=False),
                     item.get("kind"), item.get("medium"), item.get("orientation"),
                     1 if item.get("has_text") else 0))
                connection.execute(
                    "INSERT INTO fts (rowid, file, caption, tags, text) VALUES (?,?,?,?,?)",
                    (position, item.get("file") or "", item.get("caption") or "",
                     " ".join(item.get("tags") or []), item.get("text") or ""))
    finally:
        connection.close()

    temporary.replace(db_path)  # atomic swap: readers never see a half-built index
    return db_path


def _terms(raw):
    """Splits a query into FTS5-safe tokens."""
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in str(raw))
    return [token for token in cleaned.split() if token]


def _match_expression(terms, conjunction=True):
    joiner = " AND " if conjunction else " OR "
    return joiner.join(f'"{term}"*' for term in terms)


def _rows(connection, terms, filters, limit, conjunction):
    where, params = [], []
    if terms:
        where.append("fts MATCH ?")
        params.append(_match_expression(terms, conjunction))
    for column, value in (filters or {}).items():
        if column not in FILTER_COLUMNS:
            continue
        where.append(f"items.{column} = ?")
        params.append(1 if value is True else 0 if value is False else value)

    order = "ORDER BY bm25(fts, ?, ?, ?, ?)" if terms else "ORDER BY items.rowid"
    if terms:
        params += list(BM25_WEIGHTS)

    sql = ("SELECT items.payload FROM items "
           + ("JOIN fts ON fts.rowid = items.rowid " if terms else "")
           + ("WHERE " + " AND ".join(where) + " " if where else "")
           + order + " LIMIT ?")
    params.append(limit)
    return connection.execute(sql, params).fetchall()


def query(db_path, text, filters=None, limit=15):
    """Ranked results. Requires every term first; falls back to any term."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []

    terms = _terms(text)
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = _rows(connection, terms, filters, limit, conjunction=True)
        reason = "all terms"
        if not rows and len(terms) > 1:
            rows = _rows(connection, terms, filters, limit, conjunction=False)
            reason = "some terms"
        if not rows and not terms:
            reason = "filter"
    finally:
        connection.close()

    results = []
    for (payload,) in rows:
        item = json.loads(payload)
        item["_reason"] = reason if terms else "filter"
        results.append(item)
    return results
