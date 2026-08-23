# The Rest of sparql10, Measured Per Category

## Status: OPEN — measurement done 2026-08-23, work not started

`issues/125` made `sparql10` reachable and wired `expr-builtin`. This records
what the REST of the tree costs, so the next person does not have to re-measure
and does not have to guess.

I said wiring the remainder was "just a list entry plus whatever it surfaces".
**That was wrong**, and this is the number: the 23 evaluation categories
collect **98 failures**, across at least six distinct causes.

## Wired 2026-08-23 — clean, zero failures

    ask  bnode-coreference  bound  dataset  optional  solution-seq  triple-match

68 cases, free coverage. Plus `expr-builtin` from `issues/125`.

## NOT wired, with the count and what is behind it

| category | ours | first look |
|---|---|---|
| `type-promotion` | 22 | `ASK { FILTER(datatype(?l + ?r) = xsd:integer) }`. `datatype()` of an ARITHMETIC result is unbound, and XSD numeric type promotion (short+short -> integer) is not implemented. One cause, 22 cases. |
| `open-world` | 10 | unexamined |
| `cast` | 7 | unexamined; `sparql11/cast` is wired and mostly passes, so compare the two |
| `expr-equals` | 6 | `FILTER(?v = 1)` over `data-eq.ttl`. Was 9 before `issues/127`; the remainder is a different cause |
| `boolean-effective-value` | 6 | unexamined |
| `graph` | 5 | likely `named_graph_semantics` §4.1 — `FROM`/`FROM NAMED` parsed and ignored |
| `algebra` | 4 | unexamined |
| `optional-filter` | 3 | unexamined |
| `regex`, `expr-ops`, `distinct` | 2 each | unexamined |
| `i18n`, `basic` | 1 each | unexamined |

## Why they are not wired with xfails

`test_dawg_sql_v2.py` says it, above `KNOWN_FAILURES`:

> Cases that fail today, kept RUNNING rather than removed so the count stays
> honest and a fix flips them to passing without anyone re-adding a category.

That works for a handful. Ninety-eight would invert it — the list stops being
a short record of known defects and becomes a wall nobody reads, and a real
regression hides in it. `issues/125` reached the same conclusion for
`expr-builtin` at 29 and was right to.

**Wire a category when its cause is fixed, not before.** Each row above is
then one line plus a green run.

## The order I would take them

1. `type-promotion` — 22 of the 98, and ONE cause. Best ratio by far, and
   `datatype()` of a computed expression is a real gap independent of DAWG.
2. `graph` — likely already-known `named_graph_semantics` §4.1, so it may
   cost nothing beyond that work.
3. `cast` — `sparql11/cast` is wired and passing, so the delta is small and
   informative.
4. The rest, cheapest first.

## What was already gained

`issues/125` and `issues/127` between them fixed four real defects found by
this tree — `lang()` on non-literals, the `langMatches` wildcard swallowing a
type error, and var-to-var value equality. The tree pays for itself; it just
does not pay all at once.
