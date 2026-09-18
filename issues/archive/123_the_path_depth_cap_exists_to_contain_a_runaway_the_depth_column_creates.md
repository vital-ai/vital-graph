# The Path Depth Cap Exists to Contain a Runaway the `depth` Column Creates

## Status: FIXED 2026-08-23 — was OPEN — found 2026-08-22 while looking for a way to remove the
## truncation in `issues/122`

`MAX_PATH_DEPTH = 100` (`emit_path.py:49`) is documented as "cycle prevention +
backstop". It is doing that job — but the cycles it prevents are ones the CTE
would not have if the `depth` column were not in it.

## The mechanism

All three recursive CTEs (`emit_path.py:372`, `:392`, `:452`) are built as

    rec(start_uuid, end_uuid, depth, ctx_uuid) AS (
      SELECT start_uuid, end_uuid, 1, ctx_uuid FROM (base)
      UNION                                   -- deduplicating, not UNION ALL
      SELECT r.start_uuid, step.end_uuid, r.depth + 1, r.ctx_uuid
      FROM rec r JOIN (base) step ON r.end_uuid = step.start_uuid
      WHERE r.depth < 100 )

`UNION` deduplicates, which is what normally makes a transitive-closure
recursion terminate on cyclic data: revisiting a pair adds no new row. **But
`depth` is part of the tuple**, so `(s, e, 1)` and `(s, e, 2)` are different
rows and the dedup never fires. The recursion then runs until the cap stops it.

Demonstrated on a three-node cycle `a -> b -> c -> a`:

    with depth + cap    300 rows, max depth 100   (stopped only by the cap)
    no depth, no cap      9 rows                  (terminated on its own)

Nine is the correct answer — three start nodes times three reachable ends.
Three hundred is the same nine repeated across a hundred depth values.

## `depth` has no other consumer

Every mention of it in `emit_path.py` is the column list, its increment, and
the comparison against the cap — lines 372, 376, 379, 392, 396, 400, 440, 446,
452, 456. It is never selected out of the CTE, never returned, never read by a
caller. **It exists to be compared against a limit that exists because of it.**

## What removing both would fix

* **`issues/122` properly.** A collection longer than 100 elements is currently
  truncated silently. Without the cap there is no limit to hit — and that is a
  better outcome than that issue's option 2, which was to make the truncation
  loud rather than remove it.
* **Deep frame nesting.** The comment at `:37` names arbitrary-depth frame
  nesting as "an active correctness surface" and says the cap "must be high
  enough to NOT truncate" it. At 100 it happens not to. Removing the cap
  removes the question.
* **Work on cyclic and multi-path data**, per the numbers above.

## Why the cap is not load-bearing as a safety fence

The file says so itself, at `:41`:

> It is NOT the primary runaway fence: a high-fan-out predicate over a
> billion-row table blows up in 2-3 steps regardless of this cap, while a low
> cap only penalizes narrow deep paths. Runaway is fenced by
> `statement_timeout` + `temp_file_limit` (Tier-0 config). This value is just a
> cycle/backstop.

So the argument for keeping it rests entirely on cycle prevention, and the
experiment above shows `UNION` does that on its own once `depth` is gone.

## What to check before doing it

1. **All three sites, and the two `UNION SELECT` forms at `:430` and `:478`**
   (the zero-length arms). They must stay deduplicating.
2. **That nothing downstream reads a four-column CTE.** `depth` is dropped from
   the tuple, so any consumer expecting four columns breaks loudly — verify it
   is really unread outside this file.
3. **Whether any path shape NEEDS ordinality.** None does today. `vg:listIndex`
   would (`rdf_collections.md` §9.5), and that is the one case where a depth
   column earns its place — lists are acyclic by construction, so it can carry
   depth without needing a cap for safety.
4. **A cyclic-data test**, which does not exist. The behaviour above was
   demonstrated in raw SQL for this issue, not by anything in the suite.

## Relationship to issues/122

`issues/122` records the symptom — a silently truncated collection — and its
option 2 was to make the truncation loud. If this issue is done, that becomes
unnecessary: there is nothing to truncate. **Prefer this.**


## FIXED 2026-08-23 (`df9a06f`)

Both removed. All four recursive CTE sites now carry `(start_uuid, end_uuid,
ctx_uuid)` and terminate by `UNION` dedup.

The four checks this issue asked for, answered:

1. **All sites, including the zero-length arms** — done; the identity base no
   longer emits its `0` depth literal either.
2. **Nothing downstream read a four-column CTE** — confirmed; every reference
   to `depth` was inside `emit_path`.
3. **No path shape needed ordinality** — confirmed. `vg:listIndex` would, and
   `rdf_collections.md` §9.5 records that lists are acyclic so it could carry
   depth without needing a cap.
4. **A cyclic-data test** — written FIRST, as
   `tests/integration/test_recursive_path_termination.py`.

Two existing tests asserted the old behaviour and had to be changed:
`test_emit_path` asserted `"depth" in sql`, and `tier0_safety` asserted
`16 <= MAX_PATH_DEPTH <= 128` as a runaway fence. Both now assert that the CTE
deduplicates — termination follows from the graph being finite, which is a
stronger guarantee than a constant, and a switch to `UNION ALL` now fails a
test rather than hanging a query.

Perf: 107/108 within tolerance, 0 failing, one +5.3% buffer warning on
`traversal.skew2k.dedup.depth3`.