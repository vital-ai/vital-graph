# ASK Enumerates Every Match To Answer "Yes"

## Status: WITHDRAWN 2026-09-15, same day. NOT A DEFECT — the optimisation
## already exists and I measured the wrong SQL. Kept because the mistake is
## reusable: a bench that reads the GENERATOR's output is not measuring what
## runs.

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
buffers; `<space>` in production is 48.7M quads, where the same question
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

## WITHDRAWN — the wrapper exists, and the bench never saw it

`sparql_sql_space_impl.py:2167`, in the execution path:

    if cr.meta.query_type == 'ASK':
        sql = f"SELECT EXISTS (SELECT 1 FROM ({sql}) _ask_sub) AS _ask_result"

with a comment stating the very thing this issue "found": *"ASK only needs to
know whether any row matches. The generator does not specialise on query_type,
so without this the query materialises every matching row to answer a yes/no
question."*

Measured both, same query, same fixture:

    raw (generator output)   23,426 buffers   120,000 rows
    wrapped (what executes)           9        1

Nine buffers. The production path was already doing the right thing.

## What went wrong, and it is worth keeping

The bench calls `_generate_sql`, which returns the GENERATOR's SQL. The runtime
then applies transformations the generator does not: this ASK wrapper, and
`enable_sort = off` when `needs_ordered_scan` is set. So the bench measures a
string that is never executed for any form the runtime specialises.

That is a general hazard, not an ASK one. Anything benched through
`_generate_sql` should be read as "what the generator produced", and where the
runtime rewrites it, the bench must rewrite it too or it is measuring fiction.

Fixed in the bench by applying the same wrapper, so the recorded number is the
one a caller pays.

## The one thing here that was real

The generator DOES emit a full projection for an ASK — term text, type, uuid,
lang, datatype and all three value lanes — which the wrapper then discards. That
is wasted generation work rather than wasted execution, and it is small: the
wrapper reduces the whole thing to 9 buffers. Not worth chasing, recorded only
so the next reader does not re-derive it.