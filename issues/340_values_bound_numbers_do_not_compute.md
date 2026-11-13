# 340: Numbers bound with VALUES do not compute: arithmetic is unbound and comparisons drop every row

## Status: FIXED 2026-11-13 (uncommitted); verified on the rebuilt vg test stack: unit 6,356 passed; W3C/DAWG conformance 1,532 passed (unchanged); `tests/api/test_values_numbers_api.py` 17 and `test_fuzzy_match_api.py` 14.

## Cause (confirmed)

As guessed below: `emit_table` emitted `NULL::numeric AS v__num` (and NULL
`__bool`, `__dt`) for every literal, so the typed lanes that arithmetic,
comparison and `YEAR()` read were empty. Projection reads the text column,
which is why `?a` itself came back right.

## Fix

`emit_table._literal_lane_columns` fills the three lanes as
`TypeRegistry.term_table_columns` does for a stored term: a numeric datatype
with a number's lexical form goes on `__num`, `true/false/1/0` on `__bool`, and
a readable date/dateTime on `__dt`. `"xyz"^^xsd:integer` stays off the lane, as
it does when stored.

The guard runs in Python, not as a SQL `CASE`. The first version emitted
`CASE WHEN 'xyz' ~ … THEN CAST('xyz' AS NUMERIC) END`, and the API test failed
with `invalid input syntax for type numeric: "xyz"`: PostgreSQL coerces a
quoted constant while PARSING, before any branch is chosen. Checked directly:
`SELECT CASE WHEN 'xyz' ~ '^[0-9]+$' THEN CAST('xyz' AS NUMERIC) END` raises.
The same trap was live in the cast emitter (`issues/341`).

## Why DAWG did not catch it

Its VALUES cases with numbers only join, project or concatenate them
(`property-path/values_and_path`, `bindings/inline01`, the `agg-groupconcat`
cases). None compares or computes with one.

## Tests

- `tests/unit/sparql_sql/test_emit_table.py::TestValuesLiteralLanes`:
  numbers, booleans, datetimes on their lanes; strings on none; and a
  malformed number or date emits no CAST at all.
- `tests/api/test_values_numbers_api.py::test_a_values_number_computes` (each
  row of the table below, plus decimals, doubles, a malformed integer beside a
  good one, and numeric ORDER BY) and
  `test_a_values_boolean_and_datetime_compute`.

## Original report

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
