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


---

# ROOT CAUSE ON A LOADED STACK: THE COVERAGE MARKER, NOT THE PLANNER

Measured 2026-09-05 on `lead_nurture_100k` (53.4M quads), quiet database.

The fast path already answers these shapes. Called directly:

    campaign head          21.4 ms   total 78,871   correct
    campaign + ABSENT      19.8 ms   total 0        correct
    SFLeadId present       17.6 ms   total 1        correct

against the SPARQL fallback, which does not finish inside a 90s statement
timeout. So the capability was never missing. What was missing was permission
to use it:

    slot_sort_coverage_is_complete(lead_nurture_100k, Lead) -> False

There was NO ROW for the space in `slot_sort_coverage`, and the marker defaults
to False for every uncertainty by design -- a false NO is slow and correct, a
false YES is silently short (`issues/149`). `_try_fast_slot_filter` therefore
declined on every request and fell through to the plan that times out.

The marker is written by the maintenance coverage probe, and this space is in
`VG_MAINTENANCE_EXCLUDE_SPACES` precisely so periodic jobs leave the 50M copy
alone. Excluded from the jobs means excluded from the probe that enables the
fast path. Running it by hand takes 2.2s and reports 100,000 of 100,000 covered:

    test_scripts/perf/_record_coverage.py lead_nurture_100k

after which the marker reads True and the shapes above are served in ~20ms.

## What this corrects

  * The 55s Nurture timeout is NOT a planner problem and was not fixed by
    `MAX_PROBE_CANDIDATES`. Measured with the probe declined, the count still
    does not finish in 90s -- declining only changes WHICH slow plan runs
    (`issues/166`).
  * `component_intersect` does not fire on this shape at all. With
    `VG_COMPONENT_INTERSECT` set and unset the generated SQL is byte-identical
    (5,220 and 6,356 characters). An apparent 6x improvement from enabling it
    was cache warming between consecutive runs, not the flag.
  * The SPARQL path remains slow and is still worth fixing -- it is what serves
    any shape `can_serve_filter` declines, and any type whose coverage is
    genuinely short. But it is the FALLBACK, and the fallback being slow is not
    why production timed out.

## What has to be true in production

The marker must exist and be true for each queried entity type. That means
`entity_slot_sort` backfilled and the maintenance coverage probe running on the
space -- the `issues/149` prerequisites, which are the actual deploy blocker for
this performance work.

An unset marker has NO SYMPTOM other than slowness: no error, correct answers,
and a fast path that silently never engages. `maintenance_job` logs a failure to
record at WARNING for exactly that reason; a space excluded from maintenance
produces no warning at all, because nothing tried.


---

# PRODUCTION FIX PLAN — MAKING THE FAST PATH STAY ON

The capability is built and measured (~20ms against a >90s fallback). Every
remaining problem is about the MARKER being true when it should be, and the
failure mode is always the same: no error, correct answers, and a silent
reversion to the slow path. The four gaps below are what stands between "works
when run by hand" and "works in production, permanently".

## G1. `resync_all` disables the fast path and does not re-enable it

It CLEARS the marker first -- correctly, because a marker describing the old
contents would let the filter serve a confident subset while the rebuild is in
flight -- then rebuilds `entity_slot_sort` COMPLETELY via
`resync_entity_slot_sort`, and stops. The comment defers re-establishment to
"the maintenance coverage probe afterwards".

So every repair, bulk import and `repair_derived_tables.py` run switches the
fast path OFF for the space, and it stays off until an unrelated periodic job
happens to run. On a space excluded from maintenance it stays off forever. That
is exactly how `lead_nurture_100k` came to time out with a fully populated,
completely correct table underneath it.

FIX: record coverage at the END of `resync_all`, in the same call that cleared
it. The table was just rebuilt in full, so the probe's answer is known-good and
costs 2.2s on a 53M-quad space. Clearing and re-establishing then belong to one
operation instead of two, and the window is bounded by the rebuild rather than
by a scheduler.

## G2. An excluded space loses the fast path silently

`VG_MAINTENANCE_EXCLUDE_SPACES` exists so benchmark fixtures are not re-ANALYZEd
mid-session, and it is empty in production by default -- so this is not a
production defect today. It IS a trap: exclusion is documented as "statistics
and bloat are NOT maintained", and nothing says it also withholds the marker
that enables the FILTER path. Anyone excluding a space for cost gets a
permanent, symptomless performance cliff.

FIX: name the consequence where the exclusion is logged, and warn per cycle when
an excluded space has an `entity_slot_sort` table -- i.e. when the exclusion is
actually costing something.

## G3. The decline has no symptom

`_try_fast_slot_filter` returns None when the marker is not complete, with no
log. That is the correct BEHAVIOUR -- decline, be slow, be right -- but it makes
the cliff invisible: the request succeeds, the answer is correct, and the only
evidence is latency. `maintenance_job` already logs a failed marker WRITE at
WARNING for this reason; the READ side should be equally visible.

FIX: log once per (space, type) when the filter path declines on coverage, at
WARNING, naming what to run. Throttled, because it is per request.

## G4. Nothing brings a space to complete on demand

Maintenance repairs one BOUNDED BATCH per cycle, deliberately -- a full backfill
on a large space is not something a periodic job should attempt. That is right
for steady state and wrong for a deploy: a freshly migrated production space
would converge over an unknown number of cycles, with the fast path off
throughout.

FIX: an operator script that drives `backfill_entity_slot_sort_batch` to
completion for one space or all, then records coverage -- the deploy-time
counterpart to the steady-state job, reporting what it covered so the operator
can see the fast path is actually on.

## Ordering, and what each is worth

G1 is the one that caused the measured outage and is the smallest change. G4 is
what a deploy needs. G3 is what stops the next occurrence being invisible. G2 is
a documentation-and-warning change guarding a foot-gun this session walked into.

## NOT in scope

The SPARQL fallback itself. It is genuinely slow on this shape (>90s) and that
is worth fixing, but it is the path taken when the fast path CANNOT serve, and
making the fast path reliable is what removes the timeouts. Tracked separately
above; `issues/166` records why the semi-join gate is not the lever.
