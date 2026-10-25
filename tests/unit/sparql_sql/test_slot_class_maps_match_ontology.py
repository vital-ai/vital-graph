"""Every slot class the hand-written maps name is a class the ontology defines.

The slot-class maps are copies, kept apart on purpose (the wire model does not
depend on the db package), and copies drift. `fast_slot_sort._LANE` and
`kgqueries_model._PROJECTABLE_SLOT_CLASSES` both spelled `KGJsonSlot`, which
haley-ai-kg does not define; the class is `KGJSONSlot`. Nothing failed: a
projection naming the real class was rejected by the validator as "not
projectable", and a sort on it declined the fast path, both with the JSON slots
sitting in `entity_slot_sort` the whole time.

So the test is against the ontology, not against another copy: a key that is
not a class can never match a stored slot, whichever copy it is in.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import ai_haley_kg_domain
from vitalgraph.db.sparql_sql.fast_slot_sort import _LANE
from vitalgraph.model.kgqueries_model import _PROJECTABLE_SLOT_CLASSES, SlotProjection
from vitalgraph.db.sparql_sql.slot_projection import resolve_columns
from vitalgraph.sparql import kg_query_builder as qb

_KG = "http://vital.ai/ontology/haley-ai-kg#"


def _ontology_classes():
    owl_dir = Path(ai_haley_kg_domain.__file__).parent / "domain-ontology"
    owls = sorted(owl_dir.glob("haley-ai-kg-*.owl"))
    assert owls, f"no haley-ai-kg ontology under {owl_dir}"
    text = owls[-1].read_text(encoding="utf-8")
    return set(re.findall(r'<owl:Class rdf:about="([^"]+)"', text))


_CLASSES = _ontology_classes()

_MAPS = {
    "fast_slot_sort._LANE": set(_LANE),
    "kgqueries_model._PROJECTABLE_SLOT_CLASSES": set(_PROJECTABLE_SLOT_CLASSES),
    "kg_query_builder._SLOT_CLASS_TO_VALUE_PROPERTY": set(qb._SLOT_CLASS_TO_VALUE_PROPERTY),
    "kg_query_builder._URI_VALUE_SLOT_CLASSES": set(qb._URI_VALUE_SLOT_CLASSES),
    "kg_query_builder._DATETIME_SLOT_CLASSES": set(qb._DATETIME_SLOT_CLASSES),
    "kg_query_builder._TEXT_SLOT_CLASSES": set(qb._TEXT_SLOT_CLASSES),
}


@pytest.mark.parametrize("name", sorted(_MAPS))
def test_every_key_is_an_ontology_class(name):
    unknown = sorted(_MAPS[name] - _CLASSES)
    assert not unknown, f"{name} names classes haley-ai-kg does not define: {unknown}"


def test_every_slot_class_has_a_value_property():
    # The builder's map must cover every KGSlot subclass the ontology defines; a
    # missing class falls back to `hasTextSlotValue` and matches nothing.
    owl_dir = Path(ai_haley_kg_domain.__file__).parent / "domain-ontology"
    owl = sorted(owl_dir.glob("haley-ai-kg-*.owl"))[-1].read_text(encoding="utf-8")
    parent = {}
    for cls, body in re.findall(
            r'<owl:Class rdf:about="([^"]+)">(.*?)</owl:Class>', owl, re.S):
        parent[cls] = re.findall(r'<rdfs:subClassOf rdf:resource="([^"]+)"', body)

    def is_slot(c, seen=()):
        return any(p == _KG + "KGSlot" or (p not in seen and is_slot(p, seen + (p,)))
                   for p in parent.get(c, []))

    slots = {c for c in parent if is_slot(c)}
    assert slots, "found no KGSlot subclasses in the ontology"
    missing = sorted(slots - set(qb._SLOT_CLASS_TO_VALUE_PROPERTY))
    assert not missing, f"slot classes with no value property: {missing}"


def test_sort_lanes_are_exactly_the_classes_the_sort_table_stores():
    # `entity_slot_sort` holds the values of `SLOT_VALUE_URIS` only. A class
    # whose value predicate is stored but which has no lane declines the fast
    # path for data that is there (the `KGJsonSlot` failure); a lane for a
    # class whose predicate is not stored would serve an empty column.
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import SLOT_VALUE_URIS
    stored = {u.replace(_KG, "haley:") for u in SLOT_VALUE_URIS}
    served = {c for c, p in qb._SLOT_CLASS_TO_VALUE_PROPERTY.items() if p in stored}
    assert set(_LANE) == served


def test_projectable_classes_are_the_sort_lanes():
    # `_PROJECTABLE_SLOT_CLASSES` says it is "deliberately the SAME map
    # `fast_slot_sort._LANE` uses": a projection and a sort of one column must
    # read one lane.
    assert set(_PROJECTABLE_SLOT_CLASSES) == set(_LANE)


def test_a_json_slot_projects_from_the_text_lane():
    col = SlotProjection(alias="payload", frame_path=["urn:t:frame:F"],
                         slot_type="urn:t:slot:Payload",
                         slot_class_uri=_KG + "KGJSONSlot")
    assert [c.lane for c in resolve_columns([col])] == ["text"]
