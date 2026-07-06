# VitalGraph Formal Testing Plan

> **Document structure**: This is the main index document. Detailed per-tier
> plans are split into separate files:
>
> - [Tier 1 — Unit Tests](testing_plan_tier1.md)
> - [Tier 2 — SPARQL Conformance](testing_plan_tier2.md)
> - [Tier 3 — Integration Tests](testing_plan_tier3.md)
> - [Tier 4 — API / E2E Tests](testing_plan_tier4.md)
> - [Tier 5 — Performance Tests](testing_plan_tier5.md)

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

- ~~**No pytest infrastructure** — no `conftest.py`, no fixtures, no markers.~~ ✅ DONE (326 tests, `tests/conftest.py`, fixtures, markers)
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

## Tier Summary

| Tier | Purpose | Tests | Status | Details |
|------|---------|-------|--------|---------|
| 1 | Unit tests (no DB) — IR, optimizer passes, expressions, types | 1018 | ✅ Complete | [testing_plan_tier1.md](testing_plan_tier1.md) |
| 2 | SPARQL conformance (DAWG + pyoxigraph) | 245 | ✅ 91.2% pass | [testing_plan_tier2.md](testing_plan_tier2.md) |
| 3 | Integration (needs PG) — roundtrip, CRUD, concurrency | 66 | ✅ 60 pass, 6 xfail | [testing_plan_tier3.md](testing_plan_tier3.md) |
| 4 | API / E2E (needs server) — all REST endpoints | 237 | ✅ All pass | [testing_plan_tier4.md](testing_plan_tier4.md) |
| 5 | Performance benchmarks | 0 | ❌ Not started | [testing_plan_tier5.md](testing_plan_tier5.md) |

**Grand total: 1566 tests.**

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

> **⚠️ Update (2026-06-28):** Many of the directories listed below have already
> been **moved** (not reviewed or ported) into `test_scripts/` as subdirectories
> during prior cleanup passes. The scripts were relocated as-is and still need
> to be reviewed, triaged, and ported to the formal `tests/` structure.
> The moves may have **broken hardcoded paths** in those scripts (e.g.,
> `sys.path.insert`, relative file references, config file paths). Any triage
> of `test_scripts/` should include checking and fixing import paths.
>
> Directories already consolidated into `test_scripts/`:
> - `test_scripts_misc/` → `test_scripts/misc/`
> - `test_script_kg_impl/` → `test_scripts/kg_impl/`
> - `test_sparql/` → `test_scripts/sparql/`
> - `test_client_api/` → `test_scripts/client_api/`
> - `vitalgraph_client_test/` → `test_scripts/vitalgraph_client/`
> - `vitalgraph_mock_client_test/` → `test_scripts/mock_client/`
> - `vitalgraph_service_tests/` → `test_scripts/service/`
> - `vitalsigns_test_scripts/` → `test_scripts/vitalsigns/`
> - `scripts/query_entity_graph_leftovers.py` → `test_scripts/` (root)
>
> Directories already deleted:
> - `test_sparql_sql_endpoints/` (was empty)
> - `test_vs/` (was single file)
> - `localTestFiles/`
>
> `test_scripts/` now contains **~793 files** across these subdirectories.
> The formal `tests/` directory has not been created yet.

Original plan (updated with current locations):

| Current location | Action |
|-----------------|--------|
| `test_scripts/` (root, ~130 scripts) | **Triage**: port valuable ones to `tests/integration/` or `tests/conformance/`, delete the rest. `test_scripts/archive/` (~90 scripts) can be deleted outright. |
| `test_scripts/misc/` (was `test_scripts_misc/`, ~40 scripts) | **Triage**: port or delete. |
| `test_scripts/kg_impl/` (was `test_script_kg_impl/`) | **Port** orchestrator-based KG tests to `tests/integration/kg/`. |
| `test_scripts/sparql/` (was `test_sparql/`) | **Move** fixtures/utils into `tests/conformance/`. |
| `test_scripts/client_api/` (was `test_client_api/`) | **Port** to `tests/api/`. |
| `test_scripts/vitalgraph_client/` (was `vitalgraph_client_test/`, ~70 scripts) | **Port** valuable scripts to `tests/api/` and `tests/integration/`. |
| `test_scripts/mock_client/` (was `vitalgraph_mock_client_test/`, ~30 scripts) | **Port** to `tests/integration/mock/`. |
| `test_scripts/service/` (was `vitalgraph_service_tests/`) | **Port** to `tests/integration/service/`. |
| `test_scripts/vitalsigns/` (was `vitalsigns_test_scripts/`) | **Port** to `tests/unit/vitalsigns/` or delete. |
| `test_files/` (~40 PDFs) | Test fixtures. **Move** to `tests/fixtures/files/` or .gitignore if too large. |
| `test_files_download/` | **Delete** or .gitignore. |

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

> **Approach note:** Build the new `tests/` structure first, drawing from and
> referencing existing scripts in `test_scripts/` as needed. New tests may copy
> patterns, queries, or data from existing scripts but should be written as
> proper pytest tests from the start. **Do not delete or reorganize
> `test_scripts/` until the new `tests/` suite is implemented and working.**
> Once the formal test suite covers the same ground, we can triage
> `test_scripts/` — archiving or deleting scripts that are now redundant.

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

| Metric | Target | Current |
|--------|--------|---------|
| Unit test count | ≥ 150 | ✅ 1018 |
| Unit test line coverage on `sparql_sql/` | ≥ 80% | 44% overall; emit handlers avg 92% |
| DAWG P0 pass rate | ≥ 95% | 91.2% (pyoxigraph baseline) |
| Jena ARQ pass rate | ≥ 85% | — |
| Integration test count | ≥ 100 | 66 (60 pass, 6 xfail) |
| API test count | ≥ 80 | ✅ 213 |
| CI run time (Tier 1–3) | < 15 min | ✅ 0.94s (Tier 1+2) |
| Zero flaky tests in CI | 100% deterministic | ✅ (Tier 1) |
| Performance regression detection | ≤ 20% threshold | — |

---

## Implementation Progress

> **Moved to per-tier files.** See the individual tier documents for detailed
> implementation progress, test file listings, and discovered bugs.

---

## Open Questions for Discussion

1. ~~**Jena sidecar dependency**: The V2 pipeline uses a Java sidecar for
   SPARQL parsing. Should CI start the sidecar in a container, or should
   we add a pure-Python SPARQL parser fallback for unit tests?~~
   **RESOLVED**: Generate-once approach — sidecar JSON fixtures are captured
   once and committed; tests reconstruct PlanV2 trees via pure Python.
   Sidecar is only needed to regenerate fixtures.

2. ~~**Test database provisioning**: Ephemeral per-run (Docker service) vs.
   persistent dev database with per-test space isolation?~~
   **RESOLVED**: Per-test space isolation using `inttest_` prefixed ephemeral
   spaces against the dev database. Tests auto-skip without PG. CI can use
   Docker service container.

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
