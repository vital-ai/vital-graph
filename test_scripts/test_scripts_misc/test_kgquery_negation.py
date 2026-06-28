"""Unit tests for KGQuery frame & slot negation support.

Tests that the SPARQL query builder generates correct FILTER NOT EXISTS
and OPTIONAL + !BOUND patterns for:
  - Frame-level negation (FrameCriteria.negate=True)
  - Slot-level not_exists comparator
  - Slot-level is_empty comparator
  - Double negation validation (rejected)
"""

import sys
import os
import unittest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.sparql.kg_query_builder import (
    KGQueryCriteriaBuilder,
    EntityQueryCriteria,
    FrameCriteria,
    SlotCriteria,
    FrameQueryCriteria,
)


class TestFrameNegation(unittest.TestCase):
    """Test FrameCriteria.negate wraps frame pattern in FILTER NOT EXISTS."""

    def setUp(self):
        self.builder = KGQueryCriteriaBuilder()

    # ── Edge mode ──────────────────────────────────────────────────────

    def test_negate_frame_type_only_edge_mode(self):
        """negate=True with frame_type only → FILTER NOT EXISTS wrapping frame connection + type."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:AddressFrame",
                    negate=True,
                )
            ],
            use_edge_pattern=True,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("FILTER NOT EXISTS", sparql)
        self.assertIn("Edge_hasEntityKGFrame", sparql)
        self.assertIn("urn:AddressFrame", sparql)

    def test_negate_frame_with_slot_criteria_edge_mode(self):
        """negate=True with frame_type + slot criteria → combined negation."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:AddressFrame",
                    negate=True,
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:ZipCodeSlot",
                            value="10001",
                            comparator="eq",
                        )
                    ],
                )
            ],
            use_edge_pattern=True,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("FILTER NOT EXISTS", sparql)
        self.assertIn("urn:AddressFrame", sparql)
        self.assertIn("urn:ZipCodeSlot", sparql)
        self.assertIn('"10001"', sparql)

    # ── Direct mode ────────────────────────────────────────────────────

    def test_negate_frame_direct_mode(self):
        """negate=True in direct mode → FILTER NOT EXISTS with vg-direct pattern."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:AddressFrame",
                    negate=True,
                )
            ],
            use_edge_pattern=False,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("FILTER NOT EXISTS", sparql)
        self.assertIn("vg-direct:hasEntityFrame", sparql)
        self.assertIn("urn:AddressFrame", sparql)

    # ── Mix of negated and non-negated ─────────────────────────────────

    def test_mixed_negate_and_normal_frames(self):
        """One negated frame + one normal frame in same query."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(frame_type="urn:ContactFrame", negate=False),
                FrameCriteria(frame_type="urn:AddressFrame", negate=True),
            ],
            use_edge_pattern=True,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        # Should have exactly one FILTER NOT EXISTS (for AddressFrame)
        self.assertEqual(sparql.count("FILTER NOT EXISTS"), 1)
        self.assertIn("urn:ContactFrame", sparql)
        self.assertIn("urn:AddressFrame", sparql)

    # ── Hierarchical child frame negation ──────────────────────────────

    def test_negate_child_frame_in_hierarchy(self):
        """negate=True on a child frame in hierarchical structure."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:ParentFrame",
                    frame_criteria=[
                        FrameCriteria(
                            frame_type="urn:ChildFrame",
                            negate=True,
                        )
                    ],
                )
            ],
            use_edge_pattern=True,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("FILTER NOT EXISTS", sparql)
        self.assertIn("urn:ChildFrame", sparql)
        # ParentFrame should NOT be inside FILTER NOT EXISTS
        self.assertIn("urn:ParentFrame", sparql)


class TestSlotNotExists(unittest.TestCase):
    """Test SlotCriteria.comparator='not_exists' generates FILTER NOT EXISTS."""

    def setUp(self):
        self.builder = KGQueryCriteriaBuilder()

    def test_not_exists_in_frame_criteria_edge_mode(self):
        """not_exists on a slot within a frame → FILTER NOT EXISTS wrapping slot pattern."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:AddressFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:ZipCodeSlot",
                            comparator="not_exists",
                        )
                    ],
                )
            ],
            use_edge_pattern=True,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("FILTER NOT EXISTS", sparql)
        self.assertIn("urn:ZipCodeSlot", sparql)
        self.assertIn("Edge_hasKGSlot", sparql)

    def test_not_exists_direct_mode(self):
        """not_exists in direct mode → FILTER NOT EXISTS with vg-direct:hasSlot."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:AddressFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:ZipCodeSlot",
                            comparator="not_exists",
                        )
                    ],
                )
            ],
            use_edge_pattern=False,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("FILTER NOT EXISTS", sparql)
        self.assertIn("vg-direct:hasSlot", sparql)
        self.assertIn("urn:ZipCodeSlot", sparql)

    def test_not_exists_standalone_slot_criteria(self):
        """not_exists as standalone slot_criteria (no frame_type)."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            slot_criteria=[
                SlotCriteria(
                    slot_type="urn:ZipCodeSlot",
                    comparator="not_exists",
                )
            ],
            use_edge_pattern=True,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("FILTER NOT EXISTS", sparql)
        self.assertIn("urn:ZipCodeSlot", sparql)

    def test_mixed_eq_and_not_exists_same_frame(self):
        """Combine eq on one slot with not_exists on another in same frame."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:AddressFrame",
                    slot_criteria=[
                        SlotCriteria(slot_type="urn:CitySlot", value="Boston", comparator="eq"),
                        SlotCriteria(slot_type="urn:ZipCodeSlot", comparator="not_exists"),
                    ],
                )
            ],
            use_edge_pattern=True,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("FILTER NOT EXISTS", sparql)
        self.assertIn("urn:CitySlot", sparql)
        self.assertIn('"Boston"', sparql)
        self.assertIn("urn:ZipCodeSlot", sparql)

    def test_not_exists_in_frame_query(self):
        """not_exists in build_frame_query_sparql path."""
        criteria = FrameQueryCriteria(
            slot_criteria=[
                SlotCriteria(
                    slot_type="urn:ZipCodeSlot",
                    comparator="not_exists",
                )
            ],
        )
        sparql = self.builder.build_frame_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("FILTER NOT EXISTS", sparql)
        self.assertIn("urn:ZipCodeSlot", sparql)


class TestSlotIsEmpty(unittest.TestCase):
    """Test SlotCriteria.comparator='is_empty' generates OPTIONAL + !BOUND pattern."""

    def setUp(self):
        self.builder = KGQueryCriteriaBuilder()

    def test_is_empty_with_slot_class_uri(self):
        """is_empty with known slot_class_uri → specific value property in OPTIONAL."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:AddressFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:ZipCodeSlot",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                            comparator="is_empty",
                        )
                    ],
                )
            ],
            use_edge_pattern=True,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("OPTIONAL", sparql)
        self.assertIn("!BOUND", sparql)
        self.assertIn("hasTextSlotValue", sparql)
        # Slot connection should be mandatory (not inside OPTIONAL)
        self.assertIn("Edge_hasKGSlot", sparql)

    def test_is_empty_without_slot_class_uri_or_type(self):
        """is_empty without slot_class_uri or slot_type → multi-property OPTIONAL check."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:AddressFrame",
                    slot_criteria=[
                        SlotCriteria(
                            comparator="is_empty",
                        )
                    ],
                )
            ],
            use_edge_pattern=True,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("OPTIONAL", sparql)
        self.assertIn("!BOUND", sparql)
        # Should check multiple value properties
        self.assertIn("hasTextSlotValue", sparql)
        self.assertIn("hasDoubleSlotValue", sparql)
        self.assertIn("hasIntegerSlotValue", sparql)
        self.assertIn("hasBooleanSlotValue", sparql)

    def test_is_empty_with_unknown_slot_type_defaults_to_text(self):
        """is_empty with slot_type but no slot_class_uri → single value property (text default)."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:AddressFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:ZipCodeSlot",
                            comparator="is_empty",
                        )
                    ],
                )
            ],
            use_edge_pattern=True,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("OPTIONAL", sparql)
        self.assertIn("!BOUND", sparql)
        self.assertIn("hasTextSlotValue", sparql)

    def test_is_empty_in_frame_query(self):
        """is_empty in build_frame_query_sparql path."""
        criteria = FrameQueryCriteria(
            slot_criteria=[
                SlotCriteria(
                    slot_type="urn:ZipCodeSlot",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                    comparator="is_empty",
                )
            ],
        )
        sparql = self.builder.build_frame_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("OPTIONAL", sparql)
        self.assertIn("!BOUND", sparql)
        self.assertIn("hasTextSlotValue", sparql)

    def test_is_empty_standalone_slot_criteria(self):
        """is_empty as standalone slot_criteria."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            slot_criteria=[
                SlotCriteria(
                    slot_type="urn:ZipCodeSlot",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot",
                    comparator="is_empty",
                )
            ],
            use_edge_pattern=True,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("OPTIONAL", sparql)
        self.assertIn("!BOUND", sparql)
        self.assertIn("hasIntegerSlotValue", sparql)


class TestDoubleNegationValidation(unittest.TestCase):
    """Test that double negation combinations are rejected."""

    def setUp(self):
        self.builder = KGQueryCriteriaBuilder()

    def test_not_exists_inside_negated_frame_rejected(self):
        """not_exists slot comparator inside negate=True frame → ValueError."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:AddressFrame",
                    negate=True,
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:ZipCodeSlot",
                            comparator="not_exists",
                        )
                    ],
                )
            ],
            use_edge_pattern=True,
        )
        with self.assertRaises(ValueError) as ctx:
            self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("double negation", str(ctx.exception).lower())

    def test_nested_negated_frame_inside_negated_frame_rejected(self):
        """negate=True child inside negate=True parent → ValueError."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:ParentFrame",
                    negate=True,
                    frame_criteria=[
                        FrameCriteria(
                            frame_type="urn:ChildFrame",
                            negate=True,
                        )
                    ],
                )
            ],
            use_edge_pattern=True,
        )
        with self.assertRaises(ValueError) as ctx:
            self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("double negation", str(ctx.exception).lower())

    def test_eq_inside_negated_frame_allowed(self):
        """eq comparator inside negate=True frame → should work (not double negation)."""
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:AddressFrame",
                    negate=True,
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:ZipCodeSlot",
                            value="10001",
                            comparator="eq",
                        )
                    ],
                )
            ],
            use_edge_pattern=True,
        )
        # Should not raise
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertIn("FILTER NOT EXISTS", sparql)
        self.assertIn('"10001"', sparql)


class TestExistingComparatorsUnchanged(unittest.TestCase):
    """Verify existing comparators still work after the changes."""

    def setUp(self):
        self.builder = KGQueryCriteriaBuilder()

    def test_eq_comparator(self):
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:AddressFrame",
                    slot_criteria=[
                        SlotCriteria(slot_type="urn:CitySlot", value="Boston", comparator="eq"),
                    ],
                )
            ],
            use_edge_pattern=True,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertNotIn("FILTER NOT EXISTS", sparql)
        self.assertIn('"Boston"', sparql)

    def test_exists_comparator(self):
        criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:AddressFrame",
                    slot_criteria=[
                        SlotCriteria(slot_type="urn:CitySlot", comparator="exists"),
                    ],
                )
            ],
            use_edge_pattern=True,
        )
        sparql = self.builder.build_entity_query_sparql(criteria, "urn:graph1", 10, 0)
        self.assertNotIn("FILTER NOT EXISTS", sparql)
        self.assertIn("?slot_pred_", sparql)


if __name__ == "__main__":
    unittest.main()
