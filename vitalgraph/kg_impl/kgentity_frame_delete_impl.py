"""
KGEntity Frame Delete Implementation

This module provides the KGEntityFrameDeleteProcessor for handling frame deletion operations
within the KGEntities context, following the established architectural pattern.
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from ..kg_impl.kg_backend_utils import FusekiPostgreSQLBackendAdapter


@dataclass
class DeleteFrameResult:
    """Result of frame deletion operation."""
    success: bool
    deleted_frame_uris: List[str]
    deleted_component_count: int
    validation_results: Dict[str, Any]
    message: str
    error: Optional[str] = None


class KGEntityFrameDeleteProcessor:
    """
    Processor for deleting frames within KGEntity context.
    
    Handles complete frame graph deletion using frameGraphURI grouping,
    validates frame ownership, and manages entity-frame relationship cleanup.
    """
    
    def __init__(self, backend: FusekiPostgreSQLBackendAdapter, logger: logging.Logger):
        """
        Initialize the frame delete processor.
        
        Args:
            backend: Backend adapter for SPARQL operations
            logger: Logger instance
        """
        self.backend = backend
        self.logger = logger
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
        self.vital_prefix = "http://vital.ai/ontology/vital-core#"
    
    async def delete_frames(self, space_id: str, graph_id: str, entity_uri: str, 
                           frame_uris: List[str]) -> DeleteFrameResult:
        """
        Delete frames and their complete frame graphs from entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier  
            entity_uri: Entity URI that owns the frames
            frame_uris: List of frame URIs to delete
            
        Returns:
            DeleteFrameResult with deletion details
        """
        try:
            self.logger.info(f"🗑️ Starting frame deletion for entity {entity_uri}: {len(frame_uris)} frames")
            
            # Phase 1: Validate frame ownership (security)
            validated_frame_uris = await self.validate_frame_ownership(space_id, graph_id, entity_uri, frame_uris)
            
            if not validated_frame_uris:
                return DeleteFrameResult(
                    success=False,
                    deleted_frame_uris=[],
                    deleted_component_count=0,
                    validation_results={"valid_frames": 0, "invalid_frames": len(frame_uris)},
                    message="No valid frames found for deletion",
                    error="Frame ownership validation failed"
                )
            
            # Track invalid frames for reporting
            invalid_frames = set(frame_uris) - set(validated_frame_uris)
            
            self.logger.info(f"🔍 Frame ownership validation: {len(validated_frame_uris)} valid, {len(invalid_frames)} invalid")
            
            # Phase 2: Delete complete frame graphs
            deleted_frame_uris = []
            total_deleted_components = 0
            
            for frame_uri in validated_frame_uris:
                try:
                    # Delete complete frame graph using frameGraphURI
                    deleted_components = await self.delete_frame_graph(space_id, graph_id, frame_uri)
                    
                    if deleted_components > 0:
                        deleted_frame_uris.append(frame_uri)
                        total_deleted_components += deleted_components
                        self.logger.info(f"🗑️ Deleted frame graph {frame_uri}: {deleted_components} components")
                    else:
                        self.logger.warning(f"⚠️ No components found for frame {frame_uri}")
                        
                except Exception as e:
                    self.logger.error(f"❌ Error deleting frame graph {frame_uri}: {e}")
                    continue
            
            # Phase 3: Delete entity-frame relationship edges
            if deleted_frame_uris:
                await self.delete_entity_frame_edges(space_id, graph_id, entity_uri, deleted_frame_uris)
            
            validation_results = {
                "valid_frames": len(validated_frame_uris),
                "invalid_frames": len(invalid_frames),
                "invalid_frame_uris": list(invalid_frames)
            }
            
            success = len(deleted_frame_uris) > 0
            message = f"Successfully deleted {len(deleted_frame_uris)} frame graphs ({total_deleted_components} components)"
            
            if invalid_frames:
                message += f", {len(invalid_frames)} frames skipped (ownership validation failed)"
            
            return DeleteFrameResult(
                success=success,
                deleted_frame_uris=deleted_frame_uris,
                deleted_component_count=total_deleted_components,
                validation_results=validation_results,
                message=message
            )
            
        except Exception as e:
            self.logger.error(f"❌ Error in frame deletion process: {e}")
            return DeleteFrameResult(
                success=False,
                deleted_frame_uris=[],
                deleted_component_count=0,
                validation_results={"valid_frames": 0, "invalid_frames": len(frame_uris)},
                message=f"Frame deletion failed: {str(e)}",
                error=str(e)
            )
    
    async def validate_frame_ownership(self, space_id: str, graph_id: str, entity_uri: str, 
                                     frame_uris: List[str]) -> List[str]:
        """
        Validate that frames belong to the specified entity (security check).
        
        Reuses the same validation logic as the enhanced GET endpoint.
        
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
            # For child frames, check kGGraphURI; for top-level frames, check entity-frame edges
            ownership_query = f"""
            SELECT DISTINCT ?frame_uri WHERE {{
                GRAPH <{graph_id}> {{
                    {{
                        # Direct entity-frame relationship (top-level frames)
                        ?edge a <{self.haley_prefix}Edge_hasEntityKGFrame> .
                        ?edge <{self.vital_prefix}hasEdgeSource> <{entity_uri}> .
                        ?edge <{self.vital_prefix}hasEdgeDestination> ?frame_uri .
                        FILTER(?frame_uri IN ({frame_uris_filter}))
                    }} UNION {{
                        # Child frames - check if they have the entity's kGGraphURI
                        ?frame_uri a <{self.haley_prefix}KGFrame> .
                        ?frame_uri <{self.haley_prefix}hasKGGraphURI> <{entity_uri}> .
                        FILTER(?frame_uri IN ({frame_uris_filter}))
                    }}
                }}
            }}
            """
            
            self.logger.debug(f"🔍 Frame ownership validation query: {ownership_query}")
            
            ownership_results = await self.backend.execute_sparql_query(space_id, ownership_query)
            self.logger.debug(f"🔍 Ownership query results: {ownership_results}")
            self.logger.debug(f"🔍 Expected entity URI: {entity_uri}")
            self.logger.debug(f"🔍 Expected frame URIs: {frame_uris}")
            self.logger.debug(f"🔍 Graph ID: {graph_id}")
            
            # Debug: Check if any Edge_hasEntityKGFrame edges exist at all
            debug_query = f"""
            SELECT DISTINCT ?edge ?source ?dest ?graph WHERE {{
                GRAPH ?graph {{
                    ?edge a <{self.haley_prefix}Edge_hasEntityKGFrame> .
                    ?edge <{self.vital_prefix}hasEdgeSource> ?source .
                    ?edge <{self.vital_prefix}hasEdgeDestination> ?dest .
                }}
            }}
            LIMIT 10
            """
            
            debug_results = await self.backend.execute_sparql_query(space_id, debug_query)
            self.logger.debug(f"🔍 Debug - All Edge_hasEntityKGFrame edges in graph: {debug_results}")
            
            validated_frame_uris = self._extract_frame_uris_from_results(ownership_results)
            
            return validated_frame_uris
            
        except Exception as e:
            self.logger.error(f"❌ Error validating frame ownership: {e}")
            return []
    
    async def delete_frame_graph(self, space_id: str, graph_id: str, frame_uri: str) -> int:
        """
        Delete complete frame graph using frameGraphURI grouping.
        
        This deletes all objects that have frameGraphURI pointing to the frame_uri,
        including the frame itself, all slots, and internal edges.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI whose complete graph should be deleted
            
        Returns:
            Number of deleted components
        """
        try:
            # First, find all subjects that belong to this frame graph
            find_components_query = f"""
            SELECT DISTINCT ?subject WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject <{self.haley_prefix}hasFrameGraphURI> <{frame_uri}> .
                }}
            }}
            """
            
            self.logger.debug(f"🔍 Finding frame graph components: {find_components_query}")
            
            components_results = await self.backend.execute_sparql_query(space_id, find_components_query)
            component_uris = self._extract_subject_uris_from_results(components_results)
            
            # Also include the frame URI itself (it may not have frameGraphURI pointing to itself)
            if frame_uri not in component_uris:
                component_uris.append(frame_uri)
            
            if not component_uris:
                self.logger.warning(f"⚠️ No components found for frame graph {frame_uri}")
                return 0
            
            self.logger.info(f"🔍 Found {len(component_uris)} components in frame graph {frame_uri}")
            
            # Delete all triples for these components
            delete_patterns = []
            for component_uri in component_uris:
                # Use URI directly as VitalSigns produces clean URIs
                component_str = str(component_uri).strip()
                delete_patterns.append(f"    <{component_str}> ?p ?o .")
            
            delete_query = f"""
            DELETE {{
                GRAPH <{graph_id}> {{
                    {chr(10).join(delete_patterns)}
                }}
            }}
            WHERE {{
                GRAPH <{graph_id}> {{
                    {chr(10).join(delete_patterns)}
                }}
            }}
            """
            
            self.logger.debug(f"🗑️ Frame graph deletion query: {delete_query}")
            
            success = await self.backend.execute_sparql_update(space_id, delete_query)
            
            if success:
                self.logger.info(f"🗑️ Successfully deleted frame graph {frame_uri} with {len(component_uris)} components")
                return len(component_uris)
            else:
                self.logger.error(f"❌ Failed to delete frame graph {frame_uri}")
                return 0
                
        except Exception as e:
            self.logger.error(f"❌ Error deleting frame graph {frame_uri}: {e}")
            return 0
    
    async def delete_entity_frame_edges(self, space_id: str, graph_id: str, entity_uri: str, 
                                      frame_uris: List[str]) -> bool:
        """
        Delete Edge_hasEntityKGFrame relationships between entity and frames.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI
            frame_uris: List of frame URIs to remove relationships for
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Delete edges one at a time to avoid SPARQL parsing issues with FILTER
            all_success = True
            deleted_count = 0
            
            for frame_uri in frame_uris:
                # First, find the edge URI, then delete all its triples
                # This two-step approach avoids SPARQL parsing issues with variable subjects
                find_edge_query = f"""
                SELECT ?edge WHERE {{
                    GRAPH <{graph_id}> {{
                        ?edge a <{self.haley_prefix}Edge_hasEntityKGFrame> .
                        ?edge <{self.vital_prefix}hasEdgeSource> <{entity_uri}> .
                        ?edge <{self.vital_prefix}hasEdgeDestination> <{frame_uri}> .
                    }}
                }}
                """
                
                # Find the edge URI
                edge_results = await self.backend.execute_sparql_query(space_id, find_edge_query)
                
                # Extract edge URIs from results (variable name is 'edge', not 'subject')
                edge_uris = []
                if isinstance(edge_results, dict) and 'results' in edge_results:
                    bindings = edge_results['results'].get('bindings', [])
                    for binding in bindings:
                        if 'edge' in binding:
                            edge_value = binding['edge']
                            if isinstance(edge_value, dict) and 'value' in edge_value:
                                edge_uris.append(edge_value['value'])
                
                if not edge_uris:
                    self.logger.debug(f"No entity-frame edge found for frame {frame_uri}")
                    continue
                
                # Delete all triples for each found edge
                for edge_uri in edge_uris:
                    delete_edge_query = f"""
                    DELETE {{
                        GRAPH <{graph_id}> {{
                            <{edge_uri}> ?p ?o .
                        }}
                    }}
                    WHERE {{
                        GRAPH <{graph_id}> {{
                            <{edge_uri}> ?p ?o .
                        }}
                    }}
                    """
                
                self.logger.debug(f"🗑️ Deleting entity-frame edge for frame {frame_uri}")
                
                success = await self.backend.execute_sparql_update(space_id, delete_edge_query)
                
                if success:
                    deleted_count += 1
                else:
                    self.logger.error(f"❌ Failed to delete entity-frame edge for {frame_uri}")
                    all_success = False
            
            if all_success:
                self.logger.info(f"🗑️ Successfully deleted {deleted_count} entity-frame edges")
            else:
                self.logger.warning(f"🗑️ Deleted {deleted_count}/{len(frame_uris)} entity-frame edges")
                
            return all_success
            
        except Exception as e:
            self.logger.error(f"❌ Error deleting entity-frame edges: {e}")
            return False
    
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
    
    def _extract_subject_uris_from_results(self, results: Dict[str, Any]) -> List[str]:
        """
        Extract subject URIs from SPARQL query results.
        
        Args:
            results: SPARQL query results
            
        Returns:
            List of subject URI strings
        """
        subject_uris = []
        
        try:
            # Handle SPARQL JSON format
            if isinstance(results, dict) and 'results' in results:
                bindings = results['results'].get('bindings', [])
                for binding in bindings:
                    if 'subject' in binding:
                        subject_value = binding['subject']
                        if isinstance(subject_value, dict) and 'value' in subject_value:
                            subject_uris.append(subject_value['value'])
                        else:
                            subject_uris.append(str(subject_value))
            elif isinstance(results, list):
                # Handle list format (fallback)
                for result in results:
                    if isinstance(result, dict) and 'subject' in result:
                        subject_value = result['subject']
                        if isinstance(subject_value, dict) and 'value' in subject_value:
                            subject_uris.append(subject_value['value'])
                        else:
                            subject_uris.append(str(subject_value))
            
        except Exception as e:
            self.logger.error(f"❌ Error extracting subject URIs from results: {e}")
            self.logger.debug(f"🔍 Results structure: {results}")
        
        return subject_uris
