"""A whole-entity write must carry every slot's Edge_hasKGSlot — issues/279.

A whole-entity write replaces the entity's graph with the request, so a slot
no edge in the request reaches has nothing stored left to hold it.
"""

from __future__ import annotations

from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot

from vitalgraph.kg_impl.kg_validation_utils import KGEntityValidator


def _o(cls, uri, **kw):
    o = cls()
    o.URI = uri
    for k, v in kw.items():
        setattr(o, k, v)
    return o


def _graph(*, with_slot_edge=True, with_child=True):
    e = "http://example.org/e"
    f, c, s = f"{e}/f", f"{e}/f/c", f"{e}/f/c/s"
    objs = [_o(KGEntity, e, name="e"), _o(KGFrame, f),
            _o(Edge_hasEntityKGFrame, f"{e}/ef", edgeSource=e, edgeDestination=f),
            _o(Edge_hasKGFrame, f"{e}/fc", edgeSource=f, edgeDestination=c),
            _o(KGTextSlot, s, textSlotValue="v")]
    if with_child:
        objs.append(_o(KGFrame, c))
    if with_slot_edge:
        objs.append(_o(Edge_hasKGSlot, f"{e}/cs", edgeSource=c, edgeDestination=s))
    return objs, c, s


def test_a_closed_entity_graph_is_valid():
    objs, _, _ = _graph()
    r = KGEntityValidator().validate_entity_structure(objs)
    assert r.valid, r.errors


def test_a_slot_without_its_edge_is_refused():
    objs, _, s = _graph(with_slot_edge=False)
    r = KGEntityValidator().validate_entity_structure(objs)
    assert not r.valid
    assert any(s in err and "Edge_hasKGSlot" in err for err in r.errors), r.errors


def test_an_absent_child_frame_is_refused():
    objs, c, _ = _graph(with_child=False)
    r = KGEntityValidator().validate_entity_structure(objs)
    assert not r.valid and any(c in err for err in r.errors), r.errors
