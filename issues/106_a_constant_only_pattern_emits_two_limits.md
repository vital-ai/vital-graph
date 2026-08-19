# An All-Constant Pattern Emits Two LIMITs and Reaches PostgreSQL Malformed

## Status: FIXED 2026-08-18

    SELECT * WHERE { GRAPH <g> { <s> <p> <o> } } LIMIT 1

    asyncpg.exceptions.PostgresSyntaxError: syntax error at or near "LIMIT"

A BGP with no variables is an existence check, and `emit_bgp` short-circuits it:
one matching row settles the question, so scanning further is waste. It appended
`LIMIT 1` to do that — and left it TERMINATING the returned string.

Every other emitter in this package returns COMPOSABLE SQL: a parent may wrap it
in a subquery or append clauses to it. This one quietly did not, so a query
carrying its own limit produced

    ... WHERE q0.subject_uuid = ... AND q0.context_uuid = ... LIMIT 1 LIMIT 1

The fix keeps the short-circuit and moves it inside a subquery:

    SELECT 1 AS _dummy FROM (SELECT 1 FROM ... WHERE ... LIMIT 1) _exists

## Why it survived

The shape has to be unusual in three ways at once, and each one alone is fine:

* `SELECT *` with **no variables anywhere in the pattern** — otherwise
  `plan.var_slots` is non-empty and this branch is never taken.
* an explicit `LIMIT` — without one nothing is appended and the SQL is valid.
  `SELECT * WHERE { GRAPH <g> { <s> <p> <o> } }` answers correctly.
* not `ASK`, which wraps the same body in `SELECT EXISTS (...)` and so never
  appends a limit to it.

Nothing in the suites asked for that combination. It was found while probing an
unrelated symptom by hand — the frames-list count/page mismatch of `issues/088`'s
late-text regression — where it appeared as a stray failure next to the case
being investigated and was set aside rather than filed.

## Severity

Malformed SQL, not a wrong answer: it raises rather than under-reporting, which
is the better of the two failures and the reason this is a small issue rather
than a repeat of `issues/100`. A caller sees a 500.

## Tests

`tests/integration/test_constant_bgp_is_composable.py` — the pattern under
`LIMIT 1`, `LIMIT 10` and no limit; an ABSENT constant under a limit, so the
short-circuit still short-circuits and still answers "no"; and `ASK` over both,
asserted against the emitted SQL rather than the bindings, because this impl
returns ASK as `SELECT EXISTS (...)` with an empty `bindings` list — reading the
rows would have asserted nothing.

Verified to fail before the fix: the two limit cases error, the rest pass.

## Related

- `issues/073` — the `provably_empty` wrapper that also appends `LIMIT 0`; it
  wraps in a subquery, which is why it never collided with this
