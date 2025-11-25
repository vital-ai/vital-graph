"""Sample Entity Graph Data for Testing

Provides sample JSON-LD documents containing entities, frames, and slots
for testing graph validation and separation functionality.
"""

from typing import Dict, Any


def create_single_entity_graph() -> Dict[str, Any]:
    """Create a simple entity graph with one entity, one frame, and one slot."""
    return {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital-core": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
            {
                "@id": "http://example.org/entity1",
                "@type": "haley:KGEntity",
                "vital-core:name": "Test Entity 1",
                "haley:hasKGGraphURI": "http://example.org/entity1/kg-graph"
            },
            {
                "@id": "http://example.org/frame1",
                "@type": "haley:KGFrame",
                "vital-core:name": "Test Frame 1",
                "haley:hasFrameGraphURI": "http://example.org/frame1/frame-graph"
            },
            {
                "@id": "http://example.org/slot1",
                "@type": "haley:KGSlot",
                "vital-core:name": "Test Slot 1",
                "vital-core:value": "Test Value"
            },
            # Relationships
            {
                "@id": "http://example.org/entity1",
                "haley:hasFrame": {"@id": "http://example.org/frame1"}
            },
            {
                "@id": "http://example.org/slot1",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/frame1"}
            }
        ]
    }


def create_multiple_entity_graphs() -> Dict[str, Any]:
    """Create JSON-LD with multiple separate entity graphs."""
    return {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital-core": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
            # Entity 1 graph
            {
                "@id": "http://example.org/entity1",
                "@type": "haley:KGEntity",
                "vital-core:name": "Entity 1",
                "haley:hasKGGraphURI": "http://example.org/entity1/kg-graph"
            },
            {
                "@id": "http://example.org/frame1",
                "@type": "haley:KGFrame",
                "vital-core:name": "Frame 1",
                "haley:hasFrameGraphURI": "http://example.org/frame1/frame-graph"
            },
            {
                "@id": "http://example.org/slot1",
                "@type": "haley:KGSlot",
                "vital-core:name": "Slot 1",
                "vital-core:value": "Value 1"
            },
            
            # Entity 2 graph
            {
                "@id": "http://example.org/entity2",
                "@type": "haley:KGEntity",
                "vital-core:name": "Entity 2",
                "haley:hasKGGraphURI": "http://example.org/entity2/kg-graph"
            },
            {
                "@id": "http://example.org/frame2",
                "@type": "haley:KGFrame",
                "vital-core:name": "Frame 2",
                "haley:hasFrameGraphURI": "http://example.org/frame2/frame-graph"
            },
            {
                "@id": "http://example.org/slot2",
                "@type": "haley:KGSlot",
                "vital-core:name": "Slot 2",
                "vital-core:value": "Value 2"
            },
            
            # Relationships for Entity 1
            {
                "@id": "http://example.org/entity1",
                "haley:hasFrame": {"@id": "http://example.org/frame1"}
            },
            {
                "@id": "http://example.org/slot1",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/frame1"}
            },
            
            # Relationships for Entity 2
            {
                "@id": "http://example.org/entity2",
                "haley:hasFrame": {"@id": "http://example.org/frame2"}
            },
            {
                "@id": "http://example.org/slot2",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/frame2"}
            }
        ]
    }


def create_complex_entity_graph() -> Dict[str, Any]:
    """Create a complex entity graph with multiple frames, slots, and child frames."""
    return {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital-core": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
            # Main entity
            {
                "@id": "http://example.org/complex-entity",
                "@type": "haley:KGEntity",
                "vital-core:name": "Complex Entity",
                "vital-core:vitaltype": "http://example.org/PersonEntity",
                "haley:hasKGGraphURI": "http://example.org/complex-entity/kg-graph"
            },
            
            # Parent frame
            {
                "@id": "http://example.org/parent-frame",
                "@type": "haley:KGFrame",
                "vital-core:name": "Parent Frame",
                "vital-core:vitaltype": "http://example.org/PersonFrame",
                "haley:hasFrameGraphURI": "http://example.org/parent-frame/frame-graph"
            },
            
            # Child frame
            {
                "@id": "http://example.org/child-frame",
                "@type": "haley:KGFrame",
                "vital-core:name": "Child Frame",
                "vital-core:vitaltype": "http://example.org/AddressFrame",
                "haley:hasFrameGraphURI": "http://example.org/child-frame/frame-graph"
            },
            
            # Slots for parent frame
            {
                "@id": "http://example.org/name-slot",
                "@type": "haley:KGSlot",
                "vital-core:name": "Name Slot",
                "vital-core:vitaltype": "http://example.org/NameSlot",
                "vital-core:value": "John Doe"
            },
            {
                "@id": "http://example.org/age-slot",
                "@type": "haley:KGSlot",
                "vital-core:name": "Age Slot",
                "vital-core:vitaltype": "http://example.org/AgeSlot",
                "vital-core:value": "30"
            },
            
            # Slots for child frame
            {
                "@id": "http://example.org/street-slot",
                "@type": "haley:KGSlot",
                "vital-core:name": "Street Slot",
                "vital-core:vitaltype": "http://example.org/StreetSlot",
                "vital-core:value": "123 Main St"
            },
            
            # Relationships
            {
                "@id": "http://example.org/complex-entity",
                "haley:hasFrame": {"@id": "http://example.org/parent-frame"}
            },
            {
                "@id": "http://example.org/parent-frame",
                "haley:hasChildFrame": {"@id": "http://example.org/child-frame"}
            },
            {
                "@id": "http://example.org/name-slot",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/parent-frame"}
            },
            {
                "@id": "http://example.org/age-slot",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/parent-frame"}
            },
            {
                "@id": "http://example.org/street-slot",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/child-frame"}
            }
        ]
    }


def create_entity_graph_with_orphaned_triples() -> Dict[str, Any]:
    """Create entity graph with orphaned triples that don't belong to any entity."""
    return {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital-core": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
            # Valid entity graph
            {
                "@id": "http://example.org/entity1",
                "@type": "haley:KGEntity",
                "vital-core:name": "Valid Entity",
                "haley:hasKGGraphURI": "http://example.org/entity1/kg-graph"
            },
            {
                "@id": "http://example.org/frame1",
                "@type": "haley:KGFrame",
                "vital-core:name": "Valid Frame"
            },
            {
                "@id": "http://example.org/slot1",
                "@type": "haley:KGSlot",
                "vital-core:name": "Valid Slot",
                "vital-core:value": "Valid Value"
            },
            
            # Orphaned objects (not connected to any entity)
            {
                "@id": "http://example.org/orphaned-frame",
                "@type": "haley:KGFrame",
                "vital-core:name": "Orphaned Frame"
            },
            {
                "@id": "http://example.org/orphaned-slot",
                "@type": "haley:KGSlot",
                "vital-core:name": "Orphaned Slot",
                "vital-core:value": "Orphaned Value"
            },
            
            # Valid relationships
            {
                "@id": "http://example.org/entity1",
                "haley:hasFrame": {"@id": "http://example.org/frame1"}
            },
            {
                "@id": "http://example.org/slot1",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/frame1"}
            }
            
            # Note: orphaned-frame and orphaned-slot have no relationships to entity1
        ]
    }


def create_empty_document() -> Dict[str, Any]:
    """Create an empty JSON-LD document."""
    return {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital-core": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": []
    }


def create_entity_only_document() -> Dict[str, Any]:
    """Create document with only entities (no frames or slots)."""
    return {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital-core": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
            {
                "@id": "http://example.org/entity1",
                "@type": "haley:KGEntity",
                "vital-core:name": "Standalone Entity 1",
                "haley:hasKGGraphURI": "http://example.org/entity1/kg-graph"
            },
            {
                "@id": "http://example.org/entity2",
                "@type": "haley:KGEntity",
                "vital-core:name": "Standalone Entity 2",
                "haley:hasKGGraphURI": "http://example.org/entity2/kg-graph"
            }
        ]
    }
