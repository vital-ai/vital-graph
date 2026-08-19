"""A refused query must not answer like a query that matched nothing.

`sparql_sql_space_impl` checked `cr.ok` — the COMPILE result — and never checked
`gen.ok`. A refused generation therefore fell through with `sql=None`, and the
caller received an ordinary empty result set. Observed end to end on the test
stack: the generator logged

    v2 SQL generation refused: CONTAINS(?o, 'XQ') cannot be served by the text index

while the API answered HTTP 200 with `bindings: []` and no message.

That is strictly worse than the cost the refusal avoids. A 60-second scan is
visible and can be complained about; "no results" is a plausible answer to the
question that was asked, and the caller acts on it. The refusal was built to tell
someone to use STRSTARTS, and it told them their data does not exist.

The UPDATE path had the same gap in a worse form: `if sql:` treated a refused
generation as nothing to do and fell through to the success return — a write
that never happened, reported as one (`issues/105`).

HTTP 200 with the failure in the body is correct here and is the house rule:
non-200 is for server-level errors, not domain outcomes. The defect was never the
status code, it was that the body said nothing.
"""

from __future__ import annotations

import inspect

from vitalgraph.db.sparql_sql import sparql_sql_space_impl as impl


def _source_of(name: str) -> str:
    fn = getattr(impl.SparqlSQLSpaceImpl, name, None)
    assert fn is not None, f"{name} moved; this test is now measuring nothing"
    return inspect.getsource(fn)


class TestBothPathsCheckGenerationBeforeUsingIt:
    """Structural, because the runtime cases need a million-term table to reach.

    A test that cannot reach the condition it names is the failure mode this
    whole file is about, so this asserts on the code rather than pretending.
    """

    def test_the_query_path_checks_gen_ok(self):
        src = _source_of("execute_sparql_query")
        assert "gen.ok" in src, (
            "only cr.ok was checked, so a refused generation returned empty "
            "bindings — a refusal indistinguishable from 'no matches'")

    def test_the_query_path_returns_the_reason(self):
        src = _source_of("execute_sparql_query")
        i = src.index("gen.ok")
        assert "gen.error" in src[i:i + 1200], (
            "returning success=False without the message leaves the caller "
            "knowing only that something went wrong, which is the state that "
            "sent two days into wrong hypotheses in issues/100")

    def test_the_update_path_refuses_rather_than_skipping(self):
        src = _source_of("execute_sparql_update")
        i = src.index("gen.ok")
        after = src[i:i + 400]
        assert "return False" in after, (
            "`if sql:` skipped a refused update and fell through to the success "
            "return — a write that never happened, reported as one")


class TestTheCompileCheckIsStillThere:
    """The two failures are different and both must be reported: a compile error
    is a malformed query, a generation refusal is a well-formed one this backend
    declines. Fixing the second by removing the first would trade one silence
    for another."""

    def test_compile_failure_is_still_reported(self):
        src = _source_of("execute_sparql_query")
        assert "cr.ok" in src and "cr.error" in src
