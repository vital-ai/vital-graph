#!/usr/bin/env python3
"""
KGEntity Hierarchical Frame Processor Implementation

This module provides the KGEntityHierarchicalFrameProcessor class for handling
hierarchical frame operations within the KGEntities context.

Handles parent frame validation, connection edge creation, and grouping URI management
for hierarchical frame structures using parent_frame_uri parameter.
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Domain model imports
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame

# Backend adapter import
from vitalgraph.kg_impl.kg_backend_utils import FusekiPostgreSQLBackendAdapter


@dataclass
class HierarchicalFrameResult:
    """Result of hierarchical frame operation."""
    success: bool
    created_connection_edges: List[str]
    processed_frame_uris: List[str]
    validation_results: Dict[str, Any]
    message: str
    error: Optional[str] = None


class KGEntityHierarchicalFrameProcessor:
    """
    Processor for hierarchical frame operations within KGEntity context.
    
    Handles parent frame validation, connection edge creation, and proper
    grouping URI management for hierarchical frame structures.
    """
    
    def __init__(self, backend: FusekiPostgreSQLBackendAdapter, logger: logging.Logger):
        """
        Initialize the hierarchical frame processor.
        
        Args:
            backend: Backend adapter for SPARQL operations
            logger: Logger instance
        """
        self.backend = backend
        self.logger = logger
        self.vs = VitalSigns()
    
    async def validate_parent_frame(self, space_id: str, graph_id: str, entity_uri: str, parent_frame_uri: str) -> bool:
        """
        Validate that parent_frame_uri exists and belongs to the specified entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI that should own the parent frame
            parent_frame_uri: Parent frame URI to validate
            
        Returns:
            bool: True if parent frame is valid, False otherwise
        """
        from .kg_validation_utils import KGHierarchicalFrameValidator
        
        validator = KGHierarchicalFrameValidator(self.backend, self.logger)
        return await validator.validate_parent_frame(space_id, graph_id, entity_uri, parent_frame_uri)
    
    def create_connection_edges(self, entity_uri: str, frame_objects: List[GraphObject], parent_frame_uri: Optional[str] = None) -> List[GraphObject]:
        """
        Create appropriate connection edges for hierarchical frame operations.
        
        Args:
            entity_uri: Entity URI that owns the frames
            frame_objects: List of frame objects to create connections for
            parent_frame_uri: Optional parent frame URI for hierarchical connections
            
        Returns:
            List[GraphObject]: List of connection edge objects
        """
        connection_edges = []
        
        for graph_obj in frame_objects:
            if isinstance(graph_obj, KGFrame):
                frame_uri = graph_obj.URI
                
                if parent_frame_uri:
                    # Create Edge_hasKGFrame for parent-child frame relationship
                    parent_child_edge = Edge_hasKGFrame()
                    parent_child_edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGFrame/{parent_frame_uri.split('/')[-1]}_{frame_uri.split('/')[-1]}_edge"
                    parent_child_edge.edgeSource = parent_frame_uri
                    parent_child_edge.edgeDestination = frame_uri
                    parent_child_edge.kGGraphURI = entity_uri  # Edge belongs to entity graph
                    # Note: parent_child_edge does NOT have frameGraphURI (connecting edge)
                    
                    connection_edges.append(parent_child_edge)
                    self.logger.info(f"Created parent-child frame edge: {parent_frame_uri} → {frame_uri}")
                else:
                    # Create Edge_hasEntityKGFrame for entity-frame relationship (root frames)
                    entity_frame_edge = Edge_hasEntityKGFrame()
                    entity_frame_edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasEntityKGFrame/{entity_uri.split('/')[-1]}_{frame_uri.split('/')[-1]}_edge"
                    entity_frame_edge.edgeSource = entity_uri
                    entity_frame_edge.edgeDestination = frame_uri
                    entity_frame_edge.kGGraphURI = entity_uri  # Edge belongs to entity graph
                    # Note: entity_frame_edge does NOT have frameGraphURI (connecting edge)
                    
                    connection_edges.append(entity_frame_edge)
                    self.logger.info(f"Created entity-frame edge: {entity_uri} → {frame_uri}")
        
        return connection_edges
    
    def apply_hierarchical_grouping_uris(self, entity_uri: str, graph_objects: List[GraphObject]) -> List[GraphObject]:
        """
        Apply proper grouping URI management for hierarchical frame structures.
        
        Args:
            entity_uri: Entity URI for kGGraphURI assignment
            graph_objects: List of graph objects to process
            
        Returns:
            List[GraphObject]: Processed graph objects with proper grouping URIs
        """
        processed_objects = []
        
        for graph_obj in graph_objects:
            if isinstance(graph_obj, KGFrame):
                frame_uri = graph_obj.URI
                if frame_uri:
                    # Set grouping URI properties for hierarchical frames
                    # 1. Set frameGraphURI - groups all objects within this frame
                    graph_obj.frameGraphURI = frame_uri
                    
                    # 2. Set kGGraphURI - groups all objects within the entity's complete graph
                    graph_obj.kGGraphURI = entity_uri
                    
                    self.logger.info(f"Applied hierarchical grouping URIs for frame {frame_uri}: frameGraphURI={frame_uri}, kgGraphURI={entity_uri}")
                    
                processed_objects.append(graph_obj)
            else:
                # Handle other graph objects (slots, edges, properties, etc.)
                if hasattr(graph_obj, 'URI') and graph_obj.URI:
                    # Set kGGraphURI for entity-level grouping
                    graph_obj.kGGraphURI = entity_uri
                    
                processed_objects.append(graph_obj)
        
        return processed_objects
    
    def determine_affected_frames(self, edge: GraphObject, frame_uris: List[str]) -> List[str]:
        """
        Determine which frames are affected by a connecting edge.
        
        Args:
            edge: Connection edge object
            frame_uris: List of frame URIs to check against
            
        Returns:
            List[str]: List of affected frame URIs
        """
        affected_frames = []
        
        # Check if edge connects to any of the frames
        if hasattr(edge, 'edgeSource'):
            edge_source = str(edge.edgeSource)
            if edge_source in frame_uris:
                affected_frames.append(edge_source)
        
        if hasattr(edge, 'edgeDestination'):
            edge_dest = str(edge.edgeDestination)
            if edge_dest in frame_uris:
                affected_frames.append(edge_dest)
        
        return affected_frames
    
    async def process_hierarchical_frame_operation(self, space_id: str, graph_id: str, entity_uri: str, 
                                                 frame_objects: List[GraphObject], parent_frame_uri: Optional[str] = None) -> HierarchicalFrameResult:
        """
        Process a complete hierarchical frame operation.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI that owns the frames
            frame_objects: List of frame objects to process
            parent_frame_uri: Optional parent frame URI for hierarchical connections
            
        Returns:
            HierarchicalFrameResult: Result of the hierarchical frame operation
        """
        try:
            # Step 1: Validate parent frame if provided
            if parent_frame_uri:
                parent_valid = await self.validate_parent_frame(space_id, graph_id, entity_uri, parent_frame_uri)
                if not parent_valid:
                    return HierarchicalFrameResult(
                        success=False,
                        created_connection_edges=[],
                        processed_frame_uris=[],
                        validation_results={"parent_frame_valid": False},
                        message=f"Parent frame validation failed: {parent_frame_uri} does not exist or does not belong to entity {entity_uri}",
                        error="Parent frame validation failed"
                    )
            
            # Step 2: Apply hierarchical grouping URIs
            processed_objects = self.apply_hierarchical_grouping_uris(entity_uri, frame_objects)
            
            # Step 3: Create connection edges
            connection_edges = self.create_connection_edges(entity_uri, processed_objects, parent_frame_uri)
            
            # Step 4: Extract frame URIs for result
            processed_frame_uris = []
            for obj in processed_objects:
                if isinstance(obj, KGFrame) and hasattr(obj, 'URI') and obj.URI:
                    processed_frame_uris.append(obj.URI)
            
            # Step 5: Extract connection edge URIs for result
            created_edge_uris = []
            for edge in connection_edges:
                if hasattr(edge, 'URI') and edge.URI:
                    created_edge_uris.append(edge.URI)
            
            return HierarchicalFrameResult(
                success=True,
                created_connection_edges=created_edge_uris,
                processed_frame_uris=processed_frame_uris,
                validation_results={
                    "parent_frame_valid": parent_frame_uri is None or True,  # Already validated above
                    "processed_frame_count": len(processed_frame_uris),
                    "created_edge_count": len(created_edge_uris)
                },
                message=f"Successfully processed hierarchical frame operation for {len(processed_frame_uris)} frames with {len(created_edge_uris)} connection edges"
            )
            
        except Exception as e:
            self.logger.error(f"Error in hierarchical frame operation: {e}")
            return HierarchicalFrameResult(
                success=False,
                created_connection_edges=[],
                processed_frame_uris=[],
                validation_results={},
                message=f"Hierarchical frame operation failed: {str(e)}",
                error=str(e)
            )
