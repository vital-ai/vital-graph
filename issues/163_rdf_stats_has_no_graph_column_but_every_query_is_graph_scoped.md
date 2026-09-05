# `rdf_stats` Has No Graph Column, But Every Query Is Graph-Scoped

## Status: IMPLEMENTED. Harmless on today's fixtures, wrong by the number of
## graphs in production — which is what production is expected to be.

## The mismatch

`{space}_rdf_stats` is keyed `(predicate_uuid, object_uuid) -> row_count`,
counted across the WHOLE SPACE. Every generated query is scoped to one graph —
`context_uuid = <graph>` appears in every BGP — so the number the planner reads
is not the number the query will see.

The error is a factor of how many graphs share a pair. Measured on
`e2e_test_space`, the only multi-graph space in the test stack:

    graphs sharing a pair   pairs   space-wide rows   rows in one graph
    1                          33                44                  44
    2                           1                 2                   1
    3                           1                 3                   1

Every other fixture has exactly one graph, which is why nothing has surfaced
this. Production is expected to hold many graphs per space, where the
over-estimate scales with the graph count.

## Why it matters more than it looks

These counts are not reporting numbers — they are the planner's inputs:

  * `choose_direction` picks the end with fewer rows. Two ends inflated by
    DIFFERENT factors (a pair in 10 graphs against a pair in 2) can invert the
    comparison, and the walk drives from the larger end. `issues/090` measured
    9.2x for choosing right.
  * The semijoin selectivity gate divides `matches / candidates`. Both come from
    this table, so a mixed inflation moves the ratio across `MIN_SELECTIVITY`
    and flips probe-vs-join.
  * `absence_bounds` (`issues/153`) reads absence as an upper bound derived from
    each predicate's smallest STORED pair. With graphs collapsed, "absent from
    the space" and "absent from THIS graph" are different facts and the bound is
    computed from the wrong one.
  * `_equality_criterion` prices an equality from the same pairs.

So a multi-graph space does not merely report inflated numbers; it can take
systematically different plans.

## Cost of fixing it is proportional to the problem

Adding `context_uuid` to the key means `GROUP BY predicate_uuid, object_uuid,
context_uuid` in `recompute_stats_tables`. For a SINGLE-graph space that
produces exactly the same number of rows — the test fixtures pay nothing. A
space with N graphs pays up to Nx rows for a pair that genuinely appears in N
graphs, which is precisely where the accuracy is needed.

## What has to change together

  1. **Schema** — `context_uuid` column; primary key becomes
     `(predicate_uuid, object_uuid, context_uuid)`.
  2. **Recompute** — add it to the GROUP BY. The `keep_top_n` cap and the
     fairness ordering (`row_number() OVER (PARTITION BY predicate_uuid ...)`)
     must decide whether they partition by predicate or by
     (predicate, context) — keeping the largest pairs PER GRAPH is the useful
     property, and that is a deliberate choice, not a mechanical edit.
  3. **Reader** — `_load_quad_stats` keys by the pair today; it must key by
     (pair, context) and look up with the query's graph. Both key spellings
     already cause silent misses here (UUID objects vs `::text`), so this needs
     the same care.
  4. **`absence_bounds`** — depth is derived per predicate; it becomes per
     (predicate, context).
  5. **Migration** — existing rows have no context and cannot be back-filled;
     the table must be RECOMPUTED, not migrated. It is derived, so that is
     cheap: 13.7s for a 53M-quad space (`issues/142`).

## What landed

  1. **Schema** — `context_uuid UUID NOT NULL`; primary key is now
     `(predicate_uuid, object_uuid, context_uuid)`.
  2. **Recompute** — `GROUP BY 1,2,3`, and the fairness window partitions by
     `(predicate_uuid, context_uuid)`. That second half is the real decision:
     `absence_bounds` reads a missing pair against the smallest STORED pair of
     the same predicate, so once counts are per graph the bound is per
     (predicate, graph) and the round-robin has to guarantee a floor per
     (predicate, graph). Partitioning by predicate alone lets one busy graph
     take every slot and leaves the others unpriced — `issues/147` one dimension
     over. `test_the_cap_is_fair_per_graph_not_just_per_predicate` pins it.
  3. **Reader** — the preload NARROWS to `graph_lock_uri` when the query has
     one, and sums over graphs when it does not. `graph_lock_uri` is applied to
     every quad alias by `collect` as a scoping/security constraint, so under a
     lock no pattern can read outside it and the counts describe exactly the
     reachable rows. Deliberately NOT `default_graph` or a dataset clause: those
     scope outer BGPs only, and a `GRAPH ?g` block in the same query would then
     be UNDER-priced — the one direction of error that must not be introduced
     silently. `aliases.quad_stats` keeps its shape, so no consumer changed.
  4. **The stats cache** — was keyed by `space_id` alone, which is no longer
     enough: two queries on one space under different locks want different
     entries, and the first would have served its graph's counts to the second.
     Keyed `(space_id, lock_uri)`, with invalidation dropping every graph's
     entry for a space.
  5. **The on-demand lookups** — both the missing-pair loader and the traversal
     chain's pair lookup now sum in SQL and narrow the same way. A pair fetched
     space-wide and merged into a graph-scoped dict would look larger than
     everything around it purely by how it was fetched.
  6. **The second writer** — `ops/database_op.py` had its own pair aggregate,
     drifted: no cap, no fairness, and the `HAVING COUNT(*) <= 200000` bound the
     recompute removed on evidence. It rebuilt the table into the shape the
     recompute exists to avoid. It now delegates, so "the ONLY writer" is true.
  7. **Migration** — `scripts/migrate_rdf_stats_context_column.py`. Nothing is
     backfilled because nothing can be: a stored row is a sum over graphs and
     the split is not recoverable from it. Truncate, alter, recompute, one
     transaction — absence means "not in the top N", so a committed truncate
     without its rebuild reads as a confident "no selective pairs exist"
     (`issues/103`).

## The cost, measured rather than argued

Migrating all 17 spaces in the test database took 3m09s end to end. Every one of
the 16 single-graph spaces came back with `rows_before == rows_after`, exactly:

    kg_load_test              309 ->      309
    sp_lead_dup             6,312 ->    6,312
    sp_kg_rel              10,010 ->   10,010
    sp_graph_skew_2k       13,638 ->   13,638
    sp_lead_types          21,808 ->   21,808
    wordnet_frames         50,000 ->   50,000   (at the cap)
    lead_nurture_100k      50,000 ->   50,000   (at the cap)

and uncapped, the group-key comparison held to 1,086,774 pairs. The three-graph
`e2e_test_space` went 9 -> 7: splitting by graph pushes thin pairs below
`STATS_MIN_ROW_COUNT`, so the table can SHRINK rather than grow.

The streaming precondition survives on an index that already exists.
`idx_{space}_quad_ctx_pred` is `(context_uuid, predicate_uuid, object_uuid)` —
this key in a different order — and `GROUP BY` is order-insensitive, so the
planner reorders the group key to match. Verified on `sp_lead_synth_10k`:
`GroupAggregate` with `Group Key: context_uuid, predicate_uuid, object_uuid`
over an index-only scan. No new index, no sort, no spill.

## WHERE THE LINE IS DRAWN, and why it is not "everywhere"

Two families of number feed the planner, and they are compared WITHIN a family,
not across:

  * PAIR COUNTS — `quad_stats`, the on-demand missing-pair lookups, the traversal
    chain's lookups, and the bounded direct count for pairs `rdf_stats` does not
    hold. `choose_direction` compares two of these against each other, so they
    must agree about what they are counting. All four are now graph-scoped
    together, and all four caches are keyed by the lock.
  * CRITERION SELECTIVITY — range, text and IN. These stay SPACE-WIDE.

Scoping half of the second family would be worse than scoping none of it. A
range criterion is answered from the value histogram when one is available and
by a counted form when it is not — and `rdf_value_stats` has no graph column
either, so narrowing only the counted path would make two answers to the SAME
question disagree depending on which path happened to fire. Giving the
histograms a graph is the same change again, one table over, and belongs with
them rather than bolted onto this.

The residual error is bounded and in the safe direction: a space-wide criterion
count is an OVER-count against graph-scoped pair counts, so a criterion looks
less selective than it is and is passed over rather than wrongly chosen as the
driver. Worth fixing, not urgent, and it is recorded here rather than left to be
rediscovered.

## Found on the way

`issues/164` — graph-filtered analytics filtered on `q.graph_id`, a column the
quad table does not have, so every graph-scoped analytics request had always
failed. Fixed with the same context plumbing.

## Still open

The analytics fast path is no longer gated to whole-space requests, but
`with_frames_count` (13-15 s, a four-way join with `COUNT(DISTINCT
src_term.term_text)`) is untouched and is now the dominant cost in that job.
