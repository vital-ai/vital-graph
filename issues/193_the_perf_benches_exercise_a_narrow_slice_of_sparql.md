# The Perf Benches Exercise A Narrow Slice Of SPARQL

## Status: OPEN. No bench anywhere touches OPTIONAL, MINUS, BIND, a sub-SELECT
## or a property path. The largest coverage gap in the suite.

**Related:** `issues/178`-`182` (five shape defects, none of them benched),
`issues/179` (LCASE defeats the trigram index),
`planning/planning_performance/perf_coverage_gaps_plan.md` §6

## Measured — operators appearing anywhere in `tests/performance/*.py`

| present | | absent entirely | |
|---|---|---|---|
| `VALUES` | 31 | `OPTIONAL` / left-join | **0** |
| `DISTINCT` | 30 | `MINUS` | **0** |
| `ORDER BY` | 18 | `BIND` | **0** |
| `FILTER` | 11 | sub-SELECT | **0** |
| `GROUP BY` | 9 | property paths | **0** |
| `UNION` | 7 | `REGEX` / `CONTAINS` / `LCASE` | **0** |
| `NOT EXISTS` | 6 | `DESCRIBE`, `ASK` | **0** |
| `HAVING` | 1 | `SERVICE` | **0** |
| `CONSTRUCT` | 1 | UPDATE forms | **0** (`issues/192`) |

The authored SPARQL that does exist is five shapes in
`test_generated_sql_plans.py`: `predicate_scan`, `two_hop_join`,
`typed_listing`, and two lead-dataset variants. Everything else in the tier
reaches SQL through KGQuery, where the user writes no SPARQL at all — so the
GENERATED shapes are a coverage question too, not only the authored ones.

## Why this is the gap that keeps costing

The optimiser work is landing in the SPARQL→SQL pipeline, and the recent defects
are all shape defects:

    178  the frame CONSTRUCT loses half its triples and spends 58s in generation
    179  LCASE + CONTAINS defeats the trigram index
    180  a union-bound variable forces a null-tolerant join
    181  the traversal gate cannot see a text filter as a driving set
    182  the frame CONSTRUCT enumerates every frame in the space

Not one of those shapes is in a bench. Every one was found by hand, on a real
query, after it was already slow, and none of them can regress into a red cell
today because nothing measures the shape.

Second reason: interference. An optimisation for one shape is routinely a
pessimisation for its neighbour — left-join against NOT EXISTS is the classic
pair, and `180` is already a join strategy chosen for one arm hurting another.
With no OPTIONAL or MINUS cell anywhere, that trade is invisible until a client
reports it.

## Most of this is assembly

* **`scripts/query_shape_audit.py`** ranks a corpus by work proportional to the
  ANSWER — busiest plan node loops ÷ rows returned. No baseline, no domain
  knowledge, no intuition about what should be fast. On `178` the ratio was 671
  before and 0.8 after, and it separated six attempted rewrites that
  **wall-clock did not** — two failures looked like improvements on a warm
  cache. It already takes a directory of `.sparql` and emits `--json`.
* **`tests/conformance/dawg_data`** — 1,120 `.rq` across 47 `sparql11` category
  directories (`bind`, `exists`, `negation`, `property-path`, `subquery`,
  `aggregates`, `construct`, `functions`, `grouping`, `project-expression`, …).
  The shape enumeration already exists. What it is NOT is a cost test: DAWG
  fixtures are a handful of triples, so every query is fast against every plan.
* **`plan_shape.report_slow_query` + `--from-log`** replays a query that was slow
  in production against the same space here, with no transcription.

## What to build

1. A shape-matrix corpus in the repo — one `.sparql` per (feature ×
   selectivity), written against the resident fixtures rather than lifted from
   DAWG. Axes: algebra (BGP, join, OPTIONAL, UNION, MINUS, EXISTS/NOT EXISTS,
   sub-SELECT, VALUES, property paths, graph scoping), modifiers
   (DISTINCT/REDUCED, ORDER BY single/multi/DESC/expression, LIMIT-OFFSET at
   depth, GROUP BY + HAVING, aggregates per datatype), expressions (BIND, FILTER
   by datatype, REGEX/CONTAINS/LCASE, datetime compare), forms (SELECT,
   CONSTRUCT, DESCRIBE, ASK, UPDATE).
2. Gate on the RATIO, not the clock. `work_per_answer` is scale-portable and is
   the number that separated `178`'s attempts. Record it as a claim metric with
   a rule (`issues/188`), alongside the plan-shape tree.
3. Make coverage countable: "N of 47 `sparql11` categories have a priced shape at
   scale" — the discipline that made the conformance hole actionable when it was
   stated as "19 of 34 categories ran".
4. A declined shape is a RECORDED OUTCOME, not a skip. Not every form is
   supported by the `sparql_sql` backend; one that declines must record the
   decline and its reason, because a silent skip is the coverage failure
   `issues/188` is about (`issues/167`).

Keep it cheap: one cell per shape at one fixture size, widened only where a
cliff appears. `test_paging_fence_covers_every_shape.py` is the precedent —
48 cells, `ingest_bench`-marked so it stays out of the edit loop.

Each shape this catches doing work disproportionate to its answer gets its own
issue, which is exactly how `178`-`182` were worked.
