# Unknown-Datatype Comparison: Type Error or False? The Two Authorities Disagree

## Status: OPEN — semantics SETTLED and partly implemented 2026-08-24.
## Two of seven cases fixed; five remain with a diagnosed cause.

`issues/128` names `open-world` as the largest remaining sparql10 cluster.
Attempted it; got two of seven cases passing and reverted, because the change
broke eight other things and the reason is a genuine semantic conflict rather
than a coding mistake.

## What the DAWG cases demand

`open-eq-06` is `FILTER ( ?v != "a"^^t:type1 )` over `data-1.ttl`:

    :x1 :p "a"^^t:type1 .   :y1 :p "a"^^t:type2 .   :z1 :p "1"^^xsd:integer .
    :x2 :p "b"^^t:type1 .   :y2 :p "b"^^t:type2 .   :z2 :p "01"^^xsd:integer .
                                                    :z3/:z4 "2"/"02"^^integer

**Expected: 0 rows.** Eight rows in, none out. So every one is either FALSE or
an ERROR — including `"b"^^t:type1 != "a"^^t:type1`, two DIFFERENT terms of the
SAME unrecognised datatype. The only reading that gives zero is: when a
datatype's value space is unknown, we cannot know whether two lexical forms
denote the same value, so the comparison is a TYPE ERROR and the FILTER drops
the row.

`open-eq-04` (`?v != 1`, expected 2) agrees: only the integers are comparable.

## What our own tests demand — and they came from `issues/121`

`tests/integration/test_datatype_equality.py`, written 2026-08-23:

    test_two_unknown_datatypes_that_differ_are_not_equal
        "x"^^<custom> = "x"^^<other>     asserts FALSE

That follows `issues/121`, which states the spec answer for
`"x"^^<urn:myType> = "x"` is FALSE, reasoning from `RDFterm-equal`
(§17.4.1.7): two literals with different datatypes ARE different RDF terms,
and the function "returns FALSE if term1 and term2 are known to be different".

**Both readings are defensible and they contradict each other.** RDFterm-equal
says different-datatype literals are known-different, hence FALSE. The
open-world cases say an unknown value space makes the comparison
undeterminable, hence error.

## Measured cost of implementing the DAWG reading

Two cases fixed, `open-eq-06` and `open-eq-04`. Eight broken:

* five in `test_datatype_equality.py`, all asserting FALSE where the rule
  returns unbound;
* `bind/bind11`, `aggregates/SAMPLE`, `aggregates/SAMPLE DISTINCT`, which had
  been passing.

Reverted on that basis. A change that breaks eight to fix two is not a fix,
and the three conformance regressions say the blast radius reaches well past
the datatype family.

## What it would take to settle this

1. **Read §17.3's operator table, not just §17.4.1.7.** The `=` operator is
   only defined as RDFterm-equal when the operands fall OUTSIDE the supported
   datatypes; the table is what decides whether an unknown datatype makes the
   operator inapplicable (error) or falls through to term comparison (false).
2. **Check what the three regressions actually needed.** `SAMPLE` breaking
   suggests the rule reached aggregate paths that only wanted term identity —
   possibly the fix belongs at the comparison operators alone, not in a shared
   helper.
3. **Decide, then make ONE of the two test sets authoritative** and correct the
   other, rather than leaving both asserting opposite things. Right now
   `issues/121`'s premise and the DAWG corpus cannot both be right.

## Also learned, and worth keeping

`open-eq-07` — `FILTER(?v1 = ?v2)`, two variables — did NOT move under any of
the three edits, staying at 28 rows where 12 are expected. It never reached
`_cmp_sql`. The likely explanation is in the code's own comment: the builder
turns variable equality into a triple pattern (term identity) rather than a
FILTER. That is a THIRD comparison path, after the expression emitter and the
push-down, and nothing in the planning docs mentions it.


## Settled: the standard says TYPE ERROR

SPARQL 1.1 §17.3 routes `=` to a value comparison only for the datatypes it
supports. Everything else falls through to RDFterm-equal (§17.4.1.7), which
**"produces a type error if the arguments are both literal but are not the
same RDF term"**. FALSE is reserved for the case where they are NOT both
literal — a URI against a literal is well defined and unequal.

So the DAWG corpus was right and `issues/121`'s "spec: FALSE" premise was
wrong. Five tests written from that premise now assert the standard.

**What `issues/121` fixed is unaffected.** In a FILTER a type error and FALSE
both drop the row. The two differ only where the value is observed — a BIND —
and under negation, where `!error` stays an error but `!FALSE` is TRUE.

## Done

* `4fae676` — the expression path. Fixes `open-eq-06`.
* this commit — the push-down. Fixes `open-eq-04`.

Two constraints, both learned by violating them: resolve the datatype through
`_dt_sql` rather than `info.dt_col` (the latter engages where `_datatype_guard`
declines and references columns not in scope — it took out
`aggregates/SAMPLE`), and skip a pair already in one value space (the numeric
lane already yields NULL for a term outside it).

## Remaining: 5 cases, one diagnosed cause

`open-eq-07` is `FILTER(?v1 = ?v2)`: 28 rows where 12 is correct. **16 is
exactly the number of pairs among the four unknown-typed terms**, so the
same-term branch of `_term_error_cmp` is matching all of them rather than only
the four identical pairs. `open-eq-08/10/11/12` are the same shape.

**Correction to this issue's own earlier text:** it said `FILTER(?v1 = ?v2)`
never reaches `_cmp_sql`, and blamed the builder rewriting variable equality
into a triple pattern. That was inferred from a row count that did not move.
Dumping the generated SQL shows the type-error CASE is present. The path is
fine; the branch is wrong.


## The ill-typed fix was ATTEMPTED and REVERTED — comparability is PAIRWISE

Diagnosis (2026-08-24): DAWG excludes `x1/x4` against `x5`, the ill-typed
`"xyz"^^xsd:integer`. A recognised datatype carrying an unparseable lexical
form has no value, and `num_col` is NULL exactly then — so requiring
`num_col IS NOT NULL` looked like the fix.

**It made things worse.** `open-eq-08` went 42 -> 34, `open-eq-10`/`-11` went
53 -> 44. Eight pairs lost, not four gained.

The reason is structural, and it invalidates the model rather than the edit:

    x5 vs x1/x4  (ill-typed integer vs string)     DAWG EXCLUDES  -> error
    x5 vs x2/x3  (ill-typed integer vs langString) DAWG INCLUDES  -> != is TRUE
    x5 vs x7/x8  (ill-typed integer vs bnode/URI)  DAWG INCLUDES  -> != is TRUE

The SAME operand is indeterminate against one datatype and determinate against
another. **Comparability is not a property of one operand, which is what
`_comparable_sql` assumes.** Marking `x5` non-comparable removes it from all
three groups, and two of them were right.

## What the model needs to become

Pairwise determinacy, roughly:

* either side NOT a literal            -> definite (RDFterm-equal gives FALSE)
* exactly one side language-tagged     -> definite (never equal)
* both language-tagged                 -> definite (term identity over text+tag)
* both plain/typed literals            -> determinate ONLY if both datatypes are
                                          recognised AND both values parsed

That is a restructure of `_term_error_cmp`, not a patch to `_comparable_sql`.
It should be done deliberately, with the expected SRX diffed after each step —
this issue's history is five wrong theories, every one of them from reasoning
instead of diffing the expected results.

## Remaining, split by kind

NOT ours (pyoxigraph also differs from the corpus; needs hand-checking and a
recorded reason, the treatment `str-1`/`str-2` got):

    date-2      FILTER(?v != "2006-08-23"^^xsd:date)   result-set mismatch
    date-3      FILTER(?v > "2006-08-22"^^xsd:date)    expected 3, got 4
    open-eq-01  graph match, no lexical form in data   expected 2, got 0

Ours:

    open-eq-08  42 rows, correct COUNT, wrong SET      pairwise determinacy
    open-eq-10  52 vs 53, one extra row                probably the same
    open-eq-11  52 vs 53, one extra row                same shape as -10
    open-eq-12  10 vs 64, filter not constraining      DIFFERENT cause: an
                OPTIONAL body's FILTER is not restricting the optional match.
                A join/scoping question, not an equality one.
