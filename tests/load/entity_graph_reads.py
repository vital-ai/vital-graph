"""Prepare per-entity graph reads for the load mix. `issues/171` Part 2.

The two things real usage does are FIND ENTITIES and OPEN ONE. The find half is
served by the slot-sort fast path in ~20ms; the open half is a SPARQL query with
four UNION branches — entity triples, its frames, its frames' slots, its child
frames — that goes through the GENERAL PIPELINE. They exercise different halves
of the system and only the first was being measured.

COMPILED ONCE, EXECUTED MANY TIMES. Each entity URI produces different SQL, so a
faithful version would compile per request and put the sidecar on the hot path —
which would measure the sidecar, not the database, and cap throughput at its
round trip. Instead a sample of real entities is compiled during setup and their
SQL is cycled during the run. What that measures is the DATABASE cost of opening
an entity under contention, which is the question; what it does not measure is
compile latency, which is a separate concern with a separate cache.

DETERMINISTIC ROTATION, not random selection. A random pick makes two runs
incomparable for no benefit — the point is to touch many distinct entities, and
a cycle does that exactly.
"""

from __future__ import annotations

from itertools import cycle
from typing import Iterator, List, Optional


async def sample_entity_uris(conn, space_id: str, limit: int = 20) -> List[str]:
    """Real entity URIs that actually have slots, so the graph read is not empty.

    Drawn from `entity_slot_sort` because an entity with no frames returns a
    handful of rows and would make the read look cheap for the wrong reason.
    """
    rows = await conn.fetch(
        f"SELECT DISTINCT t.term_text"
        f"  FROM {space_id}_entity_slot_sort s"
        f"  JOIN {space_id}_term t ON t.term_uuid = s.entity_uuid"
        f" LIMIT {int(limit)}")
    return [r[0] for r in rows]


async def prepare_entity_graph_sql(conn, space_id: str, uris: List[str],
                                   sidecar_url: str) -> List[str]:
    """Compile + generate the entity-graph SQL for each URI, once."""
    from vitalgraph.sparql.kg_query_builder import KGGraphSeparationQueryBuilder
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    builder = KGGraphSeparationQueryBuilder()
    client = AsyncSidecarClient(sidecar_url)
    out: List[str] = []
    try:
        for uri in uris:
            try:
                raw = await client.compile(
                    builder.build_entity_graph_collection_query(uri))
                cr = map_compile_response(raw)
                if not cr.ok:
                    continue
                gen = await generate_sql(cr, space_id, conn=conn)
                if gen.ok and gen.sql:
                    out.append(gen.sql)
            except Exception:
                # One entity failing to compile is not a reason to abandon the
                # workload; an empty result IS, and the caller checks for that.
                continue
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            r = close()
            if hasattr(r, "__await__"):
                await r
    return out


def sql_rotation(statements: List[str]) -> Iterator[str]:
    return cycle(statements)
