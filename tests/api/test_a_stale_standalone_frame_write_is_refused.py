"""The conditional write on the routes with no owning entity (`issues/253`).

A frame inside an entity and a top-level frame (or a child of one) are DIFFERENT
THINGS in this model, reached through different routes, and the unit of
concurrency follows the object. So `/kgentities/kgframes` guards on the owning
ENTITY, which is what its callers hold, and these routes guard on the FRAME —
they have no entity, as `_create_frames` says in its own docstring and as
`_update_frame_slots` shows by not being given one. Two different keys because
they are two different objects, not one guard and one weaker version of it.

That stamp did not exist before this issue: a frame write stamped only the
entity, so there was nothing for a frame-keyed precondition to compare against.
These routes now advance the frame's version on every write, which is what makes
the loop possible at all, and the first test here asserts exactly that.

Three things are asserted that the unit tests cannot reach: that the stamp
arrives over HTTP, that the refusal arrives as `status="conflict"` in a 200 with
nothing written, and that a precondition covering several frames is refused as a
bad REQUEST rather than silently narrowed to one of them.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/sfstale/"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _frame(value: str, uri: str | None = None):
    """A standalone frame with one slot carrying *value*."""
    frame_uri = uri or f"{NS}frame_{_uid()}"
    slot_uri = f"{NS}slot_{_uid()}"

    frame = KGFrame()
    frame.URI = frame_uri
    frame.name = "Standalone Probe"

    slot = KGTextSlot()
    slot.URI = slot_uri
    slot.name = "Value"
    slot.textSlotValue = value

    edge = Edge_hasKGSlot()
    edge.URI = f"{NS}edge_{_uid()}"
    edge.edgeSource = frame_uri
    edge.edgeDestination = slot_uri

    return frame_uri, [frame, slot, edge]


async def _stamp(vg_client, space, graph, frame_uri):
    """The FRAME's modification stamp, through the client's own accessor."""
    r = await vg_client.kgframes.get_kgframe(
        space_id=space, graph_id=graph, uri=frame_uri,
        include_frame_graph=True)
    assert r.is_success, r.error_message
    stamp = r.modification_stamp
    assert stamp, f"{frame_uri} came back without a modification stamp"
    return stamp


@pytest_asyncio.fixture(loop_scope="session")
async def frame(vg_client, test_space, test_graph):
    """One standalone frame, already written."""
    frame_uri, objs = _frame("v0")
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs)
    assert r.is_success, r.error_message or r.message
    return frame_uri


class TestTheFrameCarriesItsOwnVersion:
    async def test_a_write_stamps_the_frame(
            self, vg_client, test_space, test_graph, frame):
        # The precondition for everything else. Before this issue a frame
        # carried no stamp at all, so there was nothing to be conditional on.
        assert await _stamp(vg_client, test_space, test_graph, frame)

    async def test_the_stamp_advances_on_each_write(
            self, vg_client, test_space, test_graph, frame):
        # A version that does not move is worse than none: the next conditional
        # caller reads "nobody wrote" and overwrites.
        first = await _stamp(vg_client, test_space, test_graph, frame)
        _, objs = _frame("v1", uri=frame)
        r = await vg_client.kgframes.update_kgframes(
            space_id=test_space, graph_id=test_graph, objects=objs)
        assert r.is_success, r.error_message or r.message
        assert await _stamp(vg_client, test_space, test_graph, frame) != first


class TestTheRefusal:
    async def test_the_current_stamp_is_accepted(
            self, vg_client, test_space, test_graph, frame):
        stamp = await _stamp(vg_client, test_space, test_graph, frame)
        _, objs = _frame("fresh", uri=frame)
        r = await vg_client.kgframes.update_kgframes(
            space_id=test_space, graph_id=test_graph, objects=objs,
            if_unmodified_since=stamp)
        assert r.is_success, f"a current stamp must not be refused: {r.message}"
        assert r.is_conflict is False

    async def test_a_stale_stamp_is_refused_as_a_conflict(
            self, vg_client, test_space, test_graph, frame):
        stamp = await _stamp(vg_client, test_space, test_graph, frame)

        _, winner = _frame("winner", uri=frame)
        r = await vg_client.kgframes.update_kgframes(
            space_id=test_space, graph_id=test_graph, objects=winner,
            if_unmodified_since=stamp)
        assert r.is_success, r.error_message or r.message

        _, loser = _frame("loser", uri=frame)
        r = await vg_client.kgframes.update_kgframes(
            space_id=test_space, graph_id=test_graph, objects=loser,
            if_unmodified_since=stamp)

        assert r.is_conflict is True, (
            f"status={r.status!r} message={r.message or r.error_message!r}")
        assert r.is_success is False
        # 200, not 409: the refusal is a domain outcome, so only the body says so.
        assert r.status_code == 200

    async def test_a_refused_write_left_the_frame_alone(
            self, vg_client, test_space, test_graph, frame):
        stamp = await _stamp(vg_client, test_space, test_graph, frame)
        _, winner = _frame("keeper", uri=frame)
        r = await vg_client.kgframes.update_kgframes(
            space_id=test_space, graph_id=test_graph, objects=winner,
            if_unmodified_since=stamp)
        assert r.is_success, r.error_message or r.message
        after = await _stamp(vg_client, test_space, test_graph, frame)

        _, loser = _frame("discarded", uri=frame)
        r = await vg_client.kgframes.update_kgframes(
            space_id=test_space, graph_id=test_graph, objects=loser,
            if_unmodified_since=stamp)
        assert r.is_conflict is True
        assert await _stamp(vg_client, test_space, test_graph, frame) == after

    async def test_omitting_it_keeps_the_previous_behaviour(
            self, vg_client, test_space, test_graph, frame):
        _, objs = _frame("legacy", uri=frame)
        r = await vg_client.kgframes.update_kgframes(
            space_id=test_space, graph_id=test_graph, objects=objs)
        assert r.is_success, r.error_message or r.message
        assert r.is_conflict is False


class TestOneStampCannotCoverManyFrames:
    async def test_it_is_refused_as_a_bad_request(
            self, vg_client, test_space, test_graph, frame):
        # Not narrowed to one of them and not reported as a conflict: a conflict
        # says "re-read and retry" and this request is refused identically
        # however fresh the stamp is. The caller has to change what it SENDS.
        stamp = await _stamp(vg_client, test_space, test_graph, frame)
        _, a = _frame("a", uri=frame)
        _, b = _frame("b")

        r = await vg_client.kgframes.update_kgframes(
            space_id=test_space, graph_id=test_graph, objects=a + b,
            if_unmodified_since=stamp)

        assert r.is_success is False
        assert r.is_conflict is False, "an ambiguous request is not a conflict"
        msg = (r.message or r.error_message or "")
        assert "if_unmodified_since" in msg, msg

    async def test_the_batch_still_works_unconditionally(
            self, vg_client, test_space, test_graph, frame):
        # The refusal is about the PRECONDITION, not about writing many frames.
        # `b` is created first: an update of a frame that does not exist is
        # NOT_FOUND since `issues/256` item 3, and this test was relying on
        # update creating it.
        _, a = _frame("a", uri=frame)
        b_uri, b = _frame("b")
        r = await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=b)
        assert r.is_success, r.error_message or r.message
        _, b = _frame("b2", uri=b_uri)
        r = await vg_client.kgframes.update_kgframes(
            space_id=test_space, graph_id=test_graph, objects=a + b)
        assert r.is_success, r.error_message or r.message


class TestTheSlotRouteGuardsOnItsFrame:
    async def test_a_stale_slot_write_is_refused(
            self, vg_client, test_space, test_graph, frame):
        # `_update_frame_slots` is given only the frame URI, which is the
        # clearest case for keying the precondition on the frame.
        stamp = await _stamp(vg_client, test_space, test_graph, frame)

        slot = KGTextSlot()
        slot.URI = f"{NS}slot_{_uid()}"
        slot.name = "Value"
        slot.textSlotValue = "first"
        r = await vg_client.kgframes.create_frame_slots(
            space_id=test_space, graph_id=test_graph, frame_uri=frame,
            objects=[slot], if_unmodified_since=stamp)
        assert r.is_success, r.error_message or r.message

        slot2 = KGTextSlot()
        slot2.URI = f"{NS}slot_{_uid()}"
        slot2.name = "Value"
        slot2.textSlotValue = "second"
        r = await vg_client.kgframes.create_frame_slots(
            space_id=test_space, graph_id=test_graph, frame_uri=frame,
            objects=[slot2], if_unmodified_since=stamp)
        assert r.is_conflict is True, (
            f"status={r.status!r} message={r.message or r.error_message!r}")

    async def test_a_slot_write_advances_the_frame(
            self, vg_client, test_space, test_graph, frame):
        # Editing a frame's slots IS a change to the frame, so a caller watching
        # the frame's version has to see it move — otherwise two callers editing
        # different slots of one frame never conflict and one of them is lost.
        before = await _stamp(vg_client, test_space, test_graph, frame)
        slot = KGTextSlot()
        slot.URI = f"{NS}slot_{_uid()}"
        slot.name = "Value"
        slot.textSlotValue = "moved"
        r = await vg_client.kgframes.create_frame_slots(
            space_id=test_space, graph_id=test_graph, frame_uri=frame,
            objects=[slot])
        assert r.is_success, r.error_message or r.message
        assert await _stamp(vg_client, test_space, test_graph, frame) != before


class TestTheOtherWritesToTheSameRoute:
    """Four more client methods POST to `/api/graphs/kgframes`.

    None of their names says so, and all four were missed when the parameter was
    first added to the obvious ones. A unit test now pins the audit by URL; this
    proves the two that a test can drive actually refuse over HTTP, because
    "sends the parameter" and "is refused" are different claims.
    """

    async def test_frames_with_slots_refuses_a_stale_stamp(
            self, vg_client, test_space, test_graph, frame):
        stamp = await _stamp(vg_client, test_space, test_graph, frame)
        _, objs = _frame("winner", uri=frame)
        r = await vg_client.kgframes.update_kgframes_with_slots(
            space_id=test_space, graph_id=test_graph, objects=objs,
            if_unmodified_since=stamp)
        assert r.is_success, r.error_message or r.message

        _, objs = _frame("loser", uri=frame)
        r = await vg_client.kgframes.update_kgframes_with_slots(
            space_id=test_space, graph_id=test_graph, objects=objs,
            if_unmodified_since=stamp)
        assert r.is_conflict is True, (
            f"status={r.status!r} message={r.message or r.error_message!r}")

    async def test_the_create_halves_refuse_a_stale_stamp_too(
            self, vg_client, test_space, test_graph, frame):
        # The create/upsert halves take a DIFFERENT server handler from the
        # update halves (`_handle_create_mode` vs `_handle_update_mode`), each
        # with its own broad `except`, so passing on one says nothing about the
        # other — that is exactly how the 500 on the update path survived a green
        # create path earlier in this issue. Through UPSERT, the create-path mode
        # that rewrites an existing frame: a CREATE of one is refused once
        # `issues/256` item 3 is switched on.
        stamp = await _stamp(vg_client, test_space, test_graph, frame)
        _, objs = _frame("winner", uri=frame)
        r = await vg_client.kgframes.create_kgframes_with_slots(
            space_id=test_space, graph_id=test_graph, objects=objs,
            if_unmodified_since=stamp, operation_mode="upsert")
        assert r.is_success, r.error_message or r.message

        _, objs = _frame("loser", uri=frame)
        r = await vg_client.kgframes.create_kgframes_with_slots(
            space_id=test_space, graph_id=test_graph, objects=objs,
            if_unmodified_since=stamp, operation_mode="upsert")
        assert r.is_conflict is True, (
            f"status={r.status!r} message={r.message or r.error_message!r}")

    async def test_create_child_frames_refuses_a_stale_stamp(
            self, vg_client, test_space, test_graph, frame):
        child_uri, child = _frame("c0")
        r = await vg_client.kgframes.create_child_frames(
            space_id=test_space, graph_id=test_graph,
            parent_frame_uri=frame, objects=child)
        assert r.is_success, r.error_message or r.message

        stamp = await _stamp(vg_client, test_space, test_graph, child_uri)
        _, objs = _frame("winner", uri=child_uri)
        # Rewrites of the existing child through UPSERT under the parent: the
        # same `POST /kgframes?parent_uri=` route `create_child_frames` uses,
        # which always sends create — refused for an existing frame once
        # `issues/256` item 3 is switched on.
        r = await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, parent_uri=frame,
            objects=objs, if_unmodified_since=stamp, operation_mode="upsert")
        assert r.is_success, r.error_message or r.message

        _, objs = _frame("loser", uri=child_uri)
        # Rewrites of the existing child through UPSERT under the parent: the
        # same `POST /kgframes?parent_uri=` route `create_child_frames` uses,
        # which always sends create — refused for an existing frame once
        # `issues/256` item 3 is switched on.
        r = await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, parent_uri=frame,
            objects=objs, if_unmodified_since=stamp, operation_mode="upsert")
        assert r.is_conflict is True, (
            f"status={r.status!r} message={r.message or r.error_message!r}")

    async def test_child_frames_refuses_a_stale_stamp(
            self, vg_client, test_space, test_graph, frame):
        # A child frame is its own frame and carries its own version, so the
        # precondition is about the CHILD being written, not the parent.
        child_uri, child = _frame("c0")
        r = await vg_client.kgframes.create_child_frames(
            space_id=test_space, graph_id=test_graph,
            parent_frame_uri=frame, objects=child)
        assert r.is_success, r.error_message or r.message

        stamp = await _stamp(vg_client, test_space, test_graph, child_uri)
        _, objs = _frame("winner", uri=child_uri)
        r = await vg_client.kgframes.update_child_frames(
            space_id=test_space, graph_id=test_graph,
            parent_frame_uri=frame, objects=objs, if_unmodified_since=stamp)
        assert r.is_success, r.error_message or r.message

        _, objs = _frame("loser", uri=child_uri)
        r = await vg_client.kgframes.update_child_frames(
            space_id=test_space, graph_id=test_graph,
            parent_frame_uri=frame, objects=objs, if_unmodified_since=stamp)
        assert r.is_conflict is True, (
            f"status={r.status!r} message={r.message or r.error_message!r}")
