---
name: lupa-search
description: >-
  Use WHENEVER you need to find images in a collection already indexed by lupa —
  "find a photo of X", "what references do we have for Y", "I need a portrait image
  with no text", "what is in the collection about Z". It queries the text index and
  returns a few candidates with links and reasons, without opening a single image.
  Use this INSTEAD of listing a Drive folder or looking at images one by one — that
  is the difference between spending cents and spending dollars. Do NOT use to create
  or update the index (skill lupa-index).
---

# lupa · search

## The rule that justifies this skill

**Read text, never pixels.** Opening images is the expensive operation. The index
exists so you can answer "which photos fit here?" by reading lines of text. Only
after the search narrows the collection to a dozen candidates is it worth looking —
and then it is twelve images, not three hundred.

## How to query

**With the MCP running** (the normal case, since the plugin loads it):

```
lupa_search(query="bread oven warm light", kind="photo", limit=10)
lupa_status()   # which collections exist and when they were updated
```

**From the command line**, when the MCP is unavailable:

```bash
python3 -m lupa search "bridge night blue" --kind design --limit 10
python3 -m lupa status
```

## The filters that keep junk out of the result

Collections mix raw photography, finished posts, and screenshots. Always filter by
type:

| Filter | Values | Use it to |
|---|---|---|
| `kind` | `photo` `design` `screenshot` `diagram` `logo` `other` | separate raw material from finished work |
| `medium` | `physical` `digital` `na` | `design`+`physical` means print, banner, real mockup |
| `orientation` | `portrait` `landscape` `square` | match the destination format |
| `has_text` | `true` `false` | `false` returns clean images with no baked-in type |

Requests these actually solve:

- *"clean photos to put text over"* → `kind=photo`, `has_text=false`
- *"how we have applied the brand in print"* → `kind=design`, `medium=physical`
- *"story references"* → `orientation=portrait`, `kind=design`

## Reading the result

Each candidate carries a caption, tags, type, link, and **why it matched**
(`matched on:`). Use the reason to calibrate: a match that came only from OCR may be
weak — the piece mentioned the term in its copy, but the image may show nothing of
the sort.

## Collections indexed from a local folder

A collection indexed from disk has no Google OCR. Its `text` field is empty and
searching for text baked into the artwork will not work there — search by tags and
caption instead. `lupa_status` lists the collections; each one's `INDEX.md` shows
its real vocabulary.

## When the search finds nothing

1. Run `lupa_status` and read the vocabulary in that collection's `INDEX.md`.
2. Try broader terms — the index uses concrete words ("wood", "natural-light"),
   not abstractions ("cozy", "premium").
3. If the collection looks stale, call the `lupa-index` skill to run an update
   before concluding that the image does not exist.
