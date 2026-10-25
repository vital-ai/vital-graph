# 310 — category_page on the default path orders the reason CTE from its field units

## Status: OPEN — measured on production 2026-10-25; fix proposed, not started. Owner to be agreed with the qtree planner work (see "Relation to the qtree planner").

**Related:** `issues/293` (the class, and the dashboard this query belongs to),
the qtree planner (`planner_ext.py` `late_optional`, `qplan.py`),
`test_scripts_internal/kg_uw_decision_reasons/group_cost_probe.py` (the
unit-aware pricing prototype).

## Measured on production (v0.0.96-prod, the production UW space, 1,406 decisions)

The UW dashboard's `category_page` query (`SELECT DISTINCT` of ten fields for
decisions with any of nine Industry codes, `ORDER BY DESC(?computedAt) LIMIT
25`, test runs excluded) took **2.15 s** median in the production bench.
`decision_page`, the same fields without the code filter, took **0.87 s**.
`category_page` is the slowest dashboard query after `only_cause` (3.77 s).

Per-node breakdown on production (the current generator run locally against
production PostgreSQL in a read-only session; EXPLAIN ANALYZE as JSON, 3
runs, ~3.0 s each under EXPLAIN): **2.4 s** of it is one node, the
materialized reason BGP `bgp_sg_q11_cte` (5,989 rows). Inside it:

```
#93 Hash Join  sg_q14_cte.q14__object_uuid = sg_q11_cte.q11__object_uuid   rows 1,533,315
  #94 Hash Join  sg_q17_cte.q17__object_uuid = sg_q14_cte.q14__object_uuid rows 1,533,315
    #97 Nested Loop                                                         rows 1,533,315
      #98 CTE Scan sg_q14_cte (a decision field slot group)                rows 1,407
      #99 Index Only Scan q4  hasKGGraphURI, probed BY OBJECT ?d            1,090 rows x 1,407 loops
#92 Hash Join  q4.subject_uuid = q5.subject_uuid  (q5: the reason-kind slot type)  rows 11,527
```

The BGP holds the decision's three required field slot groups (materialized
as `sg_*` CTEs, 1,407 rows each), the reason-kind slot (`q4` graph link, `q5`
slot type, `q6` frame link, `q7` value) and the reason-code slot (`q8`-`q10`).
The written order joins the field units first, then probes `?f_k
hasKGGraphURI ?d` by `?d`: about 1,090 graph members per decision, 1.53M rows,
which the kind slot type then cuts to 11,527. **About 250x the rows the
answer needs.** The good order starts from the 11,527 reason-kind slot pins
(`q5`), joins the frame and code slots, then hash-joins the field units on
`?d` once: on the order of 10^5 rows.

## Cause

`emit_bgp._emit_flat_inner`: after the slot-group rewrite, the remainder (the
group units plus the leaves not in a group) is ordered by `reorder_joins`,
not by the cardinality model. The kind-slot group is not itself a slot-group
CTE: the gate declines it, "a smaller driver reaches the slot without the
graph link", expecting the code side to drive it through the frame. Nothing
makes the join take that route. `reorder_joins` roots on the smallest leaf
(a field unit, 1,407) and then reaches `q4` through `?d`. The statement-wide
`join_collapse_limit = 1` pin, set because the model's order fired elsewhere
in the statement, then freezes exactly that written order.

## Proposed fix (default path, so RDS production)

Order the remainder after regrouping with the cardinality model, units
included:

- each group unit as a COLUMN leaf (`bgp_cardinality.Leaf.cols`, as the edge
  and frame_slot leaves): its rows are its pinned count, its columns are the
  CTE's renamed `qN__col` columns, with the BGP's variable positions remapped
  onto them;
- choose the order with `choose_order` over units and leaves; fall back to
  `reorder_joins` whenever anything is unpriced, as everywhere else.

`group_plan_cost` in `group_cost_probe.py` is the pricing prototype. It was
not shipped earlier because on the local fixtures it chose the same plan as
the precedence rule; production's data is where it changes a decision.

Validation as for the rest of 293: the dashboard set's result multisets and
rows processed / buffers locally, the performance suite (slot groups fire on
none of its queries, so its plans should not change), and read-only EXPLAIN
ANALYZE on production for `category_page` and the other eight dashboard
queries before and after.

## Relation to the qtree planner

The qtree planner (`VG_PLANNER_FEATURES=qtree`, with `late_optional`: "on an
ORDER BY ... LIMIT page, cut the required part to the page FIRST and left-join
the OPTIONALs onto those rows only") targets this query shape directly, and its
NOT EXISTS planning has a decorrelated form, which `only_cause` needs. It runs
only where the `vg_planner` extension is installed (`planner_ext.active()`
needs `VG_PLANNER_EXTENSION=on|require` and a detected extension). RDS cannot
load custom extensions, so production on RDS keeps the default path. The fix
above is for that path. It touches `emit_bgp.py` and `bgp_cardinality.py`,
which the planner work reads and whose route-arounds it retires by name
(`planner_ext.retired("slot_group_cte")`), so it needs agreeing with that work
before it starts.

## Not covered here

`only_cause` (3.77 s on production): its `FILTER NOT EXISTS` still runs as a
per-row probe, one per reason row, now planned with statistics (`issues/293`,
60ba280e). A decorrelated form (the body once, as a CTE keyed on the
correlated variables, hash anti-joined) is the separate next step on the
default path. An earlier attempt to lift its correlated filter lost to a
misestimated outer side (293, "Attempted ... reverted: lift").
