"""The client speaks the request and response changes this issue introduced.

`issues/253`. Two things changed in the contract, and the client has to carry
both ends:

REQUEST — `if_unmodified_since` on the entity-frame writes, so a caller can say
"only if nobody moved it since I read it". Without the client sending it, the
server-side guard is unreachable.

RESPONSE — `status="conflict"` when the write is refused for that reason. It
arrives in a 200 body, per this codebase's convention, so nothing about the HTTP
status reveals it.
"""
import inspect

import pytest

from vitalgraph.client.endpoint.kgentities_endpoint import KGEntitiesEndpoint
from vitalgraph.client.response.client_response import VitalGraphResponse
from vitalgraph.client.retry import classify_status, FailureClass
from vitalgraph.model.result_status import OperationStatus, _SUCCESS_STATUSES


def _r(status):
    return VitalGraphResponse(error_code=0, status=status, status_code=200,
                              message="x")


class TestTheRequestSide:
    @pytest.mark.parametrize("method", ["create_entity_frames",
                                        "update_entity_frames"])
    def test_the_write_accepts_the_precondition(self, method):
        params = inspect.signature(getattr(KGEntitiesEndpoint, method)).parameters
        assert "if_unmodified_since" in params
        # Optional, because every existing caller passes nothing and must keep
        # the previous last-writer-wins behaviour.
        assert params["if_unmodified_since"].default is None

    @pytest.mark.parametrize("method", ["create_entity_frames",
                                        "update_entity_frames"])
    def test_it_is_actually_sent_and_not_just_accepted(self, method):
        # A parameter that is accepted and dropped is worse than none: the caller
        # believes it is protected. `issues/240` and `issues/210` are two
        # instances of exactly that in this codebase.
        src = inspect.getsource(getattr(KGEntitiesEndpoint, method))
        assert "if_unmodified_since=if_unmodified_since" in src


class TestTheResponseSide:
    def test_a_conflict_is_not_a_success(self):
        assert OperationStatus.CONFLICT not in _SUCCESS_STATUSES
        assert _r("conflict").is_success is False

    def test_a_conflict_is_distinguishable_from_an_ordinary_failure(self):
        # The two want OPPOSITE responses: a conflict means re-read and retry, a
        # store_failed means retrying will not change the outcome. Both are
        # `is_error`, so a caller that cannot tell them apart either drops a
        # write it could have saved or loops on one it cannot.
        assert _r("conflict").is_conflict is True
        assert _r("store_failed").is_conflict is False
        assert _r("created").is_conflict is False
        assert _r("conflict").is_error and _r("store_failed").is_error

    def test_the_transport_will_not_blindly_replay_a_conflict(self):
        # It arrives as HTTP 200, which the retry policy never retries — correct,
        # because replaying with the same stale precondition is refused
        # identically. Re-reading is the caller's job, not the transport's.
        assert classify_status(200) is FailureClass.FATAL

    def test_a_zero_count_refusal_keeps_its_status(self):
        # `update_entity_frames` short-circuits on "nothing was updated" and
        # built a response without the server's status, so a refusal reached the
        # caller as `status=None` — `is_conflict` False on the one response that
        # means re-read and merge. The count is the same for a refusal and a
        # failure; only the status separates them.
        src = inspect.getsource(KGEntitiesEndpoint.update_entity_frames)
        zero = src[src.index("frames_updated == 0"):]
        zero = zero[:zero.index("deserialize_response_to_graphobjects")]
        assert "status=response_data.get('status')" in zero \
            or 'status=response_data.get("status")' in zero, (
                "the zero-count branch must carry the server's status")

    def test_the_client_derives_its_success_set_from_the_server_enum(self):
        # Why `conflict` needed no client-side list edit, and why the next status
        # will not either. A hand-copied list is how the two drift.
        from vitalgraph.client.response.client_response import _SUCCESS_STATUS_VALUES
        assert _SUCCESS_STATUS_VALUES == frozenset(s.value for s in _SUCCESS_STATUSES)
