"""Every broad handler between the guard and the caller lets `StaleWrite` past.

`issues/253`. The stale-write guard raises deep in the write path and the answer
is only useful at the top: the endpoint turns it into `status="conflict"`, which
is what tells a caller to re-read and merge rather than give up or replay the
same losing write.

Four functions sit between the two, and all four end in `except Exception: return
False`. So the refusal arrived over HTTP as `store_failed` — indistinguishable
from a real store failure — until each of them was taught to re-raise. The
mechanism and its endpoint mapping were both correct and the contract was still
broken, which is why this is asserted structurally rather than left to the one
API test that happens to cover the create path.

Read over the AST, not the text: a handler mentioning `StaleWrite` in a comment
is not a handler, and this repo has twice had a literal-string guard tripped by
its own prose.
"""
from __future__ import annotations

import ast
import inspect

import pytest

from vitalgraph.endpoint import kgentities_endpoint, kgframes_endpoint
from vitalgraph.kg_impl import (
    kgentity_frame_create_impl, kgentity_frame_update_impl, kgframe_create_impl)

# (module, function) pairs on the frame-write path, from the guard upwards.
ON_THE_PATH = [
    (kgentity_frame_create_impl, "execute_frame_creation"),
    (kgentity_frame_create_impl, "execute_atomic_frame_update"),
    (kgentity_frame_create_impl, "create_entity_frame"),
    (kgentity_frame_update_impl, "update_frames"),
    (kgentities_endpoint, "_create_or_update_frames"),
    (kgentities_endpoint, "_update_entity_frames"),
    # The standalone-frame routes, which guard on the FRAME because they have no
    # owning entity to guard on (`issues/253`).
    (kgframe_create_impl, "execute_frame_creation"),
    (kgframe_create_impl, "execute_atomic_frame_update"),
    (kgframe_create_impl, "create_frame"),
    (kgframes_endpoint, "_create_frames"),
    (kgframes_endpoint, "_create_frame_slots"),
    (kgframes_endpoint, "_update_frame_slots"),
    # The mode handlers sit BETWEEN the processor and `_create_frames`, and each
    # turns anything it catches into a 500. They turned the refusal into one too.
    (kgframes_endpoint, "_handle_create_mode"),
    (kgframes_endpoint, "_handle_update_mode"),
    (kgframes_endpoint, "_handle_upsert_mode"),
]


def _function(module, name):
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    pytest.fail(f"{module.__name__}.{name} not found — was it renamed?")


def _handler_names(handler):
    """The exception names one `except` clause catches; () means bare."""
    t = handler.type
    if t is None:
        return ()
    parts = t.elts if isinstance(t, ast.Tuple) else [t]
    return tuple(p.id if isinstance(p, ast.Name) else getattr(p, "attr", "?")
                 for p in parts)


# The calls that can raise `StaleWrite`, directly or by re-raise. A broad
# handler only matters if one of these sits inside its `try`: both endpoint
# functions also wrap the non-critical post-write `touch_entity_modification_time`
# in `except Exception`, and that one is correct — nothing it calls can refuse.
WRITE_CALLS = {
    "update_subjects_graph", "update_quads",
    "execute_frame_creation", "execute_atomic_frame_update",
    "create_entity_frame", "update_frames",
    "_create_or_update_frames", "_update_entity_frames",
    # standalone-frame path
    "create_frame", "_store_frame_slots_in_backend",
    "_update_frame_slots_in_backend",
    "_handle_create_mode", "_handle_update_mode", "_handle_upsert_mode",
}


def _reaches_the_write(try_node):
    for node in ast.walk(try_node):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = getattr(f, "attr", None) or getattr(f, "id", None)
        if name in WRITE_CALLS:
            return True
    return False


class TestTheRefusalSurvivesTheClimb:
    @pytest.mark.parametrize("module,func", ON_THE_PATH,
                             ids=[f"{m.__name__.rsplit('.', 1)[-1]}.{f}"
                                  for m, f in ON_THE_PATH])
    def test_a_broad_handler_is_preceded_by_a_stale_write_handler(self, module, func):
        fn = _function(module, func)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Try) or not _reaches_the_write(node):
                continue
            seen_stale = False
            for handler in node.handlers:
                names = _handler_names(handler)
                if "StaleWrite" in names:
                    seen_stale = True
                    continue
                if not names or set(names) & {"Exception", "BaseException"}:
                    assert seen_stale, (
                        f"{module.__name__}.{func}: the handler at line "
                        f"{handler.lineno} swallows StaleWrite, so a refused "
                        f"write is reported as a generic failure")

    def test_the_refusal_is_re_raised_rather_than_translated(self):
        # Re-raised, not turned into a `False` return or a different exception:
        # the entity URI and both stamps live on the exception, and the endpoint
        # puts them in the message a caller reads.
        ANSWERS = {"_create_or_update_frames", "_update_entity_frames",
                   "_create_frames", "_create_frame_slots", "_update_frame_slots"}
        for module, func in ON_THE_PATH:
            if func in ANSWERS:
                continue            # the top of the path — it ANSWERS, by design
            fn = _function(module, func)
            for node in ast.walk(fn):
                for handler in getattr(node, "handlers", []):
                    if "StaleWrite" not in _handler_names(handler):
                        continue
                    body = [s for s in handler.body
                            if not isinstance(s, ast.Expr)]
                    assert len(body) == 1 and isinstance(body[0], ast.Raise), (
                        f"{module.__name__}.{func}: the StaleWrite handler at "
                        f"line {handler.lineno} does something other than "
                        f"re-raise")
                    assert body[0].exc is None, (
                        f"{module.__name__}.{func}: re-raise bare, so the "
                        f"original traceback and both stamps survive")

    @pytest.mark.parametrize("func", ["_create_or_update_frames",
                                      "_update_entity_frames"])
    def test_the_handler_imports_the_model_it_returns(self, func):
        """A handler cannot borrow an import from the body it is catching.

        The endpoint imports its response models function-locally, inside the
        `try`. That makes the name a LOCAL of the function, so an `except`
        handler referencing it hits `UnboundLocalError` — and the refusal came
        back as a 500 with the mapping sitting right there, correct and
        unreachable. Both handlers must import what they return.
        """
        fn = _function(kgentities_endpoint, func)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if "StaleWrite" not in _handler_names(handler):
                    continue
                returned = {
                    n.func.id for n in ast.walk(handler)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
                imported = {
                    a.asname or a.name for n in ast.walk(handler)
                    if isinstance(n, (ast.Import, ast.ImportFrom))
                    for a in n.names}
                missing = {r for r in returned if r.endswith("Response")} - imported
                assert not missing, (
                    f"{func}: the StaleWrite handler at line {handler.lineno} "
                    f"returns {sorted(missing)} without importing it — the "
                    f"body's import makes that name an unbound local here")

    def test_the_endpoint_answers_with_a_conflict(self):
        # The other end of the contract: having let it climb, the endpoint must
        # name it. `CONFLICT` is deliberately not a success status, so the
        # client's `is_success` is False on a 200.
        from vitalgraph.model.result_status import OperationStatus

        for module, n in ((kgentities_endpoint, 2), (kgframes_endpoint, 3)):
            src = inspect.getsource(module)
            assert src.count("except StaleWrite") == n, (
                f"{module.__name__}: every frame entry point must map the refusal")
            assert src.count("OperationStatus.CONFLICT") >= n
        assert OperationStatus.CONFLICT.value == "conflict"

    def test_an_ambiguous_precondition_is_not_a_conflict(self):
        # One stamp cannot cover several frames. Reported as INVALID_REQUEST, not
        # CONFLICT: a conflict says "re-read and retry" and this request would be
        # refused identically however fresh the stamp is.
        from vitalgraph.kg_impl.kg_backend_utils import AmbiguousPrecondition
        from vitalgraph.model.result_status import OperationStatus

        src = inspect.getsource(kgframes_endpoint)
        assert "except AmbiguousPrecondition" in src
        assert OperationStatus.INVALID_REQUEST not in __import__(
            "vitalgraph.model.result_status", fromlist=["_SUCCESS_STATUSES"]
        )._SUCCESS_STATUSES
        assert str(AmbiguousPrecondition(3)).count("3") >= 1
