# 320 — only_cause on the default path scans its NOT EXISTS body's CTE once per outer row

## Status: OPEN 2026-10-27. Measured on production, read-only; not yet reproduced or fixed locally.

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

## How it was found

`issues/310`'s production check: `test_scripts_internal/kg_uw_decision_reasons/prod_explain_ab.py`,
a per-node breakdown of the last plan (`/tmp/claude/vg310/after_only_cause_plan.json`).
