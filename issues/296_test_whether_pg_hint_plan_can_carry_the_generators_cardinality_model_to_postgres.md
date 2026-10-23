# 296 — Test whether `pg_hint_plan` can carry the generator's cardinality model to Postgres

## Status: OPEN — experiment, not started (2026-10-22). Not a defect: a question with a decision at the end.

**Related:** `issues/293` (the generator's cardinality model and how its order is
enforced today), `issues/119` §9 ("do not fix the estimate", measured),
`issues/archive/047` (`pg_hint_plan` 1.8.0 verified on the production RDS
instance; `Rows()` could not reach a SubPlan), and the class 293 tracks
(161, 118, 045, 138, 218).

## The question

Since 293's stages 1–3, the generator owns a join cardinality model for flat quad
BGPs and chooses the join order from it. Postgres is kept from overriding that
order by restructuring the SQL, not by telling Postgres anything:

- `SET LOCAL join_collapse_limit = 1` (`sparql_sql_space_impl.py:118`) keeps the
  written order;
- `slot_group_cte` emits a slot group whose graph link would fan out as a
  `MATERIALIZED` CTE.

That leaves three gaps:

1. **Join method.** The order is fixed, but Postgres still picks nested loop or
   hash join from its own wrong estimates.
2. **Nodes above the BGP.** Aggregates, sorts and the outer query inherit
   Postgres' row counts, not the model's.
3. **Coverage.** Edge and `frame_slot` BGPs are neither modelled nor enforced
   (293, stage 4). A `MATERIALIZED` CTE is also an optimisation fence: 293's
   `all_of` regressed (380 → 1,220 ms) because the fence blocked a pushed-down
   VALUES, and it needed a third gate rule to stop it.

`pg_hint_plan` lets one statement carry the model directly: `Rows()` (a join's
row estimate), `Leading()` (join order and tree shape), `NestLoop` / `HashJoin`
/ `MergeJoin` (method), and scan hints. The question: **does a model-derived
hint set give plans at least as good as today's enforcement, on more shapes,
with less SQL restructuring?**

## Why 119 §9 does not already answer it

119 §9 measured that a CORRECTED estimate flips the planner from nested loop to
hash join, 20–93x slower, because the good plan depends on the estimate being
wrong. 293 lists "injecting the cardinality into Postgres" as not on the table,
per 119.

Both are about handing over a better *statistic*: an ANALYZE, a stats target, or
extended statistics. That changes every query and leaves the method to the cost
model. A hint applies to one statement, and it can pin the method and order
together with the estimate. Those are different interventions.

The experiment therefore expects **`Rows()` alone to reproduce 119's flip**, and
puts in a dedicated arm to show it. What is untested is the method and order
hints, with and without `Rows()`. If `Rows()` alone is the only arm that changes
anything, that confirms 119 and this issue closes.

## Arms

| arm | SQL | hints |
|---|---|---|
| A (control) | today's generator: `join_collapse_limit = 1`, `slot_group_cte` | none |
| B | today's generator | `Rows()` from the model on every join it prices |
| C | no `join_collapse_limit`, no `slot_group_cte` | `Leading()` + join method from the model's order |
| D | as C | C + B |

## Shapes

- `uw_prodshape`'s eight dashboard queries from 293 (`decision_page`,
  `by_reason`, `category_page`, `latest_per_deal_by_outcome`,
  `naics_for_category`, `by_outcome`, `all_of`, `only_cause`). `all_of` is the
  fence regression; `only_cause` is the correlated `NOT EXISTS` nothing fixes
  yet, and probably a SubPlan that `Rows()` cannot reach (047).
- 119's fixtures, where the misestimate HELPS: the flip test for arm B.
- Regression cases for 161, 118, 045, 138 and 218.
- At least one edge or `frame_slot` BGP, which today's enforcement does not
  cover. This is where hints could add the most.

## Measurement

- vg test stack, rebuilt for the code under test, at prod scale.
- Primary measures: the busiest node's loop count, and full result multisets,
  which must be identical across all arms.
- Wall time: 5 runs per cell, min/med/max, on a quiet database, with swap
  checked first.
- **Check that every hint was applied.** A malformed or unmatched hint is
  silently ignored, so an arm can measure today's plan and look like "no
  change". Run with `pg_hint_plan.debug_print = verbose` and confirm in
  `EXPLAIN` that the hinted joins show the hinted row counts and methods. Any
  unused hint invalidates that cell.

## Setup

- `docker/test-pg/Dockerfile` does not install `pg_hint_plan`. Add the PGDG
  package `postgresql-18-pg-hint-plan` at **1.8.0**, the version 047 found on
  production. For the experiment, a superuser session `LOAD 'pg_hint_plan'` is
  enough. Adopting it needs `shared_preload_libraries`, as RDS requires. If the
  image changes, confirm the perf suite's plan shapes are unchanged with the
  library loaded and no hints.
- No generator change is needed to run the experiment. A script can take the
  generated SQL plus the model's `plan_decisions` and prepend the hint comment.
  It must emit unique table aliases per statement, and it must check whether a
  hint can address relations inside a CTE or subquery block on each shape that
  has one.

## If it wins: what adoption costs

- A parameter-group change and a reboot on **every install**. The code must
  detect whether the library is loaded and fall back to today's enforcement
  when it isn't. The fallback therefore stays permanently and keeps being
  tested; it is not replaced.
- `Rows()` cannot reach SubPlans (047), so `EXISTS` / `NOT EXISTS` shapes keep
  the current mechanisms.
- The generator would emit hints for every query it models, and an unused hint
  must fail a test rather than pass quietly.

## Decision

Adopt (C or D) only if, on every shape A already handles, it matches A's loop
counts or beats them, with identical result multisets. It must also improve at
least one shape A does not cover (edge / `frame_slot`, or `all_of` without the
third gate rule). Any regression must be explained before it counts as a win.

Otherwise close with the numbers, as a second, per-statement confirmation of
119 §9, and record which arm failed and how.

## Dependency on model coverage (recorded 2026-10-22)

This issue is stage 6 work (`issues/293`: the model replaces `reorder_joins`'
single-pattern root, the semi-join anchor and the `selective-driven` gate,
retiring the class's route-arounds). Its reach depends on the model covering
**edge and `frame_slot` tables**, which it does not yet: KGQuery's paths, where
the semi-join and `selective-driven` decisions actually run, go through those
tables, so without that coverage there are no model prices to hint. Order:
(1) model coverage of edge/`frame_slot` tables; (2) 297's census and pairs,
then 296's arms, each where coverage exists, each judged by the statistics
policy (a decision changes, measured). The UW dashboard's two remaining slow
queries are NOT addressed by this issue: `only_cause` is a correlated
`NOT EXISTS` SubPlan and `category_page` an unhashable `IS NULL OR` join
condition, both structural, pursued separately under 293. Production's quiet
slow log is not evidence against stage 6: it is quiet partly because the
route-arounds fixed each shape after it reached production.

## Results, arm C first (2026-10-22): per-BGP `Leading()` does not work as a scoped enforcement

Run because 293's gate experiment showed the statement-wide
`join_collapse_limit = 1` is the problem: enforcing the model's order at gate 1
made `category_page` 3.8 s -> 8.7 s and `decision_page` 0.3 s -> 2.6 s
(1,033,972 loops) on `uw_prodshape2`, because the setting freezes EVERY join
in the statement, not just the modelled BGP. Arm C asks whether
`pg_hint_plan` can scope the order to the BGP instead.

**Setup.** `postgresql-18-pg-hint-plan` 1.8.0-3.pgdg13+1 installed into the
running test container only (`apt-get`, gone on container recreation; the
Dockerfile and the pinned perf baselines are untouched). `LOAD 'pg_hint_plan'`
per superuser session, `debug_print = on`, `message_level = notice`, and the
report read back per cell. Script:
`test_scripts_internal/kg_uw_decision_reasons/hint_ab.py`. Arms: A (today:
gate 10, jcl = 1 when the model fires), A1 (gate 1, statement-wide jcl = 1), C
(gate 1 SQL, no jcl, one `Leading()` per BGP in its written order).
`uw_prodshape2`, 5 runs per cell, swap high so medians only; identical result
multisets in every arm.

| query | A | A1 | C | hint report for C |
|---|---|---|---|---|
| all_of | 191 ms, 6,950 loops | 123 ms, 3,477 | **26,849 ms**, 10,425 | 1 `Leading`, used |
| category_page | 5,200 ms | 11,760 ms, 74,313 | 5,638 ms, 74,313 | **invalid**: 7 `Leading`, duplicates dropped, 1 used |
| decision_page | 318 ms, 3,991 | 2,456 ms, 1,033,972 | 14,334 ms, 1,033,972 | **invalid**: same |

Two findings, both structural:

1. **One `Leading()` per statement.** `pg_hint_plan` reports the second and
   later `Leading()` hints as duplicates and applies only the last. A
   statement with several BGPs (every dashboard query but `all_of`) cannot
   carry an order per BGP. There is no way to address a query block other than
   naming its relations, and the hint set is statement-wide.
2. **A `Leading()` over a subset of a join problem breaks the rest of it.**
   `all_of` had one BGP and its hint was used. The BGP ran in the model's
   order in ~0.6 s, and every join planned around the forced group showed
   `Disabled: true`. The 26 s was a `Gather` over the two-row VALUES list
   rescanned 3,475 times (a parallel worker start per outer row, ~6.4 ms each).
   Adding `Set(max_parallel_workers_per_gather 0)` made it worse
   (140-193 s), and raising `join_collapse_limit`/`from_collapse_limit` to 30
   did not remove the disabled paths (39.7 s). Postgres plans the remainder
   from the same wrong estimates and can no longer pick the paths it relied on.

So arm C as designed, a per-BGP order with everything else left to Postgres,
is not available through `pg_hint_plan`. The remaining form is a hint for the
FULL join tree of each statement: every relation, term joins, VALUES and CTE
scans included, plus join methods. That means the generator plans the whole
statement, which is the same scope as `join_collapse_limit = 1` (A1) with a
better written order. Arms B and D were not run. B is expected to reproduce
119 §9's flip, and D depends on C. This closes the experiment's main
question unless full-tree generation is taken on.

The container still has the package installed; recreating it removes it.
