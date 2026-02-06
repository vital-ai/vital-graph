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
    fuseki_success: Optional[bool] = None


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
            
            # Phase 2: Discover all triples to delete (frame content + entity-frame edges)
            all_triples = []  # List of (s, p, o, o_type) tuples
            deleted_frame_uris = []
            total_deleted_components = 0
            
            any_fuseki_failure = False
            
            for frame_uri in validated_frame_uris:
                try:
                    # Discover frame graph triples
                    frame_triples, component_count = await self._discover_frame_graph_triples(space_id, graph_id, frame_uri)
                    
                    if frame_triples:
                        all_triples.extend(frame_triples)
                        deleted_frame_uris.append(frame_uri)
                        total_deleted_components += component_count
                        self.logger.info(f"� Frame {frame_uri}: {len(frame_triples)} triples, {component_count} components")
                    else:
                        self.logger.warning(f"⚠️ No components found for frame {frame_uri}")
                        
                except Exception as e:
                    self.logger.error(f"❌ Error discovering frame graph {frame_uri}: {e}")
                    continue
            
            # Discover entity-frame edge triples
            if deleted_frame_uris:
                edge_triples = await self._discover_entity_frame_edge_triples(space_id, graph_id, entity_uri, deleted_frame_uris)
                if edge_triples:
                    all_triples.extend(edge_triples)
                    self.logger.info(f"🔍 Found {len(edge_triples)} entity-frame edge triples")
            
            # Phase 3: Single batch delete of all collected triples
            if all_triples:
                fuseki_success = await self._batch_delete_triples(space_id, graph_id, all_triples)
                if fuseki_success is False:
                    any_fuseki_failure = True
                self.logger.info(f"🗑️ Batch deleted {len(all_triples)} triples for {len(deleted_frame_uris)} frames")
            else:
                self.logger.warning(f"⚠️ No triples found to delete")
            
            validation_results = {
                "valid_frames": len(validated_frame_uris),
                "invalid_frames": len(invalid_frames),
                "invalid_frame_uris": list(invalid_frames)
            }
            
            success = len(deleted_frame_uris) > 0
            message = f"Successfully deleted {len(deleted_frame_uris)} frame graphs ({total_deleted_components} components)"
            
            if invalid_frames:
                message += f", {len(invalid_frames)} frames skipped (ownership validation failed)"
            
            # Determine overall fuseki_success: None if no issues, False if any Fuseki failure
            overall_fuseki_success = False if any_fuseki_failure else True
            
            return DeleteFrameResult(
                success=success,
                deleted_frame_uris=deleted_frame_uris,
                deleted_component_count=total_deleted_components,
                validation_results=validation_results,
                message=message,
                fuseki_success=overall_fuseki_success
            )
            
        except Exception as e:
            self.logger.error(f"❌ Error in frame deletion process: {e}")
            return DeleteFrameResult(
                success=False,
                deleted_frame_uris=[],
                deleted_component_count=0,
                validation_results={"valid_frames": 0, "invalid_frames": len(frame_uris)},
                message=f"Frame deletion failed: {str(e)}",
                error=str(e),
                fuseki_success=False
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
    
    async def _discover_frame_graph_triples(self, space_id: str, graph_id: str, frame_uri: str) -> tuple:
        """
        Discover all triples belonging to a frame graph (without deleting).
        
        Finds all subjects with frameGraphURI pointing to frame_uri,
        then gets all their triples.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI whose graph triples to discover
            
        Returns:
            Tuple of (triples_list, component_count) where triples_list is
            list of (s, p, o, o_type) tuples
        """
        try:
            # Find all subjects that belong to this frame graph
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
                return ([], 0)
            
            self.logger.debug(f"🔍 Found {len(component_uris)} components in frame graph {frame_uri}")
            
            # Get all triples for all components in a single query
            component_filter = ', '.join([f'<{str(uri).strip()}>' for uri in component_uris])
            
            triples_query = f"""
            SELECT ?s ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    ?s ?p ?o .
                    FILTER(?s IN ({component_filter}))
                }}
            }}
            """
            
            results = await self.backend.execute_sparql_query(space_id, triples_query)
            triples = self._extract_triples_from_results(results)
            
            return (triples, len(component_uris))
                
        except Exception as e:
            self.logger.error(f"❌ Error discovering frame graph {frame_uri}: {e}")
            return ([], 0)
    
    async def _discover_entity_frame_edge_triples(self, space_id: str, graph_id: str, 
                                                   entity_uri: str, frame_uris: List[str]) -> List[tuple]:
        """
        Discover all triples for entity-frame edges (without deleting).
        
        Finds Edge_hasEntityKGFrame edges and returns all their triples.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI
            frame_uris: List of frame URIs whose edges to discover
            
        Returns:
            List of (s, p, o, o_type) tuples for all edge triples
        """
        all_edge_triples = []
        
        try:
            for frame_uri in frame_uris:
                # Find the edge URI
                find_edge_query = f"""
                SELECT ?edge WHERE {{
                    GRAPH <{graph_id}> {{
                        ?edge a <{self.haley_prefix}Edge_hasEntityKGFrame> .
                        ?edge <{self.vital_prefix}hasEdgeSource> <{entity_uri}> .
                        ?edge <{self.vital_prefix}hasEdgeDestination> <{frame_uri}> .
                    }}
                }}
                """
                
                edge_results = await self.backend.execute_sparql_query(space_id, find_edge_query)
                
                # Extract edge URIs
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
                
                # Get all triples for the edge(s)
                edge_filter = ', '.join([f'<{uri}>' for uri in edge_uris])
                edge_triples_query = f"""
                SELECT ?s ?p ?o WHERE {{
                    GRAPH <{graph_id}> {{
                        ?s ?p ?o .
                        FILTER(?s IN ({edge_filter}))
                    }}
                }}
                """
                
                results = await self.backend.execute_sparql_query(space_id, edge_triples_query)
                edge_triples = self._extract_triples_from_results(results)
                all_edge_triples.extend(edge_triples)
                self.logger.debug(f"🔍 Edge for frame {frame_uri}: {len(edge_triples)} triples")
            
        except Exception as e:
            self.logger.error(f"❌ Error discovering entity-frame edge triples: {e}")
        
        return all_edge_triples
    
    async def _batch_delete_triples(self, space_id: str, graph_id: str, 
                                     triples: List[tuple]) -> Optional[bool]:
        """
        Delete all collected triples in a single DELETE DATA call.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            triples: List of (s, p, o, o_type) tuples to delete
            
        Returns:
            fuseki_success value (True/False/None)
        """
        try:
            delete_statements = []
            for triple in triples:
                s, p, o, o_type = triple[0], triple[1], triple[2], triple[3]
                o_datatype = triple[4] if len(triple) > 4 else ''
                o_lang = triple[5] if len(triple) > 5 else ''
                
                if o_type == 'literal':
                    o_escaped = o.replace('\\', '\\\\').replace('"', '\\"')
                    if o_lang:
                        o_formatted = f'"{o_escaped}"@{o_lang}'
                    elif o_datatype:
                        o_formatted = f'"{o_escaped}"^^<{o_datatype}>'
                    else:
                        o_formatted = f'"{o_escaped}"'
                else:
                    o_formatted = f'<{o}>'
                
                delete_statements.append(f'        <{s}> <{p}> {o_formatted} .')
            
            delete_query = f"""
            DELETE DATA {{
                GRAPH <{graph_id}> {{
{chr(10).join(delete_statements)}
                }}
            }}
            """
            
            self.logger.debug(f"🗑️ Batch DELETE DATA with {len(triples)} triples")
            
            result = await self.backend.execute_sparql_update(space_id, delete_query)
            
            fuseki_success = True
            if hasattr(result, 'fuseki_success'):
                fuseki_success = result.fuseki_success
            
            if result:
                if fuseki_success is False:
                    self.logger.error(f"⚠️ FUSEKI_SYNC_FAILURE: Triples deleted from PostgreSQL but Fuseki may be inconsistent")
                return fuseki_success
            else:
                self.logger.error(f"❌ Batch delete failed")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Error in batch delete: {e}")
            return False
    
    def _extract_triples_from_results(self, results: Dict[str, Any]) -> List[tuple]:
        """
        Extract (s, p, o, o_type, o_datatype, o_lang) tuples from SPARQL SELECT ?s ?p ?o results.
        
        Args:
            results: SPARQL query results
            
        Returns:
            List of (subject, predicate, object, object_type, datatype, language) tuples
        """
        triples = []
        try:
            if isinstance(results, dict) and 'results' in results:
                bindings = results['results'].get('bindings', [])
                for binding in bindings:
                    if 's' in binding and 'p' in binding and 'o' in binding:
                        s_value = binding['s'].get('value', '') if isinstance(binding['s'], dict) else str(binding['s'])
                        p_value = binding['p'].get('value', '') if isinstance(binding['p'], dict) else str(binding['p'])
                        o_value = binding['o'].get('value', '') if isinstance(binding['o'], dict) else str(binding['o'])
                        o_type = binding['o'].get('type', 'uri') if isinstance(binding['o'], dict) else 'uri'
                        o_datatype = binding['o'].get('datatype', '') if isinstance(binding['o'], dict) else ''
                        o_lang = binding['o'].get('xml:lang', '') if isinstance(binding['o'], dict) else ''
                        
                        if s_value and p_value and o_value:
                            triples.append((s_value, p_value, o_value, o_type, o_datatype, o_lang))
        except Exception as e:
            self.logger.error(f"❌ Error extracting triples from results: {e}")
        
        return triples
    
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
