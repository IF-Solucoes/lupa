# lupa — a visual collection index for agents

**Status:** implemented · **Schema:** v1

---

## 1. The problem

An image collection is opaque to an agent. To find one reference it has to look at
the images, and looking at images is expensive. With hundreds of files the cost
makes the whole approach unusable.

Collections are also heterogeneous. Raw photographs, finished posts, printed
mockups, and screenshots all live in the same folder. Without separating them, every
search returns noise.

## 2. Goal

A text index of the collection that any agent can read cheaply, and that stays
current without being rebuilt.

| Verb | Does | Cost |
|---|---|---|
| `index` / `update` | the same command: lupa reads the index and decides whether this is a first pass or a reconciliation | once per image, then only the delta |
| `search` | queries and returns ≤15 candidates with URL and reason | zero |

The user never chooses between `index` and `update` — the program decides.

## 3. Non-goals (the boundary)

lupa is infrastructure without opinion. It does **not** know what a client, a brand,
a visual identity, or an editorial line is. Judging fitness belongs to the consuming
skill.

Deliberately out of scope:

- Judging whether an image is good, beautiful, or on-brand.
- A global controlled tag vocabulary.
- Embeddings and vector search. The text index covers the use case.
- Editing the collection's files. lupa only creates the files under `_lupa/`.

## 4. Findings that shaped the design

Four verified facts, each with a direct consequence:

1. **Drive already returns OCR and labels, for free.** The connector exposes, in
   `contentSnippet`, the text extracted from the image plus an `Image labels` list.
   The OCR is excellent. The labels are generic noise — on a post about
   prioritization, Google suggested "Heineken" and "Beryllium".
   → *Consequence:* the vision model never pays for OCR or object detection. It
   fills only the gap: composition, palette, light, style.

2. **The Drive connector cannot edit existing files.** It can only create new files
   in a chosen folder.
   → *Consequence:* the index is a **file**, never metadata on the indexed files.
   This also makes both faces identical.

3. **Claude Code plugins carry MCP servers natively**, through a `.mcp.json` at the
   plugin root using `${CLAUDE_PLUGIN_ROOT}`. The client starts and stops the stdio
   server itself, on any operating system.
   → *Consequence:* the MCP travels inside the repository. Nobody needs a specific
   shell, a port, a daemon, or a manual install.

4. **Gemini 2.5 Flash-Lite describes well and judges poorly.** It is built for
   classification and extraction at volume, not for aesthetic judgment.
   → *Consequence:* two passes. The wide one (Flash-Lite, cents) covers the whole
   collection. The narrow one (the agent's own model) looks only at the 8–15
   finalists the search returned.

## 5. Architecture

### 5.1 Two faces, one contract

- **Claude Code face** — a plugin with an embedded MCP server. Runs all verbs and
  does the heavy work: fetching thumbnails, calling Gemini, writing the index.
- **Cowork / claude.ai face** — a `SKILL.md` that teaches an agent to **read** the
  index through the Drive connector. It executes no code.

The contract between them is the files under `_lupa/`. Neither face knows the other.

### 5.2 Index layout

```
<collection>/_lupa/
├── INDEX.md            # entry point: counts, vocabulary, how to query
├── catalog.jsonl       # one line per image — machine reading
├── by-tag/<tag>.md     # inverted index — cheap reading without code
├── contact-sheets/     # visual grids for human curation
├── MANIFEST.json       # hashes and state; what makes updates incremental
├── runs/<date>.md      # report for each run
└── .backup/<ts>/       # the previous index, kept before any rebuild
```

Three reading levels, cheapest first: `INDEX.md` (~2 KB, always) → `by-tag/` (only
the relevant tags) → `catalog.jsonl` (only when fields must be crossed).

`INDEX.md` opens by stating the rule that sustains the economics: **read text, never
pixels**. If you must look, look at the finalists.

### 5.3 Catalog line schema (v1)

See [`schema/index-v1.json`](../schema/index-v1.json). Versioned on purpose: a
consumer that breaks is a consumer that ignored the version field.

### 5.4 Type classification

A **closed** taxonomy — an open one is precisely the noise we are avoiding:

- `kind`: `photo` · `design` · `screenshot` · `diagram` · `logo` · `other`
- `medium`: `physical` · `digital` · `na`

There is no `mockup`. A mockup is `design` + `physical`. The consumer decides
whether that is past work or raw material for a new render.

Classification starts deterministic; the vision model only breaks ties:

| Signal | Cost | Decides |
|---|---|---|
| EXIF (`Make`/`Model`) | zero | camera present → `source: camera`; absent → `generated` |
| Aspect ratio | zero | 4:5, 9:16, 1:1 → social design; large 3:2, 4:3 → photograph |
| OCR density | zero | lots of text → `design`/`diagram`; none → `photo` |
| Format | zero | large PNG without EXIF → design export |
| Vision model | already paid | `medium` (physical vs digital) and the ambiguous cases |

### 5.5 Where the collection comes from — and why that still matters

The user points at the collection whichever way is easiest: a Drive folder URL, a
bare id, a local path, or the name of a collection already indexed. lupa resolves it;
nobody needs to know what a `folder_id` is, and nobody edits a config file by hand
(the first successful run registers the collection).

The origin is not neutral, though. Through the Drive API you get three things the
disk cannot provide:

| | folder on disk | Drive API |
|---|---|---|
| describing, classifying, searching, incremental updates | identical | identical |
| OCR and labels for free | absent | in the metadata, zero cost |
| link in the result | `file://…`, useless off-machine | `https://…`, opens anywhere |
| file identity | the path: renaming forces a reindex | immutable `id` |

The ambiguous case is a **Google Drive for Desktop folder mounted on disk**. It looks
local and is Drive. lupa detects it (`lupa/mount.py`) and preflight explains what the
URL would buy — **without blocking**. The choice is informed, not mandatory.

### 5.6 Preflight is mandatory

It is not a flag; it is the first stage of every run. It:

1. resolves the target and discovers the collection's real name (the folder name,
   not the id);
2. checks the Gemini key, Drive credentials, sign-in session, and collection source;
3. stops on any `✗`, **spending nothing**, printing the fix step by step;
4. runs the dry run and shows the plan and the cost;
5. only then asks whether to proceed.

The error message is the documentation. Whoever calls lupa — person or agent — gets
the exact instruction instead of a traceback.

## 6. Incremental updates

`MANIFEST.json` stores `id → hash` for everything already described. Each update
lists metadata from the source (seconds, zero tokens) and reconciles by sets:

| Situation | Detection | Action | Cost |
|---|---|---|---|
| added | id present remotely, absent from the manifest | describe | pays |
| changed | id present, checksum differs | describe again | pays |
| removed / trashed | id in the manifest, absent remotely | drop the catalog line | zero |
| unchanged | id and hash both match | skip | **zero** |

Running `update` twice with no change in between costs nothing.

## 7. Guardrails

The dangerous verb is a rebuild. Four layers, cheapest first:

1. A normal run never overwrites — it reconciles.
2. Rebuilding requires typing the collection name: `--rebuild --confirm "<name>"`.
   That passes neither by accident nor by an agent's autocomplete.
3. Every rebuild copies the previous index to `.backup/<timestamp>/` first. The
   operation is reversible.
4. Cost ceiling: above `LUPA_CONFIRM_ABOVE` new images (200 by default), the command
   shows the plan and waits. `--dry-run` plans without spending.

A `.lock` file under `_lupa/` keeps two concurrent runs from scrambling the manifest.
A lock older than 30 minutes is treated as orphaned and reclaimed.

## 8. Portability

The repository is public and cannot assume its author's environment:

- No platform-specific shell calls and no absolute paths from one machine.
- The MCP server is stdio and dependency-free — the client starts it. No port, no
  daemon, no service.
- The Cowork face executes nothing. Where there is no Python, the index still reads.
- Every path is configurable by environment variable, with a portable default under
  `~/.lupa`.

## 9. Success criteria

`scripts/postcheck.py` validates the index; the test suite covers the rest.

1. Indexing a fresh collection produces a complete `_lupa/`, valid against the schema.
2. Rebuilding without confirmation writes nothing and explains why.
3. An update with no changes makes zero Gemini calls and zero downloads.
4. An update after adding, replacing and deleting files reflects all three.
5. `search` answers in under a second over 10,000 lines.
6. An agent with no code execution can answer "which portrait photos have no text"
   by reading only `INDEX.md` and one `by-tag/` file.
7. No file in the collection is ever modified. Only `_lupa/` is written.

## 10. Known risks

Three points that only a real collection can confirm:

1. **Reading the index through the connector.** The Cowork face depends on the Drive
   connector reading `.md` and `.jsonl` as text. That is the expected behavior, but
   it deserves verification before the face is promised — it is success criterion 6.
2. **Searching inside the catalog without code.** Drive's own `search_files` is not
   reliable for filtering lines of a large `.jsonl`. `by-tag/` exists precisely so
   that nothing depends on it.
3. **Gemini batch mode requires a billing-enabled project.** Without it, batch fails
   and the cost doubles in synchronous mode. The command should detect and warn,
   rather than fail mid-run.

## 11. Deferred

- Vector search (CLIP) for visual similarity queries.
- Drive's `changes.list` with `startPageToken`, replacing the full listing.
- Additional collection sources (S3, other cloud drives).
