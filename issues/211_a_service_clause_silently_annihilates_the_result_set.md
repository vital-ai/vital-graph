# A SERVICE Clause Silently Annihilates The Result Set

## Status: FIXED 2026-09-16 by failing closed in `map_op`. Filed while closing
## the `issues/193` shape-coverage gap — found by asking why SERVICE had no
## bench; it had none because it did not work, and the way it did not work was
## silent. The root cause was broader than SERVICE: see "The actual fault".

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

## The actual fault was not SERVICE-specific

`map_op` mapped ANY unregistered operator to `OpNull`, with a log warning as
the only trace:

    logger.warning("Unknown op type: %s — returning OpNull", otype)
    return OpNull()

`OpNull` emits `SELECT 1 WHERE FALSE`, and an unknown op is joined to the rest
of the query, so the empty relation annihilates every solution above it.
SERVICE was simply the operator we happened to hit; anything else Jena emits
without a mapper here behaved the same way, and would have been just as quiet.

This module already had the policy and the exception for it.
`UnsupportedSparqlElement` sits 250 lines above, and its docstring says
"Raised instead of degrading to an empty pattern." The UPDATE path has raised
it since `issues/023`, for the mirror-image reason: there a dropped element
WIDENS the pattern, so a whole-graph DELETE reports success. Query and update
disagreed; they now agree.

`execute_sparql_query` already wraps translation in a try/except that returns
`{'success': False, 'error': str(e)}`, so the refusal surfaces as a domain
outcome rather than a 500 — no endpoint change was needed.

## Not implementing federation is fine

This is not an argument that the store must federate. Declining is a
legitimate choice, and most embedded stores make it. The defect is that the
choice is expressed as a wrong answer rather than as a refusal.

Rejecting the query at parse time — "SERVICE is not supported" — resolves this
completely and is probably the right fix. It is also much less work than
federation, and it turns a silent data-loss bug into an error message.

## Rejecting SILENT deviates from §10.2, deliberately

This is the one part of the fix that is a judgement call rather than a
correction, so it is recorded as such.

§10.2 would have `SERVICE SILENT` preserve the surrounding solutions. It does
not here — both forms are refused. The reasoning: SILENT means "carry on if the
remote is unavailable", and this store never attempts the call at all. Carrying
on would mean quietly returning an answer assembled from half the query, which
is the same silence this issue was filed about, merely better spelled. While
federation is unimplemented, an explicit refusal is the honest outcome.

If federation is ever implemented, this is the decision to revisit, and
`test_silent_service_is_refused_rather_than_silently_emptied` is the cell that
has to change back.

## Pinned by

`tests/integration/test_service_clause_semantics.py`, three cells, all passing:

  * a control proving the local pattern matches 3 rows, so the others are not
    vacuous;
  * unreachable SERVICE returns `success: False` with an error;
  * SILENT is refused too, and the error NAMES what was refused — asserted,
    because an error the caller cannot act on is barely better than silence.

## Why there is no bench

`issues/193` lists SERVICE as an unbenched shape. It stays unbenched: a bench
records what a shape COSTS, and this one has no meaningful cost because it
returns nothing. The two cells above are the right instrument until the
semantics are settled. DESCRIBE, the other gap that issue names, IS now
benched — `query.sparql_shape[describe]`, both phases.
