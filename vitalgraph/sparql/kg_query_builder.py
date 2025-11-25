"""KG Query Builder

Builds SPARQL queries specifically for KG entity and frame operations,
including graph separation queries and criteria-based search queries.
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SlotCriteria:
    """Criteria for slot filtering in KG queries."""
    slot_type: Optional[str] = None
    value: Optional[Any] = None
    comparator: Optional[str] = None  # "eq", "gt", "lt", "gte", "lte", "contains", "ne", "exists"


@dataclass
class EntityQueryCriteria:
    """Criteria for entity queries."""
    search_string: Optional[str] = None  # Search in entity name
    entity_type: Optional[str] = None    # Filter by entity type URI
    frame_type: Optional[str] = None     # Entities must have frame of this type
    slot_criteria: Optional[List[SlotCriteria]] = None  # Slot-based filtering


@dataclass
class FrameQueryCriteria:
    """Criteria for frame queries."""
    search_string: Optional[str] = None  # Search in frame name
    frame_type: Optional[str] = None     # Filter by frame type URI
    entity_type: Optional[str] = None    # Frames must belong to entity of this type
    slot_criteria: Optional[List[SlotCriteria]] = None  # Slot-based filtering


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
        """
    
    def build_entity_discovery_query(self) -> str:
        """Build query to discover all KGEntity subjects.
        
        Returns:
            SPARQL query string to find all KGEntity subjects
        """
        query = f"""
        {self.prefixes}
        SELECT DISTINCT ?entity WHERE {{
            ?entity rdf:type haley:KGEntity .
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
        # Build WHERE clauses based on criteria
        where_clauses = ["?entity rdf:type haley:KGEntity ."]
        
        # Add entity type filter
        if criteria.entity_type:
            where_clauses.append(f"?entity vital-core:vitaltype <{criteria.entity_type}> .")
        
        # Add search string filter (search in name/label)
        if criteria.search_string:
            where_clauses.append(f"""
            {{
                ?entity rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?label), LCASE("{criteria.search_string}")))
            }} UNION {{
                ?entity vital-core:name ?name .
                FILTER(CONTAINS(LCASE(?name), LCASE("{criteria.search_string}")))
            }}
            """)
        
        # Add frame type filter
        if criteria.frame_type:
            where_clauses.append(f"""
            ?entity haley:hasFrame ?frame .
            ?frame vital-core:vitaltype <{criteria.frame_type}> .
            """)
        
        # Add slot criteria filters
        if criteria.slot_criteria:
            for i, slot_criterion in enumerate(criteria.slot_criteria):
                slot_var = f"slot_{i}"
                frame_var = f"frame_{i}"
                
                slot_clauses = [
                    f"?entity haley:hasFrame ?{frame_var} .",
                    f"?{slot_var} haley:kGFrameSlotFrame ?{frame_var} ."
                ]
                
                if slot_criterion.slot_type:
                    slot_clauses.append(f"?{slot_var} vital-core:vitaltype <{slot_criterion.slot_type}> .")
                
                if slot_criterion.value is not None and slot_criterion.comparator:
                    value_clause = self._build_value_filter(slot_var, slot_criterion.value, slot_criterion.comparator)
                    slot_clauses.append(value_clause)
                elif slot_criterion.comparator == "exists":
                    slot_clauses.append(f"?{slot_var} ?slot_pred_{i} ?slot_val_{i} .")
                
                where_clauses.append(" ".join(slot_clauses))
        
        # Build complete query
        where_clause = " ".join(where_clauses)
        
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
        
        # Add frame type filter
        if criteria.frame_type:
            where_clauses.append(f"?frame vital-core:vitaltype <{criteria.frame_type}> .")
        
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
                    slot_clauses.append(f"?{slot_var} vital-core:vitaltype <{slot_criterion.slot_type}> .")
                
                if slot_criterion.value is not None and slot_criterion.comparator:
                    value_clause = self._build_value_filter(slot_var, slot_criterion.value, slot_criterion.comparator)
                    slot_clauses.append(value_clause)
                elif slot_criterion.comparator == "exists":
                    slot_clauses.append(f"?{slot_var} ?slot_pred_{i} ?slot_val_{i} .")
                
                where_clauses.append(" ".join(slot_clauses))
        
        # Build complete query
        where_clause = " ".join(where_clauses)
        
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
    
    def _build_value_filter(self, var_name: str, value: Any, comparator: str) -> str:
        """Build SPARQL filter clause for value comparison.
        
        Args:
            var_name: Variable name to filter
            value: Value to compare against
            comparator: Comparison operator
            
        Returns:
            SPARQL filter clause
        """
        # Escape string values
        if isinstance(value, str):
            escaped_value = f'"{value}"'
        else:
            escaped_value = str(value)
        
        if comparator == "eq":
            return f"?{var_name} vital-core:value {escaped_value} ."
        elif comparator == "ne":
            return f"?{var_name} vital-core:value ?val . FILTER(?val != {escaped_value})"
        elif comparator == "gt":
            return f"?{var_name} vital-core:value ?val . FILTER(?val > {escaped_value})"
        elif comparator == "lt":
            return f"?{var_name} vital-core:value ?val . FILTER(?val < {escaped_value})"
        elif comparator == "gte":
            return f"?{var_name} vital-core:value ?val . FILTER(?val >= {escaped_value})"
        elif comparator == "lte":
            return f"?{var_name} vital-core:value ?val . FILTER(?val <= {escaped_value})"
        elif comparator == "contains":
            return f"?{var_name} vital-core:value ?val . FILTER(CONTAINS(LCASE(?val), LCASE({escaped_value})))"
        else:
            self.logger.warning(f"Unknown comparator: {comparator}")
            return f"?{var_name} vital-core:value {escaped_value} ."
