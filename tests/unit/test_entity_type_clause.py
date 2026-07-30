"""Unit tests for the entity vitaltype UNION in the KG query builder.

``_build_entity_where_clause`` emits a 4-way UNION over KGEntity subtypes to bind
``?entity``. That UNION is redundant whenever a more selective constraint already
pins ``?entity`` — an explicit ``hasKGEntityType``, or a ``VALUES`` list of URIs —
and enumerating four vitaltypes to establish something another triple already
establishes is pure cost.

It is load-bearing in the unconstrained case, though, so these tests pin both
directions. Suppressing it there would silently widen the result set to every
subject in the graph.

Context: planning/planning_performance/prod_db_saturation_plan.md
"""

import pytest

from vitalgraph.sparql.kg_query_builder import (
    EntityQueryCriteria,
    FrameCriteria,
    SlotCriteria,
)
import vitalgraph.sparql.kg_query_builder as kqb


BASE_KGENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
SUBTYPE_MARKER = "KGNewsEntity"   # only ever appears inside the UNION


@pytest.fixture
def builder():
    """The class exposing _build_entity_where_clause, whatever it is named."""
    for name in dir(kqb):
        obj = getattr(kqb, name)
        if isinstance(obj, type) and hasattr(obj, "_build_entity_where_clause"):
            return obj()
    pytest.fail("no class exposing _build_entity_where_clause found")


def _frame_criteria():
    return [
        FrameCriteria(
            frame_type="urn:cardiff:kg:frame:ContactReferenceFrame",
            slot_criteria=[
                SlotCriteria(
                    slot_type="urn:cardiff:kg:slot:CtRefSFLeadId",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                    value="00QUg00000Y6qq0MAB",
                    comparator="eq",
                )
            ],
        )
    ]


def test_union_suppressed_when_entity_type_pins_entity(builder):
    """The production shape: hasKGEntityType already constrains ?entity."""
    where = builder._build_entity_where_clause(
        EntityQueryCriteria(
            entity_type="urn:cardiff:kg:entity:NurtureAction",
            frame_criteria=_frame_criteria(),
        )
    )
    assert SUBTYPE_MARKER not in where
    # The constraint that replaces it must still be present.
    assert "hasKGEntityType <urn:cardiff:kg:entity:NurtureAction>" in where


def test_union_suppressed_when_entity_uris_pin_entity(builder):
    """A VALUES list pins ?entity even harder than a type constraint."""
    where = builder._build_entity_where_clause(
        EntityQueryCriteria(entity_uris=["urn:cardiff:kg:entity:abc"])
    )
    assert SUBTYPE_MARKER not in where
    assert "VALUES ?entity" in where


def test_union_retained_without_a_pinning_constraint(builder):
    """Generic listing: nothing else binds ?entity, so the UNION is load-bearing."""
    where = builder._build_entity_where_clause(
        EntityQueryCriteria(frame_criteria=_frame_criteria())
    )
    assert SUBTYPE_MARKER in where


def test_union_retained_for_explicit_base_kgentity_type(builder):
    """entity_type == the base KGEntity is not a narrowing constraint.

    The builder does not emit a hasKGEntityType triple in this case, so removing
    the UNION would leave ?entity unbound.
    """
    where = builder._build_entity_where_clause(
        EntityQueryCriteria(entity_type=BASE_KGENTITY)
    )
    assert SUBTYPE_MARKER in where
    assert where.strip()


def test_no_empty_group_emitted_when_union_suppressed(builder):
    """Suppressing the clause must not leave a stray blank in the WHERE body."""
    where = builder._build_entity_where_clause(
        EntityQueryCriteria(entity_uris=["urn:cardiff:kg:entity:abc"])
    )
    assert "{ }" not in where.replace("\n", " ")
    assert not where.lstrip().startswith(".")
    # Braces must still balance.
    assert where.count("{") == where.count("}")
