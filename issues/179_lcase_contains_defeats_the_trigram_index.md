# LCASE + CONTAINS Defeats The Trigram Index That Exists For It

## Status: OPEN, and now known to be **the fix for `issues/182`** — the root
## cost of this whole family. On the simplified traversal it is worth
## **324x (1,153,015 -> 3,561 buffers)** and reaches the pinned-set floor,
## because it gives the planner a cheap entry point from the selective end and
## the 285,348-frame enumeration disappears. It still REGRESSES the reference
## CONSTRUCT, and finding why is the one open question. Implemented and reverted
## three times; not shipped.

**Raised:** 2026-09-09, profiling the reference happy-frame CONSTRUCT while
working `issues/178`. Split out from it because it is a different mechanism with
a different fix and much wider reach.

**Related:** `issues/178` (where it surfaced), `issues/098` (the other defect in
how search text reaches SQL), `vitalgraph/db/sparql_sql/emit_expressions.py`

## The defect

The push-down that would make this fast **already exists** — `_try_text_filter`
in `filter_pushdown.py` turns a text FILTER into
`uuid IN (SELECT term_uuid FROM term WHERE term_text ILIKE '%needle%')`, which
the trigram index serves. That is the "do the text first to shrink the space"
optimisation, and `issues/070` is its history.

It declines this query. Confirmed against the compiled AST rather than inferred:

    FILTER(CONTAINS(LCASE(STR(?description)), "happy"))

    arg0                     ExprFunction lcase
      after _unwrap_fold ->  ExprFunction str      fold: lcase
    arg1                     ExprValue             fold: None
    _text_search_operands -> None

Two independent gates in `_text_search_operands` reject it, either alone
sufficient:

```python
if f0 != f1:                      return None   # LCASE(?d) vs a BARE "happy"
if not isinstance(a0, ExprVar):   return None   # a0 is STR(?d), not a var
```

So the filter is not pushed, and the same predicate is evaluated above the join
as `lower(term_text) ~~ '%happy%'` — per candidate row, `loops=109,745` per
UNION branch. The index is never consulted.

**The index is not the problem and neither is `lower()`.** Both exist because
the push declined; fix the decline and the emitted form changes with it.

## What the two gates are actually protecting

Neither is arbitrary, and a fix has to keep what each is for.

**`f0 != f1`** is guarding a real wrong-answer:

    # LCASE(?v) against an unfolded needle is case-SENSITIVE against a
    # lowercased haystack, which ILIKE would over-match; that asymmetry is a
    # wrong answer, not a slow one.

Correct, and too strict by one case. `CONTAINS(LCASE(?v), "Happy")` is *always
false* in SPARQL — nothing upper-case survives `LCASE` — while
`ILIKE '%Happy%'` matches, so the guard is necessary. But when the needle is
already lower-case, `LCASE(?v) CONTAINS "happy"` and `?v ILIKE '%happy%'` are
the same predicate. The condition to test is not "both sides folded" but "the
needle is invariant under the fold".

**`isinstance(a0, ExprVar)`** excludes `STR(?v)`, and unwrapping it is NOT
free — it interacts with the literal guard applied further down:

```python
# §17.4.3 string functions take a literal; a URI or blank node is a type
# error, i.e. no row. ... so `regex(?val, "example\.com")` matched
# <http://example.com/uri> as well as the literal and returned a row too many.
if name in _TEXT_SEARCH_OPS:
    term_cond = f"term_type = 'L' AND ({term_cond})"
```

`STR()` is exactly what removes that type error. `CONTAINS(?v, "x")` on a URI is
an error and matches nothing; `CONTAINS(STR(?v), "x")` returns the URI's text
and CAN match. So a `STR`-wrapped push must NOT carry `term_type = 'L'` — adding
it would drop every URI match and return too FEW rows, the mirror image of the
bug that comment records.

## The fix, in three parts

1. Unwrap `STR()` around the variable, recording that it was present.
2. When it was present, omit the `term_type = 'L'` restriction — `STR` has
   already made the type error go away.
3. Accept an unfolded needle when it is invariant under the fold (all
   lower-case for `LCASE`, all upper-case for `UCASE`), instead of requiring
   both sides folded.

All three are general. None mentions this query, this space, or this needle.

## IMPLEMENTED, MEASURED, REVERTED — 2026-09-09

All three parts were written and behave exactly as intended. Gate behaviour
across shapes, against the compiled AST:

    LCASE(STR(?d)) + "happy"     PUSH   ci=True  stringified=True
    LCASE(STR(?d)) + "Happy"     declined            <- always-false in SPARQL
    LCASE(?d)      + "happy"     PUSH   ci=True  stringified=False
    ?d             + "happy"     PUSH                <- unchanged
    STR(?d)        + "happy"     PUSH   ci=False stringified=True
    UCASE(?d)      + "HAPPY"     PUSH
    UCASE(?d)      + "happy"     declined            <- always-false in SPARQL

`lower(term_text)` disappeared from the generated SQL, `ILIKE` replaced it, and
the trigram index was used. The full `tests/unit/sparql_sql/` suite stayed green.

**And the query got 17x slower.**

    before   1,738,342 buffers    1,464 ms   Rows Removed by Join Filter:     16,162
    after   36,408,167 buffers   24,586 ms   Rows Removed by Join Filter: 34,812,031

### Why — and it is not the index

Pushing the filter turns it into a quad-level constraint, which destroys the
plan shape that made `LIMIT 10` cheap:

    before   Limit -> Gather Merge (over a Sort on ?entity) -> ...
             incremental; the outer side produced ONE row and stopped

    after    Result -> Sort -> Nested Loop  rows=425
             the ENTIRE result set is computed, then sorted, then 10 are taken
             inner side: all 285,348 frames

The sorted incremental path is gone, so `LIMIT` no longer stops anything, and
every row must cross the null-tolerant join — 34.8 million of them.

### RETRACTED: this is not blocked on issues/180

The first revision concluded that the null-tolerant join of `issues/180` was the
blocker and had to be fixed first. That was wrong, and `issues/180` records the
measurement that refutes it: deleting the UNION removes the disjunction and
makes the query **6x slower**, so the disjunction is not what stops the push
paying off.

This also retires the guess recorded in the first revision of this issue, that
driving from the trigram index "could be much better or could expose a bad
estimate". It is neither: the estimate is fine and the join order is fine. What
changed is that an ORDER BY + LIMIT stopped being satisfiable incrementally.

The implementation is reverted rather than kept behind a flag, because a
17x regression is not something to leave one config away from a user, and the
three-part change is small enough to rewrite once 180 is done.

## What is NOT established

- **The end-to-end win.** Only the predicate was measured, standalone. Inside
  the real query the current plan reaches the term table by primary key and
  filters; with an index-eligible predicate the planner would likely DRIVE from
  the trigram index and join outward — a different join order, not just a
  cheaper leaf. That could be much better or could expose a bad estimate. It has
  to be measured before the 402x is quoted as a query-level number.
- **Whether other spaces have the index.** It is present on `wordnet_frames`;
  whether `create_space_tables_sql` emits it for every space, and whether older
  spaces have it, was not checked.
- **Selectivity estimates.** The bitmap scan estimated 185 rows and got 77. Fine
  here; unknown at other cardinalities.


## The full matrix — measured 2026-09-09, and the reason this keeps flipping

Every earlier measurement in this issue and in `issues/180` was taken on ONE
query shape: `ORDER BY ?entity LIMIT 10`. That shape turns out to be a special
case, and a cheap one. Decomposing it:

                           baseline (no push)      with the push
    ORDER BY + LIMIT 10      770 ms /  1.74M     19,427 ms / 28.4M    25x WORSE
    ORDER BY, no LIMIT     8,672 ms / 15.7M      18,364 ms / 28.4M     2x worse
    LIMIT 10, no ORDER     3,918 ms / 15.7M         365 ms / 0.51M    10.7x BETTER
    neither                8,208 ms / 15.7M      17,137 ms / 28.4M     2x worse

Two things follow, and they matter more than the push itself.

**The real cost of this query is ~8 s and 15.7M buffers**, not the 1.7M that
this issue and `issues/178` have been quoting throughout. 425 rows at ~37,000
buffers each. `ORDER BY` + `LIMIT` together produce a plan 10x cheaper than the
query's own full cost, and every conclusion drawn before this matrix was drawn
from that outlier.

**The push produces the best result ever measured for this query** — 365 ms and
511,445 buffers, 3.4x better in time and 3.4x fewer buffers than the previous
best — but only when `ORDER BY` is absent. With a sort in the plan the pushed
form costs 28.4M buffers, nearly double the unpushed full-query cost.

So the open question is not "is the push good" but **why the push and the sort
are incompatible**, and whether an ordered path can be preserved alongside it.
Note also that pushing RAISES the full-set cost from 15.7M to 28.4M buffers,
which is not explained by the sort and suggests the pushed subquery is being
evaluated per UNION branch rather than once.

## What is NOT established

- Why the pushed form costs more on the full result set (15.7M -> 28.4M) when a
  more selective filter should cost less. The per-branch-evaluation guess above
  is a guess.
- Whether `ORDER BY ?entity` can be served by an index or a sorted derived
  table, which would make the two compatible.
- Whether any of this generalises past this one query. Everything here is
  `wordnet_frames` and one CONSTRUCT.


## Re-evaluated 2026-09-09 — this is the fix for issues/182

`issues/182` attributed the query's cost: the plan enumerates all 285,348 frames
and evaluates the text filter once per frame, because with
`lower(term_text) ~~ '%happy%'` there is no cheap way to start from the text.

Applying this fix gives the planner the missing option:

    simplified traversal, WITHOUT this fix   1,153,015 buffers
    simplified traversal, WITH this fix          3,561 buffers   114 ms
    pinned 61-entity floor (issues/181)          3,699 buffers

    ->  Bitmap Index Scan on idx_wordnet_frames_term_trgm

**324x, and slightly better than handing the query its answer by hand.**

So the earlier framing in this document — "its sign depends on ORDER BY" — is
true but misleading. The fix is right. What is not understood is why the
reference CONSTRUCT defeats it while the simplified form of the same traversal,
on the same data with the same predicate, gets 324x.

The bisection in `issues/182` is the way to find out, and it is the only thing
between this and shipping.
