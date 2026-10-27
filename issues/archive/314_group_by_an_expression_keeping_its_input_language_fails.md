# 314 — GROUP BY an expression that keeps its input's language or datatype fails with a SQL error

## Status: RESOLVED 2026-10-27. Verified on the vg test stack rebuilt for the fix: unit, DAWG conformance, integration and API suites, 0 failures.

## Defect

On the default (non-planner) path, which production runs, this query fails:

```sparql
SELECT ?i (COUNT(*) AS ?c) WHERE { ?s ex:name ?n } GROUP BY (SUBSTR(?n, 1, 1) AS ?i)
```

It fails with `column "g0.v1__lang" must appear in the GROUP BY clause or be used in an aggregate
function`. The cause:
- SUBSTR, UCASE, LCASE and similar functions keep their argument's language tag. So the group key's
  `__lang` companion is a column of the input (`g0.v1__lang`), not a constant.
- `emit_group._emit_group_impl` added the key's value to GROUP BY, plus its companion overrides,
  but not a language or datatype read from a column.

The query is answered with an error rather than a result. Any GROUP BY on such an expression is
affected; a key whose companions are constants (`STRLEN`, arithmetic) is not.

## How it was found

The planner's contract check runs today's SQL beside the planner's. On the new expression shapes
(`corpus/expr_shapes/x02`), today's SQL raised and the planner's ran.

## Fix

`emit_group.py`: when the key's language or datatype is SQL (`lang_is_sql`, `datatype_is_sql`), it
is grouped too. That is also the right semantics: "a"@en and "a" are different terms, so they are
different groups.

## Test

`tests/integration/test_group_by_expression_keeps_its_companions.py` covers GROUP BY SUBSTR, which
must keep "a"@fr apart from "a", and GROUP BY UCASE. Both failed with the GroupingError before the
fix and pass after.

Also run on the fix: the unit suite, DAWG on the default path, and the full integration suite.
