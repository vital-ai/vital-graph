# Testing Plan — Tier 3: Integration Tests (needs PG)

> Split from [testing_plan.md](testing_plan.md). See main doc for overall
> architecture, CI pipeline, fixtures, and migration strategy.

## Purpose

Verify end-to-end behavior through the real `SparqlSQLDbImpl`
against a real PostgreSQL instance.

## Approach

- Use a **dedicated test database** (e.g., `vitalgraph_test`) created/destroyed
  per session.
- Each test module creates a temporary space, loads data, runs operations,
  validates results, and drops the space.
- Fixtures manage the asyncpg pool lifecycle.

## Key test areas

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

---

## Implementation Progress

**Infrastructure** (`tests/integration/`):
- `conftest.py` — async fixtures for PG connection pool (`pg_pool`, `pg_conn`), ephemeral
  test space creation/teardown (`test_space`), SPARQL execution helpers (`sparql_execute`,
  `sparql_update`, `sparql_query_sql`), and KG-level fixtures (`space_impl` — session-scoped
  `SparqlSQLSpaceImpl`, `backend_adapter` — per-test `SparqlSQLBackendAdapter`).
  Auto-skips if PG or Jena sidecar unreachable.
- Uses `pytest-asyncio` 1.0+ `loop_scope="session"` to share one event loop across
  session-scoped pool and module-scoped space fixtures.
- All test spaces use `inttest_` prefix. System/global spaces (`sp_kg_types`, `dawg_test`)
  are documented as protected and never touched.

**Test files** (`tests/integration/`):

| File | Tests | What it validates |
|------|-------|-------------------|
| `test_sparql_roundtrip.py` | 13 | INSERT DATA + SELECT roundtrip: URI triples, typed literals (int/string), OPTIONAL, DELETE DATA, UNION, aggregation (COUNT/SUM), LIMIT/OFFSET, DISTINCT, BIND |
| `test_datatype_fidelity.py` | 17 (4 xfail) | XSD numeric types (integer/decimal/double/float), booleans, date/dateTime, lang-tagged strings (xfail: UUID mismatch bug), xsd:string, Unicode (CJK/emoji), special chars (quotes/backslash) |
| `test_schema_lifecycle.py` | 6 | Space create/drop table verification, `space_tables_exist` check, datatype seeding, space isolation (data invisible across spaces), index creation |
| `test_graph_operations.py` | 5 | Named graph INSERT+SELECT, default vs named graph isolation, multi-triple named graph, DELETE from named graph |
| `test_concurrency.py` | 5 (2 xfail) | Parallel INSERT DATA (xfail: term race), concurrent read+write safety, pool exhaustion (20 parallel), pool recovery after burst |
| `test_bulk_load.py` | 6 | 100-triple batch insert, individual query, multi-predicate bulk, mixed URI+literal bulk, sequential batch accumulation, batch filtering |
| `test_kg_crud.py` | 14 | KGEntity full lifecycle (create/exists/get/delete), batch entities, frame CRUD, slot CRUD, entity graph (entity+frame+slot+edges), graph isolation |
| **Total** | **66** | **60 pass, 6 xfail — ~9s runtime** |

## Discovered bugs (recorded in `issues/`)

1. **`001_emit_update_lang_uuid_mismatch.md`** — Lang-tagged literal INSERT generates
   mismatched UUIDs between term table and quad object_uuid, making data unqueryable.
   Severity: High.
2. **`002_drop_space_residual_tables.md`** — `drop_space()` leaves `_fts_document_segments`
   and `_search_mapping_index` tables behind. Severity: Low.
3. **`003_concurrent_insert_term_race.md`** — Concurrent INSERT DATA hits
   `UniqueViolationError` on term table due to `WHERE NOT EXISTS` race. Fix:
   use `ON CONFLICT DO NOTHING`. Severity: Medium.
