# 239 — TRACKER: background work is about half the production database

## Status: TRACKER, OPEN. Not a defect — an index over one, so the members are
## worked as a group and the group can be shown to be finished.

Every other issue in this repository is one defect. This one is deliberately
not: the members below were each found separately, each looks modest on its own,
and together they are roughly **half of all production database execution
time**. Filing them individually has already produced the failure this exists to
stop — `issues/150` records a full walk consuming 54% of wall-clock *after*
`issues/143` had removed a different full walk from the same loop. Fixing one
member and re-measuring the box tells you almost nothing; the next member fills
the gap.

**The binding principle is already written** and is not restated here:
`planning/planning_performance/maintenance_incremental_only_plan.md` — *no
recurring job may perform a full walk or full scan of a space.* Most of what
follows is that rule, unenforced in a particular place.

## The measurement that binds them

Production `pg_stat_statements`, 57-day window (reset 2026-07-30), 4-vCPU
`db.r6g.xlarge`, 114 GB database, **615 hours of total execution time**. Taken
2026-09-25 with the box otherwise IDLE — 19 idle connections, nothing running,
no ungranted locks — so this is background load, not an incident.

Production is used here for its 57 days of accumulated call counts, which is the
one thing a fresh local stack does not have. Every shape below reproduces
locally at the same or larger scale — see "All of this is reproducible locally".

| work | hours | share | issue |
|---|---:|---:|---|
| `ANALYZE` / `VACUUM` | 129.8 | 21.1% | `236`, `143` |
| drift + integrity probes | ~71.0 | 11.5% | `143` rec 1 (46.8 h GATED 2026-09-25), `150` |
| backfill graph discovery | 35.0 | 5.7% | `237` (GATED 2026-09-25) |
| `entity_slot_sort` write-path delete | 59.6 | 9.7% | `238` |
| stats recompute | 9.1 | 1.5% | `143` |
| **subtotal** | **~304** | **~49%** | |
| *(separately)* entity lock WAITING | 44.1 | 7.2% | unfiled, see below |
| *(separately)* vector segment inserts | 91.0 | 14.8% | unfiled, see below |

The three largest single statements in the entire database are `ANALYZE
"prod_kg_rdf_quad"`, `VACUUM "prod_kg_term"` and `ANALYZE
"prod_kg_term"`. **No user query appears until well down the list.**

Read the subtotal as an order of magnitude, not a precise figure: the
`entity_slot_sort` delete is write-path work that must happen in *some* form, so
the waste there is the excess rather than the whole. The ANALYZE/VACUUM,
discovery and probe rows are waste in full — they recompute what did not change.

## The members

| # | status | what remains |
|---|---|---|
| **143** | PARTIALLY FIXED; rec 1 DONE 2026-09-25 | **The parent.** Rec 2 landed (watches off the 300s loop); rec 1 finished 2026-09-25 — it was half built, and the missing half was 46.8 h on a never-written fixture space. Recs 3, 4 unwritten: gate the drift/self-link checks on change, sample instead of scanning, stagger spaces. Rec 1 is the single biggest remaining win and is *agreed in the code* — `sync_edge_table.py:435` says "THIS QUERY SHOULD NOT EXIST ON A SCHEDULE AT ALL". |
| **236** | FIXED 2026-09-25 | ANALYZE/VACUUM scheduled by staleness ALONE (`maintenance_job.py:1018`, `:1052` are conjunctions). Three idle fixture spaces have absorbed 32,115 ANALYZEs and 13,696 VACUUMs with zero pending mods and zero dead tuples. One-line inversion: make need necessary, let staleness order the queue. |
| **237** | FIXED 2026-09-25 | Backfill ran `SELECT DISTINCT` discovery over the quad table BEFORE the `backfill_state.is_complete()` gate that would skip it. Now cached on the same `quad_activity` counter the markers use: 535.8 ms → ~1.7 ms per cycle on a real 74M-quad space, one scan instead of five. |
| **238** | FIXED 2026-09-25 | `entity_slot_sort` delete was a Seq Scan (two subquery arms defeat BitmapOr). Fixed and tested: **1,496x** on a real 4.06M-row space (above production scale), cost now flat in table size. |
| **150** | FIXED in code | A drift probe ate half the box — and was itself caused by a fix (`478fa06`). The precedent for why this tracker exists. |
| **149** | FIXED in code | The slot-sort backfill blocked by a client timeout. |
| **171** | PART 2 RAN 2026-09-25 and PASSES | PART 1 stop building what nothing reads. **PART 2 was already built** (`tests/load/`, opt-in via `VG_RUN_LOAD_TEST=1`) and passes on a 74.2M-quad space: 11,805 queries, 0 timeouts, p50 160.8 ms, p99 828.9 ms, max 1,345 ms, ingest progressing. BUT it runs each job ONCE, so it prices one pass — it is NOT a before/after for the frequency fixes in this tracker. |
| **231** | IN PROGRESS | Steps 1-2 landed 2026-09-24; 3-5 open. Where background work RUNS — the INTERNAL pool class. Bounds the blast radius rather than the cost. |

Fixed, verified live, and listed only so they are not re-diagnosed from stale
notes: **`136`** (maintenance connections set their own 15-minute fence —
confirmed, an ANALYZE ran 341s against the database's 60s default, which cannot
happen otherwise), **`139`** (`rdf_stats` corruption has NOT returned —
`prod_kg_rdf_stats` sums to 22,846,358 with a 3,025,627 max, the post-fix
shape), **`230`** (the ANALYZE pile-up guard), **`194`**/**`187`** (the derived
tables are maintained by every write path — which is what made `238` hot).

## A fix is live where the code runs — so the production numbers are HISTORY

Running locally IS the deploy. There is no separate step between "fixed" and
"in effect", and nothing in this tracker is waiting on one.

The consequence to hold on to is about READING the measurements, not about
shipping: every `pg_stat_statements` figure here was accumulated over 57 days
BEFORE these fixes existed. It is the record that found them and it does not
update itself. `149`, `150`, `236`, `237` and `238` are all in effect wherever
the code runs, and each carries its own local evidence — `238`'s is an EXPLAIN
before/after plus 15 tests and a 1,496x measurement on a real 4.06M-row table.

## Two observations not yet filed

Both were found in the same pass and are recorded here so they are not lost.
Neither has been investigated; neither should be treated as a defect yet.

  * **Entity lock waiting: `SELECT pg_advisory_xact_lock($1)`, 411,639 calls,
    386 ms mean, 44.1 hours.** That is time spent WAITING to enter the entity
    critical section, not doing work. `issues/173` introduced the lock for
    correctness and is the right thing; the question is what holds it so long.
    `238` is one plausible answer — the 249-721 ms scan ran inside that section,
    and that scan is now gone. So the 386 ms figure predates its most likely
    cause and should be RE-MEASURED before being investigated. That needs
    concurrent writers to the same entity, which is `171` PART 2's harness: lock
    waiting cannot be reproduced serially. If it does not move under that
    harness, something else holds the lock.
  * **Vector segment inserts: 653,024 calls at 333 ms on `lead_prod` against
    764,200 at 145 ms on `prod_kg` — 91 hours combined.** Single-row inserts
    into a table carrying a vector index. The 2.3x difference between two spaces
    doing the same thing is the interesting part, and is unexplained. Batching
    is the obvious question; so is whether the index type differs between them.

## Order of work

1. ~~**`236`**~~ **DONE 2026-09-25** — need is now necessary at BOTH levels
   (space pick and per table), verified against live production state: all seven
   `prod_kg` tables would be skipped where all seven were being processed
   every ~25 minutes. 26 tests.
2. ~~**`143` rec 1**~~ **DONE 2026-09-25** — it was HALF built: the gate existed
   and worked (an unwritten space ran the probe 0 times in 16,691 cycles), but
   TWO expensive probes had none — `entity_slot_sort_coverage` (24.4 h) and a
   SECOND, uncopied-gate call site of `frame_slot_drift` (22.4 h), both burning
   time on `testspace`, whose write watermark is zero. 46.8 h gated. What remains
   for actively-written spaces is recs 3/4 and the incremental counts
   (`sync_edge_table.py:435`), not more gating.
3. ~~**`237`**~~ **DONE 2026-09-25** — discovery cached on the write counter;
   535.8 ms → ~1.7 ms per cycle, measured on a real 74M-quad space.
4. ~~**`171` PART 2**~~ **RAN 2026-09-25, PASSES** — and it turned out to be
   already built. On 74.2M quads with reads, writes and the real job set in
   flight: 0 timeouts, p99 828.9 ms, max 1,345 ms. It prices ONE PASS of each
   job, though, so it does not measure what this tracker's fixes changed
   (frequency). The remaining gap is a variant that includes ANALYZE/VACUUM in
   the job set, and a longitudinal `pg_stat_statements` read for frequency.
5. **The advisory-lock wait, measured under that harness** — see above. It needs
   concurrent writers to one entity, so it comes with PART 2 rather than before
   it.

## All of this is reproducible locally, at production scale

Worth stating plainly, because the measurements above were taken against
production and that invites the wrong inference. **The dev and vg environments
hold datasets the same size or larger than production**, so nothing here needs
AWS to reproduce:

| space | rows | size |
|---|---:|---:|
| prod `prod_kg_rdf_quad` | 50,191,500 | 24 GB |
| dev (5432) `sp_lead_synth_100k_rdf_quad` | 50,570,300 | 21 GB |
| vg (5433) `sp_lead_synth_100k_rdf_quad` | **74,165,400** | **32 GB** |
| prod `prod_kg_entity_slot_sort` | 3,027,690 | 1,872 MB |
| vg (5433) `sp_lead_synth_100k_entity_slot_sort` | **4,063,149** | **2,361 MB** |

Some shapes still need data built for them — a specific frame depth, a specific
value distribution, a table at two controlled sizes. That is a local task too,
and the two kinds of fixture answer different questions:

  * **A real space gives magnitude and equivalence.** `238` on the real 4.06M-row
    table read **1,496x**, with both query forms agreeing on the same 343 matched
    rows — an equivalence check that generated uuids cannot make, because they
    match nothing.
  * **A synthetic table isolates a variable.** `238`'s two sizes (500k and 2M)
    are what established that the cost tracked TABLE SIZE rather than rows
    deleted — 4.0x the rows, 4.03x the time. No single real table shows that.

Worth noting the synthetic fixture UNDERSTATED the fix (446x against 1,496x), so
"measured on a synthetic table" is not a conservative claim in either direction.
Use both; say which one a number came from.

What production supplied was not scale but **the accumulated usage record**: 57
days of `pg_stat_statements` showing which statements are called 647,255 times.
That is a ranking, not a behaviour — and the same loops run locally, so even the
ranking can be reproduced by resetting the counters on a local stack and letting
the jobs run.

The differences that remain are hardware (4 vCPU / 3,000 IOPS gp3 against a
workstation) and concurrent real traffic. Neither changes a plan, a scan, or
which variable a cost is proportional to. Both matter for `issues/171` PART 2,
which is about contention rather than shape — and even there the answer is a
local concurrent test, not a production one.

## How to know the group is finished

**The gate is `issues/171` PART 2's concurrent test, locally.** It measures the
thing users actually experience — the SPREAD of a listing query's latency while
writes and background jobs run against the same database. `143` measured the
same SQL at 1,216 ms and 11,187 ms inside one three-minute window, a 9x spread
on an unchanging query; collapsing that is the goal, and a per-statement
improvement that does not collapse it has not finished the job. A serial
benchmark cannot see any of this, which is precisely how the group reached
production.

Each member also needs its own local before/after, which is cheap for all of
them: seed a fixture at a realistic size on the test stack, assert the plan, and
time both forms. `238` is the worked example.

Production `pg_stat_statements` is then CONFIRMATION, not the test — and it has
to be read carefully, because it is cumulative and `issues/143` records reading
a fossil as a live rate misleading this investigation once already. Reset it,
wait a known window, recompute the table at the top. The current ~49% is the
baseline to beat; no target beyond "a small minority" is worth inventing.

## Not established

  * Whether the ~49% subtotal double-counts. The buckets come from distinct
    `pg_stat_statements` rows so they do not overlap, but "drift + integrity
    probes" was assembled by reading query texts, not by an exhaustive
    classification, and is the least certain row.
  * Whether any of this is what users actually feel TODAY. The slowness report
    that prompted the measurement had an upstream cause; this was found with the
    box idle. `143` demonstrated the mechanism (cache eviction and CPU
    saturation by full scans) on a smaller instance — it has not been
    re-demonstrated on the current one.
  * Whether autovacuum should simply be allowed to do this. It is configured
    aggressively (`scale_factor` 0.01/0.005) and currently starved by the app's
    own passes — `last_autovacuum` on `prod_kg_term` is 2026-07-30. `236`
    raises this; nobody has decided it.
