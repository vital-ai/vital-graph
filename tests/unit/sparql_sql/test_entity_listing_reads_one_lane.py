"""An entity listing reads the lane it needs, and its page comes from the fast path.

Two defects found on production 2026-09-23, both on the NurtureAction listing:

* the COUNT matched every property row of every qualifying entity -- five or six
  lanes each -- and de-duplicated afterwards, while the PAGE read only the lane
  it sorts on. 81,135 rows / 83,800 buffers against 16,227 / 16,441 for the same
  answer;
* asking for `include_entity_graph=true` silently gave up the fast path for the
  page of URIs too, so the URI page was resolved in SPARQL: one query looping
  **84,941 times** -- once per entity of that type -- to return 25 rows.
  gen 14 ms, exec 27,935 ms, 1,430,060 buffers, flagged `disproportionate` with
  3,397 loops per returned row. The same page through the fast path is 71 ms.
"""
from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql import fast_prop_sort

CREATED = "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime"
ENTITY_TYPE = "urn:acme:kg:entity:NurtureAction"


class _Conn:
    def __init__(self):
        self.sql = None
        self.args = None

    async def fetchval(self, sql, *args):
        self.sql, self.args = sql, args
        return 16227


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Cm:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False

        return _Cm()


class _Impl:
    def __init__(self, conn):
        self.db_impl = type("D", (), {"connection_pool": _Pool(conn)})()


@pytest.fixture
def conn(monkeypatch):
    c = _Conn()
    async def present(*a, **k): return True
    async def blocked(*a, **k): return False
    monkeypatch.setattr(fast_prop_sort, "prop_sort_table_present", present)
    monkeypatch.setattr(fast_prop_sort, "prop_sort_blocked", blocked)
    return c


@pytest.mark.asyncio
async def test_a_filtered_count_is_pinned_to_one_property_lane(conn):
    n = await fast_prop_sort.fast_entity_prop_count(
        _Impl(conn), "sp", "urn:g", entity_type_uri=ENTITY_TYPE,
        filters={"created_after": "2026-08-24T02:00:00Z"}, sort_by=CREATED)
    assert n == 16227
    sql = " ".join(conn.sql.split())
    assert "s.entity_uuid IN (" in sql, sql
    assert "AND s.property_uuid = $" in sql, (
        "the outer scan reads every lane of every qualifying entity; the "
        "subquery already restricts to one lane and the PK makes it single-row")


@pytest.mark.asyncio
async def test_an_unfiltered_count_is_left_alone(conn):
    """With no filter there is no lane the subquery guarantees, so pinning
    would change the answer rather than the cost."""
    await fast_prop_sort.fast_entity_prop_count(
        _Impl(conn), "sp", "urn:g", entity_type_uri=ENTITY_TYPE)
    sql = " ".join(conn.sql.split())
    assert "s.property_uuid" not in sql, sql


class TestTheGraphListingUsesTheFastPage:
    """`include_entity_graph=true` must not give up the fast path for the URI
    page. It needs exactly what `fast_entity_page` returns."""

    @staticmethod
    def _processor():
        from vitalgraph.kg_impl.kgentity_list_impl import KGEntityListProcessor
        return KGEntityListProcessor()

    class _Adapter:
        def __init__(self, fast_uris):
            self.fast_uris = fast_uris
            self.sparql_calls = []
            self.fast_calls = 0

        async def fast_entity_page(self, *a, **k):
            self.fast_calls += 1
            return self.fast_uris

        async def execute_sparql_query(self, space_id, sparql):
            self.sparql_calls.append(sparql)
            return {"results": {"bindings": []}}

    @pytest.mark.asyncio
    async def test_the_uri_page_comes_from_the_fast_path(self, monkeypatch):
        proc = self._processor()
        adapter = self._Adapter(["urn:e:1", "urn:e:2"])

        async def no_count(*a, **k):
            return 2
        monkeypatch.setattr(proc, "_resolve_total_count", no_count)

        async def fake_graphs(*a, **k):
            return []
        monkeypatch.setattr(proc, "_fetch_graphs_batched", fake_graphs, raising=False)

        try:
            await proc._list_entities_with_graph(
                "sp", "urn:g", 25, 0, ENTITY_TYPE, None, adapter,
                sort_by=CREATED, sort_order="desc")
        except Exception:
            pass                      # hydration is stubbed; the page is the point
        assert adapter.fast_calls == 1, "the fast page was never attempted"
        assert not any("ORDER BY" in q for q in adapter.sparql_calls), (
            "a SPARQL URI query ran even though the fast path returned a page; "
            "that query looped 84,941 times for 25 rows on production")

    @pytest.mark.asyncio
    async def test_a_decline_still_falls_back_to_sparql(self, monkeypatch):
        proc = self._processor()
        adapter = self._Adapter(None)          # fast path declines

        async def no_count(*a, **k):
            return 0
        monkeypatch.setattr(proc, "_resolve_total_count", no_count)

        res = await proc._list_entities_with_graph(
            "sp", "urn:g", 25, 0, ENTITY_TYPE, "some search", adapter,
            sort_by=CREATED, sort_order="desc")
        assert adapter.fast_calls == 1
        assert adapter.sparql_calls, "declining must fall back, not return empty"
        assert res.total_count == 0
