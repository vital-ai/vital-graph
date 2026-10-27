# 310 — category_page on the default path orders the reason CTE from its field units

## Status: RESOLVED 2026-10-27. Verified locally (pinned and unpinned, suites green) and on production (read-only EXPLAIN ANALYZE, below). only_cause, which this fix does not reach on production, is `issues/320`.

## Fix as built

- **`bgp_cardinality.unit_model`:** each slot-group unit becomes ONE column leaf.
  - Its rows are its members joined greedily from the pin.
  - Its columns are the CTE's `alias__col` columns, with the BGP's variable positions remapped
    onto them, one column per variable.
  - It returns None when a member is unpriced.
- **`emit_bgp._remainder_model_order`:** after regrouping, the remainder is priced with
  `choose_order`, and the model's order is written when the same model prices it cheaper than
  `reorder_joins`'s order.
  - This is not a new pin, so `ENFORCE_MIN_GAIN`, which guards forcing, does not apply. The
    written order is the model's best guess instead of the heuristic's.
  - It falls back to `reorder_joins` when anything is unpriced, or for a text, range or FTS
    anchor.
  - **Not in a correlated (EXISTS) body.** A unit is a MATERIALIZED CTE with no index, so probed
    per outer row it is SCANNED per row. The column-leaf model priced only_cause's body probe at
    0.008 rows; it reads 6,950 per probe, about 24M over the outer rows. That body keeps its
    measured order.
- **`pinned_heuristic_order`** (a plan_decisions note, `EmitContext.heuristic_orders`, shared
  with EXISTS bodies): names every BGP the statement-wide pin keeps without the model having
  ordered it.
  - On the UW dashboards it lists only_cause's NOT EXISTS body (deliberate: the pin is kept for
    exactly that order) and **by_reason_tied's `q0` BGP**. by_reason_tied runs at about 57 ms
    either way, so it is the next candidate, not a defect today.
  - So the invariant proposed below does not hold, and is recorded, not asserted.

**Measured** (`uw_prodshape2`, today's SQL before vs after, 5 interleaved runs, no swapping;
results identical in every query):

| query | as the executor runs it | pin forced (as production) |
|---|---|---|
| category_page | 521 → **329** ms | 1,209 → **334** ms |
| only_cause | 1,488 → **695** ms | 1,445 → **679** ms |
| naics_for_category | 202 → 211 ms (**5-9% slower**, repeated 3x) | 203 → **69** ms |
| by_reason | 66 → 49 ms | 68 → 54 ms |
| the other 7 dashboard queries | same SQL | same SQL |

naics_for_category is the trade. Unpinned, PostgreSQL re-plans most of its 9-relation
remainder itself, and the model's written order is slightly worse for the part past
`join_collapse_limit` that it still controls. Pinned, it is 3x faster.

Tests:
- `tests/unit/sparql_sql/test_slot_group_remainder_order.py` (3);
- `test_slot_group_cte.py`'s stub updated to the new `_slot_group_ctes` return value;
- unit, DAWG conformance and the full integration suite green on the vg test stack.

**Related:** `issues/293` (the class, and the dashboard this query belongs to),
the qtree planner (`qplan.py`; its plan for this query is the target order below),
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

## Reproduced locally (2026-10-25, `uw_prodshape2` on the planner stack, switch off)

Locally the statement-wide pin does NOT fire: the model's order gate declines ("predicted gain
within the model's error band"). Without it PostgreSQL reorders the reason CTE itself. Forcing
the pin that production's statistics fire (`SET LOCAL join_collapse_limit = 1` on today's SQL)
reproduces production:

| | total | reason CTE `bgp_sg_q11_cte` | largest join |
|---|---|---|---|
| unpinned (what runs locally) | 703 ms | 197 ms (3,475 rows) | small: hash and merge joins over the slot pins |
| pin forced (as production) | **2,132 ms** | **1,850 ms** | merge joins of **1.8M rows** (graph-link members) |

Production's 2.15 s matches the pinned run. **Any test of the fix must force the pin** (or
reproduce the statistics that fire it), or it cannot see the defect locally.

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

**The pin is the trigger.** The heuristic order is only harmful because the pin, which is
statement-wide, freezes an order the model never chose. Unpinned, PostgreSQL repairs it (703 ms
locally).

**The class is wider than this BGP.** Whenever the model fires the pin for one BGP, every other
BGP in the statement has its heuristic (`reorder_joins`) order frozen with it.
`join_collapse_limit` has no per-BGP scope, so the practical repair is that every order a
pinned statement can contain is model-chosen. This issue's fix does that for the slot-group
remainder; other heuristic orders under the pin are latent instances of the same defect.

## Proposed fix (default path, so RDS production)

Order the remainder after regrouping with the cardinality model, units
included:

- each group unit as a COLUMN leaf (`bgp_cardinality.Leaf.cols`, as the edge
  and frame_slot leaves): its rows are its pinned count, its columns are the
  CTE's renamed `qN__col` columns, with the BGP's variable positions remapped
  onto them;
- choose the order with `choose_order` over units and leaves; fall back to
  `reorder_joins` whenever anything is unpriced, as everywhere else.
- **let the model pick the driver; do not fix it at the reason-kind slot.** The "good order"
  above starts from the 11,527 kind-slot pins. The qtree planner prices the same leaves and
  starts from the reason-CODE slot pinned by the nine VALUES codes:
  `(((((?f_c →f ?f_k) →d ?d) ⋈ ?gv) ⋈ ?o) ⋈ ?ca)`, i.e. code slot, its frame to the kind slot,
  then `?d`, then the field units hashed on `?d`. That runs in **83-100 ms** locally, against
  703 ms unpinned and 2,132 ms pinned. The model should see both candidates, with the VALUES pin
  priced from `rdf_stats` pairs as the planner does (`qplan._build_region`). That order is the
  target for the default path.

Alongside the fix:

- **An invariant over the dashboard set:** in a statement with `fixed_join_order`, every
  multi-relation BGP's order is model-chosen. Checked by a test that generates each dashboard
  query and inspects the decisions.
- **A `plan_decisions` note** naming any BGP frozen by the pin with a heuristic order, so the
  next instance shows in the logs rather than in a production bench.

`group_plan_cost` in `group_cost_probe.py` is the pricing prototype. It was
not shipped earlier because on the local fixtures it chose the same plan as
the precedence rule; production's data is where it changes a decision.

Validation as for the rest of 293:
- the dashboard set's result multisets, and rows processed / buffers, locally;
- **the pinned local run, before and after:** `uw_prodshape2` with `join_collapse_limit = 1`
  forced, compared contract-style (identical result multisets, 5 interleaved runs, quiet
  machine; check swap first: it was active on 2026-10-25);
- the performance suite (slot groups fire on none of its queries, so its plans should not
  change);
- last, read-only EXPLAIN ANALYZE on production for `category_page` and the other eight
  dashboard queries, before and after.

## Relation to the qtree planner

- **What the planner does with this query.** Nearly all of its gain on `category_page` is the
  join order above (a code-slot driver). Joining the OPTIONALs after the cut (`late_optional`,
  off by default) added only 101 → 83 ms on top. Its decorrelated NOT EXISTS (for `only_cause`)
  is part of its base planning, not a feature.
- **Where it runs.** Only with the `vg_planner` extension (`planner_ext.active()` needs
  `VG_PLANNER_EXTENSION=on|require` and a detected extension). RDS cannot load it, and
  production runs BOTH paths, so the planner cannot stand in for this fix. The default path
  needs it regardless.
- **The coupling is small.**
  - `planner_ext.retired()` is true only with the switch ACTIVE and the route-around retired.
    Nothing is retired today (`RETIRED` all False), and it has no effect with the switch off.
  - With the switch on, the qtree planner replaces the SQL when it plans the query. When it
    declines, the default SQL runs, so this fix helps both paths.
  - Coordination is a heads-up that `emit_bgp.py` and `bgp_cardinality.py` change, not a
    shared owner.

## Not covered here

`only_cause` (3.77 s on production): its `FILTER NOT EXISTS` still runs as a
per-row probe, one per reason row, now planned with statistics (`issues/293`,
60ba280e). A decorrelated form (the body once, as a CTE keyed on the
correlated variables, hash anti-joined) is the separate next step on the
default path. An earlier attempt to lift its correlated filter lost to a
misestimated outer side (293, "Attempted ... reverted: lift").

## Production check, 2026-10-27 (read-only EXPLAIN ANALYZE)

The generator before the fix (`2c7d297e^`) and after it (the default path at `44981a7e`), run locally
against the production UW space in a read-only session (`default_transaction_read_only`), three runs
each; same row counts on both sides; every block a buffer hit.
`test_scripts_internal/kg_uw_decision_reasons/prod_explain_ab.py`.

| query | before | after |
|---|---|---|
| category_page (the dashboard's, test runs excluded) | 4,877 ms | **1,148 ms** (4.2x) |
| naics_for_category | 1,094 ms | **280 ms** (3.9x) |
| only_cause | 4,638 ms | 4,674 ms (no change: `issues/320`) |
| all_of, by_outcome, by_reason, decision_page, latest_per_deal_by_outcome, total | | within 3% |

only_cause halved locally (1,488 -> 695 ms) but not on production: there its time is the NOT EXISTS
body and a term-table hash this fix leaves alone (`issues/320`).
