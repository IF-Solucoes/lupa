---
name: lupa-index
description: >-
  Use when the user wants to CREATE or UPDATE the index of an image collection —
  "index these photos", "catalog this folder", "refresh the index", "what changed in
  the references". The collection can be given any way: a Google Drive folder URL, a
  folder id, a local folder path, or the name of a collection already indexed. Every
  run starts with a preflight that checks the environment, explains what is missing,
  and shows the cost before spending. Incremental: only what changed costs anything.
  Do NOT use to search an existing index (skill lupa-search), and do NOT use to judge
  whether an image suits a brand. Also covers `lupa map` — the free step 0 that
  shows the shape of a collection (how many files lupa can index, and how many it
  ignores: video, PSD, PDF, Google Docs) before anything is indexed or paid for.
---

# lupa · index

## What this skill does

Turns a folder of images into a text index, so that agents can find references
**without opening the images**. Each image is described once in its life.

A collection is a **starting point**: lupa branches into every subfolder beneath the
one you point at, at any depth, and never enters a `_lupa/` index folder. Pass
`--no-recursive` when the user explicitly wants only the top level.

**It holds no opinion.** It knows nothing about clients, brands, or editorial
direction. Judging fitness belongs to the consuming skill.

## Step 0 — look before you index (`lupa map`, free)

```bash
python -m lupa map <target>
```

**Offer this whenever the user has not indexed this collection before, or does not
know what is in it.** It walks the folders and counts the files by type. It
downloads nothing, describes nothing and calls no model — it does not even need a
`GEMINI_API_KEY`, so there is no version of this command that costs money.

It answers the one question the index cannot: **what will be left out.** `lupa
index` lists only images in a supported format, so video, PSD, PDF and Google Docs
never appear in an index, in a plan, or in a cost — they are simply absent. In a
folder called `4 - Fotos & Vídeos` that absence is the whole story: the index
reports 489 images and says nothing about the 298 `.mp4` beside them.

```
Drive map · "acervo" · 1K6qh1sIFt9SyvKLgVMiFP4x3rI4vfXa-
free · names and types only — no download, no model call, no API key

    4 - Fotos & Vídeos/                          489 indexable · 312 ignored
      Tratamento de Fotos/                       485 jpg
      Brutas/                                    4 jpg · 298 mp4 · 14 mov

  total: 875 indexable · 356 ignored (mp4 298 · psd 41 · mov 14 · pdf 3)
```

| flag | what it does |
|---|---|
| `--depth N` | how many folder levels to print (default 2). Deeper folders are folded into the row above and the folding is announced — raise it to open them |
| `--out PATH` | where to write `MAP.md`. By default it goes next to where the index will live, `<index root>/<collection>/MAP.md`, as a sibling of `INDEX.md` |

Two things to report back, always: the number of **ignored** files by type, and
that the map cost nothing. A user deciding where to spend needs the first; a user
who has just been shown a number needs the second.

`map` is **not** part of preflight, and must not be run before every index:
preflight has to be quick, and a map is a full walk of the collection. Run it once,
when the shape is unknown.

## One command, and the user needs to know nothing

```bash
python -m lupa index <target>
```

**Run it from the folder that holds the `lupa/` package.** There is no installed
console script: `python -m lupa` only finds the package when it sits in the current
directory, and from anywhere else it dies with `No module named lupa`.

| where you are | what to run first |
|---|---|
| the plugin is installed | `cd` into the plugin root — the folder holding `lupa/`, `server/` and `skills/`, two levels above the directory this skill was loaded from |
| a checkout of the repository | `cd` into the repository root |

Always spell the interpreter `python`. The versioned alias — the same word with a
`3` on the end — is, on Windows, the Microsoft Store stub: it prints an
advertisement, runs nothing, and says so in a way that reads like success.

The target takes any of these forms. Do not ask the user which one they have —
just pass along whatever they said:

| What the user gave you | Example |
|---|---|
| a Drive folder URL | `https://drive.google.com/drive/folders/1a2B3c` |
| a folder id | `1a2B3c` |
| a path on disk | `~/Photos/Client` or `/mnt/g/My Drive/Clients` |
| the name of a saved collection | `if-editorial` |

`index` and `update` are the same command. lupa reads the index and decides
whether this is a first run or an update. **Never ask the user which to use.**

## Preflight runs every time — read what it says

Before any spending, the command prints a diagnosis and a plan:

- **`✗` (blocker)** — it stopped and spent nothing. The message itself carries the
  fix, step by step. **Relay that instruction verbatim**; do not invent your own.
- **`!` (warning)** — it still works. The common case: the folder given is Drive
  mounted on disk. Mention what the user would gain by pasting the Drive URL
  (shareable https links, a stable id per file) without forcing them to change.
- **Plan** — how many images will be described and what it costs. An empty plan
  means one of two opposite things, and they must never be reported alike:
  - **`Nothing changed since the last run`** — the incremental working as promised.
    The run is over: report it and stop. It exits 0.
  - **`✋ Nothing found to index`** — the collection came back with no image at all.
    **Do not report this as success.** It exits non-zero. Relay the listed causes
    verbatim — the likeliest on Drive is that the folder was never shared with this
    account, because Drive answers a listing you may not see with an empty list
    rather than an error. Nothing was indexed and nothing was spent.

**The exit code outranks the text.** Any non-zero exit from `lupa index` is a failed
run, however friendly some line above it reads.

To see only the plan: `--dry-run`.
To run unattended: `--yes` — but only after you have read the plan.

## Flags worth knowing

| flag | when to reach for it |
|---|---|
| `--no-push` | the index must not leave the machine. By default a Drive collection gets its `_lupa/` folder written back into the Drive folder, where everyone who can see the collection can read every caption. Offer this flag whenever the material is confidential — nobody else will |
| `--retry-failed` | the last run reported failures and the user wants them described |
| `--resume-batch` | a previous run died waiting on its batch; lupa refuses to start until that batch is collected or given up. lupa prints the exact command — paste it as written, target and all |
| `--no-recursive` | the user explicitly wants only the top folder |
| `--no-batch` | the user needs the index now and accepts paying twice as much |
| `--workers N` | tuning parallelism when batch is off (default 8) |
| `--no-contact-sheets` | Pillow is missing, or the grids are not wanted |

## After the run

The command saves the collection under a short name (taken from the folder name),
publishes the index to Drive when the source is Drive (unless `--no-push`), and
prints a summary. Report
what changed (`+N added · ~N changed · -N removed`) and the cost. Failures, if any,
land in `runs/<date>.errors.jsonl`.

A run with failures **does not publish**: a partial index must not overwrite a
complete one in the client's folder. Fix what failed, run again with
`--retry-failed`, and the publish happens then.

## Publishing on its own

```bash
lupa publish <target>
```

Two situations need it, and `lupa index` reaches neither:

* the index was built with `--no-push` and the user now wants it on Drive;
* the collection is unchanged, so the run stops at "Nothing changed" before the
  publish step. An index with nothing left to describe may still never have been
  published at all.

It describes nothing and costs nothing. It also retires pages the index no
longer has, moving them to the Drive trash, so a vocabulary that shrank does not
leave stale tag pages sitting beside the current ones.

## What a run writes down about each image

A caption, generic tags, type and material, orientation, palette, whether the image
has text baked in and a transcription of it — and, separately from the tags,
**`entities`: the proper names carried by the piece**. Services, products,
campaigns, brands, people, copied as written.

That last one is the reason to reindex an old collection. Tags are generic by
construction (`dog`, `clinic`, `indoor` — true of every veterinary clinic alive);
`entities` is the part that belongs to this client and to no one else. It lands in
`catalog.jsonl`, in its own **Entities** section of `INDEX.md` (complete, not
truncated), and in one `by-entity/<name>.md` file per name, in the shape of
`by-tag/`.

Two honest things to tell the user:

- The field is **empty on most photographs**, by design, and the model is instructed
  never to guess a name from context. That is the only way the field stays
  trustworthy: a made-up service name reads exactly like a real one.
- **Indexes built before this existed carry no names.** They stay valid and readable
  — the field is optional — but they answer nothing about names until they are
  rebuilt, which costs a full description of every image.

## Rebuilding from scratch (rare, and expensive)

```bash
python -m lupa index <name> --rebuild --confirm "<name>"
```

It requires typing the name. The previous index is copied to `.backup/` before any
write. Do this only when the schema changed or the index is corrupt.

A rebuild is **not** an incremental update: it ignores what is already indexed and
describes every image again, at full price. Preflight marks it (`! index state`)
and the plan counts the whole collection — read those two numbers to the user
before confirming, because on a large collection this is the most expensive command
lupa has.

Two things not to be surprised by:

- `--retry-failed` adds nothing to a rebuild and is skipped, out loud: everything
  gets described again anyway.
- If a batch is still registered as in flight, the run refuses, rebuild or not —
  that money is already spent. Collect it first (`--resume-batch`). A batch
  submitted for a handful of changed images cannot serve a rebuild, and lupa says
  so instead of writing a half-empty index.

## Common errors

| Symptom | What to do |
|---|---|
| `✗ Gemini key` | follow the printed instruction; the key belongs in your `lupa.env` |
| `✗ Google Drive access` | the OAuth client JSON is missing; the message lists the 3 steps |
| `I could not make sense of "<x>"` | the target is not a URL, an id, or an existing folder — ask the user for the Drive folder URL |
| `⏳ Another run is using this index` | wait, or delete `_lupa/.lock` if you are sure |
| `is still registered as in flight` | a batch was ALREADY CHARGED and never collected. Paste the `Collect it:` command exactly as printed — it names the target the user typed, and shortening it to the collection name is how this instruction used to dead-end. Never rerun without `--resume-batch`: that pays for the same images twice |
