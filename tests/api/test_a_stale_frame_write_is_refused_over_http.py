"""The lost update, end to end over HTTP (`issues/253`).

Reported from production: "a slower, older save can overwrite a newer one even
when nothing fails", every request reporting success. The guard itself and its
database-level proof live in `tests/integration/test_a_stale_write_is_refused.py`;
this file asserts the CONTRACT — that a caller can reach the guard through the
client and recognise the answer it gets back.

Both halves of that have failed in this codebase before, which is why both are
asserted here rather than assumed: a parameter accepted by a route and then
dropped on the way down, and a refused write reported as a success.

The refusal arrives as HTTP **200** with `status="conflict"`, per this codebase's
convention of putting domain outcomes in the body. So the status code reveals
nothing and only the body does — which is how the caller came to log 42,343
successful writes and one error while losing updates.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/stale/"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _frame_for(entity_uri: str, value: str):
    """A frame carrying *value* in one slot, with both edges it needs."""
    frame_uri = f"{NS}frame_{_uid()}"
    slot_uri = f"{NS}slot_{_uid()}"

    frame = KGFrame()
    frame.URI = frame_uri
    frame.name = "Stale Probe"

    slot = KGTextSlot()
    slot.URI = slot_uri
    slot.name = "Value"
    slot.textSlotValue = value

    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = f"{NS}edge_ef_{_uid()}"
    edge_ef.edgeSource = entity_uri
    edge_ef.edgeDestination = frame_uri

    edge_fs = Edge_hasKGSlot()
    edge_fs.URI = f"{NS}edge_fs_{_uid()}"
    edge_fs.edgeSource = frame_uri
    edge_fs.edgeDestination = slot_uri

    return [frame, slot, edge_ef, edge_fs]


async def _stamp(vg_client, space, graph, entity_uri):
    """The entity's modification time, read the way a caller reads it.

    Through the client's own accessor, not by digging the predicate URI out of
    the object: that is the API a caller has, so this exercises it against real
    server data rather than asserting a parallel implementation of it. The unit
    tests cover its edges, including the `str()` form that never matches.
    """
    r = await vg_client.kgentities.get_kgentity(
        space_id=space, graph_id=graph, uri=entity_uri,
        include_entity_graph=True)
    assert r.is_success, r.error_message
    stamp = r.modification_stamp
    assert stamp, f"{entity_uri} came back without a modification stamp"
    return stamp


@pytest_asyncio.fixture(loop_scope="session")
async def host(vg_client, test_space, test_graph):
    """An entity with one frame already written."""
    entity_uri = f"{NS}entity_{_uid()}"
    entity = KGEntity()
    entity.URI = entity_uri
    entity.name = "Stale Probe Host"
    r = await vg_client.kgentities.create_kgentities(
        space_id=test_space, graph_id=test_graph, objects=[entity])
    assert r.is_success, r.error_message

    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity_uri,
        objects=_frame_for(entity_uri, "v0"))
    assert r.is_success, r.error_message
    return entity_uri


class TestTheContractOverHttp:
    async def test_the_entity_carries_a_stamp_a_caller_can_read(
            self, vg_client, test_space, test_graph, host):
        # The precondition for the whole mechanism: the value a caller sends
        # back has to be one the server gave it. A frame write stamps the
        # ENTITY, which is what makes a per-entity check possible at all.
        assert await _stamp(vg_client, test_space, test_graph, host)

    async def test_a_write_with_the_current_stamp_is_accepted(
            self, vg_client, test_space, test_graph, host):
        stamp = await _stamp(vg_client, test_space, test_graph, host)

        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=_frame_for(host, "fresh"), if_unmodified_since=stamp)

        assert r.is_success, f"a current stamp must not be refused: {r.message}"
        assert r.is_conflict is False

    async def test_a_stale_stamp_is_refused_as_a_conflict(
            self, vg_client, test_space, test_graph, host):
        stamp = await _stamp(vg_client, test_space, test_graph, host)

        # Somebody else's save lands first — the newer one.
        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=_frame_for(host, "winner"), if_unmodified_since=stamp)
        assert r.is_success, r.message

        # Now the slower save arrives, holding the stamp it read before that.
        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=_frame_for(host, "loser"), if_unmodified_since=stamp)

        assert r.is_conflict is True, (
            f"a stale write must be refused, got status={r.status!r} "
            f"message={r.message!r}")
        assert r.is_success is False
        # 200, not 409: the refusal is a domain outcome, so a caller reading
        # only the status code cannot tell this from a success.
        assert r.status_code == 200

    async def test_the_refusal_says_the_entity_moved(
            self, vg_client, test_space, test_graph, host):
        # The caller has to distinguish "retry after re-reading" from a genuine
        # store failure, and the message is where that survives — `issues/253`
        # also fixed the two methods that composed over it.
        stamp = await _stamp(vg_client, test_space, test_graph, host)
        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=_frame_for(host, "a"), if_unmodified_since=stamp)
        assert r.is_success, r.message

        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=_frame_for(host, "b"), if_unmodified_since=stamp)
        assert r.is_conflict is True
        # Which entity, what it sent, and what is actually there — enough for a
        # caller to log the race without another round trip.
        msg = r.message or ""
        assert host in msg, msg
        assert stamp in msg, msg
        current = await _stamp(vg_client, test_space, test_graph, host)
        assert current in msg, msg

    async def test_a_refused_write_wrote_nothing(
            self, vg_client, test_space, test_graph, host):
        # A conflict that still applied half the frame would be worse than the
        # lost update it replaces.
        stamp = await _stamp(vg_client, test_space, test_graph, host)
        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=_frame_for(host, "keeper"), if_unmodified_since=stamp)
        assert r.is_success, r.message
        after_winner = await _stamp(vg_client, test_space, test_graph, host)

        losing = _frame_for(host, "discarded")
        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=losing, if_unmodified_since=stamp)
        assert r.is_conflict is True

        # The stamp did not move, and the losing frame is not in the graph.
        assert await _stamp(vg_client, test_space, test_graph, host) == after_winner
        r = await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph, uri=host,
            include_entity_graph=True)
        uris = {str(getattr(o, "URI", "")) for o in (r.objects.objects or [])}
        assert str(losing[0].URI) not in uris, "a refused write left a frame behind"

    async def test_the_update_path_carries_it_too(
            self, vg_client, test_space, test_graph, host):
        # Two entry points reach the same guard, and the plumbing is separate
        # for each: `_create_or_update_frames` and `_update_entity_frames`.
        # The update path validates ownership, so the frame has to exist first.
        objs = _frame_for(host, "via-update")
        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=objs)
        assert r.is_success, r.message

        stamp = await _stamp(vg_client, test_space, test_graph, host)
        r = await vg_client.kgentities.update_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=objs, if_unmodified_since=stamp)
        assert r.is_success, r.error_message or r.message
        assert r.is_conflict is False

        r = await vg_client.kgentities.update_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=objs, if_unmodified_since=stamp)
        assert r.is_conflict is True, (
            f"status={r.status!r} message={r.message!r}")

    async def test_omitting_it_keeps_the_previous_behaviour(
            self, vg_client, test_space, test_graph, host):
        # Opt-in. Every existing caller sends nothing and must be unaffected,
        # including the autosave whose writes this is meant to order.
        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=_frame_for(host, "legacy"))
        assert r.is_success, r.message
        assert r.is_conflict is False


class TestTheReportedSymptom:
    """The autosave race itself, on one slot — not just the status it returns."""

    async def test_the_newer_value_survives_the_slower_save(
            self, vg_client, test_space, test_graph, host):
        # Both savers read the entity, both edit the SAME slot, and the one that
        # read FIRST writes LAST. That is the production shape: one lead took 40
        # saves in four and a half minutes, each sending the whole frame.
        frame_uri = f"{NS}frame_{_uid()}"
        slot_uri = f"{NS}slot_{_uid()}"

        def save(value):
            frame = KGFrame()
            frame.URI = frame_uri
            frame.name = "Apply Form"
            slot = KGTextSlot()
            slot.URI = slot_uri
            slot.name = "Employer"
            slot.textSlotValue = value
            edge_ef = Edge_hasEntityKGFrame()
            edge_ef.URI = f"{NS}edge_ef_{_uid()}"
            edge_ef.edgeSource = host
            edge_ef.edgeDestination = frame_uri
            edge_fs = Edge_hasKGSlot()
            edge_fs.URI = f"{NS}edge_fs_{_uid()}"
            edge_fs.edgeSource = frame_uri
            edge_fs.edgeDestination = slot_uri
            return [frame, slot, edge_ef, edge_fs]

        async def value():
            r = await vg_client.kgentities.get_kgentity_frames(
                space_id=test_space, graph_id=test_graph,
                entity_uri=host, frame_uris=[frame_uri])
            assert r.is_success, r.error_message
            fg = getattr(r, "frame_graph", None)
            for o in ((fg.objects if fg else None) or []):
                if isinstance(o, KGTextSlot) and str(o.URI) == slot_uri:
                    return str(o.textSlotValue) if o.textSlotValue else None
            return None

        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=save("Acme"))
        assert r.is_success, r.message

        # Both read here.
        shared = await _stamp(vg_client, test_space, test_graph, host)

        # UPSERT for the rewrites, not create: a create of an existing frame is
        # refused once `issues/256` item 3 is switched on, and re-writing is
        # what upsert is for. The guard is the same either way.
        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=save("Acme Corporation"), if_unmodified_since=shared,
            operation_mode="upsert")
        assert r.is_success, r.message
        assert await value() == "Acme Corporation"

        # The slower saver now writes what it read a moment ago. Without the
        # guard this reports success and the newer value is gone — the loss
        # nobody could see, because both requests were 200.
        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=host,
            objects=save("Acme"), if_unmodified_since=shared,
            operation_mode="upsert")
        assert r.is_conflict is True, f"status={r.status!r}"
        assert await value() == "Acme Corporation", (
            "the slower save overwrote the newer one — the lost update")
