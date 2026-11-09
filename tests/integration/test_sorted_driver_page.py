"""`ORDER BY ?v LIMIT k` on a typed holder's value pages from a sorted driver.

`emit_slice._emit_sorted_driver_page`: the holder's top N by the query's own
value order gives a candidate set closed under ties; the full query restricted
to those candidates is the answer when it fills the page, and the full query as
it is answers otherwise. Before it, both generators built every row of the
pattern and sorted them (`l2_page` on lead 100k: >30 s; 0.4 s with it).

EXACT is the claim, so every case runs the rewrite and the plain emission and
compares row for row, in order. The fixture is built to reach every branch:
tied ratings, number-less values (plain strings and dates, which sort in the
NULL tier and on the date tier), a sparse slot that rejects most candidates
(the fallback), a text-valued order (the runtime gate), and a page larger than
the driver.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql import emit_slice

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

H = "http://vital.ai/ontology/haley-ai-kg#"
G = "urn:inttest:sdpage:g"
LEADS = 300
XSD = "http://www.w3.org/2001/XMLSchema#"


def _rating(i: int) -> str:
    if i % 9 == 0:
        return '"n/a"'                                        # no number, no date
    if i % 9 == 1:
        return f'"2026-0{1 + i % 9}-{10 + i % 17}T00:00:00Z"^^<{XSD}dateTime>'
    return f'"{(i * 7) % 40}.5"^^<{XSD}double>'               # ties: 40 values


def _triples(i: int) -> str:
    d, c, a = (f"urn:inttest:sdpage:{k}{i}" for k in ("d", "c", "a"))
    out = (f"<{d}> <{H}hasKGEntityType> <urn:inttest:sdpage:Lead> . "
           f"<{c}> <{H}hasKGGraphURI> <{d}> . "
           f"<{c}> <{H}hasKGSlotType> <urn:inttest:sdpage:Rating> . "
           f"<{c}> <{H}hasDoubleSlotValue> {_rating(i)} . "
           f"<{a}> <{H}hasKGGraphURI> <{d}> . "
           f"<{a}> <{H}hasKGSlotType> <urn:inttest:sdpage:Name> . "
           f'<{a}> <{H}hasTextSlotValue> "name {i:03d}" . ')
    if i % 10 == 0:                                           # sparse: the fallback
        r = f"urn:inttest:sdpage:r{i}"
        out += (f"<{r}> <{H}hasKGGraphURI> <{d}> . "
                f"<{r}> <{H}hasKGSlotType> <urn:inttest:sdpage:Region> . "
                f'<{r}> <{H}hasTextSlotValue> "region {i % 3}" . ')
    return out


BODY = (f"?d <{H}hasKGEntityType> <urn:inttest:sdpage:Lead> . "
        f"?c <{H}hasKGGraphURI> ?d ; <{H}hasKGSlotType> <urn:inttest:sdpage:Rating> ; "
        f"<{H}hasDoubleSlotValue> ?r . "
        f"?a <{H}hasKGGraphURI> ?d ; <{H}hasKGSlotType> <urn:inttest:sdpage:Name> ; "
        f"<{H}hasTextSlotValue> ?name . ")
REGION = (f"?g <{H}hasKGGraphURI> ?d ; <{H}hasKGSlotType> <urn:inttest:sdpage:Region> ; "
          f"<{H}hasTextSlotValue> ?region . ")


def _q(order: str, extra: str = "", select: str = "?d ?name ?r") -> str:
    return f"SELECT {select} WHERE {{ GRAPH <{G}> {{ {BODY}{extra}}} }} {order}"


CASES = {
    "desc": _q("ORDER BY DESC(?r) LIMIT 10"),
    # NULLS FIRST: the number-less values lead, and the 64th key falls among
    # the dates, so the ties are found on the date tier
    "asc": _q("ORDER BY ASC(?r) LIMIT 10"),
    "offset": _q("ORDER BY DESC(?r) LIMIT 10 OFFSET 20"),
    "second key": _q("ORDER BY DESC(?r) DESC(?name) LIMIT 10"),
    # one lead in ten has a region: the candidates do not fill the page
    "fallback": _q("ORDER BY DESC(?r) LIMIT 10", REGION, "?d ?name ?r ?region"),
    # a text value: every driver row ties, the fast branch is skipped
    "text order": _q("ORDER BY ?name LIMIT 10"),
    # more than the driver holds: the candidates are every holder
    "page beyond the driver": _q("ORDER BY DESC(?r) LIMIT 100"),
}


@pytest.fixture
def small_pattern_qualifies(monkeypatch):
    """The size gate is for production patterns (more than 20 rows per
    candidate, 1,280 for a 10-row page); this fixture has 300 leads."""
    monkeypatch.setattr(emit_slice, "SORTED_DRIVER_MIN_ROWS_PER_CANDIDATE", 0)


async def _load(pg_conn, sparql_update, space):
    from vitalgraph.db.sparql_sql.generator import invalidate_stats_cache
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables
    for lo in range(0, LEADS, 50):
        body = " ".join(_triples(i) for i in range(lo, min(LEADS, lo + 50)))
        await sparql_update(f"INSERT DATA {{ GRAPH <{G}> {{ {body} }} }}", space)
    await recompute_stats_tables(pg_conn, space)
    invalidate_stats_cache(space)


@pytest.mark.parametrize("name", list(CASES))
async def test_the_page_is_the_plain_page(name, pg_conn, test_space, sparql_update,
                                          sparql_query_sql, monkeypatch,
                                          small_pattern_qualifies):
    if name == next(iter(CASES)):          # the module's space: load once
        await _load(pg_conn, sparql_update, test_space)
    query = CASES[name]

    new_sql = await sparql_query_sql(query, test_space)
    assert "_fast AS MATERIALIZED" in new_sql, f"{name}: the sorted-driver page should fire"
    monkeypatch.setattr(emit_slice, "_emit_sorted_driver_page", lambda *a, **k: None)
    old_sql = await sparql_query_sql(query, test_space)

    old = [tuple(r) for r in await pg_conn.fetch(old_sql)]
    new = [tuple(r) for r in await pg_conn.fetch(new_sql)]
    assert old, f"{name}: the fixture produced no rows, so the comparison proves nothing"
    assert new == old, f"{name}: the sorted-driver page differs from the plain page"


async def test_the_branches_the_cases_claim(pg_conn, test_space, sparql_query_sql,
                                            small_pattern_qualifies):
    """The cases above reach what they are named for: the fallback runs the
    full branch, the text order skips the fast one, `desc` is served fast.
    Read from the plan: the full branch is the Append's second child."""
    import json
    for name, want_fast in (("desc", True), ("fallback", False), ("text order", False)):
        sql = await sparql_query_sql(CASES[name], test_space)
        plan = await pg_conn.fetchval("EXPLAIN (ANALYZE, FORMAT JSON) " + sql)
        plan = plan if isinstance(plan, list) else json.loads(plan)
        full_ran = _full_branch_ran(plan[0]["Plan"])
        assert full_ran is (not want_fast), (
            f"{name}: expected the {'fast' if want_fast else 'full'} branch")


def _full_branch_ran(node) -> bool:
    """True when the Append's second child (the full branch) produced rows."""
    if node.get("Node Type") == "Append":
        kids = node.get("Plans", [])
        return len(kids) == 2 and (kids[1].get("Actual Rows", 0) or 0) > 0
    return any(_full_branch_ran(k) for k in node.get("Plans", []))


async def test_a_selective_constant_elsewhere_keeps_the_plain_page(
        test_space, sparql_query_sql, small_pattern_qualifies):
    """A leaf 10x narrower than the driver's pin already bounds the sort, and
    PostgreSQL nests the candidates under it (measured: 29 s for a 931-row
    state code against a 100,000-row pin). The rewrite declines."""
    query = _q("ORDER BY DESC(?r) LIMIT 10",
               f"?g <{H}hasKGGraphURI> ?d ; <{H}hasTextSlotValue> \"region 1\" . ",
               "?d ?name ?r")
    sql = await sparql_query_sql(query, test_space)
    assert "_fast AS MATERIALIZED" not in sql
