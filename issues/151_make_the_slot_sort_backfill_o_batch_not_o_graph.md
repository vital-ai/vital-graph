# Make The Slot-Sort Backfill O(batch), Not O(graph)

## Status: IMPLEMENTED 2026-09-03 after P1-P3 passed locally, EXCEPT S2(b).
## See "Measured" for the numbers, and "What was NOT implemented" for the gap.

## What was NOT implemented

S2 recommended option **(b)** — keep `entity_slot_sort_drift` running rarely as
an ADVISORY number, never gating a repair, so a ROW-LEVEL regression stays
visible. Coverage counts ENTITIES; drift counts SLOT ROWS. An entity present
with some of its slots missing is covered but not complete, and nothing now
detects that.

**The advisory caller is not written.** Drift is off the repair path (done) and
has no caller at all (not done). Both `entity_slot_sort_drift` and the O(graph)
`backfill_entity_slot_sort` are labelled in their docstrings as NOT on the
maintenance loop so they are not mistaken for live code — the latter is kept
deliberately as an operator escape hatch.

Closing this needs a decision about cadence and where it logs. It is a gap in
observability, not in the repair.

## Why this exists

`issues/150` stopped `entity_slot_sort_drift` running on every maintenance
cycle. It gates on changed data, so a quiet space no longer pays 216-303s per
cycle for a full `WITH RECURSIVE` walk that was consuming **54% of wall-clock**
and starving user queries (a two-frame existence check measured 1.5s idle and
58s while the probe ran; a benchmark reported 58% of runs stalling).

**The gate controls WHEN the walk runs, not HOW MUCH it walks.** On a space with
constant writes — which the affected one is — changed data unblocks it almost
every cycle and the walk is still O(graph). The gate is the right stopgap and it
is not the fix.

## The proposal, in three parts

1. **Keep coverage ungated as the detector.** Already done (`478fa06`).
   `entity_slot_sort_coverage` measures **130 ms** and counts entities from the
   QUADS, so it cannot be fooled by the derivation it is checking — that is
   `issues/149`'s lesson, and it is the same defect class as `issues/141`.
2. **Replace drift's full walk with coverage for the DECISION.** Drift becomes
   advisory, or drops. Today the walk re-derives a total in order to conclude
   something coverage already reported for 130 ms.
3. **Seed the backfill per type, in bounded batches**, driven by what coverage
   reports short.

This is a real design change to a table with a bad history — `issues/144`
(built, 0.6% populated, consulted by nothing), `issues/149` (repair fenced out
of existence), `issues/150` (the probe that ate the box). It gets the same
treatment as the last one: **prototype, measure, then commit.**

---

## What already exists, and is the reason this is cheap

The seed machinery is built and in production on the write path:

    _select_rows(space_id, where, *, seed_param=None)     # sync_entity_slot_sort.py:132
        seed_param -> " AND fe.source_node_uuid = ANY(<param>)"

    sync_entity_slot_sort_after_edge_insert   SEEDED     <- write path
    resync_entity_slot_sort                   FULL WALK
    backfill_entity_slot_sort                 FULL WALK
    entity_slot_sort_drift                    FULL WALK

`_frame_roots` already climbs `edge.dest_node_uuid -> source_node_uuid` to
`MAX_FRAME_DEPTH` to find which entity roots a change could reach, measured at
**58-164 ms**. The seeded write path was measured at 24,571->1,473ms,
16,897->467ms, 8,452->300ms, 5,934->32ms, row-identical against the unseeded
walk on production.

So the proposal is not new machinery. It is **pointing the existing seed at a
different source of UUIDs**: instead of "entities touched by this write", "a
batch of entities of the type coverage says is short".

---

## Spec

### S1. Coverage is the detector (DONE — stated for completeness)

    entity_slot_sort_coverage(conn, space_id, limit=5, timeout=None)
        -> [{entity_type, in_table, of_type, ratio}, ...]  worst shortfall first

Counts `hasKGEntityType` subjects from `{space}_rdf_quad` against
`count(DISTINCT entity_uuid)` in `{space}_entity_slot_sort`. 130 ms measured.
Independent of the walk by construction.

### S2. Retire drift's full walk from the decision path

**Current:** `_run_entity_slot_sort_integrity` picks the worst space by
`expected - actual`, where `expected` comes from the full walk.

**Proposed:** pick by coverage shortfall — `of_type - in_table`, already
returned by S1, already ordered by it.

Two things this gives up, and they should be stated rather than discovered:

* **Row-level drift becomes invisible.** Coverage counts ENTITIES; drift counted
  SLOT ROWS. An entity present with some slots missing is covered but not
  complete. The write path prevents that class (delete-then-re-derive), and
  `entity_slot_sort_drift`'s own docstring already admits it cannot see a stale
  VALUE either. So this narrows an already-partial check.
* **The `expected` total goes away.** Nothing else consumes it.

**Options for drift itself**, pick one deliberately:

    (a) DROP it. Least code. Loses the row-level count entirely.
    (b) Keep it ADVISORY — run it rarely (daily, or on demand) purely to log a
        number, never gating a repair. Keeps the signal, removes it from the
        hot path.
    (c) Keep it, seeded, over the SAME batch the backfill just processed, so it
        reports drift for known-touched entities rather than a global total.
        Cheap and useful; not a total, and must not be presented as one.

Recommendation: **(b)**. It preserves the one number that would reveal a
row-level regression, at a cadence where 216-303s is affordable, and it cannot
starve reads because nothing waits on it.

### S3. Seed the backfill per type, in bounded batches

**New:** `backfill_entity_slot_sort_for_type(conn, space_id, entity_type_uuid,
batch_size)`.

    1. Select up to `batch_size` entity UUIDs OF THAT TYPE that are absent from
       {space}_entity_slot_sort:

           SELECT q.subject_uuid
             FROM {space}_rdf_quad q
             JOIN {space}_term p ON p.term_uuid = q.predicate_uuid
              AND p.term_text = <hasKGEntityType>
            WHERE q.object_uuid = $1
              AND NOT EXISTS (SELECT 1 FROM {space}_entity_slot_sort e
                               WHERE e.entity_uuid = q.subject_uuid)
            LIMIT $2

    2. Pass them as the seed:

           INSERT INTO {space}_entity_slot_sort (...)
           {_select_rows(space_id, 'TRUE', seed_param='$N')} {_ON_CONFLICT}

    3. Return the count inserted. Zero means this type is done.

**Batch size**: start at 500 entities. The write path's seeded walk measured
32-1,473ms for its (smaller) seed sets; 500 should land in the low seconds.
**Measure before choosing** — that number is a guess and is the single most
important thing the prototype must establish.

**Cadence**: one batch per maintenance cycle per space, like
`_SWEEP_SPACES_PER_CYCLE`. At 500/cycle and 300s cycles, 77k entities is ~13
hours. Acceptable for a backlog that has stood for months; tune upward once the
per-batch cost is known.

**Termination**: when step 1 returns zero rows for every short type, coverage
reports 100% and `mark_probe_converged` records it, so `issues/150`'s gate lets
the space go quiet.

### S4. What must NOT change

* **The write path stays as it is.** It is already seeded, already measured, and
  is what keeps the table current once the backlog is gone.
* **`resync_entity_slot_sort` keeps its full walk.** It TRUNCATEs and rebuilds;
  that is a deliberate "start over" and must not be partial. It is operator-run,
  not on the maintenance loop.
* **Coverage stays ungated.** 130 ms, and it is the only thing that can see the
  failure `issues/149` recorded.

---

## Measured (P1-P3, local test stack, 2026-09-03)

**P1 — is selecting a batch cheap?** This was the kill switch: if picking the
batch is itself expensive, the design fails and nothing else matters.

    batch-select, 500 of 2,000 entities:  7 ms

**P2 — how does the seeded walk scale with batch size?**

    batch=100    selected=100   inserted=100     53 ms   (0.53 ms/entity)
    batch=500    selected=500   inserted=500     30 ms   (0.06 ms/entity)
    batch=2000   selected=2000  inserted=2000   151 ms   (0.08 ms/entity)

Linear in batch size with a small fixed overhead. Against the unseeded walk's
216-303s, that is the whole point.

**TWO CAVEATS ON THESE NUMBERS, both understating real cost:**

1. The local fixture is ONE frame and ONE slot per entity. Production entities
   carry several frames and many slots at depth, so ms/entity there will be
   higher — possibly by an order of magnitude. What P2 establishes is the
   SHAPE (linear, bounded), not the constant.
2. The fixture is small enough to be entirely cached. Production is not
   (`issues/150`: the working set exceeds shared_buffers).

Re-measure on the test stack with a production-shaped fixture before raising
`VG_ESS_BACKFILL_BATCH` above 500.

**P3 — equivalence.** `tests/integration/test_slot_sort_batched_backfill.py`.
The seeded batch derives exactly what the unseeded walk derives for the
entities it covered, including the depth-2 slot that a non-recursing walk
loses. The reference set is asserted NON-EMPTY first — this fixture family has
twice produced a comparison that passed because both sides were empty.

Also pinned: convergence (repeated batches finish, `selected == 0` means done)
and the termination hazard (an entity that derives nothing is reported as
`selected > 0, inserted == 0` rather than silently re-selected forever).

## Prototype and measurement plan

Do this before writing S2 or S3 into the job. `issues/070` is the precedent for
why: a barrier change implemented, measured, and REVERTED at 41x worse.

    P1. On the test stack, run the S3 step-1 query for the short type. Confirm
        it uses an index and returns in ms, not seconds. If selecting the batch
        is itself expensive, the design fails here and nothing else matters.

    P2. Run one seeded backfill batch at 100 / 500 / 2000 entities. Record
        wall-clock and buffers for each. Pick the batch size from this, not from
        the guess above.

    P3. Verify EQUIVALENCE: run the seeded batch, then a full
        resync_entity_slot_sort, and assert the seeded result is a SUBSET with
        identical rows for the entities it covered. The existing
        `test_entity_slot_sort_seeded_walk.py` already does this shape for the
        write path — extend it rather than writing a new one.

    P4. Only then wire S2/S3 into _run_entity_slot_sort_integrity.

**The trap to avoid, recorded because this exact fixture has produced it twice:**
a comparison that passes because both sides are empty. The seeded-walk fixture
originally compared `set() == set()` and passed. Every equivalence assertion
must first assert the unseeded side is NON-EMPTY.

---

## Expected effect

| | today | proposed |
|---|---|---|
| detect shortfall | full walk, 216-303s | coverage, 130 ms |
| repair one step | full walk, 216-303s | seeded batch, target < 5s |
| duty cycle on a busy space | up to 54% | bounded by batch size |
| time to clear a 2.7M backlog | never (it times out or starves reads) | ~13h at 500/cycle |

The last row is the point. The current design cannot finish, and every attempt
to make it finish has made reads worse.

## Generalised

The rule this produced is written up as
`planning/planning_performance/maintenance_incremental_only_plan.md`:

> No recurring job may perform a full walk or full scan of a space. Periodic
> work runs OFTEN and does a BOUNDED UNIT if there is anything to do, and
> nothing otherwise.

It also records that a time-based interval is a CONFESSION that work is neither
bounded nor incremental — which is what `2209009`'s hourly watch gating is, and
it says so.

## Related

- `issues/149` — the repair fenced out of existence; coverage probe added
- `issues/150` — the gate, shipped, and why it is only a stopgap
- `issues/144` — the table built, 0.6% populated, consulted by nothing
- `issues/143` — maintenance as a share of wall-clock; rec #1 partially done
- `issues/070` — a barrier change measured and reverted; why P1-P3 exist
