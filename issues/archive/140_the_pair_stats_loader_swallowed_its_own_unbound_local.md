# The Pair-Stats Loader Swallowed Its Own UnboundLocalError, At DEBUG, For Two And A Half Weeks

## Status: FIXED 2026-09-01 — `still` is bound before the branch that used it,
## the handler is WARNING with a traceback instead of DEBUG, and
## `tests/unit/sparql_sql/test_pair_stats_loader.py` pins the path that had none.
## Found by deploying to the TEST stack before production, which is the point.

## What happened

`generator._load_missing_pair_stats` loads everything the semi-join gate and the
join reorder read. Its whole body is wrapped in `except Exception` — deliberately,
because a statistics lookup failing should degrade a plan rather than fail a
query. The handler logged at DEBUG. Production runs at INFO.

`be8159c` (2026-08-14) made the pair-counting block conditional:

    if missing:
        ...
        still = [pr for pr in missing if pr not in aliases.extra_quad_stats]

so that range and text statistics are still collected when the pair counts are
all cached — a real fix, `issues/090`'s neighbour. It left the trailing summary
log referencing `still` unconditionally:

    logger.debug("semijoin gate: resolved %d/%d pair stats (%d counted), ...",
                 len(aliases.extra_quad_stats), len(missing),
                 len(still), ...)

So **every query whose leaf pairs were fully cached raised `UnboundLocalError`
and had it swallowed**, from 2026-08-14 until a test-stack deploy on 2026-09-01.
The commit that fixed the fully-cached path introduced a defect on precisely
that path.

## Why it was invisible, and why that is the real defect

Nothing was lost. The log is the LAST statement in the `try`, and the handler
only logs — `extra_quad_stats`, `range_stats`, `text_stats` and
`saturated_pairs` were already assigned on `aliases`. The gate got its
statistics. The plan was correct.

What it cost was diagnosis, twice over:

* **A genuine failure reports identically.** `pair stats lookup failed: …` is
  emitted for "the statistics table is gone" and for "this function has a typo",
  with nothing to separate them. On first sight the reasonable read is that the
  gate is degraded — which is exactly the conclusion drawn when it surfaced.
* **It fires at INFO too.** `logger.debug()` evaluates its arguments eagerly, so
  the exception was constructed, raised and handled on every fully-cached query
  in production. Only the message was suppressed. The DEBUG level did not make
  it cheap; it made it silent.

## The fix

**1. Bind before the branch.** `still = []` above `if missing:`, with the reason
at the site.

**2. The handler is WARNING, with `exc_info`.** Everything this function loads
decides a plan shape. Losing it degrades every leaf to "unmeasured", which is the
input that made a 2.7 ms lookup cost 54,949 ms (`issues/138`, `issues/139`). A
silent degradation of the thing that chooses the plan should be loud. The message
now names the consequence rather than only the exception:

    semijoin gate: pair stats lookup failed, plan will be chosen without leaf
    statistics: <error>

**The two changes belong together.** At WARNING without the `still` binding, this
would flood production — one warning per fully-cached query. Raising the level on
its own would have been the wrong change.

**3. Tests.** `test_pair_stats_loader.py`, three cases: the fully-cached path
reaches the summary rather than the handler; the four output attributes are
always initialised; and a real fault is reported at WARNING naming its
consequence. Verified to FAIL without the fix, with the production error:

    UnboundLocalError: cannot access local variable 'still' where it is not
    associated with a value

## What this says about the pattern

Three of the four defects found in this investigation were **silent by
construction** — a broad `except` or an absent value read as a legitimate
answer:

* `issues/138` — a truncated lookup key missed, and `_leaf_rows` returned the
  next smallest leaf instead of nothing, so the "unknown means decline" guard
  never fired.
* `issues/139` — a pruned statistics row read as "absent means zero" and the
  incremental writer stored a post-prune delta.
* this one — a bug inside a `try` whose handler was quieter than the deployment.

The shared shape is that **absence and failure were both readable as ordinary
answers.** `issues/105` and `issues/082` are the same argument on the write and
read paths. It is worth a sweep of the remaining blanket handlers in
`generator.py` for the same property; none is examined here.

## Related

- `issues/138` — the gate this loader feeds; both were found the same day.
- `issues/108` — a stale image hiding regressions. Same family: the test stack
  earning its keep, here by catching a regression before promotion.
