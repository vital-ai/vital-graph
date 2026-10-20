"""The frame_slot full build drops its secondary indexes for the load (`issues/289`).

Measured on a 50.6M-quad space: 357 s inserting with all seven indexes in place,
79 s dropping the six secondaries, inserting, and rebuilding them. This pins
what that must not cost: the same rows, every index back, and a failure part
way through leaving the table exactly as it was rather than un-indexed.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
EX = "http://example.org/fsrebuild/"
GRAPH = "http://example.org/fsrebuild/graph"


def _quads(n_frames=12, slots=3):
    from rdflib import Literal, URIRef
    g = URIRef(GRAPH)
    out = []
    for i in range(n_frames):
        e, f, fe = URIRef(f"{EX}e{i}"), URIRef(f"{EX}f{i}"), URIRef(f"{EX}fe{i}")
        out += [(fe, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasEntityKGFrame"), g),
                (fe, URIRef(f"{CORE}hasEdgeSource"), e, g),
                (fe, URIRef(f"{CORE}hasEdgeDestination"), f, g),
                (f, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGFrame"), g)]
        for j in range(slots):
            s, se = URIRef(f"{EX}s{i}_{j}"), URIRef(f"{EX}se{i}_{j}")
            out += [(se, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasKGSlot"), g),
                    (se, URIRef(f"{CORE}hasEdgeSource"), f, g),
                    (se, URIRef(f"{CORE}hasEdgeDestination"), s, g),
                    (s, URIRef(f"{KG}hasKGSlotType"), URIRef(f"{EX}Role{j}"), g),
                    (s, URIRef(f"{KG}hasEntitySlotValue"), e, g)]
    return out


async def _indexes(conn, space):
    return sorted(r["indexname"] for r in await conn.fetch(
        "SELECT indexname FROM pg_indexes WHERE tablename = $1", f"{space}_frame_slot"))


async def _rows(conn, space):
    return sorted(tuple(r) for r in await conn.fetch(f"SELECT * FROM {space}_frame_slot"))


async def test_the_rebuild_restores_every_index_and_the_rows(test_space, space_impl, pg_pool):
    from vitalgraph.db.sparql_sql.sync_frame_slot_table import (
        _secondary_index_ddl, resync_frame_slot_table)
    await space_impl.add_rdf_quads_batch(test_space, _quads())
    async with pg_pool.acquire() as conn:
        before_idx = await _indexes(conn, test_space)
        incremental = await _rows(conn, test_space)   # what the write path built
        n = await resync_frame_slot_table(conn, test_space)
        after_idx = await _indexes(conn, test_space)
        rebuilt = await _rows(conn, test_space)
    assert n == 36 and rebuilt == incremental, (
        "the rebuild must derive exactly what the incremental sync did")
    assert after_idx == before_idx
    assert {name for name, _ in _secondary_index_ddl(test_space)} <= set(after_idx)


async def test_a_failure_part_way_leaves_the_table_as_it_was(test_space, space_impl, pg_pool):
    from vitalgraph.db.sparql_sql.sync_frame_slot_table import resync_frame_slot_table

    class _FailOnInsert:
        """The real connection, except the INSERT raises -- after the TRUNCATE
        and the index drops have run."""

        def __init__(self, conn):
            self._c = conn

        def __getattr__(self, name):
            return getattr(self._c, name)

        async def execute(self, sql, *args, **kw):
            if sql.lstrip().startswith("INSERT INTO"):
                raise RuntimeError("simulated failure mid-rebuild")
            return await self._c.execute(sql, *args, **kw)

    async with pg_pool.acquire() as conn:
        if not await _rows(conn, test_space):
            await space_impl.add_rdf_quads_batch(test_space, _quads())
        before_rows, before_idx = await _rows(conn, test_space), await _indexes(conn, test_space)
        with pytest.raises(RuntimeError, match="simulated"):
            await resync_frame_slot_table(_FailOnInsert(conn), test_space)
        assert await _indexes(conn, test_space) == before_idx, "indexes were left dropped"
        assert await _rows(conn, test_space) == before_rows, "the TRUNCATE was not rolled back"
