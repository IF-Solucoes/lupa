# lupa

**A visual collection index for AI agents.** It turns a folder of images — in Google
Drive or on disk — into searchable text, so an agent can find the right image
**without opening a single one**.

```
$ lupa search "printed banner blue" --kind design --medium physical

1 candidate (out of 3,412 images):

- event-banner.jpg [design/physical, landscape] — Printed banner standing at a
  booth, white logo on blue, hall behind it
  tags: banner, event, printed, blue
  https://drive.google.com/file/d/d5/view
  matched on: tags:blue, tags:printed
```

## The problem

Ask an AI to find a reference among 3,000 photos and it will look at the photos.
Every image costs tokens; three thousand images cost enough to make you give up.
Worse, it pays that cost again on the next question.

lupa inverts this. Each image is described **once in its life**. After that, every
question is answered over text.

## How it works

1. **Collect what is already free.** Google Drive runs OCR on images and returns it
   in the file metadata. lupa harvests that — it never pays for OCR.
2. **Decide whatever metadata can decide.** EXIF, aspect ratio, format, and text
   density already tell a camera photo from a design export. Zero cost.
3. **Only then call the vision model**, and only for what is left: composition,
   light, palette, style, ambiguous types. Gemini 2.5 Flash-Lite, submitted as a
   single batch job at half price. The model never receives a 24-megapixel
   original either — it gets the 768px thumbnail Google already generated.
4. **Write a text index** inside the collection itself (`_lupa/`), at three reading
   levels, cheapest first.

From the second run on, only what changed costs anything.

### A collection is a starting point, not a flat folder

You give lupa one folder and it branches out from there: every subfolder, at any
depth, is part of the collection. A file's `file` field carries its path relative to
that root (`Campaigns/2026/story.png`), so two images named `cover.png` in different
folders stay distinguishable. The walk never enters a `_lupa/` folder, and a
shortcut loop cannot hang it.

Pass `--no-recursive` to index only the top level.

### Many collections, many projects

lupa is installed once and serves every project you work in. Each collection is
registered by name and indexed under its own directory, so indexing a folder once
makes it searchable from anywhere:

```bash
python3 -m lupa index ~/clients/acme/photos        # saved as "photos"
python3 -m lupa index "https://drive.google.com/drive/folders/1a2B3c"
python3 -m lupa status                             # every collection, anywhere

lupa_search(query="warm light", collection="photos")   # one collection
lupa_search(query="warm light")                        # all of them at once
```

Point `LUPA_INDEXES` at a path inside a repository if you want that project to keep
its own separate index instead of the shared one.

### A local folder and a Drive folder are not the same thing

You can index a folder on disk — including the one Google Drive for Desktop
synchronizes. It works, and lupa detects that case. But the Drive API gives you
three things the disk cannot:

- **the OCR Google already ran**, free — without it, text baked into artwork never
  reaches search;
- **shareable `https` links**, which other people and other agents can open;
- **an immutable id per file** — renaming a folder stops forcing a full reindex.

When you point at a mounted folder, preflight says so and carries on. The choice is
informed, not mandatory.

## Install

### In Claude Code — the full plugin

```bash
/plugin marketplace add IF-Solucoes/lupa
/plugin install lupa@lupa
```

That brings the three skills and the MCP server (`lupa_search`, `lupa_status`),
which Claude Code starts on its own. The server has no dependencies beyond the
Python standard library.

### In Claude Cowork or claude.ai — the reading face

Cowork installs skills as a zip, not as a plugin, so that face ships separately:

1. download [`dist/lupa-cowork.zip`](dist/lupa-cowork.zip) from this repository
2. in Claude: **Settings → Capabilities → Skills → +** and upload the zip

It teaches the agent to read an index that already exists in Drive, through the
connector. It executes nothing and cannot index — indexing lives in Claude Code.
Rebuild the zip after editing the skill with
`python3 scripts/build_cowork_skill.py`.

### From source

```bash
git clone https://github.com/IF-Solucoes/lupa
cd lupa && python3 -m unittest discover -s tests   # 308 tests, no network
```

To **index** (not to search) you also need:

- `pip install google-api-python-client google-auth-oauthlib` (Drive collections only)
- a [Gemini API key](https://aistudio.google.com/apikey)
- an OAuth desktop-app client from Google Cloud, with the Drive API enabled

`pip install Pillow` is optional. Without it, contact sheets are skipped and local
images are sent at full size — which works, but costs more per image. Drive
collections do not need it: the thumbnails come from Google.

## Usage

Point at the collection whichever way is easiest. lupa understands all four:

```bash
python3 -m lupa index "https://drive.google.com/drive/folders/1a2B3c"   # Drive URL
python3 -m lupa index 1a2B3c                                            # folder id
python3 -m lupa index ~/Photos/Client                                   # local path
python3 -m lupa index if-editorial                                      # saved name
```

`index` and `update` are the same command: lupa reads the index and decides whether
this is a first run or an update. **You never have to choose.**

### Every run starts with preflight

Before spending a cent, the command checks the environment, explains what is
missing, and shows the plan:

```
Preflight · collection "if-editorial"

  ✓ collection: Google Drive folder · id 1a2B3c · named "if-editorial"
  ✓ collection source: through the Drive API — with OCR and shareable links
  ✗ Gemini key: GEMINI_API_KEY is empty
      Get a key at https://aistudio.google.com/apikey and write it into
      your lupa.env    →    GEMINI_API_KEY=your-key
  ✓ index state: already exists — this is an update, only changes cost anything

Plan for this run
  +40 added · ~3 changed · -5 removed · =3364 unchanged
  images to describe: 43
  estimated cost: under US$ 0.01
```

On a `✗` it stops and spends nothing. Otherwise it shows the plan and asks before
proceeding. `--dry-run` stops right after the plan; `--yes` skips the question.

### Searching

```bash
python3 -m lupa search "bread oven warm light" --kind photo
python3 -m lupa status
python3 -m lupa forget old-collection --delete-index
```

Search runs over a SQLite FTS5 projection of the catalog, so ranking is **BM25**:
a term appearing in three images outweighs one appearing in three thousand. All
query terms are required; if nothing matches them all, it falls back to any of
them and says so in the reason. Prefixes work (`bann` finds `banner`), and the
projection is derived data — delete it and the next run rebuilds it.

Google's raw `labels` are stored but deliberately **not searchable**. They are
generic and often wrong — on a post about prioritization Drive suggested
"Heineken" and "Beryllium". Scoring them would guarantee false positives.

### Useful flags

| flag | what it does |
|---|---|
| `--dry-run` | stop after the plan, spend nothing |
| `--retry-failed` | describe again the images that failed in earlier runs |
| `--no-recursive` | index only the top level |
| `--no-batch` | one call per image, immediate but twice the price |
| `--workers N` | parallel describe calls when batch is off (default 8) |
| `--no-contact-sheets` | skip the visual curation grids |
| `--rebuild --confirm "<name>"` | rebuild from scratch, after backing up |

## The index

```
<collection>/_lupa/
├── INDEX.md          # entry point (~2 KB): counts, vocabulary, how to query
├── catalog.jsonl     # one JSON line per image — for field-level filtering
├── by-tag/<tag>.md   # inverted index, readable without running code
├── contact-sheets/   # one grid per frequent tag, for human curation
├── MANIFEST.json     # hashes — what makes updates incremental
└── runs/<date>.md    # what each run changed
```

Every catalog line follows [`schema/index-v1.json`](schema/index-v1.json):

```json
{"id":"d5","file":"event-banner.jpg","url":"https://drive.google.com/…",
 "kind":"design","medium":"physical","source":"camera","orientation":"landscape",
 "caption":"Printed banner standing at a booth, white logo on blue",
 "tags":["banner","event","printed","blue"],"has_text":true,
 "palette":["#052f41","#ffffff"],"hash":"…","v":1}
```

### The taxonomy is closed on purpose

An open taxonomy is the noise you were trying to escape. Six types, three materials,
nothing else:

| `kind` | | `medium` | |
|---|---|---|---|
| `photo` | captured photograph | `physical` | printed or a real object |
| `design` | finished artwork | `digital` | on-screen artwork |
| `screenshot` | capture of a screen | `na` | not applicable |
| `diagram` | chart, diagram, slide | | |
| `logo` | isolated brand mark | | |
| `other` | none of the above | | |

A printed mockup is `design` + `physical`. A clean photo ready to receive type is
`photo` + `has_text: false`.

## Two faces

- **Claude Code** — the plugin ships an MCP server (`lupa_search`, `lupa_status`)
  that starts automatically. Indexing happens here.
- **Cowork, claude.ai, any agent with the Drive connector** — reads the `_lupa/`
  files directly. It executes nothing, and needs nothing. The `lupa-cowork` skill
  teaches the path: `INDEX.md` → `by-tag/` → candidates.

The contract between the faces is the files. Neither knows the other exists.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | vision model key (required to index) |
| `LUPA_LANG` | `en` | language of generated captions and tags (`pt`, `es`, …) |
| `LUPA_MODEL` | `gemini-2.5-flash-lite` | model used for descriptions |
| `LUPA_CONFIRM_ABOVE` | `200` | ask before describing more images than this |
| `LUPA_ENV` | `~/.lupa/lupa.env` | where the settings file lives |
| `LUPA_CONFIG` | `~/.lupa/collections.json` | saved collection registry |
| `LUPA_INDEXES` | `~/.lupa/indexes` | local mirror of the indexes, read by the MCP |
| `LUPA_OAUTH_CLIENT` / `LUPA_OAUTH_TOKEN` | — | Google Drive credentials |

Nothing here needs to be edited by hand: the first successful run registers the
collection for you.

## Cost

Describing a thousand images in batch with Flash-Lite lands in the range of
**cents**. The arithmetic lives in `lupa/caption.py` and shows up in every
`--dry-run` before you spend.

Above 200 new images, the command asks first.

Two things keep that number honest: the model receives a 768px thumbnail rather
than the original, and the whole run goes up as one batch job at half price. Pass
`--no-batch` to trade the discount for immediate answers.

## What it does not do

It does not judge whether an image is good, beautiful, or right for a brand. It
knows nothing about clients, visual identity, or editorial direction. It produces
the index; **taste belongs to whoever consumes it**. That boundary is deliberate.

It also does no vector search and never modifies the files in your collection.

## License

MIT.
