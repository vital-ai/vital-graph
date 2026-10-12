"""`migrate.py --db PREFIX` connects to the database it names, and only that one.

For production the config profile is wrong twice: `.env`'s `PROD_DB_HOST` names an
unrelated instance and its password is stale, so a production migration has to
name the live cluster (host from the ECS task definition, password from the task's
secret). These pin how `--db` and `--ssl` become connection arguments.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

# `migrate.py` calls `load_dotenv()` at import, which copies the real `.env` into
# `os.environ` for the rest of the session; a later test that expects its own
# `.env` to supply a credential then reads the real one instead. Import it with
# the environment restored afterwards.
with mock.patch.dict(os.environ):
    from apps.entity_registry.migrate import SESSION_SETTINGS, connect_kwargs

ENV = {
    "LIVE_DB_HOST": "live.example.internal",
    "LIVE_DB_PORT": "6543",
    "LIVE_DB_NAME": "vitalgraphdb",
    "LIVE_DB_USER": "vitalgraph_user",
    "LIVE_DB_PASSWORD": "pw",
}


def test_a_prefix_names_every_connection_argument():
    kw = connect_kwargs("LIVE", None, environ=ENV)
    assert kw == dict(host="live.example.internal", port=6543, database="vitalgraphdb",
                      user="vitalgraph_user", password="pw")


def test_the_other_scripts_variable_names_are_accepted():
    env = {k.replace("_USER", "_USERNAME").replace("_NAME", "_DATABASE"): v
           for k, v in ENV.items() if k != "LIVE_DB_PORT"}
    kw = connect_kwargs("LIVE", None, environ=env)
    assert (kw["user"], kw["database"], kw["port"]) == ("vitalgraph_user", "vitalgraphdb", 5432)


def test_a_missing_variable_stops_rather_than_guessing():
    env = {k: v for k, v in ENV.items() if k != "LIVE_DB_HOST"}
    with pytest.raises(SystemExit, match="LIVE_DB_HOST"):
        connect_kwargs("LIVE", None, environ=env)


def test_ssl_is_passed_only_when_asked():
    assert connect_kwargs("LIVE", "require", environ=ENV)["ssl"] == "require"
    # unset: asyncpg's own default (prefer) applies
    assert "ssl" not in connect_kwargs("LIVE", None, environ=ENV)


def test_migrations_run_without_the_statement_cap_and_with_a_short_lock_wait():
    assert SESSION_SETTINGS == {"statement_timeout": "0", "lock_timeout": "5s"}
