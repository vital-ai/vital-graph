# The Vector Top-K Guard Materialises The Expensive Side To Protect A Scan That Streams

## Status: OPEN — UNVERIFIED HYPOTHESIS, raised 2026-09-21. Do not act on it
## without the measurement in "What would settle it".

**Related:** `issues/218` (where the same question was asked about the text
path and answered differently — GIN cannot stream, HNSW can)

## The observation

`vector_top_k_driving_sql` (`db/sparql_sql/vg_functions.py`) restricts its
top-K scan to subjects present in the child pattern:

    # Filter to only subjects present in the child pattern so the top-K
    # results are guaranteed to survive the downstream INNER JOIN.
    subject_uuid IN (SELECT DISTINCT {child_uuid_col}
                     FROM ({child_sql}) AS __cs
                     WHERE {child_uuid_col} IS NOT NULL)

The stated reason is sound: take the top K from the vector table alone and any
row that fails an outer join silently shortens the page.

But the remedy may cost more than the problem. It **materialises the child** —
the graph-pattern side, the expensive one — in order to protect a scan that is
cheap and, crucially, INCREMENTAL.

## Why "incremental" matters here

PostgreSQL's executor is demand-driven: a `LIMIT` above an ordered scan pulls
rows one at a time and stops when satisfied. pgvector's HNSW supports an
index-ordered scan, so the vector side really can behave as a generator.

Measured 2026-09-21 on a 9,200-row vector table with an HNSW index:

    EXPLAIN ANALYZE SELECT subject_uuid FROM <vec>
    ORDER BY embedding <=> <v> LIMIT 5;

    ->  Index Scan using ..._hnsw_idx   (actual rows=5)

**5 rows, not 9,200.** It streamed and stopped.

Contrast the text path, where the same question has the opposite answer:
`ts_rank_cd` is computed from the heap tuple, so GIN must read every match and
sort — `actual rows=80,705` to return 25 (`issues/218`). The vector path has
the property the text path lacks, and the guard spends it.

## The alternative

Over-fetch and re-pull, instead of pre-restricting:

1. pull K from the HNSW scan;
2. join; if fewer than K survive, pull K*m more and repeat.

The child is then never materialised, and the common case — where most or all
of the top K do survive — costs one pass. The guard's worst case becomes the
retry's rare case.

## What would settle it — and why this issue is not a fix

**This is a hypothesis with one supporting measurement, not a finding.** What
has been shown is only that HNSW streams. What has NOT been shown:

* that removing the restriction is actually faster on a real query — the child
  might be cheap, or the planner might already be hoisting it;
* how often fewer than K survive the join in practice, which decides whether
  the retry path is rare or routine;
* whether the retry loop can be expressed in the emitted SQL at all, or needs
  orchestration above it — which would be a much larger change than deleting a
  `WHERE` clause.

The honest experiment is an A/B on a populated vector index with a realistic
graph pattern, **run in both orders**. `issues/218` records why that matters:
a first A/B there showed a 4.3x win that was entirely the cache-warming
advantage of whichever query ran second.

Until then the guard stays. A correct plan that materialises too much beats a
fast one that silently returns a short page — which is the failure this guard
was added to prevent, and the same class as the paging bug in `issues/218`.
