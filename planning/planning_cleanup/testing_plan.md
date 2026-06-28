# VitalGraph Formal Testing Plan

## Goal

Transform VitalGraph into a professionally tested, high-confidence database system
focused exclusively on the **sparql_sql** pure-PostgreSQL backend.
Other backends (fuseki, fuseki_postgresql, oxigraph, tidb, aurora) are experimental
and out of scope for formal verification.

The system should inspire the same level of trust that users expect from
Weaviate, MariaDB, CockroachDB, or any serious database project — meaning
deterministic, automated, repeatable test suites that run in CI and gate every
merge.

Because VitalGraph delegates SQL execution to PostgreSQL, we do **not** need to
re-verify SQL semantics (joins, aggregation, transactions, etc.).
Testing focuses on the **unique value VitalGraph adds**:

1. SPARQL → SQL translation correctness
2. RDF quad storage fidelity (round-trip, datatypes, graphs)
3. Schema lifecycle (space create/drop, migrations)
4. KG-layer operations (entity/frame/slot/type CRUD)
5. REST API contract correctness
6. Concurrency and connection-pool safety
7. Performance regression detection

---

## Current State Assessment

### What exists today

| Asset | Location | Status |
|-------|----------|--------|
| DAWG SPARQL 1.1 conformance suite | `vitalgraph_sparql_sql/dawg_test_impl/` | Custom runner, ~80% pass (v87: 104/156), **not pytest, not in CI** |
| Jena ARQ test suite integration | same runner, `jena-main-source/` | Available but results not tracked formally |
| Structural emit unit tests | ad-hoc in dev scripts | 14/14 pass, **not in CI** |
| Service integration tests | `vitalgraph_service_tests/` | unittest-based, requires running server, **not in CI** |
| Client test scripts | `vitalgraph_client_test/` | ~70 scripts, **manual execution** |
| Mock client tests | `vitalgraph_mock_client_test/` | ~30 scripts, **manual execution** |
| KG impl test scripts | `test_script_kg_impl/` | orchestrator-based, **manual** |
| Misc test scripts | `test_scripts/`, `test_scripts_misc/` | ~130 scripts, **manual** |
| CI workflow | `.github/workflows/test-packaging.yml` | Import smoke tests only — no functional tests |

### Key gaps

- **No pytest infrastructure** — no `conftest.py`, no fixtures, no markers.
- **No CI functional tests** — packaging checks only.
- **DAWG tests use custom runner** — not integrated with pytest/CI.
- **Integration tests require live server** — no containerized test harness.
- **No coverage tracking**.
- **No performance regression baseline**.
- **Test scripts are scattered** across 10+ top-level directories.

---

## Architecture of the Test Suite

### Tier structure (modeled on how databases like Weaviate / MariaDB organize tests)

```
tests/
├── unit/                        # Tier 1: fast, no DB, no network
│   ├── sparql_sql/              # SPARQL-to-SQL translation
│   │   ├── test_collect.py      # Op-tree → PlanV2 IR
│   │   ├── test_emit_bgp.py     # BGP SQL generation
│   │   ├── test_emit_filter.py  # FILTER expressions
│   │   ├── test_emit_group.py   # GROUP BY / aggregates
│   │   ├── test_emit_union.py   # UNION
│   │   ├── test_emit_path.py    # Property paths
│   │   ├── test_emit_update.py  # SPARQL UPDATE → SQL
│   │   ├── test_var_scope.py    # Variable scoping
│   │   ├── test_ir.py           # IR data structures
│   │   └── test_type_gen.py     # Type generation / binding
│   ├── schema/
│   │   └── test_schema_ddl.py   # DDL generation correctness
│   ├── model/
│   │   └── test_response_models.py
│   └── utils/
│       └── test_data_format.py  # JSON-LD ↔ GraphObject conversion
│
├── conformance/                 # Tier 2: DAWG + Jena ARQ, needs PG
│   ├── conftest.py              # Shared fixtures: temp space, data load
│   ├── test_dawg_bind.py
│   ├── test_dawg_aggregates.py
│   ├── test_dawg_functions.py
│   ├── test_dawg_negation.py
│   ├── test_dawg_exists.py
│   ├── test_dawg_grouping.py
│   ├── test_dawg_construct.py
│   ├── test_dawg_property_path.py
│   ├── test_dawg_subquery.py
│   ├── test_dawg_update.py
│   ├── test_jena_arq.py         # Jena ARQ categories
│   └── README.md                # How to run, expected pass rates
│
├── integration/                 # Tier 3: full stack, needs PG
│   ├── conftest.py              # Fixtures: real SparqlSQLDbImpl, temp space
│   ├── storage/
│   │   ├── test_quad_roundtrip.py    # Insert → query → verify
│   │   ├── test_datatype_fidelity.py # XSD types, lang tags, booleans
│   │   ├── test_graph_operations.py  # CREATE/CLEAR/DROP GRAPH
│   │   └── test_bulk_load.py         # Large batch insert + verify
│   ├── schema/
│   │   ├── test_space_lifecycle.py   # Create, drop, recreate
│   │   ├── test_index_management.py  # Index create/rebuild
│   │   └── test_migration.py         # Schema version upgrades
│   ├── kg/
│   │   ├── test_entity_crud.py
│   │   ├── test_frame_crud.py
│   │   ├── test_slot_crud.py
│   │   ├── test_type_crud.py
│   │   ├── test_relation_crud.py
│   │   ├── test_entity_query.py      # Multi-criteria, sorting, paging
│   │   └── test_entity_graph.py      # Full entity-graph retrieval
│   ├── sparql/
│   │   ├── test_select_queries.py    # End-to-end SPARQL SELECT
│   │   ├── test_construct_queries.py
│   │   ├── test_update_queries.py
│   │   └── test_edge_cases.py        # NULL, empty, Unicode, large literals
│   └── concurrency/
│       ├── test_pool_safety.py       # Connection pool under load
│       └── test_concurrent_writes.py # Race conditions, deadlocks
│
├── api/                         # Tier 4: REST API, needs running server
│   ├── conftest.py              # Fixtures: httpx client, test space
│   ├── test_spaces_api.py
│   ├── test_entities_api.py
│   ├── test_frames_api.py
│   ├── test_sparql_api.py
│   ├── test_triples_api.py
│   ├── test_import_export_api.py
│   └── test_auth_api.py
│
├── performance/                 # Tier 5: benchmarks (not gating)
│   ├── test_query_latency.py    # p50/p95/p99 regression detection
│   ├── test_bulk_throughput.py   # quads/sec on insert
│   └── conftest.py              # WordNet or synthetic dataset
│
└── conftest.py                  # Root: pytest markers, DB connection helpers
```

### Pytest markers

```python
# tests/conftest.py
import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "unit: fast tests, no external deps")
    config.addinivalue_line("markers", "conformance: DAWG/ARQ SPARQL conformance")
    config.addinivalue_line("markers", "integration: needs PostgreSQL")
    config.addinivalue_line("markers", "api: needs running VitalGraph server")
    config.addinivalue_line("markers", "performance: benchmark tests")
    config.addinivalue_line("markers", "slow: tests taking >10s")
```

### Typical CI invocations

```bash
# Fast feedback (< 30s)
pytest tests/unit/ -m unit

# Conformance (needs PG, < 5 min)
pytest tests/conformance/ -m conformance

# Integration (needs PG, < 10 min)
pytest tests/integration/ -m integration

# Full suite excluding performance
pytest tests/ -m "not performance"

# Performance (manual / nightly)
pytest tests/performance/ -m performance --benchmark-json=results.json
```

---

## Tier Details

### Tier 1 — Unit Tests (no DB)

**Purpose**: Verify internal pipeline components in isolation — data structures,
individual optimizer passes, scoping rules, type generation. Fast feedback on
every PR.

**Why not snapshot-test generated SQL**: The full pipeline has many interacting
optimizations (BGP reorder, filter pushdown, union pruning, text_needed_vars,
edge/frame MV rewrites). Alias numbering, JOIN order, and which term JOINs
survive all shift as optimizations evolve. Snapshot-testing raw SQL produces
constant false failures and brittle tests. Translation *correctness* (does the
SQL produce the right results?) belongs in Tier 2 conformance tests where we
run against PostgreSQL and compare results to DAWG/ARQ expected output.

**What to test at this tier**:

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

**What Tier 1 does NOT test**: The full emit pipeline's SQL text — neither
exact strings nor structural properties (JOIN count, DISTINCT presence, etc.).
These are all subject to change as optimizer passes evolve.

**Pipeline-level assertions that ARE stable** (can be Tier 1 with a SQL
parser, or lightweight Tier 2 with PG):

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

**Coverage targets**:
- `var_scope.py` — variable visibility across OPTIONAL, UNION, subquery
- `sql_type_generation.py` — XSD casts, companion columns, typed lanes
- `collect.py` / `ir.py` — IR construction from SPARQL algebra
- Each optimizer pass (`filter_pushdown`, `reorder_bgp`, `prune_union`,
  `rewrite_edge_table`, `rewrite_frame_entity_table`)
- `emit_expressions.py` — per-function/operator unit tests
- Response models and data format utilities

**Estimated count**: ~150–200 test cases.

### Tier 2 — SPARQL Conformance (DAWG + Jena ARQ)

**Purpose**: Prove correctness against the W3C SPARQL 1.1 test suite and
Apache Jena's ARQ test suite.

**Approach**:
- Wrap the existing DAWG runner as a pytest parameterized test.
  Each DAWG test case becomes a `pytest.mark.parametrize` entry.
- Compare VitalGraph results against expected `.srx` / `.ttl` files.
- Use pyoxigraph as a reference oracle for any result ambiguity.
- Track **expected failures** with `pytest.mark.xfail` so the suite
  is green even while we iterate on unsupported features.

**Current baseline** (v87 report):
- P0 categories: 104 pass / 18 fail / 25 skip / 9 error = 79.4%
- Target: **95%+ pass rate** on P0, all failures documented as xfail.

**DAWG categories to cover**:

| Category | Current | Target |
|----------|---------|--------|
| bind | 7/10 | 10/10 |
| aggregates | 32/32* | maintain |
| functions | partial | 90%+ |
| negation | partial | 95%+ |
| exists | partial | 95%+ |
| grouping | partial | 95%+ |
| construct | partial | 90%+ |
| property-path | not started | 80%+ |
| subquery | partial | 90%+ |
| update (add/delete/insert/etc.) | partial | 85%+ |

*Aggregates 32/32 non-skipped as of last session.

**Jena ARQ categories**: Ask, Construct, Describe, Optional, Union, Negation,
GroupBy, SubQuery, Paths, Basic, Bound, Distinct, Sort, Select, SelectExpr, Assign.

### Tier 3 — Integration Tests (needs PG)

**Purpose**: Verify end-to-end behavior through the real `SparqlSQLDbImpl`
against a real PostgreSQL instance.

**Approach**:
- Use a **dedicated test database** (e.g., `vitalgraph_test`) created/destroyed
  per session.
- Each test module creates a temporary space, loads data, runs operations,
  validates results, and drops the space.
- Fixtures manage the asyncpg pool lifecycle.

**Key test areas**:

1. **Quad round-trip**: Insert triples via SPARQL UPDATE, retrieve via SELECT,
   verify exact match (URI, literal value, datatype, language tag, graph).

2. **Datatype fidelity**: All XSD types (string, integer, double, boolean,
   dateTime, etc.) survive round-trip. Edge cases: empty string, very large
   integers, NaN, INF, Unicode (emoji, CJK, RTL).

3. **Graph operations**: CREATE GRAPH, INSERT DATA into named graph,
   CLEAR GRAPH, DROP GRAPH. Verify isolation between graphs.

4. **KG CRUD**: Full lifecycle for entities, frames, slots, types, relations.
   Verify VitalSigns JSON-LD ↔ triple round-trip.

5. **Concurrency**: Multiple concurrent writers to the same space.
   Verify no deadlocks, no lost updates, correct connection pool behavior
   under asyncio.gather load.

6. **Schema lifecycle**: Create space, drop space, recreate with same name.
   Verify clean state, no orphaned indexes or tables.

**Estimated count**: ~100–150 test cases.

### Tier 4 — API / End-to-End Tests (needs running server)

**Purpose**: Verify the REST API contracts (request/response shapes, status
codes, pagination, error handling) via end-to-end tests against a live service.

**Key distinction**: These are **not pytest tests**. They are end-to-end test
scripts that run against a live VitalGraph server and exercise the system
through the Python and/or TypeScript client libraries. They consolidate and
improve the existing test runners and cases currently scattered across
`vitalgraph_client_test/`, `vitalgraph_mock_client_test/`, `test_client_api/`,
and `vitalgraph_service_tests/`. The goal is a unified, improved set of
end-to-end scenarios built on the proven patterns that already exist.

**Approach**:
- Requires a running VitalGraph server (local, Docker, or CI service).
- Exercises the system via the VitalGraph client(s) (Python `VitalGraphClient`,
  TypeScript client, or raw HTTP).
- Validates end-to-end behavior including auth, serialization, and round-trip
  data integrity.
- Test authentication, authorization, error responses.

**Coverage**:
- Every endpoint in `vitalgraph/endpoint/` gets at least:
  - Happy path (200/201)
  - Not found (404)
  - Bad request (400/422)
  - Auth required (401)
- Pagination correctness (total_count, offset, page_size).
- Large payload handling.

**Estimated count**: ~80–120 test cases.

### Tier 5 — Performance Tests (benchmarks)

**Purpose**: Detect performance regressions. Not gating — run nightly or on
demand.

**Approach**:
- Use `pytest-benchmark` for microbenchmarks.
- Maintain a baseline JSON file with known-good p50/p95/p99 values.
- Alert (but don't fail) on >20% regression.

**Key benchmarks**:
- SPARQL→SQL generation latency (no DB): p50 < 5ms
- Simple SELECT execution (10 results): p50 < 50ms
- Complex multi-join query (WordNet): p50 < 200ms
- Bulk insert throughput: > 10k quads/sec
- Entity list with graph retrieval: p50 < 200ms

---

## Project Cleanup

The repository has accumulated significant clutter: abandoned backends,
duplicate frontend directories, scattered ad-hoc scripts, stale data files,
and dead code. Before building a formal test suite, the project needs
consolidation so that developers can navigate confidently and CI doesn't
process irrelevant files.

### Guiding principles

- **Delete** anything that has no path to being used again.
- **Archive to a branch** anything with potential reference value but no
  active use (preserves git history without polluting the working tree).
- **Move into `vitalgraph/`** anything that is part of the shipped product
  but currently lives at the repo root.
- **Consolidate tests** into `tests/` (the new formal structure).

### Items to remove (delete or .gitignore)

| Item | Reason |
|------|--------|
| `archive_vitalgraph_old/` | Superseded code, already labeled "archive" |
| `frontend-archive/` | Empty / abandoned |
| `frontend-old/` | Empty / abandoned |
| `rdflib_sqlalchemy/` | Empty, unused dependency experiment |
| `oxigraph/` (root-level) | Empty, oxigraph backend abandoned |
| `notes/` | Empty |
| `notes.txt` | Scratch notes |
| `planning_internal/` | Empty |
| `web_assets/` | Empty |
| `k8s_config/` | Empty |
| `minioFiles/` | Empty |
| `lead_test_data/` | Empty |
| `lead_test_data_docs/` | Empty |
| `test_data/` | Empty |
| `dist/` | Build artifact, should be .gitignored |
| `vital_graph.egg-info/` | Build artifact, should be .gitignored |
| `__pycache__/` (root) | Should be .gitignored |
| `_debug_industry.py` | One-off debug script |
| `test_rdflib_parsing.py` | Empty file |
| `test_term_uuid_ddl.py` | One-off debug script |
| `test_term_uuid_match.py` | One-off debug script |
| `space_realistic_org_test_quads.nq` | 60KB test data file at repo root |
| `crossref_repair_*.txt` | 9MB repair log at repo root |
| `vitalhome.zip` | Binary artifact at repo root |
| `registry_generated_vectors/` | Empty, generated output |
| `registry_output/` | Empty, generated output |

### Deprecated backend code to remove or mark experimental

| Item | Action |
|------|--------|
| `vitalgraph/db/tidb/` | Empty stubs (0-byte files). **Delete**. |
| `vitalgraph/db/aurora_postgresql/` | Empty stub (0-byte file). **Delete**. |
| `vitalgraph/db/oxigraph/` | All 0-byte files. **Delete**. |
| `vitalgraph/db/fuseki/` | Active but experimental. **Mark with README**: "Experimental — not formally tested." |
| `vitalgraph/db/fuseki_postgresql/` | Active but experimental. **Mark with README**: "Experimental — not formally tested." |
| `vitalgraph/db/mock/` | Used for mock client. **Keep**, but move tests into `tests/`. |

### Test directory consolidation

Current state: 11 test-related top-level directories. Target: 1 (`tests/`).

| Current location | Action |
|-----------------|--------|
| `test_scripts/` (~130 scripts) | **Triage**: port valuable ones to `tests/integration/` or `tests/conformance/`, delete the rest. `test_scripts/archive/` (~90 scripts) can be deleted outright. |
| `test_scripts_misc/` (~40 scripts) | **Triage**: port or delete. |
| `test_script_kg_impl/` | **Port** orchestrator-based KG tests to `tests/integration/kg/`. |
| `test_sparql/` | **Move** fixtures/utils into `tests/conformance/`. |
| `test_sparql_sql_endpoints/` | Empty `__init__.py` only. **Delete**. |
| `test_vs/` | Single file. **Port** to `tests/unit/` or delete. |
| `test_client_api/` | **Port** to `tests/api/`. |
| `test_files/` (~40 PDFs) | Test fixtures. **Move** to `tests/fixtures/files/` or .gitignore if too large. |
| `test_files_download/` | **Delete** or .gitignore. |
| `localTestFiles/` | **Delete** or .gitignore. |
| `vitalgraph_client_test/` (~70 scripts) | **Port** valuable scripts to `tests/api/` and `tests/integration/`. |
| `vitalgraph_mock_client_test/` (~30 scripts) | **Port** to `tests/integration/mock/`. |
| `vitalgraph_service_tests/` | **Port** to `tests/integration/service/`. |
| `vitalsigns_test_scripts/` | **Port** to `tests/unit/vitalsigns/` or delete. |

### Other root-level cleanup

| Item | Action |
|------|--------|
| `debug_scripts/` (~32 scripts) | **Triage**: keep only actively used ones, move to `scripts/debug/`. |
| `sql_scripts/` (~34 files) | **Move** to `vitalgraph/db/sparql_sql/sql/` or `scripts/sql/`. |
| `scripts/` | **Keep**, consolidate `debug_scripts/` into it. |
| `log_analysis/` | **Move** to `scripts/log_analysis/`. |
| `examples/` | **Keep** (1 file), good for users. |
| `planning*/` (5 dirs) | **Keep** during development, add to .gitignore for releases. |
| `docs/` (~31 md files) | **Triage**: remove docs that describe completed/abandoned work. |
| `fuseki_deploy_test/` | Fuseki-specific. **Mark experimental** or move under `deploy_docs/`. |
| `domain_schema/` | **Keep** — active schema files. |
| `generated_instances/` | **Move** to `domain_schema/generated/` or .gitignore. |
| `entity_registry/` | **Keep** — active tooling. |
| `agent_registry/` | Single migration script. **Move** to `scripts/`. |
| `tool_utils/` | **Move** into `vitalgraph/utils/` or delete if unused. |
| `bin/` | Shell entry points. **Keep**. |

### Target top-level structure (after cleanup)

```
vital-graph/
├── vitalgraph/              # Shipped package
│   ├── db/
│   │   ├── sparql_sql/      # PRIMARY backend (formally tested)
│   │   ├── fuseki/           # EXPERIMENTAL
│   │   ├── fuseki_postgresql/ # EXPERIMENTAL
│   │   ├── common/
│   │   └── ...
│   ├── endpoint/
│   ├── kg_impl/
│   ├── client/
│   ├── model/
│   └── ...
├── vitalgraph-jena-sidecar/  # Java sidecar (separate build)
├── tests/                    # ALL tests (formal, pytest)
│   ├── unit/
│   ├── conformance/
│   ├── integration/
│   ├── api/
│   ├── performance/
│   └── fixtures/
├── frontend/                 # Web UI
├── scripts/                  # Operational scripts (debug, migration, etc.)
├── docs/                     # Active documentation
├── domain_schema/            # Ontology schemas
├── entity_registry/          # Entity registry tooling
├── deploy_docs/              # Deployment guides
├── planning*/                # Planning docs (dev-only)
├── .github/                  # CI
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── README.md
└── LICENSE
```

This reduces the top-level from **~60 entries** to **~15–20**.

---

## Migration Strategy

### Phase 0 — Project Cleanup (Week 1)

1. **Delete empty/dead directories** — all items in the "remove" table above.
2. **Delete empty backend stubs** — tidb, aurora_postgresql, oxigraph.
3. **Add experimental READMEs** to fuseki, fuseki_postgresql backends.
4. **Move root-level stray files** (`.nq`, `.txt`, debug scripts) into
   appropriate subdirectories or delete.
5. **Consolidate `debug_scripts/` into `scripts/debug/`**.
6. **Move `sql_scripts/` into `scripts/sql/`**.
7. **Update `.gitignore`** — add `dist/`, `*.egg-info/`, `__pycache__/`,
   `registry_output/`, `registry_generated_vectors/`, etc.
8. **Archive `test_scripts/archive/`** — delete the ~90 archived scripts.
9. **Triage remaining `test_scripts/`** — tag each script as port/keep/delete.

### Phase 1 — Test Foundation (Week 2–3)

1. **Create `tests/` directory** with the structure above.
2. **Add root `conftest.py`** with markers, PostgreSQL connection fixtures,
   and a `temp_space` fixture that creates/drops a test space.
3. **Add `pyproject.toml` pytest config** — update `testpaths`, add markers.
4. **Port structural emit tests** from ad-hoc scripts to `tests/unit/sparql_sql/`.
5. **Create DAWG pytest wrapper** — parametrize existing runner output.
6. **Set up GitHub Actions CI** — run Tier 1 on every PR, Tier 2–3 on merge
   to main (with a PostgreSQL service container).

### Phase 2 — Unit Coverage (Week 3–4)

7. **Write unit tests for each `emit_*.py`** module.
8. **Write unit tests for `var_scope.py`**, `collect.py`, `ir.py`.
9. **Write unit tests for `sql_type_generation.py`** — XSD casts, companions.
10. **Write unit tests for optimizer passes** — filter pushdown, BGP reorder,
    union pruning.
11. **Target**: 80%+ line coverage on `vitalgraph/db/sparql_sql/`.

### Phase 3 — Integration Coverage (Week 5–6)

12. **Port best scripts from `test_scripts/`** to proper pytest tests under
    `tests/integration/`.
13. **Write quad round-trip and datatype fidelity tests**.
14. **Write KG CRUD integration tests** (entity, frame, slot, type, relation).
15. **Write concurrency tests** — parallel writers, pool exhaustion.
16. **Write schema lifecycle tests** — create, drop, recreate, index rebuild.

### Phase 4 — API & Performance (Week 7–8)

17. **Create Docker-based API test harness** — spin up server in CI.
18. **Port client test scripts** to pytest API tests.
19. **Create performance benchmark suite** with `pytest-benchmark`.
20. **Establish baseline metrics** from current WordNet dataset.

### Phase 5 — CI Hardening (Week 9–10)

21. **CI pipeline**: PR → Tier 1 (unit) + Tier 2 (conformance).
    Merge to main → Tier 3 (integration) + Tier 4 (API).
    Nightly → Tier 5 (performance).
22. **Coverage gating**: Fail PR if coverage drops below threshold.
23. **DAWG xfail audit**: Document every xfail with a tracking issue.
24. **Flaky test detection**: Run CI suite 3x, quarantine flaky tests.

---

## CI Pipeline Design

```yaml
# .github/workflows/test.yml (sketch)
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[test]"
      - run: pytest tests/unit/ -m unit --tb=short -q

  conformance:
    runs-on: ubuntu-latest
    needs: unit
    services:
      postgres:
        image: postgres:17
        env: { POSTGRES_DB: vitalgraph_test, POSTGRES_PASSWORD: test }
        ports: ["5432:5432"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[server,test]"
      - run: pytest tests/conformance/ -m conformance --tb=short -q

  integration:
    runs-on: ubuntu-latest
    needs: unit
    services:
      postgres:
        image: postgres:17
        env: { POSTGRES_DB: vitalgraph_test, POSTGRES_PASSWORD: test }
        ports: ["5432:5432"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[server,test]"
      - run: pytest tests/integration/ -m integration --tb=short -q
      - run: pytest --cov=vitalgraph/db/sparql_sql --cov-report=xml
      - uses: codecov/codecov-action@v4
```

---

## Fixture Design

### PostgreSQL connection (shared across Tier 2–4)

```python
# tests/conftest.py
import asyncio
import pytest
import asyncpg

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def db_pool():
    pool = await asyncpg.create_pool(
        host="localhost", port=5432,
        user="postgres", password="test",
        database="vitalgraph_test",
        min_size=2, max_size=10,
    )
    yield pool
    await pool.close()

@pytest.fixture
async def temp_space(db_pool):
    """Create a temporary space, yield its ID, drop it after test."""
    import uuid
    space_id = f"test_{uuid.uuid4().hex[:8]}"
    # ... create space tables via SparqlSQLSchema ...
    yield space_id
    # ... drop space tables ...
```

### DAWG parametrization

```python
# tests/conformance/test_dawg_bind.py
import pytest
from vitalgraph_sparql_sql.dawg_test_impl.dawg_test_runner import ...

cases = discover_dawg_cases(category="bind")

@pytest.mark.conformance
@pytest.mark.parametrize("case", cases, ids=lambda c: c.name)
def test_dawg_bind(case, dawg_executor):
    result = dawg_executor.run(case)
    if case.name in KNOWN_XFAILS:
        pytest.xfail(KNOWN_XFAILS[case.name])
    assert result.status == "PASS", result.error_message
```

---

## What We Trust PostgreSQL For (and don't re-test)

- SQL parsing and execution semantics
- Transaction isolation (SERIALIZABLE, READ COMMITTED)
- Index correctness (B-tree, GIN, GiST)
- COPY protocol
- Connection pooling (pgbouncer-level)
- Data durability and crash recovery
- Numeric precision (NUMERIC, DOUBLE PRECISION)
- String collation and Unicode handling
- EXPLAIN plan correctness

We test only what VitalGraph builds **on top** of PostgreSQL:
the SPARQL-to-SQL mapping, the RDF storage model, the KG abstractions,
and the REST API layer.

---

## Success Criteria

| Metric | Target |
|--------|--------|
| Unit test count | ≥ 150 |
| Unit test line coverage on `sparql_sql/` | ≥ 80% |
| DAWG P0 pass rate | ≥ 95% |
| Jena ARQ pass rate | ≥ 85% |
| Integration test count | ≥ 100 |
| API test count | ≥ 80 |
| CI run time (Tier 1–3) | < 15 min |
| Zero flaky tests in CI | 100% deterministic |
| Performance regression detection | ≤ 20% threshold |

---

## Open Questions for Discussion

1. **Jena sidecar dependency**: The V2 pipeline uses a Java sidecar for
   SPARQL parsing. Should CI start the sidecar in a container, or should
   we add a pure-Python SPARQL parser fallback for unit tests?

2. **Test database provisioning**: Ephemeral per-run (Docker service) vs.
   persistent dev database with per-test space isolation?

3. **DAWG test ownership**: Keep the custom runner as the source of truth
   and wrap it in pytest, or fully port each test to native pytest?

4. **Scope of API tests**: Test against Docker container (realistic but slow)
   or against in-process ASGI app via `httpx.ASGITransport` (fast but less
   realistic)?

5. **Performance baselines**: Use WordNet (~2.8M triples) as the standard
   benchmark dataset, or create a synthetic dataset for deterministic timing?

6. **Coverage tooling**: `pytest-cov` with Codecov, or a different reporting
   tool?

7. **What existing test scripts to keep vs. delete?** Many of the 130+ scripts
   in `test_scripts/` may be obsoleted once proper pytest tests exist.
