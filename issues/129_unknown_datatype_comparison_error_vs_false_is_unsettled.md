# Unknown-Datatype Comparison: Type Error or False? The Two Authorities Disagree

## Status: OPEN — investigated 2026-08-23, implementation REVERTED

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
