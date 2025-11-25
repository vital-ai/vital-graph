"""Sample Frame Graph Data for Testing

Provides sample JSON-LD documents containing frames and slots
for testing frame-centric graph validation and separation functionality.
"""

from typing import Dict, Any


def create_single_frame_graph() -> Dict[str, Any]:
    """Create a simple frame graph with one frame and multiple slots."""
    return {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital-core": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
            {
                "@id": "http://example.org/frame1",
                "@type": "haley:KGFrame",
                "vital-core:name": "Test Frame 1",
                "vital-core:vitaltype": "http://example.org/PersonFrame",
                "haley:hasFrameGraphURI": "http://example.org/frame1/frame-graph"
            },
            {
                "@id": "http://example.org/slot1",
                "@type": "haley:KGSlot",
                "vital-core:name": "Name Slot",
                "vital-core:vitaltype": "http://example.org/NameSlot",
                "vital-core:value": "John Doe"
            },
            {
                "@id": "http://example.org/slot2",
                "@type": "haley:KGSlot",
                "vital-core:name": "Age Slot",
                "vital-core:vitaltype": "http://example.org/AgeSlot",
                "vital-core:value": "25"
            },
            # Relationships
            {
                "@id": "http://example.org/slot1",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/frame1"}
            },
            {
                "@id": "http://example.org/slot2",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/frame1"}
            }
        ]
    }


def create_multiple_frame_graphs() -> Dict[str, Any]:
    """Create JSON-LD with multiple separate frame graphs."""
    return {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital-core": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
            # Frame 1 graph
            {
                "@id": "http://example.org/frame1",
                "@type": "haley:KGFrame",
                "vital-core:name": "Person Frame",
                "vital-core:vitaltype": "http://example.org/PersonFrame",
                "haley:hasFrameGraphURI": "http://example.org/frame1/frame-graph"
            },
            {
                "@id": "http://example.org/slot1",
                "@type": "haley:KGSlot",
                "vital-core:name": "Name Slot",
                "vital-core:value": "Alice"
            },
            
            # Frame 2 graph
            {
                "@id": "http://example.org/frame2",
                "@type": "haley:KGFrame",
                "vital-core:name": "Address Frame",
                "vital-core:vitaltype": "http://example.org/AddressFrame",
                "haley:hasFrameGraphURI": "http://example.org/frame2/frame-graph"
            },
            {
                "@id": "http://example.org/slot2",
                "@type": "haley:KGSlot",
                "vital-core:name": "Street Slot",
                "vital-core:value": "123 Main St"
            },
            
            # Relationships for Frame 1
            {
                "@id": "http://example.org/slot1",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/frame1"}
            },
            
            # Relationships for Frame 2
            {
                "@id": "http://example.org/slot2",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/frame2"}
            }
        ]
    }


def create_frame_hierarchy_graph() -> Dict[str, Any]:
    """Create frame graph with parent-child frame relationships."""
    return {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital-core": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
            # Parent frame
            {
                "@id": "http://example.org/parent-frame",
                "@type": "haley:KGFrame",
                "vital-core:name": "Parent Frame",
                "vital-core:vitaltype": "http://example.org/PersonFrame",
                "haley:hasFrameGraphURI": "http://example.org/parent-frame/frame-graph"
            },
            
            # Child frames
            {
                "@id": "http://example.org/child-frame1",
                "@type": "haley:KGFrame",
                "vital-core:name": "Address Child Frame",
                "vital-core:vitaltype": "http://example.org/AddressFrame",
                "haley:hasFrameGraphURI": "http://example.org/child-frame1/frame-graph"
            },
            {
                "@id": "http://example.org/child-frame2",
                "@type": "haley:KGFrame",
                "vital-core:name": "Contact Child Frame",
                "vital-core:vitaltype": "http://example.org/ContactFrame",
                "haley:hasFrameGraphURI": "http://example.org/child-frame2/frame-graph"
            },
            
            # Slots for parent frame
            {
                "@id": "http://example.org/name-slot",
                "@type": "haley:KGSlot",
                "vital-core:name": "Name Slot",
                "vital-core:value": "Jane Smith"
            },
            
            # Slots for child frame 1
            {
                "@id": "http://example.org/street-slot",
                "@type": "haley:KGSlot",
                "vital-core:name": "Street Slot",
                "vital-core:value": "456 Oak Ave"
            },
            {
                "@id": "http://example.org/city-slot",
                "@type": "haley:KGSlot",
                "vital-core:name": "City Slot",
                "vital-core:value": "Springfield"
            },
            
            # Slots for child frame 2
            {
                "@id": "http://example.org/email-slot",
                "@type": "haley:KGSlot",
                "vital-core:name": "Email Slot",
                "vital-core:value": "jane@example.com"
            },
            
            # Frame hierarchy relationships
            {
                "@id": "http://example.org/parent-frame",
                "haley:hasChildFrame": [
                    {"@id": "http://example.org/child-frame1"},
                    {"@id": "http://example.org/child-frame2"}
                ]
            },
            
            # Slot relationships
            {
                "@id": "http://example.org/name-slot",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/parent-frame"}
            },
            {
                "@id": "http://example.org/street-slot",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/child-frame1"}
            },
            {
                "@id": "http://example.org/city-slot",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/child-frame1"}
            },
            {
                "@id": "http://example.org/email-slot",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/child-frame2"}
            }
        ]
    }


def create_frame_graph_with_orphaned_slots() -> Dict[str, Any]:
    """Create frame graph with orphaned slots that don't belong to any frame."""
    return {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital-core": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
            # Valid frame
            {
                "@id": "http://example.org/frame1",
                "@type": "haley:KGFrame",
                "vital-core:name": "Valid Frame",
                "haley:hasFrameGraphURI": "http://example.org/frame1/frame-graph"
            },
            
            # Valid slot
            {
                "@id": "http://example.org/slot1",
                "@type": "haley:KGSlot",
                "vital-core:name": "Valid Slot",
                "vital-core:value": "Valid Value"
            },
            
            # Orphaned slots (not connected to any frame)
            {
                "@id": "http://example.org/orphaned-slot1",
                "@type": "haley:KGSlot",
                "vital-core:name": "Orphaned Slot 1",
                "vital-core:value": "Orphaned Value 1"
            },
            {
                "@id": "http://example.org/orphaned-slot2",
                "@type": "haley:KGSlot",
                "vital-core:name": "Orphaned Slot 2",
                "vital-core:value": "Orphaned Value 2"
            },
            
            # Valid relationship
            {
                "@id": "http://example.org/slot1",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/frame1"}
            }
            
            # Note: orphaned slots have no kGFrameSlotFrame relationships
        ]
    }


def create_mixed_top_level_and_child_frames() -> Dict[str, Any]:
    """Create document with both top-level frames and child frames."""
    return {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital-core": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
            # Top-level frame 1
            {
                "@id": "http://example.org/top-frame1",
                "@type": "haley:KGFrame",
                "vital-core:name": "Top Level Frame 1",
                "haley:hasFrameGraphURI": "http://example.org/top-frame1/frame-graph"
            },
            
            # Top-level frame 2
            {
                "@id": "http://example.org/top-frame2",
                "@type": "haley:KGFrame",
                "vital-core:name": "Top Level Frame 2",
                "haley:hasFrameGraphURI": "http://example.org/top-frame2/frame-graph"
            },
            
            # Child frame (belongs to top-frame1)
            {
                "@id": "http://example.org/child-frame",
                "@type": "haley:KGFrame",
                "vital-core:name": "Child Frame",
                "haley:hasFrameGraphURI": "http://example.org/child-frame/frame-graph"
            },
            
            # Slots
            {
                "@id": "http://example.org/slot1",
                "@type": "haley:KGSlot",
                "vital-core:name": "Slot for Top Frame 1",
                "vital-core:value": "Value 1"
            },
            {
                "@id": "http://example.org/slot2",
                "@type": "haley:KGSlot",
                "vital-core:name": "Slot for Top Frame 2",
                "vital-core:value": "Value 2"
            },
            {
                "@id": "http://example.org/slot3",
                "@type": "haley:KGSlot",
                "vital-core:name": "Slot for Child Frame",
                "vital-core:value": "Value 3"
            },
            
            # Relationships
            {
                "@id": "http://example.org/top-frame1",
                "haley:hasChildFrame": {"@id": "http://example.org/child-frame"}
            },
            {
                "@id": "http://example.org/slot1",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/top-frame1"}
            },
            {
                "@id": "http://example.org/slot2",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/top-frame2"}
            },
            {
                "@id": "http://example.org/slot3",
                "haley:kGFrameSlotFrame": {"@id": "http://example.org/child-frame"}
            }
        ]
    }


def create_frame_only_document() -> Dict[str, Any]:
    """Create document with only frames (no slots)."""
    return {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital-core": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": [
            {
                "@id": "http://example.org/frame1",
                "@type": "haley:KGFrame",
                "vital-core:name": "Standalone Frame 1",
                "haley:hasFrameGraphURI": "http://example.org/frame1/frame-graph"
            },
            {
                "@id": "http://example.org/frame2",
                "@type": "haley:KGFrame",
                "vital-core:name": "Standalone Frame 2",
                "haley:hasFrameGraphURI": "http://example.org/frame2/frame-graph"
            }
        ]
    }
