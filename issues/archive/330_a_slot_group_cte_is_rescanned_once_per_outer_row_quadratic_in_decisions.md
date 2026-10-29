# 330 — A slot-group CTE is rescanned once per outer row: quadratic in the number of decisions

## Status: RESOLVED 2026-10-29 (not yet released). Filed from the post-v0.0.97 production re-measure (read-only); fixed and verified locally on `uw_prodshape2`. After release, re-measure the two production queries (`prod_explain_ab.py`) to confirm.

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

## Options considered (original)

1. Make the join hashable whatever the estimate (the `issues/320` lesson: where
   a condition sits decides the join method).
2. A local `enable_nestloop = off`.
3. Feed the CTE's size: not possible in plain PostgreSQL.

Acceptance: both queries' rows processed linear in decisions (no CTE loops >
1), identical result multisets, the other seven dashboard queries unchanged,
the perf suite's plan shapes unchanged.

## Reproduced locally (`uw_prodshape2`, ~966 decisions, vg test stack)

`test_scripts_internal/kg_uw_decision_reasons/cte_rescan_probe.py` (generate,
EXPLAIN ANALYZE, list every CTE Scan with loops > 1). Locally the defect is in
FOUR of the nine dashboard queries, in two shapes:

| query | rescan | shape |
|---|---|---|
| by_outcome | `bgp_sg_q1_cte` 1,159 x 965 | OPTIONAL: Nested Loop **Left** to a `bgp_sg_*` CTE |
| latest_per_deal_by_outcome | `bgp_sg_q7_cte` 860 x 965 | OPTIONAL |
| category_page | six `bgp_sg_*` (1,159 x 965, 5 x 77 x 483-965) + `sg_q32_cte` 773 x 966 | both |
| decision_page | `sg_q25_cte` 773 x 966 | **inner**: a type-check leaf joined to the CTE |

Root cause, both shapes: PostgreSQL sizes a slot-group CTE from its slot-type
pin and the entity side from its type pair, both mid-frequency `(predicate,
object)` pairs it estimates at ~1 row (`issues/293`). Two 1-row sides make a
nested loop cheapest; a CTE has no index, so each outer row reads all of it.

**`enable_nestloop = off` is ruled out**, measured on all nine: 5-50x slower
everywhere (decision_page 361 ms -> 19.3 s, category_page 1.2 s -> 23 s),
because it also takes away the primary-key probes inside the slot groups and
the type-triple joins that `issues/293` depends on.

## Fix (2026-10-29)

Two generator changes, one per shape. Neither touches statistics or a GUC.

**Inner shape: fold the existence check into the CTE**
(`slot_group_cte._fold_existence_checks`). A leaf that adds no variable and
whose only variables are one group's (`?v hasKGEntityType <Decision>` on a
slot's value) is made a member of that group. Inside the CTE it is one
primary-key lookup per CTE row, driven from the pin. Excluded: a test of the
group's `?d` (the entity anchor, which the rest of the BGP joins through:
folded, the pinned by_reason went 124 ms -> 33 s and only_cause 0.35 s ->
50 s, measured and reverted), a correlated variable, a GRAPH `?g` context.

**Join shape: a join to a `bgp_sg_*` CTE is written as a FULL JOIN behind an
`OFFSET 0` fence** (`emit_join._hashed_cte_join`). A FULL JOIN can only be
hashed or merged. Filtered outside the fence to the rows with a left side it
is exactly the LEFT JOIN; to the rows with both and the remaining conditions,
exactly the inner join. The fence is required: PostgreSQL reduces a FULL JOIN
to LEFT/inner under any strict condition above it, and both a `COALESCE` and a
`CASE` guard were reduced (measured, still nested-looped). The inner form was
needed too: fencing only the OPTIONALs isolated category_page's VALUES-split
inner join to `bgp_sg_q11_cte` and it nested-looped there instead (1,159 x
3,475; 1.2 s -> 3.3 s), so every join to such a CTE gets it. Taken only when
the ON has a plain `__uuid` equality (the hash key; an OPTIONAL's ON must be
only those). Cost: a FILTER above the join no longer narrows the left side
before it. Both sides are read whole in any plan already (the CTE is built
whole, the left side is joined in full).

### Result (`uw_prodshape2`, nine dashboard queries)

Rows processed (deterministic; timings below), identical result multisets for
all nine, **no CTE loop > 1 anywhere**:

| query | before | after |
|---|---:|---:|
| total | 2,320 | 2,320 |
| by_outcome | 1,129,648 | 15,267 |
| all_of | 228,115 | 228,112 |
| by_reason | 204,323 | 204,323 |
| latest_per_deal_by_outcome | 1,033,714 | 207,045 |
| decision_page | 931,124 | 205,093 |
| category_page | 2,580,445 | 498,217 |
| naics_for_category | 2,194,267 | 1,174,190 |
| only_cause | 488,312 | 488,312 |

naics_for_category had no CTE rescan but changes too (a `bgp_sg_*` join now
hashed), fewer rows, same results.

Timings, the generator before (a worktree at `9768d521`) and after, same
database, two alternating rounds of 5 runs, median ms (round 1 / round 2):

| query | before | after |
|---|---:|---:|
| by_outcome | 271 / 250 | 34 / 14 |
| latest_per_deal_by_outcome | 327 / 419 | 195 / 118 |
| decision_page | 549 / 328 | 255 / 227 |
| category_page | 1,048 / 717 | 405 / 354 |
| naics_for_category | 580 / 415 | 313 / 389 |
| all_of | 155 / 99 | 168 / 92 |
| by_reason | 105 / 99 | 101 / 73 |
| only_cause | 248 / 296 | 331 / 328 |

The workstation was paging throughout (6,500-12,600 swap-ins/s), so read these
for direction only; rows processed above is the measurement. only_cause's SQL
is byte-identical before and after, so its spread is the noise floor. What
remains of decision_page is linear slot-group work; on production's 1,920
decisions the removed part was larger (outer x CTE = decisions^2), not
re-measured there.

Suites on the vg test stack rebuilt for this code: unit, conformance,
integration, API (`:8002`) 0 failures; performance tier
(`tests/performance -m "not ingest_bench"`) 0 failures, its own assertions only
(no `perf_compare.py` baseline comparison).

Tests: `tests/unit/sparql_sql/test_slot_group_cte.py` (the fold, the anchor,
a leaf with its own variable, a correlated variable);
`tests/integration/test_hashed_cte_join.py` (same rows as the plain LEFT and
inner joins on PostgreSQL, unmatched rows on both sides, several matches, a
NULL in a remaining condition; no Nested Loop in the plan; the declines).
