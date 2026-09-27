# 236 — ANALYZE and VACUUM are scheduled by staleness alone, so tables with nothing to do are maintained forever

## Status: FIXED 2026-09-25 in `maintenance_job.py` — live wherever the code
## runs. Measured
## on production 2026-09-24/25 with the box IDLE. A NARROW defect inside
## `issues/143`'s territory, not a restatement of it.

## The fix, and what it verified

**Two gates, because the pick is per SPACE and the work is per TABLE.** Fixing
only the first would have left the production case untouched: a space with real
churn is correctly picked, and then still processed all seven of its tables.

1. **`_pick_worst_for_analyze` / `_pick_worst_for_vacuum`** — the conjunction is
   now `mods < THRESHOLD and last is not None → skip`. Need is necessary;
   staleness keeps its real job, ordering candidates inside the score, and a
   never-touched space stays eligible via `last is None`.
2. **`_tables_needing`** (new) — once a space is picked, its tables are filtered
   to those individually over threshold or never done. This is where the 24 GB
   table is saved: `{space}_datatype` is 40 rows on production, and 10,000
   modifications in it used to drag `_rdf_quad` (24 GB), `_term` (3.7 GB),
   `_edge` (1.4 GB) and `_frame_slot` (1.3 GB) through a full pass. One catalog
   read of seven rows per cycle against passes costing 8-25 s each.

`ANALYZE_STALENESS_MINUTES` and `VACUUM_STALENESS_MINUTES` are **deleted**, not
left unused — they were the half of the conjunction that created work, and
leaving them defined invites the reading back.

**Verified against live production state.** Running the new gate's predicate as a
read-only query over `prod_kg`'s seven tables, at a moment when production was
analysing and vacuuming all of them every ~25 minutes:

| table | mods | dead | would analyze | would vacuum |
|---|---:|---:|---|---|
| `prod_kg_rdf_quad` | 4,286 | 720 | **no** | **no** |
| `prod_kg_term` | 474 | 0 | **no** | **no** |
| `prod_kg_edge` | 162 | 5,286 | **no** | **no** |
| `prod_kg_frame_slot` | 132 | 6,625 | **no** | **no** |
| `_datatype`, `_rdf_pred_stats`, `_rdf_stats` | 0 | 0 | **no** | **no** |

**All seven would be skipped.** Every value is below its threshold; the only
reason any of them was being processed is elapsed time. The expression was also
run against the vg stack, where `analyze_count = 0` and the timestamps are
genuinely NULL — there it correctly reports every table as needing its first
pass, which is the `last is None` case working rather than failing safe.

**Tests:** `tests/unit/test_maintenance_runs_only_where_there_is_work.py`, 26
cases. Both gates separately; staleness still ordering; never-touched still
eligible; VACUUM gating on dead tuples rather than mods; a table missing from
`pg_stat_user_tables` treated as NEEDING work (absence of information is not
evidence of freshness); a failing probe falling back to every table so the gate
cannot stop maintenance by breaking; and `_run_analyze`/`_run_vacuum` issuing no
statement at all when nothing needs doing. The old conjunction is kept as an
oracle and asserted to schedule exactly the three production cases — plus one
case where both rules agree, which is why this shipped unnoticed.

**Tracked by:** `issues/239` (background work is ~half the production
database — this is one member of that group)

**Related:** `issues/143` (the parent finding — maintenance as 38% of wall-clock,
recommendations 1/3/4 still open), `planning/planning_performance/maintenance_incremental_only_plan.md`
(the binding principle: no recurring full walk), `issues/230` (the ANALYZE
pile-up — fixed; this is the frequency behind it), `issues/136` (the 60s
`statement_timeout` that used to kill VACUUM — fixed, maintenance connections
now get 15 min)

## Where this sits

`issues/143` establishes that maintenance dominates production database time and
that the answer is to make it INCREMENTAL rather than less frequent. This issue
is one specific mechanism it does not name: the ANALYZE/VACUUM scheduler's skip
condition, which lets **elapsed time alone** schedule work on a table that has
not changed by one row. 143's open recommendation 1 asks for the drift and
self-link CHECKS to be gated on change; the same gate is missing one layer down,
on the ANALYZE and VACUUM the job itself issues.

## The defect

`process/maintenance_job.py:1018` and `:1052`:

```python
if mods < ANALYZE_MOD_THRESHOLD and minutes_since < ANALYZE_STALENESS_MINUTES:
    continue                      # 10,000 mods / 10 minutes
if dead < VACUUM_DEAD_THRESHOLD  and minutes_since < VACUUM_STALENESS_MINUTES:
    continue                      # 10,000 dead / 30 minutes
```

A table is skipped only when it has **both** nothing to do **and** was done
recently. Once the staleness window passes, a table with zero modifications and
zero dead tuples becomes eligible — and is then ranked by the very staleness
that made it eligible:

```python
if mods == 0:
    score = minutes_since
```

Nothing downstream re-checks whether there is work. The module docstring states
the intent — *"Freshness thresholds (skip if ALL true)"* — and the code
implements exactly that. The bug is that "fresh" was defined as a conjunction,
so **time is sufficient to schedule work that has no reason to run.**

## The evidence that it is need-free, not merely eager

Three spaces are completely idle — no pending modifications, no dead tuples —
and are maintained around the clock anyway:

| space | ANALYZEs | VACUUMs | mods pending | dead tuples |
|---|---|---|---|---|
| lead_prod | 15,030 | 9,071 | 7,961 | 2,539 |
| prod_kg | 14,740 | 15,442 | 4,952 | 724 |
| **testspace** | **11,286** | **4,508** | **0** | **0** |
| **sp_kg_types** | **11,274** | **4,506** | **0** | **0** |
| **lead_data** | **9,555** | **4,682** | **0** | **0** |
| wordnet_frames | 1,326 | 946 | 0 | 0 |
| prod_kg_archive | 865 | 34 | 0 | 21 |

`testspace`, `sp_kg_types` and `lead_data` are FIXTURE spaces. Between them they
have absorbed **32,115 ANALYZEs and 13,696 VACUUMs** — 6.3 hours of database
time over 10,021 statements — for tables that have not changed by one row.

**`prod_kg_term` is insert-only and was still vacuumed 9,543 times.**
Lifetime counters: `n_tup_upd = 0`, `n_tup_del = 6`,
`n_tup_ins = 13,842,592`, `n_dead_tup = 0`. There has never been meaningful
garbage in it to collect. Cost: 9,486 calls at a 10.2s mean — **26.9 hours.**

**The big table is on the staleness clause too, not the mods clause.** Measured
over a 12.7-hour window (2026-09-25 01:29 → 14:12 UTC) by differencing
`pg_stat_user_tables`:

    prod_kg_rdf_quad   +30 ANALYZEs, +32 VACUUMs   (one per ~25 minutes)
    prod_kg_term       +30 ANALYZEs, +32 VACUUMs

with `n_mod_since_analyze = 4,270` at the time of reading — **below** the 10,000
threshold that is supposed to be the reason to run. The table is 24 GB and 50M
rows, and an ANALYZE pass costs 24.8s on average, 341s at worst: **48.3 hours**
over the 57-day `pg_stat_statements` window.

## It also displaces autovacuum

`last_autovacuum` on `prod_kg_term` is **2026-07-30**, two months stale,
because the manual pass keeps resetting the need before autovacuum's thresholds
trip. Those thresholds are already tuned aggressively for this workload —
`autovacuum_vacuum_scale_factor = 0.01`, `autovacuum_analyze_scale_factor =
0.005`, both from the parameter group.

So PostgreSQL's own need-driven scheduler is being out-competed by a job that
decides worse.

## The fix as originally specified — IMPLEMENTED

Kept because the reasoning is the argument for the change, not just its shape.
**Make need necessary, not merely sufficient.** Staleness should order the queue,
not populate it:

```python
needs_analyze = mods >= ANALYZE_MOD_THRESHOLD or last_analyze is None
if not needs_analyze:
    continue
```

and the same for VACUUM on `dead`. A never-analyzed table stays eligible — which
is what the `last is None → inf` branch was protecting, and it survives the
change. Staleness then remains what it already is inside the score: the tiebreak
among tables that genuinely have work.

This is `issues/143` recommendation 1 applied one layer down, and it is
consistent with the incremental-only principle: the cost stops being
proportional to elapsed time and becomes proportional to writes.

Two things to decide alongside, neither of which the code currently states:

  * **Whether the app should schedule VACUUM at all.** Autovacuum is configured,
    need-driven, and currently starved by this job. ANALYZE has a clearer case —
    derived tables and `rdf_stats` benefit from a known-fresh moment after a
    bulk load — but an insert-only table vacuumed 9,543 times for six lifetime
    deletes is the argument against the VACUUM half.
  * **Whether idle spaces should be skipped wholesale.**
    `VG_MAINTENANCE_EXCLUDE_SPACES` exists but is a manual opt-out; nothing
    notices that a space has had zero writes for weeks. Fixing the condition
    above makes the exclusion list unnecessary for this purpose, which is the
    better outcome.

## Not established

  * How much of the measured cost survives a need-only rule. The idle spaces'
    6.3 hours go entirely, and at the moment of measurement `prod_kg`'s seven
    tables would ALL have been skipped — but that is one sample, not a rate. How
    often those tables genuinely cross 10,000 mods was not sampled over time.
  * Whether 10,000 is the right threshold for a 50M-row table. It is 0.02% of
    `prod_kg_rdf_quad` — far tighter than autovacuum's own 0.5% analyze scale
    factor — so even need-driven runs may be more frequent than they need to be.
  * Whether `auto_analyze.maybe_analyze` is a second path to the same waste. It
    ANALYZEs a SEVEN-table set, including `{space}_rdf_quad` and `{space}_term`,
    whenever ANY table in the space crosses a 50,000-row counter, and it carries
    no per-table need check at all. `ANALYZE_MIN_INTERVAL` (900s) exists in that
    module but is consulted only by `kg_backend_utils._maybe_analyze_aux_tables`,
    never by `maybe_analyze`. Not measured separately.
  * Whether the 341s max ANALYZE is a plan-time outlier or a wait behind another
    maintenance statement. `max_exec_time` alone cannot distinguish them.
