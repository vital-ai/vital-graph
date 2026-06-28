# Multi-Vector Query Planning

**Status**: Phase 1 (SPARQL-to-SQL pipeline) and Phase 2 (KG Query Criteria + REST API) are implemented and **end-to-end tested (7/7 pass)**. Phase 3 (oversampling + advanced fusion) is planned.

| Layer | Status | Key Files |
|-------|--------|-----------|
| Jena sidecar parsing | ✅ Done | `VectorGeoSparqlTest.java` (4 tests pass) |
| SPARQL-to-SQL pipeline | ✅ Done | `vg_functions.py` (extraction + CTE SQL generation) |
| Type inference | ✅ Done | `sql_type_generation.py` (→ `xsd:double`) |
| Expression dispatch | ✅ Done | `emit_expressions.py` (`_vg_function_to_sql`) |
| Pydantic models | ✅ Done | `kgentities_model.py`, `kgqueries_model.py` |
| SPARQL builder | ✅ Done | `kg_query_builder.py` (`_build_vector_geo_clauses`) |
| REST endpoint wiring | ✅ Done | `kgquery_endpoint.py` |
| End-to-end test | ✅ Passing (7/7) | `test_sparql_sql_multi_vector.py` (requires live server) |
| Oversampling / fusion | ⬜ Planned | Phase 3 |

---

## 1. Problem Statement

VitalGraph's SPARQL-to-SQL pipeline (see `planning_vector_geo/vector_geo_plan.md`) supports single-vector queries via custom BIND functions like `vg:vectorSimilarity` and `vg:hybridSearch`. Each returns a score that can be used in ORDER BY and FILTER.

However, real-world KG search often requires **multiple simultaneous vector searches** over different aspects of the same entity. For example:

- **KG Entity Type description** vector (e.g., "Company or corporation entity") — stored in `entity_type_default` index
- **KG Graph description** vector (e.g., "Acme Corp manufactures renewable energy panels") — stored in `entity_default` index
- **KG Document segment** vector — stored in `document_segments` index

The question: when a query involves two or more vector searches, how do we **combine their scores** into a single ranking?

### Motivating Example

A naive approach uses separate BINDs with arithmetic — valid SPARQL but creates SQL generation challenges:

```sparql
# Naive: separate BINDs → independent LATERAL JOINs → tiny intersection
BIND(vg:vectorSimilarity(?entity, "technology company", "entity_type_default") AS ?type_score)
BIND(vg:vectorSimilarity(?entity, "renewable energy manufacturing", "entity_default") AS ?graph_score)
BIND(?type_score * 0.3 + ?graph_score * 0.7 AS ?combined_score)
```

**Problems**: Each LATERAL has its own top-K; intersection may be empty. Emitter must detect the pattern and merge.

The solution is a **single function** that takes all vectors at once — the emitter directly generates UNION + fusion SQL:

```sparql
# Primary: single function → direct UNION + re-rank SQL
BIND(vg:multiVectorSimilarity(
    ?entity,
    "technology company", "entity_type_default", 0.3,
    "renewable energy manufacturing", "entity_default", 0.7
) AS ?score)
FILTER(?score > 0.5)
ORDER BY DESC(?score) LIMIT 20
```

---

## 2. Weaviate's Approach: Research Summary

Weaviate (v1.26+) provides built-in multi-vector search through **named vectors** and **multi-target vector search**. Their approach informs our design.

### 2.1 Named Vectors

Collections can have multiple named vector spaces, each with their own vectorizer, index, and distance metric:

```python
# Weaviate collection with two named vectors
client.collections.create(
    "Article",
    vector_config=[
        Configure.Vectors.text2vec_openai(
            name="title_vector",
            source_properties=["title"],
        ),
        Configure.Vectors.text2vec_openai(
            name="body_vector",
            source_properties=["body"],
        ),
    ],
)
```

**VitalGraph equivalent**: Our per-space vector index registry (`{space}_vector_index`) + per-index tables (`{space}_vec_{index_name}`) already provide this. Each entity can have embeddings in multiple indexes (e.g., `entity_default`, `entity_type_default`).

### 2.2 Multi-Target Vector Search (v1.26+)

Weaviate searches multiple vector spaces concurrently and combines results using a **join strategy**:

```python
from weaviate.classes.query import TargetVectors, MetadataQuery

response = collection.query.near_text(
    query="a wild animal",
    limit=2,
    target_vector=TargetVectors.manual_weights({
        "jeopardy_questions_vector": 10,
        "jeopardy_answers_vector": 50,
    }),
    return_metadata=MetadataQuery(distance=True),
)
```

#### Available Join Strategies

| Strategy | Formula | Description |
|----------|---------|-------------|
| **minimum** (default) | `min(d₁, d₂, ..., dₙ)` | Best match in any vector space wins |
| **sum** | `d₁ + d₂ + ... + dₙ` | Sum of all distances |
| **average** | `(d₁ + d₂ + ... + dₙ) / n` | Average of all distances |
| **manual_weights** | `w₁·d₁ + w₂·d₂ + ... + wₙ·dₙ` | Weighted sum of **raw** distances |
| **relative_score** | `w₁·norm(d₁) + w₂·norm(d₂) + ...` | Weighted sum of **normalized** distances |

#### Different Query Vectors per Target

Weaviate also allows specifying a **different query vector** (or query text) for each target vector space:

```python
response = collection.query.near_vector(
    near_vector={
        "questions_vector": v1,   # different query vector
        "answers_vector": v2,     # different query vector
    },
    target_vector=TargetVectors.relative_score({
        "questions_vector": 10,
        "answers_vector": 10,
    }),
)
```

This is the pattern that directly maps to our use case: searching entity type descriptions with one query text and entity graph descriptions with another.

### 2.3 Hybrid Search Fusion (BM25 + Vector)

Weaviate's hybrid search combines keyword (BM25) and vector results using fusion algorithms:

| Algorithm | How It Works | Pros | Cons |
|-----------|-------------|------|------|
| **Ranked Fusion** | Score = `1/(rank + 60)` per search; sum across searches | Simple, no normalization needed | Loses information about actual score magnitudes |
| **Relative Score Fusion** (default v1.24+) | Normalize each search's scores to [0,1]; weighted sum | Preserves relative score distributions | Requires knowing min/max in result set |

**Relative Score Fusion normalization**:
```
normalized_score = (score - min_score) / (max_score - min_score)
```

The `alpha` parameter controls weighting: `final = (1 - alpha) · bm25_score + alpha · vector_score`

### 2.4 Multi-Target + Hybrid (v1.27+)

Weaviate allows combining multi-target vector search with hybrid (BM25 + vector) search, creating a three-way fusion: BM25 + vector_space_1 + vector_space_2.

---

## 3. VitalGraph Current Architecture

### 3.1 Single Vector Query (Implemented)

From `vector_geo_plan.md §5.1`:

```sparql
BIND(vg:vectorSimilarity(?entity, "search text", "entity_default") AS ?score)
```

Generates SQL:
```sql
JOIN LATERAL (
    SELECT subject_uuid, 1 - (embedding <=> $vector_param) AS score
    FROM {space}_vec_entity_default
    WHERE context_uuid = (SELECT term_uuid FROM {space}_term WHERE term_text = $graph_uri)
    ORDER BY embedding <=> $vector_param
    LIMIT 20
) vec_1 ON vec_1.subject_uuid = q1.subject_uuid
```

The score is `1 - cosine_distance`, so range is [0, 1] where 1 = identical.

### 3.2 What Happens Today with Multiple BINDs

If a user writes two `vg:vectorSimilarity` BINDs in the same query today, each produces a separate LATERAL JOIN. The results are intersected (INNER JOIN semantics) — an entity must appear in **both** top-K results. This is problematic:

1. **Top-K intersection**: If vector_1 returns top 20 and vector_2 returns top 20, the intersection could be very small or empty
2. **No combined ranking**: Each LATERAL has its own `ORDER BY ... LIMIT`, but there's no combined score driving a single LIMIT
3. **No normalization**: Scores from different embedding models/dimensions aren't comparable without normalization

---

## 4. Primary Design: `vg:multiVectorSimilarity` Function

### 4.1 Core Insight

Rather than writing multiple independent `vg:vectorSimilarity` BINDs and combining them with SPARQL arithmetic (which forces the SQL emitter to detect and merge separate LATERAL JOINs after the fact), we define a **single function** that takes N vector searches at once. This mirrors Weaviate's single-call multi-target approach and lets the SQL emitter directly generate the UNION + fusion SQL without any pattern detection.

### 4.2 SPARQL Syntax

```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?name ?score WHERE {
    ?entity rdf:type haley:KGEntity .
    ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .

    BIND(vg:multiVectorSimilarity(
        ?entity,
        "technology company", "entity_type_default", 0.3,
        "renewable energy manufacturing", "entity_default", 0.7
    ) AS ?score)

    FILTER(?score > 0.4)
}
ORDER BY DESC(?score)
LIMIT 20
```

**Arguments**: `(subject_var, [query_text, index_name, weight]+ )`

- First arg: the subject variable to search
- Then repeating triplets: `(query_text, index_name, weight)`
- Weights are **auto-normalized** to sum to 1.0 — `(0.3, 0.7)` and `(3, 7)` produce identical results
- Combined score is always in [0, 1], making FILTER thresholds predictable

Jena parses this as a single `ExprFunctionN` node. The emitter reads `(n_args - 1) / 3` triplets directly — no pattern detection, no downstream BIND merging needed.

### 4.3 Why This Is Better Than Separate BINDs

| Concern | Separate BINDs | `vg:multiVectorSimilarity` |
|---------|---------------|---------------------------|
| **SQL generation** | Emitter must detect + merge independent LATERALs | Single AST node → direct fused SQL |
| **Candidate pool** | Each LATERAL has its own top-K; intersection may be empty | UNION of oversampled candidates from all vectors |
| **Score combination** | User writes arithmetic BIND; emitter must parse it | Weighted average computed internally |
| **Normalization** | User's responsibility | Handled inside the function (all scores are cosine similarity [0,1]) |
| **SPARQL complexity** | 3+ BINDs per query | Single BIND |

### 4.4 Jena AST Output (Confirmed)

Verified by `VectorGeoSparqlTest.java` — all multi-vector tests pass (2-vector, 3-vector, pre-computed vectors, combined with triple patterns):

```json
{
    "type": "ExprFunctionN",
    "functionIRI": "http://vital.ai/ontology/vitalgraph#multiVectorSimilarity",
    "args": [
        {"type": "ExprVar", "var": "entity"},
        {"type": "NodeValue", "node": {"type": "literal", "value": "technology company"}},
        {"type": "NodeValue", "node": {"type": "literal", "value": "entity_type_default"}},
        {"type": "NodeValue", "node": {"type": "literal", "value": "0.3", "datatype": "http://www.w3.org/2001/XMLSchema#decimal"}},
        {"type": "NodeValue", "node": {"type": "literal", "value": "renewable energy manufacturing"}},
        {"type": "NodeValue", "node": {"type": "literal", "value": "entity_default"}},
        {"type": "NodeValue", "node": {"type": "literal", "value": "0.7", "datatype": "http://www.w3.org/2001/XMLSchema#decimal"}}
    ]
}
```

The Python AST mapper extracts triplets: `args[1:]` in groups of 3 → `[(query, index, weight), ...]`.

**Test coverage** (in `vitalgraph-jena-sidecar/src/test/java/.../VectorGeoSparqlTest.java`):
- `testMultiVectorSimilarity_TwoVectors` — 7 args, 2 triplets ✅
- `testMultiVectorSimilarity_ThreeVectors` — 10 args, 3 triplets ✅
- `testMultiVectorNearby_PrecomputedVectors` — vector literals instead of text ✅
- `testMultiVectorSimilarity_CombinedWithOtherPatterns` — with triple patterns + additional FILTERs ✅

### 4.5 Generated SQL (Oversampled UNION + Re-rank)

```sql
WITH
v0 AS (
    SELECT subject_uuid, 1 - (embedding <=> $vec0) AS score
    FROM {space}_vec_entity_type_default
    WHERE context_uuid = $ctx
    ORDER BY embedding <=> $vec0
    LIMIT 100   -- oversample: final_limit * 5
),
v1 AS (
    SELECT subject_uuid, 1 - (embedding <=> $vec1) AS score
    FROM {space}_vec_entity_default
    WHERE context_uuid = $ctx
    ORDER BY embedding <=> $vec1
    LIMIT 100
),
candidates AS (
    SELECT subject_uuid FROM v0
    UNION
    SELECT subject_uuid FROM v1
)
SELECT c.subject_uuid,
    0.3 * COALESCE(v0.score, 0) + 0.7 * COALESCE(v1.score, 0) AS score
FROM candidates c
LEFT JOIN v0 ON v0.subject_uuid = c.subject_uuid
LEFT JOIN v1 ON v1.subject_uuid = c.subject_uuid
ORDER BY score DESC
LIMIT 20
```

**How it works**:
1. Each CTE does an HNSW index scan → top 100 candidates (oversample 5×)
2. UNION merges candidate pools (up to 200 unique subjects)
3. LEFT JOIN retrieves each candidate's score in each vector space (`COALESCE(score, 0)` for entities missing from a space)
4. Weighted sum → ORDER BY → final LIMIT 20

**Oversampling heuristic**: `oversample = min(final_limit * 5, 500)` per vector. Tunable via an optional parameter (see §4.7).

### 4.6 Variant: Pre-Computed Vectors

If the caller already has embedding vectors, use `vg:multiVectorNearby`:

```sparql
BIND(vg:multiVectorNearby(
    ?entity,
    "[0.1, 0.2, ...]", "entity_type_default", 0.3,
    "[0.4, 0.5, ...]", "entity_default", 0.7
) AS ?score)
```

Same structure, but the first element of each triplet is a vector literal string instead of text to vectorize. Skips the vectorization step — the emitter passes the vector directly to the `<=>` operator.

### 4.7 Optional Parameters

For advanced use, additional trailing arguments could control behavior:

```sparql
BIND(vg:multiVectorSimilarity(
    ?entity,
    "tech company", "entity_type_default", 0.3,
    "renewable energy", "entity_default", 0.7
    # future: optional trailing args for oversample factor, etc.
) AS ?score)
```

For now, defaults are sufficient. Oversampling factor and other tuning knobs are better exposed via the REST API / KG Query Criteria path (§7).

---

## 5. Secondary: Separate BINDs + SPARQL Arithmetic

For advanced users who need custom score formulas (e.g., multiplicative, conditional, non-linear), separate BINDs with standard SPARQL arithmetic remain available:

```sparql
BIND(vg:vectorSimilarity(?entity, "tech company", "entity_type_default") AS ?type_score)
BIND(vg:vectorSimilarity(?entity, "renewable energy", "entity_default") AS ?graph_score)

# Custom formula — product instead of weighted sum
BIND(?type_score * ?graph_score AS ?combined)
ORDER BY DESC(?combined) LIMIT 20
```

### 5.1 Emitter Optimization for Separate BINDs

When the emitter sees multiple `vg:vectorSimilarity` BINDs on the same subject variable, it should **widen the internal LIMIT** of each LATERAL JOIN (oversample) so the intersection is not artificially small. The downstream arithmetic BIND becomes a SQL expression over the joined scores.

This is a best-effort optimization — it won't produce results as good as `vg:multiVectorSimilarity` (which uses UNION instead of intersection), but it's correct and handles the general case.

### 5.2 When to Use Each

| Scenario | Use |
|----------|-----|
| Standard multi-vector search (weighted combination) | `vg:multiVectorSimilarity` |
| Custom formula (product, conditional, non-linear) | Separate BINDs + arithmetic |
| Mixing hybrid + vector searches | Separate BINDs (hybrid returns a pre-fused score) |

---

## 6. Score Fusion Internals (PostgreSQL)

All `vg:multiVectorSimilarity` queries use **weighted average** of cosine similarity scores as the default fusion. Since all scores are `1 - cosine_distance` ∈ [0, 1], they are directly comparable without normalization.

### 6.1 Default: Weighted Average

```
combined = w₁ · score₁ + w₂ · score₂ + ... + wₙ · scoreₙ
```

Weights are used as-is from the SPARQL arguments. If the user wants equal weighting, they pass equal weights (e.g., 1.0, 1.0).

### 6.2 UNION + Re-rank SQL Pattern (Primary)

See §4.5 above. This is the standard pattern for `vg:multiVectorSimilarity`.

### 6.3 Auto-Normalization for Mixed Models

When vector indexes use **different embedding models** (different dimensions, different providers, or different score distributions), raw weighted sum is misleading — a score of 0.8 from Model A doesn't mean the same as 0.8 from Model B. The emitter auto-detects this case and applies **relative score normalization**.

#### Detection

Each vector index in `{space}_vector_index` stores its model/provider/dimension. At SQL generation time:

```python
indexes = [get_vector_index_config(space_id, triplet.index) for triplet in triplets]
if len(set((idx.provider, idx.model, idx.dimension) for idx in indexes)) > 1:
    # Mixed models → normalize before combining
    return _build_normalized_union_rerank_sql(...)
else:
    # Same model → raw weighted sum is fine
    return _build_union_rerank_sql(...)
```

#### How Normalization Works

For each vector space, scores are normalized **within the oversampled candidate set** for that query:

```
norm_score = (score - min_score_in_candidates) / (max_score_in_candidates - min_score_in_candidates)
```

- The best-scoring candidate in that vector space → **1.0**
- The worst-scoring candidate in that vector space → **0.0**
- Everything between → linearly proportional

This makes scores from different models/dimensions directly comparable: a normalized 0.8 means "80% of the way between the worst and best match in this vector space for this query."

**Note**: Normalization is query-relative — the same entity can get different normalized scores depending on what other candidates are in the result set. This is the standard trade-off (same as Weaviate's `relativeScoreFusion`).

#### Generated SQL with Normalization

```sql
WITH
v0_raw AS (
    SELECT subject_uuid, 1 - (embedding <=> $vec0) AS score
    FROM {space}_vec_entity_type_default       -- Model A, 500-dim
    WHERE context_uuid = $ctx
    ORDER BY embedding <=> $vec0
    LIMIT 100
),
v0_norm AS (
    SELECT subject_uuid,
        CASE WHEN MAX(score) OVER () = MIN(score) OVER () THEN 1.0
             ELSE (score - MIN(score) OVER ()) / (MAX(score) OVER () - MIN(score) OVER ())
        END AS score
    FROM v0_raw
),
v1_raw AS (
    SELECT subject_uuid, 1 - (embedding <=> $vec1) AS score
    FROM {space}_vec_entity_default             -- Model B, 300-dim
    WHERE context_uuid = $ctx
    ORDER BY embedding <=> $vec1
    LIMIT 100
),
v1_norm AS (
    SELECT subject_uuid,
        CASE WHEN MAX(score) OVER () = MIN(score) OVER () THEN 1.0
             ELSE (score - MIN(score) OVER ()) / (MAX(score) OVER () - MIN(score) OVER ())
        END AS score
    FROM v1_raw
),
candidates AS (
    SELECT subject_uuid FROM v0_norm
    INTERSECT
    SELECT subject_uuid FROM v1_norm
)
SELECT c.subject_uuid,
    0.3 * v0.score + 0.7 * v1.score AS score
FROM candidates c
JOIN v0_norm v0 ON v0.subject_uuid = c.subject_uuid
JOIN v1_norm v1 ON v1.subject_uuid = c.subject_uuid
ORDER BY score DESC
LIMIT 20
```

**Key difference from §4.5**: The `v0_norm` / `v1_norm` CTEs add window-function normalization before combining. The final weighted sum now operates on comparable [0, 1] normalized scores regardless of the underlying model.

#### When Same Model — Skip Normalization

If all indexes use the same model (e.g., both use `text-embedding-3-small` at 1536-dim), the emitter uses the simpler SQL from §4.5 without normalization CTEs. The scores are already directly comparable.

### 6.4 Future: Additional Configurable Fusion Strategies

If needed, a strategy parameter could be added to the function:

| Strategy | Formula | When Useful |
|----------|---------|-------------|
| **weighted_sum** (default) | `w₁·s₁ + w₂·s₂` | Scores on same scale (cosine similarity) |
| **relative_score** | Normalize each to [0,1] first, then weighted sum | Different distance metrics or embedding models |
| **ranked** | `1/(rank + 60)` per search, then sum | When absolute scores aren't meaningful |
| **minimum** | `min(s₁, s₂)` | "Must match well in all spaces" |

**Relative Score Fusion SQL** (for reference — not needed when all vectors use cosine):

```sql
-- Normalization via window functions
WITH v0_raw AS (...),
v0_norm AS (
    SELECT subject_uuid,
        CASE WHEN MAX(score) OVER () = MIN(score) OVER () THEN 0.5
             ELSE (score - MIN(score) OVER ()) / (MAX(score) OVER () - MIN(score) OVER ())
        END AS norm_score
    FROM v0_raw
), ...
```

**Ranked Fusion SQL** (Reciprocal Rank Fusion):

```sql
WITH v0_ranked AS (
    SELECT subject_uuid,
        1.0 / (ROW_NUMBER() OVER (ORDER BY embedding <=> $vec0) + 60) AS rank_score
    FROM {space}_vec_entity_type_default
    WHERE context_uuid = $ctx
), ...
```

These are available if we add a strategy parameter to `vg:multiVectorSimilarity` later.

### 6.4 Hybrid + Multi-Vector (Three-Way Fusion)

Combining BM25 full-text search with multiple vector searches uses separate BINDs:

```sparql
BIND(vg:hybridSearch(?entity, "renewable energy company", "entity_default", 0.5) AS ?hybrid_score)
BIND(vg:vectorSimilarity(?entity, "technology sector", "entity_type_default") AS ?type_score)
BIND(0.6 * ?hybrid_score + 0.4 * ?type_score AS ?combined)
ORDER BY DESC(?combined) LIMIT 20
```

This is a three-way fusion: BM25 + vector_1 (from hybrid) + vector_2 (from type). The `hybridSearch` function already fuses BM25+vector internally; the outer arithmetic adds a third signal.

---

## 7. KG Query Criteria Integration

### 7.1 Data Model Extensions

```python
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum

class JoinStrategy(str, Enum):
    MINIMUM = "minimum"
    SUM = "sum"
    AVERAGE = "average"
    MANUAL_WEIGHTS = "manual_weights"
    RELATIVE_SCORE = "relative_score"
    RANKED = "ranked"

@dataclass
class WeightedVectorCriteria:
    """A single vector search with a weight for multi-vector fusion."""
    query_text: str
    index_name: str
    weight: float = 1.0
    # Optional: pass a pre-computed vector instead of text
    query_vector: Optional[List[float]] = None

@dataclass
class MultiVectorSearchCriteria:
    """Multi-vector search with fusion strategy."""
    vectors: List[WeightedVectorCriteria]
    join_strategy: JoinStrategy = JoinStrategy.RELATIVE_SCORE
    min_combined_score: Optional[float] = None
    limit: int = 20
    oversample_factor: int = 5  # candidates per vector = limit * oversample_factor
```

### 7.2 REST API Request Format

```json
POST /api/kgentities/query
{
    "space_id": "my_space",
    "graph_id": "urn:graph:main",
    "multi_vector_search": {
        "vectors": [
            {
                "query_text": "technology company",
                "index_name": "entity_type_default",
                "weight": 0.3
            },
            {
                "query_text": "renewable energy manufacturing",
                "index_name": "entity_default",
                "weight": 0.7
            }
        ],
        "join_strategy": "relative_score",
        "min_combined_score": 0.4,
        "limit": 20
    }
}
```

### 7.3 KGQueryCriteriaBuilder Extension

The builder generates a single `vg:multiVectorSimilarity` BIND:

```python
def _build_multi_vector_clauses(self, criteria: MultiVectorSearchCriteria) -> str:
    """Generate SPARQL clause for multi-vector search."""
    # Build the repeating triplet args: query_text, index_name, weight
    fn = "vg:multiVectorNearby" if criteria.vectors[0].query_vector else "vg:multiVectorSimilarity"
    triplet_args = []
    for vc in criteria.vectors:
        arg = json.dumps(vc.query_vector) if vc.query_vector else vc.query_text
        triplet_args.append(f'"{arg}", "{vc.index_name}", {vc.weight}')

    args_str = ",\n        ".join(triplet_args)
    clauses = [f'BIND({fn}(\n        ?entity,\n        {args_str}\n    ) AS ?_combined_score)']

    if criteria.min_combined_score is not None:
        clauses.append(f"FILTER(?_combined_score > {criteria.min_combined_score})")

    return "\n".join(clauses)
```

---

## 8. SQL Emitter Changes

### 8.1 Handling `vg:multiVectorSimilarity` in the AST Mapper

The `ExprFunctionN` node with IRI `vg:multiVectorSimilarity` is recognized by `_vg_function_to_sql()` in `emit_expressions.py` (same dispatch point as existing `vg:vectorSimilarity`, `vg:geoDistance`, etc.).

The mapper extracts:
- `args[0]` → subject variable
- `args[1:]` → repeating triplets `(query_text, index_name, weight)`

```python
def _emit_multi_vector_similarity(args: List, ctx: EmitContext) -> str:
    """Generate UNION + re-rank SQL for vg:multiVectorSimilarity."""
    subject_var = args[0]  # ExprVar
    triplets = []
    for i in range(1, len(args), 3):
        triplets.append({
            'query': args[i],      # text or vector literal
            'index': args[i+1],    # index name
            'weight': args[i+2],   # numeric weight
        })

    # Each triplet → a CTE with HNSW top-K scan
    # UNION all candidate sets
    # LEFT JOIN to get each candidate's score per vector
    # Weighted sum → final score expression
    return _build_union_rerank_sql(subject_var, triplets, ctx)
```

### 8.2 Vectorization Requests

Each triplet with a text query (not a pre-computed vector) generates a `VectorRequest` — same mechanism used by `vg:vectorSimilarity`. The orchestrator (`vg_resolve.py`) resolves all `__VG_EMBED_*__` placeholders before SQL execution.

### 8.3 Fallback for Separate BINDs

When the emitter sees multiple independent `vg:vectorSimilarity` BINDs on the same subject, it widens each LATERAL's internal LIMIT (oversample heuristic) but otherwise generates independent JOINs. This is correct but uses intersection semantics rather than UNION — less ideal than `vg:multiVectorSimilarity`.

---

## 9. Comparison: Weaviate vs VitalGraph pgvector

| Capability | Weaviate | VitalGraph (pgvector) |
|------------|----------|----------------------|
| Named vectors per object | ✅ Built-in `vectorConfig` | ✅ Per-index tables (`{space}_vec_{idx}`) |
| Different vectorizers per vector | ✅ Each named vector has own vectorizer | ✅ Each index has own provider/model |
| Multi-target search | ✅ `target_vector=[...]` | 🔧 `vg:multiVectorSimilarity` (single BIND) |
| Different query per target | ✅ `near_vector={name: vec, ...}` | ✅ Each BIND has its own query text |
| Join strategies (min/sum/avg/weighted) | ✅ `TargetVectors.average(...)` etc. | 🔧 SQL-level fusion (§5) |
| Relative score normalization | ✅ `TargetVectors.relative_score(...)` | 🔧 Window function normalization (§5.2) |
| Ranked fusion (RRF) | ✅ `rankedFusion` | 🔧 `ROW_NUMBER()` based (§5.3) |
| Hybrid (BM25 + vector) | ✅ `hybrid(query, alpha)` | ✅ `vg:hybridSearch` (single-table) |
| Hybrid + multi-target | ✅ v1.27+ | 🔧 Combine `vg:hybridSearch` + `vg:vectorSimilarity` |
| Combined score in results | ✅ `metadata.distance` | ✅ `?combined_score` variable |
| SPARQL integration | ❌ Not SPARQL-based | ✅ Full SPARQL query composability |

**Legend**: ✅ = implemented, 🔧 = planned (this document)

---

## 10. Implementation Phases

### Phase 1: `vg:multiVectorSimilarity` in the SPARQL-to-SQL Pipeline

- [x] Add `multiVectorSimilarity` and `multiVectorNearby` IRI constants to `vg_functions.py`
- [x] Add `MultiVectorTriplet` and `MultiVectorArgs` dataclasses
- [x] Implement `extract_multi_vector_args()` — triplet extraction with validation
- [x] Implement `multi_vector_similarity_sql()` — CTE-per-vector, correlated subquery, weighted sum with auto-normalization, NULL check (INTERSECT semantics)
- [x] Wire `VectorRequest` generation for each text triplet (reuses existing placeholder mechanism)
- [x] Add dispatch in `emit_expressions.py` → `_vg_function_to_sql()` for `VG_MULTI_VECTOR_FUNCTIONS`
- [x] Jena sidecar tests: 2-vector, 3-vector, pre-computed vectors, combined with triple patterns (all pass)
- [x] Python unit tests: 9 tests covering extraction, SQL generation, weight normalization, error cases (all pass)
- [x] Add type inference (`xsd:double`) for the new functions in `sql_type_generation.py`
- [x] End-to-end test with real pgvector data (`test_sparql_sql_multi_vector.py`)

### Phase 2: KG Query Criteria + REST API

- [x] Add `WeightedVectorInput` and `MultiVectorSearchCriteria` Pydantic models (`kgentities_model.py`)
- [x] Add `MultiVectorCriteriaInput` and `MultiVectorCriteria` builder dataclasses (`kg_query_builder.py`)
- [x] Extend `KGQueryCriteriaBuilder._build_vector_geo_clauses()` to emit `vg:multiVectorSimilarity` BIND
- [x] Add `multi_vector_criteria` field to `EntityQueryCriteria` (both Pydantic and builder)
- [x] Add `multi_vector_criteria` field to `KGQueryCriteria` Pydantic model (`kgqueries_model.py`)
- [x] Wire into `kgquery_endpoint.py` — converts Pydantic → builder, passes to entity criteria
- [x] End-to-end test passing (7/7): equal weights, weighted fusion ranking, INTERSECT semantics, min_score threshold
- [x] Unit tests for criteria builder (multi-vector path) — 26 tests in `test_kg_query_builder_vector_geo.py`

### Phase 3: Oversampling + Advanced

- [x] ~~Widen LATERAL limits when multiple separate `vg:vectorSimilarity` BINDs detected (§5.1)~~ — not needed; benchmarks confirm correlated pattern is optimal for SPARQL-filtered workloads
- [x] Add configurable oversample factor to REST API (`MultiVectorSearchCriteria.oversample_factor`)
- [x] Implement alternative fusion strategies: `weighted_sum`, `relative_score`, `ranked` (§6.3)
  - Threaded from Pydantic model → builder dataclass → EmitContext → `vg_functions.py`
  - `relative_score`: window-function normalization CTEs (MIN/MAX scaling per index)
  - `ranked`: Reciprocal Rank Fusion via `ROW_NUMBER()` CTEs
  - Unit tests: 54/54 pass
- [x] Performance benchmarks: correlated vs non-correlated (UNION+INTERSECT) — see results below
- [x] Mixed-model auto-detect: when `fusion_strategy` is `weighted_sum` (default) and vector indexes use different `model_name`/`dimensions`, auto-upgrade to `relative_score` normalization
  - `generator.py` Stage 2e: pre-loads `{space}_vector_index` metadata (async, before emit)
  - `vg_functions.py`: checks `ctx.vector_index_meta` for model mismatches
  - Explicit REST API `fusion_strategy` overrides auto-detect (only triggers on default `weighted_sum`)

#### Benchmark Results (June 2026, dim=64, PostgreSQL 17, pgvector HNSW)

Script: `test_scripts_misc/benchmark_multi_vector_sql.py`

| Scale | Pattern | Strategy | p50 | Notes |
|-------|---------|----------|-----|-------|
| **100** | Correlated × 1 | weighted_sum | 0.12ms | btree lookup |
| | NonCorr 5× (100 cand) | weighted_sum | 0.60ms | HNSW scan |
| | Correlated × 20 entities | weighted_sum | 2.85ms | 0.14ms/entity |
| | NonCorr (1 query → 20) | weighted_sum | 0.60ms | **4.8× faster** |
| **1,000** | Correlated × 1 | weighted_sum | 0.13ms | |
| | NonCorr 5× (100 cand) | weighted_sum | 0.60ms | |
| | Correlated × 20 entities | weighted_sum | 2.85ms | 0.14ms/entity |
| | NonCorr (1 query → 20) | weighted_sum | 0.60ms | **4.8× faster** |
| **10,000** | Correlated × 1 | weighted_sum | 0.15ms | |
| | NonCorr 5× (100 cand) | weighted_sum | 1.67ms | |
| | Correlated × 20 entities | weighted_sum | 4.45ms | 0.22ms/entity |
| | NonCorr (1 query → 20) | weighted_sum | 1.67ms | **2.7× faster** |
| **50,000** | Correlated × 1 | weighted_sum | 0.19ms | |
| | Correlated × 1 | relative_score | 0.27ms | +window funcs |
| | Correlated × 1 | ranked | 0.14ms | +ROW_NUMBER |
| | NonCorr 1× (20 cand) | weighted_sum | 1.13ms | |
| | NonCorr 5× (100 cand) | weighted_sum | 1.80ms | |
| | NonCorr 10× (200 cand) | weighted_sum | 1.93ms | |
| | Correlated × 20 entities | weighted_sum | 2.75ms | 0.14ms/entity |
| | NonCorr (1 query → 20) | weighted_sum | 1.05ms | **2.6× faster** |

**Key findings:**

1. **Correlated single-entity** is extremely fast (0.12–0.27ms) — btree index on `subject_uuid` makes it O(1).
2. **Non-correlated** is dominated by HNSW traversal (~0.4–0.9ms per index scan) regardless of `LIMIT`.
3. **For batch workloads** (20 entities), non-correlated is **2.6–4.8× faster** than 20 sequential correlated lookups.
4. **Oversample factor** has minimal impact on latency (1× vs 10×: ~1.1ms vs ~1.9ms) because HNSW scan cost is nearly constant for small LIMITs.
5. **Fusion strategy overhead** is negligible: `relative_score` adds ~0.05ms (window functions), `ranked` adds ~0.5ms (sort + ROW_NUMBER).
6. **INTERSECT overlap** with random vectors at 50K is near-zero at oversample=5 — real data with correlated embeddings will have much higher overlap. Consider fallback to UNION-ALL if INTERSECT returns too few candidates.

**Conclusion — correlated (SPARQL multi-vector function) is the right architecture:**

The `vg:multiVectorSimilarity` / `vg:multiVectorNearby` SPARQL functions use the correlated pattern: the outer SPARQL query filters entities first (by entity type, graph, frame criteria, property filters), then the vector function scores **only the surviving entities** via btree lookup on `subject_uuid`. This is correct because:

- Per-entity cost is O(1) via btree (0.12–0.27ms) — negligible even at 50K scale.
- The outer query's WHERE clause is the primary filter; vector scoring is a secondary enrichment step.
- The non-correlated pattern fetches HNSW candidates blindly — many will be discarded by the outer filters, wasting work.
- INTERSECT overlap at oversample=5 on uncorrelated data is near-zero, meaning the non-correlated approach would return empty results unless massively oversampled.

The non-correlated (UNION+INTERSECT) pattern would only be beneficial for a hypothetical **vector-driving** mode where multi-vector similarity is the sole filter ("find top-K across ALL entities with no other constraints"). This is not a current use case and can be revisited if needed.

---

## 10.5 Bugs Found & Fixed (June 2026)

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| **UUID mismatch in vector upsert/get endpoints** | `vector_indexes_endpoint.py` used `f"U:{uri}"` for UUID generation; quad table uses `f"{uri}\x00U"` | Fixed to `f"{uri}\x00U"` in both `upsert_vectors` and `get_vectors` |
| **UUID mismatch in auto_sync** | `auto_sync.py` used `f"{term_type}:{term_text}"` | Fixed to `f"{term_text}\x00{term_type}"` |
| **INTERSECT semantics not enforced** | `BIND()` assigns NULL for missing entities but doesn't filter them out | Added `FILTER(BOUND(?score))` in `kg_query_builder.py` |
| **Test vectors didn't differentiate rankings** | All entities had similar cosine to both query vectors | Redesigned: Acme dominates index_a, Green dominates index_b, Tech moderate |

---

## 11. Design Decisions

All questions resolved:

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Oversample factor** | 5× default, cap at 300 absolute | 5× is sufficient for 2-3 vectors. For large datasets (>100K/index), cap prevents excessive HNSW scans. Configurable via REST API. |
| **Weight normalization** | Auto-normalize (divide each weight by sum) | Scores always in [0, 1]. `FILTER(?score > 0.5)` has consistent meaning regardless of weight magnitudes. `(0.3, 0.7)` and `(3, 7)` produce identical results. |
| **Three-way fusion (hybrid + multi-vector)** | Keep separate BINDs | `vg:hybridSearch` already returns a fused score. Treat it as another input to arithmetic. Avoids a mega-function. Emitter still optimizes with oversampling. |
| **Index existence validation** | Error | Fail fast. A typo in an index name shouldn't silently produce empty results. Matches current `vg:vectorSimilarity` behavior. |
| **Missing scores** | INTERSECT (require existence in all indexes) | Entities missing from a vector index have incomplete data and should not rank. Matches Weaviate's behavior. |
| **Mixed models/dimensions** | Auto-detect → normalize | Different models/dims detected from index registry → relative score normalization (§6.3). Same model → raw weighted sum. |

---

## 12. References

- [Weaviate Multi-Target Vector Search](https://docs.weaviate.io/weaviate/search/multi-vector) — join strategies, weighted search
- [Weaviate Named Vectors Configuration](https://docs.weaviate.io/weaviate/config-refs/schema/multi-vector) — multiple vector spaces per collection
- [Weaviate Hybrid Search](https://docs.weaviate.io/weaviate/search/hybrid) — BM25 + vector fusion, alpha parameter
- [Weaviate Fusion Algorithms Blog](https://weaviate.io/blog/hybrid-search-fusion-algorithms) — ranked vs relative score fusion
- [VitalGraph Vector/Geo Plan](../planning_vector_geo/vector_geo_plan.md) — existing single-vector implementation
- [pgvector GitHub](https://github.com/pgvector/pgvector) — PostgreSQL vector extension
