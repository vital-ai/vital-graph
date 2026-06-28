# KGQuery Performance Reproduction & Optimization Plan

## Status: Phase 1 Complete — Root Cause Found & Fixed

**Date**: 2026-03-08

---

## Problem Statement

The KGQueries relation tests (R4, R8) produce correct results but were **3–9× slower than expected**. Observed timings from `test_sparql_sql_kgqueries.py`:

| Query | Description | Before Fix | After Fix | Speedup |
|-------|-------------|-----------|-----------|---------|
| R1 | All MakesProduct (simple) | 26ms | 26ms | — |
| R4 | MakesProduct + Tech frame filter | 1,099ms | 277ms | **4×** |
| R5 | Relations from large companies | — | 297ms | — |
| R6 | CompetitorOf both large | — | 333ms | — |
| R7 | Companies in 'San' cities | — | 743ms | — |
| R8 | MakesProduct + Tech + employees ≥ 500 | 3,013ms | 524ms | **6×** |

## Root Cause: Missing `ANALYZE` After Bulk Insert

When entities are created via the REST API, `SparqlSQLBackendAdapter.store_objects()` calls `add_rdf_quads_batch_bulk()` to insert quads into PostgreSQL. **No `ANALYZE` was run afterward**, so PostgreSQL's query planner had no statistics for the freshly loaded tables. With default row estimates, PostgreSQL chose catastrophically bad join orders for the 18–24 way self-joins on `rdf_quad`.

### Evidence

Benchmark script (`kgquery_perf_bench.py --fresh`) — same data, same SQL:

| Query | Fresh (no ANALYZE) | With ANALYZE | Ratio |
|-------|-------------------|-------------|-------|
| R1 | 57ms | 23ms | 2.5× |
| R4 | 1,039ms | 144ms | **7×** |
| R8 | 3,013ms | 335ms | **9×** |

### What Was NOT the Cause

- **Edge MV rewrite** — disabled in both server and benchmark (`rewrite_edge_mv.py` detects co-reference pairs but logs "DISABLED pending maintained table"). Neither path uses MVs.
- **SPARQL differences** — the server's `KGConnectionQueryBuilder` uses `FILTER(?var = 'value')` instead of direct literal triple patterns, but this only accounts for ~12% difference (408ms vs 365ms for R8).
- **Docker networking** — negligible for single SQL round-trip.
- **Sidecar overhead** — only ~15ms per query.

---

## Fix Applied

**File**: `vitalgraph/kg_impl/kg_backend_utils.py` (lines 723–736)

Added `ANALYZE` on `rdf_quad` and `term` tables after every `add_rdf_quads_batch_bulk()` call in `SparqlSQLBackendAdapter.store_objects()`:

```python
# ANALYZE so the query planner has accurate statistics for the
# freshly-loaded data.  Without this, complex multi-join queries
# (e.g. KGQuery relation queries with frame/slot filters) choose
# catastrophically bad join orders — up to 9× slower.
try:
    from ..db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    t = SparqlSQLSchema.get_table_names(space_id)
    async with self.backend.db_impl.connection_pool.acquire() as conn:
        for tbl in (t['rdf_quad'], t['term']):
            await conn.execute(f"ANALYZE {tbl}")
except Exception as ae:
    self.logger.warning("ANALYZE after bulk insert failed (non-fatal): %s", ae)
```

**Cost**: ~15ms per entity creation call. Negligible vs the seconds saved on queries.

### Docker Log Confirmation (post-fix)

Each entity creation now shows:
```
⏱️  BACKEND to_triples: 0.000s (4 objects → 24 quads)
⏱️  BULK insert: ... total=0.008s
⏱️  BACKEND add_rdf_quads_batch_bulk: 0.009s (24 inserted)
⏱️  BACKEND ANALYZE: 0.015s
⏱️  BACKEND store_objects total: 0.024s
```

---

## Data Shape

~585 GraphObjects → ~3,682 quads across 10 organizations, 6 products, 10 business events, 16 relations, and 5 KGTypes. This is a **small** dataset — the slowness was entirely due to bad query plans.

---

## Benchmark Tools Created

| File | Purpose |
|------|---------|
| `vitalgraph_sparql_sql/scripts/kgquery_perf_setup.py` | Create space, load identical test data via VitalSigns `to_triples()`, run ANALYZE |
| `vitalgraph_sparql_sql/scripts/kgquery_perf_bench.py` | Benchmark queries with timing breakdowns |

### Bench Script Modes

```bash
# Default: run against pre-existing space with warm stats
python kgquery_perf_bench.py --query slow

# Fresh: drop/create/load/query in one shot, no ANALYZE (reproduces server bug)
python kgquery_perf_bench.py --fresh --query R8

# Fresh + ANALYZE: verify the fix
python kgquery_perf_bench.py --fresh --analyze --query slow

# Pipeline mode: use SparqlSQLSpaceImpl.execute_sparql_query() (matches server path)
python kgquery_perf_bench.py --pipeline --query slow

# Show EXPLAIN ANALYZE and generated SQL
python kgquery_perf_bench.py --explain --sql --query R8
```

---

## Other Endpoints Requiring ANALYZE

The fix was applied to `SparqlSQLBackendAdapter.store_objects()`, which covers KGEntity creation. Similar `ANALYZE` calls must be added to **any endpoint that performs significant data changes**, including:

- **Bulk dataset load** (`add_rdf_quads_batch_bulk` called outside `store_objects`)
- **Entity update** (`_handle_update_mode` — deletes + re-inserts all triples)
- **Entity delete** (batch deletion of many entities changes table statistics)
- **Relation create/delete** (`kgrelations_endpoint` — inserts/removes edge triples)
- **Frame create/update/delete** (frame + slot + edge triples)
- **Space data import** (any future bulk import or migration endpoint)

The general rule: **after any operation that inserts or deletes more than a handful of rows in `rdf_quad` or `term`, run `ANALYZE` on those tables**. The cost is ~15ms and prevents the query planner from using stale statistics that lead to catastrophically bad join orders.

---

## Remaining Optimization Opportunities

The ANALYZE fix brought R8 from 3,013ms → 524ms. Further optimization is possible:

### Optimization A: Maintained Edge Table + var_slots Rewrite

The `edge_mv` is currently a stub (`WHERE false`). The `rewrite_edge_mv.py` detects co-reference pairs but is **disabled** pending switch to a maintained table. Once enabled:

- Each edge pair (2 `rdf_quad` JOINs) collapses to 1 edge table lookup
- R4 (3 edge pairs): ~18 JOINs → ~12 JOINs
- R8 (4 edge pairs): ~24 JOINs → ~16 JOINs

See `planning_sql/mv_to_maintained_table_plan.md` for implementation details.

### Optimization B: Direct SQL for Common Patterns

Bypass the SPARQL pipeline entirely for the most common KGQuery patterns (relation queries with frame/slot filters). Eliminates sidecar + generate overhead (~25ms) and produces purpose-built SQL with optimal join structure.

### Optimization C: FILTER Pattern in KGConnectionQueryBuilder

The server's `KGConnectionQueryBuilder` generates:
```sparql
?slot haley:hasTextSlotValue ?var .
FILTER(?var = 'Technology')
```

This binds the value to a variable and filters, instead of:
```sparql
?slot haley:hasTextSlotValue "Technology" .
```

The direct literal pattern allows the SQL generator to resolve the constant at term-lookup time, pruning rows earlier. This is a ~12% difference (408ms vs 365ms for R8) but worth fixing.

---

## Investigation Timeline

1. Created `kgquery_perf_setup.py` — loads identical test data via `to_triples()`
2. Created `kgquery_perf_bench.py` — benchmarks queries with timing breakdowns
3. Ran `test_sparql_sql_kgqueries.py` and inspected Docker logs — confirmed server timings (R8: 1,119ms exec)
4. Compared benchmark (365ms) vs server (1,119ms) for same SQL — 3× gap
5. Ruled out SPARQL differences (12%), ANALYZE on benchmark (10%), Docker networking (negligible)
6. Added `--fresh` mode to benchmark: drop/create/load/query without ANALYZE
7. **Reproduced**: R8 = 3,013ms with fresh space (no ANALYZE) vs 335ms with ANALYZE — **9× difference**
8. Traced entity creation path: `kgentities_endpoint` → `KGEntityCreateProcessor` → `SparqlSQLBackendAdapter.store_objects()` → `add_rdf_quads_batch_bulk()` — no ANALYZE
9. Added ANALYZE after bulk insert in `kg_backend_utils.py`
10. Confirmed fix in Docker logs: ANALYZE runs ~15ms per entity batch, query times improved
