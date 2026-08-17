# Frame/Entity Traversal: Three Priced Performance Problems

## Status: Problems 1 and 2 FIXED 2026-08-17. Problem 3 open (tidiness only).

Problem 1 fixed by absorbing a slot type constraint as a ROLE-SCOPED semi-join
(`63dbb58`). Re-measured on `sp_graph_synth_10k`, start 1658, row counts
identical to before in every case:

                              BEFORE                    AFTER
    d2 + slot type       554,977 buf  264 ms  0 joins   50,924  28.4 ms  2 joins
    d2 + criterion+slot     >30 s  TIMED OUT  0 joins   12,274   7.4 ms  2 joins
    d3 + slot type     1,669,538 buf  791 ms  0 joins  754,169 430.3 ms  3 joins
    d3 + criterion+slot     >30 s  TIMED OUT  0 joins   22,333  13.3 ms  3 joins

**The unbounded case is gone.** Criterion AND slot type together — the realistic
combination, and the one that exceeded 30 seconds at both depths — is now 7.4 ms
and 13.3 ms, and at depth 3 costs 0.2x the OPEN walk. That is the design goal
this issue states: adding a criterion never costs orders of magnitude.

Left: the slot type alone still costs 4.2x (d2) and 5.2x (d3) against the open
walk, because the semi-join runs per surviving row and nothing narrows them. With
a criterion present, few rows survive and it disappears. Worth revisiting only if
a real query constrains slot types without any criterion.

**Still declining: the slot EDGE** (`?slotEdge vitaltype Edge_hasKGSlot`, 691K
buffers), which is what `kgframes_endpoint` emits. Specified below and cheaper
than the node case — `{space}_edge` carries `edge_type_uuid`, so it needs no
type-quad join at all.

Re-measured 2026-08-17 on `sp_graph_synth_10k`, start 1658 (a start whose answer
is NON-EMPTY at both depths — the first re-measurement used one returning zero
rows and made the criterion look free for the wrong reason):

    depth 2, 1,085 rows open        buffers        ms      vs open   collapse
      open walk                      10,626       7.2         1.0x    2 joins
      + criterion       (P2)          3,534       3.2         0.4x    2 joins
      + slot type       (P1)        554,977     264.5        37.0x    0 joins
      + criterion AND slot type        >30 s   TIMED OUT              0 joins

    depth 3, 16,408 rows open
      open walk                     139,292     102.2         1.0x    3 joins
      + criterion       (P2)          6,302      37.8         0.4x    3 joins
      + slot type       (P1)      1,669,538     791.2         7.7x    0 joins
      + criterion AND slot type        >30 s   TIMED OUT              0 joins

**Problem 2 is fixed and then some.** Adding a criterion no longer costs 150x to
5,700x — it now makes the walk 2.2x to 2.7x FASTER than leaving it open, which is
the design goal this issue states. That came from `issues/090`: the criterion
gate, the direction choice and the hoist.

**Problem 1 is untouched and is now the dominant cost.** The headline said
28,000x; measured here it is 37x at depth 2 and 7.7x at depth 3, with the
collapse gone in both (`frame_entity joins=0`). The ratio is smaller than the old
number and the absolute cost is not: half a million buffers for a query whose
collapsed form reads ten thousand.

**The combination is unbounded, and it is the realistic one.** A criterion AND a
slot-type constraint together exceed 30 seconds at BOTH depths — the canonical
reference query carries the slot type, and adding a criterion is the ordinary
thing to do next. Every other row in those tables is a query that finishes.

Reproduce with `test_scripts/debug/remeasure_048.py`.

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

## The design goal: constraints must not be cliffs

All three problems are instances of one property being violated. Stated
positively:

> **Adding a criterion to a traversal must never make it dramatically slower.**
> A filter that admits fewer rows should cost no more than the walk it filters,
> whatever the criterion is on and whatever its datatype.

That is a stronger goal than "make the redundant case free", and it is the one
worth aiming at, because the queries a product issues are full of ordinary
constraints — a URI equality on a frame type, a value threshold, a date range —
and none of them are redundant. Today:

    a URI constraint on the SLOT      collapse declines      ~28,000x   (Problem 1)
    a URI constraint on the FRAME     collapse survives          ~160x   (Problem 2)
    a value constraint on the FRAME   collapse survives    150x-950x     (Problem 2)

The first two are both URI constraints and differ only in which node they touch.
Nothing about a traversal makes that a reasonable difference, which is the
clearest sign that the cost is coming from the plan rather than from the work.

**Acceptance, for any fix here**: with the constraint present, `frame_entity`
joins still equal the depth, the answer is unchanged, and the time is within a
small factor of the unconstrained walk — not merely better than it was.

---

## Who actually issues these queries — the scoping question, ANSWERED

Asked 2026-08-17 before building the fix, because it decides whether Problem 1 is
urgent or merely open. The answer is that **no product path generates the shape**.

`frame_entity` only ever holds CONNECTION frames. `sync_frame_entity_table`
requires a frame to reach a slot typed `urn:hasSourceEntity` AND one typed
`urn:hasDestinationEntity` — that is the `HAVING` clause — so a frame with
neither produces no row. Measured:

    wordnet_frames        285,348 frame_entity rows    connection frames
    sp_graph_synth_10k     45,643                      connection frames
    sp_lead_synth_10k           0                      attribute frames
    sp_kg_types                 0
    kg_load_test                0

And those two role URIs appear NOWHERE outside `vitalgraph/db/sparql_sql/`
— not in `kg_query_builder`, not in the portal query set.

What `kg_query_builder` actually emits, for an entity query with frame and slot
criteria including a nested frame, is:

    ?entity        vitaltype     KGEntity (UNION over four kinds)
    ?frame_edge_0  vitaltype     Edge_hasEntityKGFrame
    ?frame_edge_0  hasEdgeSource ?entity
    ?frame_edge_0  hasEdgeDestination ?frame_0
    ?frame_0       hasKGFrameType <LeadStatusFrame>
    ?slot_edge_0_0 vitaltype     Edge_hasKGSlot
    ?slot_edge_0_0 hasEdgeSource ?frame_0
    ?slot_0_0      hasKGSlotType <hasStatus>
    ... nested frame via Edge_hasKGFrame, then its slots

That is entity -> ATTRIBUTE frame -> slot, and frame -> frame for nesting. There
is no second entity hop anywhere in it, so these frames never enter
`frame_entity` and the collapse is not involved. The `Edge_hasKGSlot` constraint
it carries is on the losing side of the table above, but it is attached to a
shape the collapse never sees.

### Correction: a product site DOES emit the constraint, on a shape with no chain

The paragraph above originally said no product path emits it. That was wrong and
came from grepping `kg_query_builder` only. `kgframes_endpoint.py` builds the
frames-UI list-slots query and its connection branch is:

    { ?slot a <haley:KGEntitySlot> .
      ?_slotEdge hasEdgeDestination ?slot .
      ?_slotEdge hasEdgeSource <frame_uri> . }

Measured on `wordnet_frames` against a real frame: **22 buffers, 0.06 ms, 2 rows,
0 frame_entity joins.** The collapse not firing costs nothing here because there
is nothing to collapse — the query is anchored on ONE constant frame and lists
its slots. No entity-to-entity chain exists to lose.

### What the real connection-frame application queries do

`happy_words_v2` — the wordnet relationship queries, the closest thing here to a
production traversal — walks entity -> frame -> entity and carries slot
constraints. They collapse and they are fast:

    RELATIONSHIPS (happy words)   frame_entity joins=1   1,632 buffers   1.7 ms   45 rows
    FRAME_UNION   (happy words)   frame_entity joins=2   5,813 buffers   6.5 ms  425 rows

Because the slot constraints they carry are `hasKGSlotType <urn:hasSourceEntity>`
plus `hasEntitySlotValue ?entity` — which IS the collapse's input, the pattern it
recognises a slot group by. Not a slot TYPE constraint.

**That is the whole discrimination.** Problem 1 needs a query that BOTH walks
connection frames AND adds a type constraint on top of the role-plus-value
pattern. No product path and no case query does both;
`test_frame_entity_collapse.py` with `slot_typed=True` constructs exactly that
combination, and is the only place it exists today.

**So Problem 1 costs nothing to any query the product or the portal issues
today.** It costs hand-written SPARQL that adds a slot or edge type constraint to
a connection-frame walk — a first-class use of a SPARQL endpoint, and reachable
by anyone writing the reference pattern defensively, but not a live production
regression.

This is a re-pricing, not a dismissal: 690,949 buffers where the collapsed form
reads 10,626 is real, and a customer writing the canonical reference query hits
it. It moves the work from "this week" to "when the traversal area is next
opened".

## Which side of the hop the constraint sits on — the whole discrimination

Added 2026-08-17, after asking whether Problem 1 had been fixed before and
regressed. It had not. What was fixed was the FRAME side, and that still holds;
the SLOT side was never touched. Measured on `sp_graph_synth_10k`, depth 2,
start 1658, 1,085 rows in every case:

    constraint on the hop                       collapse    buffers
    none                                         2 joins     10,626
    frame  a         KGFrame                     2 joins     10,626
    frame  vitaltype KGFrame                     2 joins      9,826
    slot NODE  a         KGEntitySlot            0 joins    542,012
    slot NODE  vitaltype KGEntitySlot            0 joins    542,012
    slot EDGE  vitaltype Edge_hasKGSlot          0 joins    690,949

Both spellings behave identically on each side, so this is not an `a` versus
`vitaltype` problem — `ce9d64c` absorbs a frame type into
`frame_entity.frame_type_uuid` whichever way it is written, and no equivalent
exists for the slot.

The rewrite says so itself, in its recorded decline:

> a variable would lose the binding that ties it to the frame while still being
> bound by a surviving table

**The last row is the one that raises the priority.** `kg_query_builder` emits
`?slotEdge vital-core:vitaltype haley:Edge_hasKGSlot` — the slot EDGE, not the
slot node — so the shape the PRODUCT generates is on the losing side of this
line, and is the most expensive of the three. Scoping caveat, stated because it
has not been established: that constraint was measured here placed on a
multi-hop entity walk. Whether the product's own traversal path assembles that
combination is a separate question and is not answered by this table.

**Why the suite is green while this is true.**
`tests/integration/test_frame_entity_collapse.py` documents the decline as the
current contract — its own docstring says "the canonical reference query (which
says `?sourceSlot a KGEntitySlot`) is exactly the case that declines. The table
is therefore correct, populated, and unread." It asserts the CONTRACT rather
than which branch is taken, deliberately, so a correct-but-slow plan passes.
That is the right call for a correctness test and it is why nothing has ever
gone red over this.

Reproduce with `test_scripts/debug/remeasure_048.py`.

## Problem 1 — the fix, specified against the code as it stands 2026-08-17

Written after reading the rewrite and building the fixture that can catch the
wrong version of it. Everything below is checked against the current source, not
recalled.

### Where it goes

`rewrite_frame_entity_table` already does exactly this shape for the FRAME type
(`ce9d64c`): `_type_quads_for` finds `<frame_var> vitaltype <const>` quads, they
are added to `removed_aliases` and `type_quad_owned`, and a replacement conjunct
is appended to `absorbed_type` as `(fe_alias, sql)`, which line ~493 folds into
`new_tagged` / `new_constraints`. The slot fix is the same five steps with a
different conjunct. `space_id` is a parameter of the function, so
`f"{space_id}_edge"` and `f"{space_id}_rdf_quad"` are both available.

### The conjunct

For a slot group `g` (which already carries `slot_var`, `role`, `edge_alias`,
`frame_var`), a constraint `<g.slot_var> a|vitaltype <T>` becomes:

    EXISTS (SELECT 1
            FROM {space}_edge e_x
            JOIN {space}_rdf_quad st_x
              ON st_x.subject_uuid = e_x.dest_node_uuid
             AND st_x.predicate_uuid = <hasKGSlotType>::uuid
             AND st_x.object_uuid    = <role uri>::uuid
            JOIN {space}_rdf_quad ty_x
              ON ty_x.subject_uuid = e_x.dest_node_uuid
             AND ty_x.predicate_uuid = <the type predicate>::uuid
             AND ty_x.object_uuid    = <T token>
            WHERE e_x.source_node_uuid = {fe_alias}.frame_uuid
              AND e_x.context_uuid     = {fe_alias}.context_uuid)

**The role join is the whole correctness of it.** Without `st_x` this reads "the
frame has SOME slot of type T" instead of "the ROLE-scoped slot is of type T".
On every fixture before 2026-08-17 those two returned the same answer, because
every slot was a `KGEntitySlot`. On `sp_graph_skew_2k` regenerated with
`--attribute-slot-fraction 0.25` they are **0 and 2,317**.

### Two preconditions, both required

1. **Every surviving binding of `slot_var` is a type quad with a CONSTANT
   object.** `_type_quads_for` enforces the constant for frames and says why; a
   variable object binds something the query may read, and the column cannot
   supply it here at all. Handle `rdf:type` AND `vital-core#vitaltype` —
   `_type_quads_for` matches only the latter, and measurement shows both spellings
   reach the same decline, so both must be absorbed or the fix covers half the
   cases.
2. **`slot_var` is not projected.** Absorbing removes its last position, and
   `plan.var_slots` is then filtered to positions-only; if the query selects the
   slot, its value is gone. Decline instead.

Anything else — a slot constrained on something that is not a type, a slot whose
value is read — keeps today's decline. This widens what collapses; it does not
try to make everything collapse.

### The same treatment for the slot EDGE

`?slotEdge vitaltype Edge_hasKGSlot` breaks identically (691K buffers) and is
what `kgframes_endpoint` emits. It is CHEAPER to absorb: `{space}_edge` carries
`edge_type_uuid`, so the conjunct needs no `ty_x` join at all — add
`AND e_x.edge_type_uuid = <T>::uuid` to the EXISTS above and drop the type quad.

### How to know it worked

    correctness   ?srcSlot a KGTextSlot   -> 0 rows      (2,317 if the role join is missing)
                  ?srcSlot a KGEntitySlot -> 9,266 rows
                  both already asserted in test_traversal_direction_gate.py
    collapse      frame_entity joins goes 0 -> 2 on the depth-2 slot-typed query
    cost          542,012 buffers -> the ~10,626 the unconstrained walk reads
    no regression the differential against the flat plan, which
                  test_frame_entity_collapse.py already runs with slot_typed=True

### Why this was not landed on 2026-08-17

Context budget, honestly stated. This file has twice shipped a silent defect —
invalid SQL (`missing FROM-clause entry for table "mv0"`) and a cross product
that turned 285,348 correct rows into over a million — and both were found by
measurement rather than by tests. A half-applied change here returns WRONG
ANSWERS rather than slow ones. The fixture that can catch the likely bug now
exists, which was the prerequisite; the change itself wants a session with room
to measure it properly.

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

**Recognising redundancy is NOT the fix — it is a special case of it.**

It is tempting, because this particular constraint is redundant by construction:
a slot reached through `hasEntitySlotValue` from a `frame_entity` row IS a
`KGEntitySlot`. Detecting that and dropping it would make the canonical query
fast.

It would also fix exactly one constraint. A query that says
`?slot a KGEntitySlot` gets rescued; one that constrains the slot on anything
the collapse does not happen to guarantee falls off the same cliff. Users write
constraints that are not redundant, and a URI constraint is the most ordinary
thing a traversal carries.

**The property wanted is that adding a criterion never costs orders of
magnitude** — see the design goal below. Redundancy detection does not deliver
it; it just moves the cliff to the next constraint along.

Three ways to actually carry slot constraints through the collapse, none yet
attempted:

* **Apply them after the collapse, driven by the collapsed rows.** The
  `frame_entity` row names the frame; the slots are one indexed hop from it. A
  semi-join from a handful of collapsed rows back to the slot is cheap, and
  needs no schema change. Most likely the right answer.
* **Carry the slot uuids in `frame_entity`.** Widens the table and makes the
  constraint a column test, at the cost of a schema change and another thing
  `sync_frame_entity_table` must keep correct (`issues/041` is what that risks).
* **Prove redundancy where it holds AND fall back to one of the above.** The
  optimisation is real; it is just not the fix on its own.

Care in every case: "redundant" must be proven, not assumed.
`?slot a KGTextSlot` over the same pattern must still match NOTHING, and there
is a test asserting exactly that. A fix that discards slot constraints wholesale
passes the fast path and silently returns rows for a query that should return
none.

## Problem 2 — a criterion that SHRINKS the answer makes it far slower

**Price: 150x to 5,700x, and it grows with depth.** The one that matters most in
practice: a traversal without a criterion is a crawl, not a query.

    wordnet, depth 3, hops restricted to hypernyms   0.7 ms  ->  4,043.3 ms
    (returning ONE row where the open walk returns 32)

    graph_synth_10k, depth 3, one criterion per hop
      none 0.9 ms / 63 rows, versus 147-859 ms across integer, double,
      dateTime, string-IN, boolean and uri criteria — every datatype, same
      direction, the one returning ZERO rows costing 776 ms

**This is NOT the rewrite declining.** The collapse happens in every case — 3
`frame_entity` joins at depth 3, one per hop. The six tables per hop have
already become one; what costs is how the per-hop criterion is joined onto the
collapsed rows. That is why it is a separate line of work from Problem 1, and
why fixing the decline will not touch it.

**Full measurements, per-datatype table, and the three hypotheses to separate
first are in `issues/090`** — kept there rather than duplicated here, since
keeping two copies of the same numbers in step is how they stop being in step.
The headline above is enough to rank the work; 090 is what to read before
starting it.

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

**Judge a fix against the design goal, not against the previous number.**
"Better than 17 seconds" is satisfied by 4 seconds, which is still a cliff. The
bar is that the constrained walk costs about what the unconstrained one costs:

    frame_entity joins == depth, WITH the constraint present
    answer unchanged, and `?slot a KGTextSlot` still returns nothing
    time within a small factor of the unconstrained walk, at depth 3

and it has to hold for a constraint on the SLOT and one on the FRAME, and for
every criterion datatype the fixture carries — not just the one that motivated
the change. A fix that helps a URI equality and leaves the dateTime range at
330 ms has found a special case, not the cause.

The per-datatype sweep in `issues/090` is the table to re-run; it exists so the
answer is a row of numbers rather than an impression.

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
