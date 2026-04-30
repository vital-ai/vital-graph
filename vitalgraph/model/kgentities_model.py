"""KG Entities Model Classes

Pydantic models for KG entity operations including entities, frames, and slots.
"""

from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, model_validator

from .quad_model import QuadResponse, QuadResultsResponse
from .api_model import BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse, BasePaginatedResponse


class EntityCreateResponse(BaseCreateResponse):
    """Response model for entity creation."""
    pass


class EntityUpdateResponse(BaseUpdateResponse):
    """Response model for entity updates."""
    pass


class EntityDeleteResponse(BaseDeleteResponse):
    """Response model for entity deletion."""
    pass


class EntityFramesResponse(QuadResponse):
    """Response model for entity frames with pagination support (paginated quad results)."""
    frame_uris: Optional[List[str]] = Field(None, description="List of frame URIs for simple responses")


class EntityFramesMultiResponse(BaseModel):
    """Response model for entity frames - multi URI case returns map of entity URI -> frame URI list."""
    entity_frame_map: Dict[str, List[str]]


# Enhanced Models for Graph Operations

class QueryFilter(BaseModel):
    """Simple property-based filter for entity queries."""
    property_name: str = Field(..., description="Property name to filter by")
    operator: str = Field(..., description="Filter operator: equals, not_equals, contains, exists, gt, lt, gte, lte")
    value: Optional[Any] = Field(None, description="Value to compare against (not needed for 'exists' operator)")


class SlotCriteria(BaseModel):
    """Criteria for slot filtering in KG queries."""
    slot_type: Optional[str] = Field(None, description="Slot type URI to filter by")
    slot_class_uri: Optional[str] = Field(None, description="Underlying slot class URI (e.g., KGTextSlot, KGDoubleSlot) to determine value property")
    value: Optional[Any] = Field(None, description="Value to compare against")
    comparator: Optional[str] = Field(None, description="Comparison operator: eq, ne, gt, lt, gte, lte, contains, exists, not_exists, is_empty")


class FrameCriteria(BaseModel):
    """Criteria for frame filtering in KG queries.
    
    Supports hierarchical frame structures:
    - frame_type filters the frame at this level
    - slot_criteria filters slots within this frame
    - frame_criteria allows recursive nesting for child frames (e.g., parent→child→grandchild)
    
    Example flat structure: entity→frame→slot
    Example hierarchical: entity→parent_frame→child_frame→slot
    """
    frame_type: Optional[str] = Field(None, description="Frame type URI to filter by")
    negate: bool = Field(False, description="When True, negate this frame criterion — match entities/frames that do NOT have this frame pattern")
    slot_criteria: Optional[List[SlotCriteria]] = Field(None, description="Slot criteria within this frame")
    frame_criteria: Optional[List['FrameCriteria']] = Field(None, description="Nested frame criteria for hierarchical frame structures (parent→child frames)")


# Property registry: maps property URI → datatype for filtering and sorting.
# Adding a property here makes it available for both sorting and filtering.
_FILTERABLE_ENTITY_PROPERTIES = {
    "http://vital.ai/ontology/vital-core#hasName":                        "string",
    "http://vital.ai/ontology/vital#hasObjectModificationDateTime":       "dateTime",
    "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime":          "dateTime",
    "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType":               "uri",
    "http://vital.ai/ontology/vital-aimp#hasObjectStatusType":            "uri",
}

# Allowed property URIs for entity_property sort type (derived from registry)
_ENTITY_SORT_PROPERTIES = set(_FILTERABLE_ENTITY_PROPERTIES.keys())

# Valid operators per datatype
_OPERATORS_BY_DATATYPE = {
    "string":   {"eq", "ne", "contains"},
    "dateTime": {"eq", "ne", "gt", "lt", "gte", "lte"},
    "uri":      {"eq", "ne", "in", "not_in"},
}


class EntityPropertyFilter(BaseModel):
    """Filter on a direct property of the entity node."""
    property_uri: str = Field(..., description="Full property URI")
    operator: str = Field(..., description="Filter operator: eq, ne, gt, lt, gte, lte, contains, in, not_in")
    value: Optional[Union[str, List[str]]] = Field(
        None,
        description="Single value for eq/ne/gt/lt/gte/lte/contains, or list of values for in/not_in"
    )

    @model_validator(mode='after')
    def validate_entity_property_filter(self) -> 'EntityPropertyFilter':
        if self.property_uri not in _FILTERABLE_ENTITY_PROPERTIES:
            raise ValueError(
                f"property_uri '{self.property_uri}' is not a filterable property. "
                f"Allowed: {', '.join(sorted(_FILTERABLE_ENTITY_PROPERTIES.keys()))}"
            )
        datatype = _FILTERABLE_ENTITY_PROPERTIES[self.property_uri]
        valid_ops = _OPERATORS_BY_DATATYPE[datatype]
        if self.operator not in valid_ops:
            raise ValueError(
                f"operator '{self.operator}' is not valid for datatype '{datatype}'. "
                f"Allowed: {', '.join(sorted(valid_ops))}"
            )
        if self.operator in ("in", "not_in"):
            if not isinstance(self.value, list):
                raise ValueError(
                    f"value must be a list when operator is '{self.operator}'"
                )
        return self

_VALID_SORT_TYPES = {
    "entity_frame_slot", "frame_slot",
    "source_frame_slot", "destination_frame_slot",
    "entity_property",
}


class SortCriteria(BaseModel):
    """Criteria for sorting in KG queries.
    
    sort_type values:
      - entity_frame_slot: Sort entities by a slot value (Case 2)
      - frame_slot: Sort frames by a slot value (Case 1)
      - source_frame_slot: Sort relations by source entity's slot value (Case 3)
      - destination_frame_slot: Sort relations by destination entity's slot value (Case 3)
      - entity_property: Sort by a direct property on the entity node (e.g. hasName)
    
    For slot-based sort types, slot_type and slot_class_uri are required.
    For entity_property, property_uri is required and must be one of the
    allowed sortable properties.
    """
    sort_type: str = Field(..., description="Sort type: entity_frame_slot, frame_slot, source_frame_slot, destination_frame_slot, or entity_property")
    frame_path: List[str] = Field(default_factory=list, description="Ordered frame type URIs from anchor to the slot's parent frame")
    slot_type: Optional[str] = Field(None, description="Slot type URI to sort by (required for slot-based sort types)")
    slot_class_uri: Optional[str] = Field(None, description="Slot class URI (e.g. KGTextSlot, KGDoubleSlot) — required for slot-based sort types")
    property_uri: Optional[str] = Field(None, description="Direct property URI — required when sort_type='entity_property'")
    sort_order: str = Field("asc", description="Sort order: asc or desc")
    priority: int = Field(1, description="Sort priority: 1=primary, 2=secondary, 3=tertiary, etc.")

    @model_validator(mode='after')
    def validate_sort_criteria(self) -> 'SortCriteria':
        if self.sort_type not in _VALID_SORT_TYPES:
            raise ValueError(
                f"Invalid sort_type '{self.sort_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_SORT_TYPES))}"
            )
        if self.sort_type == "entity_property":
            if not self.property_uri:
                raise ValueError(
                    "property_uri is required when sort_type='entity_property'"
                )
            if self.property_uri not in _ENTITY_SORT_PROPERTIES:
                raise ValueError(
                    f"property_uri '{self.property_uri}' is not a sortable property. "
                    f"Allowed: {', '.join(sorted(_ENTITY_SORT_PROPERTIES))}"
                )
        else:
            if not self.slot_type:
                raise ValueError(
                    f"slot_type is required when sort_type='{self.sort_type}'"
                )
            if not self.slot_class_uri:
                raise ValueError(
                    f"slot_class_uri is required when sort_type='{self.sort_type}'"
                )
        return self


class EntityQueryCriteria(BaseModel):
    """Criteria for entity queries."""
    search_string: Optional[str] = Field(None, description="Search string for entity name/label")
    entity_type: Optional[str] = Field(None, description="Entity type URI to filter by")
    frame_type: Optional[str] = Field(None, description="Frame type URI - entities must have frame of this type")
    slot_criteria: Optional[List[SlotCriteria]] = Field(None, description="Slot-based filtering criteria")
    sort_criteria: Optional[List[SortCriteria]] = Field(None, description="Multi-level sorting criteria")
    filters: Optional[List[QueryFilter]] = Field(None, description="Property-based filters")
    entity_property_filters: Optional[List[EntityPropertyFilter]] = Field(None, description="Direct entity property filters (datatype-aware)")


class EntityQueryRequest(BaseModel):
    """Request model for entity queries."""
    criteria: EntityQueryCriteria = Field(..., description="Query criteria")
    page_size: int = Field(10, description="Number of results per page", ge=1, le=100)
    offset: int = Field(0, description="Offset for pagination", ge=0)


class EntityQueryResponse(BasePaginatedResponse):
    """Response model for entity queries."""
    entity_uris: List[str] = Field(..., description="List of matching entity subject URIs")


class EntityGraphResponse(QuadResultsResponse):
    """Response model for entity with optional complete graph (non-paginated quad results)."""
    complete_graph: Optional[QuadResultsResponse] = Field(None, description="Complete entity graph when include_entity_graph=True")


class EntityGraphDeleteResponse(BaseDeleteResponse):
    """Response model for entity graph deletion."""
    deleted_graph_components: Optional[Dict[str, int]] = Field(None, description="Count of deleted components by type")


# Enhanced Response Models

class EntitiesGraphResponse(QuadResponse):
    """Enhanced response model for entities with optional graph data (paginated quad results)."""
    complete_graphs: Optional[Dict[str, QuadResultsResponse]] = Field(None, description="Complete graphs by entity URI when include_entity_graph=True")


# Update forward references for recursive models
FrameCriteria.model_rebuild()