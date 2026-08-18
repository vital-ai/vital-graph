# W3C SPARQL test suite (DAWG)

Vendored from the W3C `rdf-tests` repository. Only the `sparql/` subtree is here:
`rdf/` (30 MB) is not referenced by anything in this repo, and the upstream
`reports/`, `Gemfile` and `Rakefile` are build tooling for publishing the suite,
not test data.

`LICENSE.md` is upstream's, retained because it governs redistribution — the
suite is dual-licensed per
<https://www.w3.org/Consortium/Legal/2008/04-testsuite-copyright.html>.

## Why it is committed

It used to live in `vitalgraph_sparql_sql_dev/dawg_tests/` and was gitignored, so
a clean checkout did not have it. CI runs `test_dawg_pyoxigraph.py`, which then
collected two tests and SKIPPED both — "got empty parameter set" — and the step
passed green. Conformance had never actually run in CI.

Test data that CI depends on cannot be gitignored; the absence is invisible
precisely because an empty suite passes.

## Layout

    sparql/sparql10   SPARQL 1.0 tests
    sparql/sparql11   SPARQL 1.1 tests — what `get_manifest_path` resolves against
    sparql/sparql12   SPARQL 1.2 tests

Access goes through `dawg_test_impl.dawg_manifest_parser.get_manifest_path`,
which appends `sparql/sparql11/<category>/manifest.ttl` to the root it is given.
