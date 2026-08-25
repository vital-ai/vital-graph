# The Rest of sparql10, Measured Per Category

## Status: OPEN — measurement done 2026-08-23, work not started

`issues/125` made `sparql10` reachable and wired `expr-builtin`. This records
what the REST of the tree costs, so the next person does not have to re-measure
and does not have to guess.

I said wiring the remainder was "just a list entry plus whatever it surfaces".
**That was wrong**, and this is the number: the 23 evaluation categories
collect **98 failures**, across at least six distinct causes. (76 after `type-promotion` landed 2026-08-23.)

## Wired 2026-08-23 — clean, zero failures

    ask  bnode-coreference  bound  dataset  optional  solution-seq  triple-match

68 cases, free coverage. Plus `expr-builtin` from `issues/125`.

## RE-MEASURED 2026-08-24, after type-promotion and the RDFterm-equal rule

48 failures of ours across 12 categories (75 including the oracle half). The
table below is the ORIGINAL measurement; the current counts are:

| category | was | now | note |
|---|---|---|---|
| ~~`open-world`~~ | ~~10~~ | **DONE** — wired 2026-08-24, 30 passed / 6 xfailed / 0 failed | `open-eq-06` fixed by the type-error rule. The rest need the same rule in the PUSH-DOWN — `?v != 1` goes through `_try_inequality_filter`, which this did not touch. |
| `cast` | 7 | **6** | next target; `sparql11/cast` is wired and passing, so the delta is small and informative |
| `expr-equals` | 6 | **4** | improved by the determinacy work. **unchanged at the first re-measure.** I predicted the type-error rule would clear these for free. It did not. Re-measured rather than assumed, which is the only reason that is known. |
| ~~`boolean-effective-value`~~ | ~~6~~ | **DONE 2026-08-24** — no EBV implementation existed; §17.2.2 now computed. 14 passed, wired. |
| `graph` | 5 | 5 | untouched |
| `algebra` | 4 | 4 | untouched |
| `optional-filter` | 3 | 3 | untouched |
| `regex`, `expr-ops`, `distinct` | 2 each | 2 each | untouched |
| `i18n`, `basic` | 1 each | 1 each | untouched |

**A measurement taken before a semantic change does not survive it, and the
direction is not predictable.** `type-promotion` went 22 -> 0 from one rule;
`expr-equals` went 6 -> 6 from a rule that looked like it should have helped.

## NOT wired, with the count and what is behind it

| category | ours | first look |
|---|---|---|
| ~~`type-promotion`~~ | ~~22~~ | **DONE 2026-08-23** — wired, 60 passed / 0 failed. Both halves were real: `datatype()` never consulted the type inference at all, and the inference typed arithmetic by propagating the FIRST argument, which XSD promotion contradicts. |
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


---

## Re-measured 2026-08-24, after `named_graph_semantics` §4.1/§4.2

The table above predates the dataset work and one of its predictions was
wrong, which is the reason for re-measuring rather than reasoning forward.

All 13 unwired sparql10 evaluation categories, measured together:

| category | ours | oracle |
|---|---|---|
| ~~`sort`~~ | ~~0~~ | ~~**10**~~ → **DONE**, wired, 28 passed |
| ~~`cast`~~ | ~~**6**~~ | 0 → **DONE**, wired, 0 failed |
| ~~`graph`~~ | ~~5~~ → **3** | 3 → **DONE**, wired, gaps registered |
| `expr-equals` | 4 | 2 |
| `construct` | 0 | 5 |
| `regex`, `optional-filter`, `expr-ops`, `distinct`, `algebra` | 2 each | — |
| `reduced` | 0 | 2 |
| `i18n` | 1 | — |

### `sort` — 10 oracle failures, one cause, none of them ours

The whole category failed on the ORACLE, which is why it had never been
wired, which is why ORDER BY had no conformance coverage at all. A `.ttl`
expectation is either a CONSTRUCT graph or the DAWG `rs:` result-set
vocabulary and `_parse_ttl_graph` chose between them; the RDF/XML and TriG
parsers never made that choice. `sort` keeps its expectations in
`result-sort-N.rdf`, so all ten compared ~22 `rs:` triples against 4 result
rows. **Our sort implementation needed no change** — it was correct
throughout and the harness could not see it.

### `cast` — 6, and the fix was in `datatype()`

The cast emitters were already right: they answer NULL where the target
cannot hold the lexical form. `datatype()` fell through to the STATIC type
inference, which reports the target type unconditionally — so
`datatype(xsd:decimal(?v))` was constant and the FILTER kept all 7 rows.
Fixing that exposed a second: `xsd:dateTime` had no lexical guard at all and
an unguarded CAST **raises** rather than returning NULL, killing the
statement outright.

### `graph` — the prediction that was wrong

The table above guessed all 5 were §4.1. One was (`graph-04`, and by way of
the harness declaring `default_graph` conditionally, not the engine). The
other three are a single unrelated gap: a graph-scoped group with **no triple
pattern** — `GRAPH ?g {}`, `GRAPH ex:unknown {}`, `GRAPH ?g { FILTER(...) }` —
must be evaluated against the named graphs, and we treat `{}` as a no-op that
matches once regardless. Registered in `XFAIL_SQL_V2_EXEC`; it needs a source
for the graph variable where no quad scan supplies one, which
`named_graph_semantics` §4.3 flags as unbounded work.

### All 13 categories now wired

Every sparql10 evaluation category is in `P0_CATEGORIES`. Our failures went
**25 -> 7**, and all seven are registered with a cause.

Three more fixes, after `sort`/`cast`/`graph`:

**The corpus outranks the oracle.** The runner compared us to pyoxigraph, and
where pyoxigraph *also* differed from the `.srx` it recorded "ACCEPTED" and
failed us anyway — without ever asking whether our answer was right. It
frequently was: pyoxigraph canonicalises numeric lexical forms, so it
collapses literals `DISTINCT`/`REDUCED` must keep apart. Five cases were
being marked failures for matching the corpus.

**Boolean and dateTime have value spaces.** `"0"^^xsd:boolean` =
`"false"^^xsd:boolean`; one instant at two UTC offsets is one value. Only the
numeric lane was chosen at run time, so of six boolean and five dateTime pairs
we matched the two spelled identically.

**§17.4.3 string functions take a literal.** `regex(?val, "example\.com")`
matched `<http://example.com/uri>` because every arm compared `term_text`.
Fixed in BOTH emitters — `filter_pushdown` carries a note that which one runs
is a performance decision and must not change semantics, and here it did.

That last one caught a fixture storing its objects as URIs: `_ensure_term`
types anything that is not a `URIRef`/`BNode`/`Literal` as `'U'`, and a bare
Python `str` is none of those. It passed only because `CONTAINS` ignored term
kind.

### The seven left, with causes

| category | n | cause |
|---|---|---|
| `graph` | 3 | `GRAPH ?g {}` — a graph-scoped group with no triple pattern does not enumerate |
| `expr-ops` + `optional-filter` | 3 | computed numerics return a canonical lexical form; the corpus keeps the operand's |
| `algebra` | 2 | rows lost joining across GRAPH/UNION and OPTIONAL/UNION — **undiagnosed** |
| `regex` | 1 | XPath bracket-negation matches newline; no PostgreSQL mode pairs that with dot-excludes-newline |
| `i18n` | 1 | no Unicode normalisation of literals on the way in |

The `regex` one is diagnosed and deliberately unfixed: emulating XPath means
dropping the newline option and rewriting `.` to `[^\n]`, a change to a shared
flag mapping whose 2x2 is measured and documented — not a change to make in
passing. `algebra` is the only pair with no diagnosis; a missing row in a
multi-way join is not something to guess at, and the two differ (1→0, 2→1) so
they may not share a cause.

### The pattern worth keeping

Two of the three wins were **harness** defects, not engine defects, and both
hid working code behind a category that could not be wired. That is the same
shape as `issues/130`, and it is now the third time the answer to "why is this
category failing" was "the test could not read its own expectation".
