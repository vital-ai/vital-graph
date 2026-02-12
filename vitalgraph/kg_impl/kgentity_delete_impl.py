"""
KGEntity Delete Implementation for VitalGraph.

This module provides the implementation for deleting KG entities from the backend storage,
supporting both single entity deletion and entity graph deletion with related objects.
"""

import logging
from typing import List, Optional, Dict, Any, Union

# VitalSigns imports for proper integration
import vital_ai_vitalsigns as vitalsigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# KG domain model imports
from ai_haley_kg_domain.model.KGEntity import KGEntity

# RDFLib helper for datatype preservation in SPARQL result parsing
from vitalgraph.kg_impl.kgentity_frame_create_impl import _sparql_binding_to_rdflib


class KGEntityDeleteProcessor:
    """
    Processor for KGEntity deletion operations with backend integration.
    
    Handles both single entity deletion and entity graph deletion with proper
    dual-write coordination between Fuseki and PostgreSQL backends.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def delete_entity(self, backend, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """
        Delete a single KGEntity from the backend.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            entity_uri: URI of the entity to delete
            
        Returns:
            bool: True if deletion was successful, False otherwise
        """
        try:
            self.logger.debug(f"Deleting single entity: {entity_uri} from graph: {graph_id}")
            
            # Use the proper graph URI for backend operations
            full_graph_uri = graph_id
            
            # Query to get all triples for this entity
            triples_query = f"""
            SELECT ?p ?o WHERE {{
                GRAPH <{full_graph_uri}> {{
                    <{entity_uri}> ?p ?o .
                }}
            }}
            """
            
            triples_result = await backend.execute_sparql_query(space_id, triples_query)
            
            # Extract quads with proper RDFLib objects to preserve datatype/language
            delete_quads = []
            if isinstance(triples_result, dict) and 'results' in triples_result:
                bindings = triples_result['results'].get('bindings', [])
                for binding in bindings:
                    if 'p' in binding and 'o' in binding:
                        p_value = binding['p'].get('value', '') if isinstance(binding['p'], dict) else str(binding['p'])
                        # Reconstruct RDFLib object from full binding to preserve datatype/language
                        o_rdflib = _sparql_binding_to_rdflib(binding.get('o', ''))
                        
                        if p_value and o_rdflib is not None:
                            delete_quads.append((entity_uri, p_value, o_rdflib, full_graph_uri))
            
            if not delete_quads:
                self.logger.warning(f"No triples found for entity {entity_uri}")
                return False
            
            self.logger.debug(f"Deleting entity {entity_uri} with {len(delete_quads)} quads")
            
            # Use remove_rdf_quads_batch for proper dual-write with typed literals
            deleted_count = await backend.remove_rdf_quads_batch(space_id, delete_quads)
            success = deleted_count > 0 if isinstance(deleted_count, int) else bool(deleted_count)
            
            if success:
                self.logger.debug(f"Successfully deleted entity: {entity_uri}")
            else:
                self.logger.warning(f"Failed to delete entity: {entity_uri}")
                
            return success
            
        except Exception as e:
            self.logger.error(f"Error deleting entity {entity_uri}: {e}")
            return False
    
    async def delete_entity_graph(self, backend, space_id: str, graph_id: str, entity_uri: str) -> int:
        """
        Delete an entity graph (entity plus all related objects) from the backend.
        
        This method finds all objects that share the same kgGraphURI as the target entity
        and deletes them all as a group.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            entity_uri: URI of the primary entity whose graph should be deleted
            
        Returns:
            int: Number of objects deleted (0 if failed)
        """
        try:
            import time
            start_time = time.time()
            self.logger.info(f"🔥 DELETE ENTITY GRAPH START: {entity_uri} from graph: {graph_id}")
            
            # Use the proper graph URI for backend operations
            full_graph_uri = graph_id
            
            # Use entity_uri as the kgGraphURI (they should be the same for entity graphs)
            kg_graph_uri = entity_uri
            
            self.logger.info(f"🔥 STEP 1: Finding all objects with kGGraphURI: {kg_graph_uri}")
            
            # First, find all subjects with this kGGraphURI
            find_subjects_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT DISTINCT ?s WHERE {{
                GRAPH <{full_graph_uri}> {{
                    ?s haley:hasKGGraphURI <{kg_graph_uri}> .
                }}
            }}
            """
            
            step1_start = time.time()
            self.logger.info(f"🔥 STEP 1: Executing SPARQL query to find subjects...")
            subjects_result = await backend.execute_sparql_query(space_id, find_subjects_query)
            step1_time = time.time() - step1_start
            self.logger.info(f"🔥 STEP 1: Query completed in {step1_time:.3f}s")
            
            # Extract subject URIs
            subject_uris = []
            if isinstance(subjects_result, dict) and 'results' in subjects_result:
                bindings = subjects_result['results'].get('bindings', [])
                for binding in bindings:
                    if 's' in binding:
                        s_value = binding['s'].get('value', '') if isinstance(binding['s'], dict) else str(binding['s'])
                        if s_value:
                            subject_uris.append(s_value)
            
            if not subject_uris:
                self.logger.warning(f"No objects found with kGGraphURI: {kg_graph_uri}")
                return 0
            
            self.logger.info(f"🔥 STEP 1: Found {len(subject_uris)} objects with kGGraphURI")
            
            # Query to get all triples for all subjects in a single query
            self.logger.info(f"🔥 STEP 2: Building FILTER IN query for {len(subject_uris)} subjects...")
            subject_filter = ', '.join([f'<{str(uri).strip()}>' for uri in subject_uris])
            
            triples_query = f"""
            SELECT ?s ?p ?o WHERE {{
                GRAPH <{full_graph_uri}> {{
                    ?s ?p ?o .
                    FILTER(?s IN ({subject_filter}))
                }}
            }}
            """
            
            step2_start = time.time()
            self.logger.info(f"🔥 STEP 2: Executing SPARQL query to get all triples...")
            triples_result = await backend.execute_sparql_query(space_id, triples_query)
            step2_time = time.time() - step2_start
            self.logger.info(f"🔥 STEP 2: Query completed in {step2_time:.3f}s")
            
            # Extract quads with proper RDFLib objects to preserve datatype/language
            self.logger.info(f"🔥 STEP 2: Extracting triples from results...")
            quads = []
            if isinstance(triples_result, dict) and 'results' in triples_result:
                bindings = triples_result['results'].get('bindings', [])
                for binding in bindings:
                    if 's' in binding and 'p' in binding and 'o' in binding:
                        s_value = binding['s'].get('value', '') if isinstance(binding['s'], dict) else str(binding['s'])
                        p_value = binding['p'].get('value', '') if isinstance(binding['p'], dict) else str(binding['p'])
                        # Reconstruct RDFLib object from full binding to preserve datatype/language
                        o_rdflib = _sparql_binding_to_rdflib(binding.get('o', ''))
                        
                        if s_value and p_value and o_rdflib is not None:
                            quads.append((s_value, p_value, o_rdflib, full_graph_uri))
            
            if not quads:
                self.logger.warning(f"No triples found for entity graph objects")
                return 0
            
            self.logger.info(f"🔥 STEP 2: Found {len(quads)} quads to delete")
            
            # Execute direct quad deletion (bypasses SPARQL parsing!)
            step4_start = time.time()
            self.logger.info(f"🔥 STEP 4: Executing direct quad deletion via backend.remove_rdf_quads_batch()...")
            deleted_count = await backend.remove_rdf_quads_batch(space_id, quads)
            step4_time = time.time() - step4_start
            self.logger.info(f"🔥 STEP 4: Direct quad deletion completed in {step4_time:.3f}s (deleted {deleted_count} quads)")
            
            if deleted_count == 0:
                self.logger.error(f"Failed to delete quads for entity graph")
                return 0
            
            self.logger.debug(f"Successfully deleted entity graph with kGGraphURI: {kg_graph_uri}")
            return len(subject_uris)
            
        except Exception as e:
            self.logger.error(f"Error deleting entity graph for {entity_uri}: {e}")
            return 0
    
    async def delete_entities_batch(self, backend, space_id: str, graph_id: str, entity_uris: List[str], 
                                  delete_entity_graph: bool = False) -> int:
        """
        Delete multiple entities from the backend.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            entity_uris: List of entity URIs to delete
            delete_entity_graph: If True, delete entity graphs instead of just entities
            
        Returns:
            int: Number of entities successfully deleted
        """
        try:
            self.logger.debug(f"Deleting {len(entity_uris)} entities (entity_graph={delete_entity_graph})")
            
            deleted_count = 0
            
            for entity_uri in entity_uris:
                try:
                    if delete_entity_graph:
                        # Delete entity graph (returns count of deleted objects)
                        graph_deleted_count = await self.delete_entity_graph(backend, space_id, graph_id, entity_uri)
                        if graph_deleted_count > 0:
                            deleted_count += 1  # Count as 1 entity deletion regardless of graph size
                    else:
                        # Delete single entity
                        success = await self.delete_entity(backend, space_id, graph_id, entity_uri)
                        if success:
                            deleted_count += 1
                            
                except Exception as e:
                    self.logger.error(f"Error deleting entity {entity_uri}: {e}")
                    continue
            
            self.logger.debug(f"Successfully deleted {deleted_count} out of {len(entity_uris)} entities")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Error in batch delete operation: {e}")
            return 0
    
    async def _get_entity_kg_graph_uri(self, backend, space_id: str, graph_id: str, entity_uri: str) -> Optional[str]:
        """
        Get the kgGraphURI property value for an entity.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            entity_uri: URI of the entity
            
        Returns:
            Optional[str]: The kgGraphURI value, or None if not found
        """
        try:
            # Get the entity object and extract kGGraphURI from it
            if hasattr(backend, 'get_entity'):
                try:
                    result = await backend.get_entity(space_id, graph_id, entity_uri)
                    if result and result.success and result.objects:
                        entity_obj = result.objects[0]  # Get first object
                        if hasattr(entity_obj, 'kGGraphURI'):
                            kg_graph_uri = getattr(entity_obj, 'kGGraphURI', None)
                            if kg_graph_uri:
                                return str(kg_graph_uri)
                except Exception as e:
                    self.logger.debug(f"Could not get kGGraphURI from entity object: {e}")
            
            # Fallback: return None (will fall back to single entity delete)
            self.logger.warning(f"Cannot get kGGraphURI for entity {entity_uri} - backend method not available")
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting kGGraphURI for entity {entity_uri}: {e}")
            return None
    
    async def _find_objects_by_kg_graph_uri(self, backend, space_id: str, graph_id: str, kg_graph_uri: str) -> List[str]:
        """
        Find all object URIs that have the specified kgGraphURI.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kg_graph_uri: The kgGraphURI to search for
            
        Returns:
            List[str]: List of object URIs with the specified kgGraphURI
        """
        try:
            # Use SPARQL query to find all objects with the specified kGGraphURI
            sparql_query = f"""
            SELECT DISTINCT ?uri WHERE {{
                GRAPH <{graph_id}> {{
                    ?uri <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> <{kg_graph_uri}> .
                }}
            }}
            """
            
            result = await backend.execute_sparql_query(space_id, sparql_query)
            self.logger.debug(f"SPARQL query result: {result}")
            
            # Extract URIs from SPARQL results
            object_uris = []
            if isinstance(result, dict) and 'results' in result:
                bindings = result.get('results', {}).get('bindings', [])
                for binding in bindings:
                    if 'uri' in binding:
                        uri_value = binding['uri']['value']
                        object_uris.append(uri_value)
            elif isinstance(result, list):
                # Handle case where result is directly a list of bindings
                for binding in result:
                    if isinstance(binding, dict) and 'uri' in binding:
                        uri_value = binding['uri']['value']
                        object_uris.append(uri_value)
            
            self.logger.info(f"Found {len(object_uris)} objects with kGGraphURI {kg_graph_uri}")
            return object_uris
            
        except Exception as e:
            self.logger.error(f"Error finding objects by kgGraphURI {kg_graph_uri}: {e}")
            return []
    
    async def entity_exists(self, backend, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """
        Check if an entity exists in the backend.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            entity_uri: URI of the entity to check
            
        Returns:
            bool: True if entity exists, False otherwise
        """
        try:
            # Use backend's object_exists method to check if entity exists
            if hasattr(backend, 'object_exists'):
                try:
                    return await backend.object_exists(space_id, graph_id, entity_uri)
                except Exception:
                    return False
            
            # Fallback: assume entity exists (let deletion handle the error)
            self.logger.warning(f"Cannot check entity existence for {entity_uri} - backend method not available")
            return True
            
        except Exception as e:
            self.logger.error(f"Error checking if entity exists {entity_uri}: {e}")
            return False
