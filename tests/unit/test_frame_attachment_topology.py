"""How an entity attaches to a frame: its TOPOLOGY.

`issues/043`. The builder only ever emitted one topology: entity
--hasEntityKGFrame--> frame. Datasets that model relations as frames whose slots
point AT the entities have no such link, so every entity query over them returned
zero rows — indistinguishable from "nothing matched".

`wordnet_frames` is such a dataset: 109,745 entities, 285,348 frames, and its
only edge kind is `Edge_hasKGSlot`. The integration counterpart to this file
asserts the counts come back right there; this file asserts the SHAPE, which
needs no database.

Links are always the reified edge objects. The `vg-direct:` property spelling
(KGQuery's direct mode) was removed in `issues/298`: no space has those
predicates and nothing writes them.
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


class TestStandaloneSlotCriteria:
    """Both hops are emitted as edges, and nothing of the removed direct mode."""

    @pytest.mark.parametrize("kw", [
        dict(value="x", comparator="eq"),
        dict(comparator="not_exists"),
        dict(comparator="is_empty"),
    ], ids=["value", "not_exists", "is_empty"])
    def test_edge_mode_still_emits_both_hops(self, builder, kw):
        sql = builder.build_entity_query_sparql(
            EntityQueryCriteria(
                slot_criteria=[SlotCriteria(slot_type=f"{KG}hasName", **kw)]),
            GRAPH, 25, 0)
        assert "Edge_hasEntityKGFrame" in sql
        assert "Edge_hasKGSlot" in sql
        assert "vg-direct" not in sql
