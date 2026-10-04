"""What both frame delete routes answer (`issues/256`).

`kg_impl/frame_delete.delete_frames` turns what the locked subtree delete did
into the response, for `/kgentities/kgframes` and `/kgframes` alike. Driven here
with a stub adapter, because the question is the MAPPING — every outcome gets
its own status, and nothing that did not delete reports a deletion — not
anything about SQL. The delete itself is exercised through the API in
`tests/api/test_delete_guards_and_scope.py`.
"""

from __future__ import annotations

import pytest

from vitalgraph.kg_impl.frame_delete import delete_frames
from vitalgraph.kg_impl.kg_backend_utils import (
    AmbiguousStamp, DeleteRefused, FrameSubtreeDelete, StaleWrite)

pytestmark = pytest.mark.asyncio


class _Adapter:
    """Answers `delete_frame_subtrees` with a canned result or exception."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    async def delete_frame_subtrees(self, space_id, graph_id, roots, **kw):
        self.calls.append((roots, kw))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


async def _run(outcome, roots=("urn:f1",), **kw):
    adapter = _Adapter(outcome)
    resp, removed = await delete_frames(adapter, "sp", "urn:g", list(roots),
                                        recursive=False, **kw)
    return adapter, resp, removed


async def test_a_delete_reports_what_it_deleted_and_hands_over_the_members():
    _, resp, removed = await _run(FrameSubtreeDelete(
        ["urn:f1"], [], ["urn:f1", "urn:s1", "urn:e1"]))
    assert resp.status.value == "deleted"
    assert resp.deleted_uris == ["urn:f1"]
    assert resp.deleted_count == 1
    assert removed == ["urn:f1", "urn:s1", "urn:e1"], (
        "auto-sync needs every subject removed, not only the frames")


async def test_absent_alongside_deleted_is_still_deleted_and_named():
    _, resp, _ = await _run(FrameSubtreeDelete(["urn:f1"], ["urn:f2"], ["urn:f1"]),
                            roots=("urn:f1", "urn:f2"))
    assert resp.status.value == "deleted"
    assert resp.absent_uris == ["urn:f2"]


async def test_nothing_there_is_no_op_not_a_failure():
    _, resp, removed = await _run(FrameSubtreeDelete([], ["urn:f1"], []))
    assert resp.status.value == "no_op"
    assert resp.success is True
    assert resp.absent_uris == ["urn:f1"]
    assert removed == []


@pytest.mark.parametrize("exc, status", [
    (DeleteRefused("belongs to entity X"), "invalid_request"),
    (StaleWrite("urn:e", "a", "b"), "conflict"),
    (AmbiguousStamp("urn:e", ["a", "b"]), "store_failed"),
    (RuntimeError("connection reset"), "store_failed"),
], ids=["refused", "stale", "undecidable", "failed"])
async def test_nothing_deleted_never_reads_as_deleted(exc, status):
    _, resp, removed = await _run(exc)
    assert resp.status.value == status
    assert resp.success is False
    assert resp.deleted_count == 0 and resp.deleted_uris == []
    assert removed == []
    assert "Successfully" not in resp.message


async def test_one_stamp_for_two_standalone_roots_is_refused_before_the_delete():
    adapter, resp, _ = await _run(FrameSubtreeDelete([], [], []),
                                  roots=("urn:f1", "urn:f2"),
                                  if_unmodified_since="t")
    assert resp.status.value == "invalid_request"
    assert adapter.calls == [], "the delete ran for a request it should refuse"


async def test_the_standalone_guard_is_the_root_frame():
    adapter, _, _ = await _run(FrameSubtreeDelete(["urn:f1"], [], ["urn:f1"]),
                               if_unmodified_since="t")
    assert adapter.calls[0][1]["guard_subject"] == "urn:f1"


async def test_the_entity_route_guards_on_the_entity_whatever_it_names():
    adapter, resp, _ = await _run(
        FrameSubtreeDelete(["urn:f1", "urn:f2"], [], ["urn:f1", "urn:f2"]),
        roots=("urn:f1", "urn:f2"), owner_entity_uri="urn:e",
        if_unmodified_since="t")
    assert resp.status.value == "deleted"
    assert adapter.calls[0][1]["guard_subject"] == "urn:e"
