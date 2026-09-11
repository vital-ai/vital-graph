# The Write-Path Matrix Enforces "Every Write Path" Over One File

## Status: FIXED 2026-09-11. `_IMPL` is now `MODULES` and `WRITE_PATHS` is
## (module, function) pairs, covering 12 write paths across 4 modules instead of
## 8 across 1.
##
## VERIFIED BY FALSIFICATION, the way the defect was found: deleting the
## maintenance calls from `kg_backend_utils.py` now fails **53** assertions.
## Before this change it left the suite fully green.
##
## Body extraction moved from a `    async def ` regex to AST. That pattern
## assumed a four-space indent, so it could only ever see methods on one class —
## the write paths outside the space implementation are module-level functions
## and methods at other depths, which is part of why they stayed invisible.
##
## It immediately answered the question this issue left open, and the answer was
## yes — see `issues/187`. Six write paths maintain `edge` and `frame_slot` and
## skip `entity_slot_sort`, where a stale row is a wrong SORT ORDER.
##
## Two judgements the widening forced, which is what the matrix is for:
##
##   * `resync_all.py` and `bulk_export.export_space` are NOT write paths —
##     one rebuilds every mirror from the quads, the other only COPYs out.
##     `bulk_export.import_space` IS, and is in the matrix.
##   * `update_entity_subject_only` is EXEMPT from all three, on the reason
##     stated in its own docstring: it deletes only quads whose subject IS the
##     entity, which carries no edge-source/dest properties and is not a frame.
##
## One marker was also wrong in the false-negative direction:
## `import_ntriples_bulk` maintains everything by calling
## `resync_all_auxiliary_tables`, and read as a triple gap until a full rebuild
## was accepted as maintenance — the same correction the file already documents
## for `resync_stats_for_predicates`.

**Raised:** 2026-09-09, while retiring `frame_entity` (`issues/183`). A manual
audit had missed five write paths; this test was expected to have caught them
and does not.

**Related:** `issues/183`, `edge_table_integrity_bug.md`,
`tests/unit/sparql_sql/test_derived_table_maintenance.py`

## The defect

The test's own first line is:

    Every write path must maintain every derived table, or say why not.

It enumerates eight write paths and greps their bodies for sync markers. It
reads exactly one file:

```python
_IMPL = (pathlib.Path(__file__).resolve().parents[3]
         / "vitalgraph" / "db" / "sparql_sql" / "sparql_sql_space_impl.py")
```

Write paths that change quads and live elsewhere are outside its scope
entirely — not exempted, not listed as gaps, simply invisible:

  * `vitalgraph/kg_impl/kg_backend_utils.py` — three delete paths
  * `vitalgraph/db/sparql_sql/resync_all.py`
  * `vitalgraph/db/sparql_sql/bulk_export.py`
  * `vitalgraph/endpoint/impl/data_import_impl.py` — three import paths

## Demonstrated

Deleting **all three** derived-table maintenance calls from
`kg_impl/kg_backend_utils.py` leaves the suite fully green — 30 passed. The
matrix cannot see them.

This was found the way it should be: by removing a call and checking the test
fails. It did not.

## Why this matters more than a coverage gap

The test exists because of a specific production incident.
`edge_table_integrity_bug.md` records an edge table ~25% incomplete because
"the edge table is maintained by only ONE of many write paths", and the symptom
was entity, frame and relation queries silently under-counting.

A test written to prevent "one path was missed" that itself scans one file
reproduces the original failure shape at the level of the guard. Its docstring
argues, correctly, that a hand-kept matrix goes stale and a derived one does
not — and then derives from a single module.

## What it cost immediately

While retiring `frame_entity` its replacement's maintenance calls were added to
`sparql_sql_space_impl.py` and `data_import_impl.py`, an audit reported
"9 calls to 9 calls" parity, and five write paths in three other files were
missed. They were found by grepping for residual callers, not by the matrix and
not by the audit.

## The fix

`_IMPL` becomes a list of modules that contain quad-changing write paths, and
`WRITE_PATHS` becomes (module, function) pairs. The exemption and known-gap
machinery already handles per-pair decisions and needs no change.

The harder half is deciding what counts as a write path outside the space
implementation — `resync_all` and `bulk_export` REBUILD rather than mutate, so
they may belong in EXEMPT with that as the reason rather than in the matrix. That
is a judgement per module, which is exactly what the test is designed to force.

## What is NOT established

- Whether other derived tables (`edge`, `entity_slot_sort`) are ALSO unmaintained
  on the four unscanned modules. The same grep that found the `frame_slot` gap
  would answer it, and it was not run for them.

## The sweep, completed — and four more misses it found

`issues/183` retired `frame_entity` for `frame_slot`. The audit that was
supposed to catch every path that touched it missed these, each of which kept
RESOLVING and so failed silently rather than loudly:

| path | what it did instead |
|---|---|
| `sparql_sql_space_impl` DROP GRAPH | called `delete_frame_entity_for_context`; cleared nothing, 14 rows survived a dropped graph |
| `maintenance_job` sweep | called `cleanup_stale_frame_entity` on a table that no longer exists, so `cleanup_stale_frame_slot` had NO scheduled caller |
| `maintenance_job` self-heal | called `backfill_frame_entity_table`; that function had no `frame_slot` equivalent at all until now |
| `sync_entity_fanout` | rebuilt the hub diagnostic FROM `frame_entity`, so every resync wrote nothing and the diagnostic read "no hubs" |
| `geo_slot_handler` | see below — worse |
| `ops/database_op`, `traversal_chain` | stale table lists and documentation |
| `sparql_sql_space_impl` incremental write | a DEAD import of the retired module beside live `frame_slot` calls |

**The pattern is one thing: the module still existed.** Deleting a table while
leaving its module importable means every call site keeps compiling, keeps
running, and keeps doing nothing. A missing module would have failed on the
first import; a missing table failed only where something read the result.

### `geo_slot_handler` was never right, not merely stale

`issues/184` recorded that this fast path has never executed. The reason is
worse than staleness: the query selected `fe.entity_uuid`, **a column
`frame_entity` never had** — it named its two roles as `source_entity_uuid` and
`dest_entity_uuid`. So it raised on every call since it was written and always
fell through to the quad walk.

`frame_slot` is one row per slot and does carry `entity_uuid`, which is the
shape the query was always written for, so repointing it also fixes it.

### A test that skips forever passes forever

`tests/integration/test_frame_entity_staleness_is_detected.py` now reports
`SKIPPED [4] no space on this stack has a populated frame_entity`. It will skip
for as long as the table is absent, which is permanently. A test whose guard
can never be satisfied is indistinguishable from one that passes, and this file
exists because of exactly that failure mode.

Still open: four test files and two scripts import `sync_frame_entity_table`.
The module is inert, but leaving it importable is the same hazard as above.
