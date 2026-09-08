# 176 — The prop-sort tables: what they are, and what commit 9756865e actually contains

**Status:** closed (record)
**Raised:** 2026-09-08
**Related:** issues/149 (a coverage probe that could not see its own shortfall),
issues/161 (marker lifecycle), issues/167 (the gate inverted to a block-list),
issues/172 (two fast paths that declined each other's input)

## Why this exists

Two reasons, and the second is the awkward one.

**The tables are new and their maintenance is not obvious.** `entity_prop_sort`
and `frame_prop_sort` are populated by a migration, maintained per-write, and
described by a coverage marker written from two places. Someone debugging a slow
listing needs to know which of those has not run, and the distinction between
"stale" and "nothing has run yet" is not visible from the data.

**A commit message under-describes its commit.** `9756865e` reads as "serve the
typed listing, record coverage, and say why on decline". It also carries the
frame population widening, the block-list correction, a gate-predicate fix and a
definition correction — the two largest of which were directed changes, not
incidental ones. The reasoning is in the code comments in full; it is not in the
log. This file is the index the log does not give.

That happened because the working tree accumulated across several distinct
pieces of work instead of each being committed as it was verified. Worth naming
rather than leaving for someone to rediscover by reading a 933-line diff.

## What the tables are

One row per (subject, context, indexed property), carrying the MIN of the
property's values in three typed lanes plus `value_all` holding every value.
Sorting reads the lanes — a sort needs one key per subject or a subject with
three values is emitted three times. Filtering reads the array, because every
membership operator (`has`, `has_any`, `eq` on a possibly multi-valued
predicate) is unanswerable from a MIN.

The subject URI is denormalised into the row as `entity_uri` / `frame_uri` and
made the last index column. That is not convenience: the SPARQL query these
replace breaks sort ties with `?s`, and the uuid is a HASH of the URI, so tying
on it reorders a tied page. Joining the term table for it instead cost a deep
page 2.1 ms -> 123 ms.

`frame_prop_sort` holds EVERY frame, with the resolved form type in a column.
It was briefly scoped to Assertions, which made form type a property of the
population rather than a filter — and traversal is general, so a table admitting
one form type can only answer the traversals whose results happen to share it.

## What keeps them current

| when | what runs |
|---|---|
| once | `scripts/migrate_*_prop_sort.py` |
| every quad change | `sync_*_prop_sort_after_change` — 8 write-path sites each |
| graph CLEAR / DROP | `delete_*_prop_sort_for_context` |
| restore, bulk load, repair | `resync_all`, `scripts/repair_derived_tables.py` |

Maintenance is per-write, not scheduled. A DELETE is a RECOMPUTE, not a row
drop — removing one value of a multi-valued property moves the stored MIN — so
the sync runs AFTER the quads move, against the survivors. There is no
before-delete hook to look for.

## What the marker means

`prop_sort_coverage` is written by the migration AND by the `prop_sort_coverage`
maintenance phase, both through `record_prop_sort_coverage`, which takes or
releases the block from the number it just measured. Measurement and gating are
not separable; splitting them produced every lifecycle bug in issues/161.

**An empty `prop_sort_coverage` means something is wrong, not that coverage is
unknown.** The table was once created and written by nothing, and an operator
diagnosing a slow listing read the empty table as "coverage was never
established". An empty table that looks like a signal costs more than an absent
one.

## Four defects worth remembering

* **A decline that logs at DEBUG is invisible.** Production runs at INFO, so a
  correct, populated, unblocked, readable table that was simply never used
  presented as a mystery and took static analysis to attribute. Every decline
  now names its reason at INFO.
* **A table must block ITSELF.** The migrations took their whole-space block in
  `slot_sort_block`, disabling the SLOT-sort fast path for the whole space for
  the length of an unrelated build — eleven minutes on a 74.5M-quad space.
  Reading that table is still right: a restore invalidates everything.
* **The gate's predicate matched a whole-space block only for untyped
  listings**, so a typed one was served from a table its own migration was still
  populating.
* **The commonest browse was the one shape declined.** A typed listing with no
  sort fell to the SPARQL walk at 3.7 s warm, 30 s once
  `PROD_TRANSACTION_TIMEOUT` killed it, while the table that could answer it in
  0.40 ms sat unused.

## Measured

    entity, typed sort, first page                    0.4 ms   vs 128.8 ms
    entity, typed listing, no sort                    0.4 ms   vs   3.7 s
    frame, any form-type tab                          0.3 ms   vs   578 ms
    frame, children of a parent (median of 60)        2.7 ms   vs   155 ms

Build cost is sized by SUBJECT count, not quad count: 285,348 frames in ~55 s,
1,200,000 frames in ~11 minutes. It is one statement with no resume.

## Still open

* `hasFrameGraphURI` is a PROXY for entity enclosure, not the definition. An
  Aspect is a frame enclosed by an entity; an Assertion is one that is not. The
  proxy agrees on the corpora measured, and the tables mirror the endpoint's
  rule deliberately rather than diverging from it — the table's job is to agree
  with what the tab lists. Correct it in the endpoint and these follow.
* Search still takes the SPARQL path for entities and frames alike. Composing
  `{space}_fts_{index}` with these tables is a join whose driving side depends
  on how selective the search is, and issues/172 is what guessing that costs.
