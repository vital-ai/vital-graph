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
