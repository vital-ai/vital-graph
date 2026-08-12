# An Explicit Sort Reverts Paging to O(matches) — 46ms Becomes 18.6s

## Status: LARGELY A CONFIGURATION ARTIFACT — 616 ms after raising shared_buffers

`shared_buffers` was 1 GB on a 64 GB machine; one query here touches 400,000+
buffers (>3 GB). Raised to 16 GB (and `effective_cache_size` 4 -> 48 GB, never
previously tuned), NO CODE CHANGED:

    sorted page, current path, warm    16,411 ms  ->  616 ms      27x
    materialise (sk, uuid)                     —  ->  453 ms      1.4x

The 404x that opened this issue was a buffer pool too small to hold the working
set. The materialise redesign buys 1.4x on a correctly configured server, not
the 50x it appeared to — four implementation attempts and four reverts chasing a
query-shape explanation for a memory setting.

Buffer counts were identical before and after (453,180 vs 416,261), which is why
they are the metric to trust.

REMAINING, and now much smaller: whether 1.4x justifies the emitter work; the
N-key case (unmeasured); and re-baselining everything else measured on the old
pool.

Full plans for review: `planning/planning_performance/sorted_paging_plans.txt`
(unsorted page, sorted page, and the phase-1 shape that times out).

`eq/KGTextSlot`, 25-row page, warm, same criteria throughout:

    no sort                                      46 ms
    sort by entity property (hasName)        18,579 ms      404x
    sort by frame slot                       INVALID SQL — see below

## Why: the sort defeats two-phase paging by construction

    Gather ... rows=9220 (actual time=5.213..26.250)     match set: 26 ms
    ->  Sort  Sort Key: t_v8.term_text, t_v2.term_text
              (actual time=19060.673..19060.898)          19 s
    Limit ... rows=25

The match set is found in 26 ms. The remaining 19 seconds resolves TERM TEXT for
all 9,220 matches so they can be ordered, after which 25 rows are kept.

That is exactly the cost `issues/040` removed for the unsorted case. Two-phase
pages 25 uuids and resolves text for 25; a sort on a text property cannot,
because the order is not known until every candidate's text is resolved. The
fast paths decline here deliberately and correctly — `emit_slice` says so at the
guard: "An explicit sort was requested, so the order key is a sort variable.
Paging on the entity uuid would ignore it."

So this is not a bug in the sort path. It is the sorted path having no
equivalent of the optimisation the unsorted path received, and nothing measuring
the difference.

## Why it was never seen

**No performance test uses `sort_criteria` or an `ORDER BY`.** Verified across
`tests/performance/`. Decision D1's uuid ordering applies only when no sort is
requested, so every benchmark in this repo exercises the unsorted path. The
sorted path — which the UI's query builder offers as a first-class control — has
never been executed by a benchmark.

Same shape as `issues/078` (every test at `offset=0`) and `issues/070` (one
fixed needle per cell): a parameter held constant across every measurement.

## The fix, DESIGN VALIDATED 2026-08-11 — and my first diagnosis was wrong

I first called this structural: "ordering by a value requires knowing the
value". That is true and it is not where the 18.6 s goes.

The full plan is a tower of EIGHT nested loops above the match set, each
estimated `rows=1` against `rows=9220` actual, accumulating 19 ms -> 23,176 ms.
They are resolving TERM TEXT FOR EVERY PROJECTED COLUMN of every match — roughly
74,000 random lookups into a 10.4M-row term table. The sort does not cost that;
it EXPOSES it, because without a sort two-phase pages 25 uuids and only 25 rows
ever reach those joins.

Two measurements settle the direction:

    enable_nestloop=off, +enable_material=off   17,589 ms -> 10,425 ms   1.7x
    resolving ONE column (the sort key) for the
      9,220-row match set, ORDER BY, LIMIT 25                    33 ms

So the misestimate is real but secondary — fixing the join method alone leaves
10 s, because the work itself is 74,000 lookups. The answer is to stop doing
them: resolve the SORT KEY for the match set, take 25, and resolve everything
else for those 25.

That is exactly the two-phase pattern this codebase already uses, extended to
the sorted case:

    phase 1   (entity_uuid, sort_key_text) for all matches
              ORDER BY sort_key LIMIT 25          measured ~33 ms
    phase 2   full projection for those 25 uuids  the existing phase 2

**Where it declines — CORRECTED, having implemented against the wrong answer.**
It is NOT `emit_slice.py:125` / `len(buried) != 1`; that was inferred from the
ORDER BY and never instrumented. Instrumented, `_emit_two_phase` returns at
lines 118-121: for a sorted plan the SEMI-JOIN IS NOT MARKED and there is no
foldable EXISTS join, so it never looks at the ordering. An implementation
built on the ORDER BY theory was written, never reached, and reverted.

**ANSWERED, by instrumenting the plan.** The sort binding is placed on the
WRONG SIDE OF THE JOIN:

    UNSORTED  needed = ['entity']
              bgp[0] binds ['entity']                     <- anchor
              bgp[1] binds [frame_0, slot_0_0_0, ...]     <- criteria
              -> semijoin: marked 1 join(s)

    SORTED    needed = ['entity', 'sort_val_0']
              bgp[0] binds ['entity']
              bgp[1] binds [frame_0, ..., 'sort_val_0']   <- HERE
              -> semijoin: no join rewritten

`collect` puts `?entity vital:hasName ?sort_val_0` in the CRITERIA bgp. A
semi-join discards that side, and `sort_val_0` is needed above it for the
ORDER BY — so `mark_semijoins` declines, CORRECTLY. Everything downstream
follows from that one placement: no semi-join means `_emit_two_phase` returns at
its first guard, which is why the sorted path gets the generic O(matches)
emission.

The plan TREES are identical between the two cases — `slice > distinct > project
> order > join(bgp, bgp)` — so this is not a shape difference. It is which bgp
owns one triple pattern.

**That makes the fix smaller and earlier than the emit change.**
`?entity vital:hasName ?sort_val_0` shares only `?entity` with the criteria; it
belongs with the anchor. Placed in bgp[0], `sort_val_0` is bound by the side the
semi-join KEEPS, the marker fires, two-phase engages, and the ordering work
(steps 1-5 of the sequence) becomes reachable at all.

**And the placement comes from the BUILDER, not `collect`.** Traced: the sort
binding is emitted as the last triple of the criteria block —

    { ?entity vitaltype KGEntity } UNION { ... }     -> bgp[0]
    ... all the criteria triples ...
    ?entity <vital-core#hasName> ?sort_val_0 .       -> bgp[1], HERE

The UNION forms one BGP and consecutive triples after it form the next, so the
sort binding is grouped with the criteria purely by adjacency in the generated
text. `collect` is faithfully reproducing what it was handed.

Moving it earlier is NOT sufficient — consecutive triples still coalesce. It
needs its own group, `{ ?entity vital-core:hasName ?sort_val_0 . }` right after
the UNION, so the boundary forces a separate BGP:
`join(join(union, sort_bgp), criteria)`. That also changes what two-phase sees —
the anchor side becomes a two-BGP join — so `find_bgp(sj.children[0])` and
`emit_bgp_anchor` both need checking against it, by instrumentation.

**The builder change ALONE is a REGRESSION — measured, then reverted.** Applied
as described, it does clear the blocker: a sorted plan reports
`semijoin: marked 1 join(s)` where it previously reported "no join rewritten".
And the query went from 18,579 ms to TIMEOUT (>200 s).

Because clearing the blocker means `_emit_two_phase` is now ATTEMPTED, still
declines at `len(buried) != 1` — nothing has taught it the two-key order yet —
and falls through to the generic emission carrying a plan whose BGP is now split
and whose join is marked. The generic path emits worse SQL against that shape.

**So this is a PAIR that must land in one commit.** The builder placement is
necessary and not sufficient; the emit change is sufficient and unreachable
without it. Either alone leaves the sorted path slower than doing nothing — and
the builder half is the dangerous one, because `semijoin: marked 1 join(s)` is
exactly the signal you would read as success.

Order for the next attempt: builder placement, THEN the emit two-key support,
and only then measure — the intermediate state is expected to be worse and
proves nothing.
Note this also invalidates Step 3's assumption, which asserted the sort quad
lands in the anchor bgp — it does not, today.

What DOES hold about the ordering, verified: the builder emits two keys:

    unsorted   ORDER BY ?entity
    sorted     ORDER BY ASC(?sort_val_0) ?entity

The tie-breaker is `?entity`, the SAME uuid the page already orders by, so a
sorted page ordering on `(sort_key, uuid)` reproduces the SPARQL semantics
exactly. There are no ties to break differently and D1 does not need reopening.

The full step-by-step sequence — decline point, anchor variable, sort column,
page shape, the `needs_ordered_scan` trap, and the gates — is in
`planning/planning_performance/two_phase_kgquery_paging_plan.md` section 8a.

### The concrete shape, traced 2026-08-11

Today's page is (`emit_slice.py`, end of `_emit_two_phase`):

    SELECT DISTINCT ON (col_ref) col_ref AS {sn}__uuid
    FROM {from_sql} WHERE {conds} AND EXISTS ({probe})
    ORDER BY col_ref
    LIMIT {limit}

The sorted variant cannot simply swap the ORDER BY: `DISTINCT ON (col_ref)`
REQUIRES `ORDER BY` to lead with `col_ref`. So the dedup and the ordering have to
be separated —

    SELECT * FROM (
        SELECT DISTINCT ON (col_ref) col_ref AS {sn}__uuid,
               {t_sk}.term_text AS __sort_key
        FROM {from_sql}
        JOIN {term} AS {t_sk} ON {t_sk}.term_uuid = {sort_col}
        WHERE {conds} AND EXISTS ({probe})
        ORDER BY col_ref                      -- required by DISTINCT ON
    ) d
    ORDER BY d.__sort_key {direction}
    LIMIT {limit}

then phase 2 joins the term table for the full projection of those `limit` rows,
exactly as it does today.

`{sort_col}` is the quad column binding the sort variable. The open question — and
the first thing to check when picking this up — is whether that column is already
in `from_sql`: the SPARQL binds `?entity vital:hasName ?sortVar`, so `collect`
should place that quad in the ANCHOR bgp, in which case the join above is the only
addition. If it lands elsewhere, phase 1 needs that leaf pulled in first.

Note what this gives up deliberately: phase 1 now MATERIALISES the match set and
sorts it (9,220 rows, measured 33 ms) instead of early-terminating. That is the
trade — `ctx.needs_ordered_scan` and the `issues/047` fence exist for the
unsorted path and should NOT be asserted here, because there is no ordered scan
to protect.

**Gate before believing any of it:** `tests/performance/test_kgquery_sorted_paging.py`
records 3x at 10k and 203x at 100k. The 100k ratio is the number that has to move,
and the 10k one must not regress. Then `scripts/perf_sweep_diff.py`, 39 cells.

**Not implemented here, deliberately.** It is a change to the paging core —
the code with two prior reverts behind it, gated on the 39-cell sweep — and
landing it half-measured would be worse than leaving it. What is de-risked is
the design and its size: ~33 ms against 17,589 ms is the target, and the fence
alternative (1.7x) is not worth shipping.

## CLOSING FINDING: the fix direction in this issue is WRONG. Measured 2026-08-11.

The phase-1 shape was measured standalone, which is what should have been done
before any of it was built:

    1. unsorted page (two-phase, current)      2,999 ms
    2. sorted page (generic path, current)    21,249 ms
    3. phase-1 shape: DISTINCT ON over the
       match set + term join, then order       TIMEOUT (>200 s)

**Phase 1 is slower than the thing it was meant to replace.** So no amount of
plumbing — the builder placement, the two-key order, the split page — could ever
have produced a fast sorted page. Four attempts failed for one reason, and it
was visible in a single 200-second measurement nobody took.

**Why, and this vindicates the FIRST diagnosis over the correction.** The 33 ms
figure came from a bare `uuid -> term_text` join over an ALREADY-MATERIALISED
9,220-row set. Real phase 1 has to produce that set, and producing it means
dropping the `LIMIT` — which is precisely what makes the unsorted page cheap.
With `LIMIT 25` the `Unique` stops after ~25 criteria probes. Without it, every
match is enumerated and every one pays the `EXISTS` probe.

So the cost is NOT term resolution, and it is not a mis-planned join tower
either. **Ordering by a value requires evaluating the criteria for every row in
the result set, and the unsorted page is fast only because any 25 rows will do.**
That is inherent to sorting, not an artefact of this emitter. The earlier
"structural" reading was right; the "it is really 74,000 term lookups"
correction identified a real secondary cost and mistook it for the primary one.

## BUFFERS: the two shapes do the SAME WORK

    current sorted path      453,180 buffers
    materialise (sk, uuid)   416,273 buffers    8% fewer

Machine-independent, immune to cache order. **Materialise is not a work
reduction** — the 2.2x median and the 836 ms minimum below were cache effects.

### And the buffer pool is 1 GB, on a 64 GB machine

    shared_buffers 1 GB   effective_cache_size 4 GB   work_mem 16 MB

A single query here touches 400,000+ buffers (>3 GB) against a 1 GB pool, so
every wall-clock number in this issue was dominated by eviction. That explains
the 15x spreads and the order-dependence, and it puts a question mark over every
timing-based conclusion in this repo's performance work, not just this issue.

`shared_buffers` cannot exceed physical RAM but has huge headroom here (~25% of
64 GB is the usual start). `effective_cache_size` is ADVISORY — it can be set to
anything, allocates nothing, and at 4 GB the planner believes far less is cached
than a real server would have, which biases it away from index scans and is
plausibly connected to the nested-loop misestimation seen throughout.

**Re-baseline on a representative configuration before continuing.**

## FIRST SOUND MEASUREMENT — materialise is ~2.2x, alternating arms

`perf_ab.py` discipline — arms alternated per repetition, repetition 0 discarded
in both, 4 reps:

    current sorted path      median 16,764 ms   min  8,357   max 23,313
    materialise (sk, uuid)   median  7,777 ms   min    836   max 13,093

**~2.2x faster on the median, tie-break included.** This supersedes the ~300 ms
figures, the 50x and the retraction — all three came from sequential loops.

Modest, but note the minimum: materialise reaches 836 ms; the current path never
went below 8.4 s in any repetition. Only one of the two shapes is CAPABLE of a
fast page, which is the case for continuing with it.

Open problem: variance. 836 -> 13,093 ms for one query, and 8,357 -> 23,313 ms
for the other. Likely the arms evicting each other from shared_buffers —
alternating fixes ordering bias but introduces contention. Next measurement
should be BUFFER COUNTS rather than wall clock: machine-independent, and the
comparator sweep already prefers them for this reason.

## MEASUREMENT INVALID — the materialise timings are cache-order artifacts

Same variants, two runs, different order:

    run 1   ORDER BY sk      ~300 ms     ORDER BY sk, uuid   17,629 ms
    run 2   ORDER BY sk     9,082 ms     ORDER BY sk, uuid      328 ms
                                         + phase-2 reorder      346 ms

The numbers swapped. What predicts the timing is which case ran FIRST — it pays
the cold materialise and everything after is ~300 ms.

**So the 50x claim and its retraction are BOTH unsound.** The relative cost of
`ORDER BY sk` versus `ORDER BY sk, uuid` is unknown. Everything timing-based in
the sections below — the ~300 ms figures, flat-with-depth, the comparison
against the current path — needs re-measuring with alternating arms.

What survives: measurements taken from PLAN OUTPUT rather than wall clock —
criteria 38 ms versus resolution ~19 s — since those are node timings within one
execution.

Use `scripts/perf_ab.py` or `test_kgquery_sorted_paging.py` (warm-up + median of
three). Do not hand-roll another sequential timing loop: that produced all three
voided rounds in this effort.

## RETRACTION — the 50x was measured without a tie-break

    ORDER BY sk                        ~300 ms    <- what the 50x was based on
    ORDER BY sk, uuid       (D2)     17,629 ms
    ORDER BY sk, entity URI          22,215 ms
    ORDER BY sk, URI @ offset 2475   17,540 ms
    current sorted path              16,411 ms

**With a deterministic tie-break the materialise shape is NOT faster** — 17.6 s
against 16.4 s. The ~300 ms figures describe `ORDER BY sk` alone, which is not a
usable page: without a tie-break the order among equal sort keys is arbitrary
and page 2 cannot continue from page 1.

Every "50x", "flat at ~300 ms" and "gate passed" claim below rests on that query.

Still holds: flatness with depth (17,540 ms at offset 2475 vs 17,629 ms at 0),
which matters for `issues/078` where the current path times out by page 41 — but
17.5 s is a poor page in absolute terms. And the structural attribution
(criteria 38 ms, resolution ~19 s) is unaffected, having come from the plan
rather than these timings.

Killed: the sorted-page win. `080` is not solved by this shape as measured.

How it happened: the tie-break was dropped when the experiment was simplified to
isolate sort cost, the favourable number was quoted four times, and the
correctness check that FOUND the missing tie-break was recorded as a semantic
question (D2) without re-running the timings. **When a correctness fix changes
the query, re-measure.**

## The SPARQL endpoint has the same problem — VERIFIED 2026-08-11

Raw SPARQL, no KGQuery criteria, LIMIT 10 on `sp_lead_synth_100k`:

    ORDER BY ?name              name asc, URI UNORDERED        4,018 ms
    ORDER BY ?name ?s           name asc, URI asc                429 ms
    ORDER BY ?t ?name ?s        all three keys asc            13,970 ms
    ORDER BY ?s                 URI asc                        3,366 ms
    ORDER BY DESC(?name) ?s     executes                         544 ms

Multi-variable ORDER BY, URI ordering and mixed ASC/DESC all work — nothing
declines or errors.

**But the cost is the same**, and these have no criteria at all. So this issue is
NOT specific to KGQuery: a fix living only in the KGQuery builder would leave the
SPARQL endpoint exactly as slow. That argues for the emitter as the home for the
materialise work.

It also supports D2 independently: with `ORDER BY ?name` alone the URI column
comes back UNORDERED, so the system already treats ties as arbitrary when no
tie-break is named. D2 is consistent with that, not an exception to it.

## DECISION D2 — ties break by entity uuid. Taken 2026-08-11.

Option 2 of the two below, and it is stronger than a compromise: **the caller
never asked for URI ordering.** `sort_criteria` names only the sort property and
the builder APPENDS `?entity` itself as a stabiliser —

    no sort_criteria      ORDER BY ?entity
    sort_criteria set     ORDER BY ASC(?sort_val_0) ?entity   <- builder-added

so D2 changes the builder's own tie-break, not a request. The sort-key order
remains exact.

Preserved: correctness with respect to what was asked; deterministic, stable
paging; and the same tie-break as D1 already uses for unsorted pages, so the two
paths stop differing.

Cost: a tie group straddling a page boundary yields a different subset than a
URI-ordered reading. Ties are not rare — 9 distinct names across 25 rows.

Scope: the tie-break within EQUAL sort keys only. If a caller names `?entity` as
a sort key themselves, that is a request and must be honoured.

TODO: document this at the endpoint next to `sort_criteria`, not only here.

## CORRECTNESS CHECKED — same rows, different tie-break

    same SET       : True          sort-key sequences identical : True
    same SEQUENCE  : False         distinct sort keys in page   : 9 of 25

Ordering by the sort key is correct; the divergence is entirely tie-breaking,
and ties are heavy (9 distinct names across 25 rows).

    current       ORDER BY ASC(?sort_val_0) ?entity  -> ties by URI STRING
    materialise   ORDER BY sk, uuid                  -> ties by UUID (a hash)

**The same 25 rows came back, and that is luck.** A tie group straddling the
LIMIT boundary would put DIFFERENT MEMBERS on the page under the two orderings.

Not covered by D1: D1 accepted uuid ordering and bounded itself to queries with
NO explicit sort. Here the ORDER BY explicitly names `?entity`, so a uuid
tie-break is a semantic deviation rather than an accepted trade.

Choose deliberately before building:

1. resolve the entity URI text and tie-break on it — one more term join over the
   match set; measure it, it may erase part of the 50x;
2. extend D1 to explicitly-sorted queries and document that ties break by uuid —
   cheaper, but it changes an answer the caller asked for.

## GATE PASSED — faithful match set, warm, 2026-08-11

The entity-type UNION is now included, so the match set is the real one:

                           materialise    current
    SORTED    offset=0        326 ms       16,411 ms    50x
    SORTED    offset=2475     331 ms
    UNSORTED  offset=0        295 ms           45 ms    6.5x SLOWER
    UNSORTED  offset=250      316 ms       39,247 ms   124x
    UNSORTED  offset=1000     296 ms        TIMEOUT
    UNSORTED  offset=2475     311 ms        TIMEOUT

    cold materialise (first touch)  ~5,000 ms

Flat at ~300 ms across a hundred pages, sorted or not. The 5,420 ms and 4,990 ms
figures recorded earlier were both COLD first runs.

Settled: the shape works, it is flat with depth, it fixes the sorted page
outright with no trade, and `MATERIALIZED` is the load-bearing part.

Not settled, each needing its own measurement first: the page-1 regression for
UNSORTED queries (295 ms vs 45 ms — a hybrid is the obvious answer and the
crossover is unmeasured); the ~5 s cold cost, which matters for a UI that pages
once; whether the emitter can assemble this at all; and CORRECTNESS — returning
25 rows in the right order is not the same as returning THE right 25 rows, and
row-identity against the current path has not been checked.

## MATERIALISE design TIMED 2026-08-11 — 16,411 ms -> 5,420 ms, indicative

Hand-written from the generated SQL's own pure-uuid layer, as the gate required:

    WITH _const AS (...), m AS MATERIALIZED ( <uuid-only layer> )
    SELECT m.v2__uuid, t.term_text AS sk
    FROM m JOIN {space}_term t ON t.term_uuid = m.v8__uuid
    ORDER BY t.term_text LIMIT 25

    current sorted page   16,411 ms
    this                   5,420 ms   rows=25

**Caveat: the extracted uuid layer omits the entity-type UNION** (it lives in
the other join operand), so the match set is not identical to the real query's.
The figure is indicative of the shape, not a result to quote.

What it settles — and no previous attempt got this far — is that the design is
not pathological: no timeout, no cross product, no inverted join. `MATERIALIZED`
holds the barrier so the planner joins FROM the match set instead of driving
from the term table, and one term join over that set is affordable, which is the
assumption the whole phase-1 design rests on.

Next: rebuild the uuid layer WITH the entity-type UNION, re-time, then EXPLAIN
to locate the remaining 5.4 s. If it is the sort over 9,220 rows, datatype
narrowing (`dt_val` / `num_val`, both btree-backed) is the next lever — and a
dateTime sort should be measured before a text one.

## The structure, and the MATERIALISE design it points at

The generated SQL resolves term text INSIDE the join operands:

    SELECT DISTINCT ... p0.v0 .. p0.v8              16 columns
    FROM ( SELECT j0.<8 vars x 8 cols>              ~64 columns
           FROM (uuid subquery JOIN term t_v0) AS j0
           JOIN (uuid subquery JOIN term t_v2, t_v8) AS j1 ...

So every variable of every match is fully resolved before the outer DISTINCT /
ORDER BY / LIMIT sees a row. That is the ~74,000 lookups. It is structural to
how the projection is assembled, which is why no index or fence moved it.

Underneath is a pure-uuid layer (`q4.subject_uuid AS v1__uuid ... q17.object_uuid
AS v8__uuid`, quads and edges only) — the materialisable match set, and what the
38 ms Gather measures.

    WITH m AS MATERIALIZED ( <uuid-only layer> ),
    ordered AS (
        SELECT m.v0__uuid, t.term_text AS sk
        FROM m JOIN {space}_term t ON t.term_uuid = m.v8__uuid
        WHERE t.datatype_id IN (...)
        ORDER BY t.term_text LIMIT 25 OFFSET :offset )
    SELECT <full projection> FROM ordered ...

`MATERIALIZED` is load-bearing: without the barrier PostgreSQL inlines and
inverts the join, which is exactly how the phase-1 probe ended up driving from
the whole term table. Note this is the OPPOSITE verdict to `issues/070`, where a
CTE barrier destroyed early termination — worth understanding before reusing
either conclusion.

DATATYPE narrows it further: the sort key's `datatype_id` is known from the sort
criterion, so a dateTime sort filters to ids (9, 7) AND can order on `t.dt_val`,
a typed column WITH a btree — sidestepping `term_text`, the one sortable column
with none.

Hand-write, time, EXPLAIN. Only then touch the emitter.

## Why every phase-1 attempt timed out — ANSWERED, and it was my construction

Phase 1 was built by taking the two-phase INNER query and stripping its `LIMIT`.
That inner is an ordered scan with a PER-ROW EXISTS PROBE — cheap only because
`LIMIT` stops it after ~25 probes. Without the LIMIT it probes every row:

    Index Only Scan on rdf_quad_pkey ... Filter: EXISTS(SubPlan 1)
    cost 9,592,042

The GENERIC sorted path computes the same logical match set SET-BASED (parallel
hash join under a Gather) in 38 ms. Two plans for one set; all four attempts
reused the wrong one.

The probe's own plan is worth noting too: given `ORDER BY term_text LIMIT 25`
PostgreSQL DID try the ordered driver — Gather Merge over the whole term table
in text order — and lost because the join back to the match set has only a Join
Filter, no index. The ordered-driver idea fails on the return path, not on the
idea.

**The design that follows:** phase 1 = the generic set-based match set (~38 ms)
+ ONE term join for the sort key + sort + LIMIT 25; phase 2 = the existing
full-projection resolve, for 25 rows. That is the generic path with its
projection-over-every-match replaced, NOT the two-phase inner without a LIMIT.

Hand-write and time that query before touching the emitter. If it is not ~1-3 s
the design is wrong again and nothing should be built.

## COST ATTRIBUTED 2026-08-11 — it is projection volume

From the plan, not from inference:

    Gather (match set, criteria already evaluated)   38 ms   9,220 rows
    8 x Index Scan term_pkey, 9,220 loops each   ~19,000 ms

**Criteria evaluation is 38 ms; term resolution is ~19 s.** The sorted page is
expensive because it resolves the FULL PROJECTION for every match — ~74,000
random heap lookups — not because it evaluates criteria for every match, and not
because of anything to do with ordering.

`(term_uuid) INCLUDE (term_text)` was built and measured: **no improvement**
(18,458 ms). `term_table_columns` needs term_type, lang, datatype_id, num_val,
bool and dt as well, so the heap fetch stays and covering all of them would be
an index the size of the table.

This RE-OPENS the phase-1 design recorded above as disproved: it attacks exactly
the dominant term, and the objection against it — that materialising the match
set is costly — is measured at 38 ms. Why the hand-written probe timed out at
>200 s is unknown; the next action is an EXPLAIN of that query, not a fourth
implementation attempt.

## Earlier reading: DRIVER SELECTION, not indexes and not depth

    no sort                                              63 ms
    sort hasObjectCreationTime (dt_val HAS a btree)  12,462 ms
    sort hasName (no btree)                          16,961 ms

    datetime sort, offset 0                          13,491 ms
    datetime sort, offset 250                         5,605 ms
    datetime sort, offset 2475                        2,727 ms

A sort key WITH a btree is 12.5 s — the same order as one without. **The index
exists and the plan does not use it**, so the blocker is which driver the
emitter picks, not what is available to it. Adding `btree(term_text)` would buy
nothing on its own.

And sorted paging does NOT collapse with depth — it gets faster, the opposite of
`issues/078`. So sorted queries have a PAGE-1 problem, not a deep-page problem,
and a cursor cache does not address this issue (it still addresses `078`).

The ordered-driver direction below remains the right one; what it needs is for
the emitter to CHOOSE the sort key's index, which is the same driver-selection
work as the text and range anchors in `reorder_bgp`.

## CORRECTION to the closing finding: this is the RANGE problem, already solved

"Ordering by a value requires evaluating the criteria for every row" is WRONG,
and the counter-example is in this codebase already. Range comparators (`gte`,
`lt`, ...) have the identical shape — a criterion whose match set is large — and
they were solved by letting an INDEX-BACKED LEAF DRIVE the scan. `reorder_bgp`
says so at the precedence rule: a range leaf roots the chain because it is
"cheap to ENTER whatever it matches", served by a narrow index scan on
`num_val` / `dt_val`.

The same move applies to a sort: **drive the page from the sort key's index IN
SORT ORDER, probe the criteria per candidate, and stop at 25.** Then the cost is
O(candidates until 25 pass) — exactly the unsorted page's cost model, with the
sort key's index supplying the order instead of the uuid index. Nothing has to
be materialised and nothing has to be sorted.

The phase-1 design failed because it MATERIALISED AND SORTED. That was the wrong
mechanism, not evidence that the problem is inherent.

### Why the measurement said otherwise: I chose the one sort key that cannot work

    btree (num_val)     ordered scan possible
    btree (dt_val)      ordered scan possible
    hash  (term_text)   NO ordered scan
    gin   (term_text gin_trgm_ops)

`hasName` is TEXT, and `term_text` carries only a HASH index and a trigram GIN —
neither can produce sorted output. So the one case measured all day is precisely
the case the ordered-driver approach cannot serve without a new index. A sort on
a numeric or datetime property is a different story and is feasible with the
indexes already present.

### What to do, revised

1. **Measure a NUMERIC sort first** (e.g. `MQLRating`, a KGDoubleSlot). If the
   ordered-driver hypothesis holds anywhere it holds there, and `num_val`
   already has the btree. This is the cheap decisive test and it should have
   been the first one.
2. If it holds, the change is the driver-selection one this codebase has made
   twice already (text anchor, range anchor) — extend the same precedence to a
   sort key, rather than inventing a phase-1 shape.
3. For TEXT sorts, the question becomes whether to add
   `btree (term_text)`. That is a schema decision with real cost on a 10.4M-row
   table, and it should be made against a measurement of (1), not before it.

## What this leaves as the actual options

* **Accept it, deliberately.** 16-21 s is inside the 120 s request deadline. It
  degrades rather than fails, and it is a decision the product can make.
* **Make the criteria evaluation cheap in bulk**, not per candidate. The probe
  is what costs; a set-based criteria evaluation would change the multiplier for
  every match. This is a much larger piece of work than paging.
* **Restrict what is sortable.** A sort on a property the anchor already carries
  needs no criteria re-evaluation. `hasName` is not one today.

Do NOT reopen the phase-1 design without first re-running measurement 3 above.

## The paired change was implemented, and it is STILL not enough

Both halves together — builder group placement AND `_emit_two_phase` two-key
support with the split dedup/order page — did not complete the 100k sorted case
inside 600 s. Reverted; baseline stands at 50 ms / 16,411 ms.

The causal chain traced in this issue is right at every link, and repairing all
of it end to end still does not produce a fast sorted page. So the remaining
cost is not the plumbing. Two candidates, neither yet measured:

* The inner `DISTINCT ON` now runs over the whole match set WITH the term join
  attached and the criteria EXISTS in its WHERE. The 33 ms figure that motivated
  this design was a bare `uuid -> term_text` join over 9,220 rows — a different
  query, and the only one that was measured.
* The anchor is now a two-BGP join, so `emit_bgp_anchor` may be anchoring on the
  sort quad rather than the entity-type union, changing which scan drives.

**Measure the inner query standalone before wiring anything again.** If phase 1
is not tens of milliseconds on its own, the page shape is wrong and no plumbing
fixes it. Another end-to-end attempt costs ~10 minutes and reports only that
something is slow.

## Other options considered, and why they lose

Unlike `078`, there is no obviously correct fix — ordering by a value genuinely
requires knowing the value:

* **An index-backed sort key.** If the sort property has its own index and the
  criteria can be probed against it, the ordered scan could drive the page the
  way the entity uuid does today. That is a schema question as much as a
  planner one.
* **Sort on a column already carried by the anchor.** `hasName` is resolved
  through the term table; if the anchor exposed a sortable projection, the top-N
  could be taken before the join.
* **Accept it and bound it.** 18.6 s is inside the 120 s request deadline, so it
  degrades rather than fails. Deciding this is acceptable is a legitimate
  answer — but it should be a decision, and right now it is an accident.

Measure before choosing: the numbers above are one shape at one scale.

## Secondary: a frame-slot sort generates invalid SQL

    sort_type="entity_frame_slot", slot_type=..., slot_class_uri=...,
    frame_path=[parent, child]
    -> asyncpg.exceptions.UndefinedColumnError: column s0.v14 does not exist

NOT CONFIRMED as a product defect: the frontend only ever sends
`sort_type`/`property_uri`/`direction` (`KGQueryBuilder.tsx:211`) and filters on
`property_uri`, so it never constructs this shape, and the criteria above may
simply be malformed. Two things are worth separating before acting:

1. whether that criteria construction is valid — if it is, generation is broken
   for a documented `sort_type`;
2. whether invalid input should produce invalid SQL at all, rather than a
   rejected request. It currently reaches PostgreSQL and fails there.

## Related

- `issues/040` — paging is O(matches) not O(page). Fixed for the unsorted path.
- `issues/078` — paging past page 1. The other half of the paging surface that
  no benchmark covered.
- `issues/047` — the paging plan flipping to a blocking sort above 51 rows.
