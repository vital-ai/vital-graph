# The frame_entity Rewrite Never Fires, and the Relation Query Matches No Data

## Status: SETTLED 2026-08-08 — not a pessimization; dead on every API path

The original suspicion was that `rewrite_frame_entity_table` might be a
pessimization: hand-written SPARQL matching its documented pattern produced a
plan costing 337 billion, driven by a sequential scan of the term table, that
timed out where the unrewritten form returned in 27s.

Driving the same comparison from the real builder settles it, and the answer is
neither "it is slow" nor "it is fine":

**1. The rewrite never fires on API output.** With the rewrite enabled,
`_frame_entity` does not appear in the generated SQL at all. Its pattern —
a frame with `hasSourceEntity` and `hasDestinationEntity` slot groups — is
emitted by **no builder in the codebase**. `grep -rl hasSourceEntity
vitalgraph/sparql vitalgraph/endpoint` returns nothing. It can only be reached
by hand-written SPARQL, which is how the original signal was produced.

So the 337-billion plan is real but unreachable. Nothing in production is slowed
by it, because nothing in production runs it.

**2. `{space}_frame_entity` is written and never read.** 285,348 rows are
maintained on wordnet by `sync_frame_entity_table` — insert hooks, delete hooks,
resync, backfill and drift detection — for a table no query path consults. That
is write amplification and a correctness surface (`issues/041`, `043`) bought
for nothing.

**3. The relation query cannot return wordnet's relations.**
`kg_connection_query_builder.build_relation_query` looks for direct
entity-to-entity edges:

```sparql
?relation_edge vital:vitaltype haley:Edge_hasKGRelation .
?relation_edge vital:hasEdgeSource ?source_entity .
?relation_edge vital:hasEdgeDestination ?destination_entity .
```

`Edge_hasKGRelation` count, measured:

| space | rows |
|---|---|
| wordnet_frames | **0** |
| sp_lead_synth_10k | **0** |
| sp_sql_lead_dataset | **0** |
| restored production copy | **0** |

Not one instance anywhere. wordnet models its relations as connection *frames*
(`hasKGFrameType urn:Edge_WordnetHyponym` plus source/destination entity slots),
which is exactly the shape `frame_entity` materialises — and exactly what the
relation query does not ask for. The query returns 0 rows on every dataset
available here.

So there are two representations of entity-to-entity connection: the frame form,
which the data uses and `frame_entity` indexes, and the direct-edge form, which
the API queries. Nothing joins them.

## What to do

This needs a decision rather than a fix, and it is not mine to make:

1. If connections are meant to be frames, `build_relation_query` is querying the
   wrong shape and the rewrite should be reachable from it.
2. If they are meant to be direct edges, then `frame_entity` and its sync
   machinery are maintaining an index for a representation the API abandoned,
   and should be removed rather than repaired.
3. Either way the relation path has **no test coverage at all** — no
   performance test, and nothing that would have noticed it returning 0 rows on
   every dataset in the repository.

Before acting, confirm against a dataset that exercises relation queries in
anger. Every space available here is either wordnet-shaped or lead-shaped, and
neither uses `Edge_hasKGRelation`; a tenant that does would change the picture.

## Evidence

## Context: the system has two disjoint query families

Established while extending the shape matrix (`scripts/perf_shape_matrix.py`)
beyond the lead fixtures:

| | wordnet_frames | lead fixtures |
|---|---|---|
| slot-value predicate | `hasEntitySlotValue` (570,696) | `hasTextSlotValue`, `hasDoubleSlotValue`, … |
| frame pattern | **connection** (entity → entity) | **attribute** (entity → literal) |
| `{space}_frame_entity` | **285,348 rows** | **0 rows** |
| builder | `kg_connection_query_builder.py` | `kg_query_builder.py` |
| perf coverage | fastpath / covering / edge-hop benches | KGQuery benches |

They barely overlap. Everything in `issues/040`, `045`, `046` and `047` — the
semi-join, two-phase paging, the ordered-scan fence — is on the **attribute**
path. The `frame_entity` rewrite fires only on the **connection** path, so none
of that work touches it, and the lead fixtures cannot exercise it at all
(the table is empty there by construction).

`build_frame_query_sparql` and the connection builder appear in **zero**
performance test files.

## The signal

`rewrite_frame_entity_table` states its own purpose:

> When a source group and dest group share the same frame variable, all 6
> tables (2 edge + 2 slot_type + 2 slot_value) are replaced by one
> frame_entity table … This eliminates 5 JOINs per hop.

Hand-written SPARQL matching exactly that pattern on wordnet (frame typed
`urn:Edge_WordnetHyponym`, source and dest slot groups sharing `?frame`),
25-row page:

| | plan cost | driving scan | result |
|---|---|---|---|
| rewrite **ON** | **337,271,749,808** | `Parallel Seq Scan on wordnet_frames_term` (771,818 rows) | **timed out at 60s** |
| rewrite **OFF** | **8,878** | index scans | 25 rows in 27,155 ms |

Estimated rows also diverge — 49,306 with the rewrite against 2 without — which
is a larger gap than plan choice alone would explain and hints the rewritten
plan may have lost a join condition rather than merely been costed badly.

Note the *unrewritten* 27 s for a 25-row page is itself poor, and is the same
O(matches) shape `issues/040` addressed on the attribute side. The connection
path appears never to have had that work — and it has no performance coverage
at all, which stands regardless of how the rewrite question resolves.

## How it was settled

Driving the differential from `build_relation_query` rather than hand-written
SPARQL, rewrite monkeypatched on and off. Both sides produced identical SQL with
no `_frame_entity` reference, identical plans, identical (empty) results — which
is what "the rewrite never fires" looks like from the outside.

## Join reduction is proven — which is why this instance looks like a bug

An earlier revision of this issue framed the finding as "the shipped precedent
may be backwards", implying the materialised-table pattern itself is suspect.
That was the wrong inference. Measured on the production copy, same query, same
results, edge-table rewrite toggled:

| | full result set (34,423 entities) | 50-row page |
|---|---|---|
| edge rewrite ON | **6,901 ms** | 2 ms |
| edge rewrite OFF | **55,350 ms** | 4 ms |

**8x on the O(matches) path.** The page path shows only 2x because the
issues/047 fence already limits how many rows cross those joins — that is the
fence working, not join reduction ceasing to matter.

The saving is per hop, and concentrated where the data is:

| criteria depth | quad joins, rewrite ON | rewrite OFF |
|---|---|---|
| 1 (entity → frame → slot) | 6 | 10 |
| 2 (entity → frame → frame → slot) | 8 | 14 |

Production slot URIs are **98.0% depth 1**, 1.9% depth 2, 0.08% depth 3 — so
the edge table's benefit lands squarely on the common shape. Deeper chains
compound the saving but are rare enough not to drive the design, which is why
the current edge table is a reasonable compromise rather than a partial one.

So the pattern is validated, repeatedly, across the edge table, `num_val` and
the covering indexes. A rewrite that collapses 6 tables into 1 and yields a
337-billion-cost plan driven by a sequential scan of the term table is behaving
unlike every other join-reduction path here. That points at this implementation,
not at the idea — and it makes settling the question more urgent, not less,
because `frame_entity` is also the closest existing model for any larger
materialised access path.

## Related

- `issues/041`, `issues/043` — the other derived-table defects
- `planning/planning_performance/high_cardinality_slot_value_query_plan.md` —
  records `frame_entity` as empty on that production space too, because it uses
  attribute frames
- `vitalgraph/db/sparql_sql/rewrite_frame_entity_table.py`
- `vitalgraph/db/sparql_sql/sync_frame_entity_table.py`
