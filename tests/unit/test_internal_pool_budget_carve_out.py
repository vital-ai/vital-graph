"""The internal pool is carved OUT of `max_pool_size`, not added to it.

`issues/231`, decided 2026-09-25. `max_pool_size` is the whole budget for a
task across both classes:

    request pool  = max_pool_size - internal_pool_size
    internal pool = internal_pool_size
    total         = max_pool_size

WHY IT MATTERS ENOUGH TO PIN. Adding the internal pool on top was the ONLY
effect of the bulkhead the end-to-end workload could detect: an unmatched A/B
showed the treatment winning every run (p50 136ms -> 42ms median) and a
capacity-matched one showed no difference at all, so the apparent win was purely
the extra connections. If the carve-out regresses, the bulkhead silently starts
buying latency again by spending connections nobody budgeted — and the database
sees the SUM across every task and class, which is the number `issues/231`
step 4 exists to reduce.

Asserted against `connect()`'s source rather than by connecting, because the
arithmetic is what is under test and a live server would add nothing.
"""

import inspect
import re

import pytest

from vitalgraph.db.sparql_sql import sparql_sql_db_impl

SRC = inspect.getsource(sparql_sql_db_impl.SparqlSQLDbImpl.connect)


def test_the_request_pool_is_the_budget_minus_the_internal_pool():
    assert "request_max = max_size - internal_max" in SRC, (
        "the internal pool is no longer carved out of the budget; it is being "
        "added on top, which is the measured false win")


def test_the_request_pool_is_what_gets_created():
    """Computing `request_max` and then passing `max_size` would leave the
    arithmetic in place and the behaviour unchanged."""
    assert "max_size=request_max" in SRC
    # and the budget must NOT be handed to a pool directly any more
    assert not re.search(r"max_size=max_size\b", SRC), (
        "a pool is still being created with the whole budget as its size")


def test_disabling_the_split_returns_the_whole_budget_to_requests():
    """With no internal pool there is nothing to reserve, so the request pool
    gets everything — otherwise the kill switch would shrink capacity."""
    assert "request_max = max_size" in SRC


def test_an_oversized_internal_pool_cannot_starve_request_serving():
    """internal >= budget would leave the request pool at zero or negative.

    asyncpg would reject it, but the failure mode to avoid is subtler than a
    crash: a bulkhead that consumes the entire budget is an outage with extra
    steps.
    """
    assert "if internal_max >= max_size:" in SRC
    assert "internal_max = max(0, max_size - 1)" in SRC


def test_the_min_clamp_compares_against_the_request_pool():
    """`min_pool_size` applies to the request pool, which is now SMALLER than
    the budget — so a min that fits the budget can still exceed its pool.

    Clamping against `max_size` here would pass a min above the pool's max
    straight to asyncpg, which fails at connect() with an error naming neither.
    """
    assert "if min_size > request_max:" in SRC
    assert "min_size = request_max" in SRC


def test_the_log_states_the_split():
    """An operator reading the log must be able to see where the budget went;
    two separate "pool created" lines with no total is how the addition went
    unnoticed in the first place."""
    assert "carved out for INTERNAL" in SRC
    assert "total across both pools" in SRC


def test_the_internal_pool_gets_the_MAINTENANCE_command_timeout():
    """THE SECOND FENCE, which `maintenance_timeouts()` cannot reach.

    `command_timeout` is asyncpg's CLIENT-SIDE limit; `statement_timeout` is the
    server's. They are independent, and raising only the server one leaves the
    client killing the query anyway.

    Measured on production 2026-09-28: a full resync of a 3.2M-slot space had the
    server fence correctly raised to 15 minutes and still died four times at
    ~60-70s each, because the pool's `command_timeout` was the request path's 60.
    It surfaced as `Resync failed: ` — an EMPTY message — because
    `asyncio.TimeoutError` has no string. `issues/231` had listed this exact
    interaction as unestablished.

    The REQUEST pool must keep 60s: that fence is for user queries.
    """
    assert "MAINTENANCE_STATEMENT_TIMEOUT_MS / 1000.0" in SRC, (
        "the internal pool is back on the request path's client-side fence")
    # and the REQUEST pool must keep the 60s fence. Checked on its own
    # create_pool call rather than on everything above the internal block —
    # the import of the constant lives up there too, which is why an earlier
    # version of this assertion failed on its own import.
    # Bounded by the register_pool that follows it — splitting on ")" stops at
    # the first inner paren (`require(self.config, 'host')`) and reads nothing.
    request_call = SRC.split("self.connection_pool = await create_pool(")[1]
    request_call = request_call.split("register_pool(self.connection_pool")[0]
    assert "command_timeout=self.config.get('command_timeout', 60)" in request_call, (
        "the REQUEST pool no longer carries the read-path command_timeout")
    assert "MAINTENANCE" not in request_call, (
        "the REQUEST pool got the maintenance command_timeout; that fence is "
        "for user queries and must stay at 60s")


def test_both_fences_are_overridable_per_deployment():
    """A table can outgrow any fixed budget, so neither is hardcoded."""
    assert "'internal_command_timeout'" in SRC, (
        "the internal client-side fence cannot be tuned without a code change")
