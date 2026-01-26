#!/usr/bin/env python3
"""
KGEntity Frame Discovery Processor Implementation

This module provides the KGEntityFrameDiscoveryProcessor class for discovering
and managing frame relationships within the KGEntities context.

Handles frame discovery via SPARQL queries, frame URI extraction, and frame
relationship analysis for atomic frame operations.
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Backend adapter import
from vitalgraph.kg_impl.kg_backend_utils import FusekiPostgreSQLBackendAdapter


@dataclass
class FrameDiscoveryResult:
    """Result of frame discovery operation."""
    success: bool
    discovered_frame_uris: List[str]
    frame_count: int
    discovery_method: str
    message: str
    error: Optional[str] = None


class KGEntityFrameDiscoveryProcessor:
    """
    Processor for discovering frames within KGEntity context.
    
    Handles SPARQL-based frame discovery, frame URI extraction from query results,
    and frame relationship analysis for atomic frame operations.
    """
    
    def __init__(self, backend: FusekiPostgreSQLBackendAdapter, logger: logging.Logger):
        """
        Initialize the frame discovery processor.
        
        Args:
            backend: Backend adapter for SPARQL operations
            logger: Logger instance
        """
        self.backend = backend
        self.logger = logger
    
    async def discover_entity_frames(self, space_id: str, graph_id: str, entity_uri: str) -> List[str]:
        """
        Discover existing frames associated with an entity using SPARQL.
        
        This method finds all frames connected to the entity through Edge_hasEntityKGFrame
        relationships and frame-to-frame hierarchies via Edge_hasKGFrame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to discover frames for
            
        Returns:
            List[str]: List of discovered frame URIs
        """
        try:
            # SPARQL query to discover all frames associated with the entity
            # Includes both direct entity-to-frame connections and hierarchical frame structures
            discovery_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            SELECT DISTINCT ?frame_uri WHERE {{
                GRAPH <{graph_id}> {{
                    # Find all frames that belong to this entity
                    ?frame_uri a haley:KGFrame ;
                               haley:hasKGGraphURI <{entity_uri}> .
                }}
            }}
            """
            
            # Execute discovery query
            result = await self.backend.execute_sparql_query(space_id, discovery_query)
            
            # Extract frame URIs from results
            frame_uris = self._extract_frame_uris_from_results(result)
            
            self.logger.info(f"Discovered {len(frame_uris)} frames for entity {entity_uri}")
            return frame_uris
            
        except Exception as e:
            self.logger.error(f"Error discovering entity frames: {e}")
            return []
    
    def _extract_frame_uris_from_results(self, results) -> List[str]:
        """
        Extract frame URIs from SPARQL query results.
        
        Args:
            results: SPARQL query results in various formats
            
        Returns:
            List[str]: List of extracted frame URIs
        """
        frame_uris = []
        
        try:
            if isinstance(results, dict) and results.get("bindings"):
                # Standard SPARQL JSON results format
                for binding in results["bindings"]:
                    frame_uri = binding.get("frame_uri", {}).get("value")
                    if frame_uri:
                        frame_uris.append(frame_uri)
            elif isinstance(results, list):
                # List of result dictionaries
                for result in results:
                    if isinstance(result, dict):
                        frame_uri = result.get("frame_uri", {}).get("value")
                        if frame_uri:
                            frame_uris.append(frame_uri)
            elif hasattr(results, 'bindings'):
                # RDFLib-style results
                for binding in results.bindings:
                    if 'frame_uri' in binding:
                        frame_uri = str(binding['frame_uri'])
                        frame_uris.append(frame_uri)
            else:
                self.logger.warning(f"Unexpected SPARQL result format: {type(results)}")
        
        except Exception as e:
            self.logger.error(f"Error extracting frame URIs from results: {e}")
        
        return frame_uris
    
    async def discover_frame_hierarchy(self, space_id: str, graph_id: str, root_frame_uri: str) -> Dict[str, List[str]]:
        """
        Discover the hierarchical structure of frames starting from a root frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            root_frame_uri: Root frame URI to start hierarchy discovery from
            
        Returns:
            Dict[str, List[str]]: Mapping of parent frame URIs to their child frame URIs
        """
        try:
            # SPARQL query to discover frame hierarchy
            hierarchy_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?parent_frame ?child_frame WHERE {{
                GRAPH <{graph_id}> {{
                    # Find all frame-to-frame connections in the hierarchy
                    ?edge a haley:Edge_hasKGFrame ;
                          vital:hasEdgeSource ?parent_frame ;
                          vital:hasEdgeDestination ?child_frame .
                    
                    # Ensure we're in the same entity graph as the root frame
                    ?parent_frame haley:hasKGGraphURI ?entity_uri .
                    ?child_frame haley:hasKGGraphURI ?entity_uri .
                    <{root_frame_uri}> haley:hasKGGraphURI ?entity_uri .
                }}
            }}
            """
            
            # Execute hierarchy query
            result = await self.backend.execute_sparql_query(hierarchy_query)
            
            # Build hierarchy mapping
            hierarchy = {}
            if isinstance(result, dict) and result.get("bindings"):
                for binding in result["bindings"]:
                    parent_uri = binding.get("parent_frame", {}).get("value")
                    child_uri = binding.get("child_frame", {}).get("value")
                    
                    if parent_uri and child_uri:
                        if parent_uri not in hierarchy:
                            hierarchy[parent_uri] = []
                        hierarchy[parent_uri].append(child_uri)
            
            self.logger.info(f"Discovered frame hierarchy with {len(hierarchy)} parent-child relationships")
            return hierarchy
            
        except Exception as e:
            self.logger.error(f"Error discovering frame hierarchy: {e}")
            return {}
    
    async def validate_frame_ownership(self, space_id: str, graph_id: str, entity_uri: str, frame_uris: List[str]) -> Dict[str, bool]:
        """
        Validate that a list of frame URIs belong to the specified entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI that should own the frames
            frame_uris: List of frame URIs to validate
            
        Returns:
            Dict[str, bool]: Mapping of frame URIs to their ownership validation results
        """
        from .kg_validation_utils import KGHierarchicalFrameValidator
        
        validator = KGHierarchicalFrameValidator(self.backend, self.logger)
        return await validator.validate_frame_ownership(space_id, graph_id, entity_uri, frame_uris)
    
    async def discover_frame_components(self, space_id: str, graph_id: str, frame_uri: str) -> Dict[str, List[str]]:
        """
        Discover all components (slots, edges, etc.) that belong to a specific frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to discover components for
            
        Returns:
            Dict[str, List[str]]: Mapping of component types to their URIs
        """
        try:
            # SPARQL query to discover frame components
            components_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?component_uri ?component_type WHERE {{
                GRAPH <{graph_id}> {{
                    # Find all objects that belong to this frame
                    ?component_uri haley:hasFrameGraphURI <{frame_uri}> ;
                                   a ?component_type .
                    
                    # Filter out the frame itself
                    FILTER(?component_uri != <{frame_uri}>)
                }}
            }}
            """
            
            # Execute components query
            result = await self.backend.execute_sparql_query(components_query)
            
            # Group components by type
            components = {}
            if isinstance(result, dict) and result.get("bindings"):
                for binding in result["bindings"]:
                    component_uri = binding.get("component_uri", {}).get("value")
                    component_type = binding.get("component_type", {}).get("value")
                    
                    if component_uri and component_type:
                        # Extract simple type name
                        type_name = component_type.split('#')[-1] if '#' in component_type else component_type
                        
                        if type_name not in components:
                            components[type_name] = []
                        components[type_name].append(component_uri)
            
            self.logger.info(f"Discovered {sum(len(uris) for uris in components.values())} components for frame {frame_uri}")
            return components
            
        except Exception as e:
            self.logger.error(f"Error discovering frame components: {e}")
            return {}
    
    async def perform_comprehensive_frame_discovery(self, space_id: str, graph_id: str, entity_uri: str) -> FrameDiscoveryResult:
        """
        Perform comprehensive frame discovery for an entity including hierarchy and components.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to perform discovery for
            
        Returns:
            FrameDiscoveryResult: Comprehensive discovery results
        """
        try:
            # Step 1: Discover all frames for the entity
            frame_uris = await self.discover_entity_frames(space_id, graph_id, entity_uri)
            
            if not frame_uris:
                return FrameDiscoveryResult(
                    success=True,
                    discovered_frame_uris=[],
                    frame_count=0,
                    discovery_method="comprehensive",
                    message=f"No frames found for entity {entity_uri}"
                )
            
            # Step 2: Validate frame ownership
            ownership_results = await self.validate_frame_ownership(space_id, graph_id, entity_uri, frame_uris)
            valid_frames = [uri for uri, valid in ownership_results.items() if valid]
            
            # Step 3: Discover hierarchy for valid frames
            hierarchy_info = {}
            if valid_frames:
                # Use first frame as root for hierarchy discovery
                hierarchy_info = await self.discover_frame_hierarchy(space_id, graph_id, valid_frames[0])
            
            return FrameDiscoveryResult(
                success=True,
                discovered_frame_uris=valid_frames,
                frame_count=len(valid_frames),
                discovery_method="comprehensive",
                message=f"Successfully discovered {len(valid_frames)} frames with {len(hierarchy_info)} hierarchical relationships"
            )
            
        except Exception as e:
            self.logger.error(f"Error in comprehensive frame discovery: {e}")
            return FrameDiscoveryResult(
                success=False,
                discovered_frame_uris=[],
                frame_count=0,
                discovery_method="comprehensive",
                message=f"Frame discovery failed: {str(e)}",
                error=str(e)
            )
