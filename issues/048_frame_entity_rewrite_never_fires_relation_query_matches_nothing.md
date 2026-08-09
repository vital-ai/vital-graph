# The frame_entity Rewrite Never Fires, and the Relation Query Matches No Data

## Status: SETTLED 2026-08-08 — not a pessimization; dead on every API path

The rewrite **does** fire on the query it was built for — the canonical form in
`vitalgraph_sparql_sql_dev/sql_reference/happy_frame_query.sparql` — and on that
query it emitted SQL PostgreSQL rejects outright:

```
missing FROM-clause entry for table "mv0"
```

An earlier revision of this issue said the rewrite fires on nothing. That was
wrong, and wrong because the search was scoped to `vitalgraph/sparql` and
`vitalgraph/endpoint` and missed `vitalgraph_sparql_sql_dev/`, where the
reference query and its supporting work live. All entity-to-frame topologies are
supported by design, and the edge-traversal tables were defined for exactly this
shape; the finding is a broken rewrite, not an abandoned representation.

### The bug

`rewrite_frame_entity_table` collapses six tables (2 edge + 2 slot_type + 2
slot_value) into one `frame_entity` row, and remaps constraints that referenced
the collapsed aliases. Some constraints cannot be remapped: `frame_entity` holds
`(frame_uuid, source_entity_uuid, dest_entity_uuid, context_uuid)`, so a
constraint on the **slot** node has no column to land on. The canonical query has
exactly that —

```sparql
?sourceSlot a haley-ai-kg:KGEntitySlot .
```

— an `rdf:type` quad joined via `q8.subject_uuid = mv0.dest_node_uuid`. After
the collapse `mv0` is gone from the FROM clause, the reference survives, and the
statement will not plan.

### Fix applied

The rewrite now checks that no constraint still references a collapsed alias and
declines if any does, returning the plan untouched. The query then runs
unrewritten — slower, but valid. This is the same conservative shape as
`semijoin`'s split-revert: a rewrite that cannot complete must leave no trace,
because a half-applied one is worse than none.

Verified: the canonical query goes from `UndefinedTableError` to running, with
results identical to the unrewritten path. Full suite clean.

### Still open

Declining is correct but it is not the goal. `{space}_frame_entity` holds
285,348 rows on wordnet and is now, in practice, still unused for this query —
the acceleration it exists to provide is not being delivered. Making the rewrite
handle slot-level constraints (by proving them redundant, or by keeping a slot
column) is the work that would actually pay for the table.

And separately, unchanged by this: `build_relation_query` looks for
`Edge_hasKGRelation`, of which there are zero instances in wordnet, both lead
fixtures and the restored production copy. That path has no test coverage and
returns nothing on every dataset available here.

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
