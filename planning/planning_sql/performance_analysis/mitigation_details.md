# Mitigation Implementation Details

Companion to `100x_scalability_analysis.md`. Provides concrete SQL, code
snippets, and PG configuration for each proposed mitigation.

---

## 1. Missing Composite Indexes (Phase 1, #1-2)

Add to `sparql_sql_schema.py` `create_space_indexes_sql()`:

```sql
-- Graph-scoped predicate lookup (most common query pattern)
CREATE INDEX IF NOT EXISTS idx_{space}_quad_ctx_pred
  ON {space}_rdf_quad (context_uuid, predicate_uuid);

-- Graph-scoped subject lookup (entity deletion, subject existence)
CREATE INDEX IF NOT EXISTS idx_{space}_quad_ctx_subj
  ON {space}_rdf_quad (context_uuid, subject_uuid);
```

**Expected impact**: Queries with `WHERE context_uuid = $1 AND predicate_uuid = $2`
go from index scan + heap filter to direct index-only lookup. At 1B rows,
reduces from **minutes** (scanning millions of heap pages) to **~5ms** per lookup.

**Storage cost**: ~1B × 32 bytes × 2 indexes ≈ **64 GB** additional. This is
substantial but mandatory — without these indexes, graph-scoped queries at 1B
rows are unusable.

---

## 2. Cap Term Cache with LRU (Phase 1, #3)

In `generator.py`, replace the unbounded dict:

```python
# Current:
_term_cache: Dict[tuple, str] = {}

# Proposed:
from cachetools import LRUCache
_TERM_CACHE_MAX = 50_000
_term_cache: LRUCache = LRUCache(maxsize=_TERM_CACHE_MAX)
```

If adding a dependency is undesirable, use `collections.OrderedDict`:

```python
from collections import OrderedDict

_TERM_CACHE_MAX = 50_000

class _LRUTermCache(OrderedDict):
    def __getitem__(self, key):
        self.move_to_end(key)
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > _TERM_CACHE_MAX:
            self.popitem(last=False)

_term_cache = _LRUTermCache()
```

`invalidate_term_cache()` continues to work unchanged since both implementations
support `.clear()` and dict-style iteration.

---

## 3. Cap Stats Load Query (Phase 1, #4)

In `generator.py` `_load_quad_stats()`, add a LIMIT:

```python
# Current:
quad_rows = await db.execute_query(
    f"SELECT predicate_uuid::text, object_uuid::text, row_count "
    f"FROM {space_id}_rdf_stats "
    f"WHERE row_count >= 2 AND row_count <= 200000",
    conn_params=conn_params, conn=conn,
)

# Proposed:
quad_rows = await db.execute_query(
    f"SELECT predicate_uuid::text, object_uuid::text, row_count "
    f"FROM {space_id}_rdf_stats "
    f"WHERE row_count >= 2 AND row_count <= 200000 "
    f"ORDER BY row_count ASC "
    f"LIMIT 10000",
    conn_params=conn_params, conn=conn,
)
```

The `ORDER BY row_count ASC` prioritizes low-cardinality pairs (most selective),
which is what the join reorder heuristic values most. Requires an index:

```sql
CREATE INDEX IF NOT EXISTS idx_{space}_rdf_stats_rc
  ON {space}_rdf_stats (row_count);
```

---

## 4. Reduce MAX_PATH_DEPTH (Phase 1, #5)

In `emit_path.py`:

```python
# Current:
MAX_PATH_DEPTH = 100

# Proposed:
MAX_PATH_DEPTH = 5  # Configurable via ctx or space settings
```

For production deployments, consider making this configurable per-query via a
SPARQL pragma or per-space configuration.

---

## 5. PostgreSQL Configuration Recommendations (Phase 1, #6)

For a server with **128 GB RAM** and NVMe storage serving 1B-row spaces
(minimum viable configuration at this scale):

```ini
# Memory
shared_buffers = 32GB
effective_cache_size = 96GB
work_mem = 256MB                # Careful: per-sort/hash per query
hash_mem_multiplier = 8.0       # PG 15+: let hash joins use more
maintenance_work_mem = 4GB
huge_pages = on                 # Mandatory at this scale

# Planner
default_statistics_target = 500
random_page_cost = 1.1          # NVMe storage
effective_io_concurrency = 200  # NVMe storage
join_collapse_limit = 8         # Keep default
geqo_threshold = 12

# Parallel query
max_parallel_workers_per_gather = 4
max_parallel_workers = 8
parallel_tuple_cost = 0.01
parallel_setup_cost = 100

# Write performance
wal_buffers = 256MB
checkpoint_completion_target = 0.9
max_wal_size = 16GB
min_wal_size = 4GB

# Safety limits
temp_file_limit = 100GB         # Prevent runaway queries filling disk
statement_timeout = 120s        # Kill queries after 2 minutes
idle_in_transaction_session_timeout = 60s

# Autovacuum (tuned for billion-row tables)
autovacuum_vacuum_scale_factor = 0.01     # 1% — trigger at 10M changes
autovacuum_analyze_scale_factor = 0.005   # 0.5% — trigger at 5M changes
autovacuum_vacuum_cost_delay = 2ms        # Faster vacuuming
autovacuum_work_mem = 2GB                 # Dedicated vacuum memory
```

Per-table statistics targets (run once after migration):

```sql
ALTER TABLE {space}_rdf_quad
  ALTER COLUMN predicate_uuid SET STATISTICS 1000,
  ALTER COLUMN subject_uuid SET STATISTICS 1000,
  ALTER COLUMN context_uuid SET STATISTICS 500,
  ALTER COLUMN object_uuid SET STATISTICS 500;

ALTER TABLE {space}_term
  ALTER COLUMN term_type SET STATISTICS 10;  -- only 4 values
```

---

## 6. Remove quad_uuid from PK (Phase 2, #7)

Migration SQL:

```sql
-- Step 1: Drop old PK
ALTER TABLE {space}_rdf_quad DROP CONSTRAINT {space}_rdf_quad_pkey;

-- Step 2: Create new UNIQUE constraint (deduplication)
ALTER TABLE {space}_rdf_quad
  ADD CONSTRAINT {space}_rdf_quad_uniq
  UNIQUE (subject_uuid, predicate_uuid, object_uuid, context_uuid);

-- Step 3: Add surrogate PK (optional, for foreign key references)
ALTER TABLE {space}_rdf_quad ADD COLUMN id BIGSERIAL;
ALTER TABLE {space}_rdf_quad ADD PRIMARY KEY (id);

-- Step 4: REINDEX (rebuilds all indexes with new physical layout)
REINDEX TABLE {space}_rdf_quad;
ANALYZE {space}_rdf_quad;
```

**Space savings**: ~16 bytes per PK entry × 1B rows = **16 GB** less PK index.
**Insert speedup**: ~20% faster ON CONFLICT probes (4-column vs 5-column
comparison). At 1B rows where every probe is disk-bound, this is significant.

**Risk**: If any application code relies on `quad_uuid` as a unique identifier,
it must be updated to use the 4-column natural key or the new surrogate PK.

---

## 7. COPY-Based Bulk Insert (Phase 2, #8)

Replace `executemany` in `add_rdf_quads_batch_bulk` with `copy_records_to_table`:

```python
# Current:
await conn.executemany(
    f"INSERT INTO {t['term']} "
    f"(term_uuid, term_text, term_type, lang, datatype_id) "
    f"VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING",
    term_args,
)

# Proposed:
# Use a staging table to get COPY speed + ON CONFLICT dedup
await conn.execute(
    f"CREATE TEMP TABLE _staging_term (LIKE {t['term']} INCLUDING NOTHING) "
    f"ON COMMIT DROP"
)
await conn.copy_records_to_table(
    '_staging_term',
    records=term_args,
    columns=['term_uuid', 'term_text', 'term_type', 'lang', 'datatype_id'],
)
await conn.execute(
    f"INSERT INTO {t['term']} "
    f"SELECT * FROM _staging_term "
    f"ON CONFLICT DO NOTHING"
)
```

Same pattern for quads:

```python
await conn.execute(
    f"CREATE TEMP TABLE _staging_quad (LIKE {t['rdf_quad']} INCLUDING NOTHING) "
    f"ON COMMIT DROP"
)
await conn.copy_records_to_table(
    '_staging_quad',
    records=quad_rows,
    columns=['subject_uuid', 'predicate_uuid', 'object_uuid', 'context_uuid'],
)
await conn.execute(
    f"INSERT INTO {t['rdf_quad']} "
    f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
    f"SELECT * FROM _staging_quad "
    f"ON CONFLICT DO NOTHING"
)
```

**Expected speedup**: 5-10× for batches of 10K+ rows.

---

## 8. Batch Edge/Frame-Entity Sync (Phase 2, #9)

In `sync_edge_table.py`, chunk the `ANY($3)` array:

```python
SYNC_CHUNK_SIZE = 10_000

async def sync_edge_table_after_insert(conn, space_id, subject_uuids):
    if not subject_uuids:
        return 0
    total = 0
    for i in range(0, len(subject_uuids), SYNC_CHUNK_SIZE):
        chunk = subject_uuids[i:i + SYNC_CHUNK_SIZE]
        result = await conn.execute(
            f"INSERT INTO {edge_table} ..."
            f"WHERE src.subject_uuid = ANY($3) ...",
            ..., chunk,
        )
        total += int(result.split()[-1]) if result else 0
    return total
```

---

## 9. DELETE ... RETURNING for Stats (Phase 2, #10)

Replace the read-before-delete pattern:

```python
# Current (two queries):
rows = await conn.fetch(
    f"SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid "
    f"FROM {t_quad} WHERE subject_uuid = ANY($1) AND context_uuid = $2",
    subject_uuids, context_uuid,
)
await sync_stats_after_delete(conn, space_id, quad_rows)
await conn.execute(
    f"DELETE FROM {t_quad} WHERE subject_uuid = ANY($1) AND context_uuid = $2",
    subject_uuids, g_uuid,
)

# Proposed (one query):
rows = await conn.fetch(
    f"DELETE FROM {t_quad} "
    f"WHERE subject_uuid = ANY($1) AND context_uuid = $2 "
    f"RETURNING subject_uuid, predicate_uuid, object_uuid, context_uuid",
    subject_uuids, g_uuid,
)
quad_rows = [(r['subject_uuid'], r['predicate_uuid'],
              r['object_uuid'], r['context_uuid']) for r in rows]
await sync_stats_after_delete(conn, space_id, quad_rows)
```

**Note**: Edge and frame_entity sync must still happen BEFORE the delete (they
query rdf_quad for relationship data). Only the stats sync can be moved after.

---

## 10. LIMIT Push-Through for Term JOINs (Phase 2, #11)

When a SLICE (LIMIT) node wraps a BGP, defer term JOINs past the LIMIT:

```sql
-- Current (term JOINs before LIMIT):
SELECT t_v0.term_text AS v0, t_v1.term_text AS v1
FROM (
  SELECT q0.subject_uuid AS v0__uuid, q0.object_uuid AS v1__uuid
  FROM rdf_quad q0 WHERE ...
) AS sub
JOIN term AS t_v0 ON sub.v0__uuid = t_v0.term_uuid
JOIN term AS t_v1 ON sub.v1__uuid = t_v1.term_uuid
LIMIT 10

-- Proposed (LIMIT before term JOINs):
SELECT t_v0.term_text AS v0, t_v1.term_text AS v1
FROM (
  SELECT q0.subject_uuid AS v0__uuid, q0.object_uuid AS v1__uuid
  FROM rdf_quad q0 WHERE ...
  LIMIT 10
) AS sub
JOIN term AS t_v0 ON sub.v0__uuid = t_v0.term_uuid
JOIN term AS t_v1 ON sub.v1__uuid = t_v1.term_uuid
```

This means only 10 term lookups instead of potentially **hundreds of millions**
of term lookups (into a 28 GB heap) followed by discarding all but 10 results. Implementation requires `emit_slice.py` to
detect when its child is a BGP and push the limit into the inner query.

**Caveat**: Cannot push LIMIT past ORDER BY (PostgreSQL needs all rows to sort).
Can push past bare BGP or BGP + FILTER.

---

## 11. Partial GIN Index (Phase 2, #12)

```sql
-- Current:
CREATE INDEX idx_{space}_term_trgm
  ON {space}_term USING gin (term_text gin_trgm_ops);

-- Proposed:
DROP INDEX IF EXISTS idx_{space}_term_trgm;
CREATE INDEX idx_{space}_term_trgm
  ON {space}_term USING gin (term_text gin_trgm_ops)
  WHERE term_type = 'L';
```

URIs are always looked up by exact match (via `term_uuid` PK). Only literals
need text search (CONTAINS, REGEX). This reduces GIN index size by ~60% (URIs
are typically ~60% of terms) and proportionally reduces maintenance cost.

**Requires**: Update `filter_pushdown.py` semi-join subqueries to add
`AND term_type = 'L'` when the filter target is known to be a literal.

---

## 12. Hash-Partitioning rdf_quad (Phase 3, #13)

```sql
-- Create partitioned table
CREATE TABLE {space}_rdf_quad (
    subject_uuid   UUID NOT NULL,
    predicate_uuid UUID NOT NULL,
    object_uuid    UUID NOT NULL,
    context_uuid   UUID NOT NULL,
    quad_uuid      UUID NOT NULL DEFAULT gen_random_uuid(),
    dataset        VARCHAR(50) NOT NULL DEFAULT 'primary'
) PARTITION BY HASH (context_uuid);

-- Create partitions (16 is a good starting point)
CREATE TABLE {space}_rdf_quad_p0  PARTITION OF {space}_rdf_quad FOR VALUES WITH (MODULUS 16, REMAINDER 0);
CREATE TABLE {space}_rdf_quad_p1  PARTITION OF {space}_rdf_quad FOR VALUES WITH (MODULUS 16, REMAINDER 1);
...
CREATE TABLE {space}_rdf_quad_p15 PARTITION OF {space}_rdf_quad FOR VALUES WITH (MODULUS 16, REMAINDER 15);
```

**Benefit**: With 256 partitions at 1B total rows, each partition has ~4M rows.
Indexes on each partition are ~**400 MB** — small enough to fit in
`shared_buffers`. Queries with `WHERE context_uuid = $1` prune to a single
partition (if using LIST partitioning by graph), turning a 120 GB table scan
into a 500 MB partition scan.

With 16 partitions (simpler), each partition has ~62M rows with ~6 GB of indexes
— still a massive improvement over a single 420 GB index set.

**Alternative**: LIST partitioning by known graph URIs is even better for spaces
with a small number of named graphs, as it enables exact partition pruning.

**Trade-off**: Hash partitioning doesn't help queries without a `context_uuid`
filter — those scan all partitions. For SPARQL queries without GRAPH clauses,
this adds overhead.

---

## 13. Covering Indexes (Phase 3, #14)

```sql
-- Enable index-only scans for the inner BGP query
CREATE INDEX idx_{space}_quad_pred_covering
  ON {space}_rdf_quad (predicate_uuid)
  INCLUDE (subject_uuid, object_uuid, context_uuid);

CREATE INDEX idx_{space}_quad_ctx_pred_covering
  ON {space}_rdf_quad (context_uuid, predicate_uuid)
  INCLUDE (subject_uuid, object_uuid);
```

**Benefit**: The inner BGP query only needs UUID columns. With a covering index,
PostgreSQL can satisfy the query entirely from the index without touching the
heap. This eliminates random heap I/O — the biggest performance killer at scale.

**Cost**: ~1B × 64 bytes × 2 ≈ **128 GB** additional index storage. This is
substantial, but covering indexes **replace** the need for some existing
single-column indexes. Drop `(predicate_uuid)` and `(context_uuid)` standalone
indexes after adding their covering equivalents to net ~**64 GB** additional.

At 1B rows, index-only scans are not optional — they are the difference between
sub-second and multi-minute query times.

**Note**: Covering indexes require PostgreSQL 11+.

---

## 14. Read Replica Configuration (Phase 4, #20)

### PostgreSQL Streaming Replication Setup

On the **primary**:
```ini
# postgresql.conf
wal_level = replica
max_wal_senders = 10
max_replication_slots = 10
hot_standby = on
```

```sql
-- Create replication slot (prevents WAL cleanup before replica catches up)
SELECT pg_create_physical_replication_slot('replica_1');
```

On each **replica**:
```ini
# postgresql.conf
hot_standby = on
hot_standby_feedback = on      # Prevents vacuum from removing rows needed by replica queries
max_standby_streaming_delay = 30s  # Allow long replica queries
```

### VitalGraph Dual-Pool Implementation

In `db_provider.py`, add read/write pool routing:

```python
import asyncpg

class DualPoolProvider:
    """Routes reads to replicas, writes to primary."""

    def __init__(self, primary_dsn: str, replica_dsns: list[str],
                 primary_pool_size: int = 10, replica_pool_size: int = 20):
        self._primary_dsn = primary_dsn
        self._replica_dsns = replica_dsns
        self._primary_pool_size = primary_pool_size
        self._replica_pool_size = replica_pool_size
        self._primary_pool: asyncpg.Pool | None = None
        self._replica_pools: list[asyncpg.Pool] = []
        self._replica_idx = 0

    async def initialize(self):
        self._primary_pool = await asyncpg.create_pool(
            self._primary_dsn,
            min_size=2, max_size=self._primary_pool_size,
            command_timeout=30,
        )
        for dsn in self._replica_dsns:
            pool = await asyncpg.create_pool(
                dsn,
                min_size=2, max_size=self._replica_pool_size,
                command_timeout=120,
            )
            self._replica_pools.append(pool)

    def get_read_pool(self) -> asyncpg.Pool:
        """Round-robin across replica pools."""
        if not self._replica_pools:
            return self._primary_pool  # Fallback if no replicas
        pool = self._replica_pools[self._replica_idx % len(self._replica_pools)]
        self._replica_idx += 1
        return pool

    def get_write_pool(self) -> asyncpg.Pool:
        return self._primary_pool
```

**Integration points**:
- `execute_sparql_query` → `get_read_pool()`
- `add_rdf_quads_batch_bulk`, `delete_entity_graph_bulk` → `get_write_pool()`
- `generate_sql` (which calls `materialize_constants`) → `get_read_pool()`
  (it only reads term/stats tables)

---

## 15. Space-Level Sharding (Phase 4, #23)

### Shard Registry

```python
import asyncpg
from typing import Dict

class ShardRegistry:
    """Maps space_id → connection pool for space-level sharding."""

    def __init__(self):
        self._shard_map: Dict[str, asyncpg.Pool] = {}
        self._shard_pools: Dict[str, asyncpg.Pool] = {}  # dsn → pool

    async def register_shard(self, shard_dsn: str, pool_size: int = 20):
        """Create a pool for a new shard."""
        if shard_dsn not in self._shard_pools:
            self._shard_pools[shard_dsn] = await asyncpg.create_pool(
                shard_dsn, min_size=2, max_size=pool_size,
            )
        return self._shard_pools[shard_dsn]

    def assign_space(self, space_id: str, shard_dsn: str):
        """Assign a space to a shard."""
        pool = self._shard_pools.get(shard_dsn)
        if not pool:
            raise ValueError(f"Shard {shard_dsn} not registered")
        self._shard_map[space_id] = pool

    def get_pool(self, space_id: str) -> asyncpg.Pool:
        """Get the connection pool for a space."""
        pool = self._shard_map.get(space_id)
        if not pool:
            raise ValueError(f"Space {space_id} not assigned to any shard")
        return pool

    def least_loaded_shard(self) -> str:
        """Return the DSN of the shard with the fewest assigned spaces."""
        counts = {}
        for pool in self._shard_map.values():
            for dsn, p in self._shard_pools.items():
                if p is pool:
                    counts[dsn] = counts.get(dsn, 0) + 1
        return min(self._shard_pools.keys(),
                   key=lambda d: counts.get(d, 0))
```

**Integration**: Replace the single `_db._pool` reference in
`SparqlSqlSpaceImpl` with `shard_registry.get_pool(space_id)`. Since every
method already receives `space_id`, this is a mechanical change.

---

## 16. PgBouncer Configuration (Phase 4, #22)

```ini
# pgbouncer.ini
[databases]
vitalgraph = host=pg-primary port=5432 dbname=vitalgraph
vitalgraph_ro = host=pg-replica-1 port=5432 dbname=vitalgraph

[pgbouncer]
listen_port = 6432
listen_addr = 0.0.0.0
auth_type = scram-sha-256
auth_file = /etc/pgbouncer/userlist.txt

# Transaction pooling — release connection after each transaction
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 50
reserve_pool_size = 10

# Timeouts
server_idle_timeout = 300
query_timeout = 120
client_idle_timeout = 60

# Logging
log_connections = 0
log_disconnections = 0
stats_period = 60
```

**VitalGraph change**: Point `asyncpg.create_pool()` DSN at PgBouncer
(port 6432) instead of PostgreSQL directly (port 5432). No other code
changes needed.

**Benefit**: 1000 VitalGraph connections multiplex to 50 PG backends.
At 1B rows where queries hold connections longer, this prevents PG
backend exhaustion.

---

## 17. OLTP / Analytics Pool Separation (Phase 4, #21)

```python
# In db_provider.py or space_impl configuration
OLTP_SETTINGS = {
    'min_size': 5,
    'max_size': 20,
    'command_timeout': 5,      # 5 seconds — fast queries only
}
ANALYTICS_SETTINGS = {
    'min_size': 2,
    'max_size': 10,
    'command_timeout': 120,    # 2 minutes — allow complex queries
}
```

**Query classification heuristic** (in `execute_sparql_query`):
```python
def _is_analytics_query(sql: str) -> bool:
    """Classify a query as analytics (slow) vs OLTP (fast)."""
    indicators = [
        'WITH RECURSIVE',       # Property paths
        'GROUP BY',             # Aggregates
        'UNION ALL',            # Multi-branch unions
        sql.upper().count(' JOIN ') > 6,  # Complex multi-join
    ]
    return any(indicators)
```

Alternatively, classify by the SPARQL query structure before SQL generation:
queries with aggregates, property paths, or UNION are analytics; simple
BGP+FILTER+LIMIT queries are OLTP.

---

## Verification Queries

Run these on a test space to validate improvements (works at any scale):

```sql
-- Check index usage
SELECT indexrelname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
WHERE relname LIKE '{space}_%'
ORDER BY idx_scan DESC;

-- Check table bloat
SELECT relname,
       pg_size_pretty(pg_total_relation_size(oid)) AS total_size,
       pg_size_pretty(pg_table_size(oid)) AS heap_size,
       pg_size_pretty(pg_indexes_size(oid)) AS index_size
FROM pg_class
WHERE relname LIKE '{space}_%' AND relkind = 'r'
ORDER BY pg_total_relation_size(oid) DESC;

-- Check sequential scans (should be near zero for indexed queries)
SELECT relname, seq_scan, seq_tup_read, idx_scan, idx_tup_fetch
FROM pg_stat_user_tables
WHERE relname LIKE '{space}_%'
ORDER BY seq_tup_read DESC;

-- Identify slow queries (requires pg_stat_statements extension)
SELECT query, calls, mean_exec_time, rows
FROM pg_stat_statements
WHERE query LIKE '%{space}%'
ORDER BY mean_exec_time DESC
LIMIT 20;
```
