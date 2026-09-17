# A SERVICE Clause Silently Annihilates The Result Set

## Status: OPEN, filed 2026-09-16 while closing the `issues/193` shape-coverage
## gap. Found by asking why SERVICE had no bench; it has no bench because it
## does not work, and the way it does not work is silent.

## What happens

Federation is not implemented. The generator compiles a `SERVICE` block to an
empty relation and INNER joins it:

    JOIN (SELECT 1 WHERE FALSE) AS j1 ON TRUE

An inner join against an empty relation annihilates everything above it.
Measured on `sp_lead_synth_10k`, same local pattern either way:

    SELECT * WHERE { GRAPH <g> { ?f vitaltype KGFrame } }                 5 rows
    ... the same, plus SERVICE <http://example.org/sparql> { ?f ?p ?o }   0 rows

No error. No warning. No `vg:` marker in the SQL. `success` is not false. The
caller cannot distinguish "the remote service had nothing for you" from "this
store ignored a third of your query and answered the rest".

## Both halves of §10.2 are wrong, in opposite directions

SPARQL 1.1 §10.2 defines the two cases, and neither holds:

  * plain `SERVICE` against an endpoint that cannot be reached is an **error**.
    Quietly returning zero rows is the one response it must not give.
  * `SERVICE SILENT` must behave as though the pattern matched a **single empty
    solution**, so the surrounding solutions survive the join. Here SILENT is
    not distinguished from plain SERVICE at all — both emit the same
    `SELECT 1 WHERE FALSE` — so it destroys exactly the solutions it is
    specified to preserve.

The SILENT case is the more serious of the two. A caller writes SILENT
*precisely* to say "carry on without the remote part", and gets back nothing.

## Not implementing federation is fine

This is not an argument that the store must federate. Declining is a
legitimate choice, and most embedded stores make it. The defect is that the
choice is expressed as a wrong answer rather than as a refusal.

Rejecting the query at parse time — "SERVICE is not supported" — resolves this
completely and is probably the right fix. It is also much less work than
federation, and it turns a silent data-loss bug into an error message.

## Pinned by

`tests/integration/test_service_clause_semantics.py`, three cells:

  * a control proving the local pattern matches 3 rows, so the others are not
    vacuous;
  * `xfail`: unreachable SERVICE should error, not answer empty;
  * `xfail`: SILENT should preserve the local solutions.

`strict=False` on both, because either resolution — implementing federation or
rejecting the query — turns one or both green, and neither should then fail
for having succeeded.

## Why there is no bench

`issues/193` lists SERVICE as an unbenched shape. It stays unbenched: a bench
records what a shape COSTS, and this one has no meaningful cost because it
returns nothing. The two cells above are the right instrument until the
semantics are settled. DESCRIBE, the other gap that issue names, IS now
benched — `query.sparql_shape[describe]`, both phases.
