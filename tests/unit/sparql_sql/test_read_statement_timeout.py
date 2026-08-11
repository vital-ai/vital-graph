"""The read path carries a PostgreSQL-enforced fence, not just a client one.

asyncpg's `command_timeout` already cancels a slow query, but it fires from an
event-loop callback. If the loop stalls — `utils/event_loop_monitor.py` exists
because that is a live concern — or the worker is killed mid-query, the callback
never runs and the query is unbounded: PostgreSQL will not notice a dead client
on a long SELECT until it tries to return rows.

A `statement_timeout` is enforced by the backend regardless of client health.
See issues/044 gap 5.

These pin the policy, not the plumbing. The behaviour against a live backend
(the fence firing, and `SET LOCAL` not leaking past COMMIT) was verified
directly; what is easy to break later is the configuration contract.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import (
    _READ_STATEMENT_TIMEOUT_MS_DEFAULT,
    _read_statement_timeout_ms,
)

ENV = "VITALGRAPH_READ_STATEMENT_TIMEOUT_MS"


class TestReadStatementTimeout:

    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv(ENV, raising=False)
        assert _read_statement_timeout_ms() == _READ_STATEMENT_TIMEOUT_MS_DEFAULT

    def test_default_is_below_the_asyncpg_command_timeout(self):
        """Ordering is the point, not the number.

        issues/044 gap 3: the server fence sat AT the client's own per-attempt
        budget, so the client was guaranteed to abandon first and the query kept
        running. Whoever fires first should be the server, so the client gets a
        real error to surface. asyncpg's command_timeout defaults to 60s
        (sparql_sql_db_impl.py).
        """
        assert _READ_STATEMENT_TIMEOUT_MS_DEFAULT < 60_000

    def test_override(self, monkeypatch):
        monkeypatch.setenv(ENV, "12000")
        assert _read_statement_timeout_ms() == 12_000

    def test_zero_disables(self, monkeypatch):
        """0 is PostgreSQL's own spelling for "no timeout"."""
        monkeypatch.setenv(ENV, "0")
        assert _read_statement_timeout_ms() == 0

    def test_negative_is_clamped_not_passed_through(self, monkeypatch):
        """A negative would be a syntax error in the SET, i.e. every read fails."""
        monkeypatch.setenv(ENV, "-1")
        assert _read_statement_timeout_ms() == 0

    def test_garbage_falls_back_rather_than_raising(self, monkeypatch):
        """A typo in an env var must not take the read path down."""
        monkeypatch.setenv(ENV, "sixty seconds")
        assert _read_statement_timeout_ms() == _READ_STATEMENT_TIMEOUT_MS_DEFAULT
