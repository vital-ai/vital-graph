# 340: Numbers bound with VALUES do not compute: arithmetic is unbound and comparisons drop every row

## Status: OPEN. Found 2026-11-12; not investigated beyond the reproduction.

Found while writing the API tests for `issues/337`.

## Reproduction

Read-only queries. Results are the same on the vg test stack (this session's
build) and on the dev server's older image (built 2026-11-10), so this
predates `337`'s changes.

| Query | Returned | SPARQL says |
|---|---|---|
| `SELECT ?a ?y WHERE { VALUES ?a { 1 2 } BIND(?a + 1 AS ?y) }` | `a=1`, `a=2`; **`?y` unbound** | `y=2`, `y=3` |
| `SELECT ?a ?y WHERE { VALUES ?a { 1 2 } BIND(?a * 3 AS ?y) }` | `?y` unbound | `y=3`, `y=6` |
| `SELECT ?a WHERE { VALUES ?a { 1 2 } FILTER(?a > 1) }` | **no rows** | `a=2` |
| `SELECT ?a WHERE { VALUES ?a { 1 2 } FILTER(?a * 3 > 4) }` | no rows | `a=2` |
| `SELECT ?a ?y WHERE { VALUES ?a { 1 } BIND(?a AS ?y) }` | `a=1, y=1` | correct |
| `SELECT ?a ?y WHERE { BIND(2 AS ?a) BIND(?a * 3 AS ?y) }` | `y=6` | correct |
| `{ BIND(1 AS ?a) } UNION { BIND(2 AS ?a) } BIND(?a * 3 AS ?y)` | `y=3`, `y=6` | correct |

So a number from VALUES reads back as itself and is projected correctly, but
does not take part in arithmetic or numeric comparison. The same number from
BIND does.

**It fails silently**: a FILTER drops every row, and an expression leaves its
variable unbound. A caller gets a plausible, wrong answer, not an error.

## Likely cause (unverified)

The VALUES emitter (`emit_table`) probably does not fill the `__num` companion
for numeric literals, so the numeric lane reads NULL. `_cmp_sql` and the
arithmetic emitters prefer `__num` when an operand looks numeric. That would
explain a NULL comparison (row dropped) and a NULL arithmetic result (unbound)
while the text column projects fine. Check the VALUES literal → `ColumnInfo`
and companion columns first.

## Why the conformance suite did not catch it

Not checked. The DAWG `bindings` / VALUES tests may use only IRIs and strings,
or compare through a different path. Look at which DAWG cases put a numeric
literal in VALUES and then compute with it.

## Impact

Any query that puts numbers in VALUES and filters or computes with them. KG
endpoints mostly put IRIs in VALUES. A client's hand-written SPARQL could hit
it, and would get wrong results, not an error.
