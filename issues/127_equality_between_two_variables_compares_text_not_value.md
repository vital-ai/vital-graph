# Equality Between Two Variables Compares Text, Not Value

## Status: RESOLVED 2026-08-23 in `60b600c`. Found and fixed the day
## `sparql10/expr-builtin` first ran. Original report follows.

    { ?x1 :p ?v1 . ?x2 :p ?v2 . FILTER ( ?v1 = ?v2 ) }

over `"1"^^xsd:integer` and `"01"^^xsd:integer` returns **nothing**. They are
one value and two terms, so `=` is TRUE and `sameTerm` is FALSE.

Found by DAWG `sameTerm-not-eq`, whose filter is exactly the distinction:

    FILTER ( !sameTerm(?v1, ?v2) && ?v1 = ?v2 )     expected 18, got 0

## Mechanism — and `sameTerm` is not the problem

`sameTerm` is correct. `emit_expressions.py:1384` compares `uuid_col`, which
IS term identity, and `term_uuid` is a UUIDv5 over
`(text, type, lang, datatype)`.

The other half is wrong. `_cmp_pair` sends two variables to the TEXT lane,
because `_is_numeric_expr` refuses to trust a BGP variable's `num_col`, and
says why:

> BGP variables all have num_col (a CASE WHEN that returns NULL for
> non-numeric values), but that doesn't mean the variable IS numeric — it
> could be a URI. Only trust typed_lane='num' which is set for computed
> variables (BIND, aggregates) known to produce numbers.

That reasoning is sound and the conclusion is still wrong: refusing the
numeric lane does not make the comparison safe, it makes it LEXICAL. So
`"1"` vs `"01"` compares false, and `"1.0e0"^^double` vs `"1"^^double` — the
same value written three ways in `data-builtin-1.ttl` — compares false too.

## Why this is not the same as the fixes that landed 2026-08-23

Those all had one side written IN THE QUERY, so the datatype was known at emit
time and the lane could be chosen statically:

* `issues/121` — literal vs stored term, datatype guard
* dateTime by instant — literal vs `dt_val`
* `"5.0"^^double` matching `5^^integer` — literal vs `num_val`

**Two variables have no compile-time type.** The lane cannot be chosen; it has
to be DECIDED AT RUN TIME, per row:

    CASE WHEN a.num_val IS NOT NULL AND b.num_val IS NOT NULL
              THEN a.num_val = b.num_val
         WHEN a.dt_val  IS NOT NULL AND b.dt_val  IS NOT NULL
              THEN a.dt_val = b.dt_val
         ELSE a.term_text = b.term_text
              AND COALESCE(a.datatype,'..#string')
                  IS NOT DISTINCT FROM COALESCE(b.datatype,'..#string')
    END

That is the shape, not a patch to apply blind. **Measure first:** this
replaces a column-to-column comparison inside joins with a multi-branch CASE,
and `?v1 = ?v2` across two BGP triples is a join predicate. `issues/054`
records `gt` becoming uniquely slow from a related change, and the
`num_val`/`dt_val` partial indexes exist precisely so the planner can use one
branch — a CASE may defeat them.

## Blast radius

Wider than the DAWG case. Any `FILTER(?a = ?b)` between two stored values is
lexical today, so a query joining two numeric properties silently misses rows
whose lexical forms differ — `1` vs `01` vs `1.0`. Our own data is largely
written by one path and so is lexically consistent, which is why nothing has
noticed.

`!=` inverts it: two variables holding one value with different spellings
compare UNEQUAL, so a `FILTER(?a != ?b)` returns rows it should not.

## Tests

`sameTerm-eq`, `sameTerm-not-eq`, `sameTerm-simple` are in `KNOWN_FAILURES`
naming this issue, kept RUNNING so a fix flips them rather than needing anyone
to remember to re-add a category. They also appear in `XFAIL_TESTS_V2`,
because the oracle independently disagrees with the corpus for them — both
entries are needed and deleting either hides half the picture.


## Resolved

`_var_var_cmp` in `emit_expressions.py`. The lane is chosen PER ROW rather than
at emit time: `num_col` is already a `CASE` yielding NULL for anything
non-numeric, so "are both sides numeric" costs nothing to ask. Where it holds,
compare numerically; otherwise the text lane exactly as before, datatype guard
included.

A plain `"1"` is NOT caught by the numeric branch — `num_col` requires a
numeric `datatype_id` — so a string that merely looks like a number still
compares as a string. That is the distinction `issues/121` turns on.

Verified against the CORPUS, not against my own expectation:

    case              .ttl   pyoxigraph   before   after
    sameTerm-eq        24        14         14      24
    sameTerm-not-eq    18        28          0      18
    sameTerm-simple    24        14         14      24

`sameTerm-not-eq` went from zero rows to eighteen, which is what the `.ttl`
expects. All three now match the corpus and pyoxigraph is the one that differs,
so they stay in `KNOWN_FAILURES` with a corrected reason rather than being
deleted — `test_sql_v2` compares against the oracle, and deleting them would
claim a pass we do not get.

Perf ran clean afterwards, which was the real risk: this puts a `CASE` where a
column comparison used to sit, and `?a = ?b` across two BGP triples is a JOIN
PREDICATE. `issues/054` records `gt` becoming uniquely slow from a related
change.

**Marked resolved a day late**, which is the drift the
`planning_sparql_features` README now warns about — and it happened in work
done the same session as that warning.
