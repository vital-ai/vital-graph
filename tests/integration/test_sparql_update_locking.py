"""A SPARQL update must serialise against entity and frame writes.

`issues/174` item 5. A raw SPARQL update can modify the same subjects an entity
upsert or entity-graph delete is replacing. Until it took the same advisory lock
those paths hold, the two interleaved — which is how slots ended up holding two
values on the production space: 94 subjects on `hasTextSlotValue`, 92 on
`hasDateTimeSlotValue`.

DETERMINISTIC, NOT A TIMING RACE. Proving this by racing two writers needs a
window wide enough for the compile round trip to land inside, which makes the
test slow and flaky and says nothing when it passes. Instead a holder
transaction takes the grouping lock and keeps it, and the assertion is simply
whether the update proceeds. Three attempts at the racing version passed with
the lock removed before this shape was arrived at.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from rdflib import URIRef, Literal

from vitalgraph.db.sparql_sql.entity_lock import lock_entities
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid

pytestmark = pytest.mark.asyncio(loop_scope="session")

GU = "http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI"
TXT = "http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue"

# Long enough that a merely slow update is not mistaken for a blocked one, short
# enough that a genuine hang fails the test rather than the session.
_BLOCKED_AFTER = 2.0
_PROCEEDS_WITHIN = 20.0


async def _seed_slot(space_impl, space_id, graph, slot, entity):
    """A slot that EXISTS inside an entity graph, carrying only its grouping.

    The value is deliberately absent. With a value present, PostgreSQL's own row
    locks serialise the two writers and the test passes whether or not the
    advisory lock works — which is one of the ways an earlier version of this
    test proved nothing.
    """
    async with space_impl.db_impl.connection_pool.acquire() as conn:
        await space_impl.add_rdf_quads_batch_bulk(
            space_id,
            [(URIRef(slot), URIRef(GU), URIRef(entity), URIRef(graph))],
            connection=conn)


def _update(graph, slot, value):
    return f"""
    DELETE {{ GRAPH <{graph}> {{ <{slot}> <{TXT}> ?old . }} }}
    INSERT {{ GRAPH <{graph}> {{ <{slot}> <{TXT}> "{value}" . }} }}
    WHERE  {{ GRAPH <{graph}> {{ OPTIONAL {{ <{slot}> <{TXT}> ?old . }} }} }}
    """


async def _values(space_impl, space_id, graph, slot):
    async with space_impl.db_impl.connection_pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT t.term_text FROM {space_id}_rdf_quad q "
            f"  JOIN {space_id}_term t ON t.term_uuid = q.object_uuid "
            f" WHERE q.subject_uuid = $1 AND q.predicate_uuid = $2 "
            f"   AND q.context_uuid = $3",
            _generate_term_uuid(slot, "U"), _generate_term_uuid(TXT, "U"),
            _generate_term_uuid(graph, "U"))
    return sorted(r[0] for r in rows)


async def test_update_waits_for_a_held_entity_lock(space_impl, test_space):
    """The lock does its job: the update cannot proceed while the entity is held.

    The change set names ONLY the slot value quad — no reference to the entity
    enclosing it — so this also exercises resolving the subject to its grouping
    through the store. Without that resolution the update would lock the slot,
    collide with nothing, and sail past the held lock.
    """
    sp = test_space
    graph = f"urn:test:{sp}"
    entity = f"urn:test:ent:{uuid.uuid4().hex[:8]}"
    slot = f"{entity}:slot"
    await _seed_slot(space_impl, sp, graph, slot, entity)

    holder = await space_impl.db_impl.connection_pool.acquire()
    tx = holder.transaction()
    task = None
    try:
        await tx.start()
        await lock_entities(holder, [entity])          # the entity write's key

        task = asyncio.ensure_future(
            space_impl.execute_sparql_update(sp, _update(graph, slot, "sparql")))
        done, _ = await asyncio.wait({task}, timeout=_BLOCKED_AFTER)
        assert not done, (
            "the update completed while the entity lock was held — it either "
            "took no lock, or resolved the slot to a different key than the "
            "entity write uses")

        await tx.rollback()                            # release the grouping
        await asyncio.wait_for(task, timeout=_PROCEEDS_WITHIN)
    finally:
        # Roll back HERE too: on assertion failure the block above never
        # reaches its rollback, and returning a connection with an open
        # transaction to the pool turns one failed test into a broken session.
        try:
            await tx.rollback()
        except Exception:
            pass
        if task is not None and not task.done():
            task.cancel()
        await space_impl.db_impl.connection_pool.release(holder)

    assert await _values(space_impl, sp, graph, slot) == ["sparql"]


async def test_update_is_not_blocked_by_an_unrelated_entity(space_impl, test_space):
    """The control, and the half that makes the first test mean something.

    Without this, a lock that simply blocked everything — or an update that
    happened to be slow — would look identical to correct behaviour.
    """
    sp = test_space
    graph = f"urn:test:{sp}"
    entity = f"urn:test:ent:{uuid.uuid4().hex[:8]}"
    slot = f"{entity}:slot"
    unrelated = f"urn:test:ent:{uuid.uuid4().hex[:8]}"
    await _seed_slot(space_impl, sp, graph, slot, entity)

    holder = await space_impl.db_impl.connection_pool.acquire()
    tx = holder.transaction()
    try:
        await tx.start()
        await lock_entities(holder, [unrelated])       # a DIFFERENT grouping

        await asyncio.wait_for(
            space_impl.execute_sparql_update(sp, _update(graph, slot, "sparql")),
            timeout=_PROCEEDS_WITHIN)
    finally:
        try:
            await tx.rollback()
        except Exception:
            pass
        await space_impl.db_impl.connection_pool.release(holder)

    assert await _values(space_impl, sp, graph, slot) == ["sparql"]
