# Message Search Took 50s Where The Work Is 0.6s — Three Causes, None Of Them The One This Issue First Named

## Status: FIXED 2026-09-21. **The original diagnosis in this file was WRONG
## and is retained below, because the way it was wrong is the useful part.**

**Related:** `planning/planning_vector_geo/nurture_message_keyword_search_plan.md`
§6A; `issues/150` / `issues/161` (the absent-term shape that used to time out —
now 0.10 s)

## What was measured

Loaded production export: 48.1M quads, 84,291 `NurtureAction` entities,
321,276-row message FTS index.

    search_messages, 'saved application' (4,320 matches)   50 s  ->  0.59 s
    absent term, 0 matches                               timeout ->  0.10 s
    'saving apps'      (68,332 matches)                            4.23 s
    '"text me back"'   (80,705 matches)                            7.53 s

## THE RETRACTED DIAGNOSIS

This issue originally said: *the push fires, but `reorder_joins` prices that
leaf without it, so the query drives from the entity type instead of the text.*
It proposed recording an `fts_leaves` statistic mirroring `range_leaves`.

**That was wrong, and acting on it would have added a statistic nothing needed.**

Checked afterwards, in the order that should have come first:

* `join_collapse_limit` is 8 and the query joins 6 quad relations, so
  PostgreSQL is FREE to reorder — the emitted order is a suggestion, not a
  fence.
* PostgreSQL HAS tsvector statistics on the column: 739 most-common lexemes in
  `pg_stats.most_common_elems`. It can estimate `tsv @@ q` without help.
* Given the inner join alone, it chose correctly and unprompted: a Parallel
  Hash Semi Join against the FTS bitmap scan, 4,320 rows, **267 ms**.

The join order was never the problem. The evidence that looked like a
misordered join — `q2 ... loops=84291` — was the *third* cause below, and the
50 s was mostly the *first*.

## The three actual causes

### 1. The image was stale, so the push still kept its filter

`push_text_search` was changed to CONSUME the filter it pushes (plan §6A: the
win is the score subquery evaluating on survivors, not on every candidate).
The container was rebuilt BEFORE that change, so the running server had the
add-and-keep form — the variant measured SLOWER than no push at all.

Visible as `loops=321301` on the score subquery. After rebuilding: `loops=4320`.

    50 s -> 20-28 s

**The lesson is procedural.** Every measurement taken through the server is a
measurement of the IMAGE, not the repo. `docker exec ... grep -c` for the
change before trusting a number.

### 2. A self-join through `URIProp`

The generated SPARQL bound the entity with

    ?slot haley:hasKGGraphURI ?entityUri .
    ?entity vc:URIProp ?entityUri .

`hasKGGraphURI`'s object IS the entity's subject term, so that second pattern
joined a term to itself. It was not free: `URIProp` is carried by EVERY subject
in the graph, so it offered the planner a leaf with no selectivity, and the
entity side was built by walking all 84,291 entities through it to serve 4,320
surviving rows.

Replaced by binding `?entity` directly from `hasKGGraphURI`.

    20-28 s -> 0.59 s

### 3. `ORDER BY DESC(?score)` is not a total order

`ts_rank_cd` ties heavily here — the top score is shared by many messages — so
OFFSET paging over it is unstable between calls. Measured: pages 1 and 2 of a
10-row page shared **6 of 10** slots, and together did not equal the 20-row
page. No error; a caller sees a plausible list with duplicates and gaps.

Fixed with `ORDER BY DESC(?score) ?slot`. Caught by the paging-partition
assertion in `test_scripts/search/test_message_search_e2e.py`, which exists
because every gap in that check has hidden a shipped bug.

## Still true, and still open

**Cost scales with the MATCH COUNT, not the page size.** A query matching
80,705 messages takes 7.5 s because the score is computed for every match and
then sorted, to return 25 rows. `vg_optimize`'s top-K hint does not help: on
the correlated text path it emits `ORDER BY ... LIMIT 1` INSIDE a subquery
keyed on one `subject_uuid`, where the sort orders nothing.

A real top-K would rank inside the FTS table — which has the tsvector and the
GIN index — and join back only the winners, the same shape
`vector_top_k_driving_sql` already uses for vectors. That is the next
optimisation, and unlike the statistic this issue first proposed, it is aimed
at something measured.

Also still true: the score is computed TWICE per row, once for `v5` and once
for `v5__num`.
