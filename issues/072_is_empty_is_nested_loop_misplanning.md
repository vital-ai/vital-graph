# `is_empty` Is Nested-Loop Misplanning — and Four Other Cells Were Not

## Status: CORRECTED — 2026-08-10. One cell, not five.

    is_empty/Text    47,514 ms -> 5,310 ms    8.9x    REAL
    eq/Integer            37 ms ->    37 ms    ~same
    eq/Double              4 ms ->     4 ms    ~same
    not_exists/Text      173 ms ->   177 ms    ~same
    eq/Text               24 ms ->    23 ms    ~same   (two-phase, sort fence applied)
    has_all/Text          22 ms ->    23 ms    ~same
    lt/DateTime           40 ms ->    38 ms    ~same
    contains/Text         22 ms ->    24 ms    ~same

Alternating arms, three reps, first discarded.

### The retraction, and the mistake that produced it

The first revision of this issue claimed FIVE cells were nested-loop
misplanning, with `eq`/Integer at 54x and `eq`/Text at 51x. Those numbers came
from a harness that ran `for off in (False, True)` — **nestloop=on first on a
cold cache, nestloop=off second on a warm one**. The 50x was the buffer cache,
not the join method.

This is the same cold-cache contamination that voided an earlier round of
measurements in this same effort, reintroduced by writing a fresh loop instead
of reusing `scripts/perf_ordered_scan_fence.py`, which alternates and discards
the first run precisely to prevent it. The lesson is not "be careful" — it is
that a comparison harness should be a shared, reviewed thing, not written inline
each time.

`is_empty` survived because its two arms were run in the opposite order —
nestloop=off FIRST, cold — so its 8.9x is if anything understated.

### What this also retracts

`eq`/Text was described as BIMODAL (1,124 / 107 / 1,335 / 1,258 ms across
sweeps) with the planner "flipping between join methods on a knife-edge
estimate". That was wrong too. It is 23 ms warm, every time. The spread is
first-touch I/O.

### What it says about the sweep itself

Most cells the sweep reports at 0.8-2 s run in **2-40 ms** on immediate
re-execution:

    eq/Text        1,070 ms in sweep    ->  24 ms warm
    has_all/Text   1,255 ms in sweep    ->  22 ms warm
    contains/Text    817 ms in sweep    ->  22 ms warm
    gte/DateTime      36 ms in sweep    ->   4 ms warm

`scripts/perf_comparator_timing.py` executes each cell ONCE, so what it measures
is dominated by first-touch cost, not steady-state. That is a legitimate thing
to measure — production cold-start latency is real, and it is what made the
original timeouts real — but it must not be read as the cost of the query. Cells
in the 1-2 s band are cold-start artifacts; only cells that stay slow warm
(`is_empty`, `has_any`, and the two genuine timeouts) are query-cost problems.

`issues/053`'s "N cells exceed 1s" counts cold-start. Worth reporting both.

## Rewriting `is_empty` as NOT EXISTS is WORSE — measured 2026-08-10

Tried and reverted. The reasoning was: `is_empty` emits
`OPTIONAL { ?slot p ?v } FILTER(!BOUND(?v))`, which compiles to a LEFT JOIN with
an IS NULL filter; `semijoin` refuses to rewrite a LEFT JOIN, so two-phase paging
declines and the plan blocks. `FILTER NOT EXISTS { ?slot p ?v }` is the same
question and is the negation family `issues/057` made fast — `not_has` is 72 ms.

The rewrite did exactly what it was supposed to structurally: `needs_ordered_scan`
flipped to True, the LEFT JOIN disappeared, the semi-join fired. And it went from
**53 s to over 300 s**.

The flaw: `not_has` is fast because its NOT EXISTS body binds a CONSTANT object
(`?slot p <value>`), which is what the candidate-driven fold needs.
`is_empty`'s body binds a VARIABLE (`?slot p ?v`) — that is the `not_exists`
shape, not the `not_has` shape. And `not_exists` is not actually cheap either: it
reads **7,236,171 buffers** to return 0 rows, which the sweep only revealed once
it started reporting buffers. Nesting that at slot level, once per candidate,
is worse than the blocking LEFT JOIN it replaced.

So "emit the question in the form the pipeline optimises" was right as a
principle and wrong about which form that is. The negation path is fast for
constant-object negation, not for negation in general.

## The estimate

`EXPLAIN ANALYZE` on `is_empty` (55,773 ms, 0 rows):

    Nested Loop  (cost=... rows=1) (actual rows=100000 loops=1)
      ...
      Parallel Hash Join (cost=... rows=278) (actual rows=33333 loops=3)

`rows=1` estimated against **100,000** actual, and the error starts lower down:
the edge-table join `q15 ⋈ mv2` is estimated at 22,863 and returns 100,000, then
joining `q11` against it is estimated at 278 and returns 100,000. The planner
assumes the two sides are independent when in this data they overlap almost
completely — every entity has the frame, every frame has the slot.

Believing `rows=1`, a nested loop looks free. It then runs 100,000 times.

Same signature as the production `nurture` slot-value queries that hit the 60 s
client timeout: predicate/object correlation underestimate leading to a
nested-loop blowup.

## What it is NOT

Both ruled out by measurement rather than argument:

**Not the ordered-scan fence.** `enable_sort` on vs off is identical on the
datetime cells (`issues/053`).

**Not GEQO or join-order search.** These plans join 17 relations, past
`geqo_threshold` (12) and `join_collapse_limit` (8), so the genetic optimiser is
active and non-deterministic — an appealing explanation for `eq`/Text reading
1,124 / 107 / 1,335 / 1,258 ms across four runs. It is wrong:

    geqo = off                              59,333 ms   (baseline 48,512 ms)
    join/from_collapse_limit = 20           (>200 s)
    geqo = off + collapse limits = 20       23,436 ms
    enable_nestloop = off                    5,831 ms

Turning GEQO off alone does nothing. The bimodality is the planner flipping
between join METHODS on a knife-edge estimate, not searching orders randomly.

## Why the obvious fix is dangerous

`enable_nestloop = off` cannot simply be set the way `enable_sort = off` is for
`needs_ordered_scan`. The two-phase probe **depends** on nested loops: its whole
design is an index probe per candidate, early-terminating at LIMIT. Disabling
them globally would destroy the O(page) plans this work exists to produce — the
cells above are the ones NOT on that path, or ones where the sort fence is
already applied alongside.

So the fence would have to be conditional on the same signal that already
distinguishes the two regimes, and the interaction with `needs_ordered_scan`
needs to be worked out rather than guessed. Note that `lt`/DateTime was measured
with BOTH fences applied, so its 41 ms is not attributable to `enable_nestloop`
alone.

## Directions, roughly in order of appeal

1. **Fix the estimate, not the plan.** PostgreSQL has no cross-table join
   statistics, so `ANALYZE` cannot learn this. But these joins are through the
   `{space}_edge` and `{space}_frame_entity` derived tables, whose cardinality
   the application KNOWS — `{space}_edge_fanout` already computes exactly this
   per edge type. Feeding it to the planner is the question.
2. **Conditional fence**, gated the way `needs_ordered_scan` is, and set only
   for plans that are already blocking.
3. **`is_empty` specifically** is O(entities) whatever the plan, because its
   answer is empty and absence has to be verified for every entity. 5.8 s may be
   near the floor without a derived structure recording slot presence.

## Related

- `issues/053` — the sweep; these are 5 of its 9 remaining cells
- `issues/071` — `is_empty` and `eq`/Integer, filed as undiagnosed; this is the
  diagnosis for both
- `issues/070` — `has_any`, the two cells this does NOT explain
- `two_phase_kgquery_paging_plan.md` — why nested loops are load-bearing on the
  probe path
