"""Which stack everything talks to — one resolver, outside any shipped package.

This used to live in `vitalgraph_sparql_sql_dev.db`, which is an EXPERIMENTAL
package: production imports it zero times, and it is now excluded from the wheel.
A resolver that 25 scripts and the conformance suite depend on should not be tied
to the fate of an experimental SPARQL pipeline, and should not be reachable from
a stale `pip install` — an installed copy of that package shadowed the repo for
any script lacking a sys.path insert, and still resolved the host cluster with an
empty password.

`vitalgraph_sparql_sql_dev.db` re-exports these names so existing imports keep
working; new code should import from here.

WHY ONE PLACE. Every caller having its own default is how the suites and the
fixture loaders ended up on different clusters while both reported success — the
host carries same-named spaces, so the queries answered (issues/055,
issues/099). The DEFAULT is the part that had to stop disagreeing; an explicit
setting always wins.
"""

from __future__ import annotations

import os
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Connection parameters
# ---------------------------------------------------------------------------

# The stack every test suite targets. One set of variables decides it, and this
# module resolves them the same way `tests/{performance,integration,api}/
# conftest.py` do — so the conformance suites, which reach the database through
# here rather than through those conftests, cannot end up on a different stack
# from the rest.
#
# They did. This module defaulted to port 5432 (host cluster) while the fixture
# loaders and the other suites defaulted to 5433 (docker test stack), so the
# conformance suite ran against the dev database while its sidecar checks
# pointed at the test one. Nothing said so — the host cluster carries
# same-named spaces, so the queries answered (issues/099).
_STACK_DEFAULTS = {
    "host": "localhost",
    "port": "5433",          # docker test stack; 5432 is the host cluster
    "dbname": "sparql_sql_graph",
    "user": "postgres",
    "password": "testpass",
}


def get_connection_params() -> Dict[str, Any]:
    """Build connection parameters for the configured stack.

    Precedence, most specific first:

      1. ``VG_TEST_PG_*``   — the stack selector the test suites share
      2. ``PGHOST``/``PGPORT``/...  — standard libpq variables
      3. ``LOCAL_DB_*``     — the .env development profile
      4. the docker test stack

    An explicit setting always wins; the DEFAULT is what had to stop
    disagreeing, since with nothing set each caller silently chose its own.
    """
    def _pick(*names_then_key: str) -> str:
        *names, key = names_then_key
        for name in names:
            value = os.environ.get(name)
            if value is not None and value != "":
                return value
        return _STACK_DEFAULTS[key]

    return {
        "host": _pick("VG_TEST_PG_HOST", "VG_PG_HOST", "PGHOST",
                      "LOCAL_DB_HOST", "host"),
        "port": int(_pick("VG_TEST_PG_PORT", "VG_PG_PORT", "PGPORT",
                          "LOCAL_DB_PORT", "port")),
        "dbname": _pick("VG_TEST_PG_DATABASE", "VG_PG_DATABASE", "PGDATABASE",
                        "LOCAL_DB_NAME", "dbname"),
        "user": _pick("VG_TEST_PG_USER", "VG_PG_USER", "PGUSER",
                      "LOCAL_DB_USERNAME", "user"),
        # Password is the one field where an empty string is a legitimate value
        # (trust auth), so it is read separately rather than through the
        # non-empty filter above.
        "password": next(
            (os.environ[n] for n in ("VG_TEST_PG_PASSWORD", "VG_PG_PASSWORD",
                                     "PGPASSWORD", "LOCAL_DB_PASSWORD")
             if n in os.environ),
            _STACK_DEFAULTS["password"]),
    }


def pg_kwargs() -> Dict[str, Any]:
    """The resolved target as asyncpg keyword arguments.

    Same values as `get_connection_params`, with `dbname` spelled `database`,
    which is what `asyncpg.connect` and `create_pool` take. Scripts connect
    directly rather than through this module's pool, so they need the spelling
    asyncpg uses and should not each convert it.
    """
    p = get_connection_params()
    return {"host": p["host"], "port": p["port"], "database": p["dbname"],
            "user": p["user"], "password": p["password"]}


def add_pg_arguments(parser) -> None:
    """Give an ops script its `--host/--port/--database/--user/--password`.

    Every maintenance script had its own copy of these five defaults, and they
    did not agree: seventeen defaulted to port 5432 while everything that READS
    a fixture defaults to 5433, across TWO env families (`VG_TEST_PG_*` and
    `VG_PG_*`) that did not see each other's variables. Setting the one the
    tests use left half the scripts pointed at the other cluster.

    For a migration script that is worse than for a loader. A loader writes a
    fixture where nobody looks; a migration ALTERS whichever cluster it reached,
    and the host carries same-named spaces, so it succeeds and says so
    (`issues/055`, and `issues/099` one layer up).

    The default is the docker test stack, which is also the safe direction: an
    unset environment now reaches the disposable cluster rather than the one
    with real data on it.
    """
    d = get_connection_params()
    parser.add_argument("--host", default=d["host"])
    parser.add_argument("--port", type=int, default=d["port"])
    parser.add_argument("--database", default=d["dbname"])
    parser.add_argument("--user", default=d["user"])
    parser.add_argument("--password", default=d["password"])


def describe_target(args_or_params) -> str:
    """One line naming the cluster about to be touched, and which one it is.

    Printed rather than logged at debug: the whole failure mode here is a script
    doing the right thing to the wrong database and reporting success. Naming
    the target is what makes that visible without reading the code.
    """
    g = (args_or_params.get if isinstance(args_or_params, dict)
         else lambda k, _d=None: getattr(args_or_params, k, _d))
    host, port = g("host", "?"), int(g("port", 0) or 0)
    db = g("dbname", None) or g("database", "?")
    known = {5433: "docker test stack", 5432: "host cluster"}
    which = known.get(port, "unrecognised cluster")
    return f"{host}:{port}/{db} — {which}"


# The sidecar belongs here for the same reason the database does. It is a
# STATELESS COMPILER, so reaching the wrong one returns a plausible AST rather
# than an error, and version skew between two instances lands as a query-shape
# mystery rather than a connection failure. Six scripts and one test had their
# own default and four of them named 7070 — the dev sidecar, which is also the
# test container's OWN internal port, which is how that value gets copied.
_SIDECAR_DEFAULT = "http://localhost:7071"   # test stack; 7070 is the dev one


def sidecar_url() -> str:
    """The configured Jena sidecar, resolved in one place.

    `VG_TEST_SIDECAR_URL` is the selector the suites share. A script must not
    carry its own default: with nothing set, every caller has to land on the
    same instance or the disagreement is invisible.
    """
    return (os.environ.get("VG_TEST_SIDECAR_URL") or _SIDECAR_DEFAULT).rstrip("/")


def dsn() -> str:
    """The configured target as a `postgresql://` URL.

    `get_connection_string` below returns the libpq keyword form and is for
    DISPLAY — it carries no password and cannot be connected with. This one is
    what `asyncpg.connect(dsn)` takes.

    Scripts hardcoded this string. Five of them defaulted to
    `postgresql://<user>@localhost:5432/sparql_sql_graph` — the host cluster,
    with a username baked in — while the suites and the fixture loaders used
    5433. The host carries same-named spaces, so those scripts connected,
    answered, and reported success against stale data (issues/055, issues/099).
    """
    p = get_connection_params()
    return (f"postgresql://{p['user']}:{p['password']}@"
            f"{p['host']}:{p['port']}/{p['dbname']}")
