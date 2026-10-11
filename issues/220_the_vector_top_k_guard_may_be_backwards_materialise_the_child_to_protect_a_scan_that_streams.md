# The Vector Top-K Guard Materialises The Expensive Side To Protect A Scan That Streams

## Status: CORRECTNESS FIXED 2026-09-26. COSTS MEASURED 2026-10-11 on a 100k-vector fixture: decline costs 1.5-1.9x on filtered queries, the guard ~130x on unfiltered ones; two fixes proposed, neither built (see the end).
## Original status: the rewrite declines when it cannot keep
## its promise, and the failing query returns 5 rows where it returned 0. The
## PERFORMANCE question this issue was raised for is STILL OPEN and still unmeasured,
## and over-fetch-and-retry — the better design — is still not built. See the last
## two sections.
##
## Originally: OPEN, and no longer a hypothesis in the part that matters. MEASURED
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

## FIXED 2026-09-26 — the rewrite now DECLINES rather than promising what it cannot keep

`_annotate_vector_top_k` refuses to annotate when a restriction sits between the
ORDER and the EXTEND, because that is exactly the case the driving subquery's child
cannot see. The correlated form then serves the query, which scores per row and so
applies the outer filters first.

**The score threshold is the one exemption**, and it is principled rather than
convenient: `_annotate_filter_threshold` pushes that filter INTO the driving
subquery, so it is applied on the vector side rather than above the join. Every
other filter means the K rows are chosen from a superset.

    vg_optimize: top-K DECLINED for ?vg_score — FILTER between ORDER and EXTEND
      is not visible to the driving subquery (issues/220)

Declared as a `Rule` so the refusal is REPORTABLE, not just logged — "why is this
query not using the vector fast path" is asked about one query by someone holding
that query and not the log level it ran under.

**Verified on the case that found it:** `total_count=66` with 0 results becomes
**5 results**, and all five are the `paragraph` segment type — the in-scope one —
checked by looking the returned URIs up in the quad table rather than by trusting
the count. `tests/api/test_wikipedia_document_e2e.py` +
`test_kgtypes_entity_integration.py`: **41 passed, 0 failed**, where 7 were failing
before this and `issues/244`/`245`. tests/unit 4973 passed.

**What the decline costs, on this query:** 29-169 ms server-side over 5 runs (min
29, med 61, max 169), against the ~15 ms the broken form took to return nothing.
That is not a like-for-like comparison and is not offered as one — the old number is
the cost of returning zero rows.

## STILL OPEN after this fix

  * **The original cost question is untouched.** This changes WHEN the rewrite
    fires, not what it does when it fires. Whether materialising the child costs
    more than the streaming HNSW scan it protects is still unmeasured, and the A/B
    in "What would settle it" is still unrun.
  * **Over-fetch-and-retry is still the better design and is NOT built.** Declining
    is correct and small; over-fetch would keep the optimisation for filtered
    queries by verifying survival after the join instead of predicting it. It needs
    a retry loop in the executor rather than a single statement, which is why it was
    not done here.
  * **The regression risk of declining is unquantified.** Any filtered vector query
    now takes the correlated path. On this 209-vector index that is tens of
    milliseconds; on a large index with a selective filter it could be much worse,
    and there is no fixture with a large vector table AND a filtered query to
    measure it on. That fixture is the missing piece, and it is the same one the
    cost A/B needs.

## Measured on a large vector fixture, 2026-10-11

The fixture this issue said was missing now exists: space `perf220_vec_100k` on the
test stack, 100,000 KGEntities with `urn:p220:tier` in common 50% / uncommon 5% /
rare 0.5%, and a random 384-d vector each in index `p220` (product DDL, HNSW).
`test_scripts/perf/_issue220_vector_topk.py setup` builds it; `measure` runs
`ORDER BY DESC(?vg_score) LIMIT 10` three ways and checks every page against the
EXACT answer (brute force over the filtered set). 5 runs per cell, test app
stopped.

| filter | form | plan | rows | exact top-10 | buffers | ms min/med |
|---|---|---|---|---|---|---|
| none | shipped | driving (HNSW) | 10 | 1/10 | 3,567 | 187.6 / 231.6 |
| common | shipped (declined) | correlated | 10 | 10/10 | 752,598 | 589.9 / 647.6 |
| common | pushed | driving | 10 | 10/10 | 501,691 | 319.3 / 335.2 |
| uncommon | shipped (declined) | correlated | 10 | 10/10 | 75,259 | 57.5 / 59.4 |
| uncommon | pushed | driving | 10 | 10/10 | 50,300 | 35.7 / 37.9 |
| rare | shipped (declined) | correlated | 10 | 10/10 | 7,520 | 5.3 / 6.4 |
| rare | pushed | driving | 10 | 10/10 | 5,159 | 3.6 / 4.1 |

"pushed" is the same query with the FILTER in an inner group, so it lands below
the EXTEND, inside the driving subquery's child. Semantically identical: the filter
does not mention `?vg_score`.

**What this settles:**

1. **The decline costs 1.5-1.9x on filtered queries** (common 648 vs 335 ms,
   uncommon 59 vs 38, rare 6.4 vs 4.1), and is exact. That is the "regression
   risk of declining" this issue left unquantified: real, not catastrophic.
2. **For a constant-equality filter the decline was never needed.** The emitter
   folds `FILTER(?t = "rare")` into the BGP as `object_uuid IN (... term_text =
   'rare')`, so the driving child already carries it. The pre-220 form ("forced",
   decline patched out) generated byte-identical SQL to "pushed" and returned the
   same exact pages. The decline protects against filters that do NOT fold (a
   `NOT EXISTS`, as in the case that found this, or a range), and it cannot tell
   the difference.
3. **Filtered driving pages are exact on this fixture** because the planner drives
   them from the child through the `subject_uuid` btree and computes distances
   exactly, even at 50% selectivity. It never chose HNSW with a filter here. That
   choice is cost-based, so a less selective filter could flip it to HNSW plus a
   post-filter, which is pgvector's short-page case. Not observed, not ruled out.
4. **The original cost question, answered: the guard costs ~130x on an unfiltered
   query.** The bare HNSW top-10 is 1.5-1.7 ms and 1,474 buffers. The same top-10
   restricted to `subject_uuid IN (child)` is 218-219 ms and 404,369 buffers; the
   100k-row `DISTINCT` child alone is 68 ms. `hnsw.iterative_scan = relaxed_order`
   changes neither. Here the guard protects nothing, since every vector subject is
   a KGEntity in the child. (Unfiltered recall is 1/10 against the exact answer,
   which is HNSW's approximation on uniform random vectors, a known worst case,
   and the same in every form.)

**So there are two different fixes, for two different shapes:**

* **Filtered:** push a FILTER that does not mention the score variable below the
  EXTEND in `vg_optimize` (`Filter(Extend(P, ?s, f), c) = Extend(Filter(P, c), ?s,
  f)` when `?s` is not in `c`). The child then carries the restriction, so the
  driving form's promise holds and the decline is left for filters on the score
  itself. Measured gain 1.5-1.9x. Risk: point 3, so it needs a guard (or a check of
  the chosen plan) against HNSW plus a post-filter.
* **Unfiltered or barely filtered:** the guard's materialisation is the cost
  (~130x). Over-fetch-and-retry (a bare HNSW scan, join, re-pull if short) keeps
  the streaming scan. It needs a loop in the executor, and the vector table has no
  graph scoping of its own (point 1 of "Two things worth fixing"), so the join is
  also what scopes it.

Neither is built. Both change which plan a vector query gets, so they want a
decision first, not a quiet change.

## Over-fetch-and-retry, simulated 2026-10-11

`test_scripts/perf/_issue220_overfetch.py`: each pass takes the top-N nearest from
the HNSW index alone, joins them to the filtered pattern, and stops when 10
survive, otherwise N x4. pgvector stops an HNSW scan after `hnsw.ef_search` rows
unless iterative scan is on, so it was run both ways: ef_search raised to N
(capped at 1,000) and `hnsw.iterative_scan = relaxed_order`. 5 runs, test app
stopped.

| filter (kept) | over-fetch med ms | passes | shipped (decline) | pushed | exact top-10, over-fetch / others |
|---|---|---|---|---|---|
| none | **31** | 1 | 232 | n/a | 1/10 / 1/10 |
| common 50% | **76** | 2 | 648 | 335 | 1/10 / 10/10 |
| uncommon 5% | 123-265 | 4 | 59 | **38** | 5/10 / 10/10 |
| rare 0.5% | 854-1,167 | 5-8 | 6 | **4** | 4-6/10 / 10/10 |

* **Over-fetch wins only when the filter keeps most rows** (4-8x on none or
  common), and **loses 3-200x on selective ones**: at 0.5% about 2,000 candidates
  are needed for 10 survivors.
* **It is not the safe option.** It goes through HNSW, so it is approximate where
  the filtered forms score the filtered rows exactly. With ef_search capped it
  returned **7 rows for the rare filter**, the short page this issue began with;
  only iterative scan filled it, at 854 ms.
* Recall here is pessimistic (uniform random vectors are HNSW's worst case; real
  embeddings cluster). The timing pattern is not: survival rate sets the number
  of passes.

**Recommendation: choose by selectivity.** Small filtered pattern (the planner's
estimate is available at generation time): push the filter below the EXTEND and
score exactly. Large or unfiltered: over-fetch through HNSW with iterative scan.
Keep the decline as the fallback for filters on the score itself. Build the
push-down half first; it is the smaller change, measured, and exact.
