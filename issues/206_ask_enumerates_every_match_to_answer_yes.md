# ASK Enumerates Every Match To Answer "Yes"

## Status: OPEN, found 2026-09-15 by the `issues/193` shape bench — the second
## defect that bench found, and it had not measured anything twice.

## The measurement

    ASK { GRAPH <urn:sp_lead_synth_10k> { ?f vital-core:vitaltype haley:KGFrame } }

    buffers  23,427
    rows     120,000

120,000 is exactly the number of `KGFrame` instances in the fixture. The query
asks whether AT LEAST ONE exists and evaluates ALL of them.

## The generated SQL says why

    has LIMIT   : False
    has EXISTS  : False
    shape       : SELECT t_v0.term_text AS v0, t_v0.term_type, ... (3,311 chars)

It is an ordinary SELECT that projects the full term columns — text, type, uuid,
lang, datatype, and the numeric/boolean/datetime lanes — for every match, and
the boolean answer is inferred from whether any rows came back.

So an ASK pays twice over: it enumerates the whole match set, AND it resolves
term text for each row it will never return.

## Why this matters more than the fixture suggests

The cost tracks the match set, and ASK is the form a caller reaches for
PRECISELY when they do not want the rows. On this 7.4M-quad fixture it is 23,427
buffers; `cardiff_kg` in production is 48.7M quads, where the same question
against a common type would enumerate proportionally more.

An existence check over an indexed predicate should be a single index probe —
one buffer, not 23,427.

## The fix, most likely

`SELECT EXISTS (...)`, or failing that `... LIMIT 1` with no term projection.
PostgreSQL stops an `EXISTS` at the first tuple, which is the semantics ASK
already has. The projection is pure waste in either case: no column of it is
used to produce a boolean.

## Not yet established

- Whether the ASK path shares its emitter with SELECT and simply never applies
  a limit, or whether something explicitly asks for the full projection.
- Whether a `FILTER`ed ASK behaves the same, or whether the filter happens to
  bound it.
- Whether DESCRIBE has the same shape. It is still unbenched — `issues/193`
  lists it as absent, and a pattern-less DESCRIBE is already known to produce
  degenerate SQL (a skipped case in `test_emit_pipeline.py`).

## Reproduce

`tests/performance/test_sparql_shape_coverage.py::test_sparql_form_is_measured`,
the `ask` case. The generated SQL is one `_generate_sql` call away.
