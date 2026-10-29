# 330 — A slot-group CTE is rescanned once per outer row: quadratic in the number of decisions

## Status: OPEN, filed 2026-10-29 from the post-v0.0.97 production re-measure (read-only). Live: the dashboard's two slowest queries, ~1 s today and growing with the square of the decision count.

**Related:** `issues/293` (the slot-group CTE this rescans; the misestimate class),
`issues/320` (the same "CTE scanned per outer row" shape inside a NOT EXISTS,
fixed by moving the FILTER so PostgreSQL could hash-anti-join).

## Measured (production underwriting space, v0.0.97, 2026-10-29)

`test_scripts_internal/kg_uw_decision_reasons/prod_explain_ab.py`, read-only
session, the current generator (production's v0.0.97 SQL), 5 EXPLAIN ANALYZE
runs each, every block a buffer hit:

| query | exec ms (med) | rows processed | busiest node |
|---|---:|---:|---|
| latest_per_deal_by_outcome | 1,157 | 3,149,314 | CTE Scan `bgp_sg_q7_cte`: **1,585 loops x 1,920 rows** |
| decision_page | 1,019 | 3,917,220 | CTE Scan `sg_q4_cte`: **1,920 loops x 1,920 rows** |

The join above each is a **Nested Loop with the equality as a Join Filter**
(`q0.subject_uuid = sg_q4_cte.q4__object_uuid`; `sub.v0__uuid =
bgp_sg_q7_cte.v6__uuid`, a LEFT join for the OPTIONAL field). A MATERIALIZED
CTE has no index, so the inner side is read whole for every outer row.
PostgreSQL chose it from its estimates: outer side 42 / 1 rows (actual 1,920 /
1,585), CTE 61 / 1 rows (actual 1,920). With the right sizes it would hash.

Work is outer x CTE = decisions^2: 1,920 decisions today (1,159 on Oct 21).
Doubling them quadruples these two queries.

## Direction (not decided)

The generator knows the sizes PostgreSQL gets wrong: each slot group's pin is
counted (`issues/293` stages 1-2). Options, to measure on `uw_prodshape2`
scaled to production's decision count first:

1. Make the join hashable whatever the estimate: e.g. join the CTE in a form
   whose equality PostgreSQL hashes (the `issues/320` lesson: where a condition
   sits decides the join method).
2. A local `enable_nestloop = off` only around statements whose slot groups are
   predicted large (as `enable_sort` is set from `needs_ordered_scan`): blunt,
   but scoped and cheap to test.
3. Feed the CTE's size: not directly possible in PostgreSQL; a `LIMIT n`-style
   hint is not an estimate.

Acceptance: both queries' rows processed linear in decisions (no CTE loops >
1), identical result multisets, the other seven dashboard queries unchanged,
the perf suite's plan shapes unchanged.
