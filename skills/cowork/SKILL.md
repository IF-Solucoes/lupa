---
name: lupa-cowork
description: >-
  Use when you need to find images in a Google Drive collection indexed by lupa from
  an environment WITHOUT code execution — Claude Cowork, claude.ai, or any agent that
  only has the Drive connector. It teaches you to read the `_lupa/` index already
  published in the collection folder and answer visual queries by reading two small
  files, instead of opening dozens of images. Do NOT use in Claude Code with the
  plugin installed (the MCP is faster there — use lupa-search). It cannot index:
  without code execution, the index can be read but never created or updated.
---

# lupa · the no-code face

## What you have in front of you

A Drive folder of images that has already been indexed. Inside it lives `_lupa/`, a
**text** index built for you. You do not need — and should not want — to open the
images to learn what the collection holds.

## The rule

**Read text, never pixels.** Every image you open costs far more than the entire
index. Open images only at the end, only the finalists the search pointed at, and
only if the user needs visual confirmation.

## The path, in three steps

**1. Read `_lupa/INDEX.md`.** It is small (~2 KB) and carries the image count, the
breakdown by type, and the **tag vocabulary with counts**. It is the map. Always
read it first.

That vocabulary is **the 40 most frequent tags, and the file does not say so**: a
collection with 546 tags shows 40 of them. Never conclude from that list that the
collection has nothing about a subject — list `_lupa/by-tag/` and look for the tag
there. The tags are written in the index's language, English by default, whatever
language the collection or the user speaks: search `cat`, not `gato`.

**2. Pick the relevant tags and read `_lupa/by-tag/<tag>.md`.** Each file is a
ready-made table: file, type, orientation, caption, and link. For most requests this
is the whole job — stop here.

**3. Only if you must cross fields, read `_lupa/catalog.jsonl`.** One JSON line per
image, every field present. Use it when the request combines criteria that `by-tag`
cannot separate (for example: portrait **and** no text **and** a photograph).

## The fields that keep you from delivering junk

Collections mix raw photography with finished work. Always filter by type:

- `kind`: `photo` (captured) · `design` (finished artwork) · `screenshot` ·
  `diagram` · `logo` · `other`
- `medium`: `physical` (print, real object) · `digital` (on-screen artwork) · `na`
- `has_text`: `true` when type is baked into the image
- `orientation`: `portrait` · `landscape` · `square`

A printed mockup is `design` + `physical`. A clean photo ready to receive type is
`kind: photo` + `has_text: false`.

## What to give the user

Return a handful of candidates — five to ten — with **file name, short caption, and
Drive link**. Say why each one made the list. If nothing matches, report the
vocabulary the collection actually has rather than inventing synonyms.

## Where this face comes from

This skill arrives with the lupa plugin — the same package Claude Code installs.
Nothing about the index differs between the two; what differs is that here you
read it, and there it is produced.

## Limits of this face

- **You cannot index here.** If the index is stale or absent, tell the user: creating
  and updating it belongs to lupa running in Claude Code.
- **New images do not appear** until someone runs `lupa update`. `INDEX.md` shows the
  date of the last run — check it before claiming something does not exist.
- **`text` is a transcription, not OCR from Drive.** Whatever `has_text` and `text`
  say was written by the vision model that described the image; Google Drive gives
  lupa no text at all. A Drive collection and a local one are equal here.
- **An index built before that was fixed says `has_text: false` on every image**,
  with `text` empty, because lupa read a Drive field that does not exist. If nothing
  in the whole catalog has text, that is what you are looking at — say so instead of
  reporting that the collection has no printed material.
