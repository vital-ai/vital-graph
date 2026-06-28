# Fuseki-PostgreSQL Backend: Async & Performance Optimization Plan

## Current State Assessment

### What's Already Async ✅

| Component | Driver | Status |
|-----------|--------|--------|
| Fuseki reads (SPARQL queries) | aiohttp | ✅ Fully async |
| Fuseki writes (SPARQL updates) | aiohttp | ✅ Fully async |
| PG writes (`store_quads_to_postgresql`) | asyncpg | ✅ Fully async |
| PG deletes (`remove_quads_from_postgresql`) | asyncpg | ✅ Fully async |
| PG transactions (`begin/commit/rollback`) | asyncpg | ✅ Fully async |
| PG connection pool | asyncpg.create_pool | ✅ Fully async |
| Signal manager (NOTIFY/LISTEN) | asyncpg | ✅ Fully async |

### What Blocks the Event Loop ⚠️

#### 1. Legacy sync psycopg in `fuseki_postgresql_space_terms.py`

The `FusekiPostgreSQLSpaceTerms` class has instance methods that use **sync psycopg** 
via `self.space_impl.core.get_dict_connection()`:

- `add_term()` — sync cursor.execute + cursor.fetchone (lines 141-160)
- `get_term_uuid()` — sync cursor.execute + cursor.fetchone (lines 201-205)
- `get_term_uuid_from_rdf_value()` — sync cursor.execute + cursor.fetchone (lines 252-256)
- `delete_term()` — sync cursor.execute (lines 296-316)
- `batch_lookup_term_uuids()` — sync cursor.execute + cursor.fetchall (lines 374-375)

**Impact**: These methods are NOT in the main write/read hot path. The main path uses 
`FusekiPostgreSQLSpaceTerms.generate_term_uuid()` (static, no DB call) and the asyncpg-based 
methods in `postgresql_db_impl.py`. However, these legacy methods could be called from 
utility/admin operations and would block the event loop.

**Files**: `vitalgraph/db/fuseki_postgresql/fuseki_postgresql_space_terms.py`

#### 2. CPU-bound VitalSigns conversions

VitalSigns operations (`vs.from_triples_list()`, `obj.to_rdf()`, `vs.to_jsonld()`) are 
CPU-bound and block the event loop between awaits. When N concurrent requests arrive, each 
request's CPU work prevents other requests' I/O operations from proceeding.

**Impact**: Under concurrent load, request latency increases linearly because CPU-bound 
work serializes on the single event loop thread.

**Files**:
- `vitalgraph/endpoint/kgentities_endpoint.py` — `_triples_to_vitalsigns()`, `_to_jsonld()`
- `vitalgraph/endpoint/kgframes_endpoint.py` — similar conversion methods
- `vitalgraph/utils/data_format_utils.py` — `batch_jsonld_to_graphobjects()`, `batch_graphobjects_to_quads()`

---

## Phase 1: Migrate Legacy Sync Term Methods to asyncpg

**Goal**: Eliminate all sync psycopg usage from the fuseki_postgresql backend.

**Scope**: `fuseki_postgresql_space_terms.py` — 5 instance methods

### Changes Required

1. **Remove `import psycopg.rows`** (line 5)

2. **Rewrite instance methods to use asyncpg** via `self.space_impl.postgresql_impl`:
   - Replace `self.space_impl.core.get_dict_connection()` → use asyncpg pool from `self.space_impl.postgresql_impl.connection_pool`
   - Replace `cursor.execute(sql, params)` → `conn.fetch(sql, *params)` or `conn.execute(sql, *params)`
   - Replace `%s` parameter placeholders → `$1, $2, ...` (asyncpg uses numbered params)
   - Remove manual `conn.commit()` calls (asyncpg auto-commits outside transactions)

3. **Method-by-method conversion**:

   | Method | Sync Calls | asyncpg Equivalent |
   |--------|-----------|-------------------|
   | `add_term()` | cursor.execute + fetchone | conn.fetchrow + conn.execute |
   | `get_term_uuid()` | cursor.execute + fetchone | conn.fetchrow |
   | `get_term_uuid_from_rdf_value()` | cursor.execute + fetchone | conn.fetchrow |
   | `delete_term()` | cursor.execute (x2) + fetchone | conn.fetchrow + conn.execute |
   | `batch_lookup_term_uuids()` | cursor.execute + fetchall | conn.fetch |

### Testing

- Run existing test suite to confirm no regressions
- Verify term CRUD operations still work via admin/utility paths
- Confirm no `psycopg` imports remain in `vitalgraph/db/fuseki_postgresql/`

---

## Phase 2: Offload CPU-Bound VitalSigns Work to Thread Pool

**Goal**: Prevent CPU-bound VitalSigns conversions from blocking the event loop.

**Pattern**: Wrap CPU-bound calls with `asyncio.to_thread()`:

```python
# Before (blocks event loop):
graph_objects = vs.from_triples_list(rdflib_triples)

# After (runs in thread pool, event loop stays free):
graph_objects = await asyncio.to_thread(vs.from_triples_list, rdflib_triples)
```

### Candidate Call Sites

| File | Method | CPU-bound call |
|------|--------|---------------|
| `kgentities_endpoint.py` | `_triples_to_vitalsigns()` | `vs.from_triples_list()` |
| `kgentities_endpoint.py` | response serialization | `obj.to_jsonld()` |
| `kgframes_endpoint.py` | `_triples_to_vitalsigns()` | `vs.from_triples_list()` |
| `kgframes_endpoint.py` | response serialization | `obj.to_jsonld()` |
| `data_format_utils.py` | `batch_jsonld_to_graphobjects()` | `vs.from_jsonld_list()` |
| `data_format_utils.py` | `batch_graphobjects_to_quads()` | `vs.to_triples_list()` |
| `kg_backend_utils.py` | `store_objects()` | `obj.to_rdf()` + graph.parse() |

### Considerations

- `asyncio.to_thread()` uses the default ThreadPoolExecutor (usually 5 × CPU cores)
- Each thread holds the GIL during Python execution, but releases it during I/O
- For VitalSigns (pure Python CPU work), benefit comes from allowing the event loop to 
  process other requests' I/O while one request's CPU work runs in a thread
- Thread safety: VitalSigns operations should be stateless per-call; verify no shared 
  mutable state

### Testing

- Load test with concurrent requests (N=5-10) to measure latency improvement
- Compare p50/p95 latency before and after
- Monitor thread pool utilization

---

## Phase 3: asyncpg Connection Pool Tuning

**Goal**: Optimize pool size for production workload.

### Current Configuration

```python
# fuseki_postgresql/postgresql_db_impl.py:90-98
self.connection_pool = await asyncpg.create_pool(
    host=..., port=..., database=..., user=..., password=...,
    min_size=1,
    max_size=10,
    command_timeout=60
)
```

### Tuning Parameters

| Parameter | Current | Recommended | Rationale |
|-----------|---------|-------------|-----------|
| `min_size` | 1 | 3-5 | Avoid connection creation latency on first requests |
| `max_size` | 10 | 15-20 | Support more concurrent write operations |
| `command_timeout` | 60 | 30 | Fail faster on stuck queries |
| `max_inactive_connection_lifetime` | default | 300 | Recycle stale connections |

### Make Configurable

Move pool settings to `vitalgraph-config.yaml`:

```yaml
fuseki_postgresql:
  postgresql:
    pool:
      min_size: 3
      max_size: 15
      command_timeout: 30
      max_inactive_connection_lifetime: 300
```

### Testing

- Monitor pool stats (`pool.get_size()`, `pool.get_idle_size()`) under load
- Watch for "pool exhausted" warnings
- Measure connection acquisition latency

---

## Priority Order

1. **Phase 2** (asyncio.to_thread) — highest impact, lowest risk
2. **Phase 3** (pool tuning) — easy win, config-only change
3. **Phase 1** (sync term migration) — correctness improvement, low urgency since methods aren't in hot path

## Already Completed ✅

- `asyncio.gather()` for parallel entity/frame fetches (4 files)
- Single-transaction `update_quads` to fix concurrent delete race condition
- Skip orphan cleanup during update_quads DELETE phase
