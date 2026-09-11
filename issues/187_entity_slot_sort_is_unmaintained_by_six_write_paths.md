# `entity_slot_sort` Is Unmaintained By Six Write Paths

## Status: OPEN, but DOWNGRADED after measurement — the gap is LATENT, not
## active. Measured 2026-09-11 on production: **no shortfall on any space.**
## Named in `KNOWN_GAPS`; deliberately NOT wired.

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

## Measured — and the answer changes the priority

Run 2026-09-11 with `entity_slot_sort_coverage`, which counts entities from the
QUADS and so cannot be confirmed by the derivation it checks:

    PRODUCTION
      cardiff_kg    2,898,205 rows    no shortfall
      lead_data     1,102,169 rows    no shortfall
      lead_prod       797,006 rows    no shortfall

    DEV (11 populated spaces)
      10 of 11      no shortfall
      sp_kg_rel     4,500 of 4,875    92.31%

**The six unmaintained write paths have produced no observable staleness.**

### Why, and it is not luck

The maintenance job already repairs this table, and on the independent probe:

    DETECT   entity_slot_sort_coverage — counts from the quads
    REPAIR   one seeded batch of ONE short type per cycle

So a row these paths fail to write is picked up by the background repair. That
is why the defect is real in code and invisible in the data.

### What that does and does not license

It does NOT make the gap acceptable. The repair is **one batch of one type per
cycle** — a bounded rate. A write burst concentrated on those six paths can
outpace it, and nothing in the current measurement says how much headroom there
is.

It DOES mean wiring six write paths is not urgent, and the measurement was worth
taking before doing it. `issues/178` records six rewrites argued convincingly
and reverted after measurement; this is the same discipline applied before the
work rather than after.

### Use coverage, not drift

`entity_slot_sort_drift` compares the table against `_select_rows` — the same
walk that populated it — so when the walk is at fault the two agree and it
reports converged. Production measured **809 entities against 76,996 of that
type with drift satisfied** (`issues/149`). Any future sizing of this issue must
use `entity_slot_sort_coverage`.

## The fix

Wire `sync_entity_slot_sort_after_edge_insert` / the delete-side counterpart
into the six paths, beside the `edge` and `frame_slot` calls already there, and
remove the `KNOWN_GAPS` entries.

**The measurement is done** (above) and says this is not urgent. If it is
taken up, the work is to wire `sync_entity_slot_sort_after_edge_insert` and its
delete-side counterpart into the six paths beside the `edge` and `frame_slot`
calls already there, then remove the `KNOWN_GAPS` entries.

Before that, the question worth answering is the one the measurement raised:
**how much headroom does the one-batch-per-cycle repair actually have?** If a
realistic write burst on these paths can outrun it, that is the argument for
wiring. If it cannot, the repair is the design and these paths are arguably
EXEMPT rather than broken.
