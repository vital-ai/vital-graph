"""The error that killed a write must not be hidden by the rollback that followed.

`issues/253`. Five production writes were lost on 2026-09-30 and every log line
said the same thing — "cannot call Transaction.__aexit__(): the underlying
connection is closed" — which is the symptom. Ruling out a server-side
termination took a trawl through the database's own logs, and the cause had been
in `e.__context__` the whole time.

Two mechanisms, both reproduced below: an exception raised while LEAVING a
context manager replaces the one raised inside it, and `str()` of
`asyncio.TimeoutError` — what asyncpg's `command_timeout` raises — is EMPTY, so
even unmasked it prints as nothing.
"""
import asyncio

import pytest

from vitalgraph.utils.exception_detail import describe_exception


def _masked():
    """The production shape: body fails, then the rollback fails on a dead
    connection and takes the blame."""
    try:
        try:
            raise asyncio.TimeoutError()
        except asyncio.TimeoutError:
            raise RuntimeError(
                "cannot call Transaction.__aexit__(): "
                "the underlying connection is closed")
    except RuntimeError as e:
        return e


class TestTheProductionCase:
    def test_the_masked_timeout_is_named(self):
        out = describe_exception(_masked())
        assert "the underlying connection is closed" in out
        assert "TimeoutError" in out
        assert "masked" in out

    def test_an_empty_str_exception_still_prints_its_type(self):
        # THE SECOND TRAP. "%s" % asyncio.TimeoutError() is the empty string, so
        # the old line would have read "... failed: " with nothing after it —
        # which is the defect recorded in sparql_sql_db_impl for a resync.
        assert str(asyncio.TimeoutError()) == ""
        assert describe_exception(asyncio.TimeoutError()) == "TimeoutError"

    def test_the_top_level_message_is_not_lost(self):
        # Unmasking must ADD, not replace: whoever reads this log line today is
        # reading the top-level text.
        assert describe_exception(_masked()).startswith(
            "RuntimeError: cannot call Transaction.__aexit__()")


class TestTheChain:
    def test_a_deliberate_cause_is_labelled_differently_from_an_accident(self):
        # `raise ... from` is an author's claim about causation; `__context__` is
        # an accident of nesting. Reading the second as the first misattributes.
        try:
            try:
                raise ValueError("inner")
            except ValueError as inner:
                raise RuntimeError("outer") from inner
        except RuntimeError as e:
            assert "caused by ValueError: inner" in describe_exception(e)

    def test_suppressed_context_is_honoured(self):
        # `raise ... from None` is an author saying the chain is noise.
        try:
            try:
                raise ValueError("noise")
            except ValueError:
                raise RuntimeError("clean") from None
        except RuntimeError as e:
            assert describe_exception(e) == "RuntimeError: clean"

    def test_a_plain_exception_is_unchanged(self):
        assert describe_exception(ValueError("just this")) == "ValueError: just this"

    def test_a_long_chain_is_capped(self):
        # The cap counts FRAMES PRINTED, including the raised one, so a default
        # of 4 shows four exceptions and then says it stopped.
        exc = ValueError("deepest")
        for i in range(10):
            nxt = RuntimeError(f"layer{i}")
            nxt.__context__ = exc
            exc = nxt
        out = describe_exception(exc)
        assert out.endswith("<- ...")
        assert out.count("RuntimeError") == 4
        assert "deepest" not in out

    def test_a_chain_exactly_at_the_cap_does_not_claim_more(self):
        # An "..." where nothing was left out sends the next reader looking for a
        # frame that does not exist — which is the same class of defect as the
        # masking this file exists to fix.
        exc = ValueError("root")
        for i in range(3):
            nxt = RuntimeError(f"layer{i}")
            nxt.__context__ = exc
            exc = nxt
        out = describe_exception(exc)          # exactly 4 frames
        assert "root" in out
        assert "..." not in out

    def test_the_cap_is_adjustable(self):
        exc = ValueError("deepest")
        for i in range(5):
            nxt = RuntimeError(f"layer{i}")
            nxt.__context__ = exc
            exc = nxt
        assert describe_exception(exc, max_frames=2).count("RuntimeError") == 2

    def test_a_cyclic_chain_does_not_repeat_or_hang(self):
        # Possible once someone re-raises an exception they were holding; without
        # a guard the output would print the same frame until the depth cap.
        a, b = RuntimeError("a"), RuntimeError("b")
        a.__context__ = b
        b.__context__ = a
        out = describe_exception(a)
        assert out == "RuntimeError: a <- masked RuntimeError: b"


class TestTheWritePathsUseIt:
    def test_every_swallowing_write_path_describes_the_chain(self):
        # A guard, not a style check: each of these is a path where a failing
        # rollback can replace the real error, and `%s` on its own loses it.
        import inspect

        from vitalgraph.kg_impl import kg_backend_utils

        src = inspect.getsource(kg_backend_utils)
        for name in ("store_objects", "update_quads", "upsert_objects_atomic",
                     "update_entity_graph", "update_subjects_graph"):
            assert f'"{name} failed: %s", describe_exception(e)' in src, name
