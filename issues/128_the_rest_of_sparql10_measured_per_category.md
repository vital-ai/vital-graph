# The Rest of sparql10, Measured Per Category

## Status: CLOSED 2026-08-25 — all 13 categories wired, our failures 25 -> 0.
## Measurement done 2026-08-23; the work it scoped is complete.

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

| category | n | cause | state |
|---|---|---|---|
| `graph` | 3 | `GRAPH {}` did not enumerate graphs | **fixed** |
| `expr-ops` + `optional-filter` | 3 | *misfiled* — see below | **fixed** |
| `regex` | 1 | the 2x2 was a 2x2x1 — see below | **fixed** |
| `i18n` | 1 | *misfiled* — sidecar IRI normalisation, `issues/132` | filed |

`algebra` is **fixed** — see below. The `regex` one is diagnosed and
deliberately unfixed: emulating XPath means
dropping the newline option and rewriting `.` to `[^\n]`, a change to a shared
flag mapping whose 2x2 is measured and documented — not a change to make in
passing.

### The pattern worth keeping

Two of the three wins were **harness** defects, not engine defects, and both
hid working code behind a category that could not be wired. That is the same
shape as `issues/130`, and it is now the third time the answer to "why is this
category failing" was "the test could not read its own expectation".


---

## `algebra` — one flag carrying two meanings

Both cases lost rows joining a UNION whose branches bind **different variable
sets**:

    { ?a ?p 1  { ?p a ?y } UNION { ?a ?z ?p } }

The first branch binds no `?a`. Its rows reached the join with `?a` NULL, met
a bare equijoin, and died on `NULL = x` — so the query answered with the
second branch alone. SPARQL joins COMPATIBLE mappings, and unbound is
compatible with anything.

Two defects, one behind the other.

**The gate.** `emit_join` applied the compatible-mapping disjuncts when
`right_is_table or left_is_table or is_left` — VALUES joins and LEFT JOINs.
That is two of the three ways a variable comes out unbound, and it misses the
third, which the `_all_required` helper immediately above names explicitly:
*a UNION branch that omits it*. The knowledge was already in the file; the
gate never asked. It now asks `_all_required` rather than widening to all
inner joins, so BGP-to-BGP keeps its equijoin — that is where the measured
6,219 ms → 4.6 ms lives.

**The flag.** Fixing the gate changed nothing, which is the more interesting
half. `emit_union` computed

    ti = all(i.has_term_identity() for i in (l_info, r_info) if i)

and passed it as `uuid_materialized`. The `if i` deliberately skips a branch
that does not bind the variable — correct for TERM IDENTITY, which is what
`ti` is about. But `uuid_materialized` is read by `_always_bound` as *"every
row of this block bound this variable"*, which is a claim about BOUNDNESS, and
for a UNION that holds only when every branch binds it. So the flag asserted
always-bound for a variable one branch never binds, and the disjuncts were
dropped again one level down.

The fix records the missing half in `partial`, a field that already existed
on `ColumnInfo` with exactly the right definition — *"whether this binding may
be NULL (from OPTIONAL/UNION)"* — and was never set or read by anything.
`_always_bound` now returns False when it is set, before any identity evidence
is consulted.

### The fix I nearly shipped instead

My first version carried the term identity on `from_triple` and narrowed
`uuid_materialized`. Every test passed. It was still wrong: `from_triple` is
read in eight other places — `emit_distinct`, `emit_group` (×3), `emit_minus`,
`emit_context`, and join lane selection — so setting it on union outputs
changes DISTINCT, GROUP and MINUS behaviour to fix a join condition.

The comment on `uuid_materialized` says so directly, and I had read it:

> Kept separate from `from_triple` on purpose: that flag also drives
> OPTIONAL/MINUS boundness reasoning, and widening it there is what made MINUS
> a silent no-op (issue 026).

What caught it was not the test suite, which was green. It was the perf run's
skip count moving 1 → 2 on a probe-timeout test — a signal with no failure
attached — and then asking what else reads the flag before trusting it.

### Two lessons, both about sequence

The gate fix looked obviously right and changed nothing; only printing what
`_always_bound` actually decided exposed the flag overriding it one level
down. And a green suite did not mean the second fix was safe — the blast
radius of a shared flag is not something tests in the changed area can show
you.


---

## The last six, and two causes filed wrong

**`expr-ops` + `optional-filter` were not about lexical form.** That reason was
inferred from a comparator message mentioning `2E+1` and `__NUMERIC__`, and
none of the three cases involved a lexical form at all. Measuring each one
directly gave three unrelated defects:

- **unary plus did not exist.** The sidecar emits `unaryplus`; nothing handled
  it, so `(+?v AS ?result)` bound nothing.
- **unary minus dropped the datatype.** `-("3"^^xsd:float)` came back as a
  plain `-3`. XSD gives the unary signs the operand's type; neither matched in
  `infer_expr_type` so both fell to the default. They now sit with `abs`,
  which had the rule already.
- **a FILTER at the top of an OPTIONAL group belongs to the LEFT JOIN.**
  §18.2.2.3: where the OPTIONAL's pattern translates to `Filter(F, P)`, the
  result is `LeftJoin(G, P, F)`. Jena lifts it for the plain form; for a
  nested group it does not, so `OPTIONAL { { P FILTER F } }` arrived as
  `LeftJoin(A, Filter(F, P))` and F was emitted against the right side alone,
  where a left-side variable is unresolvable. It compiled to NULL, the filter
  never held, and no book got a price. **The engine logged the unresolvable
  variable on every run**; nothing ever acted on the log.

**`graph` — enumeration.** `GRAPH ?g {}` and `GRAPH <uri> {}` were answered
from Jena's unit table, which binds nothing and matches unconditionally: `?g`
came back missing, and a graph that does not exist still produced a row. Now
built as `?s ?p ?o` scoped to the graph, projected to the context and
DISTINCT'd — so it inherits the existing scoping, default-graph exclusion and
dataset rules instead of a second path that would have to restate them.

The URI form needs the same projection: `GRAPH <uri> {}` asks whether the
graph EXISTS, one solution and not one per quad. Projecting nothing left
DISTINCT with no column to collapse and a two-quad graph answered twice —
caught by `graph-exist`, which had been passing.

### Filed-cause accuracy

Of the seven gaps registered on 2026-08-24, **two of five reasons were wrong**
(`expr-ops`/`optional-filter` as lexical form; `algebra` as undiagnosed but
plausibly shared). Both were written from failure messages rather than from
running the case. The registry is more useful than no registry, but a reason
in it is a hypothesis until someone measures it.


---

## `regex` — the documented 2x2 was missing an axis

`regex_flags` mapped XPath's `s` and `m` onto PostgreSQL's four
newline-sensitivity options as a clean 2x2. There is a third axis and **no
PostgreSQL option covers it**: every one of those letters ties bracket
negation to `.`.

| option | `.` and `[^x]` |
|---|---|
| `p`, `n` | both **exclude** the newline |
| `s`, `w` | both **admit** it |

XPath does not tie them — `.` excludes the newline unless `s`, while `[^x]` is
a set complement and always admits it. SPARQL's default is none of the four:

    'a\nc' ~ '(?p)a[^b]c'   ->  false   (what we emitted)
    'a\nc' ~ '(?s)a[^b]c'   ->  true    (XPath, and the corpus)

So the dot moves into the PATTERN — `dot_to_non_newline` rewrites each
unescaped `.` outside a bracket to `[^\n]` — and the option is left to place
only the anchors (`s` normally, `w` for `m`). All four XPath combinations,
exactly.

A pattern arriving at RUN TIME has no text to rewrite, so `apply_to_pattern`
keeps `p`/`n`: `.` right, bracket negation wrong. Deliberate — there is no
third option there and `.` is the commoner case.

**And a duplication.** `filter_pushdown` was calling `translate_classes` and
splicing the options itself instead of using `apply_to_literal` — the same
divergence `regex_flags` exists to prevent, one level below the flag mapping it
already shared. It is precisely why the dot rewrite would have landed in one
emitter and been missed in the other. It now calls the shared function.

## Closing count

Wired: **all 13** sparql10 evaluation categories, plus the 11 UPDATE
categories and the syntax/protocol suites — and `test_dawg_coverage` asserts
every corpus category is either run or declined in writing, so this cannot
quietly regrow.

Our failures across the sweep: **25 -> 1**, and the one left is not ours.
`i18n/normalization-02` fails upstream of the SQL pipeline, in the sidecar's
PNAME expansion (`issues/132`).

### Filed-cause accuracy, final tally

Of the seven gaps registered on 2026-08-24, **three of five reasons were
wrong**: `expr-ops`/`optional-filter` (filed as lexical form, was three
unrelated defects), `algebra` (filed as undiagnosed-but-maybe-shared, was one
cause behind another), and `i18n` (filed as Unicode normalisation of literals —
the test is about IRIs, about dot-segments, and about NOT normalising; that
reason was written from the category name).

Every wrong reason was written from a failure message or a category name
instead of from running the case. The registry was still worth having — it
kept the work visible and the suite honest — but a reason in it is a
hypothesis, and three of five did not survive contact.


---

## Closed 2026-08-25

Every sparql10 evaluation category is wired. `XFAIL_SQL_V2_EXEC`,
`XFAIL_SQL_V2_ACCEPTED` and `KNOWN_FAILURES` are all empty: **no case in the
suite leaves our backend unmeasured.**

Our failures across the sweep went **25 -> 0**. The last one,
`i18n/normalization-02`, was not ours — it was the sidecar removing RFC 3986
dot-segments from absolute IRIs, fixed in `issues/132`.

### What the sweep actually cost, versus what it looked like

Of the 25, roughly half were not engine defects at all:

| | |
|---|---|
| `sort` (10) | HARNESS — the RDF/XML and TriG parsers never checked for the `rs:` result-set vocabulary, so `.rdf` expectations were compared as raw triples. **Our sort implementation needed no change.** |
| `graph` (1 of 5) | HARNESS — the runner declared `default_graph` only when named graphs existed |
| `i18n` (1) | SIDECAR — `issues/132` |
| the rest | genuine engine gaps: cast/datatype, boolean and dateTime value spaces, literal-only string functions, UNION join compatibility, unary signs, OPTIONAL's nested FILTER, graph enumeration, XPath bracket negation |

Three separate times the answer to "why is this category failing" was **"the
test could not read its own expectation"** — and each time it had been hiding
working code behind a category that could not be wired.

### Filed-cause accuracy

Of the seven gaps registered on 2026-08-24 with a diagnosed reason, **three
were wrong**: `expr-ops`/`optional-filter` (filed as lexical form, was three
unrelated defects), `algebra` (filed as undiagnosed-but-plausibly-shared, was
one cause behind another), and `i18n` (filed as Unicode normalisation of
literals; it is about IRIs, dot-segments, and NOT normalising).

Every wrong reason was written from a failure message or a category name rather
than from running the case. The registry earned its keep — it kept the work
visible and the suite honest — but a reason in it is a hypothesis, and three of
five did not survive contact.