# 287 — Markdown segmentation drops the short tail of an oversized section

## Status: RELEASED IN 0.0.48 AND DEPLOYED 2026-10-20 to AWS test and AWS production. Documents already segmented keep their gaps until re-segmented.

**Related:** `issues/286` (the worker now passes the type's real minimum).

## What happened

`DocumentSegmenter._segment_markdown` splits an oversized section recursively.
It kept a sub-chunk only `if chunk_tokens >= config.min_segment_tokens`; there
was no else branch. So the remainder of every oversized section that fell below
the minimum disappeared from the segments, and with it from full-text and vector
search over them. Through the worker the minimum was 20, so any final paragraph
under 20 tokens was lost.

Sections that fit but are too small were merged into the previous segment, and
the plain splitter merges too. Only this branch dropped text. The whole text was
never lost from storage: it stays on the document.

The segmenter's own tests had never run. They sat in `vitalgraph/document/`,
outside pytest's `testpaths`.

## Fix

- **A short sub-chunk is merged into the previous segment,** as long as the
  result still fits the embedding limit. Otherwise it is kept as its own segment.
  It is never dropped.
- **The tests now run.** `test_document_segmenter.py` and
  `test_segmentation_processor.py` moved to `tests/unit/`, without their
  hardcoded `sys.path` line and script `main()`.

## Verified

`tests/unit/test_document_segmenter.py::test_an_oversized_sections_short_tail_is_kept`
fails on the old segmenter, because the tail marker is missing, and passes on the
new one. It also asserts that no segment exceeds the limit.

## Not done

Problems found in `_split_recursive` while reading it, left as they are:

- **Word-level splitting is skipped.** When the text has no `". "`, it goes
  straight to fixed character chunks, which can cut words in half.
- **Character chunks are not re-checked** against the token limit.
- **Overlap is applied at every level of recursion** and counted in whitespace
  words.
- **Offsets are wrong for overlapped chunks,** because `find()` returns -1.
