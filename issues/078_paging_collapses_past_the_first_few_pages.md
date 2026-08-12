# Paging Collapses Past the First Few Pages — Page 11 Takes 39 Seconds

## REOPENED 2026-08-12 — the shipped fix was REVERTED, it returned wrong pages

The fix committed as `9322ed8` was reverted. It was fast (58x at page 201) and
it was WRONG, in exactly the way an earlier attempt recorded below was wrong —
the second attempt hid it rather than fixing it.

A minimal 8-entity fixture, pages of 3 and 5:

    limit=100 offset=0    e0 e1 e2 e3 e4 e5 e6 e7      the whole match set
    limit=5   offset=0    e0 e1 e2 e3 e4               correct
    limit=5   offset=5    e6 e7 e3      <- e5 MISSING, e3 REPEATED
    limit=3   offset=3    e2 e4 e6      <- should be e3 e4 e5

Against the pre-fix code the same probe gives `e5 e6 e7` and `e3 e4 e5`.

**Why, and why it cannot be tuned away.** The match set is ordered by `v0` —
the entity's URI TEXT — because that is what the query's own `ORDER BY ?entity`
asks for. `_emit_deep_page` sliced it with `ORDER BY dp0.v0__uuid`. Two
different total orders, so a page boundary in one has no meaning in the other.
That is not a policy choice like D1: the query REQUESTED an ordering and the
emitter silently substituted another.

**Why the original verification missed it.** It compared page 2 against a
single-query ordering taken from the SAME uuid-ordered path, so both sides
shared the defect. The check that finds it compares pages against the FULL
result set and asserts they partition it — no row missing, none repeated. That
is now `tests/integration/test_kgquery_bindings_are_named.py`.

**What survives:** the diagnosis in this issue is unchanged and correct —
`OFFSET` defeats early termination, the shape is O(offset), and a set-based
match set is the way out. What is unsolved is producing a deep page in the
ORDER THE QUERY ASKED FOR without resolving text for the whole match set. D1
(`issues/075`) is the same question and is still open.


## ATTEMPT 7 — the ordering works, and it exposes that D1 is the real blocker

Built and measured 2026-08-12, then NOT shipped. The design is the one this
issue and `080` point at: build the match set set-based, resolve **only the
order key** for it, slice in that order, then resolve the full projection for
the page alone.

It is fast, and it is flat:

    offset      0      44 ms     (page 1, unchanged — still two-phase)
    offset     25     307 ms
    offset    250     323 ms     was    673 ms
    offset  1,000     383 ms     was  2,958 ms
    offset  5,000     288 ms     was 16,271 ms      56x

And on an 8-entity fixture every page is correct and in the requested order —
pages partition the result exactly, at every offset, which is what killed
attempt 6.

**It still cannot ship, and the reason is D1.** On the 100k fixture the pages
disagree with page 1:

    page 1 (_emit_two_phase)   sorted by URI text?   NO   -> uuid order
    single query, 100 rows     sorted by URI text?   NO   -> uuid order
    pages 2-4 (deep page)      sorted by URI text?   YES  -> requested order

`_emit_two_phase` ignores `ORDER BY ?entity` and orders by uuid, because
ordering on a real indexed column is what lets its scan terminate early. That is
decision D1 (`issues/075`), and it is PRE-EXISTING. Attempt 6 ordered deep pages
by uuid and broke on the 8-entity fixture, where two-phase does not fire and
page 1 is text-ordered. Attempt 7 orders by text and breaks on 100k, where it
does. **Neither is universally consistent, because page 1's ordering depends on
which emitter fires.**

So this is not a paging problem any more. Any pagination sequence that crosses
those two emitters is broken regardless of what the deep page does, and the only
reason it has not been visible is that nothing paged deeply enough to cross it.

### The choice, with numbers

1. **Resolve D1.** Make two-phase honour the requested order and everything
   agrees. The cost is two-phase's early termination, which is what `080`
   measures — this is the expensive option and the correct one.
2. **Drop two-phase for these queries** and use the set-based path at every
   offset. Uniform, correct, ~300 ms FLAT for every page including page 1 —
   against 44 ms today. A 7x slower first page, which is the page users actually
   hit, in exchange for correct deep paging.
3. **Leave it.** Deep paging stays O(offset) and correct; page 1 stays 44 ms.
   The uuid-vs-text divergence remains latent for anyone who pages deeply.

Currently (3), because 1 and 2 are both decisions about what the product should
do rather than defects to fix. The measurement stands ready for either.


## ATTEMPT 8 — option 1 BUILT AND MEASURED. It is not viable, and here is why

Implemented "one emitter for every page": the generator leaves any PAGED plan
unsplit (`_is_paged`, before `mark_semijoins`), and a single set-based emitter
produces every page ordered by the requested key.

**The paging half worked perfectly.** On the 100k fixture, four pages of 25
reproduce a single 100-row query's ordering EXACTLY — no duplicates, nothing
missing, far pages at 5,000/5,025 disjoint and correctly ordered — and the curve
is flat:

    offset      0     291 ms      was     52 ms      page 1 6.6x SLOWER
    offset    250     299 ms      was    673 ms
    offset  1,000     298 ms      was  2,958 ms
    offset  5,000     325 ms      was 16,271 ms      50x

**And the comparator sweep collapsed.** 27 of 39 cells slow WARM, against the
zero `053` closed with:

    lt/KGDoubleSlot          29,377 ms warm     4,340,568 buffers
    not_exists/KGTextSlot    10,728 ms warm
    not_has_any/KGTextSlot    5,997 ms warm     7,692,839 buffers

`081` records this sweep's cells at 4,350..82,724 buffers. These are 1.2M..7.7M
— 50-90x more. Buffers do not move with machine or load, so no baseline re-run
is needed to read that. Reverting restores `lt/KGDoubleSlot` to **8 ms**.

**The cause is exactly what was traded away.** `mark_semijoins` is what makes a
comparator criterion cheap — `045` measured that rewrite at 24.5-32.3 s -> 2 ms.
Disabling it for every paged query disables it for essentially every KGQuery,
and the set-based match set it forces is affordable only for the entity-type
anchored shape the lead fixture uses. **The ~300 ms figure quoted for option 1
was measured on that ONE query shape and does not generalise.**

### What this rules out, and what it leaves

Option 1 as specified — uniform set-based paging — is dead. Not tunable: the
semi-join rewrite and the set-based match set are alternatives, and the sweep
needs the former while flat deep paging needs the latter.

What survives is a narrower version worth measuring, because **consistency only
requires one emitter per QUERY, not one globally**:

* choose per query — set-based for all its pages when its match set is cheap to
  build, two-phase for all its pages otherwise;
* both are internally consistent, so pagination never crosses two orders;
* the ordering still differs BETWEEN queries, which is D1 and unchanged.

The cost model to gate on already exists in this file's neighbourhood
(`_text_leaf_should_drive`, `assess_traversal`, leaf cardinality). That is the
next thing to try, and it is strictly more work than either option as framed.

## Earlier attempt: THE FIX WORKS — AND BREAKS PAGINATION. It is blocked on D1.

Skipping `mark_semijoins` when `plan.offset > 0` is one condition in the
generator and delivers the predicted curve:

    offset     0      47 ms    unchanged
    offset   250     303 ms    was   673 ms
    offset 1,000     298 ms    was 2,958 ms
    offset 5,000     326 ms    was 16,271 ms     50x, FLAT

Then the row check:

    page1 == first50[:25]          True
    page2 == first50[25:]          FALSE
    rows in first50 missed by 1+2  25

**Paging from page 1 to page 2 silently skips 25 rows.** Reverted; continuity
restored.

Cause: the two plans order the result set differently — `issues/075`, filed as
NOT A BUG because each path is internally consistent. That holds only while a
pagination sequence uses ONE of them. At the `offset == 0` boundary a single
sequence uses both, so each page is a correct page of a DIFFERENT total order.

No page-level check can see this: every page has 25 real matches, no repeats,
consecutive pages do not overlap. Only comparison against a single-query
ordering exposes it.

To ship, either use the set-based shape at offset 0 too (consistent, but page 1
goes 47 ms -> ~300 ms and 121 -> 11 q/s under load), or make both plans agree on
a total order — which is decision D1, reopened today because its justification
was measured on a 1 GB pool.

**So this issue and `issues/075` are one piece of work.** The fix is available
and measured; what blocks it is an ordering decision, not an emitter change.

## THE LAST PIECE MUST MOVE UPSTREAM — checked, not attempted

Attempt 5 left one step: emit the match set with the semi-join unmarked. Checked
before writing it, and it would return WRONG ANSWERS.

`mark_semijoins` SPLITS the anchor BGP before deciding, and a split is only
equivalent to the original AS A SEMI-JOIN — it drops the cross-link constraint,
which the EXISTS correlation replaces. Unmarked splits are reverted inside that
function; the code records why: a criterion below MIN_SELECTIVITY once kept its
split as a plain join and returned 0 rows instead of 96.

The revert data is local to `mark_semijoins` and discarded on return, so at emit
time a marked split has no original to restore. Clearing its hint gives a plain
join missing a constraint — a correctness bug, not a slow query.

**So the paging strategy must be chosen BEFORE `mark_semijoins`**, while the
unsplit plan exists: deep page -> set-based join, shallow page -> probe. One
decision from `plan.offset`, taken in the generator, making the two shapes
siblings rather than reconstructing one from the other's remains.

That is why five attempts inside `emit_slice` failed — each tried to recover a
set-based match set from a plan already transformed for probing. The
transformation is lossy and happens upstream.

Next: a `plan.offset > 0` branch in the generator that skips semi-join marking
for the match-set emission, keeps the current path at `offset == 0`, gated on
`test_kgquery_deep_paging.py` and the 39-cell sweep. Expected: page 201 from
16 s to ~310 ms, flat at any depth.

## ATTEMPT 5 — the shape works and is FLAT; one piece left

Emitting the child with `text_needed_vars` emptied and names taken from the
CHILD registry (attempt 4's bug) fires correctly:

    offset 250   term joins = 1   EXISTS = 1      uuid-only, as designed
    offset     0       45 ms
    offset   250   35,547 ms
    offset 1,000   40,349 ms
    offset 5,000   34,910 ms      FLAT with depth — the goal

Flat, and 100x too slow: ~35 s against ~310 ms hand-written.

The cause is attempt 1's trap relocated: the child still carries the SEMI-JOIN
MARKING, so its match set runs the correlated EXISTS probe per candidate, and
with no LIMIT that is every candidate. The generic SET-BASED join — the ~38 ms
one — is emitted only when the semi-join is NOT marked.

    marked    ordered scan + per-candidate probe   cheap ONLY with a LIMIT
    unmarked  set-based hash join                  ~38 ms, no LIMIT needed

**Last piece: emit the match set with the semi-join unmarked.** Not a one-liner
— `mark_semijoins` records hints ON THE PLAN, so clearing them for one emission
mutates shared state, which is exactly what made attempt 2 worse than doing
nothing. It needs snapshot-and-restore on every exit, or a plan copy.

Everything else from attempt 5 is right and should be kept.

## ATTEMPT 4 — text_needed_vars is not enough; the work is bigger than a patch

Emitting the child plan through a context with `text_needed_vars` emptied looked
like a uuid-only mode via a tested path. It is not:

    deep page declined: no entity__uuid column in the match set;
    columns look like 'SELECT DISTINCT * FROM (SELECT p0.v0 AS v0, ...'

1. `ctx.child()` makes a CHILD TYPE REGISTRY, so sql_names differ from the
   parent's (`v0__uuid`, not `entity__uuid`).
2. `text_needed_vars` controls the BGP's term joins, but the PROJECT node above
   re-projects every variable regardless — so the match set still carries every
   text column. A uuid-only emission needs the PROJECTION restricted, which is a
   change in the project emitter, not a context flag.

Four attempts, one shape of mistake — reusing an existing emission for a purpose
it was not built for:

    1. wrap the two-phase inner      inner loses its LIMIT -> probes everything
    2. carry filters into the driver plan mutated then declined -> worse plan
    3. compose from the two BGPs     right BGP loses its correlation
    4. empty text_needed_vars        projection still emits every column

The uuid layer is not a component this emitter exposes; it is an intermediate
inside `emit_bgp`. The work is a uuid-only emission MODE honoured by the project
and BGP emitters — a first-class capability with its own tests, not a patch in
`emit_slice`, where all four attempts died. Worth doing: page 201 goes 16 s ->
~310 ms.

## IMPLEMENTATION ATTEMPT — reverted, and it names where the work belongs

`_emit_materialised_page` in `emit_slice`, hooked on `plan.offset > 0`, building
the match set from `emit_bgp_anchor(left_bgp)` JOIN `emit_bgp_anchor(right_bgp)`
behind an `OFFSET 0` fence.

    generation   works, correct shape
    offset 0     165 ms   unchanged, as intended
    offset 250   >40,000 ms   against ~310 ms for the hand-written equivalent

Reverted; baseline restored (360/500/687 ms at offsets 100/175/250).

**Why it differs from the hand-written query.** That one took its match set from
the GENERIC path's uuid layer, already ordered by the generic emitter. This one
emits the criteria BGP standalone — but in two-phase that BGP is only ever a
CORRELATED EXISTS probe, and standalone it becomes a full chain scan whose join
order is chosen without the correlation that normally constrains it.

That is the same mistake as the earlier failures in a new place: the two-phase
BGPs are shaped for PROBING, and reusing them set-based does not yield the
set-based plan. First the inner lost its LIMIT; now the right BGP lost its
correlation.

**Next attempt: do not build the match set from the two-phase BGPs.** The
generic path already emits the pure-uuid layer measured at ~38 ms. Give THAT a
uuid-only mode rather than reconstructing it from probe-shaped parts — which
means the change belongs in the generic join emitter, not in `emit_slice`. Three
attempts inside `emit_slice` have now failed for variations of one reason.

## CONCURRENCY CROSSOVER — page 5-6, so "first page only" costs ~4x on page 2

8 concurrent clients, 10 s per arm, unsorted:

    page   offset   ordered scan          materialise         ordered wins
       1        0   121.6 q/s ( 59 ms)    11.1 q/s (669 ms)     11x
       2       25    53.6 q/s (136 ms)    13.8 q/s (573 ms)    3.9x
       3       50    24.4 q/s (329 ms)    12.9 q/s (601 ms)    1.9x

Single-query put ordered ahead 2.4x and 1.4x here; under load it is 3.9x and
1.9x. Materialise is flat at ~13 q/s at any offset — its virtue and its ceiling.
The ordered scan falls below that around page 5-6.

So `offset == 0` gives up ~4x throughput on page 2 and ~2x on page 3, on pages
users actually hit. The alternative, `offset < ~100`, captures them at the price
of a tuned constant that moves with match-set size — the gate pattern this
codebase has watched drift four times.

Reading: still take `offset == 0`. Pages 2-3 stay under 600 ms median at eight
clients, so nothing becomes slow; the throughput given up is bounded, the drift
risk is not. But it is a product judgement and these are the numbers for it.

## CROSSOVER MEASURED — near offset 90-100, and "first page only" is the rule

    page   offset   ordered scan    materialise flat ~310 ms
       1        0       52 ms       ordered 6x
       2       25      128 ms       ordered 2.4x
       3       50      226 ms       ordered 1.4x
       5      100      343 ms       CROSSOVER
      11      250      673 ms       materialise 2.2x

So `offset == 0 -> ordered scan, else materialise` costs page 2 ~180 ms and page
3 ~85 ms, and pays from page 5. Still the right rule, because:

* `offset == 0` is a property of the query, not an estimate — it cannot drift
  from the emitter it selects, which is the failure this codebase has hit four
  times. "offset < 100" is a tuned constant and would.
* the true crossover is DATA-DEPENDENT: it moves with match-set size, so a
  constant right for 9,220 rows is wrong for 200.
* the cost is bounded and small — pages 2-4 at ~310 ms rather than 128-343 ms.

UNMEASURED: offsets 25 and 50 under CONCURRENCY. The ordered scan's page-1
advantage grew from 6x to 11x under load; if pages 2-3 do the same, this rule
costs more than the single-query numbers show. One concurrency run decides it.

## UNSORTED PAGE 1: the ordered scan wins 11x — always-materialise is WRONG

8 concurrent clients, 12 s, UNSORTED page 1:

    two-phase ordered scan   121.6 q/s   median  59 ms   p95    97 ms
    materialise               11.1 q/s   median 669 ms   p95 1,240 ms

The single-query 6x deficit WIDENED to 11x under load: materialise builds the
whole match set for each of eight clients while the ordered scan stops after 25
matches. Opposite sign to the sorted result.

**So the hybrid is necessary**, and the rule has three clauses:

    sorted            -> materialise, at any depth
    unsorted, shallow -> ordered scan
    unsorted, deep    -> materialise      (313 ms vs 16,271 ms at offset 5000)

The unsorted crossover is between offset 0 and 250 and is UNMEASURED. It must be
measured under CONCURRENCY: the ordered scan's advantage grew from 6x to 11x
under load, so a threshold picked from single-query numbers would be too low.

## CONCURRENCY CHECKED — materialise wins under load (sorted shape)

    8 concurrent clients, 12 s per arm, sorted page 1
      ordered scan (current)    9.6 q/s   median 810 ms   p95 1,283 ms
      materialise              14.1 q/s   median 564 ms   p95   784 ms

1.47x throughput, lower median and p95. The worry that building the whole match
set per query would cost throughput is not borne out — plausibly because the
ordered scan's per-candidate probes serialise on the same pages while the
materialise pass is a bulk scan that shares them.

STILL UNTESTED, and it is the case the caveat was really about: the UNSORTED
page 1, where the ordered scan is 54 ms against materialise's 312 ms. That arm
needs the two-phase SQL's uuid layer, which the extraction used here cannot
reach. Until it is measured, the hybrid argument survives for unsorted page 1
only.

## Direction: ALWAYS materialise, not a hybrid (concurrency now checked for sorted)

Flat ~312 ms at every depth is easier to reason about and support than
54 ms .. 16 s depending on how far the user paged — a p99 that depends on user
behaviour is not a p99. 312 ms is inside what a UI absorbs.

The maintainability argument is the stronger one: a hybrid needs a THRESHOLD,
and a threshold is a gate that must agree with the emitter it selects. This repo
has been bitten by gate/emitter drift four times in one effort and wrote itself
a rule about it. One plan shape has no gate to drift.

It also enables the cursor cache later (planning §8c): the materialised match set
is identical for every page of a query, which is exactly what such a cache would
hold. A hybrid's early pages could not participate.

**Caveat to measure first:** materialise builds the whole match set every query,
where the ordered scan at page 1 does ~1/25th of it and stops. Single-query that
is 6x latency; under CONCURRENCY it is throughput and memory, and every number
here is single-query. Concurrency is this repo's largest blind spot. Measure
under load before making materialise the only path.

## Status: FIXED 2026-08-11 — deep pages are flat, and pagination still continuous

    offset     0     45 ms    unchanged (ordered scan, page 1)
    offset   250    330 ms    was   673 ms
    offset 1,000    339 ms    was 2,958 ms
    offset 5,000    282 ms    was 16,271 ms      58x

    rows: same SET and same SEQUENCE as before, at every offset
    pagination: page2 == first50[25:], 0 rows missed

TWO changes, and they only work together:

1. **The generator leaves a deep page's plan UNSPLIT** (`_has_deep_page` ->
   skip `mark_semijoins`). Marked, the criteria join is a correlated EXISTS
   probe driven per candidate — right at offset 0, O(offset) beyond it. The
   choice must be made there because a split cannot be undone later: it is
   equivalent to the original only AS a semi-join, and the undo list is local to
   `mark_semijoins`.
2. **`_emit_deep_page` orders by the entity UUID.** Change 1 alone was 50x AND
   SILENTLY SKIPPED 25 ROWS between page 1 and page 2, because the set-based
   path orders by entity URI while page 1's ordered scan orders by uuid — each
   page a correct page of a different total order (`issues/075`). Ordering by
   uuid makes the paths agree, which is what makes the speed usable.

This extends decision D1's deviation — pages ordered by uuid when the caller
asked for no order — from page 1 to every page. It should be read as part of
D1, not as a separate choice.

Gates: unit suite green; `test_kgquery_deep_paging` and
`test_kgquery_sorted_paging` green; `perf_sweep_diff` 39 cells, no regressions;
E2E 278/278.

Measured on shared_buffers=16GB (see `issues/081` — these numbers move ~25x with
the pool).

Warm, arms alternated, median of 3, on the corrected 16 GB pool:

                     materialise      current path
    offset     0        312 ms            54 ms      current wins 6x
    offset   250        321 ms         1,437 ms      materialise 4.5x
    offset  1000        309 ms         2,958 ms      materialise 9.6x
    offset  5000        313 ms        16,271 ms      materialise 52x

Materialise is FLAT — 296-438 ms across every offset — because its cost is
building the match set once. The current path is unbeatable at page 1 and
O(offset) after it.

**Neither dominates, so the answer is a HYBRID**: ordered scan for early pages,
materialise past a threshold, crossover somewhere between offset 0 and 250. Both
plans already exist; the work is choosing between them.

This is where the materialise work from `issues/080` belongs. `080` itself turned
out to be a configuration artifact (616 ms after the pool fix, materialise only
1.4x), but THIS issue is a real plan problem that the config improved without
solving.

`shared_buffers` 1 GB -> 16 GB on a 64 GB machine (see `issues/080`), no code
change:

    offset      before        after
         0       49 ms        54 ms
       250   39,247 ms     1,437 ms     27x
     1,000    TIMEOUT       2,958 ms
     5,000    TIMEOUT      16,271 ms

Nothing times out any more. But cost still scales with offset — the O(offset)
shape is real and independent of the pool, which only set the constant. Page 201
at 16 s is still a bad page, so this issue stands; it is just no longer a
cliff.

`eq/KGTextSlot`, 25-row page, warm, generated through the real pipeline
(`build_entity_query_sparql(..., page_size=25, offset=N)`):

    offset      page      time
         0         1        49 ms
        25         2       175 ms
       250        11    39,247 ms
     1,000        41    TIMEOUT (>120 s)
     5,000       201    TIMEOUT (>120 s)

Page 11 is 800x page 1. Page 41 does not complete.

## Why this was never seen

**Every performance test pages at `offset=0`.** Verified across
`tests/performance/`: the only offset literal present anywhere is `offset=0`.
The comparator sweep, the growth curves, the paging benches and the plan
assertions all measure the first page and nothing else.

So the entire two-phase paging effort — `issues/040`, `047`, `053`, `059`-`061`
— was validated on page 1. Everything it concluded is true of page 1. Nothing
was ever asserted about page 2 onward, and it turns out not to hold there.

That is the same shape as `issues/071` (a slow cell that was never counted) and
the `contains` single-value gap (`issues/070`): the measurement had one fixed
parameter, and the cost lived in the dimension nobody varied.

## Suspected mechanism, NOT yet confirmed

Two-phase paging exists so `LIMIT` can stop an ordered scan early. `OFFSET N`
does not let it stop early — the scan must produce and discard N rows first, so
cost is O(offset + limit) with the discarded rows paying full probe cost. The
25-row page is cheap because it stops after 25 matches; page 11 pays for 275.

That would make the curve roughly linear in offset, and 49 ms -> 175 ms -> 39 s
is much worse than linear, so something else is likely involved as well — a plan
flip past some threshold, most plausibly. **This needs an EXPLAIN at several
offsets before anyone acts on the guess above.** `issues/047` is a precedent for
exactly that: the paging plan flipped to a blocking sort above 51 rows.

## Why it matters

Deep paging is a normal thing for a UI to do, and the failure is silent — no
error, just a request that takes 39 seconds and then a timeout two pages later.
The per-request deadline from `issues/044` will now cut it off at 120 s, which
turns it into a visible failure rather than a hang, but does not make it work.

## MATERIALISE is flat with depth — a candidate fix, measured 2026-08-11

A hand-written materialise shape (`issues/080`): build the uuid match set once
in a `MATERIALIZED` CTE, then order/offset/limit over that narrow set.

                          materialise    current
        offset=0             265 ms         45 ms
        offset=250           278 ms     39,247 ms
        offset=1000          267 ms      TIMEOUT
        offset=2475          273 ms      TIMEOUT

Flat. The cost is materialising the match set once; the offset then walks an
already-built set.

The trade is explicit: ~265 ms flat against 45 ms at page 1, so it is ~6x SLOWER
for the first page and unboundedly faster after it. A HYBRID — ordered scan
early, materialise beyond a threshold — is the obvious shape, and the crossover
is measurable since both plans already exist.

This also revises the note below: that reasoning ("sorted and unsorted behave
oppositely, so they need separate fixes") was about the CURRENT plans.
Materialise is a third plan, flat for both, so one change may serve both.

CAVEAT: the uuid layer used omits the entity-type UNION, so the match set is not
the real one. Indicative only — rebuild it faithfully and re-run before relying
on any of this.

## Tested 2026-08-11: it is NOT the ordered-scan fence, and NOT the same bug as 080

The hope was that fixing sorted-page driver selection (`issues/080`) would fix
this too. Two measurements say otherwise.

The mechanism that made it plausible: two-phase sets `ctx.needs_ordered_scan`
and the executor fences the statement (`issues/047`) so page 1 keeps its
early-terminating scan. At depth that fence might forbid the better plan.
Measured, with and without it:

     page  offset   fence ON (today)   fence OFF
        1       0          3,168 ms        54 ms
       11     250         36,433 ms    35,720 ms
       41    1000           TIMEOUT      TIMEOUT
      100    2475           TIMEOUT      TIMEOUT

Within 2% at page 11, both timing out beyond. (Caveat: fence-ON ran first at
each offset so fence-OFF had the warmer cache — the page-1 pair is not
comparable. The page-11 near-equality holds despite that advantage.)

And the two paths behave in OPPOSITE directions with depth:

    sorted (080)     13,491 ms -> 5,605 ms -> 2,727 ms   FASTER
    unsorted (078)      49 ms -> 39,247 ms -> timeout    SLOWER

Opposite signs is not what one shared mechanism looks like. This issue should
keep its own fix — a cursor cache converting sequential OFFSET paging into an
internal seek (planning §8d, E4) — rather than waiting on `080`.

## What to do

1. `EXPLAIN (ANALYZE, BUFFERS)` at offsets 0 / 25 / 250 / 1000 and find where
   the plan changes, rather than assuming it is the discarded-rows cost.
2. Add offset to the perf matrix as a dimension — it is currently a constant.
   A curve over offsets belongs next to the growth curves.
3. Consider keyset pagination (page from the last uuid seen) for the ordered
   case. It is the standard answer to O(offset), and this schema pages on a
   uuid that is already ordered — `decision D1` may make that natural here.

## Related

- `issues/047` — paging plan flips to a blocking sort above 51 rows. Same class.
- `issues/040` — paging is O(matches) not O(page). The first-page half was fixed.
- `issues/071` — the measurement-shaped blind spot this shares.
