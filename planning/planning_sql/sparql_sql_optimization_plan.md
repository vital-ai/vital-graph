# SPARQL → SQL Optimization Plan

## Current State (2026-03-04, updated)

- SPARQL-to-SQL pipeline generates correct SQL for all query types (SELECT, ASK, CONSTRUCT)
- **20/20 WordNet queries passing** — including 5c (complex subquery, now enabled via CTE MATERIALIZED)
- Multiple optimization passes implemented (see Completed Optimizations below)
- Optional sqlglot post-emit optimizer integrated (`optimize=True` flag)
- Performance: simple queries 1–15ms, complex traversals 14–24ms, aggregation 155ms–5.3s (warm)
- Fuseki vs PG benchmark script: `vitalgraph_sparql_sql/scripts/benchmark_fuseki_vs_sql.py`

## Timing Baseline (wordnet_exp, 20 queries, optimize=OFF, 2026-03-04)

| Query | Rows | PG Exec | Wall | Notes |
|---|---:|---:|---:|---|
| 5c. Subquery: top-5 + relationships | 20 | 11,985ms | 12,895ms | CTE MATERIALIZED subquery + 12 JOINs |
| 1a. Distinct predicates | 14 | 4,762ms | 5,257ms | Full predicate scan |
| 2c. Count entities by type | 4 | 501ms | 4,853ms | Cold-cache penalty |
| 5b. Entity degree (COUNT) | 15 | 3,354ms | 3,661ms | 6 JOINs + GROUP BY |
| 1b. Distinct rdf:type values | 4 | 276ms | 2,117ms | |
| 4b. Count by frame type | 22 | 696ms | 1,442ms | 6 JOINs + GROUP BY |
| 4c. Entity name FILTER | 20 | 585ms | 1,224ms | ILIKE + trigram index |
| 1e. Distinct slot types | 2 | 335ms | 323ms | |
| 1c. Distinct frame types | 20 | 283ms | 296ms | |
| 5a. Total triple count | 1 | 147ms | 157ms | |
| 1d. Distinct entity types | 4 | 33ms | 53ms | |
| 3c. Full edge traversal | 10 | 4ms | 27ms | 12 JOINs (warm) |
| 4a. Hyponym relationships | 20 | 13ms | 21ms | 12 JOINs (warm) |
| 2a. Sample entities | 10 | 0ms | 18ms | |
| 3d. Traversal with names | 10 | 4ms | 18ms | 12 JOINs (warm) |
| 6b. CONSTRUCT traversal | 10 | 2ms | 17ms | 9 JOINs (warm) |
| 3b. Frame→Slot→Entity | 10 | 3ms | 15ms | |
| 2b. Entities type+name+desc | 10 | 0ms | 15ms | |
| 3a. Sample frames | 10 | 1ms | 10ms | |
| 6a. ASK hyponym exists | 1 | 0ms | 7ms | |
| **TOTAL** | | **22,985ms** | **32,427ms** | |

**Note**: Wall > PG Exec on some queries due to cold-cache PG planning time on first run.
Previous baseline total was 271s (2026-03-03). Current: 32s. **8.4x improvement** from cumulative optimizations.

## Fuseki vs PostgreSQL Comparison (2026-03-04)

Same SPARQL queries, same 7M-triple WordNet dataset. Fuseki = Jena TDB2 (localhost:3030/wordnet-frames).

| Query | Fuseki | PG (SPARQL→SQL) | Winner | Gap |
|---|---:|---:|---|---|
| 1a. Distinct predicates | 5,345ms | 5,219ms | ~tie | 1.0x |
| 2a. Sample entities | 15ms | 34ms | Fuseki | 2.2x |
| 5a. Total triple count | 1,401ms | 180ms | **PG** | **7.8x** |
| 5b. Entity degree | 1,955ms | 13,649ms | **Fuseki** | **7.0x** |
| 5c. Subquery top-5 | **TIMEOUT** | 17,959ms | **PG** | Fuseki can't finish |

### Why Fuseki Wins on 5b (Multi-Pattern Graph Joins)

Fuseki's advantage comes from its native triple-index architecture:

1. **SPO/POS/OSP indexes** — Jena TDB maintains three B+-tree indexes covering all six permutations of (S, P, O). Pattern matching `(?s, P, O)` is a single range scan. No JOINs.
2. **No UUID indirection** — Jena stores dictionary-encoded term IDs inline in the index. Pattern matching resolves to integer comparisons, not UUID string comparisons.
3. **No term table JOINs** — In PG, every variable that appears in SELECT requires a JOIN to the term table to resolve the UUID back to text. Jena's dictionary is integrated.

Our PG schema requires **2 JOINs per triple pattern** (one for the quad, one for each term resolution), so a 5-pattern BGP = 10+ JOINs. Jena handles the same BGP with 5 index lookups and zero JOINs.

### Where PG Wins

1. **COUNT(*) aggregation** (5a: 7.8x) — PG's sequential scan + count is highly optimized; Jena must iterate its index
2. **Complex subqueries** (5c) — PG's CTE MATERIALIZED + hash join handles the bounded-subquery-then-join pattern; Jena's bottom-up evaluator times out
3. **Text search** (4c) — PG's GIN trigram indexes give sub-second ILIKE; Jena has no equivalent without Lucene

---

## Root Cause Analysis

### Why multi-join queries are slow on PG

The KGFrame data model requires **4 triple patterns per relationship hop**:
- Slot type lookup
- Slot value dereference
- Edge source binding
- Edge destination binding

A single "source entity → frame → destination entity" traversal = 10–12 quad table JOINs.

PostgreSQL's planner struggles with 10+ table joins because:
1. **GEQO threshold** — PG uses genetic optimizer above `geqo_threshold` (default 12) tables
2. **Cardinality misestimation** — independence assumption fails for correlated columns (predicate_uuid + object_uuid)
3. **No adaptive plans** — once PG picks a plan, it sticks even if row estimates are wrong
4. **UUID join overhead** — every variable→text resolution requires a hash join to the 1.8M-row term table

### The structural gap vs Fuseki

| Aspect | Fuseki (Jena TDB) | PG (SPARQL→SQL) |
|---|---|---|
| Triple pattern lookup | 1 B+-tree range scan | 1 quad table scan + term JOINs |
| Variable binding | In-memory dictionary ID | UUID hash join to term table |
| 5-pattern BGP | 5 index lookups | 10–15 SQL JOINs |
| Join ordering | Jena's static analysis (good) | PG planner or GEQO (variable) |
| Text search | Lucene (optional) | GIN trigram (built-in) |
| Aggregation | Iterator-based | Hash aggregate (fast) |
| Subqueries | Bottom-up (can explode) | CTE MATERIALIZED (controlled) |

---

## Proposed Optimizations to Close the Fuseki Gap

### Priority 1: Reduce JOIN Count (High Impact)

#### 1A. Covering Composite Indexes

**Problem**: PG uses separate single-column indexes and must intersect bitmap scans. Fuseki's SPO/POS/OSP indexes cover all access patterns natively.

**Approach**: Create composite indexes that mimic Fuseki's triple-index strategy:
```sql
-- SPO equivalent: lookup by subject + predicate → get object
CREATE INDEX idx_quad_spo ON wordnet_exp_rdf_quad
  (context_uuid, subject_uuid, predicate_uuid, object_uuid);

-- POS equivalent: lookup by predicate + object → get subject
CREATE INDEX idx_quad_pos ON wordnet_exp_rdf_quad
  (context_uuid, predicate_uuid, object_uuid, subject_uuid);

-- OSP equivalent: lookup by object → get subject + predicate
CREATE INDEX idx_quad_osp ON wordnet_exp_rdf_quad
  (context_uuid, object_uuid, subject_uuid, predicate_uuid);
```

**Why**: These are *covering indexes* — PG can answer quad lookups from the index alone (index-only scans), eliminating heap fetches. The `context_uuid` prefix enables partition-like behavior per graph.

**Expected impact**: 2–3x on multi-join queries. Each triple pattern becomes an index-only scan instead of bitmap intersection.

**Storage cost**: ~3 × 200MB = 600MB additional for the 7M-quad dataset.

#### 1B. Materialized "Wide Quad" View

**Problem**: Every projected variable requires a JOIN to the term table. A 5-variable query needs 5 extra JOINs just for text resolution.

**Approach**: Pre-join the quad table with the term table for the most-accessed columns:
```sql
CREATE MATERIALIZED VIEW wordnet_exp_wide_quad AS
SELECT
    q.subject_uuid, s.term_text AS subject_text, s.term_type AS subject_type,
    q.predicate_uuid, p.term_text AS predicate_text,
    q.object_uuid, o.term_text AS object_text, o.term_type AS object_type,
    q.context_uuid
FROM wordnet_exp_rdf_quad q
JOIN wordnet_exp_term s ON q.subject_uuid = s.term_uuid
JOIN wordnet_exp_term p ON q.predicate_uuid = p.term_uuid
JOIN wordnet_exp_term o ON q.object_uuid = o.term_uuid;

-- Index it like the base table
CREATE INDEX idx_wide_spo ON wordnet_exp_wide_quad
  (context_uuid, subject_uuid, predicate_uuid);
CREATE INDEX idx_wide_pos ON wordnet_exp_wide_quad
  (context_uuid, predicate_uuid, object_uuid);
```

**Why**: Eliminates term JOINs entirely. A 5-pattern BGP becomes 5 quad-table JOINs instead of 15. This directly mimics Fuseki's integrated dictionary.

**Trade-off**: ~3× storage of the base quad table. Must be refreshed after data changes (`REFRESH MATERIALIZED VIEW CONCURRENTLY`).

**Expected impact**: 3–5x on multi-join queries (5b target: 13.6s → 2–4s).

### Priority 2: Help PG's Planner (Medium Impact)

#### 2A. Extended Multi-Column Statistics

**Problem**: PG assumes column independence and badly underestimates selectivity for `predicate = X AND object = Y`.

```sql
ALTER TABLE wordnet_exp_rdf_quad ALTER COLUMN predicate_uuid SET STATISTICS 1000;
ALTER TABLE wordnet_exp_rdf_quad ALTER COLUMN object_uuid SET STATISTICS 1000;
ALTER TABLE wordnet_exp_rdf_quad ALTER COLUMN subject_uuid SET STATISTICS 1000;

CREATE STATISTICS quad_pred_obj_stats (dependencies)
  ON predicate_uuid, object_uuid FROM wordnet_exp_rdf_quad;
CREATE STATISTICS quad_pred_obj_ndv (ndistinct)
  ON predicate_uuid, object_uuid FROM wordnet_exp_rdf_quad;
CREATE STATISTICS quad_subj_pred_stats (dependencies)
  ON subject_uuid, predicate_uuid FROM wordnet_exp_rdf_quad;

ANALYZE wordnet_exp_rdf_quad;
```

**Expected impact**: Better join order selection → 1.5–2x on mid-complexity queries.

#### 2B. GEQO Tuning

```sql
SET geqo_threshold = 16;  -- force exhaustive planning for 12–15 table joins
SET geqo_effort = 10;     -- or increase genetic effort (default 5)
```

**Risk**: Exhaustive planning of 14+ tables can take seconds. Measure planning time.

#### 2C. LATERAL JOIN Rewrite for Multi-Hop Patterns

**Problem**: A flat JOIN of 12 tables gives PG too many join-order choices (12! = 479M). Even with good stats, the planner may pick a bad order.

**Approach**: For multi-hop frame traversals (source → frame → destination), emit as nested LATERAL subqueries that force the execution order:

```sql
SELECT ...
FROM quad q1  -- slot type lookup
JOIN quad q2 ON q2.object_uuid = q1.subject_uuid  -- slot value
CROSS JOIN LATERAL (
    SELECT q3.subject_uuid AS frame_uuid, ...
    FROM quad q3
    JOIN quad q4 ON ...
    WHERE q3.object_uuid = q2.subject_uuid  -- bound from outer
) frame_matches
CROSS JOIN LATERAL (
    SELECT ...
    FROM quad q5
    WHERE q5.subject_uuid = frame_matches.frame_uuid
) dst_matches
```

**Why**: LATERAL forces PG to evaluate the outer query first and pass bound values into the inner query, similar to Jena's execution model. This eliminates the join-ordering problem entirely.

**Implementation**: Detect multi-hop patterns in the IR (chains of BGP triples sharing variables through slot→edge→frame→edge→slot patterns) and emit LATERAL blocks instead of flat JOINs.

**Expected impact**: 3–7x on traversal queries. This is the single highest-impact SQL-level change.

### Priority 3: Schema-Level Changes (High Impact, Higher Effort)

#### 3A. Predicate-Partitioned Quad Table

**Problem**: Every triple pattern scan touches the full 7M-row quad table even though each predicate has very different cardinality (rdf:type = 1.5M rows, hasName = 110K rows).

**Approach**:
```sql
CREATE TABLE wordnet_exp_rdf_quad (
    subject_uuid UUID, predicate_uuid UUID, object_uuid UUID, context_uuid UUID
) PARTITION BY LIST (predicate_uuid);

-- One partition per high-frequency predicate
CREATE TABLE quad_type PARTITION OF wordnet_exp_rdf_quad
  FOR VALUES IN ('uuid-of-rdf-type');
CREATE TABLE quad_name PARTITION OF wordnet_exp_rdf_quad
  FOR VALUES IN ('uuid-of-hasName');
-- DEFAULT partition for everything else
CREATE TABLE quad_other PARTITION OF wordnet_exp_rdf_quad DEFAULT;
```

**Why**: Pattern `?x rdf:type KGFrame` scans only the 1.5M-row type partition instead of the 7M-row table. PG's partition pruning is automatic when predicate_uuid is a constant (which it always is in our generated SQL).

**Expected impact**: 2–5x on queries with selective predicates.

#### 3B. Integer Term IDs Instead of UUIDs

**Problem**: UUID comparisons and hash joins are expensive. Fuseki uses 8-byte integer node IDs.

**Approach**: Replace UUID columns with BIGINT (auto-incrementing term_id), add a UUID→BIGINT lookup in the term table.

```sql
ALTER TABLE wordnet_exp_term ADD COLUMN term_id BIGSERIAL UNIQUE;
-- Rebuild quad table with integer columns
CREATE TABLE wordnet_exp_rdf_quad_v2 (
    subject_id BIGINT, predicate_id BIGINT, object_id BIGINT, context_id BIGINT
);
```

**Why**: BIGINT comparisons are ~2x faster than UUID. Hash joins and sorts are cheaper. Index size drops ~50%.

**Expected impact**: 1.5–2x across all queries. Multiplicative with other optimizations.

**Effort**: High — requires migration of all existing data and code changes.

### Priority 4: Autoanalyze Tuning (Maintenance)

```sql
ALTER TABLE wordnet_exp_rdf_quad SET (autovacuum_analyze_scale_factor = 0.02);
ALTER TABLE wordnet_exp_term SET (autovacuum_analyze_scale_factor = 0.02);
```

---

## Optimization Implementation Results (2026-03-04)

### ✅ 1A. Covering Composite Indexes — APPLIED, EFFECTIVE

Created `idx_quad_cspo`, `idx_quad_cpos`, `idx_quad_cosp` on `wordnet_exp_rdf_quad`.
Enables index-only scans for all triple pattern access patterns.

**Result**: 5b dropped from 13.6s → 6.6s (2x). Warm-cache: 3.3–3.5s. Combined with 2A, this was the largest single win.

### ✅ 2A. Extended Multi-Column Statistics — APPLIED, EFFECTIVE

Created `STATISTICS 1000` on individual UUID columns and extended statistics (`dependencies`, `ndistinct`) for multi-column combinations.

**Result**: Better cardinality estimates improve join ordering. 5c dropped from 18s → 8.2s (2.2x). Combined with 1A for multiplicative benefit.

### ❌ 1B. Materialized Wide-Quad View — TESTED, REJECTED

Created `wordnet_exp_wide_quad` (7M rows × 8 columns). Tested with full emitter integration.

**Result**: **No warm-cache benefit, often 2–3x worse.**
- 5b: 3.5s → 3.4s (no change)
- 5c: 7s → 18s (2.6x worse)
- 2a: 23ms → 750ms (32x worse)
- 5a: 167ms → 673ms (4x worse)

**Why it failed**: The wider rows (text inline) destroy PG's buffer cache efficiency. The narrow UUID-only quad table fits more rows in memory, and the separate term JOINs only touch small result sets. The Fuseki "integrated dictionary" advantage doesn't translate to PG's row-oriented storage.

**Action**: View dropped, code reverted. Not worth the 3.8GB storage.

### ❌ 2C. LATERAL Join Rewrite — TESTED, REJECTED

Implemented automatic LATERAL grouping in the SQL emitter: detect back-references in join chains, split into `CROSS JOIN LATERAL` subqueries.

**Result**: **Marginal benefit on 5b (~9% warm cache), breaks complex queries.**
- 5b: 3.5s → 3.2s (9% better, within noise)
- 3c, 3d, 4a, 5c: **hang indefinitely** (PG planner picks catastrophic plans for LATERAL with 10+ tables)

**Why it failed**: LATERAL forces nested-loop execution, which is only beneficial when the outer scope produces few rows. For our join chains where intermediate cardinalities are high (10K+ slots), LATERAL forces row-at-a-time evaluation that's vastly slower than hash joins.

**Action**: Code reverted. LATERAL may help with explicit `LIMIT` pushdown in specific patterns but not as a general rewrite.

### Summary Table

| Strategy | Target | Expected | Actual | Verdict |
|---|---|---|---|---|
| 1A. Covering indexes | 5b | 2–3x | **2x** | ✅ Applied |
| 2A. Extended statistics | All | 1.5–2x | **2.2x on 5c** | ✅ Applied |
| 1B. Wide quad view | 5b | 3–5x | **0.3–1x** (worse) | ❌ Rejected |
| 2C. LATERAL rewrite | 5b | 3–7x | **1.1x** (hangs on complex) | ❌ Rejected |
| **Net result (1A + 2A)** | **5b** | — | **13.6s → 3.5s (3.9x)** | ✅ |

---

## Remaining Optimization Proposals

### Priority 1: Schema-Level (High Impact, High Effort)

#### 3A. Predicate-Partitioned Quad Table *(Deprioritized)*
Partition `_rdf_quad` by `predicate_uuid`. However, **the covering composite indexes (1A) already provide the main benefit**: `idx_quad_cpos` starts with `(context_uuid, predicate_uuid, ...)` so PG does index-only scans touching only the relevant predicate's entries — functionally equivalent to partition pruning.

Partitioning would give marginal wins: smaller heap pages per partition, less VACUUM bloat, and potentially better parallel scan granularity. But the 2–5x estimate was based on pre-index state and no longer applies.

**Expected with 1A already in place**: ~1.1–1.2x (marginal). Not worth the schema migration effort.

#### 3B. Integer Term IDs Instead of UUIDs
Replace UUID columns with BIGINT. 8-byte integer comparisons ~2x faster than 16-byte UUID. Hash joins, sorts, and indexes all benefit. Index sizes drop ~50%.

**Expected**: 1.5–2x across all queries. Multiplicative with everything else.

### Priority 2: Planner Hints (Low Effort)

#### 2B. GEQO Tuning
`SET geqo_threshold = 16` for queries with 12–15 tables. Measure planning time tradeoff.

#### 2D. pg_hint_plan Extension
Use `/*+ Leading(...) */` hints to force join order on specific query shapes. Could be emitted by the SQL generator when the join topology is known.

### Priority 3: Emitter-Level (Medium Effort)

#### 2E. Selective LIMIT Pushdown
For `ORDER BY ... LIMIT N` queries, push the LIMIT into the innermost subquery where the ordering column is available. PG can use a top-N heap sort instead of sorting the full result.

#### 2F. Predicate-Aware Join Ordering
Use per-predicate cardinality statistics (stored in a metadata table) to order joins by selectivity in the emitter, rather than relying solely on PG's planner estimates.

---

## Benchmark: SPARQL-Generated vs Hand-Written SQL (2026-03-03)

| Query | SPARQL | Hand-written | Rows | Status |
|-------|-------:|-------------:|-----:|--------|
| Q1. Frame lookup (given URI) | 4.3ms | 7.3ms | 1 | ✅ SPARQL faster |
| Q2. Edges connected to frame | 2.6ms | 4.0ms | 2 | ✅ SPARQL faster |
| Q3. Frame→Slot→Entity (source) | 4.9ms | 5.1ms | 1 | ✅ Near parity |
| Q4. Full traversal: src→frame→dst | 29.9ms | 28.8ms | 1 | ✅ Near parity |
| Q5. Open traversal (LIMIT 10) | 46.5ms | 33.4ms | 10 | ✅ 1.4x gap |

## End-to-End Timing: "Happy Words" Query (warm, pool pre-init)

13-table traversal + CONTAINS text filter + LIMIT 50 → **129ms wall clock**

| Phase | Time | Notes |
|-------|-----:|-------|
| Sidecar (Jena parse) | 41ms | SPARQL → algebra JSON over HTTP |
| Mapper | 0.1ms | JSON → Python IR |
| Collect | 0.1ms | IR tree walk |
| Materialize | 15ms | Batch resolve URIs → UUIDs (shared conn) |
| Resolve | 0.0ms | Alias assignment |
| Emit | 0.4ms | SQL string generation |
| Substitute | 0.0ms | UUID token replacement |
| Execute | 72ms | PostgreSQL runs query |
| **Total** | **129ms** | |

Previously 39,000ms before text filter pushdown optimization.

## Completed Optimizations

- [x] **JOIN ON TRUE → proper ON clauses** — tagged_constraints in IR (2026-03-03)
- [x] **Aggregate alias ORDER BY fix** — check agg_sql_map before text resolution (2026-03-03)
- [x] **Inner/outer query split** — quad-only inner subquery + term joins outer (pre-existing)
- [x] **CTE for constant lookups** — _const CTE avoids repeated term table scans (pre-existing)
- [x] **Pre-filtered term subquery** — inner term joins filter by UUID presence (pre-existing)
- [x] **Constant materialization** — batch DB query resolves ontology URIs to UUIDs, substituted as literals into SQL. Eliminates CTE overhead for constants. (2026-03-03)
- [x] **Greedy join reordering** — reorder quad tables in emit phase to prevent cartesian products from disconnected triple pattern islands. Constants-first, co-references next. (2026-03-03)
- [x] **FILTER / LEFT JOIN fix** — `OpLeftJoin.exprs` (OPTIONAL's own conditions) stored separately in `left_join_exprs` → ON clause. Outer FILTER expressions stay in `filter_exprs` → WHERE clause. Three files: IR, collect, emit. (2026-03-03)
- [x] **Filter pushdown into LEFT JOIN children** — FILTER expressions referencing only left-side variables pushed into left child's plan before emission, avoiding full join materialization before filtering. (2026-03-03)
- [x] **Text filter → quad constraint pushdown** — CONTAINS/REGEX/STRSTARTS/STRENDS/equality on SPARQL variables converted to `uuid IN (SELECT term_uuid FROM term WHERE ...)` at quad level. Leverages GIN trigram index. **92x speedup** on text search queries. (2026-03-03)
- [x] **Connection reuse** — orchestrator opens one pool connection shared across materialize and execute phases. Eliminates cold-start connection overhead. Materialize dropped from 551ms → 15ms. (2026-03-03)
- [x] **`_needed_vars` fix** — when `select_vars` is None, all vars are needed for projection regardless of filter_exprs presence. Prevents incorrect term JOIN pruning on child plans. (2026-03-03)
- [x] **Detailed timing instrumentation** — generate_sql exposes sub-phase timings (collect, materialize, resolve, emit, substitute). Orchestrator propagates as `generate_detail`. (2026-03-03)
- [x] **Context_uuid graph lock** — `aliases.graph_uri` applied as first constraint per quad in `_collect_bgp`. AND-ed with SPARQL `GRAPH` clause constraints. None by default; callers can enforce a specific graph. (2026-03-03)
- [x] **`sql_only` mode** — orchestrator `execute(sparql, sql_only=True)` returns generated SQL without executing. Useful for debugging and EXPLAIN ANALYZE. (2026-03-03)
- [x] **CTE MATERIALIZED for subquery JOINs** — `_emit_join` auto-detects when the left child has a LIMIT (bounded subquery) and wraps it as `WITH ... AS MATERIALIZED`. Prevents PG from inlining the subquery into a flat join. Query 5c: 42s → 12.9s. (2026-03-03)
- [x] **sqlglot optimizer integration** — optional post-emit optimization via `optimize=True` flag. Applies safe passes: pushdown_predicates, simplify, eliminate_joins, eliminate_ctes. Verified to preserve MATERIALIZED CTEs. ~22ms overhead. (2026-03-03)
- [x] **EXPLAIN ANALYZE benchmarking** — `query_wordnet.py` supports `--optimize on|off|both` with dual metrics (Python wall time + PG EXPLAIN execution time). Fresh connections for EXPLAIN to minimize cache effects. (2026-03-03)
- [x] **Fuseki vs PG benchmark** — `benchmark_fuseki_vs_sql.py` compares same SPARQL queries against Jena TDB and PostgreSQL. (2026-03-04)
- [x] **Covering composite indexes (1A)** — `idx_quad_cspo`, `idx_quad_cpos`, `idx_quad_cosp` on `wordnet_exp_rdf_quad`. Enables index-only scans for all triple pattern access patterns. 5b: 13.6s → 6.6s (2x). (2026-03-04)
- [x] **Extended multi-column statistics (2A)** — `STATISTICS 1000` per UUID column + extended `dependencies`/`ndistinct` stats. Better cardinality estimates. 5c: 18s → 8.2s (2.2x). (2026-03-04)
- [x] **Wide-quad materialized view (1B) — TESTED, REJECTED** — pre-joined text inline. Wider rows destroy PG buffer cache efficiency; 2–32x slower on all query types. (2026-03-04)
- [x] **LATERAL join rewrite (2C) — TESTED, REJECTED** — automatic CROSS JOIN LATERAL for multi-hop patterns. ~9% warm-cache benefit on 5b but hangs on 10+ table queries due to forced nested-loop evaluation. (2026-03-04)

## Multi-Hop Benchmark Queries (7a–7d, 2026-03-04)

Added 4-hop pathway queries to stress-test deep graph traversal:

| Query | Pattern | Rows | Time | Quad Tables |
|---|---|---:|---:|---:|
| 7a. a→b→c→d→e from "happy" | 4-hop forward, unconstrained | 211,977 | 11.7s | 46 |
| 7b. Hop 3 = Hyponym only | 4-hop, mid-chain type filter | 1,700 | 587ms | 46 |
| 7c. Last entity = VerbSynset | 4-hop, endpoint type filter | 3,273 | 6.7s | 47 |
| 7d. Reversed SPARQL order | Same as 7c, patterns reversed | 3,273 | 6.9s | 47 |

### Key Findings

- **SPARQL source order is now independent** for multi-hop queries. The fingerprint tiebreaker (see below) ensures identical triple patterns produce the same join chain regardless of SPARQL pattern order. 7c and 7d return identical rows (3,273) with comparable performance.
- **Mid-chain filters are highly effective**: 7b constrains hop 3 to Hyponym edges (89K frames), reducing 211K results to 1,700 — a 5x speedup vs unconstrained 7a.
- **Endpoint filters are less effective**: 7c constrains only the final entity type, so all 4 hops execute before filtering. Still 1.8x faster than 7a due to reduced output.

---

## Optimization Implementation Results (2026-03-04, continued)

### ✅ Adaptive Planner Hints — APPLIED, EFFECTIVE

Two-tier strategy based on join count:
- **9–14 tables**: Raise both `join_collapse_limit` and `geqo_threshold` to `N+1` → exhaustive planning. 14! is feasible, 16! is not.
- **15+ tables**: Disable GEQO only (`geqo_threshold = N+1`) but keep `join_collapse_limit = 8` (default). This makes PG respect our heuristic's written join order at the macro level while locally reordering within groups of 8. Testing showed `jcl=14` with 38 tables causes 5x planning overhead (exponential), while `jcl=8` + no GEQO is consistently fastest.

**Result**: Ensures PG's exhaustive planner handles medium-complexity queries. No measurable overhead on planning time at N≤14.

### ✅ Predicate Cardinality Stats (MV) — APPLIED, EFFECTIVE

Created materialized views for predicate cardinality:
```sql
CREATE MATERIALIZED VIEW {space}_rdf_stats AS
SELECT predicate_uuid, object_uuid, COUNT(*) AS row_count
FROM {space}_rdf_quad GROUP BY 1, 2;

CREATE MATERIALIZED VIEW {space}_rdf_pred_stats AS
SELECT predicate_uuid, COUNT(*) AS row_count, COUNT(DISTINCT object_uuid) AS distinct_objects
FROM {space}_rdf_quad GROUP BY 1;
```

Stats loaded into `AliasGenerator` at compile time, cached per `space_id`. Used by `_reorder_joins` as a **tiebreaker** when connectivity scores are equal — prefer lower cardinality (more selective) tables first.

**Result**: 7c improved from 15s → 7s (2x) due to better within-cluster table ordering.

### ✅ ILIKE Text Filter Anchor Detection — APPLIED, EFFECTIVE

When a text-filter pushdown (ILIKE IN subquery) is present, detect it as the most selective anchor. Use the co-referenced entity table (the table sharing the ILIKE table's subject variable) as the chain root. This ensures the query starts from the selective text filter regardless of SPARQL pattern order.

**Result**: Enables correct chain root selection for reversed-order queries. Critical for SPARQL-order independence.

### ⏸️ Semi-Join Pushdown — IMPLEMENTED, DISABLED

Converts filter-only quad tables (subject=coref, pred=const, obj=const) into `IN (SELECT subject_uuid FROM rdf_quad WHERE ...)` subqueries on the binding table. Eliminates a separate JOIN and allows earlier filtering.

**Result**: 1.4x improvement for endpoint filters (7c/7d manual test), but **42x regression** on mid-chain filters (7b: 472ms → 18s). The pushdown removes a JOIN that PG was using effectively as an index condition.

**Action**: Disabled. Will re-enable with selectivity-guided heuristic: only push down tables at the end of the chain where the filter happens too late, not mid-chain filters that PG already handles well.

### ✅ Deterministic Fingerprint Tiebreaker — APPLIED, CRITICAL

When the greedy placement algorithm encounters ties (same connectivity score and same cardinality), the previous implementation broke ties by SPARQL source order (alias numbering). This meant identical triple patterns with different SPARQL ordering could produce different join chains → different GEQO plans → wildly different performance (7d timed out while 7c ran in 6.7s).

**Fix**: Pre-compute a deterministic "fingerprint" per quad table from its constraint content (predicate UUID, object UUID, co-reference column names). Use this as the final tiebreaker in the greedy score: `(connectivity, -cardinality, fingerprint)`. Since fingerprints are derived from triple pattern content (not alias names), identical patterns always produce the same chain.

**Result**: 7d (reversed SPARQL order) went from **timeout → 6.9s**, matching 7c's 6.3s. Row counts match exactly (3,273). SPARQL source order is now fully independent for join ordering.

---

## Next Steps

### Priority 1: Emitter-Level Pattern Rewrites (High Impact)

#### CTE Staging for Multi-Hop Queries — IMPLEMENTED, DISABLED

Implemented in `jena_sql_emit.py` (`_build_staged_inner`). Splits large join chains into per-hop MATERIALIZED CTEs with bridge variable pass-through. Generates correct SQL with 4 stages for 4-hop queries.

**Finding**: CTE staging **hurts** multi-hop traversals (7b: 552ms → 5,487ms). Root cause: `AS MATERIALIZED` forces eager evaluation of all intermediate rows (growing fan-out → hundreds of thousands of rows materialized at each stage). The flat join with nested loops is lazy — PG only follows paths that match, pruning dead ends early. Without `MATERIALIZED`, PG 12+ inlines single-reference CTEs, collapsing them back to a flat join with zero benefit.

The hand-written `happy_frame_query_17.sql` succeeds because it materializes only the highly-selective first CTE (185 "happy" entities). Multi-hop traversals have growing intermediate results, making eager materialization counterproductive.

**Status**: Code ready but disabled (`_CTE_STAGE_THRESHOLD = 999`). Could be useful for query shapes with selective intermediate filters (e.g., materialize only the text-filter stage).

#### ✅ Edge Structure MV Integration — IMPLEMENTED

Implemented in `jena_sql_edge_mv.py`. Detects hasEdgeSource + hasEdgeDestination quad pairs sharing the same subject variable and replaces each pair with a single lookup on `{space}_edge_mv(edge_uuid, source_node_uuid, dest_node_uuid, context_uuid)`.

**MV auto-creation**: `ensure_edge_mv()` creates the MV and 3 indexes if missing:
- `(source_node_uuid, dest_node_uuid)` — forward traversal
- `(dest_node_uuid, source_node_uuid)` — reverse traversal
- `(edge_uuid)` — edge entity lookup

**Key lesson**: indexes must NOT have `context_uuid` as leading column — most queries don't filter on context, and PG can't use the index for source/dest lookups with an unfiltered leading column.

**Results (warm cache)**:

| Query | Before | After (MV+noGEQO) | Speedup | Tables |
|---|---:|---:|---|---|
| 3c. Full edge traversal | 437ms | 28ms | **15x** | 10→8 |
| 4a. Hyponym relationships | 1,480ms | 188ms | **8x** | 11→9 |
| 5b. Entity degree | 3,654ms | 2,012ms | **1.8x** | 6→5 |
| 5c. Subquery top-5 | 7,458ms | 4,749ms | **1.6x** | 17→14 |
| 7a. Unconstrained 4-hop | 11,614ms | 9,877ms | **1.2x** | 46→38 |
| 7b. Hyponym 4-hop | 566ms | 552ms | ~same | 46→38 |
| 7c. VerbSynset 4-hop | 6,337ms | 4,693ms | **1.4x** | 47→39 |
| 7d. Reversed 4-hop | 6,877ms | 4,412ms | **1.6x** | 47→39 |

Multi-hop queries reduce from 46-47 → 38-39 tables (8 fewer JOINs). Combined with GEQO-disable (see Adaptive Planner Hints), PG respects our heuristic's join order and fully benefits from the reduced table count.

#### Frame-Entity MV: Pre-Computed Slot+Edge Chain

**MV Hierarchy** (each level subsumes the previous):

1. **Edge MV** (implemented): `(edge_uuid, source, dest)` — 570K rows. General for ALL edge traversals. Eliminates hasEdgeSource+hasEdgeDestination quad pairs.
2. **hasFrame/hasSlot MVs** (not needed): Would be subsets of edge MV data with smaller indexes. The only benefit is index size — marginal given PG's existing index-only scans on the edge MV.
3. **Frame-Entity MV** (implemented): `(frame_uuid, source_entity_uuid, dest_entity_uuid)` — one row per frame (285K rows for wordnet). Pre-computes the FULL slot+edge chain using conditional aggregation. **Eliminates 5 tables per hop.**

**Implementation**: `jena_sql_frame_entity_mv.py` — `ensure_frame_entity_mv()` creates the MV using `(array_agg(...) FILTER (WHERE slot_type = src/dst))[1]` from the edge_mv + quad tables. `rewrite_frame_entity_mv()` detects slot+edge patterns in the IR and replaces 6 tables per hop with 1 frame_entity_mv lookup. Wired into `jena_sql_generator.py` as Pass 1.8 (after edge MV rewrite).

**Note on frame chaining**: Frames can point to other frames (entity → frame → frame → ... → slot). The frame_entity MV handles the entity-slot-edge-frame pattern — the common 1-hop case. For deeper frame chains, each hop uses the edge MV individually.

**Benchmark results** (frame_entity MV + edge MV + GEQO-disable, best of 3):

| Query | Rows | Edge MV only | + Frame-Entity MV | Speedup | Tables |
|---|---|---|---|---|---|
| 7a. Unconstrained 4-hop | 211,977 | 9,877ms | 6,659ms | **1.5x** | 38→18 |
| 7b. Hyponym 4-hop | 1,700 | 552ms | 90ms | **6.1x** | 38→18 |
| 7c. VerbSynset 4-hop | 3,273 | 4,693ms | 1,243ms | **3.8x** | 39→19 |
| 7d. Reversed 4-hop | 3,273 | 4,412ms | 521ms | **8.5x** | 39→19 |

With `LIMIT 500`, 7a executes in ~41ms. The 7a uncapped time is dominated by materializing 212K result rows. 18 tables is under the GEQO threshold — PG does fully exhaustive planning.

**Note**: For datasets like lead_dataset_exp that already have `hasFrame`/`hasSlot` as direct quads, those properties serve the same role but as actual data rather than MVs. MVs are preferred: no data duplication, auto-derived from edge structure, REFRESH on data change.

### Priority 2: Planner Hints & Index Tuning (Medium Impact)

#### Semi-Join Pushdown with Selectivity Guard
Re-enable `_apply_semijoin_pushdown` with a selectivity-guided heuristic: only push down filter-only quad tables at the end of the chain (endpoint filters) where the filter happens too late. Skip mid-chain filters that PG already handles efficiently as index conditions. Use predicate cardinality from the stats MV to decide.

#### Partial Indexes for High-Frequency Predicates
Auto-create predicate-specific partial indexes for top-N predicates per space (e.g. hasEdgeSource, hasEdgeDestination, hasSlotType). Much smaller than full composite indexes. See `sql_scripts/create_edge_indexes.sql` and `create_simple_edge_indexes.sql`. Marginal benefit with existing SPO/POS/OSP composites but may help targeted lookups.

#### work_mem Tuning
`SET LOCAL work_mem = '256MB'` for queries with 10+ quad tables. Allows larger in-memory hash tables, avoiding temp file spills. Trivial to implement in the orchestrator alongside the existing adaptive `join_collapse_limit`.

#### pg_hint_plan (2D)
Emit explicit `/*+ Leading(...) */` hints to force join order for known query shapes. Requires the pg_hint_plan extension.

### Priority 3: Grouping URI → Materialized View Migration (High Impact, Medium Effort)

#### Background: Grouping URIs
The current system stores grouping properties as actual triples:
- `?s entityGraphURI <entity123>` — all nodes/edges belonging to entity123's graph
- `?s frameGraphURI <frame456>` — all nodes/edges belonging to frame456's graph

These are effectively a manually maintained materialized index stored as triples. They work but:
- **Data duplication**: every member node gets an extra triple per grouping
- **Maintenance burden**: insert/delete must update grouping triples
- **Mixed concerns**: structural metadata lives alongside content data

#### Proposed: General Membership MVs
Replace grouping URI triples with MVs derived from the edge structure:

```sql
-- Entity membership MV: all nodes reachable from an entity via edges
CREATE MATERIALIZED VIEW {space}_entity_members_mv AS
SELECT
    root_entity_uuid,
    member_uuid,
    depth  -- 0=entity, 1=frame, 2=slot
FROM (
    -- depth 0: the entity itself
    -- depth 1: frames connected via edge→slot→entity
    -- depth 2: slots connected via edge from frames
    ...
);

-- Frame membership MV: all nodes belonging to a frame
CREATE MATERIALIZED VIEW {space}_frame_members_mv AS
SELECT
    frame_uuid,
    member_uuid,
    depth  -- 0=frame, 1=slots
FROM ...;
```

**Benefits**:
- No extra triples in rdf_quad — cleaner data model
- Auto-derived from edge structure — `REFRESH MATERIALIZED VIEW` on data change
- Can serve both query optimization (JOIN reduction) and grouping lookups (`?s entityGraphURI <e>`)
- Generalizes the frame_entity MV: membership MVs at different depths provide different query shortcuts

**Relationship to frame_entity MV**: The frame_entity MV (`frame, src_entity, dst_entity`) is a specialized, query-optimized projection of the frame membership MV. It's the immediate target for JOIN reduction. The general membership MVs are a longer-term replacement for grouping URI triples.

### Priority 4: Schema-Level Changes (High Impact, High Effort)

#### Integer Term IDs
Replace UUID columns with BIGINT. 8-byte integer comparisons ~2x faster than 16-byte UUID. Hash joins, sorts, and indexes all benefit. Index sizes drop ~50%. Multiplicative with all other optimizations.

### Deferred

#### sqlglot AST Migration
The sqlglot post-emit optimizer is integrated but adds minimal benefit on warm-cache queries (PG's planner finds the same plan regardless). The full emit-phase AST migration remains a future option for:
- Dialect portability (MySQL, DuckDB)
- Automatic join rewriting
- Validation and debugging
