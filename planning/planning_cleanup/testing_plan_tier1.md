# Testing Plan — Tier 1: Unit Tests (no DB)

> Split from [testing_plan.md](testing_plan.md). See main doc for overall
> architecture, CI pipeline, fixtures, and migration strategy.

## Purpose

Verify internal pipeline components in isolation — data structures,
individual optimizer passes, scoping rules, type generation. Fast feedback on
every PR.

## Why not snapshot-test generated SQL

The full pipeline has many interacting
optimizations (BGP reorder, filter pushdown, union pruning, text_needed_vars,
edge/frame MV rewrites). Alias numbering, JOIN order, and which term JOINs
survive all shift as optimizations evolve. Snapshot-testing raw SQL produces
constant false failures and brittle tests. Translation *correctness* (does the
SQL produce the right results?) belongs in Tier 2 conformance tests where we
run against PostgreSQL and compare results to DAWG/ARQ expected output.

## What to test at this tier

1. **IR structure after `collect()`** — assert on `PlanV2` node types,
   children, variable sets, and modifier chains. The IR is a stable,
   inspectable tree that doesn't change with SQL-level optimizations.

2. **Individual optimizer passes in isolation** — each pass has a narrow,
   deterministic contract:
   - `reorder_bgp`: given this IR, BGP triples are reordered by selectivity
   - `filter_pushdown`: given this IR, FILTER nodes move inside the BGP
   - `prune_union`: given this IR, dead UNION branches are removed
   - `rewrite_edge_table` / `rewrite_frame_entity_table`: given this IR,
     multi-JOIN patterns are collapsed to MV lookups
   - Input IR → output IR, fully deterministic per-pass.

3. **Variable scoping (`var_scope.py`)** — given a SPARQL algebra tree,
   assert which variables are visible, projected, and in-scope at each node.
   No SQL involved.

4. **Type generation (`sql_type_generation.py`)** — given a TypeRegistry
   state, assert correct XSD cast expressions, numeric promotion, typed
   lane selection, companion columns. Pure logic, no SQL execution.

5. **Expression generation (`emit_expressions.py`)** — individual SPARQL
   functions/operators → SQL fragment. These are small, deterministic
   translations at the single-expression level (e.g., `CONTAINS(?x, "foo")`
   → `LIKE '%foo%'`, `xsd:integer(?x)` → `CAST(TRUNC(...) AS INTEGER)`).
   Tested by feeding a single expression AST node into the expression
   emitter, not by running the full pipeline.

6. **Data format utilities** — JSON-LD ↔ GraphObject conversion, response
   model validation. Pure Python, no DB.

## What Tier 1 does NOT test

The full emit pipeline's SQL text — neither
exact strings nor structural properties (JOIN count, DISTINCT presence, etc.).
These are all subject to change as optimizer passes evolve.

## Fixture-based real plan tree testing (implemented)

Rather than only testing hand-constructed IR trees (which are "constructed to
pass"), we use a **generate-once, test-forever** approach:

1. A generator script (`tests/fixtures/plan_trees/generate_fixtures.py`)
   sends a corpus of real SPARQL queries to the running Jena sidecar and
   captures the raw JSON compile responses.
2. Fixtures are stored as JSON in `tests/fixtures/plan_trees/json/`.
3. At test time, fixtures are loaded and reconstructed into real `PlanV2`
   trees via `map_compile_response()` + `collect()` — **no sidecar needed**.
4. Tests assert **structural invariants** (valid kinds, correct child counts),
   **scope invariants** (projected vars visible, text-needed ⊆ BGP vars),
   and **optimizer safety** (passes never crash on real inputs).
5. Regenerate fixtures only when the sidecar version or `collect.py` changes.

This gives us real-world query shapes (UNIONs, GROUP BY, OPTIONAL, MINUS,
subqueries, XSD casts, multi-pattern entities) without a runtime dependency
on the Java sidecar. The corpus is defined in `sparql_corpus.py` and can be
expanded as new query patterns are encountered.

## Pipeline-level assertions that ARE stable

(can be Tier 1 with a SQL parser, or lightweight Tier 2 with PG):

1. **Valid SQL** — every SPARQL query in the test corpus must produce
   syntactically valid SQL. Verify cheaply via `pglast.parse_sql()` (no DB
   needed, pure Python) or via `EXPLAIN` against PG (parses + plans without
   executing). If the pipeline emits unparseable SQL, that's always a bug
   regardless of optimizer state.

2. **Result stability** — for a fixed dataset, the same SPARQL query must
   always produce the same result set (modulo row order for unordered
   queries). This doesn't require DAWG expected output — just run the query
   twice (or after an optimizer change) and assert the results match. This
   catches optimizer regressions without coupling tests to any specific SQL
   shape.

## Coverage targets

- `var_scope.py` — variable visibility across OPTIONAL, UNION, subquery
- `sql_type_generation.py` — XSD casts, companion columns, typed lanes
- `collect.py` / `ir.py` — IR construction from SPARQL algebra
- Each optimizer pass (`filter_pushdown`, `reorder_bgp`, `prune_union`,
  `rewrite_edge_table`, `rewrite_frame_entity_table`)
- `emit_expressions.py` — per-function/operator unit tests
- Response models and data format utilities

**Estimated count**: ~150–200 test cases. *(Actual: 326 as of initial implementation.)*

---

## Implementation Progress

**Infrastructure** (all merged):
- `tests/` directory with subdirectories: `unit/`, `conformance/`, `integration/`, `api/`, `performance/`
- `tests/conftest.py` with pytest markers: `unit`, `conformance`, `integration`, `api`, `performance`, `slow`
- `pyproject.toml` updated: `testpaths = ["tests"]`, `pglast>=7.0` in dev dependencies

**Test files** (`tests/unit/sparql_sql/`):

| File | Tests | What it validates |
|------|-------|-------------------|
| `test_ir.py` | 21 | AliasGenerator, plan kind constants, PlanV2 structure, TableRef, VarSlot |
| `test_var_scope.py` | 37 | VarScope operations, compute_scope for all plan kinds, vars_in_expr, compute_text_needed_vars |
| `test_filter_pushdown.py` | 14 | CONTAINS/STRSTARTS/STRENDS/EQ/REGEX pushdown, SQL escaping, partial consumption |
| `test_prune_union.py` | 8 | Dead branch detection, nested unions, both-dead safety, tagged constraints |
| `test_reorder_bgp.py` | 8 | Chain ordering, text-filter anchoring, cardinality tiebreakers, constraint assignment |
| `test_real_plans.py` | 306 | Structural/scope/optimizer invariants on real PlanV2 trees from 34 fixture queries |
| `test_emit_pipeline.py` | 170 | Full collect→emit pipeline produces valid PostgreSQL (pglast syntax validation) |
| `test_emit_expressions.py` | 100 | Per-function/operator unit tests: comparisons, arithmetic, string, type-testing, regex, accessors, conditionals, math, hash, datetime, constructors, IN/NOT IN, aggregators, XSD casts |
| `test_sql_type_generation.py` | 85 | ColumnInfo, TypedExpr (companions, typed lanes, is_numeric/bool/dt), TypeRegistry (register, allocate, passthrough, remap, coalesce, null companions, child scopes), infer_expr_type, error guards |
| `test_rewrite_tables.py` | 28 | Edge table rewrite (pair detection via co-ref + var_slots, var remapping, constraint dedup, recursion), frame-entity rewrite (6-table pattern detection, column remapping, incomplete patterns) |
| `test_emit_group.py` | 27 | GROUP BY, aggregates (COUNT/SUM/AVG/MIN/MAX/GROUP_CONCAT/SAMPLE), HAVING, pushdown candidates, _all_count_no_keys, _qualify_agg_inner |
| `test_emit_extend.py` | 18 | BIND literal/variable/function, vector-driving top-K (similarity/nearby/threshold/VectorRequest), STRAFTER/STRBEFORE/CONCAT companions |
| `test_emit_slice.py` | 8 | LIMIT/OFFSET clauses, buried ORDER re-application, depth limit |
| `test_emit_table.py` | 9 | VALUES: URI/literal/bnode/UNDEF, multi-row UNION ALL, multi-var, SQL escaping |
| `test_emit_distinct.py` | 10 | DISTINCT/REDUCED, pushdown conditions, safe modifier chains, output vars |
| `test_emit_path.py` | 23 | All path types (Link/Inverse/Alt/Seq/OneOrMore/ZeroOrMore/ZeroOrOne/NegPropSet), graph clauses, CTE merge, variable binding |
| `test_emit_context.py` | 23 | EmitContext init, TraceStep, ProcessingTrace, property methods, logging |
| `test_collect.py` | 30 | collect() happy paths, error handling, edge cases |
| `test_emit_join_order_project.py` | 45 | emit_join, emit_order, emit_project modules |
| **Total** | **1018** | **0.51s, no external dependencies at test time** |

**Fixture infrastructure** (`tests/fixtures/plan_trees/`):
- `sparql_corpus.py` — 34 SPARQL queries covering SELECT, FILTER, OPTIONAL, UNION, GROUP BY, ORDER BY, DISTINCT, BIND, MINUS, subqueries, VALUES, XSD casts, property paths (sequence/alternative/star/plus/inverse), CONSTRUCT, ASK, DESCRIBE, NOT EXISTS, nested OPTIONAL, GROUP_CONCAT, SUM/AVG, computed expressions
- `generate_fixtures.py` — sends corpus to Jena sidecar, saves raw JSON responses
- `json/` — generated fixture files (34 queries, committed)
- Tests load fixtures → `map_compile_response()` + `collect()` → real PlanV2 trees (no sidecar at test time)
- Regenerate only when sidecar version or `collect.py` contract changes

**Key design decisions**:
1. **Generate-once, test-forever**: Sidecar JSON is captured once; tests reconstruct real trees in pure Python.
2. **pglast for SQL validation**: Every fixture query's generated SQL is verified as syntactically valid PostgreSQL without needing a running database.
3. **Invariant-based testing on real inputs**: Rather than hand-crafting inputs that pass, tests assert structural/semantic properties that must hold for all valid query shapes.
4. **Graceful degradation**: `test_real_plans.py` and `test_emit_pipeline.py` skip cleanly if fixtures don't exist.

## Remaining

- ~~`emit_expressions.py` — per-function/operator unit tests~~ ✅ DONE (100 tests)
- ~~`sql_type_generation.py` — TypeRegistry, companion columns, typed lanes~~ ✅ DONE (85 tests)
- ~~`rewrite_edge_table.py` / `rewrite_frame_entity_table.py` — MV rewrite passes~~ ✅ DONE (28 tests)
- ~~Expand fixture corpus (property paths, CONSTRUCT, ASK, DESCRIBE)~~ ✅ DONE (34 queries)
- ~~CI integration (GitHub Actions workflow for Tier 1 on every PR)~~ ✅ DONE (`.github/workflows/unit-tests.yml`)
