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
python3 -m lupa index <target>
```

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
  mounted on disk. Mention what the user would gain by pasting the Drive URL (free
  OCR, shareable links, stable ids) without forcing them to change.
- **Plan** — how many images will be described and what it costs. If it reports
  "Nothing changed", the run is over: report that and stop.

To see only the plan: `--dry-run`.
To run unattended: `--yes` — but only after you have read the plan.

## Flags worth knowing

| flag | when to reach for it |
|---|---|
| `--retry-failed` | the last run reported failures and the user wants them described |
| `--resume-batch` | a previous run died waiting on its batch; lupa refuses to start until that batch is collected or given up |
| `--no-recursive` | the user explicitly wants only the top folder |
| `--no-batch` | the user needs the index now and accepts paying twice as much |
| `--workers N` | tuning parallelism when batch is off (default 8) |
| `--no-contact-sheets` | Pillow is missing, or the grids are not wanted |

## After the run

The command saves the collection under a short name (taken from the folder name),
publishes the index to Drive when the source is Drive, and prints a summary. Report
what changed (`+N added · ~N changed · -N removed`) and the cost. Failures, if any,
land in `runs/<date>.errors.jsonl`.

## Rebuilding from scratch (rare, and expensive)

```bash
python3 -m lupa index <name> --rebuild --confirm "<name>"
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
