# 334 — Under FROM / FROM NAMED a pattern keeps only its first triple

## Status: FIXED 2026-11-08. Verified on the vg test stack: unit, W3C/DAWG conformance (1,484 passed), integration, API.

Found while changing the same function for `issues/333`.

## The defect

`collect._collect_bgp` handles a query's dataset clause inside its per-triple
loop, and that branch ended with `return plan`. So the first triple of every
basic graph pattern was collected, and the rest of the pattern was silently
dropped whenever the query had a `FROM` or `FROM NAMED`:

    SELECT ?s FROM <g> WHERE { ?s :a ?x . ?s :b ?y . ?s :c ?z }

compiled to SQL with ONE quad (`?s :a ?x`) and returned every subject with an
`:a`, whether or not it had a `:b` or `:c`. Measured through the real generator:
3 quads without a dataset clause, 1 with one.

The failure is a WIDER answer, not an error, the same shape `605a9db2` set out
to remove ("a caller scoping a query to one graph got everything and nothing
said so"). That commit (2026-08-24, "honour FROM and FROM NAMED") introduced
the `return`. Every multi-triple pattern under a dataset clause has been
affected since.

**Who is exposed.** Only callers that put `FROM` / `FROM NAMED` in their
SPARQL. KGQuery, the KG endpoints and the memory service scope with
`GRAPH <uri>` or a graph lock, so they are not affected. It is not known
whether any external caller of the SPARQL endpoint uses a dataset clause.

## Fix

`continue` to the next triple instead of `return plan`. The dataset branch
still skips the default-graph and `GRAPH <uri>` rules below it, as intended.

## Tests

`tests/integration/test_from_keeps_every_triple.py`:
- `FROM <g>` and `FROM <g> FROM NAMED <g>` with a three-triple pattern emit 3
  quads and return only the subject that has all three
- `FROM NAMED <g> { GRAPH ?g { two triples } }` returns only subjects with both

All three fail against the reverted line.

The W3C dataset tests did not catch this. The likely reason is that their
dataset queries use single-triple patterns, but that is not checked.
