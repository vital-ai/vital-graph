"""The cross-task LISTEN connection survives being lost — issues/276.

On 2026-10-17 an RDS Multi-AZ failover restarted the database at 17:12:37 UTC.
Both VitalGraph tasks re-created the connection they SEND notices on (that one
reconnects on demand) but not the one they LISTEN on: the listener loop slept
forever without ever checking it, so each task went deaf to the other and kept
serving cached reads of anything the other wrote. Broadcasts per hour went on;
receipts went to 0.

Driven with fake connections: the listener must notice a connection that
terminates, one that is closed, and one that silently stops answering (the
failover shape, caught only by the probe); reconnect; subscribe every channel
again; and run the resync callbacks after a REconnect — not on the first
connect.
"""

from __future__ import annotations

import asyncio

import pytest

from vitalgraph.signal import signal_manager as SM


class _FakeConn:
    def __init__(self, hang_probe=False):
        self.listeners = {}
        self.term = []
        self.closed = False
        self.hang_probe = hang_probe

    async def add_listener(self, channel, cb):
        self.listeners[channel] = cb

    def add_termination_listener(self, cb):
        self.term.append(cb)

    def terminate(self):
        self.closed = True
        for cb in self.term:
            cb(self)

    async def fetchval(self, sql):
        if self.hang_probe:
            await asyncio.sleep(3600)
        return 1

    async def close(self):
        self.closed = True

    def is_closed(self):
        return self.closed


def _manager(conns):
    m = SM.SignalManager(db_impl=object())
    it = iter(conns)

    async def make():
        return next(it)

    m._create_dedicated_connection = make
    return m


async def _until(pred, timeout=10.0):
    t0 = asyncio.get_running_loop().time()
    while not pred():
        if asyncio.get_running_loop().time() - t0 > timeout:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.02)


def _run(coro):
    return asyncio.run(coro)


def test_a_terminated_connection_is_replaced_and_every_channel_resubscribed(monkeypatch):
    async def go():
        a, b = _FakeConn(), _FakeConn()
        m = _manager([a, b])
        resyncs = []

        async def resync():
            resyncs.append(1)
        m.register_resync(resync)
        await m.start_listening()
        await _until(lambda: len(a.listeners) == len(m.callbacks))
        assert resyncs == [], "the FIRST connect is not a resync"

        a.terminate()
        await _until(lambda: len(b.listeners) == len(m.callbacks))
        await _until(lambda: resyncs == [1])
        assert set(b.listeners) == set(m.callbacks)
        assert m.reconnects == 1
        await m.stop_listening()
    _run(go())


def test_a_silently_dead_connection_is_caught_by_the_probe(monkeypatch):
    """The failover shape: nothing closes, nothing raises — the peer is gone."""
    monkeypatch.setattr(SM, "LISTEN_PROBE_INTERVAL_S", 1.0)
    monkeypatch.setattr(SM, "LISTEN_PROBE_TIMEOUT_S", 0.2)

    async def go():
        a, b = _FakeConn(hang_probe=True), _FakeConn()
        m = _manager([a, b])
        resyncs = []

        async def resync():
            resyncs.append(1)
        m.register_resync(resync)
        await m.start_listening()
        await _until(lambda: len(b.listeners) == len(m.callbacks), timeout=15)
        await _until(lambda: resyncs == [1])
        await m.stop_listening()
    _run(go())


def test_a_closed_connection_is_replaced(monkeypatch):
    async def go():
        a, b = _FakeConn(), _FakeConn()
        m = _manager([a, b])
        await m.start_listening()
        await _until(lambda: len(a.listeners) == len(m.callbacks))
        a.closed = True                       # closed, no termination callback
        await _until(lambda: len(b.listeners) == len(m.callbacks))
        await m.stop_listening()
    _run(go())


def test_a_failing_resync_callback_does_not_stop_the_others():
    async def go():
        m = SM.SignalManager(db_impl=object())
        ran = []

        async def bad():
            raise RuntimeError("boom")

        async def good():
            ran.append(1)
        m.register_resync(bad)
        m.register_resync(good)
        await m._run_resync()
        assert ran == [1]
    _run(go())


def test_the_app_registers_a_resync_that_clears_the_caches():
    from pathlib import Path
    import vitalgraph
    src = (Path(vitalgraph.__file__).parent / "impl" / "vitalgraphapp_impl.py").read_text()
    block = src[src.index("async def _resync_after_listen_reconnect"):]
    block = block[:block.index("register_resync(_resync_after_listen_reconnect)")]
    for call in ("_entity_graph_cache.clear()", "_count_cache.clear()",
                 "invalidate_term_cache(None)", "invalidate_datatype_cache(None)",
                 "invalidate_all_stats_caches()", "clear_token_cache()",
                 "_refresh_cache_from_db()"):
        assert call in block, call
