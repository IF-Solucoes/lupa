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
- Drive's own OCR, which exists but is not a field. Google does read the text inside
  images and makes it searchable: `q="fullText contains 'sua consulta'"` returns
  `Externo.jpg`, whose name contains none of those words. It is a query against
  Drive, not a property of a file, so it cannot be harvested per image at listing
  time — it would be a second search path, in Drive's index rather than in ours.
  **lupa does not use it today.**
- A skill for the reading face. `skills/cowork/SKILL.md` shipped one until it was
  retired: lupa is invoked from Claude Code, where the MCP answers and `lupa-search`
  is the way in, so the skill had no caller. It was also the third copy of the field
  taxonomy — after `skills/search/SKILL.md` and the generated `INDEX.md` — and had
  already drifted away from both. What the reading face needs is written where it is
  read, inside `INDEX.md`.

## 4. Findings that shaped the design

Four verified facts, each with a direct consequence:

1. **Drive returns no text to lupa — and never did.** This project was built on the
   opposite belief: that `contentSnippet` carried the OCR Google had already run,
   plus an `Image labels` list, for free. That field is not part of the Drive v3
   `File` resource. Pulling a real image with `fields="*"` returns 45 properties and
   not one of them holds text, so `text` was empty and `has_text` false on 875 of the
   875 images of the first real collection, from the first commit onward.
   → *Consequence:* the only party that can read the words in a picture is the one
   looking at it. The vision model transcribes them (~90 extra output tokens per
   image, inside the budget already quoted), and nothing may be classified from text
   before the model has answered. `labels` is retired.

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
- **The reading face** — any agent that can open the files, through the Drive
  connector or otherwise, and **reads** the index instead of the images. It
  executes no code, and lupa ships nothing for it (see §3): the reading
  instructions travel inside `INDEX.md`, with the index they describe.

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

Metadata asserts what it can prove; everything that needs eyes waits for the model:

| Signal | Cost | Decides |
|---|---|---|
| Geometry (`w`/`h`) | zero | `aspect` and `orientation` — arithmetic |
| EXIF (`Make`/`Model`) | zero | camera present → `source: camera`; absent → `generated` |
| Vision model | already paid | `kind`, `medium`, `has_text`, the transcribed `text`, the named `entities`, caption, tags, palette |

`tags` and `entities` are two lists on purpose. Tags are generic — the vocabulary of 875 images from one veterinary clinic was `dog`, `medical`, `clinic`, `gloves`: true of every clinic on earth, and therefore worth nothing to the agency that owns this one. `entities` holds the proper names written on the pieces — the services, products, campaigns, brands and people. Merged into one list they could never be separated again, and "what does this client specifically have" would stay unanswerable. The model is told never to infer one: an invented proper noun is worse than an empty field, because a proper noun is what a reader stops checking.

The heuristics that used to sit between the two — text density decides
`design`/`diagram`, aspect ratio decides social design — were removed rather than
tuned. Both hinged on `has_text`, which came from the Drive field that does not
exist and was therefore false everywhere: `camera` alone then decided `photo`/`na`
for 510 of the 875 images of the first real collection, a printed banner among them.
A heuristic answering a question it has no data for does not save money, it writes a
wrong answer into the index.

### 5.5 Where the collection comes from — and why that still matters

The user points at the collection whichever way is easiest: a Drive folder URL, a
bare id, a local path, or the name of a collection already indexed. lupa resolves it;
nobody needs to know what a `folder_id` is, and nobody edits a config file by hand
(the first successful run registers the collection).

The origin is not neutral, though. Through the Drive API you get two things the
disk cannot provide:

| | folder on disk | Drive API |
|---|---|---|
| describing, classifying, searching, incremental updates | identical | identical |
| text found inside the images | the model transcribes it | the model transcribes it — Drive contributes none |
| link in the result | `file://…`, useless off-machine | `https://…`, opens anywhere |
| file identity | the path: renaming forces a reindex | immutable `id` |

The ambiguous case is a **Google Drive for Desktop folder mounted on disk**. It looks
local and is Drive. lupa detects it (`lupa/mount.py`) and preflight explains what the
URL would buy — **without blocking**. The choice is informed, not mandatory.

### 5.6 A collection is a starting point, not a flat folder

Indexing begins at one folder and branches into everything beneath it, at any depth.
Both sources behave the same way: the local source walks with `rglob`, and the Drive
source walks the folder tree breadth-first (`walk_folders`), since Drive's
`'<id>' in parents` query only ever returns direct children.

Three rules keep the walk honest:

- the `file` field carries the path relative to the collection root, so two images
  named `cover.png` in different folders remain distinguishable;
- a `_lupa/` folder is never entered — a collection does not index its own index;
- visited folder ids are tracked, so a Drive shortcut loop cannot hang the walk.

`--no-recursive` restricts a run to the top level.

Because collections are registered by name and indexed under separate directories,
one installation serves every project: index a folder once and it is searchable from
anywhere, either by name or across all collections at once.

### 5.7 Preflight is mandatory

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
- The reading face executes nothing. Where there is no Python, the index still reads.
- Every path is configurable by environment variable, with a portable default under
  `~/.lupa`.

## 8.1 Search: a disposable SQLite projection

`catalog.jsonl` stays the source of truth — it is what the no-code face reads and
what travels with the collection. Alongside it, each run rebuilds an `index.db`
(SQLite + FTS5), which is derived, gitignored, never published, and thrown away
whenever convenient.

It exists for three things a flat scan does badly:

- **BM25 ranking.** Flat per-field weights treat a term in 3 images and a term in
  3,000 as equals, which buries the match that actually identifies the image.
- **Conjunction and prefixes.** "printed banner blue" means all three; `bann`
  should find `banner`. Both come free with FTS5.
- **Scale.** Measured over 50,000 items: 1,019 ms scanning the catalog versus
  43 ms through the projection — 23× — and the MCP no longer parses a 21 MB file
  on every call.

Rebuilding costs about a second per 50,000 items and the module degrades cleanly:
where sqlite3 lacks FTS5, or the database is missing, search falls back to the
flat scan.

## 8.2 Cost control

Two decisions keep the estimate honest rather than optimistic:

- **Thumbnails, not originals.** A 24-megapixel photograph costs several times a
  768px thumbnail and buys nothing for describing composition. Drive collections
  reuse the thumbnail Google already generated (free, no dependency); local
  collections downscale with Pillow when it is installed.
- **Batch by default.** The whole run goes up as one Gemini batch job at half
  price. `--no-batch` trades the discount for immediate answers, and parallelizes
  across a thread pool instead.

## 8.3 Durability

Every index file is written through a temporary file and renamed into place. A
crash mid-write would otherwise leave a truncated catalog, and a truncated catalog
costs a full reindex to repair.

Images that fail are recorded per run in `runs/<date>.errors.jsonl`.
`--retry-failed` drops those ids from the manifest, which is what turns them back
into new work on the next reconciliation.

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

1. **Reading the index through the connector.** The reading face depends on the Drive
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
