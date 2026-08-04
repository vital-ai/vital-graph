# `MIN`/`MAX` compare RDF terms as text, and `AVG` over a non-numeric term crashes the query

## Status: OPEN

## Severity

**Wrong results, silently** (`MIN`/`MAX`) and a **hard query failure** (`AVG`).

Read-path only — no data-loss risk. But `MIN`/`MAX` returning a plausible wrong
answer is the more dangerous of the two, because nothing signals it.

## Summary

Four W3C DAWG aggregate tests fail against the SQL backend. In every case
pyoxigraph agrees with the manifest's expected `.srx` and the SQL pipeline does
not, so these are our defects rather than oracle disagreements.

| DAWG test | Symptom |
|---|---|
| `aggregates/MAX` | wrong extremum |
| `aggregates/MAX with GROUP BY` | wrong extremum per group |
| `aggregates/MIN with GROUP BY` | wrong extremum per group |
| `aggregates/Error in AVG` | query aborts with a Postgres cast error |

## How they were found

They were not found by anyone reading the code. `tests/conformance/test_dawg_sql_v2.py`
ran only the pyoxigraph oracle and never executed the SQL pipeline, despite its
name, docstring, `sql_v2` marker and PostgreSQL+sidecar gate. Wiring it to
actually execute (2026-08-04, issue 023's coverage work) surfaced these on the
first real run.

They are currently `xfail`ed with reasons in `XFAIL_SQL_V2_EXEC` — visible and
still collected, not excluded. Removing an entry must make its test pass.

## Root cause — `MIN`/`MAX`

`_qualify_agg_inner` (`vitalgraph/db/sparql_sql/emit_group.py:292`) feeds the
**text** column to `MIN`/`MAX`:

```python
if agg_name in ("MIN", "MAX"):
    # Use text column — __num is NULL for URIs/strings, which would
    # make the error guard evaluate to NULL and destroy sort order.
    # Text comparison is correct for SPARQL MIN/MAX on all RDF types.
    return f"{src_alias}.{info.sql_name}"
```

The last line of that comment is false. Text comparison is lexicographic, so
over the test data

```turtle
:ints    :int    1, 2, 3 .
:decimals :dec   1.0, 2.2, 3.5 .
:doubles :double 1.0E2, 2.0E3, 3.0E4 .
```

`MAX(?o)` compares `"3.5"` against `"3.0E4"` as strings and picks `"3.5"`.
The correct answer is `3E+4` — thirty thousand.

SPARQL 1.1 §18.5.1 defines `MIN`/`MAX` by the `ORDER BY` ordering, which
compares numeric literals **numerically** regardless of their lexical form, and
orders across type groups (unbound < blank node < IRI < literal). Lexicographic
text ordering coincides with that only by accident.

The comment's stated concern is real — `__num` is NULL for non-numeric terms —
so the fix cannot simply switch to `__num` either. It needs a sort key that
orders numerics numerically and falls back to text (or type-group rank) for
everything else, e.g. ordering on `(type_rank, __num, text)` rather than on any
single column.

## Root cause — `AVG`

`Error in AVG` runs `AVG(?o)` over a group containing a blank node:

```turtle
:y :p 1, _:b2, 3, 4 .
```

and fails with:

```
invalid input syntax for type numeric: "b2"
```

so a text value is reaching a numeric cast. `emit_group.py:239-247` builds an
error guard intended for exactly this case —

```python
if agg_name in ("AVG", "SUM", "MIN", "MAX") and isinstance(expr.expr, ExprVar):
    ... CASE WHEN COUNT(*) != COUNT({inner_sql}) THEN NULL ELSE ...
```

— but a guard cannot help here: SQL evaluates the `CASE` arms over the same
rows, so `AVG(...)` still sees the offending value. The likely path is
`_qualify_agg_inner`'s fallback `CAST({sql_name} AS NUMERIC)` when `num_col` is
absent (`emit_group.py:288-290`); confirm before fixing.

Per SPARQL §18.5.1.4 an `AVG` over a non-numeric term yields a **type error**
for that aggregate — the solution is unbound — it does not abort the query.
The fix is to make the cast total (e.g. cast only rows that match a numeric
pattern, or use the `__num` companion which is already NULL for non-numerics)
rather than to guard around a cast that still executes.

## Suggested fix

1. `MIN`/`MAX`: order on a composite key that respects SPARQL term ordering
   instead of raw text. `__num` already exists and is populated for numeric
   literals; the missing piece is the type-group rank and the fallback.
2. `AVG`/`SUM`: never emit a cast that can raise. Prefer `__num`; where a cast
   is unavoidable, make it conditional on a numeric-literal test so a
   non-numeric row contributes NULL rather than an exception.
3. Delete the corresponding entries from `XFAIL_SQL_V2_EXEC` in
   `tests/conformance/test_dawg_sql_v2.py` — the four DAWG tests are the
   regression tests, no new ones needed.

## Related

- `issues/023_values_clause_ignored_in_sparql_update.md` — the coverage work
  that surfaced these. Its point stands: the bugs existed for as long as the
  conformance suite looked green while testing nothing.
