"""A request may not wait forever for a lock; background work still may.

`issues/253`. Measured on production 2026-09-30: `lock_timeout` was **0** —
`source: default`, no `pg_db_role_setting` override — so a request waiting for a
lock waited until `statement_timeout` at 60 s. A frame write whose own work is
~0.9 s was seen taking 51.7 s, 6.4 s of which elapsed before its first statement
ran. `issues/231` had recorded 10 s for this setting and that was wrong for the
app's sessions, which is why `entity_lock` left the single-key path unbounded on
a premise that did not hold.

The fence is per CONNECTION, so it costs nothing per write, and it is on the
REQUEST pool ONLY. That asymmetry is the point and not an oversight: background
work legitimately waits for locks — ANALYZE, VACUUM, an index build, a resync
holding ACCESS EXCLUSIVE — and fencing it would kill maintenance mid-way, which
is `issues/136` (an RDS `statement_timeout` killing 91% of VACUUMs while the job
reported success) in a new costume.
"""
import pytest

from vitalgraph.db.sparql_sql import sparql_sql_db_impl as impl


class FakeConn:
    def __init__(self):
        self.codecs = []
        self.statements = []

    async def set_type_codec(self, name, **kw):
        self.codecs.append(name)

    async def execute(self, sql, *args):
        self.statements.append(sql)

    def lock_timeout_set(self):
        return [s for s in self.statements if "lock_timeout" in s]


class TestTheRequestPool:
    @pytest.mark.asyncio
    async def test_a_request_connection_bounds_its_lock_wait(self):
        conn = FakeConn()
        await impl._init_request_conn(conn)
        assert conn.lock_timeout_set() == ["SET lock_timeout = '10000ms'"]

    @pytest.mark.asyncio
    async def test_it_still_installs_the_json_codecs(self):
        # The fence is ADDED to the existing init, not swapped for it. Losing the
        # codecs would break every jsonb column on the request path.
        conn = FakeConn()
        await impl._init_request_conn(conn)
        assert conn.codecs == ["jsonb", "json"]

    @pytest.mark.asyncio
    async def test_the_value_is_configurable(self, monkeypatch):
        monkeypatch.setenv("VITALGRAPH_REQUEST_LOCK_TIMEOUT_S", "2.5")
        conn = FakeConn()
        await impl._init_request_conn(conn)
        assert conn.lock_timeout_set() == ["SET lock_timeout = '2500ms'"]

    @pytest.mark.asyncio
    async def test_zero_disables_the_fence_rather_than_meaning_forever(
            self, monkeypatch):
        # PostgreSQL reads `lock_timeout = 0` as WAIT FOREVER, so a 0 here must
        # emit NO statement — sending `SET lock_timeout = '0ms'` would look like
        # a tight fence and be the opposite.
        monkeypatch.setenv("VITALGRAPH_REQUEST_LOCK_TIMEOUT_S", "0")
        conn = FakeConn()
        await impl._init_request_conn(conn)
        assert conn.lock_timeout_set() == []
        assert conn.codecs == ["jsonb", "json"]

    @pytest.mark.asyncio
    async def test_a_junk_setting_falls_back_rather_than_crashing_startup(
            self, monkeypatch):
        monkeypatch.setenv("VITALGRAPH_REQUEST_LOCK_TIMEOUT_S", "banana")
        conn = FakeConn()
        await impl._init_request_conn(conn)
        assert conn.lock_timeout_set() == ["SET lock_timeout = '10000ms'"]


class TestTheInternalPoolIsNotFenced:
    """`issues/136`'s shape: a fence that kills deferrable work and lets the job
    report success."""

    @pytest.mark.asyncio
    async def test_background_connections_keep_waiting_for_locks(self):
        conn = FakeConn()
        await impl._init_conn(conn)
        assert conn.lock_timeout_set() == []
        assert conn.codecs == ["jsonb", "json"]

    @pytest.mark.asyncio
    async def test_even_when_the_request_fence_is_configured_high(
            self, monkeypatch):
        monkeypatch.setenv("VITALGRAPH_REQUEST_LOCK_TIMEOUT_S", "30")
        conn = FakeConn()
        await impl._init_conn(conn)
        assert conn.lock_timeout_set() == []


class TestTheWiring:
    """The two pools must get the two different inits. Asserted over the source
    because standing up two real pools to check which hook each got would test
    asyncpg, not this decision."""

    def test_the_request_pool_gets_the_fenced_init_and_internal_does_not(self):
        import inspect
        import re

        src = inspect.getsource(impl.SparqlSQLDbImpl.connect)
        calls = re.findall(r"init=(_init_\w+)", src)
        assert calls == ["_init_request_conn", "_init_conn"], calls
