# 258 — An unbound `GRAPH ?g` estimates one row, so the planner nested-loops a hundred thousand of them

## Status: OPEN, filed 2026-10-03, measured and reproduced locally. Nothing is
## fixed. Two production queries were cancelled by `statement_timeout` against
## `the_actions_space`; the same shape is 15-19x slower than its graph-BOUND
## equivalent on a local space, and `ANALYZE` does not fix it.
##
## **IT IS NOT THE `FILTER EXISTS` / `FILTER NOT EXISTS`.** That was the reported
## cause and it is wrong — see "The hypothesis this refutes". The anti-join is
## cheap; what is expensive is doing it under a plan built for ONE row.

## What happened on production

Two queries through `/api/graphs/sparql/query`, both on `the_actions_space`,
both cancelled by `statement_timeout` (60 s, `issues/136`):

    2026-10-03 14:52:18.893  execute_sparql_query(the_actions_space) failed:
                             canceling statement due to statement timeout
    2026-10-03 14:53:36.341  (same)

The second is the one whose client gave up after 55.1 s. These are the **only
two SPARQL query failures of any cause in the full 72 h log retention**, and the
ALB reports **zero** `HTTPCode_Target_5XX_Count` and `HTTPCode_ELB_5XX_Count`
over the same window — so this shape is not firing often. It is a latent cost
that anything running the shape at scale will hit.

**Query 1**, the dry run's step-1a count:

```sparql
SELECT (COUNT(*) AS ?n) WHERE {
  GRAPH ?g {
    ?x vital:vitaltype haley:KGFrame .
    FILTER NOT EXISTS { ?x haley:hasKGFormType ?t }
    FILTER EXISTS { ?x haley:hasFrameGraphURI ?o }
  }
}
```

**Query 2**, a rewrite that replaced the `FILTER EXISTS` with a positive triple
pattern and counted distinct frames:

```sparql
SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE {
  GRAPH ?g {
    ?x vital:vitaltype haley:KGFrame ;
       haley:hasFrameGraphURI ?o .
    FILTER NOT EXISTS { ?x haley:hasKGFormType ?t }
  }
}
```

## Reproduced locally, four variants, one space

`sp_graph_forms_20k` — 5,059,197 quads, 30,543 frames matching the predicate.
`EXPLAIN (ANALYZE, TIMING OFF)` on the generator's own SQL;
`test_scripts/debug/_actions_not_exists_shape.py` rebuilds all of it.

| variant | execution | plan | estimate vs actual |
|---|---|---|---|
| **Q1** original, graph unbound | 8,563 ms | Nested Loop Anti Join | **1 vs 94,983** |
| **Q2** rewrite, graph unbound | **10,866 ms** | Nested Loop Anti Join | 1 vs 30,543 |
| **Q2** after `ANALYZE` | 1,826 ms | Nested Loop Anti Join | **still 1** vs 30,543 |
| **Q3** same as Q2, graph **BOUND** | **576 ms** | **Parallel Hash Right Anti Join** | 3,328 vs 10,181 |
| **Q4** unbound, anti-join REMOVED | 1,093 ms | Nested Loop | still 1 vs 30,543 |

Three readings follow, and each kills a plausible explanation.

### The rewrite is SLOWER than the original

10,866 ms against 8,563 ms. Replacing `FILTER EXISTS` with a positive triple did
not address the cause, so the probe's 55.1 s is not evidence that the original
shape was the faster one. Anyone tuning this by moving filters around is tuning
the wrong thing.

### Binding the graph is the whole difference: 576 ms

Same question, same filters, same `FILTER NOT EXISTS` — 19x faster than the
rewrite and 15x faster than the original. The plan changes KIND, not degree:
bound, PostgreSQL estimates 3,328 rows against 10,181 actual (3x out, perfectly
usable) and chooses a **parallel hash** anti-join. Unbound it estimates **1 row**
at every level, so it picks nested loops and performs roughly **156,071 index
probes** — `loops=156071` on the term primary-key index-only scans in Q1.

A plan built for one row is not wrong by a factor; it is the wrong algorithm.

### `ANALYZE` helps 6x and does NOT fix the estimate

10,866 ms → 1,826 ms, and the estimate stays at **1**. So this is not merely
stale statistics: the SQL emitted for an unbound `GRAPH` defeats estimation even
with fresh ones. Worth noting the local table had `last_analyze: NULL` and
`last_autoanalyze: NULL` — never analyzed at all — which is its own finding and
is why the 6x was available.

### The anti-join is not the multiplier

Q4 removes the `FILTER NOT EXISTS` entirely and the unbound query still estimates
1 row and still takes 1,093 ms. The anti-join adds to a bad plan; it does not
cause it.

## The hypothesis this refutes

Reported as "the actions space check timed out due to a slow `FILTER
EXISTS`/`FILTER NOT EXISTS` query". The filters are not the cost, and two further
claims made while chasing it were also wrong:

1. **"The actions space check"** was read as the warm-up, which does time out
   (`Query warm-up for the_actions_space timed out after 20s`, twice at boot on
   2026-10-01). But its query is
   `SELECT ?s WHERE { GRAPH <g> { ?s ?p ?o } } LIMIT 1` — no filter at all — and
   its cost is **generation**, not execution: `gen_ms` 7,918 of `total_ms` 7,923
   with `exec_ms` 4.42, dominated by `load_pair_stats` at 7,710 ms. That is a
   DIFFERENT defect from this one and belongs with the cold-planner-cache cost
   (see "Neighbours").
2. **"No slow query in 48 h contains `EXISTS`"** was offered as evidence against
   the report. **That evidence was void**, and `issues/259` is why: a cancelled
   statement never reaches `report_slow_query`, so the absence of these queries
   from that log says nothing about whether they ran. Read `259` before trusting
   any argument of the form "it is not in the slow-query log".

## Why the estimate is 1

NOT ESTABLISHED. The `rows=1` comes from PostgreSQL, not from the generator's own
statistics layer — the generator emits SQL and the planner estimates it. The
working hypothesis is that an unbound context leaves the term-uuid joins to be
resolved through subqueries whose selectivity the planner cannot see, which is
the same mechanism `issues/183` recorded: "constants resolved in a CTE are
unknown at plan time, so PostgreSQL estimated 3 rows where there were 570,696".
That is a hypothesis; it has not been confirmed for this shape.

## What a fix has to decide

1. **Constrain the context even when `GRAPH` is unbound.** Every quad in a space
   belongs to some graph, so an unbound `GRAPH ?g` is not a filter — it is the
   absence of one, and the generator could still enumerate the space's graphs and
   bind them. Changes row counts not at all; changes the estimate completely.
2. **Make the selectivity visible** — materialise the predicate constant so the
   planner sees it rather than a subquery result. `issues/183` is the precedent
   and its lesson is the trap: a constant resolved in a CTE is invisible at plan
   time, so this has to be done in a way the planner can read.
3. Do NOT reach for `enable_nestloop = off`. `issues/247`'s note applies — a
   fence applied to a shape that needs the fenced operator reads catastrophically
   slow, and the nested loop is correct here for the row count the planner
   believes.

## Workaround, today

**Bind the graph.** 576 ms against a 60 s timeout. Any caller counting frames
across a space should name the graph rather than leaving `?g` free.

## Verify after fixing

- the unbound form's estimate stops being 1 — this is the actual target, and
  execution time is a consequence of it
- `GRAPH ?g` and the graph-BOUND form land within ~2x of each other on
  `sp_graph_forms_20k`; today it is 19x
- the plan for the unbound form is a HASH anti-join, not a nested loop
- Q1 and Q2 both complete on production's `the_actions_space` inside the 60 s
  cap, and return the same counts as the bound equivalents
- the counts themselves do not change — this is a planning defect, and a fix that
  alters any result is wrong
- **`ANALYZE` is not the fix.** If a measurement improves only after one, the
  estimate was not addressed; re-check it

## Neighbours

- `issues/259` — the reason this took a local reproduction: a cancelled query
  leaves no SQL and no plan on production. File-order dependency: `259` makes the
  next occurrence of THIS diagnosable without guessing.
- `issues/228` — the same ending (`canceling statement due to statement timeout`
  surfacing as an HTTP 500) from a different cause: four index scans looping
  85-88k times. Same symptom, same "estimate versus actual" family.
- `issues/183` — "constants resolved in a CTE are unknown at plan time", the
  mechanism this most likely shares.
- `issues/139` — corrupt `rdf_stats` as a 136,000x underestimate. A different
  layer (the generator's own statistics, not PostgreSQL's) but the same failure
  mode, and worth ruling in or out here.
- The cold `load_pair_stats` cost (7,710 ms of a 7,923 ms generation; 22,269 ms
  worst case on production, and a `lock timeout` cancellation in
  `_load_missing_pair_stats` on 2026-10-02) is UNFILED and is not this issue.
