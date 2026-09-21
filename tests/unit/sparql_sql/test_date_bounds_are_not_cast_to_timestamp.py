"""A date bound is a TEXT parameter normalised in SQL, never `$n::timestamp`.

Observed in production, once per dated listing, in both halves of the fast path:

    WARNING - prop_sort page failed, caller will fall back
    asyncpg.exceptions.DataError: invalid input for query argument $4:
        '2026-06-23T14:00:00.000Z' (expected a datetime.date or
        datetime.datetime instance, got 'str')

asyncpg types each parameter from the statement PostgreSQL describes back, so
`$n::timestamp` declares $n a timestamp and the driver then refuses the ISO
string the listing holds. Both `fast_entity_prop_page` and
`fast_entity_prop_count` caught it and returned None, so this never produced a
wrong answer -- it meant `created_after` / `modified_before` had NEVER been
served by the table, in any space, while every other filter was.

The cast would be wrong even handed a datetime. `value_dt` is `term.dt_val`,
which is `vitalgraph_iso_to_utc(term_text)` -- normalised to UTC. `::timestamp`
IGNORES the offset, so a `+05:00` bound would compare five hours off the rows it
is filtering. Calling the same function the column was built with is the only
form that cannot drift from it.

Unit level, over the SQL the three builders emit, so it runs with no database.
The page and the count are checked against real rows in
`tests/integration/test_date_range_filters_are_served.py`.
"""

from __future__ import annotations

import re

import pytest

from vitalgraph.db.sparql_sql import fast_prop_sort as E
from vitalgraph.db.sparql_sql import fast_frame_prop_sort as F

NAME = "http://vital.ai/ontology/vital-core#hasName"
BOUND = "2026-06-23T14:00:00.000Z"

# `$4::timestamp`, `$12 :: TIMESTAMP` -- a parameter cast straight to the type.
_PARAM_CAST = re.compile(r"\$\d+\s*::\s*timestamp", re.IGNORECASE)

DATED_FILTERS = [
    {"created_after": BOUND},
    {"created_before": BOUND},
    {"modified_after": BOUND},
    {"modified_before": BOUND},
    {"created_after": BOUND, "modified_before": BOUND},
]


def _entity_page_sql(filters) -> tuple:
    terms = E._filter_terms(filters)
    assert terms, f"{filters} must be expressible; got {terms!r}"
    built = E.build_page_sql("sp_x", terms, sort_by=NAME, descending=False)
    assert built is not None, f"the page declined {filters}"
    return built


def _frame_page_sql(filters) -> tuple:
    terms = F._filter_terms(filters)
    assert terms, f"{filters} must be expressible; got {terms!r}"
    built = F.build_frame_page_sql("sp_x", terms, sort_by=None, descending=False)
    assert built is not None, f"the frame page declined {filters}"
    return built


async def _entity_count_sql(filters) -> str:
    """The SQL `fast_entity_prop_count` builds, without a database.

    It has no builder to call -- the statement is assembled inside the coroutine
    and only ever handed to a connection -- so a connection is what stands in.
    That inline assembly is exactly why the count carried its own copy of the
    cast and had to be fixed twice.
    """
    captured: dict[str, str] = {}

    class _Conn:
        async def fetchval(self, sql, *args):
            if "to_regclass" in sql:
                return "some.oid"          # the table is present
            captured["sql"] = sql
            return 0

        async def fetchrow(self, sql, *args):
            return None                    # nothing blocked

    class _Pool:
        def acquire(self):
            class _Ctx:
                async def __aenter__(_self):
                    return _Conn()

                async def __aexit__(_self, *exc):
                    return False
            return _Ctx()

    class _Impl:
        db_impl = type("_Db", (), {"connection_pool": _Pool()})()

    E.reset_prop_sort_present_cache()
    await E.fast_entity_prop_count(
        _Impl(), "sp_x", "http://example.org/g",
        entity_type_uri="http://example.org/T", filters=filters)
    assert "sql" in captured, "the count never reached the connection"
    return captured["sql"]


def _assert_normalised(sql: str, who: str) -> None:
    cast = _PARAM_CAST.search(sql)
    assert cast is None, (
        f"`{cast.group() if cast else ''}` types the parameter as a timestamp, "
        f"and asyncpg then rejects the ISO string the listing holds, so every "
        f"dated {who} falls back:\n{sql}")
    assert "vitalgraph_iso_to_utc(" in sql, (
        f"the {who} must read its bound with the same function `value_dt` was "
        f"derived with, or the comparison drifts from the column:\n{sql}")


@pytest.mark.parametrize("filters", DATED_FILTERS)
def test_the_entity_page_normalises_its_bound(filters):
    sql, _params = _entity_page_sql(filters)
    _assert_normalised(sql, "page")


@pytest.mark.parametrize("filters", DATED_FILTERS)
@pytest.mark.asyncio
async def test_the_entity_count_normalises_its_bound(filters):
    """The count must not merely avoid the crash, it must read the same bound.

    A count that declines while the page serves is the defect
    `test_count_and_page_move_together` exists for: they run concurrently and
    the request waits for both.
    """
    _assert_normalised(await _entity_count_sql(filters), "count")


@pytest.mark.parametrize("filters", DATED_FILTERS)
def test_the_frame_page_normalises_its_bound(filters):
    sql, _params = _frame_page_sql(filters)
    _assert_normalised(sql, "frame page")


@pytest.mark.parametrize("filters", DATED_FILTERS)
def test_the_bound_is_passed_as_the_string_it_arrived_as(filters):
    """Not parsed in Python, which would put the UTC decision in a second place."""
    _sql, params = _entity_page_sql(filters)
    assert BOUND in params, f"the bound should reach the driver as a str: {params!r}"
