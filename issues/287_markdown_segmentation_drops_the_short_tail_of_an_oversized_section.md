# 287 — Markdown segmentation drops the short tail of an oversized section

## Status: RELEASED IN 0.0.48 AND DEPLOYED 2026-10-20 to AWS test and AWS production. Splitter follow-up FIXED IN CODE 2026-10-20 (not yet released). STAYS OPEN: documents segmented before the fix keep their gaps until re-segmented.

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

## Follow-up fix (2026-10-20, not yet released) — the splitter itself

Four problems found in `_split_recursive` while reading it, left out of the
first fix, are now fixed:

- **Word-level splitting was skipped.** The separator loop stopped before `" "`
  (`remaining_separators != [" "]`), so text with no `". "` went straight to
  fixed character chunks and words were cut in half. It now tries every
  separator down to words, and character chunks only when none splits.
- **Character chunks were not re-checked** against the token limit. The size
  came from an average chars-per-token estimate, which a dense stretch exceeds.
  `_hard_chunk` now checks each chunk and halves it until it fits.
- **Overlap was applied at every level of recursion** and counted in
  whitespace words, so a recursed chunk got overlap twice and could exceed the
  limit. It is now applied once, to the final chunks, measured with the
  tokenizer, and shrunk so an overlapped chunk still fits.
- **Offsets were wrong after an overlapped chunk,** because `find()` of an
  overlapped chunk returns -1 and every later offset drifted.
  `_recursive_split_spans` returns each chunk's own span, located before the
  overlap is added; the plain and Markdown paths use it.

Verified: four tests in `tests/unit/test_document_segmenter.py` (words never cut
without a sentence separator; character chunks within the limit; overlap
applied once and within the limit on text that recurses; offsets locate each
chunk's own content with overlap). All four fail on the old splitter and pass
on the new one; the segmenter and segmentation unit tests pass (105).

## Not done

- Documents already segmented keep their old segments until re-segmented.
