"""The index migration sets its own timeouts — issues/271, 272.

Production's parameter group gives every connection `statement_timeout = 60s`
and a `lock_timeout`. On 2026-10-17 the first `--apply` was cancelled after 6 of
27 drops, waiting behind maintenance's lock on the main KG space, and the cancel
left that index INVALID. The deploy got through only by adding
`options=-c statement_timeout=0 -c lock_timeout=0` to the DSN by hand. The
script now sets both on its own session before it drops anything.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scripts",
                     "migrate_drop_redundant_quad_indexes.py")
_spec = importlib.util.spec_from_file_location("migrate_drop", _PATH)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


class _Conn:
    def __init__(self, defaults):
        self.settings = dict(defaults)
        self.log = []

    async def execute(self, sql):
        self.log.append(sql)
        name, value = sql.removeprefix("SET ").split(" = ")
        self.settings[name] = value

    async def fetchval(self, sql):
        return self.settings[sql.removeprefix("SHOW ")]


def test_both_timeouts_are_zeroed_whatever_the_server_default():
    conn = _Conn({"statement_timeout": "60s", "lock_timeout": "10s"})
    assert asyncio.run(M.configure_session(conn)) == {
        "statement_timeout": "0", "lock_timeout": "0"}


def test_they_are_set_before_anything_is_dropped():
    import inspect
    src = inspect.getsource(M.run)
    assert src.index("configure_session(conn)") < src.index("DROP INDEX")
