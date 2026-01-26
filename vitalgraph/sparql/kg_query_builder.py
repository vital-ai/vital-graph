"""KG Query Builder

Builds SPARQL queries specifically for KG entity and frame operations,
including graph separation queries and criteria-based search queries.
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


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
    slot_criteria: Optional[List['SlotCriteria']] = None  # Slot criteria within this frame
    frame_criteria: Optional[List['FrameCriteria']] = None  # Nested frame criteria for hierarchical structures


@dataclass
class SlotCriteria:
    """Criteria for slot filtering in KG queries."""
    slot_type: Optional[str] = None
    slot_class_uri: Optional[str] = None  # Underlying slot class URI (e.g., KGTextSlot, KGDoubleSlot)
    value: Optional[Any] = None
    comparator: Optional[str] = None  # "eq", "gt", "lt", "gte", "lte", "contains", "ne", "exists"


@dataclass
class SortCriteria:
    """Criteria for sorting in KG queries."""
    sort_type: str  # "frame_slot" | "entity_frame_slot" | "property"
    slot_type: Optional[str] = None  # Slot type URI for sorting (required for frame_slot and entity_frame_slot)
    frame_type: Optional[str] = None  # Required for entity_frame_slot sorting
    property_uri: Optional[str] = None  # Property URI for property-based sorting
    sort_order: str = "asc"  # "asc" | "desc"
    priority: int = 1  # 1=primary, 2=secondary, 3=tertiary, etc.


@dataclass
class QueryFilter:
    """Simple property-based filter for entity queries."""
    property_name: str
    operator: str  # "equals", "not_equals", "contains", "exists", "gt", "lt", "gte", "lte"
    value: Optional[Any] = None


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
    use_edge_pattern: bool = True  # Use edge-based pattern (Edge_hasEntityKGFrame) vs direct property (hasFrame)


@dataclass
class FrameQueryCriteria:
    """Criteria for frame queries."""
    search_string: Optional[str] = None  # Search in frame name
    frame_type: Optional[str] = None     # Filter by frame type URI
    entity_type: Optional[str] = None    # Frames must belong to entity of this type
    slot_criteria: Optional[List[SlotCriteria]] = None  # Slot-based filtering
    sort_criteria: Optional[List[SortCriteria]] = None  # Multi-level sorting


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
            ?slot haley:kGFrameSlotFrame <{frame_uri}> .
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
                ?slot haley:kGFrameSlotFrame ?frame .
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
                ?slot haley:kGFrameSlotFrame <{frame_uri}> .
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
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        """
    
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
        # Build WHERE clauses - start with entity type selection
        entity_type_clause = """
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
        
        # Add search string filter (search in name/label)
        if criteria.search_string:
            filter_clauses.append(f"""{{
                ?entity rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?label), LCASE("{criteria.search_string}")))
            }} UNION {{
                ?entity vital-core:hasName ?name .
                FILTER(CONTAINS(LCASE(?name), LCASE("{criteria.search_string}")))
            }}""")
        
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
        
        # Combine entity type clause with filters
        if filter_clauses:
            where_clauses = [entity_type_clause] + filter_clauses
        else:
            where_clauses = [entity_type_clause]
        
        # Add frame criteria filters (entity -> frame -> slot paths)
        # Each FrameCriteria represents a separate path from entity through frame to slots
        # Supports both flat (entity->frame->slot) and hierarchical (entity->parent->child->slot) structures
        if criteria.frame_criteria:
            for i, frame_criterion in enumerate(criteria.frame_criteria):
                frame_var = f"frame_{i}"
                frame_edge_var = f"frame_edge_{i}"
                
                # Build entity -> frame path
                frame_clauses = [
                    f"?{frame_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .",
                    f"?{frame_edge_var} vital-core:hasEdgeSource ?entity .",
                    f"?{frame_edge_var} vital-core:hasEdgeDestination ?{frame_var} ."
                ]
                
                if frame_criterion.frame_type:
                    frame_clauses.append(f"?{frame_var} haley:hasKGFrameType <{frame_criterion.frame_type}> .")
                
                # Add slot criteria for this frame (frame -> slot paths)
                if frame_criterion.slot_criteria:
                    for j, slot_criterion in enumerate(frame_criterion.slot_criteria):
                        slot_var = f"slot_{i}_{j}"
                        slot_edge_var = f"slot_edge_{i}_{j}"
                        
                        # Build frame -> slot path
                        frame_clauses.extend([
                            f"?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                            f"?{slot_edge_var} vital-core:hasEdgeSource ?{frame_var} .",
                            f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} ."
                        ])
                        
                        if slot_criterion.slot_type:
                            frame_clauses.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                        
                        if slot_criterion.value is not None and slot_criterion.comparator:
                            value_clause = self._build_value_filter(slot_var, slot_criterion.value, slot_criterion.comparator, slot_criterion.slot_class_uri, slot_criterion.slot_type)
                            frame_clauses.append(value_clause)
                        elif slot_criterion.comparator == "exists":
                            frame_clauses.append(f"?{slot_var} ?slot_pred_{i}_{j} ?slot_val_{i}_{j} .")
                
                # Handle hierarchical frame structures (parent -> child frames)
                if frame_criterion.frame_criteria:
                    hierarchical_patterns = self._build_hierarchical_frame_patterns(
                        frame_var,
                        frame_criterion.frame_criteria,
                        str(i)
                    )
                    frame_clauses.extend(hierarchical_patterns)
                
                where_clauses.append(" ".join(frame_clauses))
        
        # Add standalone slot criteria filters (entity -> frame -> slot path without frame type filter)
        if criteria.slot_criteria:
            for i, slot_criterion in enumerate(criteria.slot_criteria):
                slot_var = f"slot_{i}"
                frame_var = f"frame_{i}"
                frame_edge_var = f"frame_edge_{i}"
                slot_edge_var = f"slot_edge_{i}"
                
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
                    value_clause = self._build_value_filter(slot_var, slot_criterion.value, slot_criterion.comparator, slot_criterion.slot_class_uri, slot_criterion.slot_type)
                    slot_clauses.append(value_clause)
                elif slot_criterion.comparator == "exists":
                    slot_clauses.append(f"?{slot_var} ?slot_pred_{i} ?slot_val_{i} .")
                
                where_clauses.append(" ".join(slot_clauses))
        
        # Build complete query
        where_clause = " ".join(where_clauses)
        
        if graph_id is None:
            # Query default graph
            query = f"""
            {self.prefixes}
            SELECT DISTINCT ?entity WHERE {{
                {where_clause}
            }}
            ORDER BY ?entity
            LIMIT {page_size}
            OFFSET {offset}
            """
        else:
            # Query named graph
            query = f"""
            {self.prefixes}
            SELECT DISTINCT ?entity WHERE {{
                GRAPH <{graph_id}> {{
                    {where_clause}
                }}
            }}
            ORDER BY ?entity
            LIMIT {page_size}
            OFFSET {offset}
            """
        
        self.logger.debug(f"Built entity criteria query with {len(where_clauses)} conditions")
        return query.strip()
    
    def build_entity_count_query_sparql(self, criteria: EntityQueryCriteria, graph_id: str) -> str:
        """Build SPARQL COUNT query for entity search with criteria.
        
        Args:
            criteria: Entity query criteria
            graph_id: Graph ID to search in
            
        Returns:
            SPARQL COUNT query string
        """
        # Build WHERE clauses using the same logic as the main query
        where_clauses = []
        
        # Entity type filter
        if criteria.entity_type:
            where_clauses.append(f"?entity a <{criteria.entity_type}> .")
        else:
            where_clauses.append("?entity a haley:KGEntity .")
        
        # Search string filter
        if criteria.search_string:
            where_clauses.append(f"""
            ?entity vital-core:hasName ?name .
            FILTER(CONTAINS(LCASE(?name), LCASE("{criteria.search_string}")))
            """)
        
        # Additional filters
        if criteria.filters:
            for filter_criteria in criteria.filters:
                if filter_criteria.property_name and filter_criteria.value:
                    property_uri = self._get_property_uri(filter_criteria.property_name)
                    if filter_criteria.operator == "equals":
                        where_clauses.append(f'?entity <{property_uri}> "{filter_criteria.value}" .')
                    elif filter_criteria.operator == "contains":
                        where_clauses.append(f"""
                        ?entity <{property_uri}> ?prop_value .
                        FILTER(CONTAINS(LCASE(?prop_value), LCASE("{filter_criteria.value}")))
                        """)
                    elif filter_criteria.operator == "not_empty":
                        where_clauses.append(f"""
                        ?entity <{property_uri}> ?prop_value .
                        FILTER(?prop_value != "")
                        """)
        
        # Build complete query
        where_clause = "\n            ".join(where_clauses)
        
        query = f"""
        {self.prefixes}
        
        SELECT (COUNT(DISTINCT ?entity) AS ?count) WHERE {{
            GRAPH <{graph_id}> {{
                {where_clause}
            }}
        }}
        """
        
        self.logger.debug(f"Built entity count query with {len(where_clauses)} conditions")
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
        
        # Frame type filtering is now handled via frame_criteria
        
        # Add search string filter
        if criteria.search_string:
            where_clauses.append(f"""
            {{
                ?frame rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?label), LCASE("{criteria.search_string}")))
            }} UNION {{
                ?frame vital-core:name ?name .
                FILTER(CONTAINS(LCASE(?name), LCASE("{criteria.search_string}")))
            }}
            """)
        
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
                
                slot_clauses = [f"?{slot_var} haley:kGFrameSlotFrame ?frame ."]
                
                if slot_criterion.slot_type:
                    slot_clauses.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                
                if slot_criterion.value is not None and slot_criterion.comparator:
                    value_clause = self._build_value_filter(slot_var, slot_criterion.value, slot_criterion.comparator, slot_criterion.slot_class_uri, slot_criterion.slot_type)
                    slot_clauses.append(value_clause)
                elif slot_criterion.comparator == "exists":
                    slot_clauses.append(f"?{slot_var} ?slot_pred_{i} ?slot_val_{i} .")
                
                where_clauses.append(" ".join(slot_clauses))
        
        # Build complete query
        where_clause = " ".join(where_clauses)
        
        if graph_id is None:
            # Query default graph
            query = f"""
            {self.prefixes}
            SELECT DISTINCT ?frame WHERE {{
                {where_clause}
            }}
            ORDER BY ?frame
            LIMIT {page_size}
            OFFSET {offset}
            """
        else:
            # Query named graph
            query = f"""
            {self.prefixes}
            SELECT DISTINCT ?frame WHERE {{
                GRAPH <{graph_id}> {{
                    {where_clause}
                }}
            }}
            ORDER BY ?frame
            LIMIT {page_size}
            OFFSET {offset}
            """
        
        self.logger.debug(f"Built frame criteria query with {len(where_clauses)} conditions")
        return query.strip()
    
    def _get_slot_value_property(self, slot_class_uri: str = None, slot_type: str = None) -> str:
        """Get the correct slot value property based on slot class URI or slot type.
        
        Args:
            slot_class_uri: Slot class URI (e.g., KGTextSlot, KGDoubleSlot) - preferred
            slot_type: Slot type URI - fallback for backward compatibility
            
        Returns:
            SPARQL property name for slot values
        """
        # Use slot_class_uri if provided (preferred)
        if slot_class_uri:
            if slot_class_uri.endswith("KGTextSlot"):
                return "haley:hasTextSlotValue"
            elif slot_class_uri.endswith("KGDoubleSlot"):
                return "haley:hasDoubleSlotValue"
            elif slot_class_uri.endswith("KGDateTimeSlot"):
                return "haley:hasDateTimeSlotValue"
            elif slot_class_uri.endswith("KGIntegerSlot"):
                return "haley:hasIntegerSlotValue"
            elif slot_class_uri.endswith("KGBooleanSlot"):
                return "haley:hasBooleanSlotValue"
            elif slot_class_uri.endswith("KGEntitySlot"):
                return "haley:hasEntitySlotValue"
            elif slot_class_uri.endswith("KGURISlot"):
                return "haley:hasUriSlotValue"
        
        # Fallback to slot_type for backward compatibility
        if slot_type:
            if slot_type == "http://vital.ai/ontology/haley-ai-kg#KGTextSlot":
                return "haley:hasTextSlotValue"
            elif slot_type == "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot":
                return "haley:hasDoubleSlotValue"
            elif slot_type == "http://vital.ai/ontology/haley-ai-kg#KGDateTimeSlot":
                return "haley:hasDateTimeSlotValue"
            elif slot_type == "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot":
                return "haley:hasIntegerSlotValue"
            elif slot_type == "http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot":
                return "haley:hasBooleanSlotValue"
            elif slot_type == "http://vital.ai/ontology/haley-ai-kg#KGEntitySlot":
                return "haley:hasEntitySlotValue"
            elif slot_type == "http://vital.ai/ontology/haley-ai-kg#KGURISlot":
                return "haley:hasUriSlotValue"
        
        # Default to text slot value
        return "haley:hasTextSlotValue"

    def _is_numeric_slot(self, slot_class_uri: str = None, slot_type: str = None) -> tuple[bool, str]:
        """Check if slot is numeric and return the XSD type.
        
        Returns:
            Tuple of (is_numeric, xsd_type)
        """
        # Check slot_class_uri first
        if slot_class_uri:
            if slot_class_uri.endswith("KGDoubleSlot"):
                return True, "xsd:double"
            elif slot_class_uri.endswith("KGIntegerSlot"):
                return True, "xsd:integer"
        
        # Fallback to slot_type
        if slot_type:
            if slot_type == "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot":
                return True, "xsd:double"
            elif slot_type == "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot":
                return True, "xsd:integer"
        
        return False, ""

    def _build_hierarchical_frame_patterns(self, parent_frame_var: str, frame_criteria_list: List, frame_index_prefix: str, depth: int = 0) -> List[str]:
        """Recursively build SPARQL patterns for hierarchical frame structures.
        
        Args:
            parent_frame_var: Variable name of the parent frame
            frame_criteria_list: List of FrameCriteria for child frames
            frame_index_prefix: Prefix for variable naming (e.g., "0_0" for nested indices)
            depth: Current depth in the hierarchy (for debugging)
            
        Returns:
            List of SPARQL pattern strings
        """
        patterns = []
        
        for i, frame_criterion in enumerate(frame_criteria_list):
            child_frame_var = f"frame_{frame_index_prefix}_{i}"
            child_frame_edge_var = f"frame_edge_{frame_index_prefix}_{i}"
            
            # Build parent frame -> child frame path
            frame_patterns = [
                f"?{child_frame_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame> .",
                f"?{child_frame_edge_var} vital-core:hasEdgeSource ?{parent_frame_var} .",
                f"?{child_frame_edge_var} vital-core:hasEdgeDestination ?{child_frame_var} ."
            ]
            
            # Add frame type filter if specified
            if frame_criterion.frame_type:
                frame_patterns.append(f"?{child_frame_var} haley:hasKGFrameType <{frame_criterion.frame_type}> .")
            
            # Add slot criteria for this child frame
            if frame_criterion.slot_criteria:
                for j, slot_criterion in enumerate(frame_criterion.slot_criteria):
                    slot_var = f"slot_{frame_index_prefix}_{i}_{j}"
                    slot_edge_var = f"slot_edge_{frame_index_prefix}_{i}_{j}"
                    
                    # Build child frame -> slot path
                    frame_patterns.extend([
                        f"?{slot_edge_var} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                        f"?{slot_edge_var} vital-core:hasEdgeSource ?{child_frame_var} .",
                        f"?{slot_edge_var} vital-core:hasEdgeDestination ?{slot_var} ."
                    ])
                    
                    if slot_criterion.slot_type:
                        frame_patterns.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                    
                    if slot_criterion.value is not None and slot_criterion.comparator:
                        value_clause = self._build_value_filter(slot_var, slot_criterion.value, slot_criterion.comparator, slot_criterion.slot_class_uri, slot_criterion.slot_type)
                        frame_patterns.append(value_clause)
                    elif slot_criterion.comparator == "exists":
                        frame_patterns.append(f"?{slot_var} ?slot_pred_{frame_index_prefix}_{i}_{j} ?slot_val_{frame_index_prefix}_{i}_{j} .")
            
            patterns.extend(frame_patterns)
            
            # Recursively process nested child frames
            if frame_criterion.frame_criteria:
                nested_patterns = self._build_hierarchical_frame_patterns(
                    child_frame_var,
                    frame_criterion.frame_criteria,
                    f"{frame_index_prefix}_{i}",
                    depth + 1
                )
                patterns.extend(nested_patterns)
        
        return patterns
    
    def _build_value_filter(self, var_name: str, value: Any, comparator: str, slot_class_uri: str = None, slot_type: str = None, value_var: str = "val") -> str:
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
            # Check if this is a URI slot or Entity slot - use angle brackets for URI references
            is_uri_slot = (slot_class_uri and (slot_class_uri.endswith("KGURISlot") or slot_class_uri.endswith("KGEntitySlot"))) or \
                         (slot_type == "http://vital.ai/ontology/haley-ai-kg#KGURISlot") or \
                         (slot_type == "http://vital.ai/ontology/haley-ai-kg#KGEntitySlot")
            if is_uri_slot:
                escaped_value = f'<{value}>'
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
    
    def build_entity_query_sparql_with_sorting(self, criteria: EntityQueryCriteria, graph_id: str,
                                             page_size: int, offset: int) -> str:
        """Build SPARQL query for entity search with criteria and sorting.
        
        Args:
            criteria: Entity query criteria (including sort_criteria)
            graph_id: Graph ID to search in
            page_size: Number of results per page
            offset: Offset for pagination
            
        Returns:
            SPARQL query string with ORDER BY clause
        """
        # Build WHERE clauses - start with entity type selection
        entity_type_clause = """
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
        sort_variables = []
        
        # Add entity type filter - use hasKGEntityType for specific entity types
        if criteria.entity_type and criteria.entity_type != "http://vital.ai/ontology/haley-ai-kg#KGEntity":
            filter_clauses.append(f"?entity haley:hasKGEntityType <{criteria.entity_type}> .")
        
        # Add search string filter
        if criteria.search_string:
            filter_clauses.append(f"""{{
                ?entity rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?label), LCASE("{criteria.search_string}")))
            }} UNION {{
                ?entity vital-core:hasName ?name .
                FILTER(CONTAINS(LCASE(?name), LCASE("{criteria.search_string}")))
            }}""")
        
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
        
        # Combine entity type clause with filters
        if filter_clauses:
            where_clauses = [entity_type_clause] + filter_clauses
        else:
            where_clauses = [entity_type_clause]
        
        # Slot criteria filtering is now handled via frame_criteria with nested slots
        # This method may need refactoring to use the new structure
        
        # Add sorting clauses and collect sort variables
        # For multi-frame queries, reuse existing slot variables for sorting
        if criteria.sort_criteria:
            # Map sort criteria to existing slot variables from slot_criteria
            for sort_criterion in criteria.sort_criteria:
                if sort_criterion.sort_type == "entity_frame_slot":
                    # Find matching slot criteria variable
                    found_matching_slot = False
                    for i, slot_criterion in enumerate(criteria.slot_criteria or []):
                        if (slot_criterion.frame_type == sort_criterion.frame_type and 
                            slot_criterion.slot_type == sort_criterion.slot_type):
                            # Use the same variable naming pattern as _build_grouped_slot_criteria
                            frame_type_key = sort_criterion.frame_type.split('#')[-1] if sort_criterion.frame_type else 'default'
                            sort_var = f"?val_slot_{frame_type_key}_{i}"
                            sort_variables.append(sort_var)
                            found_matching_slot = True
                            break
                    
                    # If no matching slot criteria found, we need to add the sort variable anyway
                    # This handles cases where we want to sort by a slot that's not used for filtering
                    if not found_matching_slot:
                        frame_type_key = sort_criterion.frame_type.split('#')[-1] if sort_criterion.frame_type else 'default'
                        # Use a unique index for sort-only variables
                        sort_index = len(criteria.slot_criteria or []) + len(sort_variables)
                        sort_var = f"?val_slot_{frame_type_key}_{sort_index}"
                        sort_variables.append(sort_var)
                        
                        # Add the necessary WHERE clauses for this sort variable
                        slot_type_key = sort_criterion.slot_type.split('#')[-1] if sort_criterion.slot_type else 'slot'
                        where_clauses.extend([
                            f"?frame_edge_{frame_type_key} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .",
                            f"?frame_edge_{frame_type_key} vital-core:hasEdgeSource ?entity .",
                            f"?frame_edge_{frame_type_key} vital-core:hasEdgeDestination ?frame_{frame_type_key} .",
                            f"?frame_{frame_type_key} haley:hasKGFrameType <{sort_criterion.frame_type}> .",
                            f"?slot_edge_{frame_type_key}_{sort_index} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                            f"?slot_edge_{frame_type_key}_{sort_index} vital-core:hasEdgeSource ?frame_{frame_type_key} .",
                            f"?slot_edge_{frame_type_key}_{sort_index} vital-core:hasEdgeDestination ?slot_{frame_type_key}_{sort_index} .",
                            f"?slot_{frame_type_key}_{sort_index} haley:hasKGSlotType <{sort_criterion.slot_type}> .",
                            f"?slot_{frame_type_key}_{sort_index} haley:hasDoubleSlotValue {sort_var} ."
                        ])
        
        # Build ORDER BY clause using the actual sort variables
        order_by_clause = self._generate_order_by_clause_with_variables(criteria.sort_criteria or [], sort_variables)
        
        # Build complete query - join clauses with proper spacing
        where_clause = "\n                ".join(where_clauses)
        
        # Build complete query with conditional GRAPH clause
        if graph_id is not None:
            query = f"""
        {self.prefixes}
        SELECT DISTINCT ?entity {' '.join(sort_variables)} WHERE {{
            GRAPH <{graph_id}> {{
                {where_clause}
            }}
        }}
        {order_by_clause}
        LIMIT {page_size}
        OFFSET {offset}
        """
        else:
            query = f"""
        {self.prefixes}
        SELECT DISTINCT ?entity {' '.join(sort_variables)} WHERE {{
            {where_clause}
        }}
        {order_by_clause}
        LIMIT {page_size}
        OFFSET {offset}
        """
        
        self.logger.debug(f"Built entity criteria query with sorting: {len(where_clauses)} conditions, {len(criteria.sort_criteria or [])} sort criteria")
        return query.strip()
    
    def build_frame_query_sparql_with_sorting(self, criteria: FrameQueryCriteria, graph_id: str,
                                            page_size: int, offset: int) -> str:
        """Build SPARQL query for frame search with criteria and sorting.
        
        Args:
            criteria: Frame query criteria (including sort_criteria)
            graph_id: Graph ID to search in
            page_size: Number of results per page
            offset: Offset for pagination
            
        Returns:
            SPARQL query string with ORDER BY clause
        """
        # Build WHERE clauses based on criteria (reuse existing logic)
        where_clauses = ["?frame rdf:type haley:KGFrame ."]
        sort_variables = []
        
        # Frame type filtering is now handled via frame_criteria
        
        # Add search string filter
        if criteria.search_string:
            where_clauses.append(f"""
            {{
                ?frame rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?label), LCASE("{criteria.search_string}")))
            }} UNION {{
                ?frame vital-core:name ?name .
                FILTER(CONTAINS(LCASE(?name), LCASE("{criteria.search_string}")))
            }}
            """)
        
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
                
                slot_clauses = [f"?{slot_var} haley:kGFrameSlotFrame ?frame ."]
                
                if slot_criterion.slot_type:
                    slot_clauses.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                
                if slot_criterion.value is not None and slot_criterion.comparator:
                    value_clause = self._build_value_filter(slot_var, slot_criterion.value, slot_criterion.comparator, slot_criterion.slot_class_uri, slot_criterion.slot_type)
                    slot_clauses.append(value_clause)
                elif slot_criterion.comparator == "exists":
                    slot_clauses.append(f"?{slot_var} ?slot_pred_{i} ?slot_val_{i} .")
                
                where_clauses.append(" ".join(slot_clauses))
        
        # Add sorting clauses and collect sort variables
        if criteria.sort_criteria:
            sort_clauses, sort_vars = self._build_frame_sorting_clauses(criteria.sort_criteria)
            where_clauses.extend(sort_clauses)
            sort_variables.extend(sort_vars)
        
        # Build complete query
        where_clause = " ".join(where_clauses)
        
        # Build ORDER BY clause
        order_by_clause = self._generate_order_by_clause(criteria.sort_criteria or [])
        
        if graph_id is None:
            # Query default graph
            query = f"""
            {self.prefixes}
            SELECT DISTINCT ?frame {' '.join(sort_variables)} WHERE {{
                {where_clause}
            }}
            {order_by_clause}
            LIMIT {page_size}
            OFFSET {offset}
            """
        else:
            # Query named graph
            query = f"""
            {self.prefixes}
            SELECT DISTINCT ?frame {' '.join(sort_variables)} WHERE {{
                GRAPH <{graph_id}> {{
                    {where_clause}
                }}
            }}
            {order_by_clause}
            
        Returns:
            Tuple of (where_clauses, sort_variables)
        """
        where_clauses = []
        sort_variables = []
        
        # Build a map of existing frame types and slot types to their variables
        existing_frames = {}
        existing_slots = {}
        if existing_slot_criteria:
            from collections import defaultdict
            frame_groups = defaultdict(list)
            
            for i, criterion in enumerate(existing_slot_criteria):
                frame_type = getattr(criterion, 'frame_type', None)
                if frame_type:
                    frame_groups[frame_type].append((i, criterion))
            
            for frame_type, criteria_list in frame_groups.items():
                frame_type_key = frame_type.split('#')[-1] if frame_type else 'default'
                existing_frames[frame_type] = f"frame_{frame_type_key}"
                
                # Also map slot types to their variables and value variables for reuse
                for i, criterion in criteria_list:
                    slot_type = getattr(criterion, 'slot_type', None)
                    if slot_type:
                        slot_key = f"{frame_type}#{slot_type}"
                        existing_slots[slot_key] = {
                            'slot_var': f"slot_{frame_type_key}_{i}",
                            'value_var': f"val_slot_{frame_type_key}_{i}"
                        }
        
        for i, sort_criterion in enumerate(sort_criteria):
            sort_var = f"sort_val_{i}"
            sort_variables.append(f"?{sort_var}")
            
            if sort_criterion.sort_type == "entity_frame_slot":
                # Check if we can reuse an existing slot variable (frame + slot type match)
                slot_key = f"{sort_criterion.frame_type}#{sort_criterion.slot_type}"
                if slot_key in existing_slots:
                    # Reuse existing slot and value variables completely - no new clauses needed!
                    slot_info = existing_slots[slot_key]
                    existing_value_var = slot_info['value_var']
                    
                    # Update the sort variable to point to the existing value variable
                    sort_variables[-1] = f"?{existing_value_var}"  # Replace the sort_val_i with existing value
                    clauses = []  # No additional clauses needed
                
                # Check if we can reuse an existing frame variable (but need new slot)
                elif sort_criterion.frame_type and sort_criterion.frame_type in existing_frames:
                    # Reuse existing frame variable
                    frame_var = existing_frames[sort_criterion.frame_type]
                    slot_var = f"sort_slot_{i}"
                    
                    # Only need slot connection clauses since frame already exists
                    clauses = [
                        f'?sort_slot_edge_{i} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .',
                        f"?sort_slot_edge_{i} vital-core:hasEdgeSource ?{frame_var} .",
                        f"?sort_slot_edge_{i} vital-core:hasEdgeDestination ?{slot_var} ."
                    ]
                    
                    if sort_criterion.slot_type:
                        clauses.append(f"?{slot_var} haley:hasKGSlotType <{sort_criterion.slot_type}> .")
                    
                    # Choose the correct property based on slot type
                    if sort_criterion.slot_type == "http://vital.ai/ontology/haley-ai-kg#KGTextSlot":
                        clauses.append(f"?{slot_var} haley:hasTextSlotValue ?{sort_var} .")
                    elif sort_criterion.slot_type == "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot":
                        clauses.append(f"?{slot_var} haley:hasDoubleSlotValue ?{sort_var} .")
                    elif sort_criterion.slot_type == "http://vital.ai/ontology/haley-ai-kg#KGDateTimeSlot":
                        clauses.append(f"?{slot_var} haley:hasDateTimeSlotValue ?{sort_var} .")
                    elif sort_criterion.slot_type == "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot":
                        clauses.append(f"?{slot_var} haley:hasIntegerSlotValue ?{sort_var} .")
                    elif sort_criterion.slot_type == "http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot":
                        clauses.append(f"?{slot_var} haley:hasBooleanSlotValue ?{sort_var} .")
                    else:
                        # Default to text slot value
                        clauses.append(f"?{slot_var} haley:hasTextSlotValue ?{sort_var} .")
                else:
                    # Create new frame variables
                    frame_var = f"sort_frame_{i}"
                    slot_var = f"sort_slot_{i}"
                    
                    clauses = [
                        f'?sort_frame_edge_{i} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .',
                        f"?sort_frame_edge_{i} vital-core:hasEdgeSource ?entity .",
                        f"?sort_frame_edge_{i} vital-core:hasEdgeDestination ?{frame_var} .",
                        f'?sort_slot_edge_{i} vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .',
                        f"?sort_slot_edge_{i} vital-core:hasEdgeSource ?{frame_var} .",
                        f"?sort_slot_edge_{i} vital-core:hasEdgeDestination ?{slot_var} ."
                    ]
                    
                    if sort_criterion.frame_type:
                        clauses.append(f"?{frame_var} haley:hasKGFrameType <{sort_criterion.frame_type}> .")
                    
                    if sort_criterion.slot_type:
                        clauses.append(f"?{slot_var} haley:hasKGSlotType <{sort_criterion.slot_type}> .")
                    
                    # Choose the correct property based on slot type
                    if sort_criterion.slot_type == "http://vital.ai/ontology/haley-ai-kg#KGTextSlot":
                        clauses.append(f"?{slot_var} haley:hasTextSlotValue ?{sort_var} .")
                    elif sort_criterion.slot_type == "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot":
                        clauses.append(f"?{slot_var} haley:hasDoubleSlotValue ?{sort_var} .")
                    elif sort_criterion.slot_type == "http://vital.ai/ontology/haley-ai-kg#KGDateTimeSlot":
                        clauses.append(f"?{slot_var} haley:hasDateTimeSlotValue ?{sort_var} .")
                    elif sort_criterion.slot_type == "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot":
                        clauses.append(f"?{slot_var} haley:hasIntegerSlotValue ?{sort_var} .")
                    elif sort_criterion.slot_type == "http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot":
                        clauses.append(f"?{slot_var} haley:hasBooleanSlotValue ?{sort_var} .")
                    else:
                        # Default to text slot value
                        clauses.append(f"?{slot_var} haley:hasTextSlotValue ?{sort_var} .")
                
                where_clauses.append(" ".join(clauses))
                
            elif sort_criterion.sort_type == "property":
                # Sort by direct property value
                if sort_criterion.property_uri:
                    where_clauses.append(f"?entity <{sort_criterion.property_uri}> ?{sort_var} .")
                
        return where_clauses, sort_variables
    
    def _build_frame_sorting_clauses(self, sort_criteria: List[SortCriteria]) -> tuple[List[str], List[str]]:
        """Build SPARQL clauses for frame sorting.
        
        Args:
            sort_criteria: List of sort criteria
            
        Returns:
            Tuple of (where_clauses, sort_variables)
        """
        where_clauses = []
        sort_variables = []
        
        for i, sort_criterion in enumerate(sort_criteria):
            sort_var = f"sort_val_{i}"
            sort_variables.append(f"?{sort_var}")
            
            if sort_criterion.sort_type == "frame_slot":
                # Sort by slot value in frame
                slot_var = f"sort_slot_{i}"
                
                clauses = [f"?{slot_var} haley:kGFrameSlotFrame ?frame ."]
                
                if sort_criterion.slot_type:
                    clauses.append(f"?{slot_var} haley:hasKGSlotType <{sort_criterion.slot_type}> .")
                
                clauses.append(f"?{slot_var} haley:hasTextSlotValue ?{sort_var} .")
                
                where_clauses.append(" ".join(clauses))
                
            elif sort_criterion.sort_type == "property":
                # Sort by direct property value
                if sort_criterion.property_uri:
                    where_clauses.append(f"?frame <{sort_criterion.property_uri}> ?{sort_var} .")
                
        return where_clauses, sort_variables
    
    def _generate_order_by_clause(self, sort_criteria: List[SortCriteria]) -> str:
        """Generate ORDER BY clause for multi-level sorting.
        
        Args:
            sort_criteria: List of sort criteria
            
        Returns:
            SPARQL ORDER BY clause
        """
        if not sort_criteria:
            return ""  # No ORDER BY if no sort criteria
        
        # Sort by priority to ensure correct order
        sorted_criteria = sorted(sort_criteria, key=lambda x: x.priority)
        
        order_terms = []
        for i, sort_criterion in enumerate(sorted_criteria):
            sort_var = f"sort_val_{i}"
            
            if sort_criterion.sort_order.lower() == "desc":
                order_terms.append(f"DESC(?{sort_var})")
            else:
                order_terms.append(f"ASC(?{sort_var})")
        
        if order_terms:
            return f"ORDER BY {' '.join(order_terms)}"
        else:
            return ""
    
    def _generate_order_by_clause_with_variables(self, sort_criteria: List[SortCriteria], sort_variables: List[str]) -> str:
        """Generate ORDER BY clause using actual variable names.
        
        Args:
            sort_criteria: List of sort criteria
            sort_variables: List of actual variable names (with ? prefix)
            
        Returns:
            SPARQL ORDER BY clause
        """
        if not sort_criteria or not sort_variables:
            return ""  # No ORDER BY if no sort criteria
        
        # Sort by priority to ensure correct order
        sorted_criteria = sorted(sort_criteria, key=lambda x: x.priority)
        
        order_terms = []
        for i, sort_criterion in enumerate(sorted_criteria):
            if i < len(sort_variables):
                sort_var = sort_variables[i]  # Already has ? prefix
                
                if sort_criterion.sort_order.lower() == "desc":
                    order_terms.append(f"DESC({sort_var})")
                else:
                    order_terms.append(f"ASC({sort_var})")
        
        if order_terms:
            return f"ORDER BY {' '.join(order_terms)}"
        else:
            return ""
    
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
