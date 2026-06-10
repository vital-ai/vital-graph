"""KG Query Builder

Builds SPARQL queries specifically for KG entity and frame operations,
including graph separation queries and criteria-based search queries.
"""

import logging
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Slot class URI → value property mapping (full URIs, never use substring match)
# ---------------------------------------------------------------------------
_HALEY_NS = "http://vital.ai/ontology/haley-ai-kg#"

_SLOT_CLASS_TO_VALUE_PROPERTY = {
    f"{_HALEY_NS}KGAudioSlot":              "haley:hasAudioSlotValue",
    f"{_HALEY_NS}KGBooleanSlot":            "haley:hasBooleanSlotValue",
    f"{_HALEY_NS}KGChoiceOptionSlot":       "haley:hasChoiceSlotOptionValues",
    f"{_HALEY_NS}KGChoiceSlot":             "haley:hasChoiceSlotValue",
    f"{_HALEY_NS}KGCodeSlot":               "haley:hasCodeSlotValue",
    f"{_HALEY_NS}KGCurrencySlot":           "haley:hasCurrencySlotValue",
    f"{_HALEY_NS}KGDateTimeSlot":           "haley:hasDateTimeSlotValue",
    f"{_HALEY_NS}KGDoubleSlot":             "haley:hasDoubleSlotValue",
    f"{_HALEY_NS}KGEntitySlot":             "haley:hasEntitySlotValue",
    f"{_HALEY_NS}KGFileUploadSlot":         "haley:hasFileUploadSlotValue",
    f"{_HALEY_NS}KGGeoLocationSlot":        "haley:hasGeoLocationSlotValue",
    f"{_HALEY_NS}KGImageSlot":              "haley:hasImageSlotValue",
    f"{_HALEY_NS}KGIntegerSlot":            "haley:hasIntegerSlotValue",
    f"{_HALEY_NS}KGJSONSlot":               "haley:hasJsonSlotValue",
    f"{_HALEY_NS}KGLongSlot":               "haley:hasLongSlotValue",
    f"{_HALEY_NS}KGLongTextSlot":           "haley:hasLongTextSlotValue",
    f"{_HALEY_NS}KGMultiChoiceOptionSlot":  "haley:hasMultiChoiceSlotValues",
    f"{_HALEY_NS}KGMultiChoiceSlot":        "haley:hasMultiChoiceSlotValues",
    f"{_HALEY_NS}KGMultiTaxonomyOptionSlot": "haley:hasKGTaxonomyOptionURI",
    f"{_HALEY_NS}KGMultiTaxonomySlot":      "haley:hasMultiTaxonomySlotValues",
    f"{_HALEY_NS}KGPropertySlot":           "haley:hasPropertyFrameTypeSlotValue",
    f"{_HALEY_NS}KGRunSlot":                "haley:hasRunSlotValue",
    f"{_HALEY_NS}KGTaxonomyOptionSlot":     "haley:hasKGTaxonomyOptionURI",
    f"{_HALEY_NS}KGTaxonomySlot":           "haley:hasTaxonomySlotValue",
    f"{_HALEY_NS}KGTextSlot":               "haley:hasTextSlotValue",
    f"{_HALEY_NS}KGURISlot":                "haley:hasUriSlotValue",
    f"{_HALEY_NS}KGVideoSlot":              "haley:hasVideoSlotValue",
}

_URI_VALUE_SLOT_CLASSES = {
    f"{_HALEY_NS}KGAudioSlot",
    f"{_HALEY_NS}KGCodeSlot",
    f"{_HALEY_NS}KGEntitySlot",
    f"{_HALEY_NS}KGFileUploadSlot",
    f"{_HALEY_NS}KGImageSlot",
    f"{_HALEY_NS}KGMultiTaxonomyOptionSlot",
    f"{_HALEY_NS}KGMultiTaxonomySlot",
    f"{_HALEY_NS}KGPropertySlot",
    f"{_HALEY_NS}KGRunSlot",
    f"{_HALEY_NS}KGTaxonomyOptionSlot",
    f"{_HALEY_NS}KGTaxonomySlot",
    f"{_HALEY_NS}KGURISlot",
    f"{_HALEY_NS}KGVideoSlot",
}

_NUMERIC_SLOT_CLASSES = {
    f"{_HALEY_NS}KGCurrencySlot": "xsd:double",
    f"{_HALEY_NS}KGDoubleSlot":   "xsd:double",
    f"{_HALEY_NS}KGIntegerSlot":  "xsd:integer",
    f"{_HALEY_NS}KGLongSlot":     "xsd:integer",
}

_TEXT_SLOT_CLASSES = {
    f"{_HALEY_NS}KGChoiceOptionSlot",
    f"{_HALEY_NS}KGChoiceSlot",
    f"{_HALEY_NS}KGJSONSlot",
    f"{_HALEY_NS}KGLongTextSlot",
    f"{_HALEY_NS}KGMultiChoiceOptionSlot",
    f"{_HALEY_NS}KGMultiChoiceSlot",
    f"{_HALEY_NS}KGTextSlot",
}


@dataclass
class FrameCriteria:
    """Criteria for frame filtering in KG queries.
    
    Supports hierarchical frame structures:
    - frame_type filters the frame at this level
    - slot_criteria filters slots within this frame
    - frame_criteria allows recursive nesting for child frames (e.g., parent→child→grandchild)
    
    Example flat structure: entity→frame→slot
    Example hierarchical: entity→parent_frame→child_frame→slot
    """
    frame_type: Optional[str] = None  # Frame type URI to filter by
    negate: bool = False  # When True, wrap entire frame pattern in FILTER NOT EXISTS
    slot_criteria: Optional[List['SlotCriteria']] = None  # Slot criteria within this frame
    frame_criteria: Optional[List['FrameCriteria']] = None  # Nested frame criteria for hierarchical structures


@dataclass
class SlotCriteria:
    """Criteria for slot filtering in KG queries."""
    slot_type: Optional[str] = None
    slot_class_uri: Optional[str] = None  # Underlying slot class URI (e.g., KGTextSlot, KGDoubleSlot)
    value: Optional[Any] = None
    comparator: Optional[str] = None  # "eq", "gt", "lt", "gte", "lte", "contains", "ne", "exists", "not_exists", "is_empty", "has", "has_any", "has_all", "not_has", "not_has_any"


@dataclass
class SortCriteria:
    """Criteria for sorting in KG queries.
    
    frame_path is an ordered list of frame type URIs from the anchor
    (entity/frame) to the slot's parent frame, disambiguating the same
    slot type under different frame hierarchies.
    
    For entity_property sort_type, only property_uri is used — the sort
    binds directly to a property on the entity node (e.g. hasName).
    """
    sort_type: str  # "entity_frame_slot" | "frame_slot" | "source_frame_slot" | "destination_frame_slot" | "entity_property"
    slot_type: Optional[str] = None  # Slot type URI to sort by (required for slot-based sort types)
    slot_class_uri: Optional[str] = None  # Slot class URI (e.g. KGTextSlot) — determines value property
    frame_path: Optional[List[str]] = None  # Ordered frame type URIs from anchor to slot's parent frame
    property_uri: Optional[str] = None  # Direct property URI — required for entity_property sort_type
    sort_order: str = "asc"  # "asc" | "desc"
    priority: int = 1  # 1=primary, 2=secondary, 3=tertiary, etc.


@dataclass
class VectorCriteria:
    """Criteria for vector similarity search.

    Generates SPARQL:
      BIND(vg:vectorSimilarity(?entity, "search_text", "index_name") AS ?vg_score)
    or with a pre-computed vector:
      BIND(vg:vectorNearby(?entity, "[0.1,0.2,...]", "index_name") AS ?vg_score)

    When used, results are automatically sorted by similarity (DESC) and
    limited to top_k results unless sort_criteria overrides.
    """
    search_text: Optional[str] = None        # Text to vectorize server-side
    vector: Optional[str] = None             # Pre-computed vector literal "[0.1,...]"
    index_name: str = "entity_default"       # Vector index name
    top_k: int = 10                          # Max results (becomes LIMIT)
    min_score: Optional[float] = None        # Optional threshold (FILTER ?vg_score > T)
    score_variable: str = "vg_score"         # SPARQL variable for the score


@dataclass
class GeoCriteria:
    """Criteria for geographic proximity search.

    Generates SPARQL:
      BIND(vg:geoDistance(?entity, lat, lon) AS ?vg_distance)
    and/or:
      FILTER(vg:withinRadius(?entity, lat, lon, radius_m))

    When radius_m is set, only entities within the radius are returned.
    When sort_by_distance is True, results are sorted by distance (ASC).
    """
    latitude: float = 0.0
    longitude: float = 0.0
    radius_m: Optional[float] = None         # Filter to within radius (meters)
    sort_by_distance: bool = False           # ORDER BY distance ASC
    top_k: Optional[int] = None             # Limit results (for nearest-N)
    distance_variable: str = "vg_distance"  # SPARQL variable for distance


@dataclass
class MultiVectorCriteriaInput:
    """A single weighted vector input for multi-vector search."""
    search_text: Optional[str] = None    # Text to vectorize server-side
    vector: Optional[str] = None         # Pre-computed vector literal "[0.1,...]"
    index_name: str = "entity_default"   # Vector index name
    weight: float = 1.0                  # Relative weight (auto-normalized)


@dataclass
class MultiVectorCriteria:
    """Criteria for multi-vector similarity search.

    Generates SPARQL:
      BIND(vg:multiVectorSimilarity(?entity, text1, idx1, w1, text2, idx2, w2) AS ?vg_score)
    or with pre-computed vectors:
      BIND(vg:multiVectorNearby(?entity, vec1, idx1, w1, vec2, idx2, w2) AS ?vg_score)

    Combines scores from multiple vector indexes with weighted fusion.
    """
    vectors: List[MultiVectorCriteriaInput] = field(default_factory=list)
    top_k: int = 10                          # Max results (becomes LIMIT)
    min_score: Optional[float] = None        # Optional threshold (FILTER ?vg_score > T)
    score_variable: str = "vg_score"         # SPARQL variable for the score
    fusion_strategy: str = "weighted_sum"    # weighted_sum | relative_score | ranked
    oversample_factor: int = 5              # candidates per vector = top_k * factor


@dataclass
class QueryFilter:
    """Simple property-based filter for entity queries."""
    property_name: str
    operator: str  # "equals", "not_equals", "contains", "exists", "gt", "lt", "gte", "lte"
    value: Optional[Any] = None


# Property datatype registry (mirrors _FILTERABLE_ENTITY_PROPERTIES in kgentities_model.py)
_FILTERABLE_ENTITY_PROPERTIES = {
    "http://vital.ai/ontology/vital-core#hasName":                        "string",
    "http://vital.ai/ontology/vital#hasObjectModificationDateTime":       "dateTime",
    "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime":          "dateTime",
    "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType":               "uri",
    "http://vital.ai/ontology/vital-aimp#hasObjectStatusType":            "uri",
}


@dataclass
class EntityPropertyFilter:
    """Filter on a direct property of the entity node."""
    property_uri: str
    operator: str  # "eq", "ne", "gt", "lt", "gte", "lte", "contains", "in", "not_in"
    value: Optional[Union[str, List[str]]] = None


@dataclass
class EntityQueryCriteria:
    """Criteria for entity queries."""
    search_string: Optional[str] = None  # Search in entity name
    entity_type: Optional[str] = None    # Filter by entity type URI
    entity_uris: Optional[List[str]] = None  # Filter by specific entity URIs
    frame_criteria: Optional[List[FrameCriteria]] = None  # Frame-based filtering
    slot_criteria: Optional[List[SlotCriteria]] = None  # Slot-based filtering
    sort_criteria: Optional[List[SortCriteria]] = None  # Multi-level sorting
    filters: Optional[List[QueryFilter]] = None  # Property-based filters
    entity_property_filters: Optional[List[EntityPropertyFilter]] = None  # Direct entity property filters
    use_edge_pattern: bool = True  # Use edge-based pattern (Edge_hasEntityKGFrame) vs direct property (hasFrame)
    vector_criteria: Optional[VectorCriteria] = None  # Vector similarity search
    multi_vector_criteria: Optional[MultiVectorCriteria] = None  # Multi-vector weighted fusion
    geo_criteria: Optional[GeoCriteria] = None  # Geographic proximity search


@dataclass
class FrameQueryCriteria:
    """Criteria for frame queries."""
    search_string: Optional[str] = None  # Search in frame name
    frame_type: Optional[str] = None     # Filter by frame type URI
    entity_type: Optional[str] = None    # Frames must belong to entity of this type
    slot_criteria: Optional[List[SlotCriteria]] = None  # Slot-based filtering
    sort_criteria: Optional[List[SortCriteria]] = None  # Multi-level sorting
    vector_criteria: Optional[VectorCriteria] = None  # Vector similarity search
    geo_criteria: Optional[GeoCriteria] = None  # Geographic proximity search


class KGGraphSeparationQueryBuilder:
    """Builds SPARQL queries for KG entity/frame graph separation and validation."""
    
    def __init__(self):
        """Initialize the query builder."""
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Ontology prefixes for KG operations
        self.prefixes = """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        """
    
    def build_entity_discovery_query(self) -> str:
        """Build query to discover all KGEntity subjects.
        
        Returns:
            SPARQL query string to find all KGEntity subjects
        """
        query = f"""
        {self.prefixes}
        SELECT DISTINCT ?entity WHERE {{
            ?entity vital-core:vitaltype haley:KGEntity .
        }}
        """
        
        self.logger.debug("Built entity discovery query")
        return query.strip()
    
    def build_frame_discovery_query(self) -> str:
        """Build query to discover all KGFrame subjects.
        
        Returns:
            SPARQL query string to find all KGFrame subjects
        """
        query = f"""
        {self.prefixes}
        SELECT DISTINCT ?frame WHERE {{
            ?frame rdf:type haley:KGFrame .
        }}
        """
        
        self.logger.debug("Built frame discovery query")
        return query.strip()
    
    def build_frame_relationship_query(self, entity_uri: str) -> str:
        """Build query to find frames related to an entity.
        
        Args:
            entity_uri: URI of the entity
            
        Returns:
            SPARQL query string to find related frames
        """
        query = f"""
        {self.prefixes}
        SELECT DISTINCT ?frame ?predicate ?object WHERE {{
            <{entity_uri}> haley:hasFrame ?frame .
            ?frame ?predicate ?object .
        }}
        """
        
        self.logger.debug(f"Built frame relationship query for entity {entity_uri}")
        return query.strip()
    
    def build_slot_relationship_query(self, frame_uri: str) -> str:
        """Build query to find slots related to a frame.
        
        Args:
            frame_uri: URI of the frame
            
        Returns:
            SPARQL query string to find related slots
        """
        query = f"""
        {self.prefixes}
        SELECT DISTINCT ?slot ?predicate ?object WHERE {{
            ?slot_edge vital-core:hasEdgeSource <{frame_uri}> .
            ?slot_edge vital-core:hasEdgeDestination ?slot .
            ?slot ?predicate ?object .
        }}
        """
        
        self.logger.debug(f"Built slot relationship query for frame {frame_uri}")
        return query.strip()
    
    def build_child_frame_query(self, parent_frame_uri: str) -> str:
        """Build query to find child frames of a parent frame.
        
        Args:
            parent_frame_uri: URI of the parent frame
            
        Returns:
            SPARQL query string to find child frames
        """
        query = f"""
        {self.prefixes}
        SELECT DISTINCT ?child_frame ?predicate ?object WHERE {{
            <{parent_frame_uri}> haley:hasChildFrame ?child_frame .
            ?child_frame ?predicate ?object .
        }}
        """
        
        self.logger.debug(f"Built child frame query for parent {parent_frame_uri}")
        return query.strip()
    
    def build_entity_graph_collection_query(self, entity_uri: str) -> str:
        """Build comprehensive query to collect entire entity graph.
        
        Args:
            entity_uri: URI of the entity
            
        Returns:
            SPARQL query to collect all entity graph triples
        """
        query = f"""
        {self.prefixes}
        SELECT DISTINCT ?subject ?predicate ?object WHERE {{
            {{
                # Entity triples
                <{entity_uri}> ?predicate ?object .
                BIND(<{entity_uri}> as ?subject)
            }} UNION {{
                # Frame triples
                <{entity_uri}> haley:hasFrame ?frame .
                ?frame ?predicate ?object .
                BIND(?frame as ?subject)
            }} UNION {{
                # Slot triples
                <{entity_uri}> haley:hasFrame ?frame .
                ?slot_edge vital-core:hasEdgeSource ?frame .
                ?slot_edge vital-core:hasEdgeDestination ?slot .
                ?slot ?predicate ?object .
                BIND(?slot as ?subject)
            }} UNION {{
                # Child frame triples
                <{entity_uri}> haley:hasFrame ?parent_frame .
                ?parent_frame haley:hasChildFrame ?child_frame .
                ?child_frame ?predicate ?object .
                BIND(?child_frame as ?subject)
            }}
        }}
        """
        
        self.logger.debug(f"Built entity graph collection query for {entity_uri}")
        return query.strip()
    
    def build_frame_graph_collection_query(self, frame_uri: str) -> str:
        """Build comprehensive query to collect entire frame graph.
        
        Args:
            frame_uri: URI of the frame
            
        Returns:
            SPARQL query to collect all frame graph triples
        """
        query = f"""
        {self.prefixes}
        SELECT DISTINCT ?subject ?predicate ?object WHERE {{
            {{
                # Frame triples
                <{frame_uri}> ?predicate ?object .
                BIND(<{frame_uri}> as ?subject)
            }} UNION {{
                # Slot triples
                ?slot_edge vital-core:hasEdgeSource <{frame_uri}> .
                ?slot_edge vital-core:hasEdgeDestination ?slot .
                ?slot ?predicate ?object .
                BIND(?slot as ?subject)
            }} UNION {{
                # Child frame triples
                <{frame_uri}> haley:hasChildFrame ?child_frame .
                ?child_frame ?predicate ?object .
                BIND(?child_frame as ?subject)
            }}
        }}
        """
        
        self.logger.debug(f"Built frame graph collection query for {frame_uri}")
        return query.strip()


class KGQueryCriteriaBuilder:
    """Builds SPARQL queries for KG entity/frame criteria-based searches."""
    
    def __init__(self):
        """Initialize the criteria query builder."""
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Ontology prefixes for KG operations
        self.prefixes = """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX vg-direct: <http://vital.ai/vitalgraph/direct#>
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        """
    
    def _build_entity_where_clause(self, criteria: EntityQueryCriteria) -> str:
        """Build the full WHERE clause body for entity queries.
        
        Shared by both paginated queries and count queries so that
        frame criteria, slot criteria, and all filters are always included.
        
        Args:
            criteria: Entity query criteria
            
        Returns:
            WHERE clause body string (without the outer WHERE { } wrapper)
        """
        # Build WHERE clauses - start with base class selection (vitaltype)
        class_clause = """
        {
            ?entity vital-core:vitaltype haley:KGEntity .
        } UNION {
            ?entity vital-core:vitaltype haley:KGNewsEntity .
        } UNION {
            ?entity vital-core:vitaltype haley:KGProductEntity .
        } UNION {
            ?entity vital-core:vitaltype haley:KGWebEntity .
        }"""
        
        # Collect all additional filters
        filter_clauses = []
        
        # Add entity URI filter - restrict to specific entity URIs if provided
        if criteria.entity_uris:
            uri_list = " ".join([f"<{uri}>" for uri in criteria.entity_uris])
            filter_clauses.append(f"VALUES ?entity {{ {uri_list} }}")
        
        # Add entity type filter - use hasKGEntityType for specific entity types
        if criteria.entity_type and criteria.entity_type != "http://vital.ai/ontology/haley-ai-kg#KGEntity":
            filter_clauses.append(f"?entity haley:hasKGEntityType <{criteria.entity_type}> .")
        
        # Add search string filter (search in hasName only)
        if criteria.search_string:
            filter_clauses.append(f"""?entity vital-core:hasName ?search_name .
FILTER(CONTAINS(LCASE(?search_name), LCASE("{criteria.search_string}")))""")
        
        # Frame type filtering is now handled via frame_criteria, not a single frame_type field
        
        # Add property-based filters
        if criteria.filters:
            for i, filter_criterion in enumerate(criteria.filters):
                filter_var = f"filter_value_{i}"
                property_uri = self._get_property_uri(filter_criterion.property_name)
                
                if filter_criterion.operator == "exists":
                    filter_clauses.append(f"?entity <{property_uri}> ?{filter_var} .")
                elif filter_criterion.operator == "equals":
                    # For rdf:type comparisons, use URI reference instead of string literal
                    if property_uri == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type":
                        filter_clauses.append(f"?entity <{property_uri}> <{filter_criterion.value}> .")
                    else:
                        filter_clauses.append(f"?entity <{property_uri}> \"{filter_criterion.value}\" .")
                elif filter_criterion.operator == "not_equals":
                    filter_clauses.append(f"?entity <{property_uri}> ?{filter_var} .")
                    filter_clauses.append(f"FILTER(?{filter_var} != \"{filter_criterion.value}\")")
                elif filter_criterion.operator == "contains":
                    filter_clauses.append(f"?entity <{property_uri}> ?{filter_var} .")
                    filter_clauses.append(f"FILTER(CONTAINS(LCASE(STR(?{filter_var})), LCASE(\"{filter_criterion.value}\")))")
        
        # Add direct entity property filters (datatype-aware)
        if criteria.entity_property_filters:
            for i, epf in enumerate(criteria.entity_property_filters):
                var = f"epf_val_{i}"
                prop_uri = epf.property_uri
                datatype = _FILTERABLE_ENTITY_PROPERTIES.get(prop_uri, "string")
                
                if epf.operator == "eq":
                    if datatype == "uri":
                        filter_clauses.append(f"?entity <{prop_uri}> <{epf.value}> .")
                    elif datatype == "dateTime":
                        filter_clauses.append(f'?entity <{prop_uri}> "{epf.value}"^^xsd:dateTime .')
                    else:
                        filter_clauses.append(f'?entity <{prop_uri}> "{epf.value}" .')
                elif epf.operator == "ne":
                    filter_clauses.append(f"?entity <{prop_uri}> ?{var} .")
                    if datatype == "uri":
                        filter_clauses.append(f"FILTER(?{var} != <{epf.value}>)")
                    elif datatype == "dateTime":
                        filter_clauses.append(f'FILTER(?{var} != "{epf.value}"^^xsd:dateTime)')
                    else:
                        filter_clauses.append(f'FILTER(?{var} != "{epf.value}")')
                elif epf.operator == "contains":
                    filter_clauses.append(f"?entity <{prop_uri}> ?{var} .")
                    filter_clauses.append(f'FILTER(CONTAINS(LCASE(STR(?{var})), LCASE("{epf.value}")))')
                elif epf.operator in ("gt", "lt", "gte", "lte"):
                    filter_clauses.append(f"?entity <{prop_uri}> ?{var} .")
                    op_map = {"gt": ">", "lt": "<", "gte": ">=", "lte": "<="}
                    sparql_op = op_map[epf.operator]
                    if datatype == "dateTime":
                        filter_clauses.append(f'FILTER(?{var} {sparql_op} "{epf.value}"^^xsd:dateTime)')
                    else:
                        filter_clauses.append(f'FILTER(?{var} {sparql_op} "{epf.value}")')
                elif epf.operator == "in" and isinstance(epf.value, list):
                    filter_clauses.append(f"?entity <{prop_uri}> ?{var} .")
                    if datatype == "uri":
                        val_list = ", ".join(f"<{v}>" for v in epf.value)
                    else:
                        val_list = ", ".join(f'"{v}"' for v in epf.value)
                    filter_clauses.append(f"FILTER(?{var} IN ({val_list}))")
                elif epf.operator == "not_in" and isinstance(epf.value, list):
                    filter_clauses.append(f"?entity <{prop_uri}> ?{var} .")
                    if datatype == "uri":
                        val_list = ", ".join(f"<{v}>" for v in epf.value)
                    else:
                        val_list = ", ".join(f'"{v}"' for v in epf.value)
                    filter_clauses.append(f"FILTER(?{var} NOT IN ({val_list}))")
                elif epf.operator == "has":
                    filter_clauses.append(f"?entity <{prop_uri}> <{epf.value}> .")
                elif epf.operator == "has_any" and isinstance(epf.value, list):
                    filter_clauses.append(f"?entity <{prop_uri}> ?{var} .")
                    val_list = ", ".join(f"<{v}>" for v in epf.value)
                    filter_clauses.append(f"FILTER(?{var} IN ({val_list}))")
                elif epf.operator == "has_all" and isinstance(epf.value, list):
                    for v in epf.value:
                        filter_clauses.append(f"?entity <{prop_uri}> <{v}> .")
                elif epf.operator == "not_has":
                    filter_clauses.append(
                        f"FILTER NOT EXISTS {{ ?entity <{prop_uri}> <{epf.value}> . }}")
                elif epf.operator == "not_has_any" and isinstance(epf.value, list):
                    val_list = ", ".join(f"<{v}>" for v in epf.value)
                    filter_clauses.append(
                        f"FILTER NOT EXISTS {{ ?entity <{prop_uri}> ?{var} . "
                        f"FILTER(?{var} IN ({val_list})) }}")
                elif epf.operator == "exists":
                    filter_clauses.append(f"?entity <{prop_uri}> ?{var} .")
                elif epf.operator == "not_exists":
                    filter_clauses.append(
                        f"FILTER NOT EXISTS {{ ?entity <{prop_uri}> ?{var} . }}")
        
        # Combine class clause with filters
        if filter_clauses:
            where_clauses = [class_clause] + filter_clauses
        else:
            where_clauses = [class_clause]
        
        # Add frame criteria filters (entity -> frame -> slot paths)
        # Each FrameCriteria represents a separate path from entity through frame to slots
        # Supports both flat (entity->frame->slot) and hierarchical (entity->parent->child->slot) structures
        if criteria.frame_criteria:
            for i, frame_criterion in enumerate(criteria.frame_criteria):
                self._validate_no_double_negation(frame_criterion)
                frame_var = f"frame_{i}"
                frame_edge_var = f"frame_edge_{i}"
                
                # Build entity -> frame path (mode-aware)
                if criteria.use_edge_pattern:
                    # Edge-based mode: Use Edge_hasEntityKGFrame
                    frame_clauses = [
                        f"?{frame_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .",
                        f"?{frame_edge_var} vital-core:hasEdgeSource ?entity .",
                        f"?{frame_edge_var} vital-core:hasEdgeDestination ?{frame_var} ."
                    ]
                else:
                    # Direct property mode: Use vg-direct:hasEntityFrame
                    frame_clauses = [
                        f"?entity vg-direct:hasEntityFrame ?{frame_var} ."
                    ]
                
                if frame_criterion.frame_type:
                    frame_clauses.append(f"?{frame_var} haley:hasKGFrameType <{frame_criterion.frame_type}> .")
                
                # Add slot criteria for this frame (frame -> slot paths)
                if frame_criterion.slot_criteria:
                    for j, slot_criterion in enumerate(frame_criterion.slot_criteria):
                        slot_var = f"slot_{i}_{j}"
                        slot_edge_var = f"slot_edge_{i}_{j}"
                        
                        if slot_criterion.comparator == "not_exists":
                            frame_clauses.append(self._build_negated_slot_pattern(
                                slot_var, slot_edge_var, frame_var, slot_criterion, criteria.use_edge_pattern))
                        elif slot_criterion.comparator == "is_empty":
                            # Slot connection is mandatory — slot must exist
                            if criteria.use_edge_pattern:
                                frame_clauses.extend([
                                    f"?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                                    f"?{slot_edge_var} vital-core:hasEdgeSource ?{frame_var} .",
                                    f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} ."
                                ])
                            else:
                                frame_clauses.append(f"?{frame_var} vg-direct:hasSlot ?{slot_var} .")
                            if slot_criterion.slot_type:
                                frame_clauses.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                            frame_clauses.append(self._build_empty_value_pattern(slot_var, slot_criterion, f"val_{i}_{j}"))
                        else:
                            # Build frame -> slot path (mode-aware)
                            if criteria.use_edge_pattern:
                                # Edge-based mode: Use Edge_hasKGSlot
                                frame_clauses.extend([
                                    f"?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                                    f"?{slot_edge_var} vital-core:hasEdgeSource ?{frame_var} .",
                                    f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} ."
                                ])
                            else:
                                # Direct property mode: Use vg-direct:hasSlot
                                frame_clauses.append(f"?{frame_var} vg-direct:hasSlot ?{slot_var} .")
                            
                            if slot_criterion.slot_type:
                                frame_clauses.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                            
                            if slot_criterion.value is not None and slot_criterion.comparator:
                                value_clause = self._build_value_filter(slot_var, slot_criterion.value, slot_criterion.comparator, slot_criterion.slot_class_uri, slot_criterion.slot_type, f"val_{i}_{j}")
                                frame_clauses.append(value_clause)
                            elif slot_criterion.comparator == "exists":
                                # Slot existence is already guaranteed by the edge/direct
                                # connection pattern above + optional slot_type filter.
                                # No extra triple needed — adding ?slot ?pred ?val would
                                # create a cross-product across all slot properties.
                                pass
                
                # Handle hierarchical frame structures (parent -> child frames)
                if frame_criterion.frame_criteria:
                    hierarchical_patterns = self._build_hierarchical_frame_patterns(
                        frame_var,
                        frame_criterion.frame_criteria,
                        str(i),
                        criteria.use_edge_pattern
                    )
                    frame_clauses.extend(hierarchical_patterns)
                
                # Wrap in FILTER NOT EXISTS if frame is negated
                if frame_criterion.negate:
                    where_clauses.append(f"FILTER NOT EXISTS {{ {' '.join(frame_clauses)} }}")
                else:
                    where_clauses.append(" ".join(frame_clauses))
        
        # Add standalone slot criteria filters (entity -> frame -> slot path without frame type filter)
        if criteria.slot_criteria:
            for i, slot_criterion in enumerate(criteria.slot_criteria):
                slot_var = f"slot_{i}"
                frame_var = f"frame_{i}"
                frame_edge_var = f"frame_edge_{i}"
                slot_edge_var = f"slot_edge_{i}"
                
                if slot_criterion.comparator == "not_exists":
                    # Negate entire entity->frame->slot path
                    inner = [
                        f"?{frame_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .",
                        f"?{frame_edge_var} vital-core:hasEdgeSource ?entity .",
                        f"?{frame_edge_var} vital-core:hasEdgeDestination ?{frame_var} .",
                        f"?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                        f"?{slot_edge_var} vital-core:hasEdgeSource ?{frame_var} .",
                        f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} ."
                    ]
                    if slot_criterion.slot_type:
                        inner.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                    if slot_criterion.value is not None:
                        self.logger.warning("not_exists comparator ignores the provided value — only checks slot presence")
                    where_clauses.append(f"FILTER NOT EXISTS {{ {' '.join(inner)} }}")
                elif slot_criterion.comparator == "is_empty":
                    # Slot connection mandatory, value check via OPTIONAL + !BOUND
                    slot_clauses = [
                        f"?{frame_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .",
                        f"?{frame_edge_var} vital-core:hasEdgeSource ?entity .",
                        f"?{frame_edge_var} vital-core:hasEdgeDestination ?{frame_var} .",
                        f"?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                        f"?{slot_edge_var} vital-core:hasEdgeSource ?{frame_var} .",
                        f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} ."
                    ]
                    if slot_criterion.slot_type:
                        slot_clauses.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                    slot_clauses.append(self._build_empty_value_pattern(slot_var, slot_criterion, f"val_entity_{i}"))
                    where_clauses.append(" ".join(slot_clauses))
                else:
                    # Build entity -> frame -> slot path
                    slot_clauses = [
                        f"?{frame_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .",
                        f"?{frame_edge_var} vital-core:hasEdgeSource ?entity .",
                        f"?{frame_edge_var} vital-core:hasEdgeDestination ?{frame_var} .",
                        f"?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                        f"?{slot_edge_var} vital-core:hasEdgeSource ?{frame_var} .",
                        f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} ."
                    ]
                    
                    if slot_criterion.slot_type:
                        slot_clauses.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                    
                    if slot_criterion.value is not None and slot_criterion.comparator:
                        value_clause = self._build_value_filter(slot_var, slot_criterion.value, slot_criterion.comparator, slot_criterion.slot_class_uri, slot_criterion.slot_type, f"val_entity_{i}")
                        slot_clauses.append(value_clause)
                    elif slot_criterion.comparator == "exists":
                        # Slot existence is already guaranteed by the edge/direct
                        # connection pattern above + optional slot_type filter.
                        pass
                    
                    where_clauses.append(" ".join(slot_clauses))
        
        # Build complete WHERE clause
        where_clause = " ".join(where_clauses)
        
        self.logger.debug(f"Built entity WHERE clause with {len(where_clauses)} conditions")
        return where_clause
    
    def build_entity_query_sparql(self, criteria: EntityQueryCriteria, graph_id: str, 
                                 page_size: int, offset: int) -> str:
        """Build SPARQL query for entity search with criteria.
        
        Args:
            criteria: Entity query criteria
            graph_id: Graph ID to search in
            page_size: Number of results per page
            offset: Offset for pagination
            
        Returns:
            SPARQL query string
        """
        where_clause = self._build_entity_where_clause(criteria)
        
        # Build sort bindings if sort_criteria provided
        sort_extra_where = ""
        select_extra = ""
        order_by = "ORDER BY ?entity"
        group_by = ""
        use_distinct = True
        if criteria.sort_criteria:
            sort_patterns, sort_vars, order_by_clause, requires_group_by = self._build_sort_bindings(
                criteria.sort_criteria, anchor_var="entity",
                use_edge_pattern=criteria.use_edge_pattern
            )
            if sort_patterns:
                sort_extra_where = " " + " ".join(sort_patterns)
                select_extra = " " + " ".join(sort_vars)
                order_by = order_by_clause
                if requires_group_by:
                    group_by = "GROUP BY ?entity"
                    use_distinct = False
        
        # Vector/geo criteria — BIND, FILTER, ORDER BY, LIMIT overrides
        vg_extra_where, vg_select, vg_order, vg_limit = self._build_vector_geo_clauses(
            criteria.vector_criteria, criteria.geo_criteria,
            multi_vector_criteria=criteria.multi_vector_criteria,
            anchor_var="entity")
        if vg_extra_where:
            sort_extra_where += " " + vg_extra_where
        if vg_select:
            select_extra += " " + vg_select
        if vg_order and not criteria.sort_criteria:
            order_by = vg_order
        if vg_limit is not None:
            page_size = vg_limit
            offset = 0
        
        select_keyword = "SELECT DISTINCT" if use_distinct else "SELECT"
        
        if graph_id is None:
            # Query default graph
            query = f"""
            {self.prefixes}
            {select_keyword} ?entity{select_extra} WHERE {{
                {where_clause}{sort_extra_where}
            }}
            {group_by}
            {order_by}
            LIMIT {page_size}
            OFFSET {offset}
            """
        else:
            # Query named graph
            query = f"""
            {self.prefixes}
            {select_keyword} ?entity{select_extra} WHERE {{
                GRAPH <{graph_id}> {{
                    {where_clause}{sort_extra_where}
                }}
            }}
            {group_by}
            {order_by}
            LIMIT {page_size}
            OFFSET {offset}
            """
        
        return query.strip()
    
    def build_entity_count_query_sparql(self, criteria: EntityQueryCriteria, graph_id: str) -> str:
        """Build SPARQL COUNT query for entity search with criteria.
        
        Uses the same full WHERE clause as ``build_entity_query_sparql``
        (including frame criteria, slot criteria, sort join patterns,
        and all filters) so the count is consistent with the paginated
        results.
        
        Args:
            criteria: Entity query criteria
            graph_id: Graph ID to search in
            
        Returns:
            SPARQL COUNT query string
        """
        where_clause = self._build_entity_where_clause(criteria)
        
        # Include sort join patterns so that entities lacking the sort
        # slot are excluded from the count (matching paginated query).
        sort_extra_where = ""
        if criteria.sort_criteria:
            sort_patterns, _sort_vars, _order_by, _requires_group_by = self._build_sort_bindings(
                criteria.sort_criteria, anchor_var="entity",
                use_edge_pattern=criteria.use_edge_pattern
            )
            if sort_patterns:
                sort_extra_where = " " + " ".join(sort_patterns)
        
        if graph_id is None:
            query = f"""
            {self.prefixes}
            
            SELECT (COUNT(DISTINCT ?entity) AS ?count) WHERE {{
                {where_clause}{sort_extra_where}
            }}
            """
        else:
            query = f"""
            {self.prefixes}
            
            SELECT (COUNT(DISTINCT ?entity) AS ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    {where_clause}{sort_extra_where}
                }}
            }}
            """
        
        return query.strip()
    
    def build_frame_query_sparql(self, criteria: FrameQueryCriteria, graph_id: str,
                                page_size: int, offset: int) -> str:
        """Build SPARQL query for frame search with criteria.
        
        Args:
            criteria: Frame query criteria
            graph_id: Graph ID to search in
            page_size: Number of results per page
            offset: Offset for pagination
            
        Returns:
            SPARQL query string
        """
        # Build WHERE clauses based on criteria
        where_clauses = ["?frame rdf:type haley:KGFrame ."]
        
        # Filter by specific frame type if provided
        if criteria.frame_type:
            where_clauses.append(f"?frame haley:hasKGFrameType <{criteria.frame_type}> .")
        
        # Add search string filter (search in hasName only)
        if criteria.search_string:
            where_clauses.append(f"""?frame vital-core:hasName ?search_name .
FILTER(CONTAINS(LCASE(?search_name), LCASE("{criteria.search_string}")))""")

        
        # Add entity type filter
        if criteria.entity_type:
            where_clauses.append(f"""
            ?entity haley:hasFrame ?frame .
            ?entity vital-core:vitaltype <{criteria.entity_type}> .
            """)
        
        # Add slot criteria filters
        if criteria.slot_criteria:
            for i, slot_criterion in enumerate(criteria.slot_criteria):
                slot_var = f"slot_{i}"
                
                if slot_criterion.comparator == "not_exists":
                    inner = [f"?{slot_var}_edge vital-core:hasEdgeSource ?frame . ?{slot_var}_edge vital-core:hasEdgeDestination ?{slot_var} ."]
                    if slot_criterion.slot_type:
                        inner.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                    if slot_criterion.value is not None:
                        self.logger.warning("not_exists comparator ignores the provided value — only checks slot presence")
                    where_clauses.append(f"FILTER NOT EXISTS {{ {' '.join(inner)} }}")
                elif slot_criterion.comparator == "is_empty":
                    slot_clauses = [f"?{slot_var}_edge vital-core:hasEdgeSource ?frame . ?{slot_var}_edge vital-core:hasEdgeDestination ?{slot_var} ."]
                    if slot_criterion.slot_type:
                        slot_clauses.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                    slot_clauses.append(self._build_empty_value_pattern(slot_var, slot_criterion, f"val_frame_{i}"))
                    where_clauses.append(" ".join(slot_clauses))
                else:
                    slot_clauses = [f"?{slot_var}_edge vital-core:hasEdgeSource ?frame . ?{slot_var}_edge vital-core:hasEdgeDestination ?{slot_var} ."]
                    
                    if slot_criterion.slot_type:
                        slot_clauses.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                    
                    if slot_criterion.value is not None and slot_criterion.comparator:
                        value_clause = self._build_value_filter(slot_var, slot_criterion.value, slot_criterion.comparator, slot_criterion.slot_class_uri, slot_criterion.slot_type, f"val_frame_{i}")
                        slot_clauses.append(value_clause)
                    elif slot_criterion.comparator == "exists":
                        slot_clauses.append(f"?{slot_var} ?slot_pred_{i} ?slot_val_{i} .")
                    
                    where_clauses.append(" ".join(slot_clauses))
        
        # Build complete query
        where_clause = " ".join(where_clauses)
        
        # Build sort bindings if sort_criteria provided
        sort_extra_where = ""
        select_extra = ""
        order_by = "ORDER BY ?frame"
        group_by = ""
        use_distinct = True
        if criteria.sort_criteria:
            sort_patterns, sort_vars, order_by_clause, requires_group_by = self._build_sort_bindings(
                criteria.sort_criteria, anchor_var="frame",
                use_edge_pattern=True
            )
            if sort_patterns:
                sort_extra_where = " " + " ".join(sort_patterns)
                select_extra = " " + " ".join(sort_vars)
                order_by = order_by_clause
                if requires_group_by:
                    group_by = "GROUP BY ?frame"
                    use_distinct = False
        
        select_keyword = "SELECT DISTINCT" if use_distinct else "SELECT"
        
        if graph_id is None:
            # Query default graph
            query = f"""
            {self.prefixes}
            {select_keyword} ?frame{select_extra} WHERE {{
                {where_clause}{sort_extra_where}
            }}
            {group_by}
            {order_by}
            LIMIT {page_size}
            OFFSET {offset}
            """
        else:
            # Query named graph
            query = f"""
            {self.prefixes}
            {select_keyword} ?frame{select_extra} WHERE {{
                GRAPH <{graph_id}> {{
                    {where_clause}{sort_extra_where}
                }}
            }}
            {group_by}
            {order_by}
            LIMIT {page_size}
            OFFSET {offset}
            """
        
        self.logger.debug(f"Built frame criteria query with {len(where_clauses)} conditions")
        return query.strip()
    
    def _get_slot_value_property(self, slot_class_uri: Optional[str] = None, slot_type: Optional[str] = None) -> str:
        """Get the correct slot value property based on slot class URI or slot type.
        
        Args:
            slot_class_uri: Slot class URI (full URI) - preferred
            slot_type: Slot type URI (full URI) - fallback for backward compatibility
            
        Returns:
            SPARQL property name for slot values
        """
        if slot_class_uri and slot_class_uri in _SLOT_CLASS_TO_VALUE_PROPERTY:
            return _SLOT_CLASS_TO_VALUE_PROPERTY[slot_class_uri]
        if slot_type and slot_type in _SLOT_CLASS_TO_VALUE_PROPERTY:
            return _SLOT_CLASS_TO_VALUE_PROPERTY[slot_type]
        # Default to text slot value
        return "haley:hasTextSlotValue"

    def _is_numeric_slot(self, slot_class_uri: Optional[str] = None, slot_type: Optional[str] = None) -> tuple[bool, str]:
        """Check if slot is numeric and return the XSD type.
        
        Returns:
            Tuple of (is_numeric, xsd_type)
        """
        for uri in (slot_class_uri, slot_type):
            if uri and uri in _NUMERIC_SLOT_CLASSES:
                return True, _NUMERIC_SLOT_CLASSES[uri]
        
        return False, ""

    def _validate_no_double_negation(self, frame_criterion) -> None:
        """Validate that a negated frame does not contain not_exists slot comparators.
        
        Raises:
            ValueError: If double negation is detected
        """
        if not frame_criterion.negate:
            return
        if frame_criterion.slot_criteria:
            for slot_criterion in frame_criterion.slot_criteria:
                if slot_criterion.comparator == "not_exists":
                    raise ValueError(
                        "Cannot use slot comparator 'not_exists' inside a negated frame criterion. "
                        "This would create double negation (universal quantification) which is not supported."
                    )
        if frame_criterion.frame_criteria:
            for child in frame_criterion.frame_criteria:
                if child.negate:
                    raise ValueError(
                        "Cannot nest a negated frame criterion inside another negated frame criterion. "
                        "Double negation is not supported."
                    )

    def _build_negated_slot_pattern(self, slot_var: str, slot_edge_var: str, frame_var: str,
                                     slot_criterion, use_edge_pattern: bool) -> str:
        """Build FILTER NOT EXISTS block for a slot that must not exist on the frame.
        
        Args:
            slot_var: Slot variable name
            slot_edge_var: Slot edge variable name
            frame_var: Parent frame variable name
            slot_criterion: SlotCriteria with slot_type
            use_edge_pattern: If True, use Edge_hasKGSlot; if False, use vg-direct:hasSlot
            
        Returns:
            SPARQL FILTER NOT EXISTS clause string
        """
        inner = []
        if use_edge_pattern:
            inner.extend([
                f"?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                f"?{slot_edge_var} vital-core:hasEdgeSource ?{frame_var} .",
                f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} ."
            ])
        else:
            inner.append(f"?{frame_var} vg-direct:hasSlot ?{slot_var} .")
        
        if slot_criterion.slot_type:
            inner.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
        else:
            self.logger.warning("not_exists comparator used without slot_type — negates existence of any slot")
        
        if slot_criterion.value is not None:
            self.logger.warning("not_exists comparator ignores the provided value — only checks slot presence")
        
        inner_str = " ".join(inner)
        return f"FILTER NOT EXISTS {{ {inner_str} }}"

    def _build_empty_value_pattern(self, slot_var: str, slot_criterion, value_var: str) -> str:
        """Build OPTIONAL + FILTER(!BOUND) pattern for a slot that exists but has no value.
        
        Args:
            slot_var: Slot variable name
            slot_criterion: SlotCriteria with optional slot_class_uri/slot_type
            value_var: Variable name prefix for value bindings
            
        Returns:
            SPARQL pattern string (OPTIONAL + FILTER)
        """
        if slot_criterion.value is not None:
            self.logger.warning("is_empty comparator ignores the provided value — checks absence of any value")
        
        # If slot_class_uri is known, check only that specific value property
        if slot_criterion.slot_class_uri or slot_criterion.slot_type:
            prop = self._get_slot_value_property(slot_criterion.slot_class_uri, slot_criterion.slot_type)
            return (
                f"OPTIONAL {{ ?{slot_var} {prop} ?{value_var} . }} "
                f"FILTER(!BOUND(?{value_var}))"
            )
        
        # No class URI — check all value properties
        all_props = [
            ("haley:hasTextSlotValue", f"{value_var}_text"),
            ("haley:hasDoubleSlotValue", f"{value_var}_num"),
            ("haley:hasIntegerSlotValue", f"{value_var}_int"),
            ("haley:hasBooleanSlotValue", f"{value_var}_bool"),
            ("haley:hasDateTimeSlotValue", f"{value_var}_dt"),
            ("haley:hasEntitySlotValue", f"{value_var}_ent"),
            ("haley:hasUriSlotValue", f"{value_var}_uri"),
        ]
        optionals = " ".join(
            f"OPTIONAL {{ ?{slot_var} {prop} ?{var} . }}" for prop, var in all_props
        )
        bounds = " && ".join(f"!BOUND(?{var})" for _, var in all_props)
        return f"{optionals} FILTER({bounds})"

    def _build_hierarchical_frame_patterns(self, parent_frame_var: str, frame_criteria_list: List, frame_index_prefix: str, use_edge_pattern: bool = True, depth: int = 0) -> List[str]:
        """Recursively build SPARQL patterns for hierarchical frame structures.
        
        Args:
            parent_frame_var: Variable name of the parent frame
            frame_criteria_list: List of FrameCriteria for child frames
            frame_index_prefix: Prefix for variable naming (e.g., "0_0" for nested indices)
            use_edge_pattern: If True, use Edge_hasKGFrame; if False, use vg-direct:hasFrame
            depth: Current depth in the hierarchy (for debugging)
            
        Returns:
            List of SPARQL pattern strings
        """
        patterns = []
        
        for i, frame_criterion in enumerate(frame_criteria_list):
            child_frame_var = f"frame_{frame_index_prefix}_{i}"
            child_frame_edge_var = f"frame_edge_{frame_index_prefix}_{i}"
            
            # Build parent frame -> child frame path (mode-aware)
            if use_edge_pattern:
                # Edge-based mode: Use Edge_hasKGFrame
                frame_patterns = [
                    f"?{child_frame_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame> .",
                    f"?{child_frame_edge_var} vital-core:hasEdgeSource ?{parent_frame_var} .",
                    f"?{child_frame_edge_var} vital-core:hasEdgeDestination ?{child_frame_var} ."
                ]
            else:
                # Direct property mode: Use vg-direct:hasFrame
                frame_patterns = [
                    f"?{parent_frame_var} vg-direct:hasFrame ?{child_frame_var} ."
                ]
            
            # Add frame type filter if specified
            if frame_criterion.frame_type:
                frame_patterns.append(f"?{child_frame_var} haley:hasKGFrameType <{frame_criterion.frame_type}> .")
            
            # Add slot criteria for this child frame
            if frame_criterion.slot_criteria:
                for j, slot_criterion in enumerate(frame_criterion.slot_criteria):
                    slot_var = f"slot_{frame_index_prefix}_{i}_{j}"
                    slot_edge_var = f"slot_edge_{frame_index_prefix}_{i}_{j}"
                    
                    if slot_criterion.comparator == "not_exists":
                        frame_patterns.append(self._build_negated_slot_pattern(
                            slot_var, slot_edge_var, child_frame_var, slot_criterion, use_edge_pattern))
                    elif slot_criterion.comparator == "is_empty":
                        if use_edge_pattern:
                            frame_patterns.extend([
                                f"?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                                f"?{slot_edge_var} vital-core:hasEdgeSource ?{child_frame_var} .",
                                f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} ."
                            ])
                        else:
                            frame_patterns.append(f"?{child_frame_var} vg-direct:hasSlot ?{slot_var} .")
                        if slot_criterion.slot_type:
                            frame_patterns.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                        frame_patterns.append(self._build_empty_value_pattern(slot_var, slot_criterion, f"val_{frame_index_prefix}_{i}_{j}"))
                    else:
                        # Build child frame -> slot path (mode-aware)
                        if use_edge_pattern:
                            # Edge-based mode: Use Edge_hasKGSlot
                            frame_patterns.extend([
                                f"?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                                f"?{slot_edge_var} vital-core:hasEdgeSource ?{child_frame_var} .",
                                f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} ."
                            ])
                        else:
                            # Direct property mode: Use vg-direct:hasSlot
                            frame_patterns.append(f"?{child_frame_var} vg-direct:hasSlot ?{slot_var} .")
                        
                        if slot_criterion.slot_type:
                            frame_patterns.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                        
                        if slot_criterion.value is not None and slot_criterion.comparator:
                            value_clause = self._build_value_filter(slot_var, slot_criterion.value, slot_criterion.comparator, slot_criterion.slot_class_uri, slot_criterion.slot_type, f"val_{frame_index_prefix}_{i}_{j}")
                            frame_patterns.append(value_clause)
                        elif slot_criterion.comparator == "exists":
                            # Slot existence is already guaranteed by the edge/direct
                            # connection pattern above + optional slot_type filter.
                            pass
            
            # Recursively process nested child frames
            if frame_criterion.frame_criteria:
                nested_patterns = self._build_hierarchical_frame_patterns(
                    child_frame_var,
                    frame_criterion.frame_criteria,
                    f"{frame_index_prefix}_{i}",
                    use_edge_pattern,
                    depth + 1
                )
                frame_patterns.extend(nested_patterns)
            
            # Wrap in FILTER NOT EXISTS if frame is negated
            if frame_criterion.negate:
                self._validate_no_double_negation(frame_criterion)
                patterns.append(f"FILTER NOT EXISTS {{ {' '.join(frame_patterns)} }}")
            else:
                patterns.extend(frame_patterns)
        
        return patterns
    
    def _build_sort_bindings(self, sort_criteria: List[SortCriteria],
                             anchor_var: str = "entity",
                             use_edge_pattern: bool = True) -> tuple[List[str], List[str], str, bool]:
        """Build SPARQL patterns for sort criteria by walking frame_path to the slot.
        
        Args:
            sort_criteria: List of sort criteria to apply
            anchor_var: The root variable to attach frames to (e.g. "entity", "frame",
                        "source_entity", "destination_entity")
            use_edge_pattern: If True, use Edge_hasEntityKGFrame / Edge_hasKGSlot / Edge_hasKGFrame
            
        Returns:
            Tuple of (where_patterns, select_vars, order_by_clause, requires_group_by)
              - where_patterns: SPARQL triple patterns to add to WHERE clause
              - select_vars: variables/expressions to add to SELECT (e.g. ["?sort_val_0"] or
                ["(MIN(?_sort_raw_0) AS ?sort_val_0)"])
              - order_by_clause: ORDER BY string (e.g. "ORDER BY DESC(?sort_val_0) ASC(?sort_val_1)")
              - requires_group_by: True if SELECT must use GROUP BY instead of DISTINCT
        """
        if not sort_criteria:
            return [], [], "", False
        
        # Sort by priority to ensure correct order
        sorted_criteria = sorted(sort_criteria, key=lambda x: x.priority)
        
        patterns = []
        select_vars = []
        order_terms = []
        requires_group_by = False
        
        for idx, sc in enumerate(sorted_criteria):
            sort_val_var = f"sort_val_{idx}"
            
            # entity_property: single triple on the anchor node
            if sc.sort_type == "entity_property":
                if not sc.property_uri:
                    raise ValueError("property_uri is required for entity_property sort_type")
                sort_datatype = _FILTERABLE_ENTITY_PROPERTIES.get(sc.property_uri)
                if sort_datatype == "uri_list":
                    raw_var = f"_sort_raw_{idx}"
                    agg_fn = "MAX" if sc.sort_order.lower() == "desc" else "MIN"
                    patterns.append(f"?{anchor_var} <{sc.property_uri}> ?{raw_var} .")
                    select_vars.append(f"({agg_fn}(?{raw_var}) AS ?{sort_val_var})")
                    requires_group_by = True
                else:
                    patterns.append(f"?{anchor_var} <{sc.property_uri}> ?{sort_val_var} .")
                    select_vars.append(f"?{sort_val_var}")
                if sc.sort_order.lower() == "desc":
                    order_terms.append(f"DESC(?{sort_val_var})")
                else:
                    order_terms.append(f"ASC(?{sort_val_var})")
                continue
            
            frame_path = sc.frame_path or []
            value_property = self._get_slot_value_property(slot_class_uri=sc.slot_class_uri)
            
            if not frame_path:
                # No frame path — slot is directly on the anchor (for frame_slot sort_type)
                slot_var = f"sort_slot_{idx}"
                slot_edge_var = f"sort_slot_edge_{idx}"
                if use_edge_pattern:
                    patterns.extend([
                        f"?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                        f"?{slot_edge_var} vital-core:hasEdgeSource ?{anchor_var} .",
                        f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} .",
                    ])
                else:
                    patterns.append(f"?{anchor_var} vg-direct:hasSlot ?{slot_var} .")
                patterns.append(f"?{slot_var} haley:hasKGSlotType <{sc.slot_type}> .")
                patterns.append(f"?{slot_var} {value_property} ?{sort_val_var} .")
            else:
                # Walk the frame path from anchor
                prev_var = anchor_var
                for depth, frame_type_uri in enumerate(frame_path):
                    frame_var = f"sort_frame_{idx}_{depth}"
                    frame_edge_var = f"sort_frame_edge_{idx}_{depth}"
                    
                    if depth == 0:
                        # First frame is attached to the anchor via Edge_hasEntityKGFrame
                        if use_edge_pattern:
                            patterns.extend([
                                f"?{frame_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .",
                                f"?{frame_edge_var} vital-core:hasEdgeSource ?{prev_var} .",
                                f"?{frame_edge_var} vital-core:hasEdgeDestination ?{frame_var} .",
                            ])
                        else:
                            patterns.append(f"?{prev_var} vg-direct:hasEntityFrame ?{frame_var} .")
                    else:
                        # Subsequent frames are child frames via Edge_hasKGFrame
                        if use_edge_pattern:
                            patterns.extend([
                                f"?{frame_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame> .",
                                f"?{frame_edge_var} vital-core:hasEdgeSource ?{prev_var} .",
                                f"?{frame_edge_var} vital-core:hasEdgeDestination ?{frame_var} .",
                            ])
                        else:
                            patterns.append(f"?{prev_var} vg-direct:hasFrame ?{frame_var} .")
                    
                    patterns.append(f"?{frame_var} haley:hasKGFrameType <{frame_type_uri}> .")
                    prev_var = frame_var
                
                # Now attach the slot to the last frame in the path
                slot_var = f"sort_slot_{idx}"
                slot_edge_var = f"sort_slot_edge_{idx}"
                if use_edge_pattern:
                    patterns.extend([
                        f"?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                        f"?{slot_edge_var} vital-core:hasEdgeSource ?{prev_var} .",
                        f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} .",
                    ])
                else:
                    patterns.append(f"?{prev_var} vg-direct:hasSlot ?{slot_var} .")
                patterns.append(f"?{slot_var} haley:hasKGSlotType <{sc.slot_type}> .")
                patterns.append(f"?{slot_var} {value_property} ?{sort_val_var} .")
            
            # Build ORDER BY term
            if sc.sort_order.lower() == "desc":
                order_terms.append(f"DESC(?{sort_val_var})")
            else:
                order_terms.append(f"ASC(?{sort_val_var})")
        
        # Add tiebreaker on anchor variable for deterministic pagination
        if order_terms:
            order_by_clause = f"ORDER BY {' '.join(order_terms)} ?{anchor_var}"
        else:
            order_by_clause = ""
        return patterns, select_vars, order_by_clause, requires_group_by
    
    def _format_slot_value(self, value: Any, slot_class_uri: Optional[str] = None, slot_type: Optional[str] = None) -> str:
        """Format a single value for use in SPARQL based on slot type.
        
        Returns the formatted SPARQL literal/URI string.
        """
        if isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, str):
            if (slot_class_uri in _URI_VALUE_SLOT_CLASSES) or (slot_type in _URI_VALUE_SLOT_CLASSES):
                return f'<{value}>'
            elif (slot_class_uri in _TEXT_SLOT_CLASSES) or (slot_type in _TEXT_SLOT_CLASSES):
                return f'"{value}"^^xsd:string'
            else:
                return f'"{value}"'
        else:
            return str(value)
    
    def _build_value_filter(self, var_name: str, value: Any, comparator: str, slot_class_uri: Optional[str] = None, slot_type: Optional[str] = None, value_var: str = "val") -> str:
        """Build SPARQL filter clause for value comparison.
        
        Args:
            var_name: Variable name to filter
            value: Value to compare against
            comparator: Comparison operator
            slot_class_uri: Slot class URI to determine correct property (preferred)
            slot_type: Slot type to determine correct property (fallback)
            
        Returns:
            SPARQL filter clause
        """
        # Get the correct property based on slot class URI or slot type
        property_name = self._get_slot_value_property(slot_class_uri, slot_type)
        
        # Format value based on slot type
        if isinstance(value, bool):
            # Boolean values must be lowercase in SPARQL
            escaped_value = "true" if value else "false"
        elif isinstance(value, str):
            # Check if this is a URI-valued slot class - use angle brackets for URI references
            is_uri_slot = (slot_class_uri in _URI_VALUE_SLOT_CLASSES) or (slot_type in _URI_VALUE_SLOT_CLASSES)
            if is_uri_slot:
                escaped_value = f'<{value}>'
            elif (slot_class_uri in _TEXT_SLOT_CLASSES) or (slot_type in _TEXT_SLOT_CLASSES):
                escaped_value = f'"{value}"^^xsd:string'
            else:
                escaped_value = f'"{value}"'
        else:
            escaped_value = str(value)
        
        if comparator == "eq":
            return f"?{var_name} {property_name} {escaped_value} ."
        elif comparator == "ne":
            return f"?{var_name} {property_name} ?{value_var} . FILTER(?{value_var} != {escaped_value})"
        elif comparator in ["gt", "greater_than"]:
            # Use XSD casting for numeric comparisons
            is_numeric, xsd_type = self._is_numeric_slot(slot_class_uri, slot_type)
            if is_numeric:
                return f"?{var_name} {property_name} ?{value_var} . FILTER({xsd_type}(?{value_var}) > {escaped_value})"
            else:
                return f"?{var_name} {property_name} ?{value_var} . FILTER(?{value_var} > {escaped_value})"
        elif comparator in ["lt", "less_than"]:
            # Use XSD casting for numeric comparisons on double and integer slots
            if slot_type == "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot":
                return f"?{var_name} {property_name} ?{value_var} . FILTER(xsd:double(?{value_var}) < {escaped_value})"
            elif slot_type == "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot":
                return f"?{var_name} {property_name} ?{value_var} . FILTER(xsd:integer(?{value_var}) < {escaped_value})"
            else:
                return f"?{var_name} {property_name} ?{value_var} . FILTER(?{value_var} < {escaped_value})"
        elif comparator in ["gte", "greater_than_or_equal"]:
            # Use XSD casting for numeric comparisons on double and integer slots
            if slot_type == "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot":
                return f"?{var_name} {property_name} ?{value_var} . FILTER(xsd:double(?{value_var}) >= {escaped_value})"
            elif slot_type == "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot":
                return f"?{var_name} {property_name} ?{value_var} . FILTER(xsd:integer(?{value_var}) >= {escaped_value})"
            else:
                return f"?{var_name} {property_name} ?{value_var} . FILTER(?{value_var} >= {escaped_value})"
        elif comparator in ["lte", "less_than_or_equal"]:
            # Use XSD casting for numeric comparisons on double and integer slots
            if slot_type == "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot":
                return f"?{var_name} {property_name} ?{value_var} . FILTER(xsd:double(?{value_var}) <= {escaped_value})"
            elif slot_type == "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot":
                return f"?{var_name} {property_name} ?{value_var} . FILTER(xsd:integer(?{value_var}) <= {escaped_value})"
            else:
                return f"?{var_name} {property_name} ?{value_var} . FILTER(?{value_var} <= {escaped_value})"
        elif comparator == "contains":
            return f"?{var_name} {property_name} ?{value_var} . FILTER(CONTAINS(LCASE(?{value_var}), LCASE({escaped_value})))"
        elif comparator == "has":
            return f"?{var_name} {property_name} {escaped_value} ."
        elif comparator == "has_any":
            if not isinstance(value, list):
                raise ValueError(f"value must be a list for comparator '{comparator}'")
            formatted = [self._format_slot_value(v, slot_class_uri, slot_type) for v in value]
            val_list = ", ".join(formatted)
            return f"?{var_name} {property_name} ?{value_var} . FILTER(?{value_var} IN ({val_list}))"
        elif comparator == "has_all":
            if not isinstance(value, list):
                raise ValueError(f"value must be a list for comparator '{comparator}'")
            parts = []
            for v in value:
                fv = self._format_slot_value(v, slot_class_uri, slot_type)
                parts.append(f"?{var_name} {property_name} {fv} .")
            return " ".join(parts)
        elif comparator == "not_has":
            return f"FILTER NOT EXISTS {{ ?{var_name} {property_name} {escaped_value} . }}"
        elif comparator == "not_has_any":
            if not isinstance(value, list):
                raise ValueError(f"value must be a list for comparator '{comparator}'")
            formatted = [self._format_slot_value(v, slot_class_uri, slot_type) for v in value]
            val_list = ", ".join(formatted)
            return f"FILTER NOT EXISTS {{ ?{var_name} {property_name} ?{value_var} . FILTER(?{value_var} IN ({val_list})) }}"
        else:
            self.logger.warning(f"Unknown comparator: {comparator}")
            return f"?{var_name} {property_name} {escaped_value} ."
    
    def _build_grouped_slot_criteria(self, slot_criteria, default_frame_type=None):
        """Build slot criteria grouped by frame type to share frame variables.
        
        Args:
            slot_criteria: List of slot criteria
            default_frame_type: Default frame type if not specified in criteria
            
        Returns:
            List of SPARQL clause strings
        """
        from collections import defaultdict
        
        # Group slot criteria by frame type
        frame_groups = defaultdict(list)
        
        for i, criterion in enumerate(slot_criteria):
            # Use criterion's frame type or default
            frame_type = getattr(criterion, 'frame_type', None) or default_frame_type
            frame_groups[frame_type].append((i, criterion))
        
        clauses = []
        
        for frame_type, criteria_list in frame_groups.items():
            # Use frame type as part of variable name for uniqueness
            frame_type_key = frame_type.split('#')[-1] if frame_type else 'default'
            frame_var = f"frame_{frame_type_key}"
            frame_edge_var = f"frame_edge_{frame_type_key}"
            
            # Build frame connection clauses
            frame_clauses = [
                f'?{frame_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .',
                f"?{frame_edge_var} vital-core:hasEdgeSource ?entity .",
                f"?{frame_edge_var} vital-core:hasEdgeDestination ?{frame_var} ."
            ]
            
            # Add frame type filter if specified
            if frame_type:
                frame_clauses.append(f"?{frame_var} haley:hasKGFrameType <{frame_type}> .")
            
            # Add slot criteria for this frame type
            for i, criterion in criteria_list:
                slot_var = f"slot_{frame_type_key}_{i}"
                slot_edge_var = f"slot_edge_{frame_type_key}_{i}"
                
                if criterion.comparator == "not_exists":
                    frame_clauses.append(self._build_negated_slot_pattern(
                        slot_var, slot_edge_var, frame_var, criterion, True))
                elif criterion.comparator == "is_empty":
                    frame_clauses.extend([
                        f'?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .',
                        f"?{slot_edge_var} vital-core:hasEdgeSource ?{frame_var} .",
                        f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} ."
                    ])
                    if criterion.slot_type:
                        frame_clauses.append(f"?{slot_var} haley:hasKGSlotType <{criterion.slot_type}> .")
                    frame_clauses.append(self._build_empty_value_pattern(slot_var, criterion, f"val_{slot_var}"))
                else:
                    # Add slot connection clauses
                    frame_clauses.extend([
                        f'?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .',
                        f"?{slot_edge_var} vital-core:hasEdgeSource ?{frame_var} .",
                        f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} ."
                    ])
                    
                    # Add slot type filter
                    if criterion.slot_type:
                        frame_clauses.append(f"?{slot_var} haley:hasKGSlotType <{criterion.slot_type}> .")
                    
                    # Add value filter
                    if criterion.value is not None and criterion.comparator:
                        value_clause = self._build_value_filter(slot_var, criterion.value, criterion.comparator, criterion.slot_class_uri, criterion.slot_type, f"val_{slot_var}")
                        frame_clauses.append(value_clause)
                    elif criterion.comparator == "exists":
                        frame_clauses.append(f"?{slot_var} ?slot_pred_{i} ?slot_val_{i} .")
            
            # Join all clauses for this frame type with proper formatting
            frame_block = "\n                ".join(frame_clauses)
            clauses.append(frame_block)
        
        return clauses
    
    def _build_vector_geo_clauses(
        self,
        vector_criteria: Optional[VectorCriteria],
        geo_criteria: Optional[GeoCriteria],
        multi_vector_criteria: Optional[MultiVectorCriteria] = None,
        anchor_var: str = "entity",
    ) -> tuple:
        """Build SPARQL clauses for vector/geo criteria.
        
        Returns:
            (extra_where, select_extra, order_by_override, limit_override)
            - extra_where: BIND/FILTER patterns to append to WHERE clause
            - select_extra: variables to add to SELECT (e.g. "?vg_score")
            - order_by_override: ORDER BY clause or "" if no override
            - limit_override: int LIMIT override or None
        """
        where_parts = []
        select_parts = []
        order_by = ""
        limit_override = None
        
        # Multi-vector similarity (takes precedence over single vector)
        if multi_vector_criteria and multi_vector_criteria.vectors:
            mvc = multi_vector_criteria
            score_var = mvc.score_variable
            
            # Determine function: multiVectorSimilarity vs multiVectorNearby
            # Use multiVectorNearby only if ALL inputs use pre-computed vectors
            all_nearby = all(v.vector is not None for v in mvc.vectors)
            func_name = "multiVectorNearby" if all_nearby else "multiVectorSimilarity"
            
            # Build argument list: ?entity, text1/vec1, idx1, w1, text2/vec2, idx2, w2, ...
            arg_parts = []
            for v in mvc.vectors:
                if v.vector:
                    escaped_val = v.vector.replace('"', '\\"')
                else:
                    escaped_val = (v.search_text or "").replace('"', '\\"')
                arg_parts.append(f'"{escaped_val}", "{v.index_name}", {v.weight}')
            
            args_str = ", ".join(arg_parts)
            where_parts.append(
                f'BIND(vg:{func_name}(?{anchor_var}, {args_str}) AS ?{score_var})')
            
            # INTERSECT semantics: exclude entities missing from any index
            # (their score is NULL from the SQL CTE)
            where_parts.append(f'FILTER(BOUND(?{score_var}))')
            
            # Threshold filter (additional)
            if mvc.min_score is not None:
                where_parts.append(f'FILTER(?{score_var} > {mvc.min_score})')
            
            select_parts.append(f"?{score_var}")
            order_by = f"ORDER BY DESC(?{score_var})"
            limit_override = mvc.top_k
        
        # Single vector similarity (only if multi-vector not used)
        elif vector_criteria:
            vc = vector_criteria
            score_var = vc.score_variable
            
            if vc.search_text:
                # Server-side vectorization: vg:vectorSimilarity
                escaped_text = vc.search_text.replace('"', '\\"')
                where_parts.append(
                    f'BIND(vg:vectorSimilarity(?{anchor_var}, "{escaped_text}", "{vc.index_name}") AS ?{score_var})')
            elif vc.vector:
                # Pre-computed vector: vg:vectorNearby
                where_parts.append(
                    f'BIND(vg:vectorNearby(?{anchor_var}, "{vc.vector}", "{vc.index_name}") AS ?{score_var})')
            
            # Threshold filter
            if vc.min_score is not None:
                where_parts.append(f'FILTER(?{score_var} > {vc.min_score})')
            
            select_parts.append(f"?{score_var}")
            order_by = f"ORDER BY DESC(?{score_var})"
            limit_override = vc.top_k
        
        # Geo proximity
        if geo_criteria:
            gc = geo_criteria
            dist_var = gc.distance_variable
            
            # Distance calculation
            where_parts.append(
                f'BIND(vg:geoDistance(?{anchor_var}, "{gc.latitude}"^^xsd:double, '
                f'"{gc.longitude}"^^xsd:double) AS ?{dist_var})')
            
            # Radius filter
            if gc.radius_m is not None:
                where_parts.append(
                    f'FILTER(vg:withinRadius(?{anchor_var}, "{gc.latitude}"^^xsd:double, '
                    f'"{gc.longitude}"^^xsd:double, "{gc.radius_m}"^^xsd:double))')
            
            select_parts.append(f"?{dist_var}")
            
            # Sort by distance (only if vector isn't also sorting)
            if gc.sort_by_distance and not vector_criteria and not multi_vector_criteria:
                order_by = f"ORDER BY ASC(?{dist_var})"
            
            if gc.top_k is not None and limit_override is None:
                limit_override = gc.top_k
        
        extra_where = " ".join(where_parts) if where_parts else ""
        select_extra = " ".join(select_parts) if select_parts else ""
        
        return extra_where, select_extra, order_by, limit_override

    def _get_property_uri(self, property_name: str) -> str:
        """Convert property name to full URI."""
        property_mappings = {
            "name": "http://vital.ai/ontology/vital-core#hasName",
            "label": "http://www.w3.org/2000/01/rdf-schema#label",
            "type": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            "title": "http://vital.ai/ontology/vital-core#title",
            "description": "http://vital.ai/ontology/vital-core#description"
        }
        return property_mappings.get(property_name, f"http://vital.ai/ontology/vital-core#{property_name}")
