"""`fast_entity_page` must not decline silently either.

The second production diagnosis in two days ran aground on this. v0.0.58 made
`fast_entity_prop_page` log every decline at INFO — but BOTH returns in
`fast_entity_page` happen BEFORE that function is called, so a listing that
declined there produced no line at all. The absence of a `prop_sort DECLINE`
was then reasonably read as "the fast path is not declining", and the
investigation went looking for a resolve failure instead.

An unexplained decline is indistinguishable from an absent one. Every return
that costs a request its fast path has to say so.
"""

from __future__ import annotations

import logging

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

CORE = "http://vital.ai/ontology/vital-core#"
GRAPH = "http://example.org/fep/graph"
LOGGER = "vitalgraph.kg_impl.kg_backend_utils"


async def test_a_search_says_so(test_space, backend_adapter, caplog):
    """The likely production shape: a UI that only enables sorting once a
    search narrows the set makes search+sort the COMMON request, and search
    declines unconditionally."""
    with caplog.at_level(logging.INFO, logger=LOGGER):
        got = await backend_adapter.fast_entity_page(
            test_space, GRAPH, 25, 0, search="anything",
            sort_by=f"{CORE}hasName")

    assert got is None
    msgs = [r.getMessage() for r in caplog.records]
    assert any("DECLINE" in m and "search" in m for m in msgs), (
        f"a search declined without saying so; that silence is what sent the "
        f"last investigation after the wrong cause. records={msgs}")


async def test_a_non_uri_graph_says_so(test_space, backend_adapter, caplog):
    """The other silent return: it names WHICH half failed, because
    'impl is None or not graph_is_uri' has two very different causes."""
    with caplog.at_level(logging.INFO, logger=LOGGER):
        got = await backend_adapter.fast_entity_page(
            test_space, "default", 25, 0, sort_by=f"{CORE}hasName")

    assert got is None
    msgs = [r.getMessage() for r in caplog.records]
    assert any("DECLINE" in m for m in msgs), f"silent decline: {msgs}"
    assert any("impl_resolved" in m and "graph_is_uri" in m for m in msgs), (
        f"the message does not distinguish an unresolved impl from a non-URI "
        f"graph, which are different bugs with different fixes: {msgs}")


def test_no_return_in_the_gate_is_unlogged():
    """Structural: every `return None` in fast_entity_page logs first."""
    import ast
    import inspect
    from vitalgraph.kg_impl import kg_backend_utils as m

    src = inspect.getsource(m.SparqlSQLBackendAdapter.fast_entity_page)
    tree = ast.parse(src.lstrip())
    returns_none, logged = 0, 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Return):
            v = node.value
            if isinstance(v, ast.Constant) and v.value is None:
                returns_none += 1
    # every `return None` sits in a body that also logs
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            body = ast.unparse(node)
            if "return None" in body and "logger.info" in body:
                logged += 1
    assert returns_none and logged >= returns_none, (
        f"{returns_none} `return None` in fast_entity_page but only {logged} "
        f"logged branches — a decline that says nothing is invisible in a "
        f"deployment running at INFO")
