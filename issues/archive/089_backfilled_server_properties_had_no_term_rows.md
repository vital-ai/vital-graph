# Backfilled Server Properties Had No Term Rows, So They Were Unqueryable

## Status: DATA REPAIRED 2026-08-13 — code was fixed 2026-08-06 by `62cb5dd`

The base-property backfill wrote quads for three server properties on every
KGEntity but never inserted the predicates' rows in the term table. A predicate
absent from `{space}_term` cannot be named in SPARQL, so those properties were
**silently unqueryable** — filtering or sorting entities by creation time,
modification time or status matched nothing, on every affected space.

    http://vital.ai/ontology/vital-aimp#hasObjectCreationTime
    http://vital.ai/ontology/vital#hasObjectModificationDateTime
    http://vital.ai/ontology/vital-aimp#hasObjectStatusType

The code defect was already fixed — `62cb5dd` (2026-08-06) says it outright:
"kg_server_properties registered no term rows for the four server-property
predicates, so the backfill wrote quads referencing terms that did not exist."
`_ensure_term_row` now inserts them, so new backfills are clean. What was never
done is repairing the spaces backfilled BEFORE that commit, and nothing recorded
that the residue existed.

## How it was found

Not by looking for it. Comparing `wordnet_frames` against `wordnet_exp` by
distinct predicate turned up 329,235 quads in BOTH whose predicate did not join
to the term table — identical in both, so it predated the copy.

The first hypothesis was that the spaces predate the properties. The data says
otherwise: the quads carry real values, timestamped 2026-04-30 and 2026-05-01,
months after the space was created (2026-03-07). Something wrote them. The
values are what identify the writer as the backfill.

## Scope

10 spaces, all with exactly the same three predicates, nothing else unresolvable
anywhere — one cause, no second story:

| space | orphaned quads |
|---|---|
| `wordnet_frames` | 329,235 |
| `graph_viz_a` … `graph_viz_f` | 81–174 each |
| `customer_journey_test`, `kg_load_test` | 60 each |
| `space_slot_negation_test` | 15 |

`wordnet_exp` had 329,235 too and was deliberately skipped — it is slated for
removal.

## The repair

Term UUIDs are a deterministic UUID-5 of `(text, type)`, so the value to insert
is derivable rather than guessable. This was PROVEN before writing anything:
`_term_uuid()` over the three URIs reproduced all three orphaned
`predicate_uuid`s exactly, accounting for 3 of 3. Only then were the rows
inserted — 3 per space, 30 total, `ON CONFLICT DO NOTHING`, one transaction per
space.

No quad was rewritten. The repair is purely additive and idempotent: the quads
already carried the right UUID, and all that was missing was the row it pointed
at.

Verified through the running server, not just by re-running the join:

    hasObjectCreationTime            49.6 ms   3 rows
    hasObjectModificationDateTime    29.3 ms   3 rows
    hasObjectStatusType              17.8 ms   3 rows

All three returned 0 rows before.

## Two things this leaves behind

**The backfilled creation times are a sentinel.** Every one of the 109,745
`hasObjectCreationTime` values on `wordnet_frames` is `1970-01-01T00:00:00+00:00`
— the backfill had no real creation time and wrote epoch zero. The property is
now queryable and its value is meaningless, which is arguably worse than absent
because a query can now sort by it and get an answer. Modification times, by
contrast, hold genuine distinct timestamps. Whether epoch-zero is the intended
default for pre-existing objects is a product question, not a bug report.

**The failure mode is silent by construction.** A missing term row does not
error; the predicate simply never matches. That is the same shape as
`issues/082` (a failed query reported as a successful empty result) and as the
dead-predicate bug that made graph expand return nothing. There is no check
anywhere that every `predicate_uuid` in `{space}_rdf_quad` resolves — the query
that found this is three lines and ran across 78 spaces in seconds, and would
make a reasonable integrity check for a maintenance job.

## Related

- `62cb5dd` — the code fix, 2026-08-06
- `issues/archive/008` — vector upsert dropping the subject URI: a different
  writer, same class of defect (a row referenced with no term row behind it)
- `issues/archive/003` — the concurrent-insert term race, on the same table
- `issues/082` — silent empty results, the failure mode this shares
