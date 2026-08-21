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

1. **Settle what metadata settles, for free.** Dimensions, aspect ratio, orientation,
   and — from EXIF — whether a camera took the picture. Arithmetic and facts stamped
   by the device: zero cost and zero guessing.
2. **Ask the vision model everything that needs eyes**: type and material,
   composition, light, palette, style, and the words baked into the image, which it
   transcribes. Gemini Flash-Lite (`LUPA_MODEL`), submitted as a single batch job at
   half price. The model never receives a 24-megapixel original either — it gets the
   768px thumbnail Google already generated.
3. **Write a text index** inside the collection itself (`_lupa/`), at three reading
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

On Windows, write `python` in every command below: `python3` there is the Microsoft
Store stub, which prints an advertisement and runs nothing. And `python -m lupa`
imports the package from the current directory — run it from the repository root, or
from the plugin folder that holds `lupa/`.

Point `LUPA_INDEXES` at a path inside a repository if you want that project to keep
its own separate index instead of the shared one.

### A local folder and a Drive folder are not the same thing

You can index a folder on disk — including the one Google Drive for Desktop
synchronizes. It works, and lupa detects that case. But the Drive API gives you two
things the disk cannot:

- **shareable `https` links**, which other people and other agents can open;
- **an immutable id per file** — renaming a folder stops forcing a full reindex.

What gets *described* is identical either way: the caption, the tags and the text
transcribed from inside the image all come from the vision model, never from Drive.

When you point at a mounted folder, preflight says so and carries on. The choice is
informed, not mandatory.

## Install

Cowork and Code both install this as a plugin, from the same repository.

### Add the marketplace, then install

**In Claude Code:**

```bash
/plugin marketplace add IF-Solucoes/lupa
/plugin install lupa@lupa
```

**In Claude Cowork:** Customize → Plugins → **Add marketplace** → `IF-Solucoes/lupa`,
then install it from the list.

Either way you get both skills and the MCP server (`lupa_search`,
`lupa_status`), which the client starts on its own. The server has no dependencies
beyond the Python standard library.

### Or upload the package

Cowork's Plugins page also accepts a plugin as a file — useful behind a proxy, for
an offline install, or when a marketplace refresh misbehaves. Download
[`dist/lupa.zip`](dist/lupa.zip) and upload it. Rebuild it after changing the
plugin with `python3 scripts/build_plugin_package.py`.

### Where the skills run

| skill | what it does | where |
|---|---|---|
| `lupa-index` | builds and updates the index | Claude Code |
| `lupa-search` | queries it through the MCP | Claude Code |

Both need local execution: indexing downloads images, calls Gemini and writes
files, and search reads a SQLite projection on disk. No skill ships for a surface
without code execution.

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

### Step 0: `lupa map` — what is in there, before paying for any of it

```bash
python -m lupa map "https://drive.google.com/drive/folders/1a2B3c"
python -m lupa map ~/Photos/Client --depth 3
```

It walks the folders and counts the files by type. No download, no model call, no
`GEMINI_API_KEY` — there is no version of this command that costs money.

It answers what an index cannot: **what gets left out.** `lupa index` lists only
images in a format it supports, so video, PSD, PDF and Google Docs never appear in
an index, a plan, or a cost. They are simply absent. On the first real collection
that was 152 files — 75 of them video — sitting invisibly beside the 875 images.

```
Drive map · "cvn-clinica-veterinaria-noroeste" · 1a2B3c
free · names and types only — no download, no model call, no API key

    6 - Linha Editorial /                        272 indexable · 14 ignored
    4 - Fotos & Vídeos /                         489 indexable · 75 ignored
      Vídeos /                                   ignored: 53 mp4 · 21 mov
      Tratamento de Fotos/                       489 jpg · ignored: 1 mp4

  total: 875 indexable · 152 ignored (mp4 54 · pdf 46 · mov 21 · fig 11 · …)
```

Two levels are printed by default; `--depth N` opens more, and the folding is
announced rather than silent. It also writes `MAP.md` next to where the index will
live — a sibling of `INDEX.md`, readable by the search agent — or wherever `--out`
says.

It is **not** part of preflight, on purpose: preflight runs before every indexing
run and has to be quick, and a map is a full walk of the collection.

### Every run starts with preflight

Before spending a cent, the command checks the environment, explains what is
missing, and shows the plan:

```
Preflight · collection "if-editorial"

  ✓ collection: Google Drive folder · id 1a2B3c · named "if-editorial"
  ✓ collection source: through the Drive API — with shareable links and a stable id per file
  ✗ Gemini key: GEMINI_API_KEY is empty
      Get a key at https://aistudio.google.com/apikey and write it into
      your lupa.env    →    GEMINI_API_KEY=your-key
  ✓ index state: already exists — this is an update, only changes cost anything

Plan for this run
  +40 added · ~3 changed · -5 removed · =3364 unchanged
  images to describe: 43
  estimated cost: US$ 0.03
```

On a `✗` it stops and spends nothing. Otherwise it shows the plan and asks before
proceeding. `--dry-run` stops right after the plan; `--yes` skips the question.

### Publishing an index that already exists

```bash
python -m lupa publish cvn-clinica-veterinaria-noroeste
```

A run that describes images publishes the result at the end, unless you pass
`--no-push`. A collection with nothing left to describe never reaches that step —
it stops at "Nothing changed" — so an index that is finished, or one built with
`--no-push`, needs this verb to reach the Drive folder it belongs to. It
describes nothing and costs nothing.

Publishing reconciles: pages the index no longer has are moved to the Drive
trash rather than left beside the current ones. It never does that on an empty
plan, so a broken read cannot empty a client's folder.

### Searching

```bash
python3 -m lupa search "bread oven warm light" --kind photo
python3 -m lupa fetch "https://drive.google.com/file/d/1a2B3c/view" --out ./work
python3 -m lupa status
python3 -m lupa forget old-collection --delete-index
```

### `lupa fetch` — bring the file to disk

Search tells you what exists and why it fits; `fetch` brings it down. Without
this the loop does not close: the agent finds the right image and is left holding
a URL it cannot open.

```
python3 -m lupa fetch <id | url | path> --out ./work
```

The path in `file` is a **Drive** path, not a filesystem one. A segment may end
in a space — Drive allows it, Windows does not — so `file` does not resolve on
disk and is not meant to. The id resolves. All three forms that show up in a
search result are accepted, and a path is matched with that invisible space
normalized away, because nobody types it.

Downloads are named after the catalog entry, not the id: a folder full of
`1N-pGXyxA4Iz...` is a folder nobody can read.

Search runs over a SQLite FTS5 projection of the catalog, so ranking is **BM25**:
a term appearing in three images outweighs one appearing in three thousand. All
query terms are required; if nothing matches them all, it falls back to any of
them and says so in the reason. Prefixes work (`bann` finds `banner`), and the
projection is derived data — delete it and the next run rebuilds it.

Four fields are searched, in this order of weight: `tags`, `caption`, `file`,
`text`. There is no `labels` field: it was supposed to hold Drive's own image
labels, and the property it was read from does not exist in the Drive API, so it
was always empty. It is no longer written.

### Useful flags

| flag | what it does |
|---|---|
| `--dry-run` | stop after the plan, spend nothing |
| `--retry-failed` | describe again the images that failed in earlier runs |
| `--resume-batch` | collect the batch a previous run left in flight — it was already charged, so this collects it instead of paying twice. The run that lost it prints the whole command to paste, target included |
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
├── by-entity/<name>.md # the same, by proper name — absent when nothing is named
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
 "entities":["Feira do Livro","Sesc Pinheiros"],
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

### `tags` are generic, `entities` are yours

`tags` say what kind of scene an image is — `dog`, `clinic`, `indoor` — and a
vocabulary of them describes a subject, not a client: 875 images from one
veterinary clinic produced 547 tags and not one proper noun. `entities` carries the
other half: the service, product, campaign, brand or person **named on the piece**,
copied as written.

The two are deliberately separate lists. Mixed into one, "what does this client
have" stops being answerable at all — there is no way to sort a proper noun back
out of a bag of keywords.

The model is instructed never to infer one: a name is written down only when it is
legible in the image or unmistakable in it, and `[]` is the ordinary answer for a
photograph. A hallucinated proper noun is worse than an empty field, because a
proper noun is the one thing a reader stops checking.

The field is **optional**: an index written before it existed carries no key, stays
valid against `schema/index-v1.json`, and reads fine — it simply has nothing to say
about names until it is rebuilt.

## The index reads without lupa

- **Claude Code** — the plugin ships an MCP server (`lupa_search`, `lupa_status`)
  that starts automatically. Indexing and search happen here.
- **Any agent holding the Drive connector** — can read the `_lupa/` files directly:
  `INDEX.md` → `by-tag/` → candidates. It executes nothing and needs nothing. No
  skill ships to teach that path; it is a property of the format, and `INDEX.md`
  opens with the instructions for reading it.

The contract is the files, and lupa is not on the other end of it.

## Configuration

### Where the settings file is found

Looked up in this order, first match wins:

| order | path | for |
|---|---|---|
| 1 | `--env <path>` or `$LUPA_ENV` | an explicit choice — what an agent or a script should pass |
| 2 | `~/.francis/.env` | a shared file, when several tools belong to the same person |
| 3 | `~/.lupa/lupa.env` | the tool's own file, and the portable default |

Nothing has to exist: with no settings file at all, every variable can come from
the process environment instead.

```bash
python3 -m lupa --env ./project.env index ~/Photos/Client
LUPA_ENV=./project.env python3 -m lupa status
```

### Settings

| variable | default | purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | vision model key (required to index) |
| `LUPA_LANG` | `en` | language of generated captions and tags (`pt`, `es`, …) |
| `LUPA_MODEL` | `gemini-3.5-flash-lite` | model used for descriptions |
| `LUPA_INPUT_PRICE` | from the table in `lupa/caption.py` | input price per 1M tokens, when you need to override the table |
| `LUPA_OUTPUT_PRICE` | from the table in `lupa/caption.py` | output price per 1M tokens, same idea |
| `LUPA_BATCH` | `1` | batch mode: half price, asynchronous. `0` forces immediate |
| `LUPA_CONFIRM_ABOVE` | `200` | ask before describing more images than this |
| `LUPA_CONFIG` | `~/.lupa/collections.json` | saved collection registry |
| `LUPA_INDEXES` | `~/.lupa/indexes` | local mirror of the indexes, read by the MCP |
| `LUPA_STATE_DIR` | — | shortcut: sets the index mirror to `<dir>/indexes` |
| `LUPA_OAUTH_CLIENT` | — | Google Drive OAuth client JSON, downloaded per person |
| `LUPA_OAUTH_TOKEN` | `~/.lupa/oauth_token.json` | where the Google sign-in is stored after the first authorization |

Nothing here needs to be edited by hand to get started: the first successful run
registers the collection for you.

## Cost

Describing a thousand images in batch with Flash-Lite lands in the range of
**cents** — US$ 0.58 at the moment, on the default model. The arithmetic lives in
`lupa/caption.py` and shows up in every `--dry-run` before you spend. Its two
token budgets are not guesses: they were measured on 2026-08-20 against a real
run, and `lupa/caption.py` records how, so the estimate can be checked instead of
believed.

Above 200 new images, the command asks first.

The price is a table, one row per model, and the preflight report always names
the model the estimate was computed for and where the number came from:

```
  ✓ cost estimate: US$ 0.30 in / US$ 2.50 out per 1M tokens for
    gemini-3.5-flash-lite · from the table for gemini-3.5-flash-lite · batch halves it
```

Set `LUPA_MODEL` to a model the table has never heard of and the estimate is not
quoted at all — it says so and tells you how to supply the two prices yourself,
because a confident number for the wrong model is worse than an admitted blank.
`LUPA_INPUT_PRICE` and `LUPA_OUTPUT_PRICE` override the table, so a price Google
changed is one line in your settings file rather than a new release of lupa.

Google retires models. When one goes, the API answers every single image with the
same 404 — and lupa reads that answer, names the successor Google itself suggests,
and tells you to put it in `LUPA_MODEL`, instead of printing a bare HTTP error a
few hundred times.

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
