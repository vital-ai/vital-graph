"""KG Connection Query Builder

Builds SPARQL queries for entity-to-entity connection discovery.
Supports two distinct query types: relation-based and frame-based connections.
"""

import logging
from typing import Dict, List, Any, Optional
from vitalgraph.model.kgqueries_model import KGQueryCriteria
from vitalgraph.model.kgentities_model import EntityQueryCriteria, SlotCriteria

logger = logging.getLogger(__name__)


class KGConnectionQueryBuilder:
    """Builds SPARQL queries for entity connection discovery."""
    
    def __init__(self):
        """Initialize the connection query builder."""
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Ontology prefixes for KG operations
        self.prefixes = """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        """
    
    def build_relation_query(self, criteria: KGQueryCriteria, graph_id: str) -> str:
        """Build SPARQL query for relation-based entity connections."""
        self.logger.info("Building relation connection query")
        
        select_clause = "SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type"
        source_patterns = self._build_source_entity_patterns(criteria.source_entity_criteria, criteria.source_entity_uris)
        relation_patterns = self._build_relation_connection_patterns(criteria)
        dest_patterns = self._build_destination_entity_patterns(criteria.destination_entity_criteria, criteria.destination_entity_uris)
        
        # NEW: Add frame/slot filtering for source and destination entities
        source_frame_patterns = self._build_source_frame_patterns(criteria.source_frame_criteria) if criteria.source_frame_criteria else ""
        dest_frame_patterns = self._build_destination_frame_patterns(criteria.destination_frame_criteria) if criteria.destination_frame_criteria else ""
        
        filter_clause = self._build_relation_filter_clause(criteria)
        
        # Build WHERE clause with all patterns
        where_patterns = [source_patterns, relation_patterns, dest_patterns]
        if source_frame_patterns:
            where_patterns.append(source_frame_patterns)
        if dest_frame_patterns:
            where_patterns.append(dest_frame_patterns)
        where_patterns.append(filter_clause)
        
        where_clause = "\n                ".join(p for p in where_patterns if p)
        
        query = f"""
        {self.prefixes}
        {select_clause}
        WHERE {{
            GRAPH <{graph_id}> {{
                {where_clause}
            }}
        }}
        ORDER BY ?source_entity ?destination_entity
        """
        
        return query.strip()
    
    def build_frame_query(self, criteria: KGQueryCriteria, graph_id: str) -> str:
        """Build SPARQL query for frame-based entity connections."""
        self.logger.info("Building frame connection query")
        
        select_clause = "SELECT DISTINCT ?source_entity ?destination_entity ?shared_frame ?frame_type"
        source_patterns = self._build_source_entity_patterns(criteria.source_entity_criteria, criteria.source_entity_uris)
        frame_patterns = self._build_shared_frame_patterns(criteria)
        dest_patterns = self._build_destination_entity_patterns(criteria.destination_entity_criteria, criteria.destination_entity_uris)
        filter_clause = self._build_frame_filter_clause(criteria)
        
        query = f"""
        {self.prefixes}
        {select_clause}
        WHERE {{
            GRAPH <{graph_id}> {{
                {source_patterns}
                {frame_patterns}
                {dest_patterns}
                {filter_clause}
            }}
        }}
        ORDER BY ?source_entity ?destination_entity
        """
        
        return query.strip()
    
    # Helper methods for building SPARQL patterns
    
    def _build_source_entity_patterns(self, entity_criteria: Optional[EntityQueryCriteria], 
                                     entity_uris: Optional[List[str]]) -> str:
        """Build SPARQL patterns for source entity constraints."""
        patterns = ["?source_entity vital:vitaltype ?source_vitaltype ."]
        
        if entity_uris:
            uri_values = " ".join(f"<{uri}>" for uri in entity_uris)
            patterns.append(f"VALUES ?source_entity {{ {uri_values} }}")
        
        if entity_criteria and entity_criteria.entity_type:
            patterns.append("?source_entity vital:vitaltype ?source_type .")
            patterns.append(f"FILTER(?source_type = <{entity_criteria.entity_type}>)")
        
        if entity_criteria and entity_criteria.search_string:
            patterns.append("?source_entity vital:hasName ?source_name .")
            patterns.append(f"FILTER(CONTAINS(LCASE(?source_name), LCASE('{entity_criteria.search_string}')))")
        
        return "\n                ".join(patterns)
    
    def _build_destination_entity_patterns(self, entity_criteria: Optional[EntityQueryCriteria], 
                                          entity_uris: Optional[List[str]]) -> str:
        """Build SPARQL patterns for destination entity constraints."""
        patterns = ["?destination_entity vital:vitaltype ?dest_vitaltype ."]
        
        if entity_uris:
            uri_values = " ".join(f"<{uri}>" for uri in entity_uris)
            patterns.append(f"VALUES ?destination_entity {{ {uri_values} }}")
        
        if entity_criteria and entity_criteria.entity_type:
            patterns.append("?destination_entity vital:vitaltype ?dest_type .")
            patterns.append(f"FILTER(?dest_type = <{entity_criteria.entity_type}>)")
        
        if entity_criteria and entity_criteria.search_string:
            patterns.append("?destination_entity vital:hasName ?dest_name .")
            patterns.append(f"FILTER(CONTAINS(LCASE(?dest_name), LCASE('{entity_criteria.search_string}')))")
        
        return "\n                ".join(patterns)
    
    def _build_relation_connection_patterns(self, criteria: KGQueryCriteria) -> str:
        """Build SPARQL patterns for relation-based connections."""
        
        patterns = []
        
        # Basic relation pattern based on direction
        if criteria.direction == "outgoing":
            patterns.extend([
                "?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .",
                "?relation_edge vital:hasEdgeSource ?source_entity .",
                "?relation_edge vital:hasEdgeDestination ?destination_entity ."
            ])
        elif criteria.direction == "incoming":
            patterns.extend([
                "?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .",
                "?relation_edge vital:hasEdgeSource ?destination_entity .",
                "?relation_edge vital:hasEdgeDestination ?source_entity ."
            ])
        else:  # bidirectional
            patterns.extend([
                "?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .",
                "{ ?relation_edge vital:hasEdgeSource ?source_entity ; vital:hasEdgeDestination ?destination_entity . }",
                "UNION",
                "{ ?relation_edge vital:hasEdgeSource ?destination_entity ; vital:hasEdgeDestination ?source_entity . }"
            ])
        
        # Get relation type
        patterns.append("?relation_edge haley:hasKGRelationType ?relation_type .")
        
        # Relation type filtering
        if criteria.relation_type_uris:
            type_values = " ".join(f"<{uri}>" for uri in criteria.relation_type_uris)
            patterns.append(f"VALUES ?relation_type {{ {type_values} }}")
        
        return "\n                ".join(patterns)
    
    def _build_shared_frame_patterns(self, criteria: KGQueryCriteria) -> str:
        """Build SPARQL patterns for shared frame connections."""
        
        patterns = []
        
        # Entities connected via shared frames
        patterns.extend([
            # Source entity to frame
            "?source_frame_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .",
            "?source_frame_edge vital:hasEdgeSource ?source_entity .",
            "?source_frame_edge vital:hasEdgeDestination ?shared_frame .",
            
            # Destination entity to same frame
            "?dest_frame_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .",
            "?dest_frame_edge vital:hasEdgeSource ?destination_entity .",
            "?dest_frame_edge vital:hasEdgeDestination ?shared_frame .",
            
            # Get frame type
            "?shared_frame vital:vitaltype ?frame_type ."
        ])
        
        # Frame type filtering
        if criteria.shared_frame_types:
            type_values = " ".join(f"<{uri}>" for uri in criteria.shared_frame_types)
            patterns.append(f"VALUES ?frame_type {{ {type_values} }}")
        
        return "\n                ".join(patterns)
    
    def _build_relation_filter_clause(self, criteria: KGQueryCriteria) -> str:
        """Build FILTER clauses for relation queries."""
        filters = []
        
        if criteria.exclude_self_connections:
            filters.append("FILTER(?source_entity != ?destination_entity)")
        
        return "\n                ".join(filters)
    
    def _build_frame_filter_clause(self, criteria: KGQueryCriteria) -> str:
        """Build FILTER clauses for frame queries."""
        filters = []
        
        if criteria.exclude_self_connections:
            filters.append("FILTER(?source_entity != ?destination_entity)")
        
        return "\n                ".join(filters)
    
    def _build_source_frame_patterns(self, frame_criteria: List) -> str:
        """Build SPARQL patterns for source entity frame/slot filtering.
        
        Args:
            frame_criteria: List of FrameCriteria for source entity
            
        Returns:
            SPARQL pattern string
        """
        if not frame_criteria:
            return ""
        
        patterns = []
        
        for frame_idx, frame_criterion in enumerate(frame_criteria):
            frame_var = f"source_frame_{frame_idx}"
            frame_edge_var = f"source_frame_edge_{frame_idx}"
            
            # Entity to frame edge
            frame_patterns = [
                f"?{frame_edge_var} vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .",
                f"?{frame_edge_var} vital:hasEdgeSource ?source_entity .",
                f"?{frame_edge_var} vital:hasEdgeDestination ?{frame_var} ."
            ]
            
            # Frame type filter - use hasKGFrameType property
            if frame_criterion.frame_type:
                frame_patterns.append(f"?{frame_var} haley:hasKGFrameType <{frame_criterion.frame_type}> .")
            
            # Slot criteria
            if frame_criterion.slot_criteria:
                for slot_idx, slot_criterion in enumerate(frame_criterion.slot_criteria):
                    slot_var = f"source_slot_{frame_idx}_{slot_idx}"
                    slot_edge_var = f"source_slot_edge_{frame_idx}_{slot_idx}"
                    slot_value_var = f"source_slot_value_{frame_idx}_{slot_idx}"
                    
                    # Connect slot to frame via Edge_hasKGSlot edge
                    frame_patterns.extend([
                        f"?{slot_edge_var} vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                        f"?{slot_edge_var} vital:hasEdgeSource ?{frame_var} .",
                        f"?{slot_edge_var} vital:hasEdgeDestination ?{slot_var} ."
                    ])
                    
                    # Slot type filter
                    if slot_criterion.slot_type:
                        frame_patterns.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                    
                    # Slot value filter with comparator
                    if slot_criterion.value is not None and slot_criterion.comparator:
                        value_filter = self._build_slot_value_filter(
                            slot_var, slot_value_var, slot_criterion.value, 
                            slot_criterion.comparator, slot_criterion.slot_class_uri
                        )
                        frame_patterns.extend(value_filter)
            
            patterns.extend(frame_patterns)
        
        return "\n                ".join(patterns)
    
    def _build_destination_frame_patterns(self, frame_criteria: List) -> str:
        """Build SPARQL patterns for destination entity frame/slot filtering.
        
        Args:
            frame_criteria: List of FrameCriteria for destination entity
            
        Returns:
            SPARQL pattern string
        """
        if not frame_criteria:
            return ""
        
        patterns = []
        
        for frame_idx, frame_criterion in enumerate(frame_criteria):
            frame_var = f"dest_frame_{frame_idx}"
            frame_edge_var = f"dest_frame_edge_{frame_idx}"
            
            # Entity to frame edge
            frame_patterns = [
                f"?{frame_edge_var} vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .",
                f"?{frame_edge_var} vital:hasEdgeSource ?destination_entity .",
                f"?{frame_edge_var} vital:hasEdgeDestination ?{frame_var} ."
            ]
            
            # Frame type filter - use hasKGFrameType property
            if frame_criterion.frame_type:
                frame_patterns.append(f"?{frame_var} haley:hasKGFrameType <{frame_criterion.frame_type}> .")
            
            # Slot criteria
            if frame_criterion.slot_criteria:
                for slot_idx, slot_criterion in enumerate(frame_criterion.slot_criteria):
                    slot_var = f"dest_slot_{frame_idx}_{slot_idx}"
                    slot_edge_var = f"dest_slot_edge_{frame_idx}_{slot_idx}"
                    slot_value_var = f"dest_slot_value_{frame_idx}_{slot_idx}"
                    
                    # Connect slot to frame via Edge_hasKGSlot edge
                    frame_patterns.extend([
                        f"?{slot_edge_var} vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .",
                        f"?{slot_edge_var} vital:hasEdgeSource ?{frame_var} .",
                        f"?{slot_edge_var} vital:hasEdgeDestination ?{slot_var} ."
                    ])
                    
                    # Slot type filter
                    if slot_criterion.slot_type:
                        frame_patterns.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                    
                    # Slot value filter with comparator
                    if slot_criterion.value is not None and slot_criterion.comparator:
                        value_filter = self._build_slot_value_filter(
                            slot_var, slot_value_var, slot_criterion.value, 
                            slot_criterion.comparator, slot_criterion.slot_class_uri
                        )
                        frame_patterns.extend(value_filter)
            
            patterns.extend(frame_patterns)
        
        return "\n                ".join(patterns)
    
    def _build_slot_value_filter(self, slot_var: str, value_var: str, value: Any, 
                                 comparator: str, slot_class_uri: Optional[str] = None) -> List[str]:
        """Build SPARQL patterns for slot value filtering.
        
        Args:
            slot_var: Slot variable name
            value_var: Value variable name
            value: Value to compare
            comparator: Comparison operator (gt, lt, eq, gte, lte, contains, ne)
            slot_class_uri: Optional slot class URI to determine value property
            
        Returns:
            List of SPARQL pattern strings
        """
        patterns = []
        
        # Determine value property based on slot class or value type
        if slot_class_uri:
            if "TextSlot" in slot_class_uri:
                value_property = "haley:hasTextSlotValue"
            elif "IntegerSlot" in slot_class_uri or "LongSlot" in slot_class_uri:
                value_property = "haley:hasIntegerSlotValue"
            elif "DoubleSlot" in slot_class_uri or "FloatSlot" in slot_class_uri:
                value_property = "haley:hasDoubleSlotValue"
            elif "DateTimeSlot" in slot_class_uri:
                value_property = "haley:hasDateTimeSlotValue"
            elif "BooleanSlot" in slot_class_uri:
                value_property = "haley:hasBooleanSlotValue"
            else:
                value_property = "haley:hasTextSlotValue"  # Default
        else:
            # Infer from value type
            if isinstance(value, bool):
                value_property = "haley:hasBooleanSlotValue"
            elif isinstance(value, int):
                value_property = "haley:hasIntegerSlotValue"
            elif isinstance(value, float):
                value_property = "haley:hasDoubleSlotValue"
            else:
                value_property = "haley:hasTextSlotValue"
        
        # Get the value
        patterns.append(f"?{slot_var} {value_property} ?{value_var} .")
        
        # Build filter based on comparator
        if comparator == "eq":
            if isinstance(value, str):
                patterns.append(f"FILTER(?{value_var} = '{value}')")
            else:
                patterns.append(f"FILTER(?{value_var} = {value})")
        elif comparator == "ne":
            if isinstance(value, str):
                patterns.append(f"FILTER(?{value_var} != '{value}')")
            else:
                patterns.append(f"FILTER(?{value_var} != {value})")
        elif comparator == "gt":
            patterns.append(f"FILTER(?{value_var} > {value})")
        elif comparator == "lt":
            patterns.append(f"FILTER(?{value_var} < {value})")
        elif comparator == "gte":
            patterns.append(f"FILTER(?{value_var} >= {value})")
        elif comparator == "lte":
            patterns.append(f"FILTER(?{value_var} <= {value})")
        elif comparator == "contains":
            patterns.append(f"FILTER(CONTAINS(LCASE(?{value_var}), LCASE('{value}')))")
        
        return patterns
