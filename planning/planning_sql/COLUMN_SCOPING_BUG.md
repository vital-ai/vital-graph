# Column Scoping Bug: EXTEND + FILTER in Non-BGP Modifier Path

## Status
**Open** — affects ~13 DAWG tests (bind04/05/07/08/10, UUID/STRUUID pattern match, exists tests, GROUP BY with functions)

## Problem

When the non-BGP modifier path in `jena_sql_emit.py` applies EXTEND expressions via sqlglot, the computed column is added to the SELECT list but is **not available** for subsequent FILTER or EXTEND expressions that reference it. This is because sqlglot adds it as a peer column in the same SELECT, not as a subquery that later clauses can reference.

## Example: UUID pattern match test

**SPARQL:**
```sparql
SELECT (STRLEN(STR(?uuid)) AS ?length)
WHERE {
  BIND(UUID() AS ?uuid)
  FILTER(ISIRI(?uuid) && REGEX(STR(?uuid), "^urn:uuid:...", "i"))
}
```

**Algebra:**
```
OpProject(vars=['length'],
  OpExtend(var='length', expr=STRLEN(STR(?uuid)),
    OpFilter(expr=ISIRI(?uuid) && REGEX(STR(?uuid), ...),
      OpExtend(var='uuid', expr=UUID(),
        OpTable(vars=[], rows=[{}])))))
```

**Generated SQL (broken):**
```sql
SELECT LENGTH(uuid) AS length
WHERE (uuid__type = 'U') AND (uuid ~* '^urn:uuid:...')
```

The base SQL from `_emit_table` is `SELECT 1 AS _dummy`. The EXTEND for `uuid` computes `'urn:uuid:' || gen_random_uuid()::text` and sqlglot adds it as a SELECT column. But the WHERE clause references `uuid` and `uuid__type` — columns that don't exist in the FROM clause.

**Correct SQL should be:**
```sql
SELECT LENGTH(sub.uuid) AS length
FROM (
  SELECT 'urn:uuid:' || gen_random_uuid()::text AS uuid,
         'U' AS uuid__type
  FROM (SELECT 1 AS _dummy) AS base
) AS sub
WHERE (sub.uuid__type = 'U')
  AND (sub.uuid ~* '^urn:uuid:...')
```

## Root Cause

The non-BGP modifier path (`emit()` lines ~630–700 in `jena_sql_emit.py`) applies modifiers sequentially on a single `parsed` sqlglot AST:

1. FILTER → `parsed.where(...)` — adds WHERE clauses
2. GROUP BY → `parsed.group_by(...)` 
3. EXTEND → adds computed columns to SELECT
4. PROJECT → final column selection

The problem is that **SPARQL evaluation order** requires EXTEND to produce its result *before* FILTER sees it. In SQL, a WHERE clause cannot reference a column alias defined in the same SELECT. The column must come from a subquery (FROM clause).

## Affected Test Patterns

| Pattern | Tests | Column Missing |
|---------|-------|----------------|
| BIND + FILTER on same var | bind04, bind05, bind08, bind10 | `nova`, `z__text` |
| BIND + outer EXTEND | bind07 | `o` |
| BIND(UUID()) + FILTER | uuid01, struuid01 | `uuid` |
| EXISTS with constants | exists tests | `__const_c_0__`, `__const_c_1__` |
| GROUP BY with function expr | agg GROUP BY | `d`, `i`, `x` |

## Proposed Fix

When an EXTEND expression is referenced by a FILTER (or a subsequent EXTEND), the modifier path must **wrap the current SQL in a subquery** before applying the FILTER. This ensures the EXTEND column is materialized and visible.

Pseudocode:
```python
# In the non-BGP modifier path:
if plan.extend_exprs:
    for var, expr in plan.extend_exprs.items():
        # Add computed column to SELECT
        sql_expr = _expr_to_sql_str(expr, plan)
        parsed = parsed.select(f"{sql_expr} AS {var}")

    # If there are FILTERs that reference EXTEND vars, wrap in subquery
    extend_vars = set(plan.extend_exprs.keys())
    filter_refs = set()  # vars referenced by filter expressions
    for expr in (plan.filter_exprs or []):
        filter_refs.update(_vars_in_expr(expr))

    if extend_vars & filter_refs:
        # Materialize EXTEND columns as a subquery
        inner_sql = parsed.sql(dialect=PG_DIALECT)
        parsed = sqlglot.parse_one(
            f"SELECT * FROM ({inner_sql}) AS _ext",
            dialect=PG_DIALECT
        )
```

## Complexity Notes

- The fix must handle **chained EXTENDs** where EXTEND B references EXTEND A
- The fix must propagate `__type`, `__uuid`, `__lang`, `__datatype` companion columns
- GROUP BY with function expressions (like `GROUP BY STR(?o)`) is a separate but related issue — the GROUP BY expression must use the same SQL as the SELECT alias
- EXISTS subquery constant resolution (`__const_c_0__`) is a different bug in the constant CTE scoping
