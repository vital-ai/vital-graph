"""A missing connection setting must raise, not connect somewhere else.

Every PostgreSQL connection in this codebase read its settings with a fallback —
`config.get('username', 'vitalgraph_user')`, and the same for host, port,
database and password. A caller whose key was missing or misspelled got a
connection attempt against `vitalgraph_user@localhost:5432/vitalgraph`,
credentials that appear nowhere in any config.

This was found by making the mistake: a probe passed `user` instead of
`username`, and the failure was `password authentication failed for user
"vitalgraph_user"` — a user nobody had configured, which says nothing about the
key that was actually wrong.

That is the BENIGN outcome. The dangerous one is an environment where
`vitalgraph`/`vitalgraph_user` exists: the wrong target answers, the caller
reports success, and every query is correct about the wrong data — `issues/055`,
where fixtures were written to one cluster and read from another and both ends
reported success because same-named spaces existed.

The same dictionary has already been bitten this way: `config_loader` carries a
comment recording that SQLAlchemy-style `pool_size`/`max_overflow` keys were
silently ignored by asyncpg, leaving `max_size` at a hardcoded 15.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vitalgraph.db.connection_config import REQUIRED_KEYS, require

REPO = Path(__file__).resolve().parents[2]

FULL = {"host": "h", "port": 5432, "database": "d", "username": "u", "password": "p"}


class TestRequire:

    @pytest.mark.parametrize("key", REQUIRED_KEYS)
    def test_a_missing_key_raises(self, key):
        cfg = {k: v for k, v in FULL.items() if k != key}
        with pytest.raises(ValueError, match=key):
            require(cfg, key)

    @pytest.mark.parametrize("key", REQUIRED_KEYS)
    def test_the_error_lists_what_was_present(self, key):
        """So a typo is visible: passing `user` shows `user` in the list while
        the message says `username` is missing."""
        cfg = {k: v for k, v in FULL.items() if k != key}
        with pytest.raises(ValueError) as exc:
            require(cfg, key)
        for other in cfg:
            assert other in str(exc.value)

    def test_an_empty_password_is_a_value_not_an_omission(self):
        """Trust authentication is legitimate, so presence is what matters."""
        assert require({**FULL, "password": ""}, "password") == ""

    def test_a_present_key_is_returned(self):
        assert require(FULL, "username") == "u"


class TestNoConnectionInventsCredentials:
    """The sweep: no live path may reintroduce the fallback.

    Keyed on the credential VALUES rather than on a call shape, because the next
    copy of this will be written with a different variable name and the same
    literals.
    """

    # Excluded deliberately, not overlooked:
    #   fuseki*            a separate backend this work does not touch
    #   config_loader.py   a STATED default profile, not a silent fallback
    #   connection_config  names the strings in order to forbid them
    #   signal_manager     `CHANNEL_USER = "vitalgraph_user"` is a NOTIFY channel
    #                      name that happens to collide with the credential
    EXCLUDE = ("fuseki", "config_loader.py", "connection_config.py", "signal_manager.py")
    BAD = ("vitalgraph_user", "vitalgraph_pass")

    # Fuseki's HTTP credentials share these literals but are a different config
    # domain — `require` is about naming a POSTGRES database. Skipped by the
    # config variable rather than by path, because `vitalgraph_impl.py` builds a
    # fuseki config from a file whose name says nothing about fuseki.
    SKIP_LINE = ("fuseki",)

    def _offenders(self):
        out = []
        for p in sorted((REPO / "vitalgraph").rglob("*.py")):
            rel = p.relative_to(REPO).as_posix()
            if any(x in rel for x in self.EXCLUDE):
                continue
            for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
                if any(x in line.lower() for x in self.SKIP_LINE):
                    continue
                if any(b in line for b in self.BAD) and ".get(" in line:
                    out.append(f"{rel}:{n}: {line.strip()}")
        return out

    def test_the_sweep_reaches_the_tree(self):
        assert list((REPO / "vitalgraph").rglob("*.py")), "no sources found"

    def test_no_live_path_defaults_to_built_in_credentials(self):
        offenders = self._offenders()
        assert not offenders, (
            "these fall back to credentials nobody configured; use "
            "`vitalgraph.db.connection_config.require`:\n  "
            + "\n  ".join(offenders))


def test_connect_propagates_a_config_error_rather_than_returning_false():
    """`connect()` returns False for an unreachable database, which callers
    retry or degrade on. A config that cannot NAME a database is not that, and
    no amount of retrying fixes it — so it propagates."""
    src = (REPO / "vitalgraph/db/sparql_sql/sparql_sql_db_impl.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "connect":
            handlers = [h for n in ast.walk(node) if isinstance(n, ast.Try)
                        for h in n.handlers]
            names = [h.type.id for h in handlers
                     if isinstance(h.type, ast.Name)]
            assert "ValueError" in names, (
                "connect() no longer distinguishes a config error from an "
                "unreachable database")
            return
    pytest.fail("connect() not found")
