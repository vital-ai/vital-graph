"""`PUT /objects` takes the entity lock the other write paths take (`issues/174` item 6).

Every KG write path serialises on its entity's lock (`entity_lock.lock_entities`).
`update_objects_batch` took none, and read the quads it deletes before opening
its transaction, so it could rewrite an entity's members while a locked writer
believed it had the entity to itself.

Each test holds a lock from a separate connection, sends the update, and checks
that the update WAITS for it, then completes once the lock is released. The
three lock targets: the entity a stored member belongs to, the entity an
incoming object is being moved into, and an ungrouped subject's own URI.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from ai_haley_kg_domain.model.KGFrame import KGFrame

from vitalgraph.db.sparql_sql.entity_lock import entity_lock_key

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/objlock/"
HOLD_S = 1.5        # well inside the request pool's 10 s lock_timeout


def _frame(name: str, entity: str | None) -> KGFrame:
    f = KGFrame()
    f.URI = f"{NS}frame_{uuid.uuid4().hex[:10]}"
    f.name = name
    if entity:
        f.kGGraphURI = entity
    return f


async def _waits_for(pg_conn, lock_uri, update):
    """True when `update` blocks while `lock_uri` is locked, then succeeds."""
    tr = pg_conn.transaction()
    await tr.start()
    try:
        await pg_conn.execute("SELECT pg_advisory_xact_lock($1)", entity_lock_key(lock_uri))
        task = asyncio.ensure_future(update())
        await asyncio.sleep(HOLD_S)
        blocked = not task.done()
    finally:
        await tr.rollback()          # releases the lock
    result = await asyncio.wait_for(task, timeout=30)
    assert result.is_success, f"update failed: {result.error_message}"
    return blocked


async def test_a_member_waits_for_its_entity(vg_client, test_space, test_graph, pg_conn):
    entity = f"{NS}entity_{uuid.uuid4().hex[:10]}"
    f = _frame("before", entity)
    cr = await vg_client.objects.create_objects(test_space, test_graph, [f])
    assert cr.is_success, cr.error_message

    f.name = "after"
    blocked = await _waits_for(pg_conn, entity, lambda: vg_client.objects.update_objects(
        test_space, test_graph, [f]))
    assert blocked, "PUT /objects did not wait for the member's entity lock"
    gr = await vg_client.objects.get_object(test_space, test_graph, str(f.URI))
    assert str(gr.object.name) == "after"


async def test_moving_into_an_entity_waits_for_that_entity(
        vg_client, test_space, test_graph, pg_conn):
    f = _frame("loose", None)
    cr = await vg_client.objects.create_objects(test_space, test_graph, [f])
    assert cr.is_success, cr.error_message

    target = f"{NS}entity_{uuid.uuid4().hex[:10]}"
    f.kGGraphURI = target
    blocked = await _waits_for(pg_conn, target, lambda: vg_client.objects.update_objects(
        test_space, test_graph, [f]))
    assert blocked, "PUT /objects did not wait for the entity it moves the object into"


async def test_an_ungrouped_subject_is_locked_by_its_own_uri(
        vg_client, test_space, test_graph, pg_conn):
    f = _frame("solo", None)
    cr = await vg_client.objects.create_objects(test_space, test_graph, [f])
    assert cr.is_success, cr.error_message

    f.name = "solo2"
    blocked = await _waits_for(pg_conn, str(f.URI), lambda: vg_client.objects.update_objects(
        test_space, test_graph, [f]))
    assert blocked, "PUT /objects did not wait for the subject's own lock"


async def test_an_unrelated_lock_does_not_block(vg_client, test_space, test_graph, pg_conn):
    """The control: the waits above are the lock, not a slow update."""
    f = _frame("free", f"{NS}entity_{uuid.uuid4().hex[:10]}")
    cr = await vg_client.objects.create_objects(test_space, test_graph, [f])
    assert cr.is_success, cr.error_message

    f.name = "free2"
    blocked = await _waits_for(pg_conn, f"{NS}someone_else",
                               lambda: vg_client.objects.update_objects(
                                   test_space, test_graph, [f]))
    assert not blocked
