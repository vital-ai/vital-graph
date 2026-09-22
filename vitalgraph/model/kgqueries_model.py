"""KG Queries Model Classes

Pydantic models for KG entity-to-entity query operations.
Single endpoint with query criteria that specifies relation, frame, or entity query type.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, field_validator, model_validator

from .kgentities_model import EntityQueryCriteria, EntityPropertyFilter, FrameCriteria, SlotCriteria, SortCriteria, VectorSearchCriteria, MultiVectorSearchCriteria, GeoSearchCriteria, DocumentSearchCriteria
from .api_model import BasePaginatedResponse
from .result_status import ResultStatus, OperationStatus


class FTSTarget(BaseModel):
    """One slot/frame population searched by an FTS criterion."""

    slot_type: str = Field(..., min_length=1, description="Slot type URI indexed for full-text matching")
    frame_type: Optional[str] = Field(None, min_length=1, description="Containing frame type URI")
    kind: Optional[str] = Field(None, min_length=1, description="Caller-defined population label returned with matches")

    @field_validator('slot_type', 'frame_type')
    @classmethod
    def validate_uri(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
        if not validate_rfc3986(value, rule='URI'):
            raise ValueError(f"invalid RFC3986 URI: {value}")
        return value


class FTSCriteria(BaseModel):
    """Unscored boolean full-text criterion composed with a KG query."""

    text: str = Field(..., min_length=1, description="Text parsed with websearch_to_tsquery")
    index_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Explicit FTS index name",
    )
    targets: List[FTSTarget] = Field(..., min_length=1, max_length=20)
    include_match_text: bool = Field(default=True, description="Include each matching slot's text in FTS metadata")

    @model_validator(mode='after')
    def validate_targets(self) -> 'FTSCriteria':
        for index, target in enumerate(self.targets):
            for other in self.targets[:index]:
                overlaps = (
                    target.slot_type == other.slot_type
                    and (
                        target.frame_type == other.frame_type
                        or target.frame_type is None
                        or other.frame_type is None
                    )
                )
                if overlaps:
                    raise ValueError("fts slot/frame targets must not overlap")
        if len(self.targets) > 1:
            kinds = [target.kind for target in self.targets]
            if any(kind is None for kind in kinds):
                raise ValueError("kind is required when multiple fts targets are used")
            if len(kinds) != len(set(kinds)):
                raise ValueError("fts target kinds must be unique")
        if not self.text.strip():
            raise ValueError("fts text cannot be blank")
        return self


class KGQueryCriteria(BaseModel):
    """Criteria for KG entity-to-entity queries."""
    
    # Query type specification
    query_type: str = Field(..., description="Query type: 'relation', 'frame', 'entity', 'frame_query', or 'document'")
    
    # Document-specific criteria (only used when query_type="document")
    document_criteria: Optional[DocumentSearchCriteria] = Field(default=None, description="Document-specific criteria for query_type='document'")
    
    # Query mode specification (for frame queries)
    query_mode: str = Field(default="edge", description="Query mode: 'edge' (use Edge_hasEntityKGFrame) or 'direct' (use vg-direct:hasEntityFrame)")
    
    # Source entity specification
    source_entity_criteria: Optional[EntityQueryCriteria] = Field(default=None, description="Criteria for source entities")
    source_entity_uris: Optional[List[str]] = Field(default=None, description="Specific source entity URIs")
    
    # Destination entity specification  
    destination_entity_criteria: Optional[EntityQueryCriteria] = Field(default=None, description="Criteria for destination entities")
    destination_entity_uris: Optional[List[str]] = Field(default=None, description="Specific destination entity URIs")
    
    # Relation-specific criteria (only used when query_type="relation")
    relation_type_uris: Optional[List[str]] = Field(default=None, description="Relation type URNs to match")
    direction: str = Field(default="outgoing", description="Direction: outgoing, incoming, bidirectional")
    
    # Frame/slot filtering for relation participants (only used when query_type="relation")
    source_frame_criteria: Optional[List[FrameCriteria]] = Field(default=None, description="Frame/slot criteria for source entities in relation queries")
    destination_frame_criteria: Optional[List[FrameCriteria]] = Field(default=None, description="Frame/slot criteria for destination entities in relation queries")
    
    # Frame-specific criteria (only used when query_type="frame")
    shared_frame_types: Optional[List[str]] = Field(default=None, description="Frame type URIs shared by connected entities")
    frame_slot_criteria: Optional[List[SlotCriteria]] = Field(default=None, description="Slot criteria on shared frames")
    frame_criteria: Optional[List[FrameCriteria]] = Field(default=None, description="Frame criteria with nested slot criteria (entity->frame->slot paths)")
    
    # Sorting
    sort_criteria: Optional[List[SortCriteria]] = Field(default=None, description="Multi-level sorting criteria (sort by slot values)")
    
    # Direct entity property filters
    entity_property_filters: Optional[List[EntityPropertyFilter]] = Field(default=None, description="Direct entity property filters (datatype-aware)")
    
    # Vector/geo search criteria
    vector_criteria: Optional[VectorSearchCriteria] = Field(default=None, description="Vector similarity search criteria")
    multi_vector_criteria: Optional[MultiVectorSearchCriteria] = Field(default=None, description="Multi-vector weighted fusion search criteria")
    geo_criteria: Optional[GeoSearchCriteria] = Field(default=None, description="Geographic proximity search criteria")
    fts_criteria: Optional[FTSCriteria] = Field(default=None, description="Unscored boolean full-text criterion")
    
    # Query constraints
    exclude_self_connections: bool = Field(default=True, description="Exclude connections from entity to itself")

    @model_validator(mode='after')
    def validate_fts_query_type(self) -> 'KGQueryCriteria':
        if self.fts_criteria and self.query_type not in {"entity", "frame_query"}:
            raise ValueError("fts_criteria is supported only for entity and frame_query queries")
        return self


class TotalCountMode(str, Enum):
    """How much effort to spend computing total_count.

    The count is over the selected query grain (for example distinct entities
    or distinct frames) across the whole match set. It cannot be paged, so it
    costs O(matches) however cheap the page is — measured on a 100,000-entity
    space: page 325ms, uncapped count 41.7s. That is a real
    trade-off rather than a bug, so it is the caller's to make.
    """

    NO = "no"
    """Do not compute it. The default: most callers page and never read it."""

    YES = "yes"
    """Compute it, bounded: stop at TOTAL_COUNT_CAP and report a lower bound.
    The response sets total_count_capped so a UI renders "1,000+"."""

    EXACT = "exact"
    """Compute the true total however long it takes. For callers that genuinely
    need the number — an export, a report, a reconciliation — and accept the
    cost. On a large space this can exceed the client's per-attempt timeout,
    and the query then runs on until the server's per-statement fence rather
    than stopping when the caller gives up. See issues/044."""


# The slot classes a projection can name, and the lane each one reads.
# Deliberately the SAME map `fast_slot_sort._LANE` uses, because a projection
# and a sort of the same column must read the same lane or they disagree about
# what the value is. Kept as a literal here rather than imported so the wire
# model does not depend on the db package.
_PROJECTABLE_SLOT_CLASSES = {
    "http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
    "http://vital.ai/ontology/haley-ai-kg#KGChoiceSlot",
    "http://vital.ai/ontology/haley-ai-kg#KGJsonSlot",
    "http://vital.ai/ontology/haley-ai-kg#KGURISlot",
    "http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
    "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot",
    "http://vital.ai/ontology/haley-ai-kg#KGLongSlot",
    "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
    "http://vital.ai/ontology/haley-ai-kg#KGCurrencySlot",
    "http://vital.ai/ontology/haley-ai-kg#KGDateTimeSlot",
}


class SlotProjection(BaseModel):
    """One column of a slot-value projection (`issues/208`).

    Read out of `{space}_entity_slot_sort` for the entities of the page that was
    already chosen, so a list view gets its columns without fetching each
    entity's whole graph: measured at 0.76 ms for a 25-entity page and eight
    columns, against 57.65 ms for the same eight values from the quads and
    3.5-5.1 s for the `include_entity_graph` fan-out that returns ~18,000 quads
    to render them.

    `slot_class_uri` IS REQUIRED and is how the value's type is decided. The
    table stores three lanes and does NOT record which value predicate produced
    a row — `value_text` holds the lexical form for a URI and for a string
    alike — so the caller declares the type, exactly as `SortCriteria` and
    `SlotCriteria` already make it declare one. A wrong class here reads the
    wrong lane and yields nulls rather than a wrong value, because a text slot
    has no `value_num`.

    `frame_path` IS REQUIRED and must be the WHOLE ordered path of frame types
    from the entity down to the slot's parent. The table is keyed on that path,
    a slot hanging directly off an entity is not in it at all, and a loose match
    admits entities reached by a different path — the wrong-rows failure
    `component_intersect` records. One hop is a path of one.
    """

    alias: str = Field(..., description="Name this column is returned under")
    frame_path: List[str] = Field(..., description="Ordered frame type URIs from the entity to the slot's parent frame")
    slot_type: str = Field(..., description="Slot type URI to project")
    slot_class_uri: str = Field(..., description="Slot class URI (e.g. KGTextSlot) — decides which value lane is read")

    @model_validator(mode='after')
    def validate_projection(self) -> 'SlotProjection':
        if not self.alias.strip():
            raise ValueError("alias is required and cannot be blank")
        if not self.frame_path:
            raise ValueError(
                f"frame_path is required for projection '{self.alias}'. "
                f"entity_slot_sort holds only slots reached through at least "
                f"one frame; a slot attached directly to an entity is not in "
                f"the table and would project as absent rather than as an error"
            )
        if self.slot_class_uri not in _PROJECTABLE_SLOT_CLASSES:
            raise ValueError(
                f"slot_class_uri '{self.slot_class_uri}' is not projectable. "
                f"Allowed: {', '.join(sorted(_PROJECTABLE_SLOT_CLASSES))}"
            )
        return self


class PropertyProjection(BaseModel):
    """One column of a DIRECT entity-property projection (`issues/208`).

    The sibling of `SlotProjection` for properties hanging straight off the
    entity rather than reached through a frame. Read from the QUADS, not from
    `entity_prop_sort` — measured at 0.31 ms against that table's 0.07 ms for
    five columns over a 25-entity page, which is noise either way, and the
    quads are authoritative (no coverage gate, so a column cannot go quietly
    blank) and hold EVERY property rather than the seven that table maintains.

    No datatype is declared, and none is needed: `SlotProjection` names a slot
    class because the sort table splits values into three lanes and one must be
    chosen. A quad carries its object directly, so the lexical form is the
    value.
    """

    alias: str = Field(..., description="Name this column is returned under")
    property_uri: str = Field(..., description="Direct property URI on the entity")

    @model_validator(mode='after')
    def validate_property_projection(self) -> 'PropertyProjection':
        if not self.alias.strip():
            raise ValueError("alias is required and cannot be blank")
        if not self.property_uri.strip():
            raise ValueError(
                f"property_uri is required for projection '{self.alias}'")
        return self


class KGQueryRequest(BaseModel):
    """Request model for KG queries."""
    criteria: KGQueryCriteria = Field(..., description="Query criteria")
    page_size: int = Field(10, description="Number of results per page", ge=1, le=100)
    offset: int = Field(0, description="Offset for pagination", ge=0)
    include_frame_graph: bool = Field(default=False, description="When True, include structured frame graph data in frame_query results")
    include_entity_graph: bool = Field(default=False, description="When True, include structured entity graph data in entity query results")
    count_only: bool = Field(default=False, description="When True, execute only the count query and return total_count with empty result lists")
    slot_projection: Optional[List[SlotProjection]] = Field(
        None,
        description=(
            "Slot values to return for the entities of the page, read from "
            "{space}_entity_slot_sort. Each column names its frame_path, "
            "slot_type and slot_class_uri. Answered for entity queries; "
            "count_only has no page and returns none."))
    property_projection: Optional[List[PropertyProjection]] = Field(
        None,
        description=(
            "Direct entity properties to return for the entities of the page, "
            "read from the quads. Shares the response map with "
            "slot_projection, so a list view gets one row per entity whichever "
            "kind each column is; aliases must be unique across both."))

    @model_validator(mode='after')
    def validate_projection_aliases(self) -> 'KGQueryRequest':
        """Two columns under one alias would silently overwrite each other.

        The response is keyed by alias, so a duplicate does not merge or error
        at read time -- it returns one column where the caller asked for two,
        with nothing saying which one survived. Checked ACROSS both projection
        lists, because they share one response map: a slot column and a
        property column under one name collide exactly as two slot columns do.
        """
        seen = set()
        for p in list(self.slot_projection or []) + list(self.property_projection or []):
            if p.alias in seen:
                raise ValueError(
                    f"duplicate projection alias '{p.alias}' — the response is "
                    f"keyed by alias, so one column would silently replace the "
                    f"other")
            seen.add(p.alias)
        return self
    include_total_count: TotalCountMode = Field(
        default=TotalCountMode.NO,
        description=(
            "Whether to compute total_count: 'no' (default), 'yes' (bounded — "
            "stops at the cap and reports a lower bound, with "
            "total_count_capped set), or 'exact' (the true total, however long "
            "it takes). One type, three values — booleans are not accepted, so "
            "there is no ambiguity about what True would have meant."))


class RelationConnection(BaseModel):
    """Represents a relation-based connection between two entities."""
    source_entity_uri: str = Field(..., description="Source entity URI")
    destination_entity_uri: str = Field(..., description="Destination entity URI")
    relation_edge_uri: str = Field(..., description="Relation edge URI")
    relation_type_uri: str = Field(..., description="Relation type URN")


class FrameConnection(BaseModel):
    """Represents a frame-based connection between two entities."""
    source_entity_uri: str = Field(..., description="Source entity URI")
    destination_entity_uri: str = Field(..., description="Destination entity URI")
    shared_frame_uri: str = Field(..., description="Shared frame URI")
    frame_type_uri: str = Field(..., description="Frame type URI")


class EntitySlotRef(BaseModel):
    """An entity reference from a frame's entity slot, including the slot's role."""
    slot_type_uri: str = Field(..., description="Slot type URI identifying the role (e.g. PersonSlot, CompanySlot)")
    entity_uri: str = Field(..., description="Entity URI referenced by the slot")


class FTSMatch(BaseModel):
    """One indexed slot that satisfied a KG query's boolean FTS criterion."""

    subject_uri: str = Field(..., description="URI of the matching indexed slot")
    frame_uri: Optional[str] = Field(default=None, description="URI of the containing frame")
    owner_entity_uri: Optional[str] = Field(default=None, description="URI of the owning entity graph")
    target_kind: Optional[str] = Field(default=None, description="Caller-defined label from the matching FTS target")
    text: Optional[str] = Field(default=None, description="Matching slot text when requested")


class FrameQueryResult(BaseModel):
    """A single frame result from a frame_query, with connected entity references."""
    frame_uri: str = Field(..., description="URI of the matching frame")
    frame_type_uri: str = Field(..., description="Frame type URI")
    entity_refs: List[EntitySlotRef] = Field(default_factory=list, description="Entities connected via entity slots, with their slot roles")
    frame_graph: Optional[Any] = Field(default=None, description="Structured frame graph data (when include_frame_graph=True)")
    fts_matches: List[FTSMatch] = Field(default_factory=list, description="Indexed slots that matched the FTS criterion")


class KGQueryResponse(BasePaginatedResponse):
    # NOTE: total_count is only populated when the request sets
    # include_total_count. When it is, the count stops at a cap — see
    # total_count_capped — so a UI must render "1,000+" rather than an exact
    # figure when that flag is set.
    """Response model for KG queries."""
    total_count: int = Field(default=0, description="Total results when requested")
    page_size: int = Field(default=0, description="Number of items requested per page")
    offset: int = Field(default=0, description="Pagination offset")
    query_type: str = Field(default="", description="Query type that was executed")
    fts_applied: bool = Field(
        default=False,
        description="True when the server applied the requested fts_criteria",
    )
    total_count_capped: bool = Field(
        default=False,
        description=("True when total_count hit the cap and is a lower bound "
                     "rather than an exact figure — render as '1,000+'."))
    # Case 1 (frame_query)
    frame_results: Optional[List[FrameQueryResult]] = Field(
        default=None,
        description="Frame query results with entity refs (when query_type='frame_query')",
    )
    # Case 2 (entity)
    entity_uris: Optional[List[str]] = Field(
        default=None, description="Matching entity URIs (when query_type='entity')")
    entity_fts_matches: Optional[Dict[str, List[FTSMatch]]] = Field(
        default=None, description="FTS matches keyed by entity URI")
    entity_graphs: Optional[Dict[str, List[Dict[str, Any]]]] = Field(
        default=None,
        description="Entity graphs as JSON quads ({s,p,o,g}) keyed by entity URI (when include_entity_graph=True)",
    )
    entity_values: Optional[Dict[str, Dict[str, List[Any]]]] = Field(
        default=None,
        description=(
            "Projected column values (when slot_projection or "
            "property_projection is set): entity URI -> alias -> LIST of "
            "values, with both kinds of column in ONE map so a list view gets "
            "one row per entity. A list because an entity may legitimately "
            "carry several slots of one type — measured up to 6 on a production "
            "space — and returning one of them would be a silent choice. An "
            "entity with no such slot has an empty list for that alias; an "
            "entity absent from the map was not projected at all. Numeric and "
            "datetime values cross the wire as strings, which is what every "
            "other value on this API does — SPARQL JSON results are strings "
            "too — and is lossless where a float would not be."))
    # Case 3 (relation)
    relation_connections: Optional[List[RelationConnection]] = Field(
        default=None,
        description="Relation connections (when query_type='relation')",
    )
    # Case 4 (document)
    document_uris: Optional[List[str]] = Field(
        default=None,
        description="Matching document/segment URIs (when query_type='document')",
    )
    document_results: Optional[List['DocumentResult']] = Field(
        default=None,
        description="Enriched document results with parent context (when query_type='document' with include_parent_context=True)",
    )
    # Legacy (query_type='frame' — unchanged)
    frame_connections: Optional[List[FrameConnection]] = Field(
        default=None, description="Frame connections (when query_type='frame')")



# ── Strongly-typed client response models (Phase 2b) ──
# These wrap KGQueryResponse for each query_type so client code gets
# the right fields without checking query_type or Optional branches.

class FrameQueryResponse(BasePaginatedResponse):
    """Typed response from query_frames() — Case 1 (frame as top-most object)."""
    results: List[FrameQueryResult] = Field(default_factory=list, description="Frame results with entity refs")
    fts_applied: bool = Field(default=False, description="True when the server applied fts_criteria")
    total_count_capped: bool = Field(default=False, description="True when total_count is a capped lower bound")

    @classmethod
    def from_raw(cls, raw: 'KGQueryResponse') -> 'FrameQueryResponse':
        return cls(
            success=raw.success,
            status=raw.status,
            message=raw.message,
            results=raw.frame_results or [],
            fts_applied=raw.fts_applied,
            total_count=raw.total_count,
            total_count_capped=raw.total_count_capped,
            page_size=raw.page_size,
            offset=raw.offset,
        )


class KGEntityQueryResponse(BasePaginatedResponse):
    """Typed response from query_entities() — Case 2 (entity as top-most object).
    
    Named KGEntityQueryResponse to avoid collision with kgentities_model.EntityQueryResponse.
    """
    entity_uris: List[str] = Field(default_factory=list, description="Matching entity URIs")
    fts_matches: Optional[Dict[str, List[FTSMatch]]] = Field(default=None, description="FTS matches keyed by entity URI")
    fts_applied: bool = Field(default=False, description="True when the server applied fts_criteria")
    total_count_capped: bool = Field(default=False, description="True when total_count is a capped lower bound")
    entity_graphs: Optional[Dict[str, List[Dict[str, Any]]]] = Field(default=None, description="Entity graphs as JSON quads ({s,p,o,g}) keyed by URI (when include_entity_graph=True)")
    entity_graph_objects: Optional[Dict[str, List[Any]]] = Field(None, exclude=True, description="Hydrated GraphObjects keyed by URI (populated client-side only)")
    entity_values: Optional[Dict[str, Dict[str, List[Any]]]] = Field(default=None, description="Projected column values keyed by entity URI, then alias (when a projection was requested)")

    @classmethod
    def from_raw(cls, raw: 'KGQueryResponse') -> 'KGEntityQueryResponse':
        return cls(
            success=raw.success,
            status=raw.status,
            message=raw.message,
            entity_uris=raw.entity_uris or [],
            fts_matches=raw.entity_fts_matches,
            entity_graph_objects=None,
            fts_applied=raw.fts_applied,
            total_count_capped=raw.total_count_capped,
            entity_graphs=raw.entity_graphs,
            entity_values=raw.entity_values,
            total_count=raw.total_count,
            page_size=raw.page_size,
            offset=raw.offset,
        )


class RelationQueryResponse(BasePaginatedResponse):
    """Typed response from query_relation_connections() — Case 3 (relation edge as top-most object)."""
    connections: List[RelationConnection] = Field(default_factory=list, description="Relation connections")

    @classmethod
    def from_raw(cls, raw: 'KGQueryResponse') -> 'RelationQueryResponse':
        return cls(
            status=raw.status,
            message=raw.message,
            connections=raw.relation_connections or [],
            total_count=raw.total_count,
            page_size=raw.page_size,
            offset=raw.offset,
        )


class DocumentResult(BaseModel):
    """A single document result with optional parent/original context."""
    document_uri: str = Field(..., description="Document or segment URI")
    score: Optional[float] = Field(default=None, description="Vector similarity or hybrid score (when vector_criteria used)")
    segment_text: Optional[str] = Field(default=None, description="Segment chunk text (when include_segment_text=True)")
    segment_headline: Optional[str] = Field(default=None, description="Segment heading (when include_segment_text=True)")
    parent_document_uri: Optional[str] = Field(default=None, description="Parent copy URI (when include_parent_context=True)")
    parent_document_name: Optional[str] = Field(default=None, description="Parent copy name (when include_parent_context=True)")
    original_document_uri: Optional[str] = Field(default=None, description="Original document URI (when include_original_uri=True)")


class DocumentQueryResponse(BasePaginatedResponse):
    """Typed response from query_documents() — Case 4 (document as top-most object)."""
    document_uris: List[str] = Field(default_factory=list, description="Flat list of document/segment URIs")
    document_results: Optional[List[DocumentResult]] = Field(
        None, description="Enriched results with parent context (populated when include_parent_context=True)")

    @classmethod
    def from_raw(cls, raw: 'KGQueryResponse') -> 'DocumentQueryResponse':
        return cls(
            status=raw.status,
            message=raw.message,
            document_uris=raw.document_uris or [],
            document_results=raw.document_results,
            total_count=raw.total_count,
            page_size=raw.page_size,
            offset=raw.offset,
        )


# Optional: Statistics and utility models

class KGQueryStatsResponse(ResultStatus):
    """Response model for KG query statistics."""
    total_entities: int = Field(..., description="Total entities in graph")
    total_relations: int = Field(..., description="Total relations in graph")
    total_frames: int = Field(..., description="Total frames in graph")
    relation_connections_count: int = Field(..., description="Count of relation-based connections")
    frame_connections_count: int = Field(..., description="Count of frame-based connections")
