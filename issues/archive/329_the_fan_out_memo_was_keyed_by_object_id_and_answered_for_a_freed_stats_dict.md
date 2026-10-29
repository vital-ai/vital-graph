# 329 — The fan-out memo was keyed by object id, and answered for a freed stats dict

## Status: RESOLVED 2026-10-29 (not yet released). Found as a CI-only unit failure; fixed with the memo carried by the stats object itself.

**Related:** `issues/293` (the cardinality model and the slot-group CTE that read
the fan-out), `generator._load_quad_stats` / `invalidate_stats_cache`.

## What

`slot_group_cte.mean_fanout` (a predicate's mean subjects per object, read by
the slot-group gate and by `bgp_cardinality`) memoised its answer in a module
dict keyed by `(id(quad_stats), predicate)`. The scan it saves is real: on
production `rdf_stats` holds ~1.2M pairs.

An `id()` is reused once its object is freed. So a stats dict created later
could land on a freed one's id and be answered with the freed dict's fan-out:

* **on a server**: a space's stats reloaded after `invalidate_stats_cache` (every
  recompute NOTIFY, `issues/300` / `305`), or another space's stats landing on a
  freed id, priced joins on another space's numbers, or on pre-recompute ones.
  Different SQL, same results: a plan-quality defect, silent;
* **on CI**: `test_no_statistics_declines_rather_than_guessing` builds a fresh
  `AliasGenerator` with empty stats and expects no slot group; in CI's run order
  the empty dict got the id of an earlier test's 1,000-member stats, and the
  memo answered 1,000. Red on main from 2026-10-29 12:14 (it passed locally,
  where the order differed).

## Fix

`slot_group_cte.StatsDict`, a `dict` with a `memo` slot. The generator builds
the cached `quad_stats` as one; `mean_fanout` memoises inside it, so a memo lives
exactly as long as the numbers it came from. A plain dict (tests, ad hoc
callers) is computed every call, never cached under an id. Nothing writes to
`quad_stats` after the loader builds it, so the memo cannot go stale.

Not taken: a strong reference in a module cache (blocks id reuse, but keeps
every invalidated stats dict alive until the cache is cleared: up to hundreds of
MB of dead statistics); a weak-key dict (a `dict` is neither hashable nor
weak-referenceable).

## Verification

`tests/unit/sparql_sql/test_slot_group_cte.py::test_a_fanout_is_never_answered_for_a_different_stats_object`:
a plain dict changed between two calls gives the new answer (the old code
returned the stale 10 for 20, checked), and two `StatsDict`s keep their own
memos. Unit suite 0 failures; the slot-group / cardinality integration tests
pass.
