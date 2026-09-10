# The Write-Path Matrix Enforces "Every Write Path" Over One File

## Status: OPEN — found by falsifying the test, not by reading it. The check is
## real and valuable; its SCOPE is one module while its promise is the tree.

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
