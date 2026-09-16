# A Projection Widened With OPTIONAL Costs Orders Of Magnitude

## Status: FIXED 2026-09-16 in `emit_join.py`. The cost was a provably dead
## disjunct in the generated ON clause, not anything about OPTIONAL itself, and
## folding it removes the cliff: 1,147,071 buffers -> 1,886 at two arms,
## 4,963,374 -> 7,998 at eight, same rows. No caller has to change. The RULE
## below is kept because it still describes good query hygiene, but it is no
## longer load-bearing for performance.

## The shape

Slot values do not share a predicate. Each datatype has its own:

    KGTextSlot     haley:hasTextSlotValue
    KGIntegerSlot  haley:hasIntegerSlotValue
    KGDoubleSlot   haley:hasDoubleSlotValue
    ...

(`kg_query_builder.py:107`, and the same split drives `_LANE` in
`fast_slot_sort.py:63` — text/num/dt.)

So a query that projects a TEXT slot and an INTEGER slot in one result set
cannot state both as required patterns: an entity has one or the other on any
given slot, and a required pattern for both matches nothing. The only form that
expresses "whichever of these exists" is `OPTIONAL` on the value predicate.

That form is the problem.

## Measured

    required-pattern form (one datatype)            194 ms
    OPTIONAL on the value predicate, ONE column     4.2 s      ~22x
    OPTIONAL on the value predicate, SIX columns   >30 s       timed out

The cost is not linear in the number of columns — one OPTIONAL is already 22x,
and six do not finish. Whatever the mechanism is, it compounds per widened
variable rather than adding.

Separately, and for the same reason the rule exists: the `cycle` column is
necessarily its OWN query, and asking it separately costs **+212 ms**. That is
the price of the rule and it is small — two queries at 194 ms and 212 ms beat
one query at 4.2 s by an order of magnitude, and beat the six-column form
outright because that one does not return.

## The rule

**Never widen a projection with OPTIONAL.** Two is already 982x one.

**Prefer a UNION of required-pattern arms** — one arm per datatype, each
binding its own variable. It costs the same at eight arms as at two (874
buffers), it is ONE round trip rather than N, and on slot data it returns the
same rows. This is better than the caller-side join the rule originally
prescribed, which costs +212 ms per extra predicate.

Since the fix above, the OPTIONAL form is no longer a disaster — 7,998 buffers
at eight arms against UNION's 874. UNION is still ~9x cheaper and is what to
reach for, but the choice is now ordinary tuning rather than a cliff to avoid.

Use the caller-side join only when the subjects genuinely carry more than one
of the predicates — there UNION's tall rows are not the wide row wanted, and
folding them in the caller is the honest fix.

## Why this is not the same as "OPTIONAL is slow"

It is not, and saying so would be the wrong lesson. `query.sparql_shape[optional]`
measures a single OPTIONAL at **406 buffers** for a 25-row page — cheaper than
the sub-SELECT case beside it. An OPTIONAL that constrains is fine.

What is expensive is an OPTIONAL that WIDENS — one that exists only to add a
column that may or may not be bound, and so cannot restrict the driving set.
Each one multiplies the shape of the result rather than narrowing it.

## The fix

The generator emitted a different join condition for the second OPTIONAL than
for the first:

    ON j0.v0__uuid = j1.v2__uuid                             -- 1st OPTIONAL
    ON (j2.v0__uuid IS NULL OR j2.v0__uuid = j3.v4__uuid)    -- 2nd OPTIONAL

The second is a DISJUNCTION, not an equijoin. PostgreSQL cannot hash, merge or
memoize it, so it materialised the entire right-hand predicate and nested-looped
it. Replacing that one condition by hand, with nothing else changed:

    as emitted     405,014 buffers   257.8 ms
    folded           1,814 buffers     6.0 ms   -- same 81,540 rows

The disjunct is DEAD. `?s` is bound by the required pattern
`?s haley:hasKGSlotType ?st`, so `j2.v0__uuid` is never NULL.

`emit_join` already drops these guards when it can prove boundness, via
`_always_bound` -> `_all_required`. That rule asks about a whole SUBTREE, and
the second OPTIONAL's left side CONTAINS the first OPTIONAL, so it was rejected
wholesale — even though the join variable comes from the required BGP
underneath. The fix adds per-variable evidence: `compute_scope(child).defined`,
which a LEFT JOIN already computes correctly (left arm's variables stay
`defined`, only the right arm's move to `maybe`). Same evidence `emit_minus`
folds on for `issues/205`.

One trap, caught by an existing guard test: `compute_scope` does NOT model
`UNDEF`, so a VALUES row binding a variable to UNDEF still reports it
`defined`. Scope evidence is therefore not consulted for any subtree containing
a VALUES block — `ColumnInfo.uuid_materialized` remains the correct
per-variable evidence there.

### After the fix

    arms   before        after
      1     1,168        1,168
      2 1,147,071        1,886
      4 2,451,204        3,594
      8 4,963,374        7,998

Linear in the number of arms, no cliff. Eight arms went 727 ms -> 33.5 ms.

### Callers that were hitting this

Stacked widening OPTIONALs are not exotic — these were all on the cliff side:

    kgframes_endpoint.py:1227   hasName + hasKGraphDescription
    kgframes_endpoint.py:1899   the same pair on the frame listing
    kgquery_endpoint.py:1726    hasKGFrameType + one more

They are fixed by the generator change; none of them had to be rewritten.

## What the plan shows (2026-09-16, `sp_lead_types`, 81,540 slots)

All three open questions are answered. Buffers for a 25-row page, generated
through `_generate_sql` and run as the runtime runs it:

    arms   OPTIONAL-widened        UNION of required arms
      1             1,168                            616
      2         1,147,071                            874
      3         1,778,706                            874
      4         2,451,204                            874
      6         3,805,849                            874
      8         4,963,374                            874

**The cliff is at the SECOND OPTIONAL, not the first.** One is nearly free.
Adding the second costs 982x; each arm after that adds roughly 600k buffers.
So it is one cliff plus a linear tail, not per-variable compounding.

The plan says why. With ONE optional the second pattern is a `Memoize` over an
index lookup keyed on the subject — 100 buffers. With TWO, that memoization is
gone and the second optional becomes:

    Nested Loop            est=9066470  act=25     buf=176,469
      Nested Loop          est=  81803  act=25     buf=    230
      Materialize          est=  22146  act=21639  buf=176,239
        Gather -> Nested Loop ...                  buf=176,239

The join predicate is no longer driving the inner side. Postgres materialises
the ENTIRE second value predicate (all 22,000 rows) and nested-loops it, and
the row estimate blows out to 9,066,470 against an actual 25. The `LIMIT` can
no longer be pushed down, so the page costs what the whole join costs.

**UNION is flat.** 874 buffers at two arms and still 874 at eight; the cost is
in the arms' own index scans, and the `LIMIT` still pushes down. At eight arms
that is 17.5 ms against 727 ms — a 5,679x buffer difference.

The `maybe`-variable hypothesis in the original writeup is NOT the cause. This
is ordinary planner behaviour on stacked LEFT JOINs, not a fast path declining.

## The one-column figure did not reproduce

The 4.2 s / 22x reading for a SINGLE OPTIONAL column is not what this data
does — one OPTIONAL measures 1,168 buffers here, within 2x of the required
form. That original measurement came from a different query against different
data and its shape is unexplained. It does not change the rule, but it should
not be cited as the cost of one OPTIONAL.

## UNION is not a drop-in in general — but it is here

The forms are not equivalent. `OPTIONAL` returns ONE WIDE row per subject with
several columns possibly bound; `UNION` returns a TALL row per matching arm.
They coincide only when a subject carries at most one of the predicates.

For slots that holds exactly: a `KGTextSlot` has `hasTextSlotValue` and not
`hasIntegerSlotValue`. Measured — subjects carrying both text and integer
values: **0**. So each subject appears on exactly one arm, and the UNION result
has the same wide shape, with one column bound per row.

The one real difference is coverage of subjects with NO value. Anchoring on
`hasKGSlotType` and widening with OPTIONAL returns them with every column
NULL; a UNION of value arms omits them:

    all 8 arms, UNION      79,290 rows
    all 8 OPTIONAL         81,540 rows   (+2,250 slots holding no value)

If the caller needs the valueless slots, that is what the extra 2,250 costs,
and it needs its own arm or a second query. If it does not, UNION is strictly
better.

## Where to look first

Capture the plan for the one-column OPTIONAL form against the required-pattern
form on the same data. `tests/performance/test_sparql_shape_coverage.py` has the
harness: generate through `_generate_sql`, then `EXPLAIN (ANALYZE, BUFFERS)`.
Note the trap `issues/206` fell into — read the SQL the RUNTIME executes, not
the generator's output, where they differ.

A bench cell for the widened form belongs in that file once the shape is
understood. `issues/193` counted `OPTIONAL` at zero occurrences until recently,
and the one cell there now measures the cheap case only.
