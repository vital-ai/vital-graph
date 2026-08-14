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

## UPDATE 2026-08-13 — the table is complete and correct; nothing uses it

`frame_entity` is not a half-built idea. On `wordnet_frames`:

    rows                              285,348   exactly one per KGFrame
    with BOTH source and dest         285,348   100%
    indexes            fe_frame, fe_src_frame, fe_dst_frame, fe_ctx, pkey

    lookup by frame, resolved           0.34 ms
    same answer by quad traversal       1.91 ms

Spot-checked against a real frame (`...1716488391362_692038076`,
Edge_WordnetHypernym): the table returns `norethynodrel -> progestin,
progestogen`, identical to what the six-table slot traversal returns. It is
indexed for traversal in BOTH directions, so it serves `entity -> frame -> slot`
and `slot -> entity` equally.

**The model this represents.** A connection frame IS the relationship between
two entities — the frame/slot structure is how that relationship is spelled out
in quads, and `(frame, source_entity, dest_entity)` is what it reduces to. That
is the same move the edge table made, and the edge table is measured in this
issue at 8x on the O(matches) path. `frame_entity` is that idea one level up,
collapsing 6 tables (2 edge + 2 slot_type + 2 slot_value) into 1.

So the gap is not the representation and not the data. The rewrite declines
whenever a constraint lands on the slot node, which is most of the time, and the
finished answer goes unread.

### It DOES fire — on a narrower shape than this issue implies

Covered now by `tests/integration/test_frame_entity_collapse.py`, on a purpose-
built 3-frame fixture rather than a development space.

The collapse happens when **both slot values are variables**:

    ?sourceSlot hasEntitySlotValue ?srcEntity      collapses
    ?sourceSlot hasEntitySlotValue <someEntity>    does NOT

`_find_slot_groups` reads the entity from `quad_object_var`, so a slot value
pinned to a CONSTANT yields no entity variable, that group is skipped, and the
frame is left holding one group instead of two — logged as "1 slot group(s) but
no frame variable carries BOTH a source and a dest group".

**That is a sharper limitation than the slot-constraint decline this issue was
written about**, because pinning one end is what a real criteria query does:
"frames whose source is X" is the question users ask. The unpinned form —
"every frame with a source and a dest" — is a scan, and the shape least in need
of acceleration. So the rewrite currently fires on the query that needs it least
and declines on the ones that need it most.

Two decline paths, then, and they should not be conflated:

    slot-node constraint      declines (no slot column) — what this issue says
    constant-valued slot end  never detected as a group — the bigger one

### Multi-hop DOES collapse, per hop — measured at depth 3

The join table further down this issue predicts the saving is per hop. That is
now tested rather than predicted. A depth-3 traversal — the shape a synset walk
has, `c0 -> c1 -> c2 -> c3` through three frames —

    rdf_quad references   15  ->  3
    frame_entity joins            3

Each hop is an independent 6-table group sharing only the entity variable with
its neighbour, and each collapses on its own. The three surviving quad
references are the `?frame a KGFrame` anchors, one per hop.

So the mechanism works, and works at depth, whenever the hops are expressed with
variable slot values. Correctness is asserted alongside it: depth 2 from a node
whose successor branches returns BOTH successors, depth 3 returns only the
branch that continues (a dead end must not be carried forward and reported at
full depth), and collapsed and uncollapsed plans agree at depths 2 and 3.

This narrows what is actually left. The rewrite is not broken and not inert —
it is unreachable from the query shapes the product issues, because those pin an
entity. Teaching `_find_slot_groups` to treat a constant-valued slot end as a
filter on the collapsed row is the change that would connect the two.

### Correction: the table is NOT 6x on the frame-detail shape

Earlier in this issue the case for `frame_entity` rested on 0.34 ms against
1.91 ms. That compared it to a hand-written RAW QUAD traversal, which is not
what the pipeline emits. Measured against the SQL actually generated for a
frame's slots — where the EDGE table rewrite fires and does the join reduction:

    generated query (edge table)   0.22 ms
    frame_entity direct lookup     0.16 ms

So for "fetch one frame's slots" the edge table has already taken the win and
`frame_entity` adds nothing measurable. The argument for finishing this work
rests on CRITERIA queries filtering across many frames, not on the detail page.

### A user-visible consequence, found today

The frames UI shows "No slots found for this frame" for frames that demonstrably
have slots. `_build_list_slots_query` in `kgframes_endpoint.py` implements only
the ATTRIBUTE half of the model and fails twice over on connection data:

* it joins slots to frames through `hasKGraphDescription`'s sibling
  `hasFrameGraphURI`, which has **0 term rows** in `wordnet_frames`;
* its subclass UNION enumerates `KGTextSlot`, `KGIntegerSlot`, `KGDateTimeSlot`,
  `KGBooleanSlot`, `KGDoubleSlot` — and omits `KGEntitySlot`, which is what this
  data has. Fixing the linkage alone would still return nothing.

This is not a wordnet quirk. Across 79 spaces:

    hasFrameGraphURI (attribute linkage)   21 spaces
    KGEntitySlot     (connection slots)     8 spaces
    both                                    6 spaces

So the two families coexist inside single spaces, and the slot endpoint has to
serve both rather than choose. Being defined by an absent predicate, the failure
is silent — "no slots" is indistinguishable from a frame that has none.

### Corrections to what this issue said

* **`Edge_hasKGRelation` is no longer "zero instances everywhere".** 11 of 79
  spaces carry the term — but they are all `graph_viz_*`, `*_test` and
  `kgquery_perf` fixtures. wordnet still has none, so the path remains untested
  against real data and the substance of the finding stands.
* **The 27,155 ms unrewritten page is stale.** It predates the whole 2026-08
  performance run. A connection-path query on the same space measured 66-101 ms
  today, though that was the graph-expand shape rather than the canonical frame
  query, so it does not refute the number — it means nobody should plan against
  it before re-measuring.
* **The MV variant is now dead everywhere, not merely dormant.**
  `wordnet_exp_edge_mv` and `wordnet_exp_frame_entity_mv` lived in the
  `fuseki_sql_graph` database — which this project does not use — and were
  dropped with the `wordnet_exp` space on 2026-08-13. `jena_sql_frame_entity_mv.py`
  gates on `pg_matviews` and is imported only from within
  `vitalgraph_sparql_sql_dev`; nothing in the shipped `vitalgraph/` package
  references it. The shipped path is `rewrite_frame_entity_table` against the
  TABLE, and it is confirmed still not firing: SQL generated for the expand
  query contains no `frame_entity` reference, only `_edge`.
* **`frame_entity` is populated in 1 space of 79** now that `wordnet_exp` is
  removed. It is empty by construction for attribute frames, so it can
  accelerate the connection path but cannot be the only path.

### Where that leaves the work

Unchanged and still the goal: make the rewrite handle slot-level constraints, by
proving them redundant or by carrying a slot column. Until then the table is
inert.

Deliberately NOT done: having the endpoint read `frame_entity` directly. It
would be fast and small, and it would hardcode a derived table into an endpoint
and inherit the staleness problem in `issues/041`. The SPARQL path is being
fixed instead, so the speed arrives through the rewrite where every caller gets
it.

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
