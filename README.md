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
   light, palette, style, ambiguous types. Gemini 2.5 Flash-Lite, in batch.
4. **Write a text index** inside the collection itself (`_lupa/`), at three reading
   levels, cheapest first.

From the second run on, only what changed costs anything.

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

```bash
git clone https://github.com/IF-Solucoes/lupa
cd lupa && python3 -m unittest discover -s tests   # 220 tests, no network
```

As a Claude Code plugin, the MCP server starts on its own — it has no dependencies
beyond the Python standard library.

To **index** (not to search) you also need:

- `pip install google-api-python-client google-auth-oauthlib` (Drive collections only)
- a [Gemini API key](https://aistudio.google.com/apikey)
- an OAuth desktop-app client from Google Cloud, with the Drive API enabled

Scopes used: `drive.readonly` to read the collection and `drive.file` to write
**only** the files lupa itself creates. It never modifies a file of yours.

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
```

## The index

```
<collection>/_lupa/
├── INDEX.md          # entry point (~2 KB): counts, vocabulary, how to query
├── catalog.jsonl     # one JSON line per image — for field-level filtering
├── by-tag/<tag>.md   # inverted index, readable without running code
├── contact-sheets/   # visual grids, for human curation
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

## What it does not do

It does not judge whether an image is good, beautiful, or right for a brand. It
knows nothing about clients, visual identity, or editorial direction. It produces
the index; **taste belongs to whoever consumes it**. That boundary is deliberate.

It also does no vector search and never modifies the files in your collection.

## License

MIT.
