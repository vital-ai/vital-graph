"""`internal_pool_size` reaches the pool that reads it. `issues/231`.

The config loader carries a scar on exactly this:

    # Key names must match what vitalgraph/db/pool.py reads. The former
    # SQLAlchemy-style pool_size/max_overflow/pool_timeout/pool_recycle
    # keys were silently ignored by asyncpg, leaving max_size at its
    # hardcoded default of 15.

A key the loader emits under a name nobody reads, or a key the impl reads that
the loader never emits, both fail the same way: SILENTLY, at the default,
looking configured. `internal_pool_size` was introduced with the second half of
that bug — `SparqlSQLDbImpl.connect()` read it and nothing ever set it, so the
INTERNAL pool was fixed at 3 with no way to tune it.

That matters more than an ordinary default, because this pool ADDS to the
global connection budget: every task now opens up to `internal_pool_size` more
connections against a box whose useful concurrency is ~8-10. Step 4 of
`issues/231` is to bring the TOTAL down, and a number that cannot be changed
cannot participate in that.

The read side is asserted against the source rather than by connecting, because
`connect()` needs a live server; the property under test is that the two names
agree, which is textual.
"""

import inspect
import os
from unittest import mock

import pytest

from vitalgraph.config.config_loader import VitalGraphConfig


# The top-level `database` block has no defaults for the settings that NAME
# the database — deliberately, so a misconfiguration cannot connect somewhere
# nobody chose — so the loader refuses to build without them.
_REQUIRED = {
    "DB_HOST": "localhost", "DB_PORT": "5432",
    "DB_NAME": "unittest_db", "DB_USERNAME": "unittest",
}


def _sparql_sql_db_config():
    """The `sparql_sql.database` block — the one `backend_config` actually
    hands to `SparqlSQLDbImpl`, which is not the top-level `database` block."""
    # Built without touching the real loader's __init__, which reads .env
    # files and a profile from the environment; `environment` is the only
    # attribute `_get_profile_env` needs, and an unlikely profile name keeps
    # the lookup falling through to the unprefixed variables the test sets.
    cfg = VitalGraphConfig.__new__(VitalGraphConfig)
    cfg.environment = "unittest"
    with mock.patch.dict(os.environ, _REQUIRED):
        built = VitalGraphConfig._load_from_env(cfg)
    return built["sparql_sql"]["database"]


def test_the_loader_emits_the_key_the_impl_reads():
    from vitalgraph.db.sparql_sql import sparql_sql_db_impl

    src = inspect.getsource(sparql_sql_db_impl)
    assert "self.config.get('internal_pool_size'" in src, (
        "the impl no longer reads this key; the loader below is then dead config")
    assert "internal_pool_size" in _sparql_sql_db_config(), (
        "the impl reads `internal_pool_size` and the loader never emits it — "
        "the INTERNAL pool is pinned at its default and cannot be tuned")


def test_it_is_settable_from_the_environment():
    with mock.patch.dict(os.environ, {"DB_INTERNAL_POOL_SIZE": "7"}):
        assert _sparql_sql_db_config()["internal_pool_size"] == 7


def test_it_defaults_small():
    """The pool exists so INTERNAL cannot take what request serving needs. A
    large default would defeat that while still looking like a bulkhead."""
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DB_INTERNAL_POOL_SIZE", None)
        size = _sparql_sql_db_config()["internal_pool_size"]
    assert 1 <= size <= 5, f"internal pool default is {size}; it should stay small"


def test_it_is_an_int_not_a_string():
    """`max_size="3"` reaches asyncpg as a string and fails far from here."""
    with mock.patch.dict(os.environ, {"DB_INTERNAL_POOL_SIZE": "4"}):
        assert isinstance(_sparql_sql_db_config()["internal_pool_size"], int)


def test_zero_is_accepted_as_the_disable_value():
    """0 must survive the loader as an int, not be coerced to the default.

    It is the rollback switch and the control arm of the bulkhead measurement,
    so a loader that quietly turned 0 into 3 would make the control run
    identical to the treatment run — and the A/B would 'prove' isolation from
    two runs of the same configuration.
    """
    with mock.patch.dict(os.environ, {"DB_INTERNAL_POOL_SIZE": "0"}):
        assert _sparql_sql_db_config()["internal_pool_size"] == 0


def test_the_disable_path_leaves_no_internal_pool_and_says_so():
    """Disabled means None plus a WARNING, not a zero-size pool.

    asyncpg rejects max_size=0, so a code path that built the pool anyway would
    fail at startup instead of falling back — and the fallback IS the feature.
    """
    import inspect
    from vitalgraph.db.sparql_sql import sparql_sql_db_impl

    src = inspect.getsource(sparql_sql_db_impl.SparqlSQLDbImpl.connect)
    assert "if internal_max > 0:" in src, (
        "the pool is created unconditionally; internal_pool_size=0 would reach "
        "asyncpg as max_size=0 and fail at startup")
    assert "self.internal_pool = None" in src
    assert "INTERNAL pool DISABLED" in src, (
        "disabling the bulkhead must be visible in the log; it is the "
        "configuration that caused an outage")


def test_a_min_above_max_is_clamped_not_fatal():
    """Lowering only `max_pool_size` must not break startup.

    asyncpg refuses `min_size > max_size` at connect(), and the refusal reaches
    the operator as `'NoneType' object has no attribute 'execute_update'` from
    the startup path — the backend is left unset and the visible error names
    neither pool nor size. Reducing the global connection budget is step 4 of
    `issues/231`, so lowering max_size is an EXPECTED operation, and it should
    not require knowing to lower min_size in the same breath.
    """
    import inspect
    from vitalgraph.db.sparql_sql import sparql_sql_db_impl

    src = inspect.getsource(sparql_sql_db_impl.SparqlSQLDbImpl.connect)
    assert "if min_size > max_size:" in src, (
        "no clamp: lowering max_pool_size below min_pool_size fails at startup "
        "with an error that names neither")
    assert "min_size = max_size" in src
