# SPARQL-SQL PostgreSQL Backend: 100× Data Scalability Analysis

**Scope**: `vitalgraph/db/sparql_sql/` — the V2 SPARQL-to-SQL pipeline  
**Baseline**: ~10M quads per space  
**Target**: ~1B quads per space (100× growth)  
**Focus**: Data-volume scaling, not query-rate scaling

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Schema Bottlenecks](#2-schema-bottlenecks)
3. [Query Execution Bottlenecks](#3-query-execution-bottlenecks)
4. [Write Path Bottlenecks](#4-write-path-bottlenecks)
5. [In-Memory Cache Scalability](#5-in-memory-cache-scalability)
6. [Auxiliary Table Scalability](#6-auxiliary-table-scalability)
7. [Recursive / Property Path Scalability](#7-recursive--property-path-scalability)
8. [PostgreSQL Planner Risks](#8-postgresql-planner-risks)
9. [Scaling PostgreSQL: Vertical & Horizontal](#9-scaling-postgresql-vertical--horizontal)
10. [Mitigation Roadmap](#10-mitigation-roadmap)
11. [Appendix: Per-File Analysis](#11-appendix-per-file-analysis)

---

## 1. Executive Summary

The V2 backend is well-engineered for moderate data sizes. At 100× data growth,
**five categories of problems** will dominate:

| Priority | Problem | Severity | Effort |
|----------|---------|----------|--------|
| P0 | **Term table JOINs** — every BGP variable requires a JOIN to `{space}_term` for text resolution; at ~200M terms these become the dominant cost, forcing multi-GB hash joins or billions of random I/O lookups | Critical | Medium |
| P0 | **Composite PK bloat** — the 5-column `rdf_quad` PK creates a ~100-byte B-tree entry per row; at 1B rows the PK index alone is **~100 GB** — far exceeding RAM on most servers | Critical | Medium |
| P0 | **Multi-table BGP cartesian risk** — queries with 4+ triple patterns produce N-way quad-table self-JOINs; at 1B rows without tight index correlation the planner produces hash joins with trillion-row intermediate candidates | Critical | High |
| P1 | **Stats table unbounded growth** — `rdf_stats` has a row per `(predicate, object)` pair, growing O(quads); at 1B quads this table itself reaches **50-200M rows** and the stats-load query becomes unbearable | High | Low |
| P1 | **Bulk ingestion throughput** — `executemany` with `ON CONFLICT DO NOTHING` on a 5-column PK; at 1B rows initial load is infeasible without COPY + index-drop/rebuild | High | Medium |

---

## 2. Schema Bottlenecks

### 2.1 The rdf_quad Primary Key

**Current** (`sparql_sql_schema.py:324-333`):
```sql
PRIMARY KEY (subject_uuid, predicate_uuid, object_uuid, context_uuid, quad_uuid)
```

**Problem**: This is a 5-column composite key using 80 bytes of UUID data per entry
(4 × 16 bytes UUID + 16 bytes `quad_uuid`). PostgreSQL B-tree index entries also
carry ~23 bytes of overhead (item pointer, page header fraction). At 1B rows:

- PK index size: ~1B × 103 bytes ≈ **100 GB**
- Heap size: ~1B × 120 bytes ≈ **120 GB** (row overhead + 4 UUIDs + varchar)
- Total 7 secondary indexes: ~**420 GB** additional
- **Combined footprint: ~640 GB** — requires dedicated storage infrastructure

The `quad_uuid` column in the PK exists for multi-value support but forces every
PK lookup to carry an extra 16-byte column that is almost never queried directly.
Every `INSERT ... ON CONFLICT DO NOTHING` must probe this 5-column index.

**Impact at 100×**: PK probes are entirely disk-bound. The B-tree depth increases
from ~3 levels (10M rows) to ~5 levels (1B rows), adding 2 extra page reads per
probe. Insert throughput drops from ~5K rows/s to **~50 rows/s** as the index
massively exceeds `shared_buffers` and every probe requires random disk I/O.

**Mitigation**:
- Remove `quad_uuid` from the PK; use `UNIQUE (subject_uuid, predicate_uuid, object_uuid, context_uuid)` instead, and keep `quad_uuid` as a non-indexed column with a default.
- Alternatively, replace the composite PK with a surrogate `BIGSERIAL` PK and a covering UNIQUE constraint, reducing index entry size by ~40%.
- Consider hash-partitioning `rdf_quad` by `context_uuid` (i.e., by named graph). Most queries filter on `context_uuid`, so partition pruning would eliminate entire segments. Each partition's indexes stay small and cache-friendly.

### 2.2 The term Table

**Current** (`sparql_sql_schema.py:300-310`):
```sql
term_uuid    UUID PRIMARY KEY,
term_text    TEXT NOT NULL,
term_type    CHAR(1),
lang         VARCHAR(20),
datatype_id  BIGINT,
dataset      VARCHAR(50) NOT NULL DEFAULT 'primary'
```

**Problem**: `term_text` is unbounded `TEXT`. In practice, URI strings average
~80 characters, literal values average ~30 characters. At 1B quads with ~200M
unique terms:

- Heap: ~200M × 140 bytes ≈ **28 GB**
- PK index: ~200M × 40 bytes ≈ **8 GB**
- GIN trigram index on `term_text`: **highly variable** — trigram indexes on 200M
  text values can reach **50–100 GB** depending on text distribution.
- **Combined term table footprint: ~90-140 GB**

The GIN trigram index (`idx_{space}_term_trgm`) is critical for `CONTAINS`/`REGEX`
filter pushdown but is the single most expensive index to maintain during writes.

**Mitigation**:
- Add a `term_text_hash` column (`INT` or `BIGINT`) storing a hash of `(term_text, term_type)`. Use a B-tree index on it for exact-match lookups, which is how 95% of term lookups work (constant materialization). This avoids scanning the full GIN index for simple equality.
- Consider partial GIN indexes: `WHERE term_type = 'L'` — only literals need text search; URIs are looked up by exact match.
- Set `maintenance_work_mem` to ≥2 GB for GIN index builds at this scale.
- Consider replacing GIN trigram with a separate full-text-search table for literals only.

### 2.3 Index Coverage Gaps

**Current indexes on rdf_quad** (`sparql_sql_schema.py:392-399`):
```
(predicate_uuid)
(subject_uuid)
(object_uuid)
(context_uuid)
(predicate_uuid, object_uuid)
(predicate_uuid, subject_uuid)
(subject_uuid, predicate_uuid)
```

**Missing**: There is no composite index with `context_uuid` as a leading column
combined with `predicate_uuid` or `subject_uuid`. The most common query pattern is:

```sql
WHERE q.predicate_uuid = $1 AND q.context_uuid = $2
```

This pattern (graph-scoped predicate lookup) must do an index scan on
`predicate_uuid` and then filter on `context_uuid` from the heap, or vice versa.
At 1B rows, the `predicate_uuid`-only index returns **millions** of candidate
rows that must be heap-checked for `context_uuid`. A single predicate like
`rdf:type` could have 100M+ rows — the index scan alone takes minutes.

**Mitigation**:
- Add `(context_uuid, predicate_uuid)` composite index — this is the single highest-value index addition.
- Add `(context_uuid, subject_uuid)` for subject-scoped graph queries.
- Covering indexes are **mandatory** at this scale: `(context_uuid, predicate_uuid) INCLUDE (subject_uuid, object_uuid)` to enable index-only scans for the inner BGP query. Without covering indexes, every row match requires a random heap read into a 120 GB heap.

---

## 3. Query Execution Bottlenecks

### 3.1 Term Table JOINs Per Variable

**Code**: `emit_bgp.py:142-180`

Every SPARQL variable that appears in a `SELECT`, `FILTER`, `ORDER BY`, `BIND`,
or `GROUP BY` requires a term table JOIN to resolve the UUID to text. The BGP
emitter produces:

```sql
SELECT t_v0.term_text AS v0, t_v0.term_type AS v0__type, ...
FROM (
  SELECT q0.subject_uuid AS v0__uuid, q0.object_uuid AS v1__uuid
  FROM {space}_rdf_quad AS q0
  WHERE ...
) AS sub
JOIN {space}_term AS t_v0 ON sub.v0__uuid = t_v0.term_uuid
JOIN {space}_term AS t_v1 ON sub.v1__uuid = t_v1.term_uuid
```

**Problem**: A query with 4 projected variables generates 4 term table JOINs on
the same table. At 200M rows in `term` (28 GB heap), each JOIN is a primary-key
lookup into a table that **cannot fit in memory**. For queries returning 10K+
rows, each lookup is a random I/O into the 28 GB term heap. With 4 variables ×
10K rows = 40K random reads, each potentially hitting disk. At 100K result rows
(common for analytics), this is **400K random disk reads** — taking minutes.

**Existing mitigation** (`emit_bgp.py:151-155`, `var_scope.py`): The
`text_needed_vars` optimization already skips term JOINs for variables that are
only used internally for UUID-level joins. The GROUP BY pushdown in
`emit_group.py:416-498` defers term JOINs past GROUP BY for COUNT-only
aggregates.

**Gap**: The text_needed optimization doesn't help when variables ARE projected.
Every `SELECT ?s ?p ?o` query requires 3 term JOINs regardless.

**Mitigation**:
- **Inline term text into rdf_quad**: Add a `subject_text`, `predicate_text`, `object_text` denormalization to `rdf_quad`. This eliminates term JOINs for the most common case (text output) at the cost of ~3× heap size. Not recommended for the general case but effective for read-heavy workloads.
- **Materialized "wide quad" view**: Create `{space}_rdf_quad_wide` as a covering view or materialized view with pre-joined text. Queries that project text can hit this view directly. Refresh incrementally.
- **Lateral term lookup**: Replace N separate term JOINs with a single `LATERAL` subquery that fetches all needed UUIDs in one pass, reducing random I/O.
- **LIMIT push-down**: For queries with `LIMIT N`, the term JOINs should be deferred to an outer wrapper so the inner query can short-circuit at N UUID-level rows before doing any text resolution. This is partially implemented but not consistent across all plan shapes.

### 3.2 Multi-Table BGP Self-JOINs

**Code**: `emit_bgp.py:96-138`, `reorder_bgp.py`

A SPARQL query like:
```sparql
SELECT ?entity ?frame ?slot ?value WHERE {
  ?entity a <EntityType> .
  ?entity <hasFrame> ?frame .
  ?frame <hasSlot> ?slot .
  ?slot <hasValue> ?value .
}
```

Generates 4 self-JOINs on `rdf_quad`:
```sql
FROM rdf_quad q0
JOIN rdf_quad q1 ON q1.subject_uuid = q0.subject_uuid
JOIN rdf_quad q2 ON q2.subject_uuid = q1.object_uuid
JOIN rdf_quad q3 ON q3.subject_uuid = q2.object_uuid
WHERE q0.predicate_uuid = ... AND q1.predicate_uuid = ...
  AND q2.predicate_uuid = ... AND q3.predicate_uuid = ...
```

**Problem**: At 1B rows, each self-JOIN on `rdf_quad` is a join between a
1-billion-row table and itself. PostgreSQL's hash join builds a hash table from
one side — at 1B rows, a single hash table is ~16 GB of UUIDs. Four self-joins
may require **64 GB of work_mem** or spill to temp files (which are sequential
but slow). The join reorder heuristic (`reorder_bgp.py:123-149`) helps by
placing selective predicates first, but at 1B rows even "selective" predicates
may have 10M+ rows. Without predicate-partitioning or tight index correlation,
query times go from seconds to **minutes or hours**.

**Existing mitigation**: The edge table rewrite (`rewrite_edge_table.py`)
eliminates 2 of these joins for edge patterns. The frame_entity rewrite
(`rewrite_frame_entity_table.py`) eliminates 5 more for frame traversals.

**Gap**: General-purpose multi-hop traversals (e.g., property chains, type
hierarchies) still produce N-way self-joins.

**Mitigation**:
- **Predicate-partitioned quad tables**: Create separate tables for high-cardinality predicates (`rdf:type`, `rdfs:label`, etc.) so that self-joins between different predicates become cross-table joins between smaller tables.
- **Bitmap index intersection**: Ensure `enable_bitmapscan = on` and that `effective_cache_size` reflects actual available memory, so PG can combine multiple single-column index scans via bitmap AND.
- **Parallel query**: Ensure `max_parallel_workers_per_gather ≥ 2` so PG can parallelize the inner sequential scans within hash joins.
- **Join collapse limit**: For queries with 6+ tables, `join_collapse_limit` (default 8) forces PG to plan all join orderings. Consider raising to 12+ or setting `geqo_threshold` appropriately if query planning time itself becomes a bottleneck.

### 3.3 DISTINCT / ORDER BY on Large Result Sets

**Problem**: `SELECT DISTINCT ?s ?p ?o` at 1B rows produces a full sort or hash
aggregate potentially over billions of candidate rows. `ORDER BY ?label` requires
sorting all rows by their text value — joining to a 28 GB term table for every
row — which means all term JOINs must complete before sorting can begin. At this
scale, unscoped DISTINCT/ORDER BY queries are effectively unusable without LIMIT.

**Mitigation**:
- Push LIMIT into subqueries before DISTINCT/ORDER when possible.
- For ORDER BY on term text: use a covering index `(term_text) INCLUDE (term_uuid)` to enable index-ordered term JOINs.
- For DISTINCT on UUIDs: perform DISTINCT on UUID columns (compact 16-byte keys) and resolve text only for the surviving rows.

### 3.4 UNION ALL Padding

**Code**: `emit_union.py:49-59`

Each UNION branch pads missing variables with NULL columns. For a UNION of 5
branches with 10 variables each, this generates 5 × 10 × 7 (companions) = 350
columns. PostgreSQL's tuple deforming becomes measurable at this width.

**Mitigation**: This is a constant-factor issue (not data-volume dependent) but
compounds with row count. No immediate action needed at 100×.

---

## 4. Write Path Bottlenecks

### 4.1 Bulk Ingestion (`add_rdf_quads_batch_bulk`)

**Code**: `sparql_sql_space_impl.py:783-948`

The current pipeline:
1. Resolve datatypes (1 query per unique datatype URI)
2. Classify terms in Python (CPU-bound loop over all quads)
3. `executemany` INSERT terms with ON CONFLICT DO NOTHING
4. `executemany` INSERT quads with ON CONFLICT DO NOTHING
5. Sync edge table (self-join on rdf_quad for inserted subjects)
6. Sync frame_entity table (join edge + rdf_quad)
7. Sync stats tables (`executemany` upserts)

**Problem at 100×**:
- Step 3: `executemany` with ~200M unique terms sends 200M parameter sets over
  the wire. Even with asyncpg pipelining, PostgreSQL processes them one-at-a-time
  against a B-tree that's 8+ GB. **Estimated: ~3-6 hours** for term inserts.
- Step 4: 1B quad inserts via `executemany` against a 100 GB PK index:
  **Estimated: ~10-20 hours**.
- Step 5: The edge sync self-join scans `rdf_quad WHERE subject_uuid = ANY($3)`
  with a list of ALL unique subject UUIDs from the batch. At 1B quads with ~100M
  unique subjects, this `ANY()` array is **1.6 GB** and is completely infeasible
  as a single query.
- GIN trigram index maintenance on `term_text`: Each term insert must update the
  GIN posting lists. At 200M terms: **hours to days** of GIN maintenance.

**Total estimated bulk load time at 100×**: **days** (vs ~minutes at current
scale). Bulk loading 1B quads requires a fundamentally different approach.

**Mitigation**:
- **Use COPY instead of executemany**: `COPY ... FROM STDIN` is 5-10× faster than
  `executemany` for bulk inserts. asyncpg supports `conn.copy_records_to_table()`.
  Prepare staging tables without indexes, COPY data in, then `INSERT ... ON CONFLICT`
  from the staging table.
- **Drop/rebuild indexes for bulk load**: Already implemented
  (`drop_indexes_for_bulk_load`, `recreate_indexes_after_bulk_load`) but
  `drop_space_indexes_sql` doesn't drop edge/frame_entity indexes. Extend it.
- **Batch the edge sync**: Instead of `ANY($3)` with all subjects, chunk into
  batches of 10K subjects.
- **Defer GIN index**: Drop the trigram index before bulk load, rebuild after.
  This alone saves 50% of bulk load time.

### 4.2 Incremental Insert (`add_rdf_quads_batch`)

**Code**: `sparql_sql_space_impl.py:746-781`

Each quad is inserted one-at-a-time with 4 `_ensure_term` calls (each a DB
round-trip). At current scale (10M rows) this is fine (~10ms per quad). At 100×
with indexes that massively exceed RAM, each `_ensure_term` call takes ~5-10ms
(disk-bound B-tree probe into 8 GB index), so a single quad insert takes ~40ms.

**Mitigation**: This path is for small incremental writes. At 1B rows the
latency increase is noticeable (~4× slower) but still acceptable for
single-quad operations. For batches of 100+, callers should use the bulk path.

### 4.3 Delete Path

**Code**: `sparql_sql_space_impl.py:983-1054`

`delete_entity_graph_bulk` first finds all subjects with a given
`hasKGGraphURI`, then deletes all quads for those subjects. The subject-finding
query:

```sql
SELECT DISTINCT subject_uuid FROM rdf_quad
WHERE predicate_uuid = $1 AND object_uuid = $2 AND context_uuid = $3
```

uses the `(predicate_uuid, object_uuid)` index, which is efficient. But the
subsequent `DELETE ... WHERE subject_uuid = ANY($1)` with potentially thousands
of subjects requires a sequential scan of the matching portion of the index.

Before deleting quads, it also calls `sync_stats_for_deleted_subjects` which
**reads back all the quads about to be deleted** to compute stat decrements:

```sql
SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid
FROM rdf_quad WHERE subject_uuid = ANY($1) AND context_uuid = $2
```

At 100× with 10K subjects × 50 triples each = 500K rows to read before deleting.
This doubles the I/O. With a 120 GB heap, the random reads for 500K scattered
rows can take **minutes**.

**Mitigation**:
- Combine the stats read and the delete into a single `DELETE ... RETURNING` statement.
- Use `subject_uuid = ANY($1) AND context_uuid = $2` with the proposed `(context_uuid, subject_uuid)` index.

---

## 5. In-Memory Cache Scalability

### 5.1 Term Cache (`_term_cache`)

**Code**: `generator.py:107-117`

```python
_term_cache: Dict[tuple, str] = {}  # (space_id, text, type) → uuid str
```

**Problem**: This is an unbounded dict. At 1B quads with ~200M unique terms, if
even 1% of terms appear as constants in SPARQL queries over time, this cache grows
to ~2M entries × ~150 bytes (key tuple + value string) ≈ **300 MB** of Python
heap. In pathological cases (scan-heavy workloads), it could reach the full 200M
entries ≈ **30 GB** — an OOM kill. Since this is a module-level global with no
eviction, it grows monotonically.

**Mitigation**:
- Add LRU eviction (e.g., `functools.lru_cache` or `cachetools.LRUCache` with a
  cap of ~50K entries).
- Alternatively, key by `(space_id, term_uuid)` and skip the text — constants in
  SPARQL queries tend to reuse the same small set of URIs.

### 5.2 Stats Cache (`_stats_cache`)

**Code**: `generator.py:139-191`

```python
_stats_cache: Dict[str, tuple] = {}  # space_id → (quad_stats, pred_stats)
```

`quad_stats` is `Dict[(pred_uuid, obj_uuid), row_count]` — one entry per unique
`(predicate, object)` pair. At 1B quads with ~50M unique pred+obj pairs, this
dict uses ~50M × 200 bytes ≈ **10 GB** — another OOM vector.

The `_load_quad_stats` query (`generator.py:172-177`) reads ALL rows from
`rdf_stats WHERE row_count >= 2 AND row_count <= 200000`:

```sql
SELECT predicate_uuid::text, object_uuid::text, row_count
FROM {space}_rdf_stats
WHERE row_count >= 2 AND row_count <= 200000
```

At 1B quads, `rdf_stats` may have **50-200M rows**. Even with the filter, this
query returns tens of millions of rows, transfers **gigabytes** over the wire,
and takes **minutes**. This single cache-load call can DoS the system.

**Mitigation**:
- Cap the stats cache at the top-N most common predicates (e.g., top 1000).
  The join reorder heuristic only needs relative selectivity, not exact counts.
- Load stats lazily per-predicate as queries arrive, not in a single bulk load.
- Add a `LIMIT 10000` to the stats query — the reorder heuristic's value
  diminishes beyond the most selective predicates.

### 5.3 Datatype Cache (`_datatype_cache`)

**Code**: `generator.py:124-230`

This is small (~34 standard + few custom datatypes) and scales with schema, not
data. **No issue at 100×**.

However, at 1B quads, the datatype resolution during bulk insert (`_resolve_all_datatypes`)
makes one query per unique datatype URI — still bounded by schema size, not data. Fine.

### 5.4 Compile Cache (`compile_cache.py`)

**Code**: `compile_cache.py:1-141`

Already uses an LRU with configurable max size. **No issue at 100×**.

---

## 6. Auxiliary Table Scalability

### 6.1 Edge Table

**Current**: `{space}_edge` with PK `(edge_uuid, context_uuid)`.

At 100× growth, if edges represent ~10% of quads, the edge table reaches **~100M
rows**. With 4 indexes (src+dst, dst+src, edge_uuid, context_uuid), total index
size is ~**32 GB**.

The `sync_edge_table_after_insert` query:
```sql
INSERT INTO edge ... SELECT src.subject_uuid, src.object_uuid, dst.object_uuid, ...
FROM rdf_quad src JOIN rdf_quad dst ON dst.subject_uuid = src.subject_uuid ...
WHERE src.predicate_uuid = $1 AND dst.predicate_uuid = $2
  AND src.subject_uuid = ANY($3)
```

At 100× with the `ANY($3)` array containing 10M+ subjects, this is completely
infeasible as a single query — the array alone is ~160 MB and the hash join
operates on a 1B-row table. Estimated: **minutes to hours**.

**Mitigation**:
- Batch the `ANY($3)` into chunks of 10K subjects.
- Add `(predicate_uuid, subject_uuid)` composite index (already exists: `idx_{space}_quad_ps`). Verify PG uses it.

### 6.2 Frame-Entity Table

Similar scaling characteristics to the edge table. Depends on the edge table
being current. The frame_entity population query involves a 3-way join
(edge + 2× rdf_quad) with GROUP BY + HAVING + array_agg. At 100×:

**Problem**: The `array_agg() FILTER (WHERE ...)` pattern requires materializing
all matching rows per frame before aggregating. With complex slot structures, this
can produce O(slots²) intermediate rows per frame.

**Mitigation**:
- Pre-filter the edge rows to only those with frame-related predicates before
  joining.
- Add a `WHERE emv.dest_node_uuid IN (SELECT subject_uuid FROM rdf_quad WHERE predicate_uuid = $1)` semi-join to prune non-slot edges early.

### 6.3 Stats Tables

**`rdf_pred_stats`**: One row per unique predicate. Typically ~200-500 rows even
at 100×. **No issue**.

**`rdf_stats`**: One row per unique `(predicate, object)` pair. At 1B quads this
can reach **50-200M rows** because many predicates (like `rdf:type`) have diverse
object values. The `resync_stats_tables` query:

```sql
INSERT INTO rdf_stats (predicate_uuid, object_uuid, row_count)
SELECT predicate_uuid, object_uuid, COUNT(*)
FROM rdf_quad
GROUP BY predicate_uuid, object_uuid
HAVING COUNT(*) <= 200000
```

At 1B rows, this `GROUP BY` produces 50-200M groups. The hash aggregate alone
requires ~**10-40 GB of work_mem** and a full sequential scan of the 120 GB heap.
Estimated: **30-60 minutes**. The resulting `rdf_stats` table is itself
**10-40 GB**, making the stats infrastructure itself a scalability bottleneck.

The incremental `sync_stats_after_insert` uses `executemany` upserts for each
`(predicate, object)` pair in the batch. For a batch of 10K quads with 8K unique
pred+obj pairs, this is 8K `INSERT ... ON CONFLICT` statements. Acceptable.

**Mitigation**:
- For `resync_stats_tables`: Use `COPY` to a temp table then `INSERT ... ON CONFLICT` from it.
- Add `LIMIT` to the stats load query in `_load_quad_stats` (e.g., `ORDER BY row_count DESC LIMIT 10000`).
- Prune `rdf_stats` rows with `row_count < 2` periodically — they don't help the reorder heuristic.

---

## 7. Recursive / Property Path Scalability

**Code**: `emit_path.py`

Property path queries (`?s <pred>+ ?o`) generate `WITH RECURSIVE` CTEs:

```sql
WITH RECURSIVE p1 AS (
  SELECT q.subject_uuid AS start, q.object_uuid AS end, ...
  FROM rdf_quad q WHERE q.predicate_uuid = ...
  UNION ALL
  SELECT p1.start, q.object_uuid, ...
  FROM p1 JOIN rdf_quad q ON q.subject_uuid = p1.end ...
  WHERE depth < 100
)
SELECT DISTINCT start, end FROM p1
```

**Problem at 100×**: If predicate `<pred>` has 1B rows, the base case returns
1B rows. Each recursive step joins 1B CTE rows against 1B quad rows. Even with
`MAX_PATH_DEPTH = 100`, the CTE work table can reach **tens of billions of rows**
before the DISTINCT collapses them — far exceeding available disk, let alone RAM.

PostgreSQL executes `WITH RECURSIVE` as a worklist algorithm — each step's output
feeds the next step's input. At 1B base rows, step 1 produces up to 1B² = 10^18
candidate rows (before deduplication). In practice, cycle elimination prevents
this from reaching theoretical max, but the **work table is not indexed** — each
step requires a hash join against the full CTE work table for deduplication. At
1B base rows, this is a system-killing query that will exhaust all available
storage.

**Unbounded property paths on a 1B-row table are a hard blocker**. They must be
fenced with mandatory depth limits and bound-variable filtering.

**Mitigation**:
- Add a **depth limit parameter** to property path queries (currently hardcoded at 100; should be configurable and default to ~5 for production).
- For `?s <pred>+ ?o` where `?s` is bound, add `WHERE q.subject_uuid = <bound_uuid>` to the base case to produce a narrow fan-out.
- For `<pred>*`, the zero-length base case should use `SELECT DISTINCT subject_uuid FROM rdf_quad` as the seed, not the entire quad table.
- Consider materialized transitive closures for frequently-traversed predicates.

---

## 8. PostgreSQL Planner Risks

### 8.1 Stale Statistics

**Code**: `auto_analyze.py`

`DEFAULT_ANALYZE_THRESHOLD = 50000` means ANALYZE runs after every 50K row
changes. At 1B rows, this threshold is comically small — ANALYZE on a 1B-row
table takes **10-30 minutes** (full table sample). Running ANALYZE every 50K rows
during bulk ingestion would mean ANALYZE runs 20,000 times.

**Risk**: At 1B rows, ANALYZE itself becomes expensive. The default statistics
target of 100 means PG samples 30,000 rows — adequate for 1B rows (0.003%
sample), but the I/O to reach those samples across a 120 GB heap is still slow.

**Mitigation**:
- Increase `DEFAULT_ANALYZE_THRESHOLD` to **5M** for spaces with >100M rows.
  ANALYZE should run at most once per major ingestion batch.
- Set `default_statistics_target = 500` (up from default 100) for UUID columns
  to improve cardinality estimation on heavily skewed distributions at 1B scale.
- Use `ANALYZE (SAMPLE 10000)` (PG 16+) for targeted sampling without full scans.

### 8.2 Join Collapse Limit

With 6+ quad tables in a BGP, PostgreSQL's join planner considers all orderings
up to `join_collapse_limit` (default 8). At 8 tables, this is 8! = 40320
orderings — planning itself takes ~50ms.

The BGP reorder heuristic (`reorder_bgp.py`) produces explicit `JOIN ... ON`
clauses, which PostgreSQL respects (it doesn't re-order explicit JOINs unless
`join_collapse_limit` is high enough). This is a good design — the application
controls join order.

**Risk**: If `join_collapse_limit` is set high and the reorder heuristic produces
suboptimal order, PG will override it. If set low and the heuristic is wrong, the
query is slow.

**Mitigation**: Keep `join_collapse_limit = 8` (default). The reorder heuristic
should be trusted for quad-table patterns.

### 8.3 Memory Pressure

At 1B rows, a query joining 4 quad tables may produce intermediate hash tables
of **10M-100M rows** each. PostgreSQL's `work_mem` (default 4MB) determines
whether these hash tables spill to disk. At 100M rows per hash table × 16 bytes
per UUID key = **1.6 GB per hash table**. Four hash joins = **6.4 GB work_mem**.

If `work_mem` is too small, all hash tables spill to temp files, adding sequential
disk I/O. If set too large, a handful of concurrent queries consume all RAM.

**Mitigation**:
- Set `work_mem = 256MB-1GB` per-operation (carefully — this is per-sort/hash per
  query). For a query with 4 hash joins, peak memory is **1-4 GB**.
- Set `effective_cache_size` to ~75% of available RAM.
- Set `shared_buffers` to 25% of RAM (**minimum 16 GB** for 1B-row workloads;
  32 GB recommended).
- Set `temp_file_limit = 50GB` to prevent runaway queries from filling disk.
- Consider `hash_mem_multiplier = 8.0` (PG 15+) to allow hash joins more memory
  than sorts.
- **Server sizing**: A 1B-quad space requires at minimum 128 GB RAM and NVMe
  storage. Spinning disk is infeasible.

---

## 9. Scaling PostgreSQL: Vertical & Horizontal

Scaling VitalGraph **is** scaling PostgreSQL. The SPARQL-SQL backend delegates
all storage, indexing, query planning, and execution to PostgreSQL. Every
bottleneck identified in this document is ultimately a PostgreSQL resource
constraint — CPU, RAM, storage I/O, or connection capacity. The mitigation
strategy must therefore include PostgreSQL-level scaling alongside
application-level query optimizations.

### 9.1 Vertical Scaling (Scale Up)

Vertical scaling increases resources on a single PostgreSQL instance. This is
the simplest path and should be exhausted before introducing horizontal
complexity.

#### Hardware Sizing for 1B Quads

| Resource | Minimum | Recommended | Notes |
|----------|---------|-------------|-------|
| **RAM** | 128 GB | 256 GB | `shared_buffers` = 25% of RAM; must hold hot indexes in cache |
| **CPU** | 16 cores | 32+ cores | Parallel query workers + concurrent connections |
| **Storage** | 2 TB NVMe | 4 TB NVMe | ~640 GB rdf_quad + ~140 GB term + indexes + WAL + temp |
| **IOPS** | 100K random | 500K+ random | B-tree probes at 1B rows are random I/O bound |
| **Network** | 10 Gbps | 25 Gbps | Large result sets + replication traffic |

#### Key PostgreSQL Configuration (Vertical)

```ini
# Match shared_buffers to available RAM
shared_buffers = 64GB              # 25% of 256 GB
effective_cache_size = 192GB       # 75% of 256 GB
huge_pages = on                    # Mandatory — reduces TLB misses on large buffer pool

# Per-query memory
work_mem = 256MB                   # Per sort/hash operation
hash_mem_multiplier = 8.0          # PG 15+: hash joins get 8× work_mem
maintenance_work_mem = 4GB         # For CREATE INDEX, VACUUM

# Parallelism
max_parallel_workers_per_gather = 4
max_parallel_workers = 16
max_worker_processes = 32

# I/O
effective_io_concurrency = 200     # NVMe
max_parallel_maintenance_workers = 4  # Parallel index builds
```

#### Storage Tiering

At 1B quads, total storage exceeds 1 TB. Not all data is equally hot:

- **Hot tier (NVMe)**: `rdf_quad` indexes, `term` PK index, covering indexes
  — these are accessed on every query. ~500 GB.
- **Warm tier (SSD)**: `rdf_quad` heap, `term` heap, `edge`/`frame_entity`
  — accessed for non-index-only scans. ~300 GB.
- **Cold tier (HDD/object store)**: WAL archives, backups, `rdf_stats`
  full-resync snapshots. ~200 GB+.

PostgreSQL tablespaces can map these tiers:
```sql
CREATE TABLESPACE fast_nvme LOCATION '/mnt/nvme/pg_data';
CREATE TABLESPACE warm_ssd LOCATION '/mnt/ssd/pg_data';

-- Move hot indexes to NVMe
ALTER INDEX idx_{space}_quad_ctx_pred SET TABLESPACE fast_nvme;
ALTER INDEX idx_{space}_quad_ctx_pred_covering SET TABLESPACE fast_nvme;
-- Keep heap on SSD
ALTER TABLE {space}_rdf_quad SET TABLESPACE warm_ssd;
```

### 9.2 Horizontal Scaling (Scale Out)

When a single PostgreSQL instance cannot handle the workload (either storage,
query throughput, or both), horizontal scaling distributes the load across
multiple nodes.

#### Option A: Read Replicas (Simplest)

**Architecture**: One primary (read-write) + N read replicas (read-only).
VitalGraph's SPARQL query path is read-only; writes go through the bulk
ingestion and SPARQL UPDATE paths.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  VitalGraph │     │  VitalGraph │     │  VitalGraph │
│  (writes)   │     │  (reads)    │     │  (reads)    │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       ▼                   ▼                   ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  PG Primary │────▶│  PG Replica │     │  PG Replica │
│  (R/W)      │     │  (R/O)      │     │  (R/O)      │
└─────────────┘     └─────────────┘     └─────────────┘
      streaming replication
```

**Implementation in VitalGraph**:
- `db_provider.py` needs a **dual-pool** configuration: write pool → primary,
  read pool → replicas (round-robin or least-connections).
- `execute_sparql_query` uses the read pool.
- `add_rdf_quads_batch_bulk`, `delete_entity_graph_bulk`, etc. use the write pool.
- Replication lag (typically <1 second with streaming replication) means
  recently-written quads may not be immediately queryable on replicas.
  This is acceptable for most VitalGraph workloads.

**Capacity**: Each replica handles the full query workload independently.
3 replicas = 3× read throughput with no application-level sharding.

**Managed services**: AWS RDS/Aurora, Google Cloud SQL, Azure Database for
PostgreSQL all support read replicas with automatic failover.

#### Option B: Space-Level Sharding

**Architecture**: Different spaces live on different PostgreSQL instances.
Since VitalGraph uses per-space tables (`{space_id}_rdf_quad`,
`{space_id}_term`, etc.), spaces are already **logically isolated** — they
share no data.

```
┌─────────────────┐
│   VitalGraph    │
│   Router        │
└────┬────┬───────┘
     │    │
     ▼    ▼
┌────────┐ ┌────────┐
│ PG #1  │ │ PG #2  │
│space_a │ │space_b │
│space_c │ │space_d │
└────────┘ └────────┘
```

**Implementation in VitalGraph**:
- Add a **shard registry** mapping `space_id → connection_pool`.
- `SparqlSqlSpaceImpl` already receives `space_id` in every method — route
  to the correct pool based on the shard registry.
- Space creation allocates to the least-loaded shard.
- No cross-space queries are needed (spaces are independent).

**Advantages**: Zero application-level query changes. Each shard handles
fewer spaces, so indexes stay smaller and fit in RAM. A 10-shard cluster
can hold 10B total quads (1B per shard) with each shard at the single-node
performance profile.

**Disadvantages**: Operational complexity (multiple PG instances to manage),
no cross-space analytics without a federation layer.

#### Option C: Table-Level Sharding (Citus / pg_partman)

**Architecture**: A single logical PostgreSQL database distributes tables
across multiple worker nodes using Citus (or similar extension).

```
┌─────────────────┐
│  VitalGraph     │
└────────┬────────┘
         ▼
┌─────────────────┐
│  Citus Coord.   │
└──┬────┬────┬────┘
   ▼    ▼    ▼
┌────┐┌────┐┌────┐
│ W1 ││ W2 ││ W3 │  (worker nodes)
└────┘└────┘└────┘
```

**Shard key**: `context_uuid` is the natural shard key — it's present in
every `rdf_quad` row and is the most common filter column. Citus would
distribute `rdf_quad` across workers by `context_uuid` hash.

**Advantages**: Transparent to VitalGraph — SQL queries route automatically.
Parallel query execution across workers. Can scale to 10B+ quads.

**Disadvantages**: Cross-shard joins (queries spanning multiple graphs)
require data shuffling. Citus is a PG extension (not vanilla PG). Some
SQL patterns (e.g., `WITH RECURSIVE` across shards) are not supported.

**Feasibility for VitalGraph**: High — most queries are graph-scoped
(`WHERE context_uuid = $1`), which Citus routes to a single worker. The
edge/frame_entity tables would need to be co-located on the same shard
key.

#### Option D: Aurora / AlloyDB (Managed Distributed Storage)

**Architecture**: Compute nodes share a distributed storage layer.

- **AWS Aurora PostgreSQL**: Up to 128 TB storage, 15 read replicas,
  storage auto-scaling. The storage layer replicates across 3 AZs.
  Eliminates storage-tier management entirely.
- **Google AlloyDB**: Columnar engine for analytics + row store for OLTP.
  Could handle both the UUID-join OLTP path and text-search analytics
  path efficiently.

**Advantages**: No sharding logic needed. Storage scales independently
of compute. Automatic failover and backup.

**Disadvantages**: Vendor lock-in. Higher per-hour cost. Some PG extensions
(e.g., `pg_trgm` GIN indexes) may behave differently.

**Feasibility for VitalGraph**: Excellent for managed deployments. The
application code requires zero changes — Aurora/AlloyDB are
wire-compatible with PostgreSQL.

### 9.3 Scaling Decision Matrix

| Scale | Strategy | Complexity | Cost |
|-------|----------|------------|------|
| 10M → 100M quads | **Vertical** — bigger instance + index tuning | Low | $ |
| 100M → 1B quads | **Vertical + Read Replicas** — 256 GB RAM, 3 replicas | Medium | $$ |
| 1B → 10B quads | **Space-Level Sharding** or **Citus** | High | $$$ |
| 10B+ quads | **Citus + Aurora/AlloyDB** + predicate partitioning | Very High | $$$$ |

### 9.4 Connection Pool Scaling

At 1B rows, individual queries take longer (seconds instead of milliseconds),
which means more connections are held concurrently. PostgreSQL's per-connection
overhead (~10 MB per backend process) limits practical connection counts.

**Current**: `db_provider.py` uses a single asyncpg pool with externally
configured size.

**Scaling strategy**:
- **PgBouncer** in transaction-pooling mode between VitalGraph and PostgreSQL.
  Allows 1000+ application connections mapped to ~50 PG backend connections.
- **Separate pools for OLTP vs analytics**: Short-running queries (entity
  lookups, single-triple inserts) should not compete with long-running
  analytics queries (aggregates, property paths) for connections.
  ```python
  # In db_provider.py
  _oltp_pool: asyncpg.Pool   # max 20, statement_timeout=5s
  _analytics_pool: asyncpg.Pool  # max 10, statement_timeout=120s
  ```
- **Read replica routing**: SPARQL SELECT queries → replica pool;
  SPARQL UPDATE/INSERT → primary pool.

---

## 10. Mitigation Roadmap

### Phase 1: Quick Wins (< 1 week)

| # | Change | File(s) | Impact |
|---|--------|---------|--------|
| 1 | Add `(context_uuid, predicate_uuid)` index | `sparql_sql_schema.py` | 10-100× faster graph-scoped queries |
| 2 | Add `(context_uuid, subject_uuid)` index | `sparql_sql_schema.py` | 10-100× faster subject lookups in graph |
| 3 | Cap `_term_cache` with LRU (50K entries) | `generator.py` | **Prevents OOM** — unbounded cache is a kill risk at 1B |
| 4 | Add `LIMIT 10000` to stats load query | `generator.py` | Prevents **multi-minute** stats load; reduces to ~50ms |
| 5 | Reduce `MAX_PATH_DEPTH` default to 5 | `emit_path.py` | **Prevents system-killing** recursive CTEs on 1B rows |
| 6 | Set `default_statistics_target = 500` for UUID cols | `sparql_sql_schema.py` | Better planner estimates at extreme scale |

### Phase 2: Medium Effort (1-2 weeks)

| # | Change | File(s) | Impact |
|---|--------|---------|--------|
| 7 | Remove `quad_uuid` from PK | `sparql_sql_schema.py`, migration | Saves ~16 GB of PK index at 1B rows |
| 8 | Use `COPY` for bulk term/quad inserts | `sparql_sql_space_impl.py` | **Mandatory** at 1B — executemany takes days |
| 9 | Batch edge/frame_entity sync to 10K chunks | `sync_edge_table.py`, `sync_frame_entity_table.py` | Prevents infeasible multi-GB ANY() arrays |
| 10 | Combine delete + stats into `DELETE RETURNING` | `sparql_sql_space_impl.py` | 50% less I/O on delete path |
| 11 | LIMIT push-through for term JOINs | `emit_bgp.py`, `emit_slice.py` | **Critical** — avoids millions of random reads into 28 GB term table |
| 12 | Partial GIN index on `term (term_text) WHERE term_type = 'L'` | `sparql_sql_schema.py` | Saves ~50 GB of GIN index at 200M terms |

### Phase 3: Architecture (2-4 weeks)

| # | Change | File(s) | Impact |
|---|--------|---------|--------|
| 13 | Hash-partition `rdf_quad` by `context_uuid` | Schema migration | **Mandatory** — each partition's indexes fit in RAM |
| 14 | Covering indexes with INCLUDE | `sparql_sql_schema.py` | **Mandatory** — avoids random reads into 120 GB heap |
| 15 | Predicate-partitioned quad tables for hot predicates | New tables, `emit_bgp.py` | Reduces 1B-row self-joins to 10M-row cross-table joins |
| 16 | Materialized transitive closures for key predicates | New table + sync | Eliminates system-killing recursive CTEs |
| 17 | **Separate term storage** — partition term table by type (URI vs Literal) or use columnar storage for text | Schema + emit changes | Reduces term JOIN I/O by 50%+ |
| 18 | **Query timeouts** — mandatory `statement_timeout` per query | `db_provider.py` | Prevents runaway queries from blocking all connections for hours |

### Phase 4: Infrastructure Scaling (ongoing)

| # | Change | Scope | Impact |
|---|--------|-------|--------|
| 19 | **Vertical sizing** — 256 GB RAM, 32 cores, NVMe | Hardware/cloud | Baseline for 1B quads |
| 20 | **Read replicas** — 2-3 streaming replicas for read traffic | `db_provider.py`, PG config | 2-3× read throughput; query latency unaffected |
| 21 | **Dual connection pools** — separate OLTP and analytics pools | `db_provider.py` | Prevents slow queries from starving fast ones |
| 22 | **PgBouncer** — transaction-mode connection pooling | Infrastructure | 10× more app connections without PG backend overhead |
| 23 | **Space-level sharding** — route spaces to different PG instances | `SparqlSqlSpaceImpl`, shard registry | Linear horizontal scale; 10 shards = 10B quads |
| 24 | **Storage tiering** — NVMe for indexes, SSD for heaps | PG tablespaces | 2-5× I/O improvement for index-heavy workloads |
| 25 | **Citus / Aurora evaluation** — for 10B+ scale | Infrastructure | Transparent distributed queries |

---

## 11. Appendix: Per-File Analysis

### `sparql_sql_schema.py`
- **5-column composite PK**: Main scalability bottleneck for writes. At 1B rows: **100 GB PK index**.
- **7 secondary indexes on rdf_quad**: ~60 bytes per index entry × 7 = 420 bytes
  of index overhead per quad row. At 1B rows: **420 GB of indexes** — requires dedicated NVMe storage.
- **Missing context-leading composite indexes**: Critical gap for graph-scoped queries.
  Without them, queries at 1B rows degrade from seconds to minutes.

### `generator.py`
- **`_term_cache`**: Unbounded growth. Must add eviction.
- **`_stats_cache`**: Bulk-loads entire stats table. Must add limit.
- **`materialize_constants`**: Efficient batched query. Scales well.

### `emit_bgp.py`
- **Inner/outer split**: Good architecture. The inner query operates on compact UUIDs.
- **Term JOINs**: The dominant cost at scale. Each variable adds one JOIN on a **200M-row, 28 GB** table.
- **Reorder integration**: Properly delegates to `reorder_bgp.py`. The `OFFSET 0` trick to force subquery evaluation is a sound optimizer fence.

### `reorder_bgp.py`
- **Greedy placement**: O(N² × C) where N = quad tables, C = constraints. At N ≤ 10 this is negligible. Correct.
- **Stats-based tiebreaker**: Uses `pred_stats` and `quad_stats` for cardinality estimates. Works well when stats are fresh.
- **Text-filter anchor**: Correctly identifies ILIKE/regex constraints as most selective. Critical for filter-pushdown queries.

### `filter_pushdown.py`
- **Semi-join pattern**: Converts `CONTAINS(?var, "text")` to `uuid IN (SELECT term_uuid FROM term WHERE term_text LIKE '%text%')`. This leverages the GIN trigram index effectively.
- **At 100×**: The semi-join subquery returns a set of UUIDs. If the text matches 10M terms (plausible at 200M total), the hash semi-join builds a **160 MB hash table** — still feasible but no longer cheap. For broad text matches, this becomes a bottleneck. Consider adding `LIMIT` to the semi-join subquery for common prefixes.

### `emit_path.py`
- **`MAX_PATH_DEPTH = 100`**: **System-killing** at 1B rows. A path depth of 100 on a 1B-row table will exhaust all disk and crash PostgreSQL.
- **No bound-variable optimization**: When `?s` is bound, the base case should filter to that single subject.

### `sync_edge_table.py`
- **`ANY($3)` with all unique subjects**: **Infeasible** at 100× with 10M+ subjects per batch.
- **`resync_edge_table`**: Full table scan + self-join on 1B-row table: **~30-60 minutes**. Must be chunked.

### `sync_frame_entity_table.py`
- **3-way join with GROUP BY + array_agg**: Complex query. At 100× the GROUP BY produces large hash tables.
- **HAVING with array_agg**: Forces full materialization before filtering.

### `sync_stats_tables.py`
- **`resync_stats_tables`**: Full sequential scan of 1B-row rdf_quad for GROUP BY: **~30-60 minutes**. The resulting rdf_stats table is 10-40 GB. Must be redesigned — consider predicate-only stats at this scale.
- **Incremental `sync_stats_after_insert`**: `executemany` upserts. Scales linearly with batch size. Still acceptable for incremental batches <100K.

### `auto_analyze.py`
- **Threshold of 50K**: Far too low for 1B rows — would trigger ANALYZE thousands of times during bulk load, each taking 10+ minutes. Must increase to 5M+.
- **Background thread execution**: Good — doesn't block the event loop.

### `compile_cache.py`
- **LRU with parameterization**: Well-designed. Cache hit rate is independent of data volume.

### `sparql_sql_db_objects.py`
- **`_fetch_objects_for_uris`**: Batches subjects in groups of 100, builds SPARQL `VALUES` for each batch. At 100× if a query matches 100K subjects, this produces **1000 batches** of SPARQL queries, each executing against 1B-row tables. Total time: **minutes**.
- **Mitigation**: Use direct SQL (bypassing the SPARQL pipeline) for this hot path. Consider cursor-based streaming for large result sets.

### `db_provider.py`
- **Connection pool**: Uses asyncpg pool from the configured `DbImplInterface`. Pool size is controlled externally. At 100× with queries that may run for minutes instead of milliseconds, pool exhaustion is **near-certain** under concurrent load.
- **Mitigation**: Ensure pool size ≥ 20, add **mandatory** query timeouts (`statement_timeout = '60s'`), and consider separate pools for fast (OLTP) vs. slow (analytics) queries.
