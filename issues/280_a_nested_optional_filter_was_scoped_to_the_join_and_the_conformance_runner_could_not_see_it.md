# 280 — A nested OPTIONAL filter was scoped to the join, and the conformance runner could not see it

## Status: ENGINE FIXED IN CODE 2026-10-19 (not yet released). Runner gap OPEN: 25 cases to triage.

**Related:** `c7caf819` (2026-08-25, which introduced the wrong scoping),
`issues/128` (the sparql10 categories wired then).

## What happened

E2E went red on `3339071b` (2026-10-19) with nothing related changed: two DAWG
cases on `sparql10/optional-filter`, `dawg-optional-filter-005`. pyoxigraph
0.5.12 had been published on 2026-10-18 at 20:00 UTC. CI installed it because
`pyproject.toml` asked for `pyoxigraph>=0.4.11`, and pyoxigraph is the
conformance suite's oracle.

```
PREFIX dc: <http://purl.org/dc/elements/1.1/>  PREFIX x: <http://example.org/ns#>
SELECT ?title ?price
WHERE { ?book dc:title ?title .
        OPTIONAL { { ?book x:price ?price . FILTER (?title = "TITLE 2") } } }
```

| | TITLE 2's price |
|---|---|
| SPARQL 1.1, approved `.srx` (`-not-simplified`) | **unbound** |
| unapproved variant (`-simplified`, commented out of `mf:entries`) | 20 |
| pyoxigraph 0.5.11 | 20 |
| pyoxigraph 0.5.12 | unbound |
| VitalGraph, 2026-08-25 → 2026-10-19 | 20 |

The OPTIONAL's group translates to Join(Z, Filter(F, A)), not Filter(F, A),
because the simplification step that would drop the Z runs after translation.
So F is scoped to the inner group, where `?title` is unbound, and F is an error.
The OPTIONAL then adds nothing. The filter only becomes the LEFT JOIN's
condition when it sits directly in the OPTIONAL's group (`OPTIONAL { P FILTER F }`),
which Jena already hands us as the join's `exprs`.

## Cause — two

1. **The engine.** `c7caf819` added a lift in `collect._collect_left_join`
   that moved a nested group's filter into the join condition whenever it named
   a variable bound only on the left. It treated the correct answer ("no price
   for any book") as a bug. It matched pyoxigraph 0.5.11, which had the same
   bug.
2. **The runner.** `run_single_test_sql_v2` compared our result with
   pyoxigraph's and returned PASS on a match, without consulting the `.srx`.
   A mistake the oracle shared with us was invisible. Both 005 variants, which
   expect opposite answers on the same query and data, passed from August until
   pyoxigraph fixed its half. The older runner path even computed the `.srx`
   comparison and ignored it.

## Fixed (code)

* `collect._collect_left_join`: the nested-filter lift is removed. The comment
  records the scoping rule and this history.
* `test_dawg_sql_v2.py`: the stale oracle entry for `-not-simplified` is
  removed. `-simplified` is skipped by name (`UNAPPROVED_TESTS`), because the
  manifest comments it out of `mf:entries` and no engine can pass both
  variants. It is the only commented-out entry across the wired manifests.
* `pyproject.toml`: `pyoxigraph==0.5.12`, pinned. An oracle upgrade changes test
  results with no change in this repo, so upgrades come as a Dependabot PR,
  judged by that PR's DAWG run.

## Verification

On the vg test stack, the same stack and env as CI's E2E job, with pyoxigraph
0.5.12: `test_dawg_syntax`, `test_dawg_sql_v2` and `test_dawg_update_sql_v2`
all pass. `-not-simplified` passes on both our engine and the oracle, and
`-simplified` is skipped in both. With the lift restored, `-not-simplified`
fails again.

## Open: the runner still trusts the oracle on a match

Cause 2 is not fixed. Making the runner require the `.srx` on an oracle match
(both `run_single_test_sql_v2` paths; the older one computes the comparison and
discards it) turns **25 passing cases into failures**. In each, our result
equals pyoxigraph's and both differ from the corpus, 2026-10-19:

* `sparql10/construct/dawg-construct-identity`
* `sparql10/construct/dawg-construct-optional`
* `sparql10/construct/dawg-construct-reification-1`
* `sparql10/construct/dawg-construct-reification-2`
* `sparql10/construct/dawg-construct-subgraph`
* `sparql10/graph/graph-not-exist`
* `sparql10/graph/graph-optional`
* `sparql10/graph/graph-variable-scope`
* `sparql10/reduced/SELECT REDUCED *`
* `sparql10/reduced/SELECT REDUCED ?x with strings`
* `aggregates/COUNT: no GROUP BY inside of GRAPH`
* `negation/outer GRAPH operator does not affect MINUS disjointness`
* `bindings/VALUES inside GRAPH binding the same variable as the graph name`
* `property-path/* with end being a constant on the empty dataset`
* `property-path/* with start being a constant on the empty dataset`
* `property-path/? with end being a constant on the empty dataset`
* `property-path/? with start being a constant on the empty dataset`
* `subquery/sq12 - Subquery in CONSTRUCT with built-ins`
* `subquery/sq14 - limit by resource`
* `cast/xsd:boolean cast`
* `cast/xsd:decimal cast`
* `cast/xsd:double cast`
* `cast/xsd:float cast`
* `cast/xsd:integer cast`
* `cast/xsd:string cast`

These fall into families, and some are probably comparator or corpus-age
artefacts rather than engine bugs:

* CONSTRUCT bnode isomorphism (5);
* RDF 1.0 plain literal versus `xsd:string` in graph results;
* cast lexical forms (8);
* REDUCED;
* row-count differences: property paths on the empty dataset, GRAPH scoping,
  subqueries, COUNT inside GRAPH.

Each of them can hide a bug the way 005 did. Taken out of this fix rather than
landing as 25 xfails at once, which would bury the signal the file is careful
to protect. 
### Triage, 2026-10-19

Each case was dumped with the query, the `.srx`, pyoxigraph's rows and ours.
The dump is a throwaway pytest in `tests/conformance` that reuses the
runner's loader and comparator. 15 are real engine bugs that pyoxigraph
shares. 10 are artefacts of our comparator or result parser.

| group | cases | verdict | detail |
|---|---|---|---|
| zero-length path to a constant on the empty dataset | 4 (`*`/`?`, start/end) | **ENGINE BUG** | `?s :p* :o` must return `?s = :o` even when `:o` is in no triple (SPARQL 1.1 ZeroLengthPath with a constant endpoint). We return nothing. |
| `GRAPH ?g { P }` evaluates P with `?g` already bound | 5 (`graph-variable-scope`, `graph-optional`, VALUES / MINUS / `COUNT` inside GRAPH) | **ENGINE BUG** | SPARQL 1.1 evaluates P in each named graph without `?g`, then joins `?g`. Hence `FILTER(BOUND(?g))` inside is false (expected 0 rows, we return 2), an inner binding of `?g` must agree with the graph name, and `count(*)` gives 0 for a graph with no matches. |
| a stored `xsd:boolean` is returned in canonical form | 6 (every `cast/*`) | **ENGINE BUG** | `"0"^^xsd:boolean` is stored as `0` and read back as `false`. A literal's identity includes its lexical form. The term table is right, so the read side canonicalises. |
| graph results: datatype IRI in `<>` from the result parser; `xsd:string` vs plain literal | 7 (5 CONSTRUCT, `sq12`, `sq14`) | ARTEFACT | The `.srx`/`.ttl` graph parser keeps angle brackets (`'<…#integer>'` against `'…#integer'`), and RDF 1.1 makes `"x"^^xsd:string` and `"x"` the same literal. With both normalised, the graphs are isomorphic. |
| REDUCED | 2 | ARTEFACT | REDUCED may return any multiplicity between DISTINCT and ALL. A strict multiset comparison is wrong. |
| `graph-not-exist` | 1 | ARTEFACT | A Turtle result set with no variables and no solutions is parsed as a one-triple graph, so the comparison is triples against rows. Both engines correctly return nothing. |

Order of work:

1. ~~Fix the three artefacts in the comparator and parser (10 cases).~~ DONE
   2026-10-19:
   * `dawg_srx_parser`: graph results take the datatype's `.value`, not
     `str()` (which is `<iri>`), so `xsd:string` folds into the plain literal
     and no datatype keeps its brackets. A bare `rs:ResultSet` parses as an
     empty result set, not a graph.
   * `dawg_result_comparator.compare_results(..., reduced=True)`: the same
     distinct rows, none more often than in the full result. The runner sends
     a REDUCED query straight to the `.srx` with it, since two REDUCED answers
     can differ and both be right. The oracle baseline passes it too.
   * Verified: compared directly with the `.srx`, the 10 now match and the 15
     engine bugs still do not. All four DAWG suites pass. 7 unit tests in
     `tests/unit/sparql_sql/test_dawg_result_parsers.py` fail on the old code.
2. Fix the engine bugs one group at a time:
   * ~~boolean lexical form (6)~~ DONE 2026-10-19. `sql_type_binding._binding_from_companions`
     rewrote every xsd:boolean `"0"`/`"1"` to `"false"`/`"true"` on output. The
     rewrite is removed. Computed booleans are canonical from the SQL already
     (the `cast/*` cases' computed column still matches). The 6 cases now match
     their `.srx`, and all four DAWG suites, the unit suite and the integration
     suite pass. Production stores only `true`/`false` in all 11 spaces (read-only
     check), so nothing there changes. `tests/unit/sparql_sql/test_stored_boolean_keeps_its_lexical_form.py`.
   * zero-length constant (4);
   * `GRAPH ?g` scoping (5).
3. Then land the runner check. Any case still failing at that point is
   recorded individually with its reason.

Production relevance, roughly: `GRAPH ?g` patterns with inner FILTER /
OPTIONAL / VALUES / aggregates on `?g` are unusual in VitalGraph's generated
queries. Zero-length paths against an absent constant are rare. Booleans
written as `0`/`1` are rare (VitalSigns writes `true`/`false`).
