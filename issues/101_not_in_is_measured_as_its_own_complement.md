# `NOT IN` Is Measured As Its Own Complement, and Inline Constants Are Not Measured At All

## Status: `NOT IN` FIXED 2026-08-17. The inline-constant gap is OPEN.

Found by surveying every criterion form through the real generator against a
loaded space, rather than by reading the recognisers — the two answer different
questions, and this is a case where a handler exists but the plumbing does not
reach it.

## The survey

Depth-2 traversal on `sp_graph_skew_2k`, pinned head, one criterion at a time,
reading `GenerateResult.traversal_decision`:

    numeric >= , <          measured     10%, 25%
    double >= , dateTime >= measured     0%, 86%
    string =                measured     1%
    string IN               measured     4%
    CONTAINS, STRSTARTS     measured     0%
    boolean =               measured     20%
    regex                   NOT measured
    numeric = , !=          NOT measured
    !=, !(=), !(IN)         NOT measured
    negated range !(<)      NOT measured
    ?f hasCategory "theta"  NOT measured   <- constant in the TRIPLE
    ?f hasTag <uri>         NOT measured   <- constant in the TRIPLE

Reproduce with `test_scripts/debug/survey_measured_criteria.py`.

So text criteria ARE measured: `text_stats` covers the LIKE family, `in_stats`
covers equality and `IN`. `regex` is the one text form that is not, and that
exclusion is deliberate — `needed_texts` documents it: pg_trgm serves only some
regexes, and a count that silently falls back to a sequential scan costs more
than the plan it informs. Leave it.

## Defect 1: `NOT IN` reports the complement of what it admits — FIXED

`theta` is 1% of `hasCategory` on this fixture:

    FILTER(?ct IN     ("theta"))    reported "admits 1%"     true:  1%
    FILTER(?ct NOT IN ("theta"))    reported "admits 1%"     true: 99%
    FILTER(?ct NOT IN ("alpha","beta"))  reported "admits 56%"  true: 44%

`_IN_OPS` has always mapped both spellings — `{"in": "IN", "notin": "NOT IN"}` —
and `needed_ins` unpacked the operator into `_sql_op` and dropped it, then summed
the values' rows. One discarded variable.

Every OTHER negation declines safely: `!=`, `!(?v = x)` and `!(?v IN (x))` all
report unmeasured, because `_equality_operands` matches `eq` only and nothing
descends into a `!`. So this one surface form was the whole of it.

### What it did and did not cost

It did NOT flip the hop-wise decision. Selectivity is REPORTED, not thresholded
(`traversal_decision.py`, "So selectivity is NOT a gate here") — a measured
criterion qualifies whatever its value, so both polarities enabled hop-wise
either way. Saying otherwise would overstate it, and the first version of this
issue did.

What it corrupted is the number: the reported selectivity, the `criterion_rows`
carried on the `Decision`, and — the one with teeth — which criterion wins the
most-selective contest when a query carries several. An inverted 1% beats a
genuinely narrow range criterion and gets reported in its place. It is also a
landmine for the moment anything DOES threshold on it, which the file
anticipates: "ranking two chains may want it later".

### The fix

`needed_ins` yields `(p_uuid, values, negated)`; the generator inverts against
`pred_stats[p_uuid]` where the total is known, and DROPS the criterion where it
is not. Dropping rather than guessing is the safe direction twice over: rdf_stats
is a capped frequent-value list, so its sum is an undercount, and an undercount
of the positive side makes the complement an OVERCOUNT — which reads as less
selective and declines.

The cached count stays the POSITIVE sum, so both polarities share one cache
entry and the inversion happens only where the total is in hand.

Verified after the fix, on the same four queries: 1%, 99%, 44%, 56% — every one
matching the true fraction, with the row counts unchanged.

## Defect 2: a constant in the triple pattern is never a criterion — OPEN

`?f <hasCategory> "theta"` is the most natural way to write a selective
criterion, and `rdf_stats` already holds the answer — 193 rows, sitting there.
`needed_pairs` gathers it into the pair stats, which is what the DIRECTION gate
now prices chain ends with. But the CRITERION gate reads `range_stats`,
`text_stats` and `in_stats` only, so it never looks, and the query reports
"pinned but no measured criterion" and declines hop-wise.

`needed_ins`'s own comment says inline constants are "already counted by
`needed_pairs`". That is true of the pair statistics and false of the criterion,
and the same claim was in `test_criterion_coverage.py`'s docstring. Both now say
which.

### Why this is not just plumbing

The pair stats also hold the chain's STRUCTURAL leaves — `hasKGSlotType =
hasSourceEntity` and friends. Feeding the pairs in unfiltered would hand the gate
a "50% criterion" for every traversal that carries no criterion at all, which
re-enables hop-wise on unfiltered walks. That is the shape the criterion
requirement exists to refuse: `wordnet_frames` depth 3, no criterion, 865 ms flat
against 2,044 ms hop-wise.

The chain knows which leaves are its own structure, so the exclusion is
available. It has to be written deliberately, and it wants its own measurement
afterwards — the fix is only worth having if a constant-object criterion behaves
like the range criteria it would join.

## Not worth fixing

`numeric =`, `numeric !=` and negated ranges all decline conservatively. A typed
numeric is several terms and one value (`5`, `5.0`, `05`), which is why the
equality path excludes it and the range path owns numerics. The payoff is small
and the exclusion is already reasoned.

## Related

- `issues/090` — the traversal gate these criteria feed, and the fixture the
  survey runs against
- `issues/070` — the trigram index that makes the text family affordable to
  measure per query
