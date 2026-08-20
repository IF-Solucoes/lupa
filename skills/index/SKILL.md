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
  whether an image suits a brand.
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

## Common errors

| Symptom | What to do |
|---|---|
| `✗ Gemini key` | follow the printed instruction; the key belongs in your `lupa.env` |
| `✗ Google Drive access` | the OAuth client JSON is missing; the message lists the 3 steps |
| `I could not make sense of "<x>"` | the target is not a URL, an id, or an existing folder — ask the user for the Drive folder URL |
| `⏳ Another run is using this index` | wait, or delete `_lupa/.lock` if you are sure |
| `is still registered as in flight` | a batch was ALREADY CHARGED and never collected. Paste the `Collect it:` command exactly as printed — it names the target the user typed, and shortening it to the collection name is how this instruction used to dead-end. Never rerun without `--resume-batch`: that pays for the same images twice |
