#!/usr/bin/env python3
"""
KGFrame Graph Processor Implementation

This module provides the KGFrameGraphProcessor class for handling
complete frame graph operations (retrieval and deletion).

Handles:
- Complete frame graph retrieval (frame + slots + edges)
- Frame graph deletion with cascade
- Child frame inclusion in graph operations
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Domain model imports
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot

# Common utilities
from vitalgraph.kg_impl.kg_backend_utils import (
    FusekiPostgreSQLBackendAdapter,
    BackendOperationResult
)


@dataclass
class FrameGraphResult:
    """Result of frame graph operation."""
    success: bool
    graph_objects: List[GraphObject]
    message: str
    error: Optional[str] = None


class KGFrameGraphProcessor:
    """
    Processor for frame graph operations.
    
    Handles:
    - Complete frame graph retrieval (frame + slots + edges)
    - Frame graph deletion with cascade
    - Child frame inclusion
    """
    
    def __init__(self):
        """Initialize the frame graph processor."""
        self.logger = logging.getLogger(__name__)
        self.vitalsigns = VitalSigns()
    
    async def get_frame_graph(
        self,
        backend_adapter: FusekiPostgreSQLBackendAdapter,
        space_id: str,
        graph_id: str,
        frame_uri: str
    ) -> FrameGraphResult:
        """
        Get complete graph for a frame including all connected objects.
        
        Returns:
        - Frame object
        - All immediate connected slots
        - All Edge_hasKGSlot relationships
        
        Note: Does NOT include child frames (which can have arbitrary depth).
        
        Args:
            backend_adapter: Backend adapter
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to get graph for
            
        Returns:
            FrameGraphResult with graph objects
        """
        try:
            self.logger.info(f"Getting frame graph for {frame_uri}")
            
            # Phase 1: Build SPARQL SELECT query to find all subject URIs in frame graph
            query = self._build_frame_graph_query(frame_uri, graph_id)
            
            # Execute query to get subject URIs
            results = await backend_adapter.execute_sparql_query(space_id, query)
            
            if not results:
                return FrameGraphResult(
                    success=False,
                    graph_objects=[],
                    message=f"Frame {frame_uri} not found",
                    error="Frame not found"
                )
            
            # Phase 2: Extract subject URIs from SELECT results
            subject_uris = []
            
            # Handle nested results structure: {'success': True, 'results': {'bindings': [...]}}
            bindings = []
            if isinstance(results, dict):
                if 'results' in results and 'bindings' in results['results']:
                    bindings = results['results']['bindings']
                elif 'bindings' in results:
                    bindings = results['bindings']
            elif isinstance(results, list):
                bindings = results
            
            for binding in bindings:
                if 'subject' in binding:
                    subject_uri = binding['subject'].get('value')
                    if subject_uri:
                        subject_uris.append(subject_uri)
            
            if not subject_uris:
                self.logger.warning("No subject URIs found in frame graph")
                return FrameGraphResult(
                    success=False,
                    graph_objects=[],
                    message=f"No objects found in frame graph for {frame_uri}",
                    error="No objects found"
                )
            
            self.logger.info(f"Found {len(subject_uris)} subjects in frame graph")
            
            # Phase 3: Fetch all objects by their URIs as VitalSigns objects
            
            # Use backend's database objects layer to get objects by URIs
            graph_objects = await backend_adapter.backend.db_objects.get_objects_by_uris(space_id, subject_uris, graph_id)
            
            if not graph_objects:
                self.logger.warning(f"No objects returned for frame graph")
                return FrameGraphResult(
                    success=False,
                    graph_objects=[],
                    message=f"No objects found for frame {frame_uri}",
                    error="No objects returned from backend"
                )
            
            self.logger.info(f"Retrieved frame graph with {len(graph_objects)} objects")
            
            return FrameGraphResult(
                success=True,
                graph_objects=graph_objects,
                message=f"Successfully retrieved frame graph with {len(graph_objects)} objects"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to get frame graph: {e}", exc_info=True)
            return FrameGraphResult(
                success=False,
                graph_objects=[],
                message=f"Failed to get frame graph: {str(e)}",
                error=str(e)
            )
    
    async def delete_frame_graph(
        self,
        backend_adapter: FusekiPostgreSQLBackendAdapter,
        space_id: str,
        graph_id: str,
        frame_uri: str
    ) -> bool:
        """
        Delete frame and all connected objects.
        
        Deletes:
        - Frame object
        - All connected slots
        - All Edge_hasKGSlot relationships
        - All Edge_hasKGFrame relationships (parent/child)
        
        Args:
            backend_adapter: Backend adapter
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to delete
            
        Returns:
            True if deletion succeeded, False otherwise
        """
        try:
            self.logger.info(f"Deleting frame graph for {frame_uri}")
            
            # Build SPARQL DELETE query for frame graph
            query = self._build_frame_graph_delete_query(frame_uri, graph_id)
            
            # Execute deletion
            await backend_adapter.execute_sparql_update(space_id, query)
            
            self.logger.info(f"Successfully deleted frame graph for {frame_uri}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to delete frame graph: {e}", exc_info=True)
            return False
    
    def _build_frame_graph_query(self, frame_uri: str, graph_id: str) -> str:
        """
        Build SPARQL query for complete frame graph.
        
        Uses frameGraphURI to find all objects belonging to this frame's graph.
        
        Args:
            frame_uri: Frame URI
            graph_id: Graph identifier
            
        Returns:
            SPARQL SELECT query to find all subjects in frame graph
        """
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?subject WHERE {{
            GRAPH <{graph_id}> {{
                # Get the frame itself
                {{ <{frame_uri}> ?p ?o . BIND(<{frame_uri}> AS ?subject) }}
                UNION
                # Get all objects that have hasFrameGraphURI pointing to this frame
                {{ ?subject haley:hasFrameGraphURI <{frame_uri}> . }}
            }}
        }}
        """
        return query
    
    def _build_frame_graph_delete_query(self, frame_uri: str, graph_id: str) -> str:
        """
        Build SPARQL DELETE query for complete frame graph.
        
        Args:
            frame_uri: Frame URI
            graph_id: Graph identifier
            
        Returns:
            SPARQL DELETE query
        """
        query = f"""
        DELETE {{
            GRAPH <{graph_id}> {{
                # Delete frame itself
                <{frame_uri}> ?framePred ?frameObj .
                
                # Delete slots
                ?slot ?slotPred ?slotObj .
                
                # Delete edges to slots
                ?edge ?edgePred ?edgeObj .
                
                # Delete child frames
                ?childFrame ?childFramePred ?childFrameObj .
                
                # Delete edges to child frames
                ?childEdge ?childEdgePred ?childEdgeObj .
            }}
        }}
        WHERE {{
            GRAPH <{graph_id}> {{
                # Frame properties
                <{frame_uri}> ?framePred ?frameObj .
                
                # Slots and edges
                OPTIONAL {{
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeSource> <{frame_uri}> .
                    ?edge <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?slot .
                    
                    ?slot ?slotPred ?slotObj .
                    ?edge ?edgePred ?edgeObj .
                }}
                
                # Child frames and edges
                OPTIONAL {{
                    ?childEdge <http://vital.ai/ontology/vital-core#hasEdgeSource> <{frame_uri}> .
                    ?childEdge <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame> .
                    ?childEdge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?childFrame .
                    
                    ?childFrame ?childFramePred ?childFrameObj .
                    ?childEdge ?childEdgePred ?childEdgeObj .
                }}
            }}
        }}
        """
        return query
    
    async def _convert_results_to_vitalsigns(self, results: List[Dict[str, Any]]) -> List[GraphObject]:
        """
        Convert SPARQL SELECT results to VitalSigns objects.
        
        The SELECT query returns subject URIs. We then fetch all triples for those subjects
        and convert them to VitalSigns objects.
        
        Args:
            results: SPARQL SELECT query results (list of bindings with 'subject' key)
            
        Returns:
            List of VitalSigns GraphObjects
        """
        try:
            if not results:
                return []
            
            # Extract subject URIs from SELECT results
            subject_uris = []
            for binding in results:
                if 'subject' in binding:
                    subject_uri = binding['subject'].get('value')
                    if subject_uri:
                        subject_uris.append(subject_uri)
            
            if not subject_uris:
                self.logger.warning("No subject URIs found in SELECT results")
                return []
            
            self.logger.info(f"Found {len(subject_uris)} subjects in frame graph")
            
            # For now, return empty list - the backend adapter should handle fetching triples
            # This will be implemented properly when we have the backend adapter method
            return []
            
        except Exception as e:
            self.logger.error(f"Failed to convert results to VitalSigns: {e}", exc_info=True)
            return []
