"""A failed batched entity-graph query must raise, not return an empty dict.

`execute_sparql_query` reports failure in its RETURN VALUE --
`{'results': {'bindings': []}, 'success': False, 'error': ...}` -- rather than
by raising. `issues/215` fixed one reader (`_extract_bindings`) to notice that;
`GraphObjectRetriever.get_entity_graphs_as_objects` was the other reader and
kept treating a failed query as a page with no entity graphs.

WHY THAT WAS WORSE THAN IT SOUNDS. The caller in `list_entities_with_graph`
distinguishes `None` (batched fetch raised -> fall back to per-entity retrieval)
from a dict (batched fetch worked -> use it). Returning `{}` is a dict, so the
fallback never ran, and the loop that copies graphs out does `if objs:` -- every
URI silently skipped. The endpoint then answered HTTP 200 with a correct
`total_count` and no entity graphs at all, carrying no indication of failure.

MEASURED IN PRODUCTION 2026-09-24: a copy of 500 entities at 10-way concurrency
saturated the app's asyncpg pool (`acquire timed out: size=30 idle=0`). 113
entity-graph queries failed; exactly 113 of the 500 entities were missing from
the target afterwards, while every request returned success and the job recorded
all 500 as copied.
"""

import pytest

from vitalgraph.kg_impl.kg_graph_retrieval_utils import GraphObjectRetriever
from vitalgraph.utils.db_retry import SparqlQueryFailed

SPACE, GRAPH = "s", "urn:g"
URIS = ["urn:e:1", "urn:e:2"]


class _Backend:
    """Backend stub returning whatever `execute_sparql_query` is told to."""

    def __init__(self, result):
        self._result = result

    async def execute_sparql_query(self, space_id, query):
        return self._result


FAILED = {"results": {"bindings": []}, "success": False,
          "error": "canceling statement due to lock timeout"}
FAILED_NO_MESSAGE = {"results": {"bindings": []}, "success": False, "error": ""}
EMPTY_OK = {"results": {"bindings": []}, "success": True}


@pytest.mark.asyncio
async def test_failed_query_raises():
    r = GraphObjectRetriever(_Backend(FAILED))
    with pytest.raises(SparqlQueryFailed):
        await r.get_entity_graphs_as_objects(SPACE, GRAPH, URIS)


@pytest.mark.asyncio
async def test_failed_query_with_no_error_text_still_raises():
    """The pool-timeout exception stringifies to '' — the log line read
    `failed: ` with nothing after it. Emptiness of the message must not make
    the failure look like a success."""
    r = GraphObjectRetriever(_Backend(FAILED_NO_MESSAGE))
    with pytest.raises(SparqlQueryFailed):
        await r.get_entity_graphs_as_objects(SPACE, GRAPH, URIS)


@pytest.mark.asyncio
async def test_genuinely_empty_result_still_returns_empty():
    """A successful query over a page with no graphs is NOT an error."""
    r = GraphObjectRetriever(_Backend(EMPTY_OK))
    assert await r.get_entity_graphs_as_objects(SPACE, GRAPH, URIS) == {}


@pytest.mark.asyncio
async def test_no_uris_is_empty_without_querying():
    class _Explode:
        async def execute_sparql_query(self, *a, **k):
            raise AssertionError("should not query for an empty URI list")
    r = GraphObjectRetriever(_Explode())
    assert await r.get_entity_graphs_as_objects(SPACE, GRAPH, []) == {}
