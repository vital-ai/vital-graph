# 292 — A text filter was declared empty from the wrong count, and from a cached zero

## Status: FIXED IN CODE 2026-10-20 (not yet released). The defects shipped with `issues/202` and are presumably live in production.

**Related:** `issues/202` (the "a required text filter that matches nothing
makes the query provably empty" short-circuit these defects live in),
`issues/070` (the text-leaf measurement), `issues/073` (the same short-circuit
for an absent constant; checked, not affected), `issues/291` (found while
testing its trigger).

## What showed it

A SPARQL `DELETE ... WHERE { GRAPH <g> { ?s <hasName> ?n .
FILTER(STRSTARTS(STR(?s), "http://example.org/isqtrg/w")) } }` deleted nothing.
The same WHERE in a SELECT returned 0 rows where 2 matched, and the generated
SQL ended `) _empty LIMIT 0`: the compiler had decided, before running
anything, that the answer was empty.

A probe on a fresh space then gave 0 rows for every STRSTARTS and CONTAINS on
`STR(?s)`, against correct counts for the equivalent REGEX, which this path
does not measure.

## Cause — two defects in the same short-circuit

1. **The count was over the wrong column.** A text needle's match count is
   "quads with this predicate whose OBJECT is in the needle's term set"
   (`generator._load_missing_pair_stats`). The leaf it is counted for came from
   `semijoin.text_bgp_binding`, which took the variable's FIRST position and
   ignored its column. A filter on a subject (`STR(?s)`) was counted against
   the predicate's objects, came back zero, and
   `prune_union._required_text_matches_nothing` made the query provably empty.
   The same position-blind lookup fed the range and IN-list estimates. For
   those it only skewed plan choice, not results.
2. **A zero was cached forever.** The count went into `_pair_count_cache`, which
   is process-wide, holds 50,000 entries, and is never invalidated on a write.
   A needle searched for before any value contained it cached 0, so the query
   stayed empty after the value was written, until a restart or an LRU
   eviction. Reproduced: CONTAINS "zebraquux" returns 0, a value containing it
   is written, and the same query still returns 0, `_empty`-wrapped.

Over the API the first defect hid on large spaces where some object literal
happened to match the needle, so the count was non-zero. For example, `"urn:"`
on `sp_lead_types`.

## Fix

- **`semijoin.object_leaf`** returns a leaf only where the variable is in
  OBJECT position. `text_bgp_binding` and the text, range and IN measurements
  all use it. A subject-position variable is not measured, so it is never
  declared empty from a count over objects.
- **A zero is never cached.** It is the one value acted on as fact. It is
  re-measured each query, which the trigram index answers in about 1 ms (the
  case `issues/202` is about). Non-zero counts, which only inform plan choice,
  are still cached.

## Verified

`tests/integration/test_text_filter_emptiness_is_measured_right.py`:

- STRSTARTS and CONTAINS on `STR(?s)` return their subjects, with no `_empty`
  wrap;
- a value written after a search that found nothing is found by the next
  search;
- a genuinely absent object needle is still declared empty.

The first three fail on the old code and pass on the new; the last passes on
both. The unit suite also passes.

## Not done

- **Production impact is unmeasured.** Any SPARQL text search, and anything that
  compiles through the same generator, for a
  value first searched before it existed has returned empty until the server
  restarted. Restarts, at every deploy, mask it.
