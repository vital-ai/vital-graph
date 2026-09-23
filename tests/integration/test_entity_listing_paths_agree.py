"""The fast entity listing must answer exactly what the slow one answers.

Both halves of this were shipped to production on 2026-09-23 with no check that
they returned the right ROWS -- only unit tests asserting SQL shape against
fakes. They were correct, but nothing here established that, and the same two
changes could as easily have been wrong:

* the COUNT matched every property row of every qualifying entity -- five or six
  lanes each -- and de-duplicated afterwards, where the PAGE reads only the lane
  it sorts on. Pinning it to one lane is equivalent ONLY because the filter
  subquery guarantees that row and `(entity_uuid, context_uuid, property_uuid)`
  is the primary key. If either stops holding, the count silently changes;
* `include_entity_graph=true` resolved its page of URIs in SPARQL instead of
  taking the fast path's. Now it takes the fast path's -- which is safe only if
  the two produce the same URIs IN THE SAME ORDER.

So these are AGREEMENT tests rather than expected-value tests: they compare the
two implementations against each other on the same data, which is the property
that has to hold and the one that no amount of SQL-shape assertion can reach.
"""

from __future__ import annotations

import re

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

AIMP = "http://vital.ai/ontology/vital-aimp#"
CORE = "http://vital.ai/ontology/vital-core#"
KG = "http://vital.ai/ontology/haley-ai-kg#"
EX = "http://example.org/elp/"
GRAPH = "http://example.org/elp/graph"
ETYPE = f"{EX}Widget"

CREATED = f"{AIMP}hasObjectCreationTime"
MODIFIED = "http://vital.ai/ontology/vital#hasObjectModificationDateTime"
STATUS = f"{AIMP}hasObjectStatusType"
NAME = f"{CORE}hasName"
ACTIVE = f"{AIMP}ObjectStatusType_ACTIVE"

#: Several lanes per entity is the whole point -- with one lane the count
#: defect is invisible, because there is nothing extra to match.
ROWS = [
    ("e1", "alpha", "2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z"),
    ("e2", "bravo", "2026-02-01T00:00:00Z", "2026-01-15T00:00:00Z"),
    ("e3", "charlie", "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z"),
    ("e4", "delta", "2026-04-01T00:00:00Z", "2026-02-01T00:00:00Z"),
    ("e5", "echo", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z"),
]

DT = "http://www.w3.org/2001/XMLSchema#dateTime"


def _quads():
    from rdflib import URIRef, Literal
    g = URIRef(GRAPH)
    out = []
    for name, label, created, modified in ROWS:
        e = URIRef(f"{EX}{name}")
        out.append((e, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), g))
        out.append((e, URIRef(f"{KG}hasKGEntityType"), URIRef(ETYPE), g))
        out.append((e, URIRef(NAME), Literal(label), g))
        out.append((e, URIRef(STATUS), URIRef(ACTIVE), g))
        out.append((e, URIRef(CREATED), Literal(created, datatype=URIRef(DT)), g))
        out.append((e, URIRef(MODIFIED), Literal(modified, datatype=URIRef(DT)), g))
    return out


async def _count(impl, space, **kw):
    from vitalgraph.db.sparql_sql.fast_prop_sort import fast_entity_prop_count
    return await fast_entity_prop_count(
        impl, space, GRAPH, entity_type_uri=ETYPE, **kw)


class TestTheCountReadsOneLane:
    """The pinned count must equal the unpinned one it replaced."""

    @pytest.mark.parametrize("filters", [
        {"created_after": "2026-02-15T00:00:00Z"},
        {"created_before": "2026-04-15T00:00:00Z"},
        {"modified_after": "2026-02-15T00:00:00Z"},
        {"status": ACTIVE},
        {"created_after": "2026-01-15T00:00:00Z", "status": ACTIVE},
        {"created_after": "2026-01-15T00:00:00Z",
         "modified_before": "2026-04-15T00:00:00Z"},
    ], ids=["created_after", "created_before", "modified_after", "status",
            "created+status", "created+modified"])
    async def test_pinning_the_lane_does_not_change_the_answer(
            self, test_space, space_impl, pg_pool, filters):
        await space_impl.add_rdf_quads_batch(test_space, _quads())

        pinned = await _count(space_impl, test_space, filters=filters,
                              sort_by=CREATED)
        assert pinned is not None, "the fast count declined; nothing was compared"

        # The same query with the lane pin removed -- the shape this replaced.
        unpinned = await self._unpinned(space_impl, test_space, filters, pg_pool)
        assert unpinned == pinned, (
            f"pinning the count to one property lane changed the answer: "
            f"{pinned} pinned against {unpinned} unpinned, filters={filters}")

    @staticmethod
    async def _unpinned(impl, space, filters, pg_pool):
        """The pre-fix count: outer scan across every lane, de-duplicated."""
        from vitalgraph.db.sparql_sql import fast_prop_sort as fps

        holder = {}

        class _Spy:
            def __init__(self, raw):
                self._raw = raw

            def __getattr__(self, n):
                return getattr(self._raw, n)

            async def fetchval(self, sql, *a):
                if "count(" in sql:
                    holder["sql"], holder["args"] = sql, a
                return await self._raw.fetchval(sql, *a)

        class _Pool:
            def __init__(self, raw): self._raw = raw
            def acquire(self):
                outer = self._raw

                class _Cm:
                    async def __aenter__(self_i):
                        self_i._cm = outer.acquire()
                        return _Spy(await self_i._cm.__aenter__())

                    async def __aexit__(self_i, *e):
                        return await self_i._cm.__aexit__(*e)

                return _Cm()

        shim = type("I", (), {"db_impl": type("D", (), {
            "connection_pool": _Pool(impl.db_impl.connection_pool)})()})()
        await fps.fast_entity_prop_count(
            shim, space, GRAPH, entity_type_uri=ETYPE,
            filters=filters, sort_by=CREATED)
        assert "sql" in holder, "no count query was issued"
        stripped, n = re.subn(r" AND s\.property_uuid = \$\d+", "", holder["sql"])
        assert n == 1, "the count is no longer pinned to a lane; this test is moot"
        async with pg_pool.acquire() as conn:
            return int(await conn.fetchval(stripped, *holder["args"]) or 0)


class TestTheGraphListingPageMatches:
    """`include_entity_graph=true` takes the fast path's page of URIs. It has to
    be the SAME page, in the same order, as the SPARQL query it replaced."""

    @pytest.mark.parametrize("sort_by,order", [
        (CREATED, "desc"), (CREATED, "asc"), (NAME, "asc"), (NAME, "desc"),
    ], ids=["created_desc", "created_asc", "name_asc", "name_desc"])
    async def test_fast_page_equals_the_sparql_page(
            self, test_space, space_impl, backend_adapter, sparql_execute,
            sort_by, order):
        await space_impl.add_rdf_quads_batch(test_space, _quads())
        from vitalgraph.kg_impl.kgentity_list_impl import KGEntityListProcessor
        from vitalgraph.db.sparql_sql.fast_prop_sort import fast_entity_prop_page

        fast = await fast_entity_prop_page(
            space_impl, test_space, GRAPH, 50, 0,
            entity_type_uri=ETYPE, filters=None,
            sort_by=sort_by, sort_order=order)
        assert fast is not None, "the fast page declined; nothing was compared"

        proc = KGEntityListProcessor()
        sparql = proc._build_entity_uris_query(
            GRAPH, 50, 0, ETYPE, None, sort_by=sort_by, sort_order=order,
            prop_filters="")
        bindings = await sparql_execute(sparql, test_space)
        slow = [b["entity"]["value"] for b in bindings if "entity" in b]

        assert fast == slow, (
            f"the two paths page differently for sort_by={sort_by} {order}\n"
            f"  fast:  {[u.rsplit('/', 1)[-1] for u in fast]}\n"
            f"  sparql:{[u.rsplit('/', 1)[-1] for u in slow]}")
