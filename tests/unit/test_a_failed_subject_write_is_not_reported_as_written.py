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
to delete them rather than pin their behaviour. What remains covers the slot
paths — since 2026-10-04 (`issues/256`) ONE handler, `_write_frame_slots`, for
create, update and upsert on both slot routes; the two write helpers it replaced
are gone, so the guarantee is pinned on the handler itself.

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


class FakeAdapter:
    """The backend after a lock timeout (`accept=False`) or a write that lands.

    `update_subjects_graph` reports failure the only way it can, by returning
    False. Nothing exists yet, so create's precondition has nothing to refuse
    (the precondition runs inside the real transaction, not here)."""

    def __init__(self, accept):
        self.accept = accept
        self.calls = 0

    async def existing_subjects(self, space_id, graph_id, uris):
        return set()

    async def update_subjects_graph(self, space_id, graph_id, subject_uris,
                                    insert_quads, **kw):
        self.calls += 1
        return self.accept


@pytest.fixture
def endpoint():
    # The write path uses neither the space manager's real backend nor auth.
    return KGFramesEndpoint(space_manager=None, auth_dependency=None)


@pytest.fixture
def slot():
    s = KGSlot()
    s.URI = SLOT
    return s


def _wire(endpoint, monkeypatch, adapter):
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
    monkeypatch.setattr(module, "create_backend_adapter", lambda impl: adapter)
    monkeypatch.setattr(endpoint, "_schedule_auto_sync", lambda *a, **k: None)


def _quads_for(slot):
    from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list
    return graphobjects_to_quad_list([slot], GRAPH)


class TestTheHandlerReportsItAsADomainFault:
    """The decision: HTTP 200, `STORE_FAILED`, `success=false` — not a 500."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["create", "upsert", "update"])
    async def test_a_refused_write_is_store_failed_with_no_uris(
            self, endpoint, slot, monkeypatch, mode):
        adapter = FakeAdapter(accept=False)
        _wire(endpoint, monkeypatch, adapter)
        response = await endpoint._write_frame_slots(
            "sp", GRAPH, FRAME, _quads_for(slot), mode)

        assert adapter.calls == 1
        # No HTTPException: the handler must not let this become a 500.
        assert response.status == OperationStatus.STORE_FAILED
        # `success` is DERIVED from `status`, so this cannot drift.
        assert response.success is False
        if mode == "update":
            assert response.updated_count == 0 and not response.updated_uris
        else:
            assert response.created_count == 0 and not response.created_uris

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode,status", [
        ("create", OperationStatus.CREATED), ("upsert", OperationStatus.UPSERTED),
        ("update", OperationStatus.UPDATED)])
    async def test_a_write_that_lands_reports_what_it_wrote(
            self, endpoint, slot, monkeypatch, mode, status):
        # The check must not cost the success case its answer.
        _wire(endpoint, monkeypatch, FakeAdapter(accept=True))
        response = await endpoint._write_frame_slots(
            "sp", GRAPH, FRAME, _quads_for(slot), mode)
        assert response.status == status and response.success is True
        uris = response.updated_uris if mode == "update" else response.created_uris
        assert uris == [SLOT]
