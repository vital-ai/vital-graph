# `entity_slot_sort` Is Unmaintained By Six Write Paths

## Status: OPEN — found 2026-09-11 by widening the write-path matrix
## (`issues/185`). Named in `KNOWN_GAPS` so the suite passes while the gap is
## visible; NOT wired.

**Related:** `issues/185` (the matrix that could not see these),
`issues/096` (why a stale row here is a wrong ANSWER), `edge_table_integrity_bug.md`

## The defect

Six quad-changing write paths maintain `{space}_edge` and `{space}_frame_slot`
and do NOT maintain `{space}_entity_slot_sort`:

| module | write path |
|---|---|
| `kg_impl/kg_backend_utils.py` | `upsert_objects_atomic` |
| `kg_impl/kg_backend_utils.py` | `update_entity_graph` |
| `kg_impl/kg_backend_utils.py` | `update_subjects_graph` |
| `endpoint/impl/data_import_impl.py` | `import_ntriples_incremental` |
| `endpoint/impl/data_import_impl.py` | `import_jsonl_quads_incremental` |
| `endpoint/impl/data_import_impl.py` | `import_vital_block_incremental` |

No stated reason in any of them. They are not exempt — each syncs the other two
mirrors in the same function, so the omission reads as an oversight rather than
a decision.

## Why it is a wrong answer, not a slow query

`issues/096` built `entity_slot_sort` as a STRUCTURAL MIRROR: `fast_slot_sort`
reads the ORDER straight off this table. A stale row does not make a sort
slower, it makes it **wrong** — the same class as the production incident in
`edge_table_integrity_bug.md`, where an edge table ~25% incomplete made entity,
frame and relation queries silently under-count.

## How it was found

`issues/185` listed this exactly, under **"What is NOT established"**:

> Whether other derived tables (`edge`, `entity_slot_sort`) are ALSO
> unmaintained on the four unscanned modules. The same grep that found the
> `frame_slot` gap would answer it, and it was not run for them.

Widening the matrix to (module, function) pairs ran it. The answer is yes.

`update_entity_subject_only` is NOT in this list. It maintains nothing, and
that is correct: it deletes only quads whose subject IS the entity, which
carries no edge-source/dest properties and is not a frame. Its docstring says
so, which is why it is an EXEMPT entry rather than a gap — the distinction the
matrix exists to force.

## Not established

* **Whether the incremental import paths are reachable in a way that matters.**
  A bulk import calls `resync_all_auxiliary_tables` and rebuilds everything; the
  incremental ones do not. How much production traffic uses them is unmeasured.
* **How stale the table actually is in production.** No drift figure was taken
  for `entity_slot_sort` on the affected spaces. `issues/096` built drift
  detection for it; running that per space would size the problem before any
  fix.

## The fix

Wire `sync_entity_slot_sort_after_edge_insert` / the delete-side counterpart
into the six paths, beside the `edge` and `frame_slot` calls already there, and
remove the `KNOWN_GAPS` entries.

**Measure first.** `issues/178` records six rewrites that were argued
convincingly and reverted after measurement; the cheap check here is the drift
figure per space, not the wiring.
