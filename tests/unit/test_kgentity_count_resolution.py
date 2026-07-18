"""Unit tests for KGEntity listing count resolution (Fix 1 + Fix 3).

Covers the pure logic added to speed up the default KG Entities render:
  - KGEntityListProcessor._resolve_total_count: cache → fast SQL → SPARQL
  - SparqlSQLBackendAdapter.fast_entity_count guard conditions

The direct-SQL execution itself needs a live PostgreSQL space and is not
exercised here; these tests pin the control flow and fallbacks.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from vitalgraph.kg_impl.kgentity_list_impl import KGEntityListProcessor
from vitalgraph.kg_impl.kg_backend_utils import SparqlSQLBackendAdapter
from vitalgraph.cache.count_cache import _count_cache


GRAPH = "http://vital.ai/graph/wordnet_frames"


class _FakeAdapter:
    """Minimal backend adapter double.

    fast_count: value returned by fast_entity_count (None → miss/fallback),
                or the string "absent" to omit the method entirely.
    sparql_count: value the SPARQL fallback should report.
    """

    def __init__(self, fast_count, sparql_count=99):
        self.sparql_calls = 0
        self.fast_calls = 0
        self._sparql_count = sparql_count
        if fast_count != "absent":
            self._fast_count = fast_count
            self.fast_entity_count = self._fast_entity_count

    async def _fast_entity_count(self, space_id, graph_id, entity_type_uri,
                                 search, prop_filters, sort_by):
        self.fast_calls += 1
        return self._fast_count

    async def execute_sparql_query(self, space_id, query):
        self.sparql_calls += 1
        return [{"count": {"value": str(self._sparql_count)}}]


def _resolve(proc, space_id, adapter):
    return asyncio.run(
        proc._resolve_total_count(
            space_id, GRAPH, adapter, count_sparql=f"COUNT-SPARQL-{space_id}",
            entity_type_uri=None, search=None, prop_filters="", sort_by=None,
        )
    )


@pytest.fixture(autouse=True)
def _clean_cache():
    yield
    _count_cache.invalidate_space("space_cache")
    _count_cache.invalidate_space("space_fast")
    _count_cache.invalidate_space("space_fallback")
    _count_cache.invalidate_space("space_absent")


def test_cache_hit_skips_both_queries():
    proc = KGEntityListProcessor()
    adapter = _FakeAdapter(fast_count=5, sparql_count=7)
    qhash = _count_cache.query_hash("COUNT-SPARQL-space_cache")
    _count_cache.put("space_cache", GRAPH, qhash, 123)

    assert _resolve(proc, "space_cache", adapter) == 123
    assert adapter.fast_calls == 0
    assert adapter.sparql_calls == 0


def test_fast_path_used_and_cached():
    proc = KGEntityListProcessor()
    adapter = _FakeAdapter(fast_count=109745, sparql_count=7)

    assert _resolve(proc, "space_fast", adapter) == 109745
    assert adapter.fast_calls == 1
    assert adapter.sparql_calls == 0  # SPARQL never touched

    # Result is written back and reused on the next call.
    assert _resolve(proc, "space_fast", adapter) == 109745
    assert adapter.fast_calls == 1  # no further work — served from cache


def test_falls_back_to_sparql_when_fast_returns_none():
    proc = KGEntityListProcessor()
    adapter = _FakeAdapter(fast_count=None, sparql_count=42)

    assert _resolve(proc, "space_fallback", adapter) == 42
    assert adapter.fast_calls == 1
    assert adapter.sparql_calls == 1


def test_backend_without_fast_path_uses_sparql():
    proc = KGEntityListProcessor()
    adapter = _FakeAdapter(fast_count="absent", sparql_count=8)

    assert not hasattr(adapter, "fast_entity_count")
    assert _resolve(proc, "space_absent", adapter) == 8
    assert adapter.sparql_calls == 1


# --- fast_entity_count guard conditions (short-circuit before any DB use) ---

def _fast(adapter_backend, **kwargs):
    adapter = SparqlSQLBackendAdapter.__new__(SparqlSQLBackendAdapter)
    adapter.backend = adapter_backend
    adapter.logger = MagicMock()
    base = dict(space_id="s", graph_id=GRAPH, entity_type_uri=None,
                search=None, prop_filters="", sort_by=None)
    base.update(kwargs)
    return asyncio.run(
        adapter.fast_entity_count(**base)
    )


@pytest.mark.parametrize("override", [
    {"entity_type_uri": "http://x/Type"},
    {"search": "cat"},
    {"prop_filters": "?entity <p> <o> ."},
    {"sort_by": "http://vital.ai/ontology/vital-core#hasName"},
    {"graph_id": "default"},          # non-URI graph → ambiguous context
    {"graph_id": ""},
])
def test_fast_entity_count_returns_none_for_non_default_shapes(override):
    # backend is never touched for these — a bare object proves it.
    assert _fast(object(), **override) is None
