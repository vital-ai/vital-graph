#!/usr/bin/env python3
"""
KGFrame Query Processor Implementation

This module provides the KGFrameQueryProcessor class for handling
frame query and search operations.

Handles:
- Criteria-based frame search
- Frame type filtering
- Property-based filtering
- Pagination
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Common utilities
from vitalgraph.kg_impl.kg_backend_utils import (
    FusekiPostgreSQLBackendAdapter,
    BackendOperationResult
)


@dataclass
class FrameQueryResult:
    """Result of frame query operation."""
    success: bool
    frame_uris: List[str]
    total_count: int
    message: str
    error: Optional[str] = None


class KGFrameQueryProcessor:
    """
    Processor for frame query and search operations.
    
    Handles:
    - Criteria-based search
    - Frame type filtering
    - Property-based filtering
    - Pagination
    """
    
    def __init__(self):
        """Initialize the frame query processor."""
        self.logger = logging.getLogger(__name__)
        self.vitalsigns = VitalSigns()
    
    async def query_frames(
        self,
        backend_adapter: FusekiPostgreSQLBackendAdapter,
        space_id: str,
        graph_id: str,
        query_criteria: Dict[str, Any]
    ) -> FrameQueryResult:
        """
        Query frames using criteria-based search.
        
        Supports:
        - Frame type filtering
        - Entity association filtering
        - Property-based filtering
        - Pagination
        
        Args:
            backend_adapter: Backend adapter
            space_id: Space identifier
            graph_id: Graph identifier
            query_criteria: Query criteria dictionary
            
        Returns:
            FrameQueryResult with matching frame URIs
        """
        try:
            self.logger.info(f"Querying frames with criteria: {query_criteria}")
            
            # Build SPARQL query from criteria
            query = self._build_frame_query(query_criteria, graph_id)
            
            # Execute query
            results = await backend_adapter.execute_sparql_query(space_id, query)
            
            # Parse results
            frame_uris = self._parse_query_results(results)
            
            self.logger.info(f"Query returned {len(frame_uris)} frames")
            
            return FrameQueryResult(
                success=True,
                frame_uris=frame_uris,
                total_count=len(frame_uris),
                message=f"Query returned {len(frame_uris)} frames"
            )
            
        except Exception as e:
            self.logger.error(f"Frame query failed: {e}", exc_info=True)
            return FrameQueryResult(
                success=False,
                frame_uris=[],
                total_count=0,
                message=f"Query failed: {str(e)}",
                error=str(e)
            )
    
    def _build_frame_query(self, criteria: Dict[str, Any], graph_id: str) -> str:
        """
        Build SPARQL query from criteria.
        
        Args:
            criteria: Query criteria
            graph_id: Graph identifier
            
        Returns:
            SPARQL SELECT query
        """
        # Extract criteria
        frame_type = criteria.get('frame_type')
        entity_uri = criteria.get('entity_uri')
        parent_frame_uri = criteria.get('parent_frame_uri')
        properties = criteria.get('properties', {})
        page_size = criteria.get('page_size', 100)
        offset = criteria.get('offset', 0)
        
        # Build WHERE clause
        where_clauses = []
        
        # Frame type filter
        if frame_type:
            where_clauses.append(f"?frame <http://vital.ai/ontology/haley-ai-kg#hasKGFrameType> <{frame_type}> .")
        
        # Entity association filter
        if entity_uri:
            where_clauses.append(f"?frame <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> <{entity_uri}> .")
        
        # Parent frame filter
        if parent_frame_uri:
            where_clauses.append(f"""
                ?edge <http://vital.ai/ontology/vital-core#hasEdgeSource> <{parent_frame_uri}> .
                ?edge <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame> .
                ?edge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?frame .
            """)
        
        # Property filters
        for prop_uri, prop_value in properties.items():
            if isinstance(prop_value, str):
                where_clauses.append(f'?frame <{prop_uri}> "{prop_value}" .')
            else:
                where_clauses.append(f'?frame <{prop_uri}> {prop_value} .')
        
        # Build complete query
        where_clause = '\n                '.join(where_clauses) if where_clauses else '?frame ?p ?o .'
        
        query = f"""
        SELECT DISTINCT ?frame
        WHERE {{
            GRAPH <{graph_id}> {{
                ?frame <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://vital.ai/ontology/haley-ai-kg#KGFrame> .
                {where_clause}
            }}
        }}
        ORDER BY ?frame
        LIMIT {page_size}
        OFFSET {offset}
        """
        
        return query
    
    def _parse_query_results(self, results: Dict[str, Any]) -> List[str]:
        """
        Parse SPARQL query results to extract frame URIs.
        
        Args:
            results: SPARQL query results
            
        Returns:
            List of frame URIs
        """
        frame_uris = []
        
        try:
            if results and 'results' in results and 'bindings' in results['results']:
                bindings = results['results']['bindings']
                for binding in bindings:
                    if 'frame' in binding:
                        frame_uri = binding['frame'].get('value')
                        if frame_uri:
                            frame_uris.append(frame_uri)
        except Exception as e:
            self.logger.error(f"Failed to parse query results: {e}", exc_info=True)
        
        return frame_uris
