# 320 — only_cause on the default path scans its NOT EXISTS body's CTE once per outer row

## Status: (1) FIXED 2026-10-27 on the default path; verified on the vg test stack rebuilt for the fix (unit, DAWG conformance, integration and API suites, 0 failures). OPEN for (2): not reproduced locally; to be re-read on production (read-only EXPLAIN) once (1) is deployed, since the plan around it changes.

## What

The UW dashboard's `only_cause` query takes **4.67 s** on production on the default path (median of
three read-only EXPLAIN ANALYZE runs). `issues/310`'s fix halved it locally (1,488 -> 695 ms on
`uw_prodshape2`), but on production it did not change (4,638 -> 4,674 ms). Production's time is in
two nodes the 310 fix does not touch:

| exclusive ms | node | estimate | actual | loops |
|---|---|---|---|---|
| 2,513 | CTE Scan `bgp_sg_ex_q0_cte`, the NOT EXISTS body's slot-group CTE, filtered on the correlation | 1 | 0.89 | **6,774** |
| 978 + 436 | Seq Scan of the term table (`t_v2`, 2,159,081 rows) into a Hash | 2.16M | 2.16M | 1 |
| 489 | the Hash Join it feeds, `NOT EXISTS (SubPlan 3)` as its join filter | **8** | **742** | 1 |

1. **The negation body's CTE is scanned per outer row.** A slot-group unit is a MATERIALIZED CTE with no
   index, so the correlated NOT EXISTS reads all of it for each of 6,774 outer rows. 310 noted this
   and deliberately kept that body's order ("Not in a correlated (EXISTS) body").
2. **The term table is hashed whole.** PostgreSQL estimated 8 rows for the join that decodes `?v2`
   (742 arrive), so it hashed all 2.16M term rows instead of probing 742 by primary key.

## Leads

- For (1): decorrelate the NOT EXISTS (one anti-join over the CTE, built once), or do not
  materialize the body's slot group. The qtree planner scores correlated against decorrelated for
  every negation; on `uw_prodshape2` it runs only_cause in about 150 ms against today's 700.
- For (2): the estimate for the join under the anti-join filter; probing the term table by key
  needs no estimate to be cheap.

## Reproduced locally

`uw_prodshape2`, under the executor's own setting (`join_collapse_limit = 1`): 673 ms, the
body's `bgp_sg_ex_q0_cte` scanned 3,475 times (one per outer row), each filtering ~1,625 rows.

## Cause of (1)

The sub-link was `NOT EXISTS (SELECT 1 FROM (SELECT * FROM (<body>) AS ex_f0 WHERE <FILTER>)
AS _ex0 WHERE <correlation>)`. PostgreSQL pulls a sub-link up into an anti- or semi-join only
when its outer references are all in the sub-link's own WHERE; the body's
`FILTER(?f2 != ?f)` reads the outer `?f` from inside the derived table, so it stayed a SubPlan
re-run per outer row. Measured by hand-editing the generated SQL:

| variant | ms |
|---|---|
| as generated | 673 |
| the body's CTE moved to the statement's WITH, FILTER left where it was | 693 |
| the FILTER moved to the sub-link's WHERE, CTE left where it was | 153 (Merge Anti Join) |

The MATERIALIZED CTE is not the obstacle; the FILTER's place is.

## Fix

`emit_expressions` (the EXISTS emitter): a body whose top is a FILTER has its conditions put
in the sub-link's own WHERE beside the correlation (`emit_filter.filter_parts`), the same rows
and conditions. Only when the body shares a variable with the outer row, so the pulled-up join
has an equality to hash or merge on: with the FILTER the only correlation
(`{ ?x :name ?n2 FILTER(?n2 = ?n && ?x != ?e) }`, the n07 shape), pulled up it became a
nested-loop semi-join testing every body row per outer row, 1.4 -> 4.8 s.

Old vs new generated SQL, the executor's settings, rows identical in every case:
only_cause 717 -> 157 ms (0.22x); the other eight UW dashboard queries generate the same SQL;
negation corpus n03 0.94x, n06 0.90x, n09 0.90x, n07 and the rest the same SQL.

`tests/integration/test_exists_body_filter_reads_the_outer_row.py`: NOT EXISTS / EXISTS with a
body FILTER reading the outer row, one reading only the body's, a constant one, and a nested
EXISTS inside the lifted FILTER.

## How it was found

`issues/310`'s production check: `test_scripts_internal/kg_uw_decision_reasons/prod_explain_ab.py`,
a per-node breakdown of the last plan (`/tmp/claude/vg310/after_only_cause_plan.json`).
