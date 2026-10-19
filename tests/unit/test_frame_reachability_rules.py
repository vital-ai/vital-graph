"""What a frame write names outside itself — issues/279.

`outside_references` decides, from the request alone, what the in-transaction
postcheck must look up. A self-contained request gets no postcheck at all, so the
common write pays nothing for the rule.
"""

from __future__ import annotations

import asyncio

import pytest

from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge

from vitalgraph.kg_impl import frame_reachability as R


def _frame(u):
    f = KGFrame()
    f.URI = u
    return f


def _slot(u):
    s = KGTextSlot()
    s.URI = u
    return s


def _edge(cls, src, dst, n=[0]):
    n[0] += 1
    e = cls()
    e.URI = f"urn:e:{n[0]}"
    e.edgeSource = src
    e.edgeDestination = dst
    return e


def test_a_self_contained_write_names_nothing_and_gets_no_postcheck():
    objs = [_frame("urn:f"), _slot("urn:s"), _edge(Edge_hasKGSlot, "urn:f", "urn:s"),
            _frame("urn:c"), _edge(Edge_hasKGFrame, "urn:f", "urn:c")]
    assert R.outside_references(objs) == (set(), set())
    assert R.reachability_postcheck("sp", "urn:g", objs) is None


def test_the_production_shape_names_the_absent_child():
    """Parent, the child's slot and both edges — no child frame."""
    objs = [_frame("urn:p"), _edge(Edge_hasKGFrame, "urn:p", "urn:p:child"),
            _slot("urn:p:child:s"), _edge(Edge_hasKGSlot, "urn:p:child", "urn:p:child:s")]
    names, loose = R.outside_references(objs)
    assert names == {"urn:p:child"} and loose == set()
    assert R.reachability_postcheck("sp", "urn:g", objs) is not None


def test_links_to_a_stored_entity_or_parent_are_looked_up_not_refused():
    objs = [_frame("urn:f"), _edge(Edge_hasEntityKGFrame, "urn:entity", "urn:f"),
            _edge(Edge_hasKGFrame, "urn:stored-parent", "urn:f")]
    names, _ = R.outside_references(objs)
    assert names == {"urn:entity", "urn:stored-parent"}


def test_a_slot_no_edge_reaches_is_loose():
    objs = [_frame("urn:f"), _slot("urn:s1"), _slot("urn:s2"),
            _edge(Edge_hasKGSlot, "urn:f", "urn:s1")]
    assert R.outside_references(objs) == (set(), {"urn:s2"})


def test_non_structural_edges_are_not_rules():
    """Only the links reads walk; any other edge may name what it likes."""
    objs = [_frame("urn:f"), _edge(VITAL_Edge, "urn:f", "urn:elsewhere")]
    assert R.outside_references(objs) == (set(), set())


class _Conn:
    def __init__(self, present=(), edged=()):
        self.present, self.edged = set(present), set(edged)

    async def fetch(self, sql, uuids, *a):
        from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
        pool = self.edged if "object_uuid" in sql.split("FROM")[0] else self.present
        key = "object_uuid" if pool is self.edged else "subject_uuid"
        return [{key: _generate_term_uuid(u, 'U')} for u in pool
                if _generate_term_uuid(u, 'U') in set(uuids)]


@pytest.fixture
def no_schema(monkeypatch):
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    monkeypatch.setattr(SparqlSQLSchema, "get_table_names",
                        staticmethod(lambda sp: {"rdf_quad": f"{sp}_rdf_quad"}))


def test_the_refusal_names_every_missing_object_and_loose_slot(no_schema):
    objs = [_frame("urn:p"), _edge(Edge_hasKGFrame, "urn:p", "urn:gone"),
            _edge(Edge_hasEntityKGFrame, "urn:entity", "urn:p"), _slot("urn:loose")]
    check = R.reachability_postcheck("sp", "urn:g", objs)
    with pytest.raises(R.UnreachableObjects) as e:
        asyncio.run(check(_Conn(present={"urn:entity"})))
    assert e.value.missing == ["urn:gone"] and e.value.unattached == ["urn:loose"]
    assert "urn:gone" in str(e.value) and "urn:loose" in str(e.value)
    assert e.value.status == "invalid_request"


def test_present_names_and_stored_slot_edges_pass(no_schema):
    objs = [_frame("urn:p"), _edge(Edge_hasKGFrame, "urn:stored", "urn:p"),
            _slot("urn:s")]
    check = R.reachability_postcheck("sp", "urn:g", objs)
    asyncio.run(check(_Conn(present={"urn:stored"}, edged={"urn:s"})))
