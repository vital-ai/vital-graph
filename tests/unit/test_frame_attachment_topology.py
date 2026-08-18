"""How an entity attaches to a frame is a separate axis from how a link is spelled.

`issues/043`. `use_edge_pattern` chooses the SPELLING of a link — a reified edge
node or a direct property. It does not choose the TOPOLOGY, and the builder only
ever emitted one: entity --hasEntityKGFrame--> frame. Datasets that model
relations as frames whose slots point AT the entities have no such link in either
spelling, so every entity query over them returned zero rows — indistinguishable
from "nothing matched".

`wordnet_frames` is such a dataset: 109,745 entities, 285,348 frames, and its
only edge kind is `Edge_hasKGSlot`. The integration counterpart to this file
asserts the counts come back right there; this file asserts the SHAPE, which
needs no database.

The second concern here is the leak the same issue flagged: the standalone
`slot_criteria` path hardcoded BOTH hops as edges with no `use_edge_pattern`
check, so a caller asking for direct-property mode silently got edge-pattern
SPARQL for part of its query — and, on a direct-property dataset, zero rows for
the same invisible reason.
"""

from __future__ import annotations

import pytest

from vitalgraph.sparql.kg_query_builder import (
    EntityQueryCriteria,
    FrameCriteria,
    KGQueryCriteriaBuilder,
    SlotCriteria,
)

GRAPH = "urn:test"
KG = "http://vital.ai/ontology/haley-ai-kg#"
SRC_ROLE = "urn:hasSourceEntity"


@pytest.fixture
def builder():
    return KGQueryCriteriaBuilder()


def _query(builder, **kw):
    return builder.build_entity_query_sparql(
        EntityQueryCriteria(frame_criteria=[FrameCriteria(frame_type=f"{KG}T")], **kw),
        GRAPH, 25, 0)


class TestAttachmentTopology:

    def test_contains_is_the_default_and_is_unchanged(self, builder):
        """The existing topology must survive being made selectable."""
        sql = _query(builder)
        assert "Edge_hasEntityKGFrame" in sql
        assert "hasEntitySlotValue" not in sql

    def test_slot_value_reaches_the_entity_through_a_slot(self, builder):
        sql = _query(builder, frame_attachment="slot_value")
        # The frame owns the slot, and the slot's value IS the entity. The
        # attachment edge must run frame -> slot, not entity -> frame.
        assert "Edge_hasKGSlot" in sql
        assert "hasEntitySlotValue ?entity" in sql
        assert "Edge_hasEntityKGFrame" not in sql, "still emitting the old topology"

    def test_slot_value_honours_direct_property_spelling(self, builder):
        """Topology and spelling are independent — all four combinations emit."""
        sql = _query(builder, frame_attachment="slot_value", use_edge_pattern=False)
        assert "vg-direct:hasSlot" in sql
        assert "hasEntitySlotValue ?entity" in sql
        assert "Edge_has" not in sql

    def test_attachment_role_is_constrained_when_given(self, builder):
        sql = _query(builder, frame_attachment="slot_value", attachment_slot_type=SRC_ROLE)
        assert f"hasKGSlotType <{SRC_ROLE}>" in sql

    def test_attachment_role_is_unconstrained_by_default(self, builder):
        """Omitting the role must match any role, not silently pick one."""
        sql = _query(builder, frame_attachment="slot_value")
        assert SRC_ROLE not in sql

    def test_attachment_slot_var_cannot_collide_with_a_criterion_slot(self, builder):
        """The attachment slot and a slot criterion are different slots.

        Reusing one variable would silently force them to be the same node,
        turning "entities attached to this frame that also have slot X" into
        "entities attached THROUGH slot X".
        """
        sql = builder.build_entity_query_sparql(
            EntityQueryCriteria(
                frame_criteria=[FrameCriteria(
                    frame_type=f"{KG}T",
                    slot_criteria=[SlotCriteria(slot_type=f"{KG}hasName",
                                                value="x", comparator="eq")])],
                frame_attachment="slot_value"),
            GRAPH, 25, 0)
        assert "?attach_slot_frame_0" in sql
        assert "?slot_0_0" in sql

    def test_unknown_attachment_is_rejected(self, builder):
        """A typo must not silently fall back to the topology that returns zero."""
        with pytest.raises(ValueError, match="frame_attachment"):
            _query(builder, frame_attachment="via_slot")


class TestStandaloneSlotCriteriaHonourSpelling:
    """The leak: these three branches ignored `use_edge_pattern` entirely."""

    @pytest.mark.parametrize("kw", [
        dict(value="x", comparator="eq"),
        dict(comparator="not_exists"),
        dict(comparator="is_empty"),
    ], ids=["value", "not_exists", "is_empty"])
    def test_direct_mode_emits_no_edge_pattern(self, builder, kw):
        sql = builder.build_entity_query_sparql(
            EntityQueryCriteria(
                slot_criteria=[SlotCriteria(slot_type=f"{KG}hasName", **kw)],
                use_edge_pattern=False),
            GRAPH, 25, 0)
        assert "Edge_has" not in sql, "edge pattern leaked into direct-property mode"
        assert "vg-direct:" in sql

    @pytest.mark.parametrize("kw", [
        dict(value="x", comparator="eq"),
        dict(comparator="not_exists"),
        dict(comparator="is_empty"),
    ], ids=["value", "not_exists", "is_empty"])
    def test_edge_mode_still_emits_both_hops(self, builder, kw):
        sql = builder.build_entity_query_sparql(
            EntityQueryCriteria(
                slot_criteria=[SlotCriteria(slot_type=f"{KG}hasName", **kw)],
                use_edge_pattern=True),
            GRAPH, 25, 0)
        assert "Edge_hasEntityKGFrame" in sql
        assert "Edge_hasKGSlot" in sql
