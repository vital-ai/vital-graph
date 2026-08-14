# Frame/Entity Traversal: Three Priced Performance Problems

## Status: OPEN — the collapse works; filtering it does not

*(The filename says "never fires". That was the 2026-08-08 finding and it is
wrong now — the rewrite fires, per hop, and delivers four orders of magnitude.
The name is kept because tests and other issues cite `issues/048` by path.)*

Multi-hop traversal between KG entities is what a graph store is for, and the
`frame_entity` table exists to make it cheap. It does — until a query says
which edges to follow. All three problems below are about the same thing: an
UNFILTERED walk is sub-millisecond, and every way of constraining it is between
150x and 28,000x slower.

**The goal is to fix these.** Each has a measurement, a cause where known, and
what to look at.

## What already works, so it is not re-litigated

`rewrite_frame_entity_table` replaces the 6 tables of a hop — 2 edge, 2
slot_type, 2 slot_value — with one `frame_entity` row, and it does this PER HOP.
Measured on `wordnet_frames` (285,348 frames), same query, rewrite toggled,
identical rows:

    depth   rewrite ON      rewrite OFF      rows
    1          0.1 ms           0.3 ms          1
    2          0.2 ms       2,658.8 ms          6
    3          0.4 ms      15,571.0 ms         32

At depth 3 that is 15 `rdf_quad` references reduced to 3. The table is correct
and complete where it is populated (285,348 rows on wordnet, one per frame,
100% with both endpoints, indexed both directions). The join reduction is not
theoretical and the gap widens with depth.

Covered by `tests/integration/test_frame_entity_collapse.py` — 31 tests over a
purpose-built fixture, including the differential that says collapsed and
uncollapsed give the same answer.

---

## Problem 1 — a slot-type constraint disables the collapse entirely

**Price: ~28,000x at depth 3.** Adding `?slot a KGEntitySlot`, which the
canonical reference query carries:

    depth   untyped     with `a KGEntitySlot`     rows
    2        0.3 ms              3,733.0 ms          6
    3        0.6 ms             17,261.1 ms         32

The rewrite declines completely — 0 `frame_entity` joins — because
`frame_entity` holds `(frame_uuid, source_entity_uuid, dest_entity_uuid,
context_uuid)` and a constraint on the SLOT node has no column to land on. The
decline is deliberate and correct as far as it goes: a half-applied rewrite once
emitted SQL PostgreSQL rejected outright (`missing FROM-clause entry for table
"mv0"`), so it now returns the plan untouched rather than collapsing while a
constraint still references a collapsed alias.

**Why this is fixable rather than fundamental.** The constraint is redundant by
construction. A slot reached through `hasEntitySlotValue` from a `frame_entity`
row IS a `KGEntitySlot` — that is what the row means. So the fix is to recognise
constraints that the collapse already guarantees, and drop them rather than
decline on them.

Care: "redundant" must be proven, not assumed. `?slot a KGTextSlot` over the
same pattern must still match nothing, and there is a test asserting exactly
that — constrain slots to a type nothing has and the answer must be empty. A
fix that discards slot constraints wholesale passes the fast path and breaks
that one.

## Problem 2 — a criterion that SHRINKS the answer makes it far slower

**Price: 150x to 5,700x, and it grows with depth.** This is the one that matters
most in practice, because a traversal without a criterion is a crawl, not a
query. Filed in detail as `issues/090`.

On `wordnet_frames`, restricting each hop to hypernyms — the only criterion that
space can express:

    depth   unfiltered   frame type = hypernym   rows
    1          0.2 ms                  0.2 ms       1
    2          0.2 ms                  0.3 ms       1
    3          0.7 ms              4,043.3 ms       1

Four seconds to return ONE row where the open walk returns 32 in 0.7 ms.

On `sp_graph_synth_10k`, which was built to vary the criterion datatype, a
3-hop walk with one criterion per hop:

    criterion                        depth 3     rows
    none                              0.9 ms       63
    hasScore >= 50 (integer)        859.1 ms        4
    hasWeight >= 0.5 (double)       776.3 ms        0
    hasOccurredAt >= (dateTime)     332.8 ms        6
    hasCategory IN (...) (string)   525.2 ms       27
    hasActive = true (boolean)      716.8 ms       12
    hasKGFrameType = (uri)          147.3 ms        1

Every datatype, same direction. The one returning ZERO rows takes 776 ms to say
so.

**This is NOT the rewrite declining.** The collapse happens in every row above —
3 `frame_entity` joins at depth 3, one per hop. The six tables per hop have
already become one; what costs is how the per-hop criterion is joined onto the
collapsed rows.

**Unmeasured, and the place to start:** every number here is wall-clock with no
`EXPLAIN` behind it. Three candidates worth separating —

* whether the criterion join is driven per collapsed row rather than set-based,
  which would explain why it grows with depth;
* whether the criterion's selectivity is visible to the planner at all. A filter
  believed non-selective is applied last, after the traversal has been expanded
  — which fits the symptom exactly: cost tracks the UNFILTERED walk regardless
  of how few rows survive;
* whether the literal comparison lands in the typed lane or falls back to text,
  since `hasWeight >= 0.5` returning nothing still costs 776 ms.

## Problem 3 — a constant-valued slot end is not recognised as a group

**Price: not measurable.** Lowest priority, recorded so it is not rediscovered.

`_find_slot_groups` reads the entity from `quad_object_var`, so
`?slot hasEntitySlotValue <someEntity>` yields no entity variable, that group is
skipped, and the frame is left holding one group instead of two — logged as
"1 slot group(s) but no frame variable carries BOTH a source and a dest group".

An earlier revision of this issue called that the sharpest limitation, on the
grounds that pinning an entity is what a real criteria query does. **That was
inferred from a join count and is retracted.** Pinning by constant costs the
collapse of the PINNED hop only — the cheapest one, bound to a single entity —
while every later hop still collapses. At depth 3: 0.6 ms pinned by FILTER,
0.6 ms pinned in the triple.

Worth fixing for tidiness, not for speed.

---

## How to verify a fix

Both fixtures and their tests exist, so a change can be judged rather than
argued about:

* `tests/integration/test_frame_entity_collapse.py` — 31 tests: per-hop collapse
  at depths 1-3, criteria of three datatypes, the slot-constraint decline, and
  differentials asserting collapsed and uncollapsed agree. The differentials
  patch the DEFINING module: `generate_sql` imports the rewrite inside the
  function body, so patching the generator namespace silently does nothing and
  the test compares the rewritten plan with itself.
* `tests/performance/test_graph_traversal_fixture.py` + `graph_fixtures.py` —
  the scale fixture, with ground truth walked by an independent BFS.
* `scripts/generate_graph_dataset.py` — 10k and 100k, scale-free degrees
  (in-degree max 270 vs median 3 at 10k), small-world clustering, and criteria
  in six datatypes with skewed distributions. Uniform values would make any
  selectivity estimate right and hide a misestimation entirely.

A fix for Problem 2 should show up as the filtered walk approaching the
unfiltered one, at every datatype and at depth 3. A fix for Problem 1 should
show `frame_entity` joins equal to the depth with `a KGEntitySlot` present, and
the KGTextSlot test still returning nothing.

---

# Historical record

What follows is the original investigation, kept for the reasoning and the
measurements. Where it contradicts the account above, the account above is
current.

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

- `issues/090` — Problem 2 in full: a criterion that shrinks a traversal makes
  it hundreds of times slower, across every datatype
- `issues/041`, `issues/043` — the other derived-table defects
- `planning/planning_performance/high_cardinality_slot_value_query_plan.md` —
  records `frame_entity` as empty on that production space too, because it uses
  attribute frames
- `vitalgraph/db/sparql_sql/rewrite_frame_entity_table.py`
- `vitalgraph/db/sparql_sql/sync_frame_entity_table.py`
