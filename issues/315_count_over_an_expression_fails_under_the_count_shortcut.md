# 315 — COUNT over an expression fails: the COUNT-only shortcut defers the text the expression needs

## Status: FIXED 2026-10-26, on the default path. Open until the vg test stack runs the full suite on the rebuilt image.

## Defect

On the default path, which production runs, these queries fail:

```sparql
SELECT (COUNT(DISTINCT LCASE(?n)) AS ?c) WHERE { ?s ex:name ?n }
SELECT ?s (COUNT(UCASE(?n)) AS ?c) WHERE { ?s ex:name ?n } GROUP BY ?s
```

When every aggregate is COUNT, `emit_group` takes a shortcut (`_all_count_no_keys`,
`_pushdown_candidates`): COUNT needs only term uuids, so every term-table JOIN is deferred. That holds
for COUNT(*) and COUNT(?v). It does not hold for COUNT over an expression: LCASE(?n) needs ?n's text.

The generator's own guard caught the deferred text and refused the statement:
`UnresolvedVariableError: ?n (text-not-materialised)`. So the query errors; it does not return a
wrong count.

## How it was found

The planner's contract check, which runs today's SQL beside the planner's, on the new expression
shapes (`corpus/expr_shapes/x05`).

## Fix

`emit_group.py`: both shortcuts require each COUNT's argument to be `*` or a plain variable.

## Test

`tests/integration/test_count_over_an_expression_reads_its_text.py`:
- COUNT(DISTINCT LCASE) and a grouped COUNT(UCASE) both failed before the fix and pass after;
- COUNT(DISTINCT ?n), which still takes the shortcut, is the control.

Also run on the fix: the unit suite, DAWG on the default path, and the full integration suite.
