"""Integration: the slot-group size hint is estimated as intended and returns nothing (`issues/330`).

`slot_group_cte.apply_groups` tells PostgreSQL a pure-star group's size with a
`UNION ALL` branch over `generate_series(1, 3 * size)` filtered by `n < 0`. It
relies on two planner behaviours: a constant `generate_series` is estimated at
its exact length, and `n < 0` on a column without statistics at 1/3. A
PostgreSQL that estimated either differently would silently undo the hint, and
the production rescan (1,950 x 1,950 rows) would come back with no error.

Pinned on the server: the branch returns no row, it is estimated at `size`
rows, and it raises a CTE's estimate by that much.
"""

from __future__ import annotations

import json

import pytest

from .conftest import skip_no_infra

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

SIZE = 1_950
BRANCH = f"SELECT NULL::uuid AS c FROM generate_series(1, {3 * SIZE}) AS p(n) WHERE p.n < 0"


async def _plan_rows(conn, sql) -> float:
    raw = await conn.fetchval("EXPLAIN (FORMAT JSON) " + sql)
    return (json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]["Plan Rows"]


async def test_the_branch_returns_nothing_and_is_estimated_at_size(pg_conn):
    assert await pg_conn.fetch(BRANCH) == []
    assert await _plan_rows(pg_conn, BRANCH) == pytest.approx(SIZE, rel=0.01)


async def test_it_raises_a_ctes_estimate_by_size(pg_conn):
    tiny = "SELECT gen_random_uuid() AS c FROM generate_series(1, 5)"
    plain = await _plan_rows(pg_conn, f"WITH t AS MATERIALIZED ({tiny}) SELECT * FROM t")
    hinted = await _plan_rows(
        pg_conn, f"WITH t AS MATERIALIZED ({tiny} UNION ALL {BRANCH}) SELECT * FROM t")
    assert plain == pytest.approx(5, abs=1)
    assert hinted == pytest.approx(5 + SIZE, rel=0.01)
    rows = await pg_conn.fetch(f"WITH t AS MATERIALIZED ({tiny} UNION ALL {BRANCH}) SELECT * FROM t")
    assert len(rows) == 5
