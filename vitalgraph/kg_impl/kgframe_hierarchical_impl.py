#!/usr/bin/env python3
"""
KGFrame Hierarchical Processor Implementation

This module provides the KGFrameHierarchicalProcessor class for handling
hierarchical frame operations for standalone frames (not entity-associated).

Handles parent frame validation, Edge_hasKGFrame creation, and grouping URI
inheritance for child frames.

Based on: kgentity_hierarchical_frame_impl.py
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Domain model imports
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame

# Common utilities
from vitalgraph.kg_impl.kg_backend_utils import (
    KGBackendInterface,
    BackendOperationResult
)


@dataclass
class CreateFrameResult:
    """Result of frame creation operation."""
    success: bool
    created_uris: List[str]
    message: str
    frame_count: int
    error: Optional[str] = None


class KGFrameHierarchicalProcessor:
    """
    Processor for creating hierarchical child frames.
    
    Based on: kgentity_hierarchical_frame_impl.py
    
    Handles:
    - Child frame creation with parent-child relationships
    - Edge_hasKGFrame relationship creation
    - Grouping URI inheritance from parent
    - Validation of parent frame existence
    """
    
    def __init__(self):
        """Initialize the hierarchical frame processor."""
        self.logger = logging.getLogger(__name__)
        self.vitalsigns = VitalSigns()
    
    async def create_child_frames(
        self,
        backend_adapter: KGBackendInterface,
        space_id: str,
        graph_id: str,
        parent_frame_uri: str,
        child_frame_objects: List[GraphObject],
        operation_mode: str = "CREATE"
    ) -> CreateFrameResult:
        """
        Create child frames linked to parent frame.
        
        Process:
        1. Validate parent frame exists
        2. Get parent's kGGraphURI and inherit it
        3. Categorize child frame objects
        4. Set hasFrameGraphURI to child frame URI
        5. Create Edge_hasKGFrame relationships (parent -> child)
        6. Execute atomic creation
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier
            parent_frame_uri: Parent frame URI
            child_frame_objects: List of child frame GraphObjects
            operation_mode: CREATE, UPDATE, or UPSERT
            
        Returns:
            CreateFrameResult with created URIs and metadata
        """
        try:
            self.logger.info(f"Creating child frames for parent {parent_frame_uri} in space {space_id}, graph {graph_id}")
            
            # Step 1: Validate parent frame exists
            parent_exists = await self._validate_parent_frame_exists(
                backend_adapter, space_id, graph_id, parent_frame_uri
            )
            
            if not parent_exists:
                return CreateFrameResult(
                    success=False,
                    created_uris=[],
                    message=f"Parent frame {parent_frame_uri} not found",
                    frame_count=0,
                    error="Parent frame does not exist"
                )
            
            # Step 2: Categorize and validate child frame objects
            frame_objects = [obj for obj in child_frame_objects if isinstance(obj, KGFrame)]
            other_objects = [obj for obj in child_frame_objects if not isinstance(obj, KGFrame)]
            
            if not frame_objects:
                return CreateFrameResult(
                    success=False,
                    created_uris=[],
                    message="No valid KGFrame objects found in request",
                    frame_count=0,
                    error="No KGFrame objects"
                )
            
            # Step 3: Set frameGraphURI on child frame members
            all_objects = self._assign_grouping_uris(child_frame_objects)
            
            # Step 4: Create Edge_hasKGFrame relationships (parent -> child)
            edge_objects = self._create_parent_child_edges(
                parent_frame_uri, frame_objects
            )
            all_objects.extend(edge_objects)
            
            # Step 5: Execute atomic creation
            result = await backend_adapter.store_objects(space_id, graph_id, all_objects)
            
            if result.success:
                created_uris = [str(obj.URI) for obj in all_objects if hasattr(obj, 'URI')]
                self.logger.info(f"Successfully created {len(frame_objects)} child frames")
                
                return CreateFrameResult(
                    success=True,
                    created_uris=created_uris,
                    message=f"Successfully created {len(frame_objects)} child frames",
                    frame_count=len(frame_objects)
                )
            else:
                return CreateFrameResult(
                    success=False,
                    created_uris=[],
                    message=result.message or "Frame creation failed",
                    frame_count=0,
                    error=result.error
                )
                
        except Exception as e:
            self.logger.error(f"Child frame creation failed: {e}", exc_info=True)
            return CreateFrameResult(
                success=False,
                created_uris=[],
                message=f"Child frame creation failed: {str(e)}",
                frame_count=0,
                error=str(e)
            )
    
    async def _validate_parent_frame_exists(
        self, 
        backend_adapter: KGBackendInterface,
        space_id: str,
        graph_id: str,
        parent_frame_uri: str
    ) -> bool:
        """
        Validate that the parent frame exists in the graph.
        
        Args:
            backend_adapter: Backend adapter
            space_id: Space identifier
            graph_id: Graph identifier
            parent_frame_uri: Parent frame URI
            
        Returns:
            True if parent frame exists, False otherwise
        """
        try:
            query = f"""
            ASK WHERE {{
                GRAPH <{graph_id}> {{
                    <{parent_frame_uri}> a <http://vital.ai/ontology/haley-ai-kg#KGFrame> .
                }}
            }}
            """
            
            results = await backend_adapter.execute_sparql_query(space_id, query)
            
            # Handle ASK result format
            if isinstance(results, dict):
                return results.get('boolean', False)
            if isinstance(results, bool):
                return results
            
            self.logger.warning(f"Parent frame {parent_frame_uri} not found")
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to validate parent frame: {e}", exc_info=True)
            return False
    
    def _assign_grouping_uris(self, objects: List[GraphObject]) -> List[GraphObject]:
        """
        Assign frameGraphURI to child frame members.
        
        - KGFrame: frameGraphURI = own URI
        - Slots/edges: frameGraphURI = owning frame URI
        
        No kGGraphURI is set — that is an entity-scoped concept.
        
        Args:
            objects: List of graph objects
            
        Returns:
            List of objects with frameGraphURI assigned
        """
        # Find frame URIs for ownership lookup
        frame_uris = {str(obj.URI) for obj in objects if isinstance(obj, KGFrame)}
        fallback_frame_uri = next(iter(frame_uris)) if len(frame_uris) == 1 else None
        
        for obj in objects:
            if isinstance(obj, KGFrame):
                obj.frameGraphURI = str(obj.URI)
                # Child frames are always Aspects
                if not getattr(obj, 'kGFormType', None):
                    obj.kGFormType = "http://vital.ai/ontology/haley-ai-kg#KGFormType_Aspect"
                self.logger.debug(f"Frame {obj.URI}: frameGraphURI={obj.URI}")
            else:
                # Slots and edges belong to a frame
                if fallback_frame_uri and hasattr(obj, 'frameGraphURI'):
                    obj.frameGraphURI = fallback_frame_uri
                    self.logger.debug(f"Object {getattr(obj, 'URI', '?')}: frameGraphURI={fallback_frame_uri}")
        
        return objects
    
    def _create_parent_child_edges(
        self,
        parent_frame_uri: str,
        child_frames: List[KGFrame]
    ) -> List[Edge_hasKGFrame]:
        """
        Create Edge_hasKGFrame relationships between parent and child frames.
        
        Args:
            parent_frame_uri: Parent frame URI
            child_frames: List of child frames
            
        Returns:
            List of Edge_hasKGFrame objects
        """
        edges = []
        
        for child_frame in child_frames:
            edge = Edge_hasKGFrame()
            
            # Create unique edge URI
            parent_id = parent_frame_uri.split('/')[-1]
            child_id = str(child_frame.URI).split('/')[-1]
            edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGFrame/{parent_id}_{child_id}_edge"
            
            # Set edge source and destination
            edge.edgeSource = parent_frame_uri
            edge.edgeDestination = str(child_frame.URI)
            
            # No kGGraphURI — entity-scoped concept not used here
            # frameGraphURI on structural edges is set to parent frame
            edge.frameGraphURI = parent_frame_uri
            
            edges.append(edge)
            self.logger.debug(f"Created Edge_hasKGFrame: {parent_frame_uri} -> {child_frame.URI}")
        
        return edges
