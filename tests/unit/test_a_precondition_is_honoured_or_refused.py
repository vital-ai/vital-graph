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
        # frames — answered INVALID_REQUEST. This is a wiring error in a call
        # site, so it is deliberately NOT mapped to a 4xx: a 500 naming the
        # subjects is the correct answer to "asked for a guarantee without the
        # means to provide it".
        from vitalgraph.kg_impl.kg_backend_utils import AmbiguousPrecondition

        assert not issubclass(UnguardableWrite, AmbiguousPrecondition)
        from vitalgraph.endpoint import kgframes_endpoint
        src = inspect.getsource(kgframes_endpoint)
        assert "except UnguardableWrite" not in src, (
            "mapping this to a response would hide a wiring bug behind a "
            "caller-facing status")

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
