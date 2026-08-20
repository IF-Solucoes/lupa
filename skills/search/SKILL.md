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
python -m lupa search "bridge night blue" --kind design --limit 10
python -m lupa status
```

Run it **from the folder that holds the `lupa/` package** — the plugin root (two
levels above the directory this skill was loaded from) or the root of a checkout of
the repository. There is no installed console script, so from any other directory
`python -m lupa` answers `No module named lupa`. Always spell the interpreter
`python`: the versioned alias — the same word with a `3` on the end — is the
Microsoft Store stub on Windows, and it runs nothing at all.

## The filters that keep junk out of the result

Collections mix raw photography, finished posts, and screenshots. Always filter by
type:

| Filter | Values | Use it to |
|---|---|---|
| `kind` | `photo` `design` `screenshot` `diagram` `logo` `other` | separate raw material from finished work |
| `medium` | `physical` `digital` `na` | `design`+`physical` means print, banner, real mockup |
| `orientation` | `portrait` `landscape` `square` | match the destination format |
| `has_text` | `true` `false` | `false` returns clean images with no baked-in type |

On the command line the same four are flags: `--kind`, `--medium`, `--orientation`,
`--has-text true|false` (`--has_text` is accepted too).

Requests these actually solve:

- *"clean photos to put text over"* → `kind=photo`, `has_text=false`
- *"how we have applied the brand in print"* → `kind=design`, `medium=physical`
- *"story references"* → `orientation=portrait`, `kind=design`

## How ranking works

Search runs over a BM25 index, so a rare term outweighs a common one — "cable-stayed"
counts for far more than "blue". All your terms are required; when nothing matches
them all, the search falls back to any of them and the reason says `some terms`
instead of `all terms`. Prefixes work: `bann` finds `banner`.

The four searchable fields are `tags`, `caption`, `file` and `text`, in that order
of weight. There is no `labels` field to search: it was harvested from a Drive
property that does not exist, so it was always empty and is no longer written.

## Where the words come from

Everything you search — caption, tags, `has_text` and the transcribed `text` —
is written by the **vision model that looked at the image**. Google Drive returns
no text of any kind to lupa, so this is true of a Drive collection and a local
folder alike: neither has an advantage in what can be found by words.

An index built before this was fixed carries `has_text: false` on every image and an
empty `text`, because the field lupa read never existed. The symptom is unmistakable:
`has_text=true` returns nothing at all, in a collection you know has printed pieces.
That index needs a rebuild (`lupa-index` skill) before it can answer about text.

## Language: the index speaks one, your user may speak another

Captions and tags are written in the language of `LUPA_LANG` — **English by
default**, whatever the language of the collection. File and folder names keep the
client's language. So in a Brazilian collection, `gato` returns nothing while `cat`
is the tag on 114 images; a query in the wrong language reads exactly like an empty
collection. When a non-English query comes back empty, translate it and search
again before telling anyone the material does not exist.

## Reading the result

Each candidate carries a caption, tags, type, link, and **why it matched**
(`matched on:`). `all terms` means every term hit; `some terms` means the search had
to fall back to any of them, so read that candidate with suspicion. The reason does
not say which field matched — a term can come from the transcribed text rather than
from the picture, so open the finalists when the answer has to be visual.

## When the search finds nothing

1. Read the collection's vocabulary: `~/.lupa/indexes/<collection>/INDEX.md` by
   default (`lupa_status` lists the collection names, not the vocabulary). Careful:
   it shows only the **40 most frequent** tags and does not say so — a collection
   with 546 tags shows 40. An absent tag is not proof of an absent subject; the full
   list is the file names under `by-tag/`.
2. Try the English term, if the query was not in English (see above).
3. Try broader terms — the index uses concrete words ("wood", "natural-light"),
   not abstractions ("cozy", "premium").
4. If the collection looks stale, call the `lupa-index` skill to run an update
   before concluding that the image does not exist.
