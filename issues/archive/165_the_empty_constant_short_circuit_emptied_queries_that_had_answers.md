# The Empty-Constant Short Circuit Emptied Queries That Had Answers

## Status: FIXED, forward, after being committed in `429aebc`. Caught by the
## performance tier, not by unit or integration.

## What it did

The short circuit rewrites a query to return nothing when a constant it needs is
absent from the term table. Worth having — proving emptiness by scanning cost
40 s+ on one measured shape. But it decided "needs" by COUNTING UNRESOLVED
CONSTANTS:

    _unresolved = [col for col in aliases.constants.values()
                   if col not in (aliases.resolved_constants or {})]
    if _unresolved and _only_conjunctive(plan):
        ... append (owner, "1 = 0")

`aliases.constants` registers every constant OFFERED during collection, not the
ones the query depends on. A rewrite can register a term and then drop it; a
type list registers every alternative it was handed.

Measured on the `mql` KG shape against `sp_lead_synth_100k`: THREE unresolved
constants —

    haley-ai-kg#KGNewsEntity
    haley-ai-kg#KGProductEntity
    haley-ai-kg#KGWebEntity

entity types that space does not contain — against SEVENTY-TWO plan
constraints, none of which referenced any of them. The query matched thousands
of rows through the types that DO exist. It returned zero.

Silent, in the way that matters: `1 = 0` is not an error, and an empty result is
a legitimate answer to a query matching nothing.

## Why the existing guard did not catch it

There IS a guard, and it is not sufficient. `_only_conjunctive` whitelists node
KINDS (BGP, JOIN, PROJECT, DISTINCT, REDUCED, SLICE, ORDER) so that a UNION
branch resolving empty cannot delete the other branch's rows.

A type disjunction is not a UNION node. It is a CONSTRAINT inside ONE BGP node,
so a plan that is disjunctive in meaning is conjunctive in shape, and the
whitelist sees nothing wrong. The guard was written against the disjunction it
could see.

## The fix, and the second bug it avoided

The test is not "is some constant unresolved" but "does a constraint that MUST
hold require one". The first attempt at that was textual — exclude constraints
containing `IN (` or ` OR ` — and it would have introduced `issues/093` one
module over:

    col = <missing>                  can never hold   -> required
    col IS DISTINCT FROM <missing>   ALWAYS holds     -> NOT required

`collect` emits the second for every `GRAPH ?g`, choosing `IS DISTINCT FROM`
over `!=` precisely so a missing default-graph term reads as "no exclusion". A
textual guard sees no `IN (` and no ` OR ` there and calls it required — which
is exactly the wrong answer `issues/093` already found and fixed once, where any
`GRAPH ?g` query with an empty default graph returned nothing.

So the rule delegates to `prune_union._dead_constant_is_required`, the function
that fix produced, rather than offering a second opinion on the same question.

## Testable now, which it was not

The rule is extracted as `generator.required_missing_constants(plan, unresolved)`
and covered by `tests/unit/sparql_sql/test_unresolved_constant_is_not_required.py`
— no database, five cases: unreferenced, `=`, `IS DISTINCT FROM`, nested/tagged
constraints, and token-prefix safety (`c_1` must not match `__CONST_c_10__`).

## What this says about how it was verified

The commit went in on unit and integration being clean while the performance
tier was still running. Unit and integration could not have caught this: the
shape needs a real space where some of a type list is present and some absent.
The perf tier caught it immediately, through a guard rail that asserts a
NON-EMPTY result before reading anything into a plan — `harness.assert_plan`'s
`min_actual_rows`. That guard rail is the reason this was found at all, and is
worth keeping in mind when adding bounds-style assertions elsewhere: an upper
bound passes vacuously on an empty result.
