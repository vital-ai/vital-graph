# `sparql10/dataset` Is Wired and Green and Tests Almost Nothing

## Status: RESOLVED 2026-08-24 in `ffcd4b9` — found while scoping `named_graph_semantics` §4.2

    4 passed, 24 skipped, 4 xfailed

Of 32 tests (16 cases x 2 functions), **four run**. The category was wired as
one of the "clean, zero failures" seven in `issues/128`, and zero failures is
true — because almost nothing executes.

This matters more than an ordinary coverage gap: `dataset` is THE category that
would validate `FROM`, `FROM NAMED` and default-graph semantics, which is
exactly the work §4.2 has just been decided for. Fifteen of its sixteen queries
use `FROM`. A green category here would be actively misleading to that work.

## Two independent causes, both in the harness

### 1. Result files with relative IRIs do not parse

Six result files carry a relative IRI — `<data-g1.ttl>` in the `rs:value` of a
solution. `_parse_ttl_graph` loads without a base:

    store.load(path.read_bytes(), "text/turtle")

pyoxigraph refuses ("No scheme found in an absolute IRI"), `parse_result_file`
returns None, and the runner SKIPS. The DATA loader passes
`base_iri=f"file://{ttl_file}"`; the RESULT parser does not.

### 2. The queries themselves cannot be parsed by the oracle

`FROM <data-g1.ttl>` is a relative IRI, and `store.query` is called without a
base. pyoxigraph reports `error at 4:19: expected IRI parsing failed`, the
oracle records "cannot execute", and `test_sql_v2` then skips too — "skip for
v2 too". **So our own backend is never exercised for any of these.**

Confirmed a base fixes the parse:

    base=None                 -> error at 4:19: expected IRI parsing failed
    base='file:///tmp/x.ttl'  -> parsed OK

## Why the obvious fix is NOT the fix — measured, then reverted

Both were attempted and both were reverted, because each converts skips into
FAILURES rather than passes:

* passing `base_iri` to `store.query` broke **9** conformance tests;
* passing it to the result-file loader broke **3** — `aggregates/COUNT: no
  GROUP BY inside of GRAPH` and `bindings/VALUES inside GRAPH binding the same
  variable as the graph name`, neither of which is in this category.

A relative IRI that previously failed to parse now resolves to `file:///...`,
which does not match what the engine returns. The base has to be the one the
DAWG suite intends, not merely any base that makes the parser stop complaining.

There is also nothing convenient to anchor on: the manifest gives these cases
`data_file=None` and `named_graph_files=[]`, because the dataset is defined by
the QUERY's `FROM`, not by the manifest. The correct base is the query file's
own directory, and the executor is never given the query file's path.

## What it would take

1. Plumb the test's own directory (or an explicit base IRI) from the manifest
   parser through to both the result parser and the oracle executor.
2. Use the SAME base the DAWG suite assumes, then re-check the 12 tests that
   currently fail under a naive base — they are the evidence that the base
   choice is load-bearing rather than cosmetic.
3. Only then read the category's result as meaning anything.

## Do this BEFORE §4.2

`named_graph_semantics` §4.2 has been decided as strict SPARQL dataset
semantics, and §4.1 (`FROM`/`FROM NAMED`) has to land with it. This category is
the natural oracle for both, and today it would report success against an
implementation that ignores `FROM` entirely — which is precisely the state
§4.1 describes.

Same shape as `issues/125`: a category that could not be reached at all, and
`issues/117`, where six skips read as six pathological shapes and were two
harness defects. A skip is not a pass, and a green category is not coverage.


---

## Resolution — `ffcd4b9`

One cause, not the two originally written up: **nothing supplied a base IRI**,
and every downstream symptom followed from that.

The earlier attempt was abandoned because a naive base "broke 9 tests and then
3". That reading was wrong, and worth recording as the reason this sat open.
Those tests were not regressing — they were *running for the first time*. The
suite had no way to say "this test just started executing and does not pass";
it could only show a skip turning into a failure, which looks identical to a
break. Measuring before believing that is what unblocked it.

### What changed

| | before | after |
|---|---|---|
| `sparql10/dataset` passing | 4 | 16 |
| suite-wide skips | 50 | 29 |
| failures | 0 | 0 |

- result files (`.ttl`, `.rdf`, `.trig`) parse against their own location
- `execute_query` takes `base_iri`; both suites pass the query file's path.
  That is the only base under which a query's `<graph.ttl>` and the
  `file://{ng_file}` its named graph is loaded under resolve to the same IRI.
- `FROM` / `FROM NAMED` are dereferenced and loaded. The dataset tests declare
  their data only in the query — the manifest has no `qt:data` for them — so
  the store was empty and every one answered 0 rows while appearing to run.

### Two genuine defects it exposed, both the oracle's

`aggregates/COUNT: no GROUP BY inside of GRAPH` and `bindings/VALUES inside
GRAPH binding the same variable as the graph name` were skipping in categories
already counted clean. Both now run, and both fail the same way: pyoxigraph
does not enumerate a named graph that is **empty**, returning one row short.
The manifests are right — the aggregates one states the rule in words
("counting no results without grouping always returns a single result per named
graph"). Registered in `XFAIL_TESTS`/`XFAIL_TESTS_V2` as oracle limitations.

Worth noting for §4.2: that empty-named-graph question is precisely what the
strict-SPARQL decision turns on, and we now have two live tests pinned to it.

### The remaining skips — also fixed, in `b412371`

The first pass left 12 skips reading `pyoxigraph cannot execute this query
(skip for v2 too)` and called them "real oracle gaps, not harness ones". That
was wrong twice over. `run_single_test_sql_v2` had never been given the base
IRI the two test modules got, so it was the *same harness bug*; and even where
the oracle genuinely cannot run, the manifest's expected result was already
parsed two lines above and simply went unused. An oracle limitation was being
allowed to switch off the test of our own backend.

- the runner passes the query file as base IRI
- `FROM` / `FROM NAMED` graphs load into the space — the dataset cases carry
  no `qt:data`, so our backend had been querying an empty space
- no oracle is no longer fatal: compare straight to the manifest, which is
  stricter. The oracle is the primary comparand because it attributes a
  failure better, not because it outranks the corpus.

Skips **29 → 11**, and `pyoxigraph cannot execute` is now **zero**. What is
left is 9 `NegativeSyntax` cases that belong to the syntax suite, one empty
parameter set, and one `ENCODE_FOR_URI` parse gap.

### What that measured: 15 real failures in our pipeline

18 more tests run and 15 fail. Not new breakage — the first measurement of
code nothing was checking. Every one names a graph by a file-relative IRI
(`FROM <data.ttl>`, `GRAPH <exists02.ttl>`), and our pipeline has no base to
resolve it against: `execute_query_via_v2_pipeline` hands the Jena sidecar no
base at all. The symptom is bimodal and confirms the diagnosis — far too many
rows where the `FROM` dataset restriction is ignored (0 → 8, 12 → 24), zero
where the unresolved name matches no loaded graph.

Recorded in `XFAIL_SQL_V2_EXEC`, which had been kept empty for exactly this.
**Deliberately not worked around in the harness**: deriving the dataset from
the query's `FROM` clause inside the test fixture would turn all 15 green and
leave the engine exactly as unable to do it.

These 15 are the concrete work list for `named_graph_semantics` §4.1, and they
now fail loudly until it lands.

### The recurring lesson, third instance

`csv-tsv-res`/`json-res` (2026-08-16), `XFAIL_TESTS_V2` deferring `test_sql_v2`
(same day), and now this. Each time: a swallowed error became a skip, the skip
counted as green, and the gap survived because nobody measured what was
actually executing. `parse_result_file` returning `None` on failure is the
shared mechanism and remains in place.
