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
import ast
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


# Routes whose server side compares `if_unmodified_since` (`issues/253`). Keyed
# by URL rather than by method name, because the question is which ENDPOINT the
# call reaches — four client methods POST to `/api/graphs/kgframes` under names
# that do not say so, and all four were missed on the first pass.
GUARDED_ROUTES = (
    "/api/graphs/kgentities/kgframes",
    "/api/graphs/kgframes",
    "/api/graphs/kgframes/kgslots",
)


def _writes_to_guarded_routes(module):
    """{method -> accepts if_unmodified_since} for every write reaching a guard."""
    tree = ast.parse(inspect.getsource(module))
    out = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        verbs, urls = set(), set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) in (
                    "_make_request", "_make_typed_request"):
                if n.args and isinstance(n.args[0], ast.Constant):
                    verbs.add(n.args[0].value)
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if getattr(t, "id", None) != "url":
                        continue
                    if isinstance(n.value, ast.Constant):
                        urls.add(n.value.value)
                    elif isinstance(n.value, ast.JoinedStr):
                        urls.add("".join(v.value for v in n.value.values
                                         if isinstance(v, ast.Constant)))
        if not ({"POST", "PUT"} & verbs):
            continue
        if not any(u in GUARDED_ROUTES for u in urls):
            continue
        names = [a.arg for a in fn.args.args + fn.args.kwonlyargs]
        out[fn.name] = "if_unmodified_since" in names
    return out


class TestEveryWriteThatCanBeRefusedCanAlsoOptIn:
    """A guard the client cannot reach is API surface and nothing else.

    Four methods POST to `/api/graphs/kgframes` — `create_kgframes_with_slots`,
    `update_kgframes_with_slots`, `create_child_frames`, `update_child_frames` —
    and none of their names mentions the route. All four were missed when the
    parameter was added to the obvious ones, so this asks the question by URL
    rather than by name, and the next method added to that route inherits it.
    """

    @pytest.mark.parametrize("modname", ["kgentities_endpoint", "kgframes_endpoint"])
    def test_no_guarded_write_is_missing_the_parameter(self, modname):
        from vitalgraph.client.endpoint import kgentities_endpoint, kgframes_endpoint
        module = {"kgentities_endpoint": kgentities_endpoint,
                  "kgframes_endpoint": kgframes_endpoint}[modname]
        writes = _writes_to_guarded_routes(module)
        assert writes, f"{modname}: found no writes to a guarded route — did a URL change?"
        missing = sorted(m for m, ok in writes.items() if not ok)
        assert not missing, (
            f"{modname}: these reach a route that compares if_unmodified_since "
            f"but cannot send it: {missing}")

    def test_it_is_sent_and_not_merely_accepted(self):
        # The same failure as `issues/240` and `issues/210`: a parameter taken and
        # dropped leaves the caller believing it is protected. Read over the AST,
        # not off the class — these are methods on endpoint classes and the
        # module namespace does not hold them.
        from vitalgraph.client.endpoint import kgentities_endpoint, kgframes_endpoint
        for module in (kgentities_endpoint, kgframes_endpoint):
            source = inspect.getsource(module)
            tree = ast.parse(source)
            bodies = {
                fn.name: ast.get_source_segment(source, fn)
                for fn in ast.walk(tree)
                if isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef))}
            for name in _writes_to_guarded_routes(module):
                assert "if_unmodified_since=if_unmodified_since" in bodies[name], (
                    f"{module.__name__}.{name} accepts the precondition and "
                    f"never sends it")


class TestANullListIsNotAMissingOne:
    """`get(k, default)` does not apply the default when the key is null.

    Four client methods read `response_data.get('updated_uri') or
    response_data.get('updated_uris', [None])[0]`. The server sends
    `updated_uris: null` when it has none, so the default never fired and `None[0]`
    raised `'NoneType' object is not subscriptable` — surfacing as a 500-shaped
    client error with the server's actual answer thrown away.

    A refused conditional write was simply the first response shaped that way
    (`updated_uri` empty, `updated_uris` null). The crash was already latent for
    any such response, which is why this is asserted on the pattern and not on
    the conflict.
    """

    def test_the_pattern_is_gone_everywhere(self):
        from vitalgraph.client.endpoint import kgframes_endpoint
        src = inspect.getsource(kgframes_endpoint)
        assert "get('updated_uris', [None])[0]" not in src
        assert "get(\"updated_uris\", [None])[0]" not in src

    def test_the_semantics_that_broke_it(self):
        # The distinction in one line, so the next reader does not have to
        # rediscover why the default looked sufficient.
        null_list = {"updated_uris": None}
        assert null_list.get("updated_uris", [None]) is None      # the bug
        assert (null_list.get("updated_uris") or [None])[0] is None  # the fix
        absent = {}
        assert absent.get("updated_uris", [None]) == [None]       # why it looked fine
