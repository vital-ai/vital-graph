#!/usr/bin/env python3
"""
KGEntity Frame Update Processor Implementation

This module provides the KGEntityFrameUpdateProcessor class for updating frames
within the KGEntities context, following the established architectural pattern.

Handles frame property updates, slot modifications, and frame graph URI preservation.
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
class UpdateFrameResult:
    """Result of frame update operation."""
    success: bool
    updated_frame_uris: List[str]
    updated_component_count: int
    validation_results: Dict[str, Any]
    message: str
    error: Optional[str] = None
    fuseki_success: Optional[bool] = None


class KGEntityFrameUpdateProcessor:
    """
    Processor for updating frames within KGEntity context.
    
    Handles frame property updates, slot modifications, and frame graph URI preservation
    while maintaining entity-frame relationships and grouping URI consistency.
    """
    
    def __init__(self, backend: FusekiPostgreSQLBackendAdapter, logger: logging.Logger):
        """
        Initialize the frame update processor.
        
        Args:
            backend: Backend adapter for SPARQL operations
            logger: Logger instance
        """
        self.backend = backend
        self.logger = logger
        self.vitalsigns = VitalSigns()
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
        self.vital_prefix = "http://vital.ai/ontology/vital-core#"
    
    async def update_frames(self, space_id: str, graph_id: str, entity_uri: str, 
                           frame_objects: List[GraphObject],
                           parent_frame_uri: Optional[str] = None) -> UpdateFrameResult:
        """
        Update frames and their complete frame graphs within entity context.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier  
            entity_uri: Entity URI that owns the frames
            frame_objects: List of frame objects to update
            
        Returns:
            UpdateFrameResult with update details
        """
        try:
            if parent_frame_uri:
                self.logger.info(f"🔄 Starting CHILD frame update for entity {entity_uri}: {len(frame_objects)} frame objects, parent_frame_uri={parent_frame_uri}")
            else:
                self.logger.info(f"🔄 Starting TOP-LEVEL frame update for entity {entity_uri}: {len(frame_objects)} frame objects")
            
            # Phase 1: Validate frame ownership (security)
            frame_uris = [str(obj.URI) for obj in frame_objects if hasattr(obj, 'URI')]
            validated_frame_uris = await self.validate_frame_ownership(space_id, graph_id, entity_uri, frame_uris)
            
            if not validated_frame_uris:
                return UpdateFrameResult(
                    success=False,
                    updated_frame_uris=[],
                    updated_component_count=0,
                    validation_results={"valid_frames": 0, "invalid_frames": len(frame_uris)},
                    message="No valid frames found for update",
                    error="Frame ownership validation failed"
                )
            
            # Track invalid frames for reporting
            invalid_frames = set(frame_uris) - set(validated_frame_uris)
            
            self.logger.info(f"🔍 Frame ownership validation: {len(validated_frame_uris)} valid, {len(invalid_frames)} invalid")
            
            # Phase 2: Prepare frame objects for update
            # Include all objects: frames, slots, and edges
            # Only validate that KGFrame objects are owned by the entity
            from ai_haley_kg_domain.model.KGFrame import KGFrame
            validated_frame_objects = []
            for obj in frame_objects:
                if isinstance(obj, KGFrame):
                    # Only include frames that passed ownership validation
                    if str(obj.URI) in validated_frame_uris:
                        validated_frame_objects.append(obj)
                else:
                    # Include all non-frame objects (slots, edges, etc.)
                    validated_frame_objects.append(obj)
            
            # Phase 3: Set proper grouping URIs for frame objects
            await self.assign_grouping_uris(validated_frame_objects, entity_uri)
            
            # Phase 4: Use KGEntityFrameCreateProcessor for atomic update
            from vitalgraph.kg_impl.kgentity_frame_create_impl import KGEntityFrameCreateProcessor
            
            frame_create_processor = KGEntityFrameCreateProcessor()
            
            # Create backend adapter for the create processor
            create_result = await frame_create_processor.create_entity_frame(
                backend_adapter=self.backend,
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_objects=validated_frame_objects,
                operation_mode="UPDATE",
                parent_frame_uri=parent_frame_uri
            )
            
            validation_results = {
                "valid_frames": len(validated_frame_uris),
                "invalid_frames": len(invalid_frames),
                "invalid_frame_uris": list(invalid_frames)
            }
            
            if create_result.success:
                message = f"Successfully updated {len(validated_frame_uris)} frame graphs"
                
                if invalid_frames:
                    message += f", {len(invalid_frames)} frames skipped (ownership validation failed)"
                
                return UpdateFrameResult(
                    success=True,
                    updated_frame_uris=validated_frame_uris,
                    updated_component_count=create_result.frame_count,
                    validation_results=validation_results,
                    message=message,
                    fuseki_success=create_result.fuseki_success
                )
            else:
                return UpdateFrameResult(
                    success=False,
                    updated_frame_uris=[],
                    updated_component_count=0,
                    validation_results=validation_results,
                    message=f"Frame update failed: {create_result.message}",
                    error=create_result.message,
                    fuseki_success=create_result.fuseki_success
                )
            
        except Exception as e:
            self.logger.error(f"❌ Error in frame update process: {e}")
            return UpdateFrameResult(
                success=False,
                updated_frame_uris=[],
                updated_component_count=0,
                validation_results={"valid_frames": 0, "invalid_frames": len(frame_objects)},
                message=f"Frame update failed: {str(e)}",
                error=str(e),
                fuseki_success=False
            )
    
    async def validate_frame_ownership(self, space_id: str, graph_id: str, entity_uri: str, 
                                     frame_uris: List[str]) -> List[str]:
        """
        Validate that frames belong to the specified entity (security check).
        
        Reuses the same validation logic as the frame delete processor.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI that should own the frames
            frame_uris: List of frame URIs to validate
            
        Returns:
            List of validated frame URIs that belong to the entity
        """
        try:
            # Build frame URIs filter for SPARQL query
            frame_uris_filter = ', '.join([f'<{uri}>' for uri in frame_uris])
            
            # Phase 1 SPARQL query: Validate frame ownership
            # Include both direct entity-frame connections and hierarchical parent-child connections
            ownership_query = f"""
            SELECT DISTINCT ?frame_uri WHERE {{
                GRAPH <{graph_id}> {{
                    {{
                        # Direct entity-frame connections
                        ?edge a <{self.haley_prefix}Edge_hasEntityKGFrame> .
                        ?edge <{self.vital_prefix}hasEdgeSource> <{entity_uri}> .
                        ?edge <{self.vital_prefix}hasEdgeDestination> ?frame_uri .
                    }} UNION {{
                        # Hierarchical frames connected via parent-child relationships
                        ?parent_edge a <{self.haley_prefix}Edge_hasEntityKGFrame> .
                        ?parent_edge <{self.vital_prefix}hasEdgeSource> <{entity_uri}> .
                        ?parent_edge <{self.vital_prefix}hasEdgeDestination> ?parent_frame .
                        ?child_edge a <{self.haley_prefix}Edge_hasKGFrame> .
                        ?child_edge <{self.vital_prefix}hasEdgeSource> ?parent_frame .
                        ?child_edge <{self.vital_prefix}hasEdgeDestination> ?frame_uri .
                    }}
                    FILTER(?frame_uri IN ({frame_uris_filter}))
                }}
            }}
            """
            
            self.logger.debug(f"🔍 Frame ownership validation query: {ownership_query}")
            
            ownership_results = await self.backend.execute_sparql_query(space_id, ownership_query)
            self.logger.debug(f"🔍 Ownership query results: {ownership_results}")
            
            validated_frame_uris = self._extract_frame_uris_from_results(ownership_results)
            
            return validated_frame_uris
            
        except Exception as e:
            self.logger.error(f"❌ Error validating frame ownership: {e}")
            return []
    
    async def assign_grouping_uris(self, frame_objects: List[GraphObject], entity_uri: str) -> None:
        """
        Assign proper grouping URIs to frame objects for update.
        
        Args:
            frame_objects: List of frame objects to update
            entity_uri: URI of the parent entity
        """
        try:
            self.logger.info(f"🏷️  Assigning grouping URIs for {len(frame_objects)} frame objects")
            
            # Use the correct dual grouping URI function from graph_operations
            from vitalgraph.utils.graph_operations import set_dual_grouping_uris
            set_dual_grouping_uris(frame_objects, entity_uri, self.logger)
            
        except Exception as e:
            self.logger.error(f"❌ Error assigning grouping URIs: {e}")
    
    def _extract_frame_uris_from_results(self, results: Dict[str, Any]) -> List[str]:
        """
        Extract frame URIs from SPARQL query results.
        
        Args:
            results: SPARQL query results
            
        Returns:
            List of frame URI strings
        """
        frame_uris = []
        
        try:
            # Handle SPARQL JSON format
            if isinstance(results, dict) and 'results' in results:
                bindings = results['results'].get('bindings', [])
                for binding in bindings:
                    if 'frame_uri' in binding:
                        frame_value = binding['frame_uri']
                        if isinstance(frame_value, dict) and 'value' in frame_value:
                            frame_uris.append(frame_value['value'])
                        else:
                            frame_uris.append(str(frame_value))
            elif isinstance(results, list):
                # Handle list format (fallback)
                for result in results:
                    if isinstance(result, dict) and 'frame_uri' in result:
                        frame_value = result['frame_uri']
                        if isinstance(frame_value, dict) and 'value' in frame_value:
                            frame_uris.append(frame_value['value'])
                        else:
                            frame_uris.append(str(frame_value))
            
            self.logger.debug(f"🔍 Extracted frame URIs from results: {frame_uris}")
            
        except Exception as e:
            self.logger.error(f"❌ Error extracting frame URIs from results: {e}")
            self.logger.debug(f"🔍 Results structure: {results}")
        
        return frame_uris
