# Five of the Nine Remaining Slow Cells Are Nested-Loop Misplanning

## Status: DIAGNOSED, not fixed — 2026-08-10, `sp_lead_synth_100k`

`SET LOCAL enable_nestloop = off`, everything else unchanged:

| cell | nestloop on | nestloop off | |
|---|---|---|---|
| `is_empty`/Text | 56,993 ms | 5,831 ms | 9.8x |
| `eq`/Integer | 2,114 ms | **39 ms** | 54x |
| `has_all`/Text | 1,255 ms | **29 ms** | 43x |
| `lt`/DateTime | 1,291 ms | **41 ms** | 31x |
| `eq`/Text | 1,070 ms | **21 ms** | 51x |
| `has_any`/Text | 15,276 ms | 12,251 ms | not this |
| `has_any`/Choice | 13,755 ms | 11,514 ms | not this |

Four of these drop under 50 ms. This is the largest single lever left in
`issues/053`, and it is not a push-down problem — the SQL is already the SQL we
want, and PostgreSQL is executing it badly.

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
