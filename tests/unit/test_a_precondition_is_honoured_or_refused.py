"""A precondition is either compared or refused — never quietly dropped.

Review findings on `issues/253`'s conditional write. Each of these was LATENT —
no live call site reaches them — and each is the same shape as the defect the
feature exists to prevent: a write that did not do what the caller asked,
reported as a success.

1. `if_unmodified_since` with nothing to compare against was SKIPPED, so the
   write proceeded unconditionally and answered success.
2. The stamp read used `LIMIT 1` with no `ORDER BY`, so a violated single-valued
   invariant made the guard pass or fail on whichever row the scan reached
   first — nondeterministic, for a check whose only job is to be decisive.

Both now raise. The third finding is structural and lives in
`test_teardown_sweeps_are_independent` below.
"""
from __future__ import annotations

import ast
import inspect

import pytest

from vitalgraph.kg_impl.kg_backend_utils import (
    AmbiguousStamp, StaleWrite, UnguardableWrite, _compare_stamp)


# The functions that ANSWER a refused conditional write. Each already maps
# `StaleWrite`; each must map `GuardUnsatisfiable` too, or it reaches a broad
# handler and becomes the 500 the convention forbids.
ENTRY_POINTS = [
    ("vitalgraph.endpoint.kgentities_endpoint", "_create_or_update_frames"),
    ("vitalgraph.endpoint.kgentities_endpoint", "_update_entity_frames"),
    ("vitalgraph.endpoint.kgframes_endpoint", "_create_frames"),
    # One handler for create, update and upsert on both slot routes since
    # `issues/256` (2026-10-04); it replaced `_create_frame_slots` and
    # `_update_frame_slots`.
    ("vitalgraph.endpoint.kgframes_endpoint", "_write_frame_slots"),
    ("vitalgraph.endpoint.kgframes_endpoint", "_delete_frame_slots"),
]


def _handler_catching(module_name, func_name, exc_name):
    """The `except` clause in *func_name* that catches *exc_name*, or None.

    Over the AST, because the handlers are not written uniformly: two catch it
    as `except (SubjectWriteFailed, GuardUnsatisfiable)` and three as a bare
    `except GuardUnsatisfiable`. A string count sees one of those shapes and
    silently misses the other — which it did, on the first run of this test.
    """
    mod = __import__(module_name, fromlist=[module_name.rsplit('.', 1)[-1]])
    src = inspect.getsource(mod)
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
               and n.name == func_name), None)
    assert fn is not None, f"{module_name}.{func_name} not found — renamed?"
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        for h in node.handlers:
            t = h.type
            if t is None:
                continue
            parts = t.elts if isinstance(t, ast.Tuple) else [t]
            if any(getattr(pp, "id", None) == exc_name for pp in parts):
                return src, h
    return src, None


class FakeConn:
    """Only what `_compare_stamp` touches."""

    def __init__(self, stamps):
        self._stamps = list(stamps)
        self.queries = []

    async def fetch(self, sql, *args):
        self.queries.append(sql)
        return [{"stamp": s} for s in self._stamps]


class TestAnAmbiguousStampIsRefused:
    @pytest.mark.asyncio
    async def test_two_stamps_raise_rather_than_picking_one(self):
        conn = FakeConn(["2026-10-01T00:00:00+00:00", "2026-10-02T00:00:00+00:00"])
        with pytest.raises(AmbiguousStamp) as e:
            await _compare_stamp(conn, "sp", "urn:g", "urn:e",
                                 "2026-10-01T00:00:00+00:00")
        # Both values named: the next person has to fix the data, and needs to
        # know what is in it.
        assert "2" in str(e.value)
        assert e.value.subject_uri == "urn:e"
        assert len(e.value.found) == 2

    @pytest.mark.asyncio
    async def test_it_is_not_reported_as_a_conflict(self):
        # A conflict tells the caller to re-read and retry. Re-reading cannot
        # resolve duplicate stamps, so answering CONFLICT here would be an
        # infinite loop. It must be a distinct, loud failure.
        assert not issubclass(AmbiguousStamp, StaleWrite)

    @pytest.mark.asyncio
    async def test_the_read_asks_for_two_rows_so_it_can_tell(self):
        conn = FakeConn(["2026-10-01T00:00:00+00:00"])
        await _compare_stamp(conn, "sp", "urn:g", "urn:e",
                             "2026-10-01T00:00:00+00:00")
        # `LIMIT 1` cannot distinguish "one stamp" from "the first of several".
        assert "LIMIT 2" in conn.queries[0]

    @pytest.mark.asyncio
    async def test_one_stamp_still_behaves_exactly_as_before(self):
        conn = FakeConn(["2026-10-01T00:00:00+00:00"])
        await _compare_stamp(conn, "sp", "urn:g", "urn:e",
                             "2026-10-01T00:00:00+00:00")        # matches: fine
        with pytest.raises(StaleWrite):
            await _compare_stamp(conn, "sp", "urn:g", "urn:e", "something-else")

    @pytest.mark.asyncio
    async def test_no_stamp_is_a_mismatch_not_an_ambiguity(self):
        # An unstamped subject is a legitimate state — a frame written before
        # this feature. A caller claiming a stamp for it is stale, not ambiguous.
        with pytest.raises(StaleWrite):
            await _compare_stamp(FakeConn([]), "sp", "urn:g", "urn:e", "x")


class TestAPreconditionWithNothingToCompareIsRefused:
    def test_the_guard_raises_instead_of_skipping(self):
        """The branch holding the comparison must not be gated on having a subject.

        Asserting on behaviour would need a live pool and a transaction, so this
        pins the structure — and it pins it over the AST, NOT as text. A text
        search fails here for a reason worth recording: the fix's own comment
        QUOTES the old condition to explain it, so `"if _guard and ..." not in
        source` trips on the prose. That is the third time in this issue a
        literal-string guard has been tripped by the explanation of the thing it
        guards against.
        """
        from vitalgraph.kg_impl import kg_backend_utils

        src = inspect.getsource(kg_backend_utils)
        tree = ast.parse(src)
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
            and n.name == "update_subjects_graph")

        # The `if` whose body performs the comparison.
        def mentions(node, name):
            return any(
                getattr(c.func, "id", None) == name
                or getattr(c.func, "attr", None) == name
                for c in ast.walk(node) if isinstance(c, ast.Call))

        branch = next(
            (n for n in ast.walk(fn)
             if isinstance(n, ast.If) and mentions(n, "_compare_stamp")), None)
        assert branch is not None, "no branch performs the stamp comparison"

        # Its condition must be about the PRECONDITION only. A `BoolOp` adding
        # `_guard` is what made a missing subject skip the check silently.
        assert not isinstance(branch.test, ast.BoolOp), (
            "the comparison branch is gated on more than "
            "`if_unmodified_since is not None`; if it also requires a subject, "
            "a write with no subject skips the check and reports success")

        # And the missing-subject case must RAISE inside that branch.
        raises = [
            n for n in ast.walk(branch)
            if isinstance(n, ast.Raise)
            and getattr(getattr(n.exc, "func", None), "id", None)
            == "UnguardableWrite"]
        assert raises, (
            "a precondition with no subject to compare against must raise, "
            "not be dropped")

    def test_it_is_distinct_from_the_callers_mistake(self):
        # `AmbiguousPrecondition` is the caller sending one stamp for several
        # frames — answered INVALID_REQUEST, because the caller must change what
        # it SENDS. This is a wiring error in a call site, so it is a different
        # status; it is NOT a different status CLASS. Both are HTTP 200.
        from vitalgraph.kg_impl.kg_backend_utils import AmbiguousPrecondition

        assert not issubclass(UnguardableWrite, AmbiguousPrecondition)

    def test_it_answers_in_the_body_and_not_with_a_500(self):
        """The convention: 200 with a status, unless the SERVICE is failing.

        This assertion replaces one that said the opposite. An earlier version
        of this test — and two docstrings two files away — claimed a 500 was
        correct here, and a reviewer reading them recommended adding a bare
        `raise` that would have produced exactly that. `result_status.py` is
        unambiguous: `STORE_FAILED` is "write failed for a describable data
        reason", `ERROR` is "server-level internal error". A wiring error and a
        violated data invariant are describable data reasons.
        """
        from vitalgraph.kg_impl.kg_backend_utils import GuardUnsatisfiable
        from vitalgraph.model.result_status import (
            OperationStatus, _SUCCESS_STATUSES)

        missing = [
            f"{m.rsplit('.', 1)[-1]}.{f}" for m, f in ENTRY_POINTS
            if _handler_catching(m, f, "GuardUnsatisfiable")[1] is None]
        assert not missing, (
            "these answer StaleWrite but not GuardUnsatisfiable, so an "
            f"undecidable guard 500s instead of answering: {missing}")

        assert issubclass(UnguardableWrite, GuardUnsatisfiable)
        assert issubclass(AmbiguousStamp, GuardUnsatisfiable)
        assert OperationStatus.STORE_FAILED not in _SUCCESS_STATUSES

    def test_the_reason_reaches_the_body_not_only_the_log(self):
        """`STORE_FAILED` promises a describable reason; it has to be IN there.

        These were collapsed into `update_subjects_graph`'s bare `False`, so the
        caller built a fresh `SubjectWriteFailed("slot update", N)` and the body
        said "slot update, N subjects" while the real cause — the subjects, or
        the conflicting stamps — lived only in the log. `StaleWrite` already
        re-raised and reached the body with its own message; these now do too.
        """
        from vitalgraph.kg_impl import kg_backend_utils

        src = inspect.getsource(kg_backend_utils.SparqlSQLBackendAdapter
                                .update_subjects_graph)
        assert "except GuardUnsatisfiable" in src, (
            "collapsed into `return False`, the cause cannot reach the body")

        # And every handler must RENDER it rather than compose over it.
        for module_name, func_name in ENTRY_POINTS:
            msrc, handler = _handler_catching(
                module_name, func_name, "GuardUnsatisfiable")
            assert handler is not None, f"{func_name} does not answer it at all"
            # EVERY `message=` in the handler, not merely one of them.
            # `_create_frames` returns from two branches, so "`str(e)` appears
            # somewhere in the handler" passed while one branch dropped the
            # reason — caught by reverting that branch and seeing this test
            # still pass.
            messages = [
                ast.get_source_segment(msrc, kw.value) or ""
                for call in ast.walk(handler)
                if isinstance(call, ast.Call)
                for kw in call.keywords if kw.arg == "message"]
            assert messages, f"{func_name} returns no message at all"
            bare = [m for m in messages if "e" not in m or "str(e)" not in m]
            assert not bare, (
                f"{func_name} answers the undecidable guard with a composed "
                f"message that drops the reason, so STORE_FAILED carries no "
                f"describable one: {bare}")

    def test_the_message_names_the_subjects(self):
        e = UnguardableWrite(["urn:a", "urn:b"])
        assert "urn:a" in str(e)
        assert e.subject_uris == ["urn:a", "urn:b"]


class TestTheTeardownSweepsAreIndependent:
    """Two sweeps in one `try` made the second depend on the first.

    `delete_space_with_tables` cancelled auto-sync and then the scheduled
    ANALYZEs in a single block, so a throw from the first skipped the second and
    logged a warning — leaving exactly the wall of `relation "…" does not exist`
    that the second sweep was added to stop, in the case where teardown is
    already going wrong.
    """

    def test_each_cancel_has_its_own_handler(self):
        from vitalgraph.space import space_manager

        src = inspect.getsource(space_manager)
        tree = ast.parse(src)
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
            and n.name == "delete_space_with_tables")

        def calls_in(node):
            return {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
                    for c in ast.walk(node) if isinstance(c, ast.Call)}

        tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try)]

        def innermost_try_for(name):
            """The NEAREST enclosing `try` of the call to *name*.

            Nearest, not any: the whole method is itself wrapped in a `try`, so
            "some `try` contains both" is true however the inner blocks are
            arranged and would pass for the defect. What matters is which
            handler catches a throw FIRST.
            """
            holders = [t for t in tries if name in calls_in(t)]
            # The innermost is the one containing no other holder.
            return min(holders, key=lambda t: len(list(ast.walk(t))), default=None)

        a = innermost_try_for("cancel_space_syncs")
        b = innermost_try_for("cancel_all")
        assert a is not None and b is not None, (
            "both cancels must be guarded — teardown is never blocked on task "
            "cancellation")
        assert a is not b, (
            "`cancel_space_syncs` and `cancel_all` share their nearest `try`, "
            "so a throw from the first skips the second")


class TestTheAnalyzeBurstIsBounded:
    def test_one_task_in_flight_per_space(self):
        from vitalgraph.db.sparql_sql import auto_analyze

        src = inspect.getsource(auto_analyze.schedule_maybe_analyze)
        assert "in_flight" in src, (
            "every write past the threshold queued another task, each taking "
            "one of three INTERNAL-pool connections to find the lock held")

    def test_skipping_cannot_lose_an_analyze(self):
        # The counter is what makes the skip safe: it stays over the threshold,
        # so the next write schedules again. Asserted because the dedupe would
        # be a real defect if the counter were cleared on schedule rather than
        # on completion.
        from vitalgraph.db.sparql_sql.auto_analyze import changes_pending
        import inspect as _i

        src = _i.getsource(changes_pending)
        assert "reset" not in src.lower() and "clear" not in src.lower(), (
            "changes_pending must only READ the counter; clearing it here "
            "would make a skipped schedule a lost ANALYZE")
