# Absence-Defined Filters Scan Every Row Once the Predicate Actually Exists

## Status: PARTIALLY FIXED 2026-08-13 — fast when the predicate is absent, still 9.7 s when it is not

The frames "Assertion" tab took **13.4 seconds** on a 1.1M-frame graph. It is now
**1.9–2.3 s**. (It measured 0.55–0.9 s before fix 3 below was reverted for
returning 0 on any COUNT over a UNION; the count is the remaining cost.) But the fix only reaches the case where the predicates are
missing from the space entirely, and **22 of 79 spaces on this database do have
them**. In those spaces the same shape is still measured at 9.7 s.

## What "Assertion" asks for

A KGFrame is an Assertion if `hasKGFormType` says so explicitly, OR if it has
**neither** `hasKGFormType` **nor** `hasFrameGraphURI`. The endpoint compiles
that second half to two `FILTER NOT EXISTS` clauses, which is a faithful
translation and the root of the cost: **the class is defined by absence**, and
absence cannot be looked up in an index. Every candidate frame must be probed.

## What was fixed

Both fixes are in the SQL pipeline, not the endpoint, and both were chosen by
measurement — several plausible-looking culprits turned out to cost nothing.

**1. A `NOT EXISTS` over a body that can never match is now folded away**
(`prune_union.fold_dead_not_exists`). If the body REQUIRES a term absent from
the term table, it matches nothing for any outer row, so the filter is a
tautology. Left in, the absent constant compiles to a scalar subquery over an
empty `_const` CTE, every comparison is NULL, the planner cannot fold it, and it
builds the correlated anti-join and runs it per candidate row:

    anchor + re-anchor                          0.4 ms
    anchor + re-anchor + 2 dead NOT EXISTS  4,506.1 ms

**2. An unrequested `ORDER BY` is no longer invented** (`build_sort_clauses`).
With no `sort_by`, the query carried `ORDER BY ?frame` — the anchor's URI TEXT,
which lives in the term table — so the backend resolved every candidate's URI
and sorted all 1.1M before LIMIT threw the sort away. Paging stays stable
because the pipeline synthesizes `ORDER BY <anchor>__uuid` for an unordered
SLICE; verified that ten consecutive pages partition with no overlap and that a
given page is repeatable.

    ORDER BY ?frame     5,571 ms
    no ORDER BY           611 ms

**3. `COUNT(?v)` no longer requests text for `?v`** — **REVERTED the same day,
it was wrong.** See below.

    count with the term JOIN   2,180 ms
    without it                   542 ms

End to end over HTTP, `sp_lead_synth_100k`, 1.1M frames:

| | before | after |
|---|---|---|
| Assertions tab, cold | 13,366 ms | 2,333 ms |
| Assertions tab, warm | 11,466 ms | 1,883 ms |
| Aspects tab | 84 ms | 44 ms |

## Fix 3 was reverted — it returned 0 for any COUNT over a UNION

`var_scope` was taught to skip text resolution for a variable that is only ever
COUNTed, because COUNT aggregates the UUID column. That is true of the
aggregate and false of the JOIN feeding it. `emit_join` compares the sides on
their TEXT columns:

    ON CAST(j0.v0 AS TEXT) = CAST(j1.v3 AS TEXT)

With text withheld both sides are NULL, `NULL = NULL` never holds, the join
matches nothing, and the count is 0. An interlock was added in `emit_group` so
the aggregate reads the UUID column when text is absent — it covered the
aggregate and missed the join predicate entirely, which is the narrower mistake
inside the wrong one.

Found while fixing the frames slot panel: the same pattern returned 4 rows as
`SELECT DISTINCT ?slot` and 0 as `COUNT(DISTINCT ?slot)`. Confirmed against
`e4e4536~1` — pre-change 3, post-change 0 — so it was this change and not a
pre-existing defect.

The cost of reverting is real and worth naming: the assertion count goes back
from 542 ms to 2,877 ms. It is still far better than the 5,965 ms it started at,
because the `NOT EXISTS` fold does the heavy lifting and is unaffected. A count
that is fast and silently zero is not a faster count.

**Why no test caught it.** A count over a plain BGP was correct throughout; only
a count over a UNION broke, and nothing exercised that. There is now
`tests/integration/test_count_over_union.py`, verified to FAIL against the
reverted code (2 of 3 cases) and pass with it.

**If this is attempted again**, the variable must be proven not to be a join
key, or `emit_join` must compare UUIDs when text is unavailable. Joining on
UUID is arguably better anyway — it is narrower and already what COUNT and the
synthesized paging order use — but it is a change to the core join emitter and
wants its own differential test rather than being smuggled in as an
optimisation.

## What is NOT fixed

Fix 1 fires only when the predicate is absent. Make the `NOT EXISTS` live and
the cost comes straight back — measured on the same 1.1M-frame graph by pointing
the filter at a predicate that space really has:

    LIST with a LIVE NOT EXISTS    9,654.5 ms

So **any space that actually populates `hasKGFormType` still has a slow
Assertions tab**, and that is 22 of the 79 spaces here. The largest is ~5.1M
quads. This has not been measured on those spaces directly — the tab was
reported slow on the synthetic one — so the size of the real-world exposure is
known in shape but not in number.

## Where a real fix would go

Roughly in order of how much they change:

* **Materialise the classification on write.** If every frame carried an
  explicit `hasKGFormType`, "assertion" becomes a positive indexed lookup and
  the anti-joins disappear. This is the only option that makes the query cheap
  rather than merely cheaper, and it is a write-path plus backfill change.
  Note the default is not a constant: an unset frame is an Assertion only when
  it also has no `hasFrameGraphURI`, so a backfill has to evaluate both.
* **A partial index or a derived column** for "has neither predicate",
  maintained like the other derived tables. Same family as `issues/041`, and
  inherits its staleness problem.
* **Teach the planner the anti-join is selective.** When almost every frame
  lacks the predicate, the anti-join returns almost everything, and a plan that
  streams the anchor and probes lazily would let LIMIT stop early. That is the
  shape `emit_slice` already reasons about for deep pages.

## Things to be careful about

* **The UNION arm and the re-anchor are NOT the problem**, despite looking like
  the obvious culprits. Measured: dropping the dead arm changed nothing
  (5,586 ms vs 5,571 ms), and the self-join the re-anchor creates costs 0.4 ms
  because PostgreSQL collapses it. The re-anchor is there for correctness — a
  filter-only UNION branch mistranslates to a global anti-join — and removing it
  measures fast for that reason, not because it is redundant.
* **Do not "fix" this by dropping the DISTINCT.** It is what makes the UNION
  arms not double-count, and `issues/046` records the elision being wrong before.
* A non-negated `EXISTS` over a dead body is constant-FALSE, which would make
  the enclosing pattern empty. That is a larger rewrite than dropping a conjunct
  and is deliberately not done; `query_is_provably_empty` covers the
  outer-constant form of the same idea.

## Related

- `issues/073` — provably-empty queries, the same "constant absent from the term
  table" reasoning applied to the outer plan
- `issues/046` — why the DISTINCT above a semi-join may not be elided
- `issues/041` — derived tables going stale, the risk any materialisation here
  would inherit
