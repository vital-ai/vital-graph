"""A frame delete that fails must not report success. `issues/242`.

`DeleteFrameResult.success` was `len(deleted_frame_uris) > 0`, and that list is
appended in Phase 2 — DISCOVERY — before Phase 3 runs the batch delete. So it
answered "did we find anything to delete", not "was anything deleted". A failed
batch delete returned:

    success        True
    message        "Successfully deleted 2 frame graphs (7 components)"
    status         deleted          (hardcoded at the endpoint, `success` unread)
    deleted_count  2

Four fields, all wrong, and the only trace was a `fuseki_success=False` on a
retired second-store flag — so removing that flag (`issues/241`) is what exposed
this rather than caused it.

This is the `issues/215` shape on the write side: a killed READ was reported as
EMPTY, which is a SUCCESS status, so a 56s timeout and a genuinely empty space were
the same response. `OperationStatus.STORE_FAILED` already existed for the write
case, and `kgentities_endpoint.py:1356` already used it correctly — this path was
the outlier, twice.

These tests drive the processor directly with a stubbed batch delete, because the
question is the CONTRACT between phases, not anything about SPARQL or a database.
"""

from __future__ import annotations

import pytest

from vitalgraph.kg_impl.kgentity_frame_delete_impl import DeleteFrameResult


def test_the_result_carries_an_error_field_for_this():
    """The dataclass must be able to SAY it failed.

    Asserted because the fix relies on it: a result type with no error channel
    forces the caller to infer failure from a count, which is how the original
    defect was written.
    """
    r = DeleteFrameResult(success=False, deleted_frame_uris=[],
                          deleted_component_count=0, validation_results={},
                          message="x", error="batch delete reported failure")
    assert r.error == "batch delete reported failure"
    assert r.success is False


def test_success_is_not_derivable_from_the_discovered_uri_list():
    """The heart of it: a populated `deleted_frame_uris` with `success=False` must
    be a representable state.

    If it is not — if anything downstream re-derives success from that list — the
    defect comes straight back, because the list is populated during discovery and
    says nothing about whether the delete ran.
    """
    r = DeleteFrameResult(success=False, deleted_frame_uris=["urn:f1", "urn:f2"],
                          deleted_component_count=7, validation_results={},
                          message="Delete FAILED: ...", error="batch delete reported failure")
    assert r.deleted_frame_uris, "the attempted set is still reported"
    assert r.success is False, "but it was not a success"


def test_the_failure_message_does_not_claim_a_deletion():
    """`message` is user-facing (`http 200 for domain outcomes`: the outcome lives
    in the body), so a message beginning "Successfully deleted" on a failed delete
    is the wrong answer even when `success` is correct. Both were wrong before."""
    from vitalgraph.kg_impl import kgentity_frame_delete_impl as mod
    src = mod.__file__
    with open(src) as fh:
        text = fh.read()
    # The success branch may say "Successfully deleted"; the failure branch must not.
    fail_branch = text.split("elif batch_delete_failed:", 1)
    assert len(fail_branch) == 2, "the failure branch is gone — did the fix regress?"
    upto_else = fail_branch[1].split("else:", 1)[0]
    assert "Successfully deleted" not in upto_else, (
        "the batch-delete failure branch claims a successful deletion")
    assert "FAILED" in upto_else, "the failure branch does not say it failed"


@pytest.mark.parametrize("status_name", ["STORE_FAILED", "QUERY_FAILED"])
def test_the_failure_statuses_exist_and_are_not_successes(status_name):
    """The vocabulary this fix depends on. `QUERY_FAILED` is included because its
    own comment records the read-side version of this bug, and losing either one
    re-opens the question "what status does a failed write get?"."""
    from vitalgraph.model.result_status import OperationStatus, _SUCCESS_STATUSES
    status = getattr(OperationStatus, status_name)
    assert status not in _SUCCESS_STATUSES, (
        f"{status_name} maps to success=True, which would make a failed "
        f"operation read as a successful one")


def test_the_endpoint_does_not_hardcode_deleted_for_this_path():
    """Guards the second half of the fix.

    Making `success` correct changed nothing on its own: both endpoint call sites
    hardcoded `status=OperationStatus.DELETED` and never read it. A future edit that
    reverts to a single unconditional response would be invisible to every test
    above, so this asserts on the source of the mapping itself.
    """
    from vitalgraph.endpoint import kgentities_endpoint as mod
    lines = open(mod.__file__).read().split("\n")

    # Every site that reports the DISCOVERED set as deleted...
    sites = [i for i, l in enumerate(lines)
             if "deleted_count=len(result.deleted_frame_uris)," in l]
    assert sites, "the frame-delete success response is gone — did the fix regress?"

    # ...must have a STORE_FAILED response guarding it just above, so a failed
    # delete cannot fall through to it.
    for i in sites:
        window = "\n".join(lines[max(0, i - 25):i])
        assert "OperationStatus.STORE_FAILED" in window, (
            f"{mod.__file__}:{i + 1} reports deleted_count from the DISCOVERED "
            f"uri list with no STORE_FAILED guard above it — a failed delete "
            f"would be reported as deleted (`issues/242`)")


# ---------------------------------------------------------------------------
# `issues/243` — the sibling delete paths 242 explicitly did NOT clear.
# ---------------------------------------------------------------------------

def test_the_entity_batch_delete_status_follows_the_outcome():
    """`DELETE /kgentities?uri_list=a,b,c` must not report `deleted` when nothing
    was deleted.

    Unlike `issues/242`, `deleted_count` here was already honest — it counts URIs
    whose delete returned ok — so only `status` lied, and it lied in the direction
    that matters: a batch where every delete failed came back `status=deleted` with
    "Successfully deleted 0 KG entities".

    Structural, for the same reason as the frame-delete cell above: the three
    branches need a backend to exercise, and the regression to guard against is
    someone collapsing them back into one unconditional response.
    """
    from vitalgraph.endpoint import kgentities_endpoint as mod
    text = open(mod.__file__).read()

    marker = "deleted_uris=deleted_uris_list"
    assert marker in text, "the entity batch-delete response is gone — fix regressed?"

    # The response must be reached through a status decision, not a literal.
    head = text.split(marker)[0]
    window = head[-2600:]
    for needed in ("OperationStatus.PARTIAL",
                   "OperationStatus.STORE_FAILED",
                   "OperationStatus.DELETED"):
        assert needed in window, (
            f"{needed} is not part of the entity batch-delete status decision — "
            f"a failed or partial batch can be reported as a success (`issues/243`)")
    assert "status=status" in window, (
        "the response takes a literal status again rather than the computed one")


def test_partial_is_used_somewhere_now():
    """`OperationStatus.PARTIAL` existed and was dead.

    Asserted on its own because "the enum has a member for this" is what made the
    old behaviour indefensible rather than merely imprecise — the vocabulary was
    there and unused, exactly like `STORE_FAILED` in `issues/242`.
    """
    from vitalgraph.endpoint import kgentities_endpoint as mod
    assert "OperationStatus.PARTIAL" in open(mod.__file__).read()


def test_the_unreachable_frame_delete_is_gone_not_repaired():
    """`issues/243`/`issues/184`: a path that has never executed has no behaviour
    to preserve.

    `kgentities_endpoint._delete_frame_by_uri` was called by nothing and was the
    only caller of `KGSparqlQueryProcessor.delete_frame`, which raised `TypeError`
    on every invocation. Both are deleted. This asserts they stay deleted, because
    the tempting repair — add the missing argument — would resurrect a function
    carrying the `242` defect twice over.
    """
    from vitalgraph.endpoint import kgentities_endpoint as ep
    from vitalgraph.kg_impl import kg_sparql_query as q
    from vitalgraph.endpoint.kgentities_endpoint import KGEntitiesEndpoint
    from vitalgraph.kg_impl.kg_sparql_query import KGSparqlQueryProcessor

    assert not hasattr(KGEntitiesEndpoint, "_delete_frame_by_uri"), (
        "the unreachable frame-delete is back on KGEntitiesEndpoint; the LIVE one "
        "is KGFramesEndpoint._delete_frame_by_uri (`issues/243`)")
    assert not hasattr(KGSparqlQueryProcessor, "delete_frame"), (
        "KGSparqlQueryProcessor.delete_frame is back — it could never succeed and "
        "carried the issues/242 defect twice (`issues/243`)")

    # and the live one is still there, so the capability was not lost with it
    from vitalgraph.endpoint.kgframes_endpoint import KGFramesEndpoint
    assert hasattr(KGFramesEndpoint, "_delete_frame_by_uri")
