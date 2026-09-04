"""A load must drop the literal->uuid mappings it just invalidated.

`issues/158`. `generator._term_cache` maps
`(space_id, text, type, lang, datatype) -> term_uuid` for the life of the
PROCESS, and `term_uuid` is a UUIDv5 over exactly those components. A bulk
import TRUNCATES the term table and reloads it, so if a literal's datatype
changes between loads its uuid changes and every cached mapping for that space
is wrong.

A server holding the old mapping emits SQL for a term that no longer exists:

    'SYN000000000'  stored after reload    ea15bbc8...  (datatype_id=1)
                    what the SQL asked for daa00b9e...  (cached, datatype NULL)

Correct query, correct data, zero rows, no error. It cost most of a day to find,
and the only reason it was found is that restarting the server fixed it.

`invalidate_term_cache` existed the whole time with no callers outside a unit
test — the cross-process mechanism was complete for the datatype and stats
caches and simply absent for this one.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.generator import _term_cache, invalidate_term_cache
from vitalgraph.endpoint.impl.data_import_impl import ImportEngine


class _FakeSignalManager:
    def __init__(self):
        self.sent = []

    async def notify_cache_invalidate(self, cache_type, space_id):
        self.sent.append((cache_type, space_id))


class _RaisingSignalManager:
    async def notify_cache_invalidate(self, cache_type, space_id):
        raise RuntimeError("bus down")


@pytest.fixture(autouse=True)
def _clean():
    _term_cache.clear()
    yield
    _term_cache.clear()


class TestTheEngineInvalidates:

    @pytest.mark.asyncio
    async def test_it_clears_this_process_and_notifies_the_others(self):
        sm = _FakeSignalManager()
        _term_cache[("sp", "x", "L", None, None)] = "stale-uuid"
        _term_cache[("other", "x", "L", None, None)] = "keep-me"

        await ImportEngine(None, signal_manager=sm)._invalidate_term_cache("sp")

        assert ("term", "sp") in sm.sent, "other processes were not told"
        assert ("sp", "x", "L", None, None) not in _term_cache
        assert ("other", "x", "L", None, None) in _term_cache, \
            "invalidation must be scoped to the space that was reloaded"

    @pytest.mark.asyncio
    async def test_without_a_signal_manager_it_WARNS(self, caplog):
        """The CLI's case, and the one that actually bit.

        A command-line import cannot reach a running server's memory. Silently
        clearing only the importer's own cache would look like success while the
        server kept answering 0 rows, so the consequence is named at WARNING —
        production runs at INFO, and this is the level it has to clear.
        """
        _term_cache[("sp", "x", "L", None, None)] = "stale-uuid"
        with caplog.at_level("WARNING"):
            await ImportEngine(None)._invalidate_term_cache("sp")

        assert ("sp", "x", "L", None, None) not in _term_cache
        msg = " ".join(r.getMessage() for r in caplog.records)
        assert "restarted" in msg and "0 rows" in msg, (
            f"the warning must say what breaks and how to fix it: {msg}")

    @pytest.mark.asyncio
    async def test_a_failing_notify_does_not_fail_the_import(self, caplog):
        """The data is already committed by this point. Losing the notification
        degrades other processes; raising would lose the whole load."""
        with caplog.at_level("WARNING"):
            await ImportEngine(None, signal_manager=_RaisingSignalManager()) \
                ._invalidate_term_cache("sp")
        assert "bus down" in " ".join(r.getMessage() for r in caplog.records)


class TestTheHandlerBranchExists:
    """The receiving half. Sending a notification nobody handles is the state
    this was in before — `notify_cache_invalidate("term", ...)` had no branch."""

    def test_the_app_handles_a_term_invalidation(self):
        import inspect
        from vitalgraph.impl import vitalgraphapp_impl

        src = inspect.getsource(vitalgraphapp_impl)
        assert 'cache_type == "term"' in src, \
            "no handler branch for term invalidation; the notify goes nowhere"
        assert "invalidate_term_cache(space_id)" in src


class TestScoping:

    def test_invalidate_is_per_space(self):
        _term_cache[("a", "t", "L", None, None)] = "1"
        _term_cache[("b", "t", "L", None, None)] = "2"
        invalidate_term_cache("a")
        assert ("a", "t", "L", None, None) not in _term_cache
        assert ("b", "t", "L", None, None) in _term_cache
