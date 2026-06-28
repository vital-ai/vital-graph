"""Sample Query Criteria for Testing

Provides sample query criteria objects for testing the KG query builders.
"""

from vitalgraph.sparql.kg_query_builder import SlotCriteria, EntityQueryCriteria, FrameQueryCriteria


def create_simple_entity_criteria():
    """Create simple entity query criteria."""
    return EntityQueryCriteria(
        search_string="John",
        entity_type="http://example.org/PersonEntity"
    )


def create_complex_entity_criteria():
    """Create complex entity query criteria with slot filters."""
    slot_criteria = [
        SlotCriteria(
            slot_type="http://example.org/NameSlot",
            value="John Doe",
            comparator="eq"
        ),
        SlotCriteria(
            slot_type="http://example.org/AgeSlot",
            value="25",
            comparator="gt"
        )
    ]
    
    return EntityQueryCriteria(
        search_string="person",
        entity_type="http://example.org/PersonEntity",
        frame_type="http://example.org/PersonFrame",
        slot_criteria=slot_criteria
    )


def create_entity_criteria_with_exists_check():
    """Create entity criteria that checks for slot existence."""
    slot_criteria = [
        SlotCriteria(
            slot_type="http://example.org/EmailSlot",
            comparator="exists"
        )
    ]
    
    return EntityQueryCriteria(
        entity_type="http://example.org/PersonEntity",
        slot_criteria=slot_criteria
    )


def create_simple_frame_criteria():
    """Create simple frame query criteria."""
    return FrameQueryCriteria(
        search_string="Address",
        frame_type="http://example.org/AddressFrame"
    )


def create_complex_frame_criteria():
    """Create complex frame query criteria with slot filters."""
    slot_criteria = [
        SlotCriteria(
            slot_type="http://example.org/StreetSlot",
            value="Main",
            comparator="contains"
        ),
        SlotCriteria(
            slot_type="http://example.org/ZipSlot",
            value="90000",
            comparator="gte"
        )
    ]
    
    return FrameQueryCriteria(
        search_string="address",
        frame_type="http://example.org/AddressFrame",
        entity_type="http://example.org/PersonEntity",
        slot_criteria=slot_criteria
    )


def create_frame_criteria_with_multiple_comparators():
    """Create frame criteria with various comparator types."""
    slot_criteria = [
        SlotCriteria(
            slot_type="http://example.org/NameSlot",
            value="Test",
            comparator="ne"
        ),
        SlotCriteria(
            slot_type="http://example.org/ScoreSlot",
            value="50",
            comparator="lt"
        ),
        SlotCriteria(
            slot_type="http://example.org/RatingSlot",
            value="3",
            comparator="lte"
        )
    ]
    
    return FrameQueryCriteria(
        frame_type="http://example.org/TestFrame",
        slot_criteria=slot_criteria
    )


def create_empty_entity_criteria():
    """Create empty entity criteria (should match all entities)."""
    return EntityQueryCriteria()


def create_empty_frame_criteria():
    """Create empty frame criteria (should match all frames)."""
    return FrameQueryCriteria()


def create_slot_criteria_samples():
    """Create various slot criteria samples for testing."""
    return [
        # Equality check
        SlotCriteria(
            slot_type="http://example.org/NameSlot",
            value="John Doe",
            comparator="eq"
        ),
        
        # Not equal check
        SlotCriteria(
            slot_type="http://example.org/StatusSlot",
            value="inactive",
            comparator="ne"
        ),
        
        # Greater than check
        SlotCriteria(
            slot_type="http://example.org/AgeSlot",
            value="18",
            comparator="gt"
        ),
        
        # Less than check
        SlotCriteria(
            slot_type="http://example.org/ScoreSlot",
            value="100",
            comparator="lt"
        ),
        
        # Greater than or equal check
        SlotCriteria(
            slot_type="http://example.org/YearSlot",
            value="2020",
            comparator="gte"
        ),
        
        # Less than or equal check
        SlotCriteria(
            slot_type="http://example.org/PriceSlot",
            value="1000",
            comparator="lte"
        ),
        
        # Contains check
        SlotCriteria(
            slot_type="http://example.org/DescriptionSlot",
            value="important",
            comparator="contains"
        ),
        
        # Exists check
        SlotCriteria(
            slot_type="http://example.org/OptionalSlot",
            comparator="exists"
        )
    ]
