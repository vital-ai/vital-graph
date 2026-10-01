"""A write that failed must not be reported as written (`issues/253`).

`update_subjects_graph` reports failure by returning False — a lock timeout on a
busy entity is the production case — and five call sites discarded it and
returned the URIs they had INTENDED to write. On the two live slot paths that
became `SlotCreateResponse(status=CREATED, created_count=N)` for a write that
never happened: `issues/242`'s shape ("a failed frame delete reports success in
four fields") and `issues/245`'s ("logs the URIs it SUBMITTED, not what was
stored").

THREE OF THOSE SITES ARE GONE, not fixed. `_store_frames_in_backend` and the
relation write helpers were DELETED on 2026-10-01 as REDUNDANT: each duplicated
a live path that already does the job and already checks its write —
`KGFrameCreateProcessor.create_frame` for frames, and
`KGRelationsCreateProcessor.create_or_update_relations` (via `store_objects`,
checking `result.success`) for relations. Nothing calls the versions that were
removed, so the guard they carried could never fire and could not be exercised
through the API.

This file used to test all three, and the docstring it gave them admitted they
were "reachable only through helpers nothing calls today" — which was the moment
to delete them rather than pin their behaviour. What remains covers the two live
slot paths.

AND IT STAYS A 200, DELIBERATELY. `issues/253` weighed 503 + `Retry-After` —
which the client's own retry policy would have retried unaided — and chose to
keep the status code: a refused write is a `STORE_FAILED` domain fault in an HTTP
200 body, which derives `success=false` (`model/result_status.py`). So the helper
raises a TYPED exception and the handler turns it into that body. A plain
`RuntimeError` would have fallen through to the handler's `except Exception` and
become a 500 — the contract this codebase deliberately does not use here, which
is why the exception type is asserted and not just the raising.

"Not reported as success" and "not reported as a server error" are two different
claims, so both are tested.
"""
import pytest

from ai_haley_kg_domain.model.KGSlot import KGSlot

from vitalgraph.endpoint.impl.impl_utils import SubjectWriteFailed
from vitalgraph.endpoint.kgframes_endpoint import KGFramesEndpoint
from vitalgraph.model.result_status import OperationStatus

GRAPH = "urn:test:graph"
FRAME = "http://vital.ai/haley.ai/domain/KGFrame/frame-1"
SLOT = "http://vital.ai/haley.ai/domain/KGSlot/slot-1"


class RefusingBackend:
    """Stands in for the backend after a lock timeout: the write did not happen,
    and `update_subjects_graph` says so the only way it can."""

    def __init__(self):
        self.calls = 0

    async def update_subjects_graph(self, space_id, graph_id, subject_uris,
                                    insert_quads, lock_uris=None, conn=None,
                                    if_unmodified_since=None,
                                    guard_subject=None, stamp_subjects=None):
        self.calls += 1
        return False


class AcceptingBackend(RefusingBackend):
    async def update_subjects_graph(self, space_id, graph_id, subject_uris,
                                    insert_quads, lock_uris=None, conn=None,
                                    if_unmodified_since=None,
                                    guard_subject=None, stamp_subjects=None):
        self.calls += 1
        return True


@pytest.fixture
def endpoint():
    # The write helpers use neither the space manager nor auth.
    return KGFramesEndpoint(space_manager=None, auth_dependency=None)


@pytest.fixture
def slot():
    s = KGSlot()
    s.URI = SLOT
    return s


class TestTheHelpersRaise:
    """Where the result was being dropped."""

    @pytest.mark.asyncio
    async def test_a_refused_slot_store_raises(self, endpoint, slot):
        backend = RefusingBackend()
        with pytest.raises(SubjectWriteFailed, match="slot write"):
            await endpoint._store_frame_slots_in_backend(
                backend, "sp", GRAPH, [slot])
        assert backend.calls == 1

    @pytest.mark.asyncio
    async def test_a_refused_slot_update_raises(self, endpoint, slot):
        backend = RefusingBackend()
        with pytest.raises(SubjectWriteFailed, match="slot update"):
            await endpoint._update_frame_slots_in_backend(
                backend, "sp", GRAPH, [slot])
        assert backend.calls == 1

    @pytest.mark.asyncio
    async def test_the_happy_path_still_returns_the_uris(self, endpoint, slot):
        # The check must not cost the success case its answer.
        backend = AcceptingBackend()
        assert await endpoint._store_frame_slots_in_backend(
            backend, "sp", GRAPH, [slot]) == [SLOT]
        assert await endpoint._update_frame_slots_in_backend(
            backend, "sp", GRAPH, [slot]) == [SLOT]


def _stub_handler(endpoint, monkeypatch, *, store_raises, slot_exists=False):
    """Wire the two slot handlers up to a refusing (or accepting) write.

    Everything stubbed here is a round trip the mapping under test does not
    depend on; the write itself is the subject. `slot_exists` differs by handler
    and is not incidental — CREATE refuses a slot that exists, UPDATE refuses one
    that does not, so a single value would make one of the two tests assert a
    precondition instead of the mapping.
    """
    from vitalgraph.endpoint import kgframes_endpoint as module

    class FakeSpaceImpl:
        def get_db_space_impl(self):
            return object()

    class FakeRecord:
        space_impl = FakeSpaceImpl()

    class FakeSpaceManager:
        async def get_space_or_load(self, space_id):
            return FakeRecord()

    endpoint.space_manager = FakeSpaceManager()
    monkeypatch.setattr(module, "create_backend_adapter", lambda impl: object())

    async def _frame_exists(*a, **k):
        return True

    async def _slot_exists(*a, **k):
        return slot_exists

    async def _write(*a, **k):
        if store_raises:
            raise SubjectWriteFailed("slot write", 1)
        return [SLOT]

    monkeypatch.setattr(endpoint, "_frame_exists_in_backend", _frame_exists)
    monkeypatch.setattr(endpoint, "_slot_exists_in_backend", _slot_exists)
    monkeypatch.setattr(endpoint, "_store_frame_slots_in_backend", _write)
    monkeypatch.setattr(endpoint, "_update_frame_slots_in_backend", _write)
    monkeypatch.setattr(endpoint, "_schedule_auto_sync", lambda *a, **k: None)
    monkeypatch.setattr(endpoint, "_set_slot_frame_relationships", lambda *a, **k: None)
    monkeypatch.setattr(endpoint, "_create_frame_slot_edges",
                        lambda frame_uri, slots, objs: list(objs))


def _quads_for(slot):
    from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list
    return graphobjects_to_quad_list([slot], GRAPH)


class TestTheHandlerReportsItAsADomainFault:
    """The decision: HTTP 200, `STORE_FAILED`, `success=false` — not a 500."""

    @pytest.mark.asyncio
    async def test_create_returns_store_failed_and_no_uris(
            self, endpoint, slot, monkeypatch):
        from vitalgraph.endpoint.kgframes_endpoint import OperationMode

        _stub_handler(endpoint, monkeypatch, store_raises=True)
        response = await endpoint._create_frame_slots(
            "sp", GRAPH, FRAME, _quads_for(slot), OperationMode.CREATE, {})

        # No HTTPException: the handler must not let this become a 500.
        assert response.status == OperationStatus.STORE_FAILED
        # `success` is DERIVED from `status`, so this cannot drift.
        assert response.success is False
        assert response.created_count == 0
        assert not response.created_uris

    @pytest.mark.asyncio
    async def test_update_returns_store_failed_and_no_uris(
            self, endpoint, slot, monkeypatch):
        _stub_handler(endpoint, monkeypatch, store_raises=True,
                      slot_exists=True)
        response = await endpoint._update_frame_slots(
            "sp", GRAPH, FRAME, _quads_for(slot), {})

        assert response.status == OperationStatus.STORE_FAILED
        assert response.success is False
        assert response.updated_count == 0

    @pytest.mark.asyncio
    async def test_a_write_that_lands_still_reports_created(
            self, endpoint, slot, monkeypatch):
        from vitalgraph.endpoint.kgframes_endpoint import OperationMode

        _stub_handler(endpoint, monkeypatch, store_raises=False)
        response = await endpoint._create_frame_slots(
            "sp", GRAPH, FRAME, _quads_for(slot), OperationMode.CREATE, {})

        assert response.status == OperationStatus.CREATED
        assert response.success is True
        assert response.created_uris == [SLOT]
