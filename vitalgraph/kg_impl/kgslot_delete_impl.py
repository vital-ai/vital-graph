"""
KGSlot Delete Implementation for VitalGraph.

This module provides the implementation for deleting KG slots from the backend storage,
supporting both single slot deletion and slot graph deletion with related objects.

Follows the same pattern as KGEntityDeleteProcessor for consistency.
"""

import logging
from typing import List, Optional, Dict, Any, Union

# VitalSigns imports for proper integration
import vital_ai_vitalsigns as vitalsigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# KG domain model imports
from ai_haley_kg_domain.model.KGSlot import KGSlot


class KGSlotDeleteProcessor:
    """
    Processor for KGSlot deletion operations with backend integration.
    
    Handles both single slot deletion and slot graph deletion with proper
    dual-write coordination between Fuseki and PostgreSQL backends.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def delete_slot(self, backend, space_id: str, graph_id: str, slot_uri: str) -> bool:
        """
        Delete a single KGSlot from the backend.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            slot_uri: URI of the slot to delete
            
        Returns:
            bool: True if deletion was successful, False otherwise
        """
        try:
            self.logger.info(f"Deleting single slot: {slot_uri} from graph: {graph_id}")
            
            # Use the proper graph URI for backend operations
            full_graph_uri = graph_id
            
            # Create SPARQL DELETE query for single slot
            delete_query = f"""
            DELETE {{
                GRAPH <{full_graph_uri}> {{
                    <{slot_uri}> ?p ?o .
                }}
            }}
            WHERE {{
                GRAPH <{full_graph_uri}> {{
                    <{slot_uri}> ?p ?o .
                }}
            }}
            """
            
            self.logger.debug(f"Executing DELETE query: {delete_query}")
            
            # Execute delete operation through backend
            success = await backend.delete_object(space_id, full_graph_uri, slot_uri)
            
            if success:
                self.logger.info(f"Successfully deleted slot: {slot_uri}")
            else:
                self.logger.warning(f"Failed to delete slot: {slot_uri}")
                
            return success
            
        except Exception as e:
            self.logger.error(f"Error deleting slot {slot_uri}: {e}")
            return False
    
    async def delete_slot_graph(self, backend, space_id: str, graph_id: str, slot_uri: str) -> int:
        """
        Delete a slot graph (slot plus all related objects) from the backend.
        
        This method finds all objects that share the same kgGraphURI as the target slot
        and deletes them all as a group.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            slot_uri: URI of the primary slot whose graph should be deleted
            
        Returns:
            int: Number of objects deleted (0 if failed)
        """
        try:
            self.logger.info(f"Deleting slot graph for: {slot_uri} from graph: {graph_id}")
            
            # Use the proper graph URI for backend operations
            full_graph_uri = graph_id
            
            # First, find the kgGraphURI for this slot
            kg_graph_uri = await self._get_slot_kg_graph_uri(backend, space_id, full_graph_uri, slot_uri)
            
            if not kg_graph_uri:
                self.logger.warning(f"No kgGraphURI found for slot {slot_uri}, falling back to single slot delete")
                success = await self.delete_slot(backend, space_id, graph_id, slot_uri)
                return 1 if success else 0
            
            # Find all objects with the same kgGraphURI
            related_objects = await self._find_objects_by_kg_graph_uri(backend, space_id, full_graph_uri, kg_graph_uri)
            
            if not related_objects:
                self.logger.warning(f"No objects found with kgGraphURI {kg_graph_uri}")
                return 0
            
            self.logger.info(f"Found {len(related_objects)} objects to delete with kgGraphURI: {kg_graph_uri}")
            
            # Delete all objects in the slot graph
            deleted_count = 0
            for obj_uri in related_objects:
                try:
                    success = await backend.delete_object(space_id, full_graph_uri, obj_uri)
                    if success:
                        deleted_count += 1
                        self.logger.debug(f"Deleted object: {obj_uri}")
                    else:
                        self.logger.warning(f"Failed to delete object: {obj_uri}")
                except Exception as e:
                    self.logger.error(f"Error deleting object {obj_uri}: {e}")
            
            self.logger.info(f"Successfully deleted {deleted_count} objects from slot graph")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Error deleting slot graph for {slot_uri}: {e}")
            return 0
    
    async def delete_slots_batch(self, backend, space_id: str, graph_id: str, slot_uris: List[str], 
                               delete_slot_graph: bool = False) -> int:
        """
        Delete multiple slots from the backend.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            slot_uris: List of slot URIs to delete
            delete_slot_graph: If True, delete slot graphs instead of just slots
            
        Returns:
            int: Number of slots successfully deleted
        """
        try:
            self.logger.info(f"Deleting {len(slot_uris)} slots (slot_graph={delete_slot_graph})")
            
            deleted_count = 0
            
            for slot_uri in slot_uris:
                try:
                    if delete_slot_graph:
                        # Delete slot graph (returns count of deleted objects)
                        graph_deleted_count = await self.delete_slot_graph(backend, space_id, graph_id, slot_uri)
                        if graph_deleted_count > 0:
                            deleted_count += 1  # Count as 1 slot deletion regardless of graph size
                    else:
                        # Delete single slot
                        success = await self.delete_slot(backend, space_id, graph_id, slot_uri)
                        if success:
                            deleted_count += 1
                            
                except Exception as e:
                    self.logger.error(f"Error deleting slot {slot_uri}: {e}")
                    continue
            
            self.logger.info(f"Successfully deleted {deleted_count} out of {len(slot_uris)} slots")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Error in batch delete operation: {e}")
            return 0
    
    async def _get_slot_kg_graph_uri(self, backend, space_id: str, graph_id: str, slot_uri: str) -> Optional[str]:
        """
        Get the kgGraphURI property value for a slot.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            slot_uri: URI of the slot
            
        Returns:
            Optional[str]: The kgGraphURI value, or None if not found
        """
        try:
            # Get the slot object and extract kGGraphURI from it
            if hasattr(backend, 'get_slot'):
                try:
                    result = await backend.get_slot(space_id, graph_id, slot_uri)
                    if result and result.success and result.objects:
                        slot_obj = result.objects[0]  # Get first object
                        if hasattr(slot_obj, 'kGGraphURI'):
                            kg_graph_uri = getattr(slot_obj, 'kGGraphURI', None)
                            if kg_graph_uri:
                                return str(kg_graph_uri)
                except Exception as e:
                    self.logger.debug(f"Could not get kGGraphURI from slot object: {e}")
            
            # Fallback: return None (will fall back to single slot delete)
            self.logger.warning(f"Cannot get kGGraphURI for slot {slot_uri} - backend method not available")
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting kGGraphURI for slot {slot_uri}: {e}")
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
    
    async def slot_exists(self, backend, space_id: str, graph_id: str, slot_uri: str) -> bool:
        """
        Check if a slot exists in the backend.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            slot_uri: URI of the slot to check
            
        Returns:
            bool: True if slot exists, False otherwise
        """
        try:
            # Use backend's object_exists method to check if slot exists
            if hasattr(backend, 'object_exists'):
                try:
                    return await backend.object_exists(space_id, graph_id, slot_uri)
                except Exception:
                    return False
            
            # Fallback: assume slot exists (let deletion handle the error)
            self.logger.warning(f"Cannot check slot existence for {slot_uri} - backend method not available")
            return True
            
        except Exception as e:
            self.logger.error(f"Error checking if slot exists {slot_uri}: {e}")
            return False
