# 330 — A slot-group CTE is rescanned once per outer row: quadratic in the number of decisions

## Status: RESOLVED 2026-10-30, RELEASED in v0.0.99 and confirmed on production (read-only A/B: latest_per_deal 1,517 -> 184 ms, decision_page 1,037 -> 379 ms, the other seven unchanged). Second attempt. The first fix (`a08ad393`, v0.0.98) missed production's shape and was reverted (`2e78ae0b`); this one is accepted on production read-only: latest_per_deal 1,515 -> 188 ms, decision_page 1,067 -> 375 ms, the other seven byte-identical SQL. See the last section.

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

## Production after v0.0.98 (2026-10-30, read-only): no gain, one regression

`prod_explain_ab.py` on the production UW space, the generator before
(`9768d521`) and after (`a08ad393`), same data (~1,950 decisions), back to back,
5 runs each, every block a buffer hit, median ms:

| query | before | after |
|---|---:|---:|
| by_outcome | 40.6 | 40.7 |
| latest_per_deal_by_outcome | 1,505.8 | 1,510.1 |
| decision_page | 1,029.7 | 1,091.1 |
| category_page | 635.2 | 715.3 |
| naics_for_category | 303.0 | **1,371.9** |

Same row counts both ways. (latest_per_deal grew 1,157 -> 1,506 ms since the
v0.0.97 read from the data alone, under both generators.)

**Why the fix missed: production's dominant rescan is a THIRD shape.** The
entity anchor joined to an ANCHORED slot group in the main BGP,
`q0.subject_uuid = sg_q4_cte.q4__object_uuid`, Nested Loop Inner, CTE estimated
70 rows, actual 1,950 x 1,950 loops: in decision_page and, twice
(`sg_q4_cte`, `sg_q14_cte`), in latest_per_deal. It is the shape this issue
recorded from production in the first place. On `uw_prodshape2` PostgreSQL
hashed that join, so the local reproduction showed only the two other shapes,
and those are what `a08ad393` fixed. Neither change touches this one. The
local acceptance test was "no CTE loop > 1 on `uw_prodshape2`"; it needed to be
"production's plan loses its rescan".

**Why naics_for_category regressed: the fence.** Its only difference is one
`_hashed_cte_join` (same CTEs, no fold). Behind `OFFSET 0` the left side is
planned alone, without the restriction the joins around it used to supply,
and becomes a 1,865,999-row nested loop. That is the trade-off recorded under
"Fix", measured locally as harmless; on production it is 4.5x.
decision_page and category_page carry 6 and 7 fences and are 6% and 13% slower.

**Next:** a local reproduction that shows production's plan (the anchored
`q0 x sg_*` nested loop) before any further change, and acceptance measured
on production read-only with this same A/B.

## The fix, second attempt (2026-10-30): tell PostgreSQL the size, in a pure star only

`a08ad393` was reverted (`2e78ae0b`). Worked out on PRODUCTION's plans this
time, read-only, with hand-edited SQL first (`prod_sql_probe.py`), and accepted
only on the production A/B.

**The mechanism.** The generator knows each group's size exactly (`pinned`,
its pin's `rdf_stats` count). PostgreSQL cannot be given a CTE's size, but it
adds up a `UNION ALL`'s branches, estimates a constant `generate_series`
exactly, and estimates `n < 0` on its column at 1/3. So each hinted CTE gets

    UNION ALL SELECT NULL::uuid AS ..., ... FROM generate_series(1, 3 * pinned) AS sg_qN_cte_pad(n) WHERE sg_qN_cte_pad.n < 0

which returns no row and raises the estimate to the group's real size. No
fence, no GUC, no statistics change. `tests/integration/test_slot_group_size_hint.py`
pins both planner behaviours it relies on.

**Only in a pure star** (`slot_group_cte._size_hints`): groups joined on one
?d plus anchors (constant predicate and object, ?d the only variable), nothing
else. Measured on production with hand-edited variants (timing off, same rows):

| variant | decision_page | latest_per_deal | category_page | naics_for_category |
|---|---:|---:|---:|---:|
| none (before) | 774 | 1,027 | 610 | 299 |
| every group hinted | 356 | 182 | 1,842 (timing on) | 2,276 (timing on) |
| all but groups beside a `hasKGGraphURI` leaf | 356 | 182 | 709 | 288 |
| pure stars only | 356 | 182 | unchanged | unchanged |

A corrected CTE estimate beside an ungrouped `hasKGGraphURI` leaf makes
PostgreSQL drive from the CTE into that leaf's per-entity fan-out (estimated
14, actual 1,094: `issues/293`'s fan-out); on category_page's mixed BGP every
hinted variant was slower. That is `issues/119` §9 again: a corrected estimate
is safe only where nothing else misestimated can be reached through it.

### Acceptance, on production (read-only, 2026-10-30)

`prod_explain_ab.py`, the generator before (`9768d521`) and after, same data,
back to back, 5 runs, median ms:

| query | before | after | SQL |
|---|---:|---:|---|
| latest_per_deal_by_outcome | 1,514.7 | **187.6** | 4 hints |
| decision_page | 1,067.4 | **375.4** | 3 hints |
| total, by_outcome, all_of, by_reason, category_page, naics_for_category, only_cause | | | byte-identical |

The seven unchanged queries moved by noise only (all_of 277 / 268, by_reason
281 / 267, category_page 671 / 640, naics 326 / 312, only_cause 542 / 526).
On the two that changed: identical result multisets, no CTE loop > 1, rows
processed 4,039,031 -> 242,386 and 7,731,998 -> 134,806.

Locally (`uw_prodshape2`) the same two queries are hinted, all nine return the
rows they did before, and the local-only rescans of the other two shapes
remain: production does not show them, which is why fixing them bought
nothing there.

## Confirmed on production after v0.0.99 (2026-10-30, read-only)

v0.0.99 (built from `526b64f2`) live on production. The same A/B, the
generator before 330 (`9768d521`) and `526b64f2`, same data, 5 runs, median ms:

| query | before 330 | v0.0.99 | SQL |
|---|---:|---:|---|
| latest_per_deal_by_outcome | 1,517.3 | **184.1** | hinted |
| decision_page | 1,036.8 | **378.5** | hinted |
| total | 3.6 | 3.7 | identical |
| by_outcome | 41.0 | 41.1 | identical |
| all_of | 267.0 | 263.4 | identical |
| by_reason | 260.7 | 264.9 | identical |
| category_page | 642.5 | 656.7 | identical |
| naics_for_category | 307.2 | 312.3 | identical |
| only_cause | 540.3 | 526.5 | identical |

Same rows; no CTE Scan with loops > 1 in any of the nine plans. v0.0.98's
regression (naics_for_category 1,372 ms) is gone.
