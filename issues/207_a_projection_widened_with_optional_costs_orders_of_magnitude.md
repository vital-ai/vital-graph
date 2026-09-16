# A Projection Widened With OPTIONAL Costs Orders Of Magnitude

## Status: OPEN, recorded 2026-09-16 from measurements taken while building a
## multi-column slot projection. The RULE is settled and actionable; the
## mechanism is not yet confirmed against a plan.

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

**Never widen a projection with OPTIONAL.** If a result set needs values that
live under different predicates, issue one query per predicate and join the
results in the caller. The extra round trip is ~200 ms; the OPTIONAL is seconds
to never.

## Why this is not the same as "OPTIONAL is slow"

It is not, and saying so would be the wrong lesson. `query.sparql_shape[optional]`
measures a single OPTIONAL at **406 buffers** for a 25-row page — cheaper than
the sub-SELECT case beside it. An OPTIONAL that constrains is fine.

What is expensive is an OPTIONAL that WIDENS — one that exists only to add a
column that may or may not be bound, and so cannot restrict the driving set.
Each one multiplies the shape of the result rather than narrowing it.

## Not yet established

- The mechanism. `emit_join` notes that a left join is what a variable
  "possibly unbound" forces (`emit_join.py:20`), and `var_scope` moves an
  OPTIONAL's right-hand variables from `defined` to `maybe`. A `maybe` variable
  disqualifies several fast paths by construction — `fast_slot_sort`'s frame
  criteria require `defined` on both sides, and `issues/205`'s MINUS folding
  does too. Whether that is what costs 22x here, or whether it is the join
  order, has NOT been checked against a captured plan.
- Whether the six-column case is the same defect compounding or a different
  cliff. ">30 s" is a timeout, not a measurement, so its shape is unknown.
- Whether a `UNION` of required-pattern arms — one arm per datatype — is
  cheaper than either. It expresses the same thing without a `maybe` variable,
  and nothing here has measured it.

## Where to look first

Capture the plan for the one-column OPTIONAL form against the required-pattern
form on the same data. `tests/performance/test_sparql_shape_coverage.py` has the
harness: generate through `_generate_sql`, then `EXPLAIN (ANALYZE, BUFFERS)`.
Note the trap `issues/206` fell into — read the SQL the RUNTIME executes, not
the generator's output, where they differ.

A bench cell for the widened form belongs in that file once the shape is
understood. `issues/193` counted `OPTIONAL` at zero occurrences until recently,
and the one cell there now measures the cheap case only.
