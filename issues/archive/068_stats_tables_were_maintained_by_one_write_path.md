# `rdf_stats` Was Maintained by One Write Path, and Nothing Self-Healed It

## Status: FIXED 2026-08-10 — the write-path gap; one bounded case still logs a skip

The third derived structure to have this exact defect, after the edge table
(`issues/041`) and frame_entity. Found by writing the test the coverage rule in
`performance_regression_tracking_plan.md` R6 asks for.

## What was wrong

| path | maintained `rdf_stats`? |
|---|---|
| `add_rdf_quads_batch_bulk` | yes |
| `add_rdf_quads_batch` | **no** |
| `execute_sparql_update` | **no** |
| maintenance job | **prunes only — never resyncs** |

The edge table at least had a backfill self-heal. Stats had none: the
maintenance job's only stats step is `prune_stats_tables`, which bounds the
table's size and cannot correct a number.

## Why it went unnoticed

A wrong count does not produce a wrong answer. It produces a wrong **plan**.

`rdf_stats` feeds the join-reorder heuristic and the semi-join selectivity gate,
so an overstated count makes a predicate look less selective, the reorder seeds
from the wrong leaf, and the gate declines to probe. The query returns exactly
the right rows, just far slower. Nothing about the result reveals it, and no
correctness test can.

That also makes it the most likely explanation for a class of "why is this query
suddenly slow" reports on spaces written through the REST or SPARQL paths, since
those are precisely the ones that maintained nothing.

## Fix

* `add_rdf_quads_batch` now syncs stats, from the rows that **actually landed** —
  `ON CONFLICT DO NOTHING` means a duplicate quad inserts no row, and counting
  it would inflate the stats it is meant to correct.
* `execute_sparql_update` recomputes stats for the predicates it touched.
  A SPARQL update usually binds subject and object but names the predicate
  literally — `DELETE WHERE { ?s <p> ?o }` — so although the affected quads
  cannot be enumerated without executing, **the set of predicates whose counts
  moved is known exactly**, and recomputing those is bounded by one predicate's
  rows rather than the table.

`resync_stats_for_predicates` also fixes `rdf_pred_stats`, which is not pruned
and therefore must always be exactly right — a delete that empties a predicate
has to leave 0, not a stale row.

## The one case still not covered, deliberately

A predicate with more than `max_rows` (default 2,000,000) quads is skipped: the
recompute is a `GROUP BY` over that predicate's rows, and doing it inline on
`vitaltype` — 10,054,000 rows in one measured space — would be a serious
per-write regression.

The skip is **logged at warning level**, not silent. That is the whole
difference between this and the defect it replaces.

Proper answers, none implemented:

1. A dirty-predicate marker plus a maintenance step that recomputes lazily,
   which is what the edge table's backfill does for its own drift.
2. Order-of-magnitude counts (`issues/061`), where a write only persists on a
   bucket crossing — the recompute becomes exponentially rarer and the hot-row
   contention on shared pairs like `(vitaltype, KGEntity)` goes away.

## Still open from the same family

`issues/062` — pruning and incremental maintenance still interact badly: a
pruned row that a later write resurrects comes back holding only its post-prune
delta, demonstrated at 100,000 → 1. Fixing the write path does not fix that;
absence has to *mean* something, which is the per-predicate MCV proposal in
`issues/061`.

## Tests

`tests/integration/test_stats_tables_after_crud.py`. Asserts that every count
**stored** equals the true count — not that every pair is present, since pruning
legitimately removes rows. A guard test asserts stats are non-empty after a
create, which is what caught the whole thing: the file would otherwise have
passed vacuously against an empty table.

## Related

- `issues/041` — the same write-path gap in the edge table
- `issues/064` — the same gap on the delete side
- `issues/061`, `issues/062` — retention policy and the resurrection bug
