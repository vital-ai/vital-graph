# The Vector Top-K Guard Materialises The Expensive Side To Protect A Scan That Streams

## Status: OPEN, and no longer a hypothesis in the part that matters. MEASURED
## 2026-09-26 against a live failing case: the guard DOES NOT KEEP ITS PROMISE.
## `child_sql` is the EXTEND node's child, so any filter the algebra puts ABOVE the
## Extend — a `FILTER NOT EXISTS`, for one — is invisible to it. The top-K is
## restricted to a SUPERSET of what survives, and the INNER JOIN still drops it:
## a document query returns `total_count=66` with ZERO results because all five
## top-K rows are segment types the outer filter excludes. Proof at the end.
##
## The PERFORMANCE question this issue was raised for is still open and still
## unmeasured. What changed is that over-fetch-and-retry is now the only CORRECT
## option, not merely the cheaper one.

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

## THE GUARD DOES NOT KEEP ITS PROMISE — measured 2026-09-26, with a failing case

This issue asked for a measurement and said not to act without one. Here is one,
and it changes the question: the guard is not merely expensive, **it does not do
what its comment claims.**

Its stated contract is:

    # Filter to only subjects present in the child pattern so the top-K
    # results are guaranteed to survive the downstream INNER JOIN.

They are not guaranteed to survive, because **`child_sql` is the EXTEND node's
child, not the whole query.** Any restriction the algebra places ABOVE the
`Extend` — which is where a `FILTER NOT EXISTS` lands — is invisible to the guard.
So the top-K is restricted to a SUPERSET of the rows that will survive, and the
INNER JOIN above still drops them.

## The failing case, on live data

`tests/api/test_wikipedia_document_e2e.py::TestKGQueryVectorSearch::test_vector_search_ai_topic`:
`total_count=66`, `document_uris=[]`, deterministic. A document query with
`search_scope="segments"`, `include_segment_text=True`, `top_k=5`, `min_score=0.0`.

The space (206 segments with a segment index, kept alive to inspect):

    segment types    markdown_section    140   <- excluded by the query
                     paragraph            66   <- the 66 the count reports
                     segmentation_parent   3   <- excluded by the query
    vectors                               209
    in-scope (paragraph) WITH a vector     66  <- all of them

So every row the query wants has a vector. Running the captured guard subquery
directly, **the child returns 209** — every segment plus the parents — not the 66
that survive the outer filter.

And the top-5 nearest to the query's real embedding, all of them:

    score   in_scope   segment type
    0.6947     f       markdown_section
    0.6415     f       markdown_section
    0.6326     f       markdown_section
    0.4140     f       segmentation_parent
    0.4044     f       markdown_section

Five rows, **none in scope**, all dropped by the INNER JOIN. Hence zero results
against a count of 66. The same top-K restricted to the 66 returns 5 rows, so
neither pgvector, the HNSW index, the threshold nor the data is at fault.

## What this does and does not settle

  * **SETTLED: the guard is not sufficient.** It cannot be, as written — it
    protects against a join it can only partially see. The "over-fetch and retry"
    alternative this issue already sketches is not just cheaper, it is the only one
    of the two that is CORRECT, because it verifies survival after the join instead
    of predicting it.
  * **STILL OPEN: whether materialising the child costs more than it saves.** The
    original performance question is untouched by this. A correctness failure is a
    stronger reason to change the design than the cost was, but it does not answer
    the cost question, and the A/B this issue asks for is still unrun.

## Two things worth fixing that fell out of it

  * **The top-K scan has no context filter.** `_context_clause(ctx)` contributes
    nothing here — the emitted SQL reads `WHERE TRUE AND <threshold> AND <guard>` —
    so the vector scan spans every graph in the space and the guard's subject list
    is the only thing keeping it graph-scoped. On a single-graph space that is
    invisible.
  * **The managed-segment lists disagree.** `_MANAGED_SEGMENT_TYPES`
    (`kgdocuments_read_impl.py`) has four entries including `paragraph`; the query
    builder's `FILTER NOT EXISTS` lists three and omits it. That is why `paragraph`
    segments are the ones in scope here — and why they cannot be created by hand,
    since the write protection uses the four-entry list. One list refuses what the
    other serves.
