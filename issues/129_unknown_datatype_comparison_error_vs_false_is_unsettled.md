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
    open-eq-12  10 vs 64                               DIFFERENT cause, below.


## `open-eq-12` — measured 2026-08-24, and my first description of it was wrong

    { ?x :p ?v1 . ?y :p ?v2 .
      OPTIONAL { ?y :p ?v3 . FILTER( ?v1 != ?v3 || ?v1 = ?v3 ) }
      FILTER (!bound(?v3)) }

I said the outer `!bound(?v3)` was not emitted, from grepping the SQL for
`IS NULL`. **It IS emitted** — as `NOT ((v5 IS NOT NULL))`, which that grep
cannot match. The filter is fine.

What the SQL actually shows: we return all 64 rows, so `?v3` is NEVER bound —
the OPTIONAL body produces no match at all. And the body's own FILTER emits
none of our type-error `CASE`s, so the equality rule is not reaching it.

The intended behaviour is subtle and worth writing down, because it is what
makes this case a test of the type-error rule rather than of OPTIONAL:
`?v1 != ?v3 || ?v1 = ?v3` is TRUE whenever the comparison is DETERMINATE, and
an ERROR when it is not. So the OPTIONAL matches exactly the determinate pairs,
`?v3` binds for those, and `!bound(?v3)` keeps only the INDETERMINATE ones —
the ten rows expected. It is the pairwise-determinacy question again, seen
through OPTIONAL.

So `-12` is probably NOT a separate cause after all; it is the same
determinacy model, and it will not be assessable until that lands. Whether the
OPTIONAL body binding nothing is a second, independent defect is UNKNOWN — it
has not been isolated from the equality behaviour.

## Triage DONE 2026-08-24 — and it reverses the earlier classification

I had grouped these three as "not our bug" from the `ACCEPTED` label. **That
label only means pyoxigraph ALSO differs from the `.srx`. It does not mean we
are right.** Hand-checked against data-1/data-3 and the expected SRX:

| case | corpus | us | verdict |
|---|---|---|---|
| `open-eq-01` | 0 | **0** | we are RIGHT; the oracle returns 2 |
| `date-2` | dt1,d4,d5 | dt1,d4,d5,**d2,d3** | OUR BUG |
| `date-3` | d1,d2,d3 | d1,d2,d3,**dt1** | OUR BUG |

### `open-eq-01` — oracle bug, we match the corpus

    SELECT * { ?x :p "001"^^xsd:integer }

A triple pattern, not a FILTER, so it matches by RDF TERM. `"001"^^xsd:integer`
is a distinct term from `"1"` and `"01"`; no term in the data has that lexical
form, so ZERO rows is right, and the manifest says so itself — "graph match -
no lexical form in data (assumes no value matching)". pyoxigraph returns 2,
value-matching in a graph pattern, which the manifest explicitly excludes.

### `date-2` — ours: an untimezoned xsd:date is INDETERMINATE against a
### timezoned one within 14 hours

    FILTER ( ?v != "2006-08-23"^^xsd:date )

We return `d2` (`2006-08-23Z`) and `d3` (`2006-08-23+00:00`), which the corpus
excludes. Those are the SAME DAY as the needle, differing only in carrying a
timezone. XSD gives dates a PARTIAL order: a timezoned and an untimezoned value
are comparable only when the interval between them exceeds the maximum offset
of 14 hours. Same day, so indeterminate — a type error, and the FILTER drops it.

That the corpus KEEPS `d5` (`2001-01-01Z`) against the same untimezoned needle
is the other half of the rule and the proof it is 14 hours and not "any
timezone mismatch": five years apart is determinate whatever the offset.

`datatypes_and_language_tags.md` §4.6 fixed the timezone question for
`xsd:dateTime` EQUALITY by requiring both sides to agree about having a
timezone. That is a cruder rule than XSD's and it was not applied to
`xsd:date` at all.

### `date-3` — ours: ordering an xsd:dateTime against an xsd:date is a type error

    FILTER ( ?v > "2006-08-22"^^xsd:date )

We return `dt1`, `"2006-08-23T09:00:00+01:00"^^xsd:dateTime`. `xsd:dateTime`
and `xsd:date` are different value spaces, so the ordering is a type error and
the row is dropped. We compare them anyway.

Note this is ORDERING, not equality. The type-error work so far deliberately
touched `=` and `!=` only, on the grounds that ordering has its own rule. This
is that rule, and it is missing.

### Disposition

`open-eq-01` can go in `KNOWN_FAILURES` and `XFAIL_TESTS_V2` with the reason
"oracle disagrees with the corpus; we match the corpus" — the same disposition
`str-1`/`str-2` got. `date-2` and `date-3` must NOT: they are real defects and
should stay visible.
