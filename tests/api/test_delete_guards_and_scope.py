"""The rest of `issues/256`'s delete contract, through the API.

Every delete is now ONE transaction under the owning lock, and everything it
decides is decided inside it:

  ENTITY-ONLY DELETE (decision 1). Without the graph flag the entity was
  removed and every frame, slot and edge was left pointing at it. It is now
  REFUSED while the entity has members.

  ENTITY-FRAME DELETE. SPARQL discovery then a quad-level delete, no lock. A
  frame owned by another entity was skipped under a DELETED status; it now
  refuses the whole request. The entity's stamp moves inside the transaction.

  `/kgframes` DELETE (decision 3). Five SPARQL updates per frame, no
  transaction, and it deleted ENTITY frames without the entity's lock. Those are
  refused; an absent frame is NO_OP where the single form said NOT_FOUND.

  `if_unmodified_since` ON EVERY DELETE (decision 4). A delete racing a save is
  the lost update `issues/253` closed for writes: stale -> CONFLICT and nothing
  deleted; absent -> NO_OP, not CONFLICT; one stamp for several targets ->
  INVALID_REQUEST.

Absence is asserted by RAW COUNT in the space's quad table as well as through
the response, because a read path can miss an object that still exists.

Runs against the vg-test stack (:8002, Postgres :5433), never the dev server.
"""

from __future__ import annotations

import uuid

import pytest

from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]

NS = "http://vital.ai/test/delete_guards/"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _frame(value: str = "v", frame_uri: str | None = None):
    """A frame with one slot and its edge. Returns (frame_uri, slot_uri, objects)."""
    frame_uri = frame_uri or f"{NS}frame_{_uid()}"
    slot_uri = f"{NS}slot_{_uid()}"
    frame = KGFrame()
    frame.URI = frame_uri
    frame.name = "Probe Frame"
    slot = KGTextSlot()
    slot.URI = slot_uri
    slot.name = "Probe Slot"
    slot.textSlotValue = value
    edge = Edge_hasKGSlot()
    edge.URI = f"{NS}edge_{_uid()}"
    edge.edgeSource = frame_uri
    edge.edgeDestination = slot_uri
    return frame_uri, slot_uri, [frame, slot, edge]


async def _entity(vg_client, space, graph) -> str:
    uri = f"{NS}entity_{_uid()}"
    e = KGEntity()
    e.URI = uri
    e.name = "Delete Guard Probe"
    r = await vg_client.kgentities.create_kgentities(
        space_id=space, graph_id=graph, objects=[e])
    assert r.is_success, r.error_message or r.message
    return uri


async def _entity_frame(vg_client, space, graph, entity_uri, parent=None,
                        value="v"):
    """A frame (and slot) on the entity, under `parent` if given."""
    frame_uri, slot_uri, objs = _frame(value)
    r = await vg_client.kgentities.create_entity_frames(
        space_id=space, graph_id=graph, entity_uri=entity_uri, objects=objs,
        parent_frame_uri=parent)
    assert r.is_success, r.error_message or r.message
    return frame_uri, slot_uri


async def _standalone(vg_client, space, graph, parent=None):
    frame_uri, slot_uri, objs = _frame()
    if parent:
        r = await vg_client.kgframes.create_child_frames(
            space_id=space, graph_id=graph, parent_frame_uri=parent, objects=objs)
    else:
        r = await vg_client.kgframes.create_kgframes(
            space_id=space, graph_id=graph, objects=objs)
    assert r.is_success, r.error_message or r.message
    return frame_uri, slot_uri


async def _quads(pg_conn, space, *uris) -> int:
    return await pg_conn.fetchval(
        f"SELECT count(*) FROM {space}_rdf_quad WHERE subject_uuid = ANY("
        f"ARRAY(SELECT vitalgraph_term_uuid(u, 'U') FROM unnest($1::text[]) u))",
        list(uris))


async def _linking_edges(pg_conn, space, frame_uri) -> int:
    """Edges of any kind whose destination is the frame."""
    return await pg_conn.fetchval(
        f"SELECT count(*) FROM {space}_rdf_quad "
        f"WHERE predicate_uuid = vitalgraph_term_uuid($1, 'U') "
        f"AND object_uuid = vitalgraph_term_uuid($2, 'U')",
        "http://vital.ai/ontology/vital-core#hasEdgeDestination", frame_uri)


async def _entity_stamp(vg_client, space, graph, entity_uri) -> str:
    r = await vg_client.kgentities.get_kgentity(
        space_id=space, graph_id=graph, uri=entity_uri, include_entity_graph=True)
    assert r.is_success, r.error_message
    assert r.modification_stamp, f"{entity_uri} has no modification stamp"
    return r.modification_stamp


async def _frame_stamp(vg_client, space, graph, frame_uri) -> str:
    r = await vg_client.kgframes.get_kgframe(
        space_id=space, graph_id=graph, uri=frame_uri, include_frame_graph=True)
    assert r.is_success, r.error_message
    assert r.modification_stamp, f"{frame_uri} has no modification stamp"
    return r.modification_stamp


_STALE = "2000-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Entity-only delete refuses while the entity has members (decision 1)
# ---------------------------------------------------------------------------

async def test_an_entity_with_members_is_not_deleted_alone(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    frame, slot = await _entity_frame(vg_client, test_space, test_graph, entity)

    r = await vg_client.kgentities.delete_kgentity(
        space_id=test_space, graph_id=test_graph, uri=entity,
        delete_entity_graph=False)

    assert r.status == "invalid_request", (
        f"entity-only delete of an entity with a frame answered {r.status!r}: "
        f"it would leave the frame pointing at a deleted entity")
    assert "delete_entity_graph=true" in (r.message or r.error_message or "")
    assert await _quads(pg_conn, test_space, entity) > 0, "the entity was deleted"
    assert await _quads(pg_conn, test_space, frame, slot) > 0


async def test_a_batch_reports_the_refused_entity_and_deletes_the_rest(
        vg_client, test_space, test_graph, pg_conn):
    bare = await _entity(vg_client, test_space, test_graph)
    owner = await _entity(vg_client, test_space, test_graph)
    await _entity_frame(vg_client, test_space, test_graph, owner)

    r = await vg_client.kgentities.delete_kgentities_batch(
        space_id=test_space, graph_id=test_graph, uri_list=[bare, owner],
        delete_entity_graph=False)

    assert r.status == "partial", f"answered {r.status!r}: {r.message}"
    assert r.deleted_uris == [bare]
    assert await _quads(pg_conn, test_space, bare) == 0
    assert await _quads(pg_conn, test_space, owner) > 0


# ---------------------------------------------------------------------------
# Entity delete with if_unmodified_since
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("graph_delete", [True, False], ids=["graph", "entity_only"])
async def test_a_stale_entity_delete_is_a_conflict_and_deletes_nothing(
        vg_client, test_space, test_graph, pg_conn, graph_delete):
    entity = await _entity(vg_client, test_space, test_graph)
    r = await vg_client.kgentities.delete_kgentity(
        space_id=test_space, graph_id=test_graph, uri=entity,
        delete_entity_graph=graph_delete, if_unmodified_since=_STALE)
    assert r.is_conflict, f"answered {r.status!r}: {r.message}"
    assert await _quads(pg_conn, test_space, entity) > 0


@pytest.mark.parametrize("graph_delete", [True, False], ids=["graph", "entity_only"])
async def test_a_current_entity_delete_goes_through(
        vg_client, test_space, test_graph, pg_conn, graph_delete):
    entity = await _entity(vg_client, test_space, test_graph)
    stamp = await _entity_stamp(vg_client, test_space, test_graph, entity)
    r = await vg_client.kgentities.delete_kgentity(
        space_id=test_space, graph_id=test_graph, uri=entity,
        delete_entity_graph=graph_delete, if_unmodified_since=stamp)
    assert r.status == "deleted", f"answered {r.status!r}: {r.message}"
    assert await _quads(pg_conn, test_space, entity) == 0


async def test_a_guarded_delete_of_an_absent_entity_is_no_op(
        vg_client, test_space, test_graph):
    absent = f"{NS}never_{_uid()}"
    r = await vg_client.kgentities.delete_kgentity(
        space_id=test_space, graph_id=test_graph, uri=absent,
        delete_entity_graph=True, if_unmodified_since=_STALE)
    assert r.status == "no_op", (
        f"answered {r.status!r}: what the caller wanted gone is gone, so it is "
        f"not a conflict")


async def test_one_stamp_for_two_entities_is_refused(
        vg_client, test_space, test_graph, pg_conn):
    a = await _entity(vg_client, test_space, test_graph)
    b = await _entity(vg_client, test_space, test_graph)
    stamp = await _entity_stamp(vg_client, test_space, test_graph, a)
    r = await vg_client.kgentities.delete_kgentities_batch(
        space_id=test_space, graph_id=test_graph, uri_list=[a, b],
        delete_entity_graph=True, if_unmodified_since=stamp)
    assert r.status == "invalid_request", f"answered {r.status!r}: {r.message}"
    assert await _quads(pg_conn, test_space, a) > 0
    assert await _quads(pg_conn, test_space, b) > 0


# ---------------------------------------------------------------------------
# Entity-frame delete
# ---------------------------------------------------------------------------

async def test_an_entity_frame_delete_takes_the_whole_frame_graph(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    frame, slot = await _entity_frame(vg_client, test_space, test_graph, entity)
    keep, keep_slot = await _entity_frame(vg_client, test_space, test_graph, entity)

    r = await vg_client.kgentities.delete_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        frame_uris=[frame])

    assert r.status == "deleted", f"answered {r.status!r}: {r.message}"
    assert r.deleted_uris == [frame]
    assert await _quads(pg_conn, test_space, frame, slot) == 0
    assert await _linking_edges(pg_conn, test_space, frame) == 0, (
        "the Edge_hasEntityKGFrame to the deleted frame survived")
    assert await _linking_edges(pg_conn, test_space, slot) == 0, (
        "the Edge_hasKGSlot to the deleted slot survived")
    assert await _quads(pg_conn, test_space, entity, keep, keep_slot) > 0
    assert await _linking_edges(pg_conn, test_space, keep) == 1


async def test_another_entitys_frame_refuses_the_whole_request(
        vg_client, test_space, test_graph, pg_conn):
    mine = await _entity(vg_client, test_space, test_graph)
    theirs = await _entity(vg_client, test_space, test_graph)
    my_frame, _ = await _entity_frame(vg_client, test_space, test_graph, mine)
    their_frame, _ = await _entity_frame(vg_client, test_space, test_graph, theirs)

    r = await vg_client.kgentities.delete_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=mine,
        frame_uris=[my_frame, their_frame])

    assert r.status == "invalid_request", (
        f"answered {r.status!r}: a frame owned by another entity used to be "
        f"skipped under a DELETED status")
    assert their_frame in (r.message or r.error_message or "")
    assert await _quads(pg_conn, test_space, my_frame) > 0, (
        "a refused request deleted the caller's own frame")
    assert await _quads(pg_conn, test_space, their_frame) > 0


async def test_an_absent_entity_frame_is_no_op(vg_client, test_space, test_graph):
    entity = await _entity(vg_client, test_space, test_graph)
    absent = f"{NS}never_{_uid()}"
    r = await vg_client.kgentities.delete_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        frame_uris=[absent])
    assert r.status == "no_op", f"answered {r.status!r}: {r.message}"
    assert r.absent_uris == [absent]


async def test_an_entity_frame_with_a_child_needs_recursive(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    parent, _ = await _entity_frame(vg_client, test_space, test_graph, entity)
    child, child_slot = await _entity_frame(
        vg_client, test_space, test_graph, entity, parent=parent)

    r = await vg_client.kgentities.delete_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        frame_uris=[parent])
    assert r.status == "invalid_request", f"answered {r.status!r}: {r.message}"
    assert await _quads(pg_conn, test_space, parent, child) > 0

    r = await vg_client.kgentities.delete_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        frame_uris=[parent], recursive=True)
    assert r.status == "deleted", f"answered {r.status!r}: {r.message}"
    assert sorted(r.deleted_uris) == sorted([parent, child])
    assert await _quads(pg_conn, test_space, parent, child, child_slot) == 0
    assert await _linking_edges(pg_conn, test_space, child) == 0


async def test_a_stale_entity_frame_delete_is_a_conflict(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    frame, slot = await _entity_frame(vg_client, test_space, test_graph, entity)
    r = await vg_client.kgentities.delete_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        frame_uris=[frame], if_unmodified_since=_STALE)
    assert r.is_conflict, f"answered {r.status!r}: {r.message or r.error_message}"
    assert await _quads(pg_conn, test_space, frame, slot) > 0


async def test_an_entity_frame_delete_advances_the_entity_stamp(
        vg_client, test_space, test_graph):
    entity = await _entity(vg_client, test_space, test_graph)
    frame, _ = await _entity_frame(vg_client, test_space, test_graph, entity)
    stamp = await _entity_stamp(vg_client, test_space, test_graph, entity)

    r = await vg_client.kgentities.delete_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        frame_uris=[frame], if_unmodified_since=stamp)

    assert r.status == "deleted", f"answered {r.status!r}: {r.message}"
    assert await _entity_stamp(vg_client, test_space, test_graph, entity) != stamp, (
        "the delete did not move the entity's version, so the next guarded "
        "writer reads 'nobody wrote'")


async def test_a_delete_racing_a_save_does_not_delete_the_save(
        vg_client, test_space, test_graph, pg_conn):
    """D12e: A reads, B saves, A deletes with what it read."""
    entity = await _entity(vg_client, test_space, test_graph)
    frame, _ = await _entity_frame(vg_client, test_space, test_graph, entity)
    read_by_a = await _entity_stamp(vg_client, test_space, test_graph, entity)

    _, b_slot, b_objs = _frame("saved by B", frame_uri=frame)
    r = await vg_client.kgentities.update_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        objects=b_objs)
    assert r.is_success, r.error_message or r.message

    r = await vg_client.kgentities.delete_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        frame_uris=[frame], if_unmodified_since=read_by_a)

    assert r.is_conflict, f"answered {r.status!r}: A deleted B's save"
    assert await _quads(pg_conn, test_space, frame, b_slot) > 0


# ---------------------------------------------------------------------------
# /kgframes delete
# ---------------------------------------------------------------------------

async def test_kgframes_refuses_an_entitys_frame(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    frame, slot = await _entity_frame(vg_client, test_space, test_graph, entity)

    r = await vg_client.kgframes.delete_kgframe(
        space_id=test_space, graph_id=test_graph, uri=frame)

    assert r.status == "invalid_request", (
        f"answered {r.status!r}: /kgframes does not take the entity's lock, so "
        f"it may not delete the entity's frames")
    assert "/kgentities/kgframes" in (r.message or r.error_message or "")
    assert await _quads(pg_conn, test_space, frame, slot) > 0


async def test_kgframes_recursive_delete_takes_the_subtree(
        vg_client, test_space, test_graph, pg_conn):
    root, root_slot = await _standalone(vg_client, test_space, test_graph)
    child, child_slot = await _standalone(vg_client, test_space, test_graph,
                                          parent=root)

    r = await vg_client.kgframes.delete_kgframe(
        space_id=test_space, graph_id=test_graph, uri=root)
    assert r.status == "invalid_request", f"answered {r.status!r}: {r.message}"
    assert await _quads(pg_conn, test_space, root, child) > 0

    r = await vg_client.kgframes.delete_kgframe(
        space_id=test_space, graph_id=test_graph, uri=root, recursive=True)
    assert r.status == "deleted", f"answered {r.status!r}: {r.message}"
    assert sorted(r.deleted_uris) == sorted([root, child])
    assert await _quads(pg_conn, test_space, root, root_slot, child, child_slot) == 0
    assert await _linking_edges(pg_conn, test_space, child) == 0


async def test_kgframes_absent_frame_is_no_op(vg_client, test_space, test_graph):
    absent = f"{NS}never_{_uid()}"
    r = await vg_client.kgframes.delete_kgframe(
        space_id=test_space, graph_id=test_graph, uri=absent)
    assert r.status == "no_op", f"answered {r.status!r}: was NOT_FOUND"
    assert r.absent_uris == [absent]


async def test_kgframes_stale_delete_is_a_conflict_and_current_goes_through(
        vg_client, test_space, test_graph, pg_conn):
    frame, slot = await _standalone(vg_client, test_space, test_graph)

    r = await vg_client.kgframes.delete_kgframe(
        space_id=test_space, graph_id=test_graph, uri=frame,
        if_unmodified_since=_STALE)
    assert r.is_conflict, f"answered {r.status!r}: {r.message or r.error_message}"
    assert await _quads(pg_conn, test_space, frame, slot) > 0

    stamp = await _frame_stamp(vg_client, test_space, test_graph, frame)
    r = await vg_client.kgframes.delete_kgframe(
        space_id=test_space, graph_id=test_graph, uri=frame,
        if_unmodified_since=stamp)
    assert r.status == "deleted", f"answered {r.status!r}: {r.message}"
    assert await _quads(pg_conn, test_space, frame, slot) == 0


async def test_kgframes_one_stamp_for_two_roots_is_refused(
        vg_client, test_space, test_graph, pg_conn):
    a, _ = await _standalone(vg_client, test_space, test_graph)
    b, _ = await _standalone(vg_client, test_space, test_graph)
    stamp = await _frame_stamp(vg_client, test_space, test_graph, a)
    r = await vg_client.kgframes.delete_kgframes_batch(
        space_id=test_space, graph_id=test_graph, uri_list=f"{a},{b}",
        if_unmodified_since=stamp)
    assert r.status == "invalid_request", f"answered {r.status!r}: {r.message}"
    assert await _quads(pg_conn, test_space, a, b) > 0


# ---------------------------------------------------------------------------
# Client entity upsert (issue 256 item 6)
# ---------------------------------------------------------------------------

async def test_the_client_can_upsert_an_entity(vg_client, test_space, test_graph):
    uri = f"{NS}upserted_{_uid()}"
    e = KGEntity()
    e.URI = uri
    e.name = "first"
    r = await vg_client.kgentities.upsert_kgentities(
        space_id=test_space, graph_id=test_graph, objects=[e])
    assert r.status == "upserted", f"create through upsert: {r.status!r} {r.message}"

    e2 = KGEntity()
    e2.URI = uri
    e2.name = "second"
    r = await vg_client.kgentities.upsert_kgentities(
        space_id=test_space, graph_id=test_graph, objects=[e2])
    assert r.status == "upserted", f"replace through upsert: {r.status!r} {r.message}"

    got = await vg_client.kgentities.get_kgentity(
        space_id=test_space, graph_id=test_graph, uri=uri)
    assert got.is_success
    names = {str(o.name) for o in got.objects if str(o.URI) == uri}
    assert names == {"second"}, f"upsert did not replace the entity: {names}"


# ---------------------------------------------------------------------------
# Through the VitalGraphClient wrappers, which the tests above never used
# ---------------------------------------------------------------------------

async def test_the_wrapper_batch_delete_deletes(vg_client, test_space, test_graph, pg_conn):
    """It passed a comma-separated string to a method that iterated it, so the
    URIs went out a character at a time; the server answered NO_OP and nothing
    was deleted."""
    a = await _entity(vg_client, test_space, test_graph)
    b = await _entity(vg_client, test_space, test_graph)
    r = await vg_client.delete_kgentities_batch(test_space, test_graph, f"{a},{b}")
    assert r.status == "deleted", f"answered {r.status!r}: {r.message}"
    assert sorted(r.deleted_uris) == sorted([a, b])
    assert await _quads(pg_conn, test_space, a, b) == 0


async def test_the_wrapper_can_delete_an_entity_with_its_graph(
        vg_client, test_space, test_graph, pg_conn):
    """Without `delete_entity_graph` the wrapper could only send the entity-only
    delete, which the server now refuses for an entity with frames."""
    entity = await _entity(vg_client, test_space, test_graph)
    frame, slot = await _entity_frame(vg_client, test_space, test_graph, entity)
    r = await vg_client.delete_kgentity(test_space, test_graph, entity,
                                        delete_entity_graph=True)
    assert r.status == "deleted", f"answered {r.status!r}: {r.message}"
    assert await _quads(pg_conn, test_space, entity, frame, slot) == 0
