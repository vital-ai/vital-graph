"""KG Entities Model Classes

Pydantic models for KG entity operations including entities, frames, and slots.
"""

from typing import Dict, List, Literal, Optional, Any, Union
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
    comparator: Optional[str] = Field(None, description="Comparison operator: eq, ne, gt, lt, gte, lte, contains, exists, not_exists, is_empty, has, has_any, has_all, not_has, not_has_any")


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
    "http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList":           "uri_list",
    "http://vital.ai/ontology/haley-ai-kg#hasKGProvenanceType":            "uri",
}

# Allowed property URIs for entity_property sort type (derived from registry)
_ENTITY_SORT_PROPERTIES = set(_FILTERABLE_ENTITY_PROPERTIES.keys())

# Valid operators per datatype
_OPERATORS_BY_DATATYPE = {
    "string":   {"eq", "ne", "contains"},
    "dateTime": {"eq", "ne", "gt", "lt", "gte", "lte"},
    "uri":      {"eq", "ne", "in", "not_in"},
    "uri_list": {"has", "has_any", "has_all", "not_has", "not_has_any", "exists", "not_exists"},
}


class EntityPropertyFilter(BaseModel):
    """Filter on a direct property of the entity node."""
    property_uri: str = Field(..., description="Full property URI")
    operator: str = Field(..., description="Filter operator: eq, ne, gt, lt, gte, lte, contains, in, not_in, has, has_any, has_all, not_has, not_has_any, exists, not_exists")
    value: Optional[Union[str, List[str]]] = Field(
        None,
        description="Single value for eq/ne/gt/lt/gte/lte/contains/has/not_has, list for in/not_in/has_any/has_all/not_has_any, none for exists/not_exists"
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
        if self.operator in ("in", "not_in", "has_any", "has_all", "not_has_any"):
            if not isinstance(self.value, list):
                raise ValueError(
                    f"value must be a list when operator is '{self.operator}'"
                )
        if self.operator in ("has", "not_has"):
            if isinstance(self.value, list):
                raise ValueError(
                    f"value must be a single string when operator is '{self.operator}'"
                )
            if self.value is None:
                raise ValueError(
                    f"value is required when operator is '{self.operator}'"
                )
        if self.operator in ("exists", "not_exists"):
            pass  # value is ignored
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


class VectorSearchCriteria(BaseModel):
    """Criteria for vector similarity search.

    Generates vg:vectorSimilarity or vg:vectorNearby SPARQL BIND.
    Results are ordered by similarity score (DESC) and limited to top_k.
    """
    search_text: Optional[str] = Field(None, description="Text to vectorize server-side for similarity search")
    vector: Optional[str] = Field(None, description="Pre-computed vector literal, e.g. '[0.1,0.2,...]'")
    index_name: str = Field("entity_default", description="Vector index name")
    top_k: int = Field(10, description="Maximum results (becomes LIMIT)", ge=1, le=1000)
    min_score: Optional[float] = Field(None, description="Minimum similarity score threshold (0.0–1.0)", ge=0.0, le=1.0)

    @model_validator(mode='after')
    def validate_vector_criteria(self) -> 'VectorSearchCriteria':
        if not self.search_text and not self.vector:
            raise ValueError("Either search_text or vector must be provided")
        if self.search_text and self.vector:
            raise ValueError("Only one of search_text or vector may be provided")
        return self


class WeightedVectorInput(BaseModel):
    """A single weighted vector input for multi-vector search."""
    search_text: Optional[str] = Field(None, description="Text to vectorize server-side")
    vector: Optional[str] = Field(None, description="Pre-computed vector literal '[0.1,0.2,...]'")
    index_name: str = Field(..., description="Vector index name")
    weight: float = Field(1.0, description="Relative weight for this vector (auto-normalized)", gt=0)

    @model_validator(mode='after')
    def validate_input(self) -> 'WeightedVectorInput':
        if not self.search_text and not self.vector:
            raise ValueError("Either search_text or vector must be provided")
        if self.search_text and self.vector:
            raise ValueError("Only one of search_text or vector may be provided")
        return self


class MultiVectorSearchCriteria(BaseModel):
    """Criteria for multi-vector similarity search.

    Generates vg:multiVectorSimilarity or vg:multiVectorNearby SPARQL BIND.
    Combines scores from multiple vector indexes with weighted fusion.
    """
    vectors: List[WeightedVectorInput] = Field(..., description="List of weighted vector inputs (min 2)", min_length=2)
    top_k: int = Field(10, description="Maximum results (becomes LIMIT)", ge=1, le=1000)
    min_score: Optional[float] = Field(None, description="Minimum combined score threshold (0.0-1.0)", ge=0.0, le=1.0)
    fusion_strategy: str = Field("weighted_sum", description="Fusion strategy: weighted_sum, relative_score, or ranked")
    oversample_factor: int = Field(5, description="Oversample factor per vector (candidates = top_k * factor)", ge=1, le=50)


class GeoSearchCriteria(BaseModel):
    """Criteria for geographic proximity search.

    Generates vg:geoDistance BIND and optional vg:withinRadius FILTER.
    """
    latitude: float = Field(..., description="Latitude of search center", ge=-90.0, le=90.0)
    longitude: float = Field(..., description="Longitude of search center", ge=-180.0, le=180.0)
    radius_m: Optional[float] = Field(None, description="Filter to within radius (meters)", gt=0)
    sort_by_distance: bool = Field(False, description="Sort results by distance ascending")
    top_k: Optional[int] = Field(None, description="Limit results for nearest-N queries", ge=1, le=1000)
    geo_target: Optional[str] = Field(
        None,
        description=(
            "Which SPARQL variable the geo function binds to. "
            "'slot' = bind to the geo slot variable from frame_criteria; "
            "'entity' = bind to ?entity (default, backward-compatible). "
            "If None, defaults to 'entity'."
        ),
    )


class EntityQueryCriteria(BaseModel):
    """Criteria for entity queries."""
    search_string: Optional[str] = Field(None, description="Search string for entity name/label")
    entity_type: Optional[str] = Field(None, description="Entity type URI to filter by")
    frame_type: Optional[str] = Field(None, description="Frame type URI - entities must have frame of this type")
    slot_criteria: Optional[List[SlotCriteria]] = Field(None, description="Slot-based filtering criteria")
    sort_criteria: Optional[List[SortCriteria]] = Field(None, description="Multi-level sorting criteria")
    filters: Optional[List[QueryFilter]] = Field(None, description="Property-based filters")
    entity_property_filters: Optional[List[EntityPropertyFilter]] = Field(None, description="Direct entity property filters (datatype-aware)")
    vector_criteria: Optional[VectorSearchCriteria] = Field(None, description="Vector similarity search criteria")
    multi_vector_criteria: Optional[MultiVectorSearchCriteria] = Field(None, description="Multi-vector weighted fusion search criteria")
    geo_criteria: Optional[GeoSearchCriteria] = Field(None, description="Geographic proximity search criteria")


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


class DocumentSearchCriteria(BaseModel):
    """Criteria for document queries — document-specific fields that map to
    SPARQL triple patterns in _build_document_where_clause.

    Sits alongside VectorSearchCriteria/GeoSearchCriteria on KGQueryCriteria.
    vector_criteria, multi_vector_criteria, geo_criteria, sort_criteria,
    entity_property_filters, and frame_criteria remain on KGQueryCriteria
    (shared with entity queries).
    """

    # ── Document type filtering ──
    document_type_uri: Optional[str] = Field(
        None,
        description="Filter by hasKGDocumentType URI (e.g. urn:kgdoctype:technical_article). "
                    "Generates: ?entity haley:hasKGDocumentType <uri> ."
    )

    # ── Segment scoping ──
    search_scope: Optional[Literal["all", "segments", "originals", "summaries"]] = Field(
        None,
        description="Controls which tier of documents to search. "
                    "'segments' → segmentIndex > 0 (chunk-level results). "
                    "'summaries' → segmentTypeURI = segmentation_parent (parent copies with summary text). "
                    "'originals' → no segmentTypeURI at all (unprocessed docs). "
                    "'all' / None → no scope filter."
    )

    # ── Segmentation method/type filtering ──
    segment_method_uri: Optional[str] = Field(
        None,
        description="Filter by segmentation method URI (e.g. urn:segmethod:markdown_heading_split). "
                    "Generates: ?entity haley:hasKGDocumentSegmentMethodURI <uri> ."
    )
    segment_type_uri: Optional[str] = Field(
        None,
        description="Filter by segment type URI (e.g. urn:segtype:markdown_section). "
                    "Generates: ?entity haley:hasKGDocumentSegmentTypeURI <uri> ."
    )

    # ── Parent scoping ──
    parent_document_uri: Optional[str] = Field(
        None,
        description="Filter to segments of a specific parent document (via Edge_hasKGDocumentSegment). "
                    "Generates: ?_seg_edge vital-core:hasEdgeSource <uri> . "
                    "?_seg_edge vital-core:hasEdgeDestination ?entity ."
    )

    # ── Content type filtering ──
    content_type: Optional[str] = Field(
        None,
        description="Filter by hasKGContentType (MIME type). "
                    "Generates: ?entity haley:hasKGContentType \"mime_type\" ."
    )

    # ── Token length range ──
    min_token_length: Optional[int] = Field(
        None, ge=0,
        description="Minimum segment token length. "
                    "Generates: ?entity haley:hasKGDocumentSegmentTokenLength ?_tlen . FILTER(?_tlen >= N)"
    )
    max_token_length: Optional[int] = Field(
        None, ge=1,
        description="Maximum segment token length. "
                    "Generates: FILTER(?_tlen <= N)  (reuses ?_tlen from min_token_length or adds binding)"
    )

    # ── Text search ──
    search_text: Optional[str] = Field(
        None,
        description="Full-text search on headline/content. "
                    "When fts_index_name is set, uses GIN-indexed BM25 search via vg:textSearch. "
                    "Otherwise falls back to CONTAINS(LCASE(...)) brute-force scan."
    )
    fts_index_name: Optional[str] = Field(
        None,
        description="Name of the FTS index to use for search_text. "
                    "When set, generates BIND(vg:textSearch(?entity, 'text', 'index') AS ?_fts_score) "
                    "FILTER(?_fts_score > 0). When None, falls back to CONTAINS string matching."
    )

    # ── Segmentation-aware response enrichment ──
    include_parent_context: bool = Field(
        False,
        description="When True (and searching segments), follow Edge_hasKGDocumentSegment "
                    "backwards to include the parent document URI and headline in the response. "
                    "Generates an additional OPTIONAL block in the SPARQL query."
    )
    include_original_uri: bool = Field(
        False,
        description="When True (and include_parent_context=True), also follow the "
                    "parent→original edge to return the original document URI. "
                    "Generates a second OPTIONAL hop."
    )
    exclude_managed_segments: bool = Field(
        True,
        description="When True (default), exclude managed segment types from results "
                    "(segmentation_parent, markdown_section, text_chunk) — same as "
                    "GET /api/kgdocuments default behavior. Set False to include all."
    )

    # ── Inline content projection ──
    include_segment_text: bool = Field(
        False,
        description="When True, project segment text directly in the SPARQL query "
                    "(hasKGDocumentContent, hasKGDocumentHeadline) so the response "
                    "contains chunk content without a second fetch. Populates "
                    "DocumentResult.segment_text and .segment_headline."
    )

    # ── Grouping ──
    group_by_document: bool = Field(
        False,
        description="When True, collapse segment results by parent document. "
                    "Returns one DocumentResult per parent, keeping the segment with "
                    "the highest vector score. Requires include_parent_context=True. "
                    "Generates SPARQL GROUP BY ?_parent_doc with MAX(?vg_score) "
                    "and SAMPLE(?entity) aggregation. "
                    "Note: when combined with include_segment_text, the text returned "
                    "is from the SAMPLE'd segment (not guaranteed to be the best-scoring one)."
    )

    # ── Validators ──
    @model_validator(mode='after')
    def _validate_dependencies(self) -> 'DocumentSearchCriteria':
        if self.include_original_uri and not self.include_parent_context:
            raise ValueError(
                "include_original_uri requires include_parent_context=True "
                "(original is resolved via parent → original edge traversal)")
        if self.group_by_document and not self.include_parent_context:
            raise ValueError(
                "group_by_document requires include_parent_context=True "
                "(grouping key is ?_parent_doc from parent context OPTIONAL)")
        return self


# Update forward references for recursive models
FrameCriteria.model_rebuild()