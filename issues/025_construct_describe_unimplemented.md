# CONSTRUCT and DESCRIBE are unimplemented — they silently execute as SELECT and return bindings

## Status: FIXED (2026-08-04)

Both stages done. Stage 1 (fail closed) landed with issue 024; stage 2
implements the forms and lifts the restriction.

### Implementation

`vitalgraph/db/sparql_sql/construct.py` — template instantiation per §16.2,
kept free of database access so the rules are testable directly:

- each solution fills the template once;
- a triple with an unbound position is **skipped, and the rest of that
  solution's triples are kept**. This issue said "skip rows leaving any
  template position unbound", which is wrong — §16.2 skips the *triple*, and
  skipping the row would drop valid output;
- template blank nodes are freshly allocated per solution;
- illegal triples (literal subject, non-IRI predicate) are skipped;
- the result is deduplicated — CONSTRUCT returns a graph, not a bag.

`_describe_triples` in the space impl resolves targets, then fetches their
triples in one VALUES-constrained SELECT.

**DESCRIBE strategy (§16.4 leaves this implementation-defined):** every triple
in the space with the target as its *subject* — a forward concise bounded
description, without recursive blank-node expansion. Chosen because it is
predictable and bounded; symmetric or recursive CBD can return unboundedly more
of the graph for a well-connected node. Stated here because the issue required
the choice to be documented.

Both forms return triples under the `triples` key and an empty `bindings`, and
`SPARQLQueryResponse.triples` was retyped from `List[Dict[str, str]]` to
`List[Dict[str, Any]]` — terms are nested SPARQL JSON objects, not strings, and
the old annotation would have rejected them.

The endpoint still refuses to present bindings as triples: if the backend
returns no `triples` key it errors rather than falling back.

### Conformance gated the harness, not the code — now fixed

Adding `construct` to `P0_CATEGORIES` initially proved nothing.
`dawg_sql_v2_executor` carried its **own** CONSTRUCT instantiation, so the DAWG
tests validated a copy living in the test harness while
`vitalgraph/db/sparql_sql/construct.py` went untested — the same facade issue
023 found on the query side.

The harness now delegates to the production instantiator and its copy is
deleted. Verified by breaking production dedup and confirming the DAWG tests
fail; with the copy in place they passed regardless.

### Verification

- 23 unit tests on the §16.2 rules — several are invisible end-to-end (a shared
  blank node across solutions, a skipped partial triple) because the output
  still looks plausible.
- 12 integration tests against the backend, using templates that are **not**
  echoes of the WHERE variables, which is what kept the defect hidden.
- 8 DAWG `construct` conformance tests, now genuinely gating production code.
- `tests/api` 507 passed against a rebuilt stack.

The 024 tests that asserted these forms were rejected are flipped to shape
assertions, as this issue anticipated. Both prologue variants remain
parametrised so the dispatch stays keyed on the parsed form.

## Severity

**Silent wrong results, no error.** A `CONSTRUCT` or `DESCRIBE` query is
accepted, runs, and returns rows. The rows are the WHERE-pattern bindings. No
part of the pipeline ever builds the triples the query asked for, and nothing
anywhere reports that the request was not honoured.

This is a missing feature rather than a bug in a code path, but it presents as
a correctness defect because the failure is silent — a caller gets a `200` and
data-shaped output for a query whose semantics were discarded.

## Summary

The SPARQL SQL backend implements exactly two query forms: `SELECT` and `ASK`
(the latter as a plain row-returning SELECT, which is why counting bindings
answers it). `CONSTRUCT` and `DESCRIBE` fall through the same machinery and
emit the WHERE pattern, with the construct template or describe targets
dropped.

The parse layer does its part correctly. The sidecar extracts both:

- `vitalgraph-jena-sidecar/.../util/QueryMetadataExtractor.java:102` —
  `meta.put("constructTemplate", template)`
- `.../QueryMetadataExtractor.java:120` — `meta.put("describeNodes", describeNodes)`

and the Python mapper faithfully carries them into `ParsedQueryMeta`:

- `vitalgraph/db/jena_sparql/jena_ast_mapper.py:114-123` — builds
  `construct_template` as `List[TriplePattern]` and `describe_nodes` as
  `List[RDFNode]`
- `vitalgraph/db/jena_sparql/jena_types.py:446-447` — both fields on
  `ParsedQueryMeta`

Then nothing reads them. `vitalgraph/db/sparql_sql/generator.py` touches
`meta.base_uri` and `meta.project_vars` and no other metadata; it consults
neither `construct_template`, `describe_nodes`, nor `query_type`. The data is
parsed, mapped, typed, and discarded one layer short of use.

## What actually happens

`CONSTRUCT { ?s ?p ?o } WHERE { GRAPH <g> { ?s ?p ?o } }` compiles to the SQL
for the WHERE pattern alone. The result is SPARQL JSON bindings for `?s ?p ?o`
— which for this particular template looks deceptively close to correct, since
the projection happens to match the template shape.

Any template that is not a verbatim echo of the WHERE variables diverges
without warning: constant predicates in the template, `BIND`-derived terms,
blank-node constructs, or a template projecting a subset or reordering of the
pattern all produce bindings that do not correspond to the requested triples.
`DESCRIBE <uri>` likewise returns whatever the surrounding pattern binds rather
than the concise bounded description of the node.

## Interaction with 024

`issues/024_query_form_detected_by_string_prefix_not_parser.md` covers a
separate defect in the REST layer: the query form is detected by
`query.strip().upper().startswith(...)`, so any query with a `PREFIX`/`BASE`
prologue misroutes. The two interact in a way worth stating explicitly, because
it makes the obvious fix for 024 wrong:

- Today, a **prologued** CONSTRUCT misroutes to the SELECT branch and its
  bindings land in `results`.
- A **bare** CONSTRUCT routes to the CONSTRUCT branch and the same bindings
  land in the `triples` field.

The second is worse. It labels WHERE bindings as RDF triples, which is a claim
the response has no basis to make and which a client cannot distinguish from a
real result. So fixing 024's dispatch in isolation — routing correctly on the
parsed `query_type` — would take every CONSTRUCT/DESCRIBE query from
accidentally-mislabelled to confidently-mislabelled.

**024's fix must therefore raise on these two forms rather than route them.**
That is recorded as step 3 of 024's suggested fix. This issue tracks lifting
that restriction.

## Suggested fix

Two stages, in order.

**1. Fail closed (belongs to 024, do first).** Reject `CONSTRUCT` and
`DESCRIBE` at `vitalgraph/endpoint/sparql_query_endpoint.py` with an explicit
not-supported error, dispatching on the parsed `CompileResult.meta.query_type`.
Cheap, and it converts a silent wrong answer into a legible one.

**2. Implement the forms.** `construct_template` and `describe_nodes` are
already in hand at `generator.py` via `compile_result.meta` — the work is
downstream of parsing, not in it.

- **CONSTRUCT** — execute the WHERE pattern as today, then instantiate the
  template per solution row: substitute bound variables into each
  `TriplePattern`, skip rows leaving any template position unbound, allocate
  fresh blank nodes per row for template bnodes, and deduplicate the resulting
  triple set (CONSTRUCT returns a graph, not a bag).
- **DESCRIBE** — resolve `describe_nodes` to concrete URIs (they may be
  variables bound by the WHERE clause, per `QueryMetadataExtractor.java:117`),
  then emit each subject's triples. Pick and document a description strategy;
  symmetric concise bounded description is the common default, but any choice
  is conformant as long as it is stated.
- Return triples in a shape distinct from bindings so the REST layer's
  `triples` field carries actual triples, and only then let 024's dispatch
  route these forms instead of raising.

## Regression tests to add

- `CONSTRUCT` with a template that is **not** an echo of the WHERE variables —
  constant predicate, reordered terms, subset projection — asserting the
  emitted triples match the template and not the bindings.
- `CONSTRUCT` producing duplicate triples across solutions, asserting
  deduplication.
- `CONSTRUCT` with a blank node in the template, asserting per-row bnode
  allocation rather than one shared bnode.
- `CONSTRUCT` where a template variable is unbound in some solutions, asserting
  those rows are skipped rather than emitting partial triples.
- `DESCRIBE <uri>` and `DESCRIBE ?var WHERE { … }`, asserting the documented
  description strategy.
- Until stage 2 lands: both forms return an explicit not-supported error, bare
  and prologued. These are the tests listed in 024 and should move here when
  they flip from error-assertions to shape-assertions.

## Related

- `issues/024_query_form_detected_by_string_prefix_not_parser.md` — the REST
  dispatch defect that currently masks this one; its fix must fail closed on
  these forms. Split out from 024's Impact section.
- `issues/023_values_clause_ignored_in_sparql_update.md` — same shape at the
  update layer: a parsed construct is dropped and the operation quietly means
  something other than what was asked.
