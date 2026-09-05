# The Production Entity-Query Shape Has No Workable Plan At 53M

## Status: OPEN. Measured 2026-09-04 on `lead_nurture_100k` (53.4M quads).

## Summary

The entity query the production Nurture workload issues — an equality on a slot
value, under a depth-2 frame shape — cannot be executed within the 60s statement
timeout at 53M quads, and NEITHER available plan fixes it. This is separate from
`issues/160`, which is about the gate that CHOOSES between them. Fixing the gate
does not give this shape a plan that works; it only changes which way it fails.

## The two plans, measured

Same space, same queries, warm, Postgres restarted between so both columns are
comparable:

    shape                    as-is (current)   hop-wise (issues/160 attempt)
    eq campaign head         13.9 s (78,871)   TIMEOUT (55s)
    eq campaign + ABSENT     TIMEOUT           TIMEOUT
    eq SFLeadId present      4 ms (1 row)      TIMEOUT (55s)
    eq SFLeadId ABSENT       400 ms (0 rows)   19 ms

Neither column is acceptable. `as-is` cannot do the head value or the two-slot
conjunction; `hop-wise` cannot do anything except the case that short-circuits.

## Three distinct defects visible in that table

**1. A zero-matching conjunction is slower than the unconstrained query.**
`campaign + ABSENT` must return 0 — the absent term is not in the term table at
all — yet it times out, while `campaign` alone returns 78,871 rows in 13.9s.
Adding a constraint that eliminates everything makes the query strictly harder.
An empty constant should collapse the whole conjunction before any join runs;
`SFLeadId ABSENT` alone proves the machinery CAN do this (400ms / 19ms), so the
collapse is not propagating across two frame criteria.

**2. The criterion contest cannot tell a filtering constant from a structural
one.** Under the `issues/160` attempt, every shape reported "criterion admits
2%" — including `SFLeadId present`, whose value matches 1 row in 1,150,000. The
2% came from a STRUCTURAL constant (a slot-type or frame-type URI, present on
every query of this shape and not a filter at all), which won the
most-selective contest and drove the nested loop. Chain constraints
(`head_constraint`/`tail_constraint`) mix both kinds and nothing distinguishes
them.

**3. 13.9s for 78,871 rows out of 53M is itself too slow**, even as the
"working" plan, on a fully indexed and ANALYZEd space.

## Why the obvious fixes do not apply

A selectivity THRESHOLD on the equality would not have helped: the shape that
regressed worst (`SFLeadId present`) is the most selective one in the set, 1 in
1,150,000. Rarity is not what separates the winners from the losers here — which
constant drives the walk is.

`absence_bounds` (`issues/153`) is correct and reaches `choose_direction`;
verified independently on this space (cut depth 42,323; both slot predicates
bounded at <= 1; 40 kept URI pairs matching the fixture's 4,960 singletons). The
bound is not the missing piece.

## What to establish next

- EXPLAIN both plans for `campaign + ABSENT` and find where the empty constant
  stops propagating. Defect 1 is the highest-value fix: it is a correctness-
  shaped performance bug with a provable right answer (0 rows, immediately).
- Decide how a constant that FILTERS is distinguished from one that names the
  shape being walked, before any further work on `issues/160`.
- Attribute the 13.9s: count vs page (the endpoint computes a total for
  pagination), and join order within the as-is form.

## Measurement caveat

The test stack runs a backfill task that writes to the space every 0.5s and a
maintenance ANALYZE, so wall-clock carries real variance — the same shape
measured 13.9s and 19.4s in adjacent runs. Decision logs are deterministic and
are the load-bearing evidence; the timeouts reproduce across runs.

## The supporting table already answers this shape, and is refused

`{space}_entity_slot_sort` holds `(context_uuid, entity_type_uuid,
frame_type_path, slot_type_uuid, value_text, entity_uuid)` with a btree index on
exactly that tuple — an equality probe for this query. Measured on
`lead_nurture_100k`, against the same ground truth:

    query                  current (BGP)      via entity_slot_sort   result
    campaign head          13.9 s             46.9 ms   (~296x)      78,871
    campaign + ABSENT      TIMEOUT (>55s)     271 ms    (>200x)      0
    campaign + PRESENT     17.2 s             98.8 ms   (~174x)      1

All three return the verified-correct answer. The 18-pattern BGP join over 53M
quads is re-deriving what the table already stores.

`fast_slot_sort.can_serve()` refuses it, deliberately:

    # The table sorts a population; it does not select one.
    if getattr(criteria, "frame_criteria", None):
        return False

and it also requires exactly one `sort_criteria`, so this query — all filter, no
sort — is declined on the first check. The fast path exists, is populated
(4,064,500 rows, 100,000/100,000 entities), and is switched off for the shape it
would help most.

Note the index's LEADING columns matter. Probing on `slot_type_uuid` +
`value_text` alone measured 5.36 s; supplying `context_uuid`,
`entity_type_uuid` and `frame_type_path` took the same query to 271 ms. An
implementation must emit the full prefix, not just the filter.

### The constraint that makes this non-trivial: COVERAGE

Serving a SORT from an incomplete table gives a mis-ordered page. Serving a
FILTER from one gives a WRONG ANSWER — silently, with a plausible row count.

That is not hypothetical. `issues/149` measured production:

    entity type          in table   of type    coverage
    NurtureAction             809    76,996      1.05%

A filter served from that table would have returned ~1% of the matching
entities and looked healthy. `entity_slot_sort_coverage` exists and already
reports this, and `issues/159` shows the backfill can sit at 0% for the whole
of a bulk load.

So the fix is NOT "call the fast path for filters too". It is:

  1. Extend `can_serve` to admit `frame_criteria` whose slot criteria are all
     equalities with a frame path — the shape the index answers.
  2. Gate it on VERIFIED COVERAGE for the entity type being queried, and fall
     back to the BGP path when coverage is short. Coverage is per (space,
     entity_type) and already computed.
  3. Emit the full index prefix, per the 5.36s/271ms measurement above.
  4. Keep the existing caveat that a slot hanging directly off an entity is not
     in the table, so `frame_path` remains required.

The coverage gate is the load-bearing part. Without it this trades a slow answer
for a wrong one.

## IMPLEMENTED 2026-09-04 — measured end to end

`fast_slot_filter.py` serves the shape from `{space}_entity_slot_sort`, gated on
a `slot_sort_coverage` marker. Measured on `lead_nurture_100k` (53.4M quads),
answers verified against the quads:

    shape                  before          after     result
    campaign head          13.9 s          323 ms    78,871  OK
    campaign + ABSENT      TIMEOUT (55s)    96 ms         0  OK
    SFLeadId present       4 ms             38 ms         1  OK
    SFLeadId ABSENT        400 ms           31 ms         0  OK

Page path (`count_only=False`, which the table above does not exercise):

    rare value page        336 ms  total=1       uri urn:acme:lead:SYN000000000
    campaign page 1        341 ms  total=78,871  5 uris
    offsets 0/5/10         68/98/106 ms          5 uris each
    PARTITION              15 collected, 15 distinct — no overlap
    empty conjunction      96 ms   total=0, 0 uris

The query that could not complete at all now answers in 96 ms.

`entity_slot_sort_all_types` (the marker probe) measures **818 ms** on this
space and reported `Lead 100000/100000`, so recording markers per maintenance
cycle is cheap.

### Known regression

`SFLeadId present` went 4 ms -> 38 ms on the count path. A single maximally
selective equality is a shape the BGP path already handled well, and the fast
path adds a marker lookup plus an INTERSECT. 34 ms absolute on a shape that was
never the problem, but it IS a regression and is recorded rather than rounded
away. The marker lookup is a per-query round trip and is the obvious thing to
cache per process if this matters.

### Still open in this issue

Defect 3 — "13.9s for 78,871 rows is too slow even as the working plan" — is
now moot for THIS shape, because the shape no longer takes that plan. It stands
for any equality filter the fast path declines (non-eq comparators, no entity
type, a slot hanging directly off an entity), which still fall back to the BGP
join. Those are correct but slow.

## ROOT CAUSE 2026-09-05: the anchor is chosen structurally, not by selectivity

The earlier sections treat this as a plan-choice problem. It is narrower and more
fixable than that: the query cannot express the good plan at all.

`semijoin._split_bgp` picks the anchor as

    anchor_aliases = {a for a in quad_aliases if bound.get(a) == {key}}

— "every quad table binding the projected variable AND NOTHING ELSE". For an
entity query that is always `?entity hasKGEntityType <T>`, i.e. the whole
population. The discriminating constants bind SLOT variables
(`?slot_0_0 hasUriSlotValue <campaign>`), so they are structurally ineligible to
anchor. Selectivity never enters the choice.

Both reachable plans therefore start from 100,000 entities:

    semijoin probe    EXISTS subplan runs ~49,000 times      -> timeout >55s
    plain join        merge-joins ALL 5,277,000 edge rows,
                      estimated cost 1,250,744,169           -> timeout >55s

### What the data actually supports

Driving from the selective end by hand — take the 78,871 matching campaign
slots, walk up two edge hops on the existing
`(dest_node_uuid, source_node_uuid)` index, count distinct entities:

    cold   9,686 ms
    warm   1,301 ms then 519 ms      correct answer, 78,871

So **519 ms against a 55s timeout**, over the quad and edge tables, with no
derived table and no new index. `entity_slot_sort` answers the same question in
323 ms, but it is not required to get under a second.

### The fix this points at

Anchor on the most selective CONSTANT and confirm upward, rather than on the
projected variable. The pieces already exist: `rdf_stats` prices every
(predicate, object) pair exactly, and `absence_bounds` prices the absent ones,
so the split could compare candidate counts before choosing an anchor instead of
taking the only structurally eligible one.

Note the hand-written query is ALSO badly estimated — PostgreSQL predicts 7 rows
against 78,871, because the term lookups are InitPlans and opaque at plan time.
It picks nested-loop index lookups almost by accident. Whatever emits the good
plan should not rely on PostgreSQL costing it correctly.

### What was tried, and what it bought

`MAX_PROBE_CANDIDATES` (semijoin.py) declines the probe when the anchor exceeds
10,000, on the ground that the probe runs once per candidate whatever the
selectivity. Measured:

    SFLeadId ABSENT   2,385 ms -> 61 ms      39x, probing 100,000 to return 0
    SFLeadId present    200 ms -> 238 ms     unchanged
    campaign head     timeout  -> timeout    unchanged
    campaign+ABSENT   timeout  -> timeout    unchanged

`tests/performance/test_kgquery_growth_curve.py`: 24 passed, 2 skipped — it does
not give back the `issues/045` shapes. So it is a safe, partial win: it stops a
bad probe, but it cannot create the good plan, because no plan the current split
can express drives from the selective end.

## THE ACTUAL DEFECT, 2026-09-05: independent criteria are CORRELATED, not intersected

Two different things were being called "nesting", and only one of them is real:

  * STRUCTURAL nesting — `frame -> frame -> slot` WITHIN one criterion, a
    containment path along shared variables. This genuinely has to be walked.
  * EVALUATION nesting — what the planner does BETWEEN two criteria: it re-runs
    the second chain once per candidate of the first. This is a choice.

Measured on the campaign + ABSENT shape:

    Nested Loop  (cost ... 957,186,606, rows=46,079)
      ->  Hash Join   (rows=46,079)                     the campaign chain
      ->  Nested Loop (cost=1015.83..20,769.37)         the ABSENT chain, PER ROW

    46,079 x 20,769 ~= 957,000,000

### The criteria are provably independent

Removing `?entity` from the BGP splits it into exactly two connected components
with NO shared variable:

    component 0:  frame_0, frame_edge_0, slot_0_0, slot_edge_0_0    campaign
    component 1:  frame_1, frame_edge_1, slot_1_0, slot_edge_1_0    SFLeadId

So each can be evaluated to a set of `?entity` independently and the sets
INTERSECTED. Nothing about the frame structure requires correlating them.

This explains every negative result on this shape: `MAX_PROBE_CANDIDATES`,
the equality criterion, `refine_chain_constraints`, ANALYZE and the
empty-constant sentinel all optimise WITHIN a component. None of them changes
the fact that two independent components are correlated instead of intersected.
`fast_slot_filter` answers the same question in 96 ms precisely because it
INTERSECTs on `entity_uuid`.

### The codebase already reasons this way

Connected-component analysis over shared variables is an established technique
here, not a new one:

  * `rewrite_edge_table` — "Method 2: var_slots transitive co-reference
    detection", which chains co-references through an intermediate quad rather
    than requiring a direct link.
  * `rewrite_frame_entity_table` — "Match slot quads to edge tables via shared
    slot variable".
  * `semijoin._split_bgp` — partitions a BGP around the projected variable
    already; its defect is that it produces ONE anchor and ONE blob, and picks
    the anchor structurally.

So the component split generalises what those passes do rather than introducing
a new idea: partition over the projected variable, evaluate each component to a
set of that variable, intersect.

### Why it matters beyond this shape

It applies to ANY query with several independent criteria on one projected
variable, with or without a derived table to serve them. The derived table makes
each component cheap; the split is what stops them multiplying.
