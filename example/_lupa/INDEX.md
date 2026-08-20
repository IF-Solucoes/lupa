# Visual index — example

**6 images** · updated 2026-08-20T14-32-00 · described by `gemini-2.5-flash-lite` · schema v1

> **Read text, never pixels.** This index exists so that you do NOT have to open
> the images. Opening an image is expensive, and avoiding it is the whole point of
> this file. If you need visual confirmation, open only the finalists that the
> search returned.

## What is here

- **By type:** design: 3 · photo: 2 · logo: 1
- **By material:** digital: 3 · na: 2 · physical: 1

`kind`: photo · design · screenshot · diagram · logo · other
`medium`: physical · digital · na — a printed mockup is `design` + `physical`.

## Vocabulary

Generic terms — what kind of scene each image is. Any collection on this subject
would share most of them.

`blue` (2) · `typography` (2) · `bread` (1) · `oven` (1) · `warm-light` (1) · `food` (1) · `banner` (1) · `event` (1) · `printed` (1) · `logo` (1) · `brand` (1) · `monochrome` (1) · `bridge` (1) · `night` (1) · `story` (1) · `dark` (1) · `green` (1) · `team` (1) · `people` (1) · `wood` (1) · `natural-light` (1)

## Entities

Proper names read off the pieces themselves: services, products, campaigns, brands,
people. This is what belongs to THIS collection and to no other. Empty on most
images, and never inferred — a name is here only when it is written on the image
or unmistakable in it.

`LUPA` (2)

## How to query

1. **Looking for what this client specifically does, sells or ran?** Start at
   **Entities**, then read `by-entity/<name>.md`.
2. **Found a tag above?** Read `by-tag/<tag>.md`. It is a ready-made table with
   links. Stop there.
3. **Need to cross fields** (type + orientation + no text)? Filter `catalog.jsonl`.
   One line per image; fields are defined in `schema/index-v1.json`.
4. **Have the lupa MCP?** Call `lupa_search` and get ranked finalists directly.

## Files

| file | purpose |
|---|---|
| `INDEX.md` | this map — always read it first |
| `by-tag/*.md` | inverted index by generic term, cheap to read without code |
| `by-entity/*.md` | the same, by proper name — absent when nothing is named |
| `catalog.jsonl` | one line per image, for field-level filtering |
| `contact-sheets/` | visual grids, for human curation |
| `MANIFEST.json` | internal state: the hashes that make updates incremental |
| `runs/` | what each run changed |
