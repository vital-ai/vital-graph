"""Two concurrent creates of one entity: exactly one is accepted.

Entity create checked "does it exist?" and then stored, with nothing between
the two. Two clients that each read not-found and created the same entity at
once were both accepted, and since the timestamps are stamped per request the
entity ended with two values of each -- which the graph read cannot build, so
the entity was missing from every graph read. `create_objects_atomic` takes the
entity lock, re-checks and writes in one transaction.

The negative control turns the atomic path off and must show the race, so the
first test cannot pass merely because the window was never hit.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from vitalgraph.db.sparql_sql.space_names import space_prefix

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

G = "urn:inttest:concurrent-create:g"
CREATED_AT = "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime"
MODIFIED_AT = "http://vital.ai/ontology/vital#hasObjectModificationDateTime"
N = 10


def _entity_graph(uri: str, frame_uri: str | None = None):
    from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
    from ai_haley_kg_domain.model.KGEntity import KGEntity
    from ai_haley_kg_domain.model.KGFrame import KGFrame
    e = KGEntity(); e.URI = uri; e.name = "concurrent create"
    f = KGFrame(); f.URI = frame_uri or f"{uri}:frame:0"
    ed = Edge_hasEntityKGFrame(); ed.URI = f"{uri}:edge:{uuid.uuid4().hex[:6]}"
    ed.edgeSource = uri; ed.edgeDestination = str(f.URI)
    return [e, f, ed]


async def _create(adapter, space, uri, frame_uri=None):
    from vitalgraph.kg_impl.kgentity_create_impl import (
        KGEntityCreateProcessor, OperationMode)
    # A fresh object graph per call: each request is stamped with its own time.
    return await KGEntityCreateProcessor(adapter).create_or_update_entities(
        space, G, _entity_graph(uri, frame_uri), OperationMode.CREATE)


async def _values(pg_conn, space, uri, predicate) -> int:
    p = space_prefix(space)
    return await pg_conn.fetchval(
        f"SELECT count(*) FROM {p}_rdf_quad q "
        f"JOIN {p}_term s ON s.term_uuid = q.subject_uuid "
        f"JOIN {p}_term pr ON pr.term_uuid = q.predicate_uuid "
        f"WHERE s.term_text = $1 AND pr.term_text = $2", uri, predicate)


async def _race(adapter, space, uris):
    """Two creates per URI, all at once. Returns {uri: [status, status]}."""
    results = await asyncio.gather(*[_create(adapter, space, u) for u in uris for _ in (0, 1)])
    out = {}
    for i, u in enumerate(uris):
        out[u] = sorted(str(getattr(r.status, "value", r.status))
                        for r in results[2 * i:2 * i + 2])
    return out


async def test_two_concurrent_creates_one_is_refused(make_space, backend_adapter, pg_conn):
    space = await make_space()
    uris = [f"urn:inttest:cc:{uuid.uuid4().hex[:8]}" for _ in range(N)]
    statuses = await _race(backend_adapter, space, uris)
    for u in uris:
        assert statuses[u] == ["already_exists", "created"], (u, statuses[u])
        assert await _values(pg_conn, space, u, CREATED_AT) == 1
        assert await _values(pg_conn, space, u, MODIFIED_AT) == 1
    # And the entity reads as a graph: entity, frame and edge.
    graph = await backend_adapter.retriever.get_entity_graph_as_objects(space, G, uris[0])
    assert uris[0] in {str(o.URI) for o in graph}
    assert len(graph) == 3


async def test_a_sub_object_clash_is_refused_under_the_lock(
        make_space, backend_adapter, pg_conn):
    """The re-check covers every URI in the request, not only the entity."""
    space = await make_space()
    a, b = (f"urn:inttest:cc:{uuid.uuid4().hex[:8]}" for _ in range(2))
    shared = f"{a}:frame:0"
    assert str((await _create(backend_adapter, space, a, shared)).status.value) == "created"

    # Past the early read so the clash is found by the locked re-check.
    async def _nothing(*_a, **_k):
        return []
    backend_adapter.batch_check_uris_exist = _nothing
    r = await _create(backend_adapter, space, b, shared)
    assert str(r.status.value) == "already_exists"
    assert "sub-object" in r.message
    assert await _values(pg_conn, space, b, CREATED_AT) == 0


async def test_without_the_atomic_path_both_are_accepted(
        make_space, backend_adapter, pg_conn, monkeypatch):
    """Negative control: the old path loses the race this test sets up."""
    space = await make_space()
    monkeypatch.setattr(backend_adapter, "create_objects_atomic", None)
    uris = [f"urn:inttest:cc:{uuid.uuid4().hex[:8]}" for _ in range(N)]
    statuses = await _race(backend_adapter, space, uris)
    doubled = [u for u in uris if statuses[u] == ["created", "created"]]
    assert doubled, "the race was never hit, so the first test proves nothing"
    assert await _values(pg_conn, space, doubled[0], CREATED_AT) == 2
