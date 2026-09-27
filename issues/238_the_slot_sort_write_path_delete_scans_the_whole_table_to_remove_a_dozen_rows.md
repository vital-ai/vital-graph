# 238 — The `entity_slot_sort` write-path delete scans the whole table to remove a dozen rows

## Status: FIXED 2026-09-25 in `sync_entity_slot_sort.py`.
## Found by measurement on production: 59.6 hours across 647,255 calls, on the
## WRITE path, inside the entity lock. Plan confirmed by EXPLAIN before and
## after, equivalence pinned by test. See "The fix, and what it measured".

## The fix, and what it measured

`_TOUCHED_FILTER`'s two `IN (SELECT ...)` arms are now resolved into a `$2`
array by `_edge_dest_nodes`, one index scan on `idx_{space}_edge_edge`, run in
the caller's transaction immediately before the DELETE — so it reads exactly the
edge rows the subquery form would have read. All five reachability arms survive.

**The plan, on the production table with production statistics:**

    before   Seq Scan on lead_prod_entity_slot_sort (cost=54.20..73066.90 rows=718210)
    after    Bitmap Heap Scan ... BitmapOr of 5 Bitmap Index Scans
                                             (cost=79.31..477.41 rows=345)

**The cost, on a REAL space at above-production scale.**
`sp_lead_synth_100k_entity_slot_sort` on the vg test stack is 4,063,149 rows /
2,361 MB, against production `prod_kg`'s 3,027,690 / 1,872 MB. Uuids drawn
FROM the table so the filter matches real rows — 343 of them — and the heap
fetches are real. `SELECT count(*)` rather than DELETE so it is read-only and
repeatable; 5 runs, median:

| | plan | min | median | max |
|---|---|---:|---:|---:|
| old | Seq Scan | 1,032.2 ms | **1,106.8 ms** | 1,315.7 ms |
| new | BitmapOr | 0.6 ms | **0.7 ms** | 1.5 ms |

**1,496x, and both forms match the same 343 rows.** The old form's 1,107 ms on
4.06M rows sits on the same line as production's 721 ms on 3.03M.

**The scaling property, on synthetic tables at two sizes** — the point being
which variable the cost follows:

| table rows | old | new |
|---:|---:|---:|
| 500,000 (114 MB) | 86.1 ms | 0.6 ms |
| 2,000,000 (452 MB) | 346.8 ms | 0.8 ms |

4.0x the rows costs the old form 4.03x the time and the new form nothing. So the
cost was proportional to the TABLE and is now proportional to the uuids passed
in, which is why the win GROWS as a space grows. No data migration is needed;
the benefit is in the query shape, so it lands
wherever the code runs.

**Tests:** `tests/integration/test_slot_sort_touched_filter_equivalence.py`, 15
cases. The pre-rewrite SQL is kept verbatim as an oracle and compared against
the implementation on the same data — once per reachability arm so a failure
names the arm, once with all five at play, once over five randomised graphs, and
once for the `context_uuid` form whose parameter moved from `$2` to `$3`. Two
plan tests bracket the defect: the new shape must not produce a `Seq Scan`, and
the old shape still must — because the two forms return identical rows, so
without that second assertion nothing would notice the rewrite being undone.

**Tracked by:** `issues/239` (background work is ~half the production
database — this is one member of that group)

**Related:** `issues/187` (FIXED — wired the six write paths to maintain this
table; this delete is that fix's implementation), `issues/194` (FIXED — the same
wave across the two prop-sort tables, which carry the same filter shape),
`issues/171` PART 2 (OPEN — "prove it under realistic load", the measurement
that would have caught this), `issues/173` (the entity advisory lock this runs
inside), `planning/planning_performance/maintenance_incremental_only_plan.md`
(the incremental-only principle — violated here on the write path rather than on
a loop)

## The defect

`sync_entity_slot_sort.py:292-300`, `_TOUCHED_FILTER`:

```sql
(slot_uuid  = ANY($1)
 OR entity_uuid = ANY($1)
 OR frame_uuid  = ANY($1)
 OR slot_uuid  IN (SELECT dest_node_uuid FROM {t_edge} WHERE edge_uuid = ANY($1))
 OR frame_uuid IN (SELECT dest_node_uuid FROM {t_edge} WHERE edge_uuid = ANY($1)))
```

Every arm is individually indexable — the table has `pkey (slot_uuid,
context_uuid)`, `idx_..._ess_entity (entity_uuid)`, `idx_..._ess_frame
(frame_uuid)`, and the edge table has `idx_..._edge_edge (edge_uuid)`. **A
BitmapOr is nonetheless impossible**, because the last two arms are subquery
semi-joins: the planner turns them into `hashed SubPlan`s, and a BitmapOr can
only combine indexable conditions. One unindexable arm forces the whole
disjunction to a sequential scan.

Confirmed on production (`EXPLAIN`, 50-element arrays):

    Delete on lead_prod_entity_slot_sort  (cost=56.09..73068.78 rows=0)
      ->  Seq Scan on lead_prod_entity_slot_sort  (cost=54.20..73066.90 rows=718210)
            Filter: (... OR (ANY (slot_uuid = (hashed SubPlan 5).col1))
                         OR (ANY (frame_uuid = (hashed SubPlan 7).col1)))
            SubPlan 5 -> Index Scan using idx_lead_prod_edge_edge
            SubPlan 7 -> Index Scan using idx_lead_prod_edge_edge

The two subqueries are index scans. The outer table is read end to end. The
estimate — **718,210 rows, 75% of the table** — is what the planner believes a
five-armed OR selects; the statement actually deletes about eleven.

## The cost is proportional to the TABLE, not to the work

`pg_stat_statements`, 57-day window:

| table | rows in table | heap | calls | mean | max | rows deleted / call | total |
|---|---:|---:|---:|---:|---:|---:|---:|
| `prod_kg` | 3,027,690 | 618 MB | 100,905 | **721 ms** | 14,425 ms | 19 | 20.2 h |
| `lead_prod` | 957,518 | 178 MB | 407,790 | **249 ms** | 11,438 ms | 11 | 28.1 h |
| `lead_prod` (2nd site) | " | " | 121,375 | 248 ms | 2,793 ms | 2 | 8.3 h |
| `prod_kg_archive` | 223,717 | 50 MB | 2,787 | **59 ms** | 842 ms | 35 | 0.03 h |
| | | | **647,255** | | | | **59.6 h** |

Read the first three rows together:

    3,027,690 / 957,518 = 3.16x rows   ->   721 / 249 = 2.90x time
      957,518 / 223,717 = 4.28x rows   ->    249 / 59 = 4.22x time

**The per-call cost tracks table size across a 13x range and is flat in rows
deleted** (11, 19 and 35 respectively — the smallest table deletes the MOST rows
per call and is the fastest). That is the signature of a full scan, and it means
the cost grows with the space forever: every entity update on `prod_kg` will
get slower as `entity_slot_sort` grows, for no additional work done.

At 59.6 hours this is the single most expensive write-path statement in the
database — the same order as the largest maintenance statements in `issues/143`.

## It is paid while holding the entity lock

`kg_backend_utils.update_entity_graph` runs, in one transaction:

1. `lock_entities(conn, [entity_uri])` — the advisory lock from `issues/173`,
   which exists to serialise concurrent writers to one entity;
2. `sync_frame_slot_before_delete`, `sync_edge_table_before_delete`,
   **`sync_entity_slot_sort_before_delete`** ← this scan;
3. the quad delete;
4. the re-insert.

So the scan is inside the critical section. Production shows
`SELECT pg_advisory_xact_lock($1)` at **411,639 calls with a 386 ms mean** —
44 hours spent waiting to acquire entity locks. That number is unexplained on
its own and entirely unsurprising if every holder runs a 249–721 ms sequential
scan before doing its actual work. The two were not correlated directly, and
that is worth doing before assuming causation — but the mechanism is present.

## The fix

**Resolve the subqueries first, then delete on indexable arms only.** The edge
lookups are already index scans; running them as separate statements costs two
index probes and turns the delete into a BitmapOr over three uuid arrays:

```python
extra = await conn.fetch(
    f"SELECT dest_node_uuid FROM {t_edge} WHERE edge_uuid = ANY($1)", uuids)
dests = [r["dest_node_uuid"] for r in extra]
# then: WHERE slot_uuid = ANY($1) OR entity_uuid = ANY($1)
#          OR frame_uuid = ANY($1) OR slot_uuid = ANY($2) OR frame_uuid = ANY($2)
```

All five arms are then plain `= ANY(array)` on indexed columns, which BitmapOr
combines. The cost becomes proportional to the uuids passed in rather than to
the table.

**The semantics must not change.** The filter's comment explains why each arm
exists — "repointing a slot's value touches only the slot, so a delete keyed on
the entity would match nothing, the re-derive would hit ON CONFLICT DO NOTHING,
and the row would keep the OLD value forever. The row COUNT never changes in
that failure, so no drift check can see it." Any rewrite has to preserve all
five reachability arms; this one does, by evaluating two of them eagerly.

**The prop-sort tables were checked and do NOT have this shape.** `issues/194`
wired `entity_prop_sort` and `frame_prop_sort` in the same wave, so they were
the obvious place for a copy — but `IN (SELECT dest_node_uuid` occurs exactly
twice in the repository, both in `sync_entity_slot_sort.py`, and both are the
arms fixed here.

## Not established

  * Whether the advisory-lock wait is actually caused by this. The correlation
    is suggestive and the ordering makes it plausible; neither was measured.
  * Whether a rewrite to `EXISTS` would have let the planner keep a single
    statement. `EXISTS` is usually the better transform for a semi-join, but it
    does not obviously help a DISJUNCTION — it was not tried, and the two-statement
    form measured well enough that it was not worth pursuing.
  * **`sync_entity_slot_sort_after_edge_insert` carries the same two
    indirections** in its INSERT's `WHERE` (`$8`). That one filters a seeded
    walk rather than scanning `entity_slot_sort`, so it is a different shape and
    was deliberately left alone — but it was not planned or measured, and it is
    the obvious next place to look.
  * Why `lead_prod` has two distinct call sites with the same filter and very
    different `rows` per call (11 vs 2). Probably two callers with different
    batch shapes; not traced.
  * What this costs on the derived-table REBUILD paths, which use the same
    module. Only the `_before_delete` entry points were measured.
