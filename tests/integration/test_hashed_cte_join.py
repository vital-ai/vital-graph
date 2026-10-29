"""Integration: a join to a materialised slot-group BGP is hashed, with the same rows (`issues/330`).

`emit_join._hashed_cte_join` writes `L JOIN / LEFT JOIN (WITH bgp_sg_* ...)` as
a FULL JOIN behind an `OFFSET 0` fence, filtered back to the join's rows, so
PostgreSQL cannot nested-loop the CTE (a CTE has no index: a loop reads all of
it per outer row, 1,920 x 1,920 on production).

Pinned on PostgreSQL itself, against the plain join on the same operands: the
same multiset of rows with unmatched rows on either side, several matches per
key, a NULL in a remaining condition's column; and no Nested Loop in the plan.
"""

from __future__ import annotations

from collections import Counter

import pytest

from .conftest import skip_no_infra

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

U = "'00000000-0000-0000-0000-00000000000{}'::uuid"

# ?d (v0) with a VALUES-like text column (v1, NULL = unbound) on the left;
# the CTE binds ?d (v3) and a code (v7). Key 1 matches twice, 2 once, 3 never;
# the CTE's key 4 has no left row.
LEFT = ("SELECT * FROM (VALUES "
        f"({U.format(1)}, 'a'), ({U.format(1)}, NULL), ({U.format(2)}, 'b'), "
        f"({U.format(3)}, 'c')) AS t(v0__uuid, v1)")
RIGHT = ("WITH bgp_sg_q9_cte AS MATERIALIZED (SELECT * FROM (VALUES "
         f"({U.format(1)}, 'a'), ({U.format(1)}, 'z'), ({U.format(2)}, 'b'), "
         f"({U.format(4)}, 'd')) AS t(v3__uuid, v7)) SELECT * FROM bgp_sg_q9_cte")
SELECT_COLS = ["j0.v0__uuid AS v0__uuid", "j0.v1 AS v1", "j1.v7 AS v7"]
EQ = "j0.v0__uuid = j1.v3__uuid"
REST = "(j0.v1 IS NULL OR CAST(j0.v1 AS TEXT) = CAST(j1.v7 AS TEXT))"


def _plain(join, on):
    return (f"SELECT {', '.join(SELECT_COLS)}\nFROM ({LEFT}) AS j0\n"
            f"{join} ({RIGHT}) AS j1\nON {' AND '.join(on)}")


async def _rows(conn, sql):
    return Counter(tuple(r) for r in await conn.fetch(sql))


async def _plan(conn, sql):
    return "\n".join(r[0] for r in await conn.fetch("EXPLAIN " + sql))


@pytest.mark.parametrize("is_left,on", [
    (True, [EQ]),
    (False, [EQ]),
    (False, [REST, EQ]),
])
async def test_same_rows_and_no_nested_loop(pg_conn, is_left, on):
    from vitalgraph.db.sparql_sql.emit_join import _hashed_cte_join

    hashed = _hashed_cte_join(LEFT, RIGHT, "j0", "j1", on, SELECT_COLS, is_left)
    assert hashed is not None
    want = await _rows(pg_conn, _plain("LEFT JOIN" if is_left else "JOIN", on))
    assert await _rows(pg_conn, hashed) == want
    assert sum(want.values()) > 0
    plan = await _plan(pg_conn, hashed)
    assert "Full Join" in plan and "Nested Loop" not in plan, plan


async def test_declines_what_it_cannot_hash():
    from vitalgraph.db.sparql_sql.emit_join import _hashed_cte_join

    # Not a slot-group BGP on the right.
    assert _hashed_cte_join(LEFT, "SELECT 1", "j0", "j1", [EQ], SELECT_COLS, True) is None
    # An OPTIONAL's other ON conditions cannot leave the ON.
    assert _hashed_cte_join(LEFT, RIGHT, "j0", "j1", [REST, EQ], SELECT_COLS, True) is None
    # A side that may be unbound: no plain equality to hash on.
    nullable = "(j0.v0__uuid IS NULL OR j0.v0__uuid = j1.v3__uuid)"
    assert _hashed_cte_join(LEFT, RIGHT, "j0", "j1", [nullable], SELECT_COLS, False) is None
    # A typed lane is NULL for a bound non-number: not a key.
    lane = "j0.v0__num = j1.v3__num"
    assert _hashed_cte_join(LEFT, RIGHT, "j0", "j1", [lane], SELECT_COLS, False) is None
