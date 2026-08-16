# `xsd:float` Casts Leak the float32→float64 Expansion Into the Lexical Form

## Status: PRECISION LEAK FIXED 2026-08-16; canonical-form question still open

    SELECT ?a ?v (xsd:float(?v) AS ?float) WHERE { ?a :p ?v }

with `:s04 :p "+33.3300"`:

| | `?float` |
|---|---|
| expected (`cast-float.srx`) | `3.333E1` |
| pyoxigraph | `33.33` |
| ours, before | `33.33000183105469` |
| **ours, after the fix** | **`33.33`** |

## Correction to the first version of this issue

It said *"We return the row with `v` already normalised"* and gave the defect low
confidence because "pyoxigraph also differs from the manifest". Both claims were
wrong, and measuring instead of inferring reversed the conclusion.

`?v` is **not** normalised by us. We return `+33.3300` exactly as the manifest
requires — verified across all 31 rows. The original reading confused the two
columns.

And while pyoxigraph does differ from the manifest here, it differs in a
*different and much smaller* way than we do, so "both differ" was hiding rather
than excusing the defect.

## The mechanism

`33.33` is not representable in binary32. The nearest float32 is
`33.3300018310546875`, and rendering depends entirely on which width you render
at:

    SELECT CAST('+33.3300' AS REAL)::text                          -->  33.33
    SELECT CAST(CAST('+33.3300' AS REAL) AS DOUBLE PRECISION)::text -->  33.33000183105469

PostgreSQL gets this right on its own: `REAL::text` gives the shortest string
that round-trips. We produce the second form, which means the cast result is
being **widened into the float8 numeric lane before it is serialised**.
`_XSD_CAST_MAP` at `emit_expressions.py:389` maps `xsd:float` to `REAL`
correctly; the loss happens after, in the lane.

So this is not a rounding disagreement or a spec ambiguity. It is a real number
rendered with sixteen digits of binary noise, in a form no engine and no
specification produces, and it is visible to anyone who calls `xsd:float`.

## Fixed

Two changes, and the second is the one that made the first take effect.

`_normalize_float` renders at the width the datatype actually has: the shortest
decimal that survives a round trip through binary32. Rendered via `repr` rather
than `%g`, whose exponent threshold would turn `-10200` into `-1.02e+04`.

`sql_to_sparql_binding` stringified the value BEFORE reading the `__datatype`
companion, so the datatype could not inform the rendering even in principle —
and that is the path the conformance suite uses. The lookup now happens first.
Fixing only the formatter would have changed nothing measurable, which is worth
recording: the first version of this fix was written in
`sparql_sql_space_impl._rows_to_bindings` and had no effect at all, because that
is a different binding builder from the one under test.

The rule lives in `sql_type_binding.normalize_numeric` alone; the inline copy
was removed rather than left beside it.

## The second, separate question

Even the shortest round-trip is not what the manifest asks for. XSD's canonical
form for `float` is scientific — `3.333E1`, `-1.02E4`, `0E0` — and NEITHER
engine emits it. pyoxigraph gives `33.33`, we give the expansion, the manifest
wants `3.333E1`.

That half is a genuine "both implementations differ from the spec" case, and is
worth deciding separately from the precision leak. The leak should be fixed
regardless of how canonical-form is settled.

## Why the precision leak was not found earlier

The `cast` category was never in `P0_CATEGORIES`. See
`planning/planning_sparql_features/dawg_conformance_coverage.md`.

## Related

- `issues/093` — subquery inside `GRAPH` returns zero rows, found in the same pass
- `csv-tsv-res/csv03` — the OPPOSITE result, and the reason this issue got
  re-examined: there we preserve `"1.0E6"^^xsd:double` correctly and pyoxigraph
  canonicalises it to `1000000`. Lexical-form handling is not uniformly wrong in
  either engine, which is exactly why each case needs measuring rather than
  attributing by reputation.
