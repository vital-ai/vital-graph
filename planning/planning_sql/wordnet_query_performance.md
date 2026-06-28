# WordNet Query Performance Analysis

Investigation of slow queries in the WordNet dataset benchmark and optimization
opportunities for the SPARQL→SQL v2 pipeline.

**Date**: 2026-03-08
**Dataset**: WordNet KGFrames (`wordnet_exp`, 7,045,871 quads, 1,851,810 terms)
**Benchmark script**: `vitalgraph_sparql_sql/scripts/query_wordnet.py`

---

## 1. Dataset Profile

| Table | Rows | Size |
|-------|------|------|
| `wordnet_exp_rdf_quad` | 7,045,871 | 4.6 GB |
| `wordnet_exp_term` | 1,851,810 | 985 MB |

Key cardinalities:
- **predicate_uuid**: 14 distinct values (out of 7M rows)
- **subject_uuid**: 1,536,485 distinct values
- Avg triples per subject: ~4.6

### Existing Indexes (13 total)

Standard quad-store indexes are in place:

| Index | Columns |
|-------|---------|
| `idx_quad_cspo` | context, subject, predicate, object |
| `idx_quad_cpos` | context, predicate, object, subject |
| `idx_quad_cosp` | context, object, subject, predicate |
| `..._predicate_uuid_idx` | predicate |
| `..._predicate_uuid_object_uuid_idx` | predicate, object |
| `..._subject_uuid_idx` | subject |
| `..._subject_uuid_predicate_uuid_idx` | subject, predicate |
| `..._object_uuid_idx` | object |
| `..._context_uuid_idx` | context |
| `..._context_uuid_predicate_uuid_idx` | context, predicate |
| `..._context_uuid_subject_uuid_idx` | context, subject |
| `..._context_uuid_predicate_uuid_object_uui_idx` | context, predicate, object |
| pkey | subject, predicate, object, context, quad_uuid, dataset |

The indexes are comprehensive. The slow queries **do use the indexes** — the
bottleneck is elsewhere.

---

## 2. Benchmark Results

25/25 queries passed. Slow queries (>1s wall time):

| # | Query | Rows | PG Plan | PG Exec | Wall | Category |
|---|-------|------|---------|---------|------|----------|
| 1a | Distinct predicates | 14 | 1ms | 9.0s | 8.9s | A |
| 7a | Multi-hop a→b→c→d→e | 212k | 38ms | 6.3s | 8.0s | C |
| 1b | Distinct rdf:type values | 4 | 13ms | 4.3s | 5.1s | A |
| 1e | Distinct slot types | 2 | 2ms | 5.0s | 4.9s | A |
| 2c | Count entities by type | 4 | 6ms | 0.9s | 4.8s | B |
| 5b | Entity degree (outgoing) | 15 | 8ms | 4.3s | 4.6s | B |
| 5c | Top 5 most-connected + join | 20 | 18ms | 3.5s | 3.6s | B |
| 5a | Total triple count | 1 | 24ms | 3.1s | 2.6s | A |
| 4b | Count by frame type | 22 | 2ms | 1.9s | 2.5s | A |

Fast queries (<100ms wall time):

| # | Query | Wall |
|---|-------|------|
| 2a | Sample entities with names | 12ms |
| 3a | Sample frames with type | 9ms |
| 3b | Frame → Slot → Entity | 35ms |
| 3c | Full edge traversal | 19ms |
| 3d | Traversal with names | 24ms |
| 4a | Hyponym relationships | 24ms |
| 6b | CONSTRUCT triples | 10ms |
| 7e | Happy frame query | 36ms |

---

## 3. Root Cause Analysis

### Category A: DISTINCT / GROUP BY on full-table scans

**Affected**: 1a, 1b, 1e, 4b, 5a

**Pattern**: Simple `SELECT DISTINCT ?var` or `GROUP BY ?var` over an
unfiltered BGP with millions of matching rows and very low result cardinality.

**Example**: Query 1a — `SELECT DISTINCT ?p WHERE { ?s ?p ?o } ORDER BY ?p`

The generated SQL:
```sql
SELECT DISTINCT *
FROM (
  SELECT t_v1.term_text AS v1, ...8 companion columns...
  FROM (
    SELECT q0.subject_uuid, q0.predicate_uuid, q0.object_uuid
    FROM wordnet_exp_rdf_quad AS q0
  ) AS sub
  JOIN wordnet_exp_term AS t_v1 ON sub.v1__uuid = t_v1.term_uuid
  ORDER BY t_v1.term_text
) AS p0
```

**What happens**:
1. Index Only Scan on `predicate_uuid_idx` → 7M rows (fast: 88ms/worker)
2. Memoized term lookup: only 14 misses (14 distinct predicates) but 7M hits
3. Sort 7M rows to disk (114 MB external merge)
4. DISTINCT deduplicates 7M → 14

**Why**: The PG planner cannot push DISTINCT below the term JOIN because it
doesn't know that `predicate_uuid → term_text` is a 1:1 functional dependency.
So it must resolve text for all 7M rows, sort them, then deduplicate.

**Ideal SQL** (what we should generate):
```sql
SELECT t_v1.term_text AS v1, ...
FROM (
  SELECT DISTINCT q0.predicate_uuid AS v1__uuid
  FROM wordnet_exp_rdf_quad AS q0
) AS sub
JOIN wordnet_exp_term AS t_v1 ON sub.v1__uuid = t_v1.term_uuid
ORDER BY t_v1.term_text
```

This deduplicates at the UUID level first (7M → 14 rows), then joins 14 rows
with the term table. Expected time: <10ms.

### Category B: GROUP BY + aggregation on large intermediate sets

**Affected**: 2c, 5b, 5c

**Pattern**: `GROUP BY ?var (COUNT(...))` where the BGP matches a large number
of quads. Same root cause as Category A — the GROUP BY should operate on UUIDs
before term resolution.

**Example**: Query 5b — Entity degree with GROUP BY + ORDER BY DESC + LIMIT 15

The GROUP BY happens after term JOINs for all projected variables. With
push-down, the GROUP BY would operate on UUIDs, then only the top-15 groups
would need term resolution.

### Category C: Inherently large result sets

**Affected**: 7a (4-hop traversal, 212k rows)

This query joins 45+ triple patterns across 4 hops. With 212k result rows,
the execution time (6.3s) is proportional to the output size. The edge MV
rewrite could help here — it doesn't exist yet for this space.

---

## 4. Proposed Optimization: DISTINCT / GROUP BY Push-Down

### 4.1 Concept

When DISTINCT or GROUP BY operates on variables from a BGP, push the
deduplication to the UUID level **before** the term JOIN. The term JOIN then
operates on the deduplicated set, which is typically orders of magnitude smaller.

This is a form of "aggregate push-down" — a well-known optimizer technique that
PG's planner cannot perform automatically because it doesn't know that
`term_uuid → term_text` is a 1:1 mapping.

### 4.2 Where to Implement

The push-down could be implemented at several levels:

**Option 1: emit_distinct.py rewrite** — Detect when the DISTINCT node sits
above a PROJECT above a BGP (with optional ORDER). Restructure the SQL to:
1. Inner: `SELECT DISTINCT uuid_columns FROM quad_scan`
2. Outer: `SELECT text_columns FROM (inner) JOIN term ON uuid_columns`

**Option 2: IR-level rewrite** — Add a new optimization pass after
`compute_text_needed_vars` that rewrites the plan tree to push DISTINCT/GROUP
below the term resolution boundary.

**Option 3: SQL-level hint** — Generate a CTE with `MATERIALIZED` to force PG
to evaluate the DISTINCT first:
```sql
WITH deduped AS MATERIALIZED (
  SELECT DISTINCT predicate_uuid FROM quad
)
SELECT t.term_text FROM deduped JOIN term t ON ...
```

### 4.3 Applicability

This optimization applies whenever:
1. DISTINCT or GROUP BY variables are all from the same BGP
2. The BGP has no FILTER that requires term text
3. The result cardinality is much lower than the scan cardinality

For the WordNet benchmark, this would fix queries 1a, 1b, 1e, 4b, and 5a
(collectively ~25s of the 51s total runtime).

### 4.4 Expected Impact

| Query | Current | Expected | Speedup |
|-------|---------|----------|---------|
| 1a. Distinct predicates | 8.9s | <50ms | ~180× |
| 1b. Distinct rdf:type | 5.1s | <100ms | ~50× |
| 1e. Distinct slot types | 4.9s | <50ms | ~100× |
| 4b. Count by frame type | 2.5s | <100ms | ~25× |
| 5a. Total triple count | 2.6s | <50ms | ~50× |
| 5b. Entity degree | 4.6s | <500ms | ~9× |
| **Total saved** | **28.6s** | **<1s** | |

---

## 5. Other Opportunities

### 5.1 Edge Materialized View for WordNet

The WordNet space doesn't have an edge MV yet. Creating one would help the
multi-hop queries (7a–7e) by collapsing the 8-quad edge traversal pattern
(frame + 2 slots + 2 slot edges + 2 slot values + frame type) into a single
MV lookup.

### 5.2 COUNT(*) Without Term JOINs

Query 5a (`SELECT (COUNT(*) AS ?total) WHERE { ?s ?p ?o }`) shouldn't need any
term JOINs at all — it just counts rows. The current `text_needed_vars`
optimization may be adding term JOINs due to the COUNT(*) fix. This could be
refined: plain `COUNT(*)` (without DISTINCT) doesn't need text for any variable.

### 5.3 Loose Index Scan for Low-Cardinality DISTINCT

For `SELECT DISTINCT predicate_uuid FROM quad`, PG doesn't natively support
"skip scan" / "loose index scan". A recursive CTE trick can simulate it:
```sql
WITH RECURSIVE dist AS (
  (SELECT min(predicate_uuid) AS v FROM quad)
  UNION ALL
  SELECT (SELECT min(predicate_uuid) FROM quad WHERE predicate_uuid > dist.v)
  FROM dist WHERE dist.v IS NOT NULL
)
SELECT v FROM dist WHERE v IS NOT NULL;
```
This finds all 14 distinct predicates with ~14 index probes instead of a 7M-row
scan. Combined with the push-down, this would make Category A queries near-instant.
