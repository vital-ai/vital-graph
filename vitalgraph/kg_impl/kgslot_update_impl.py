"""
KGSlot Update Implementation for VitalGraph.

This module provides the implementation for updating KG slots in the backend storage,
using the DELETE + INSERT pattern for complete slot replacement with proper dual-write
coordination (PostgreSQL first, then Fuseki).

Follows the same pattern as KGEntityUpdateProcessor for consistency.
"""

import logging
from typing import List, Optional, Dict, Any, Union
from ..model.kgframes_model import SlotUpdateResponse

# VitalSigns imports for proper integration
import vital_ai_vitalsigns as vitalsigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# KG domain model imports
from ai_haley_kg_domain.model.KGSlot import KGSlot


class KGSlotUpdateProcessor:
    """
    Processor for KGSlot update operations with atomic backend integration.
    
    Handles complete slot replacement using atomic update_quads operation for true
    atomicity and consistency with proper dual-write coordination.
    
    Atomic Update Strategy:
    1. Build delete quads for existing slot data (slot + related objects via kGGraphURI)
    2. Build insert quads for new slot data (VitalSigns objects to triples)
    3. Execute atomic update_quads operation (single transaction)
    4. PostgreSQL-first dual-write with Fuseki synchronization
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def update_slot(self, backend, space_id: str, graph_id: str, 
                         slot_uri: str, updated_objects: List[GraphObject]) -> SlotUpdateResponse:
        """
        Update a single KGSlot using atomic update_quads operation.
        
        This method now uses the validated atomic update_quads function for true atomicity
        instead of separate delete and insert operations.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            slot_uri: URI of the slot to update
            updated_objects: List of VitalSigns objects representing the updated slot
            
        Returns:
            SlotUpdateResponse: Response indicating success/failure of update
        """
        try:
            self.logger.info(f"🔄 Atomic slot update: {slot_uri} in graph: {graph_id}")
            
            # Step 1: Build delete quads for existing slot data
            delete_quads = await self._build_delete_quads_for_slot(backend, space_id, graph_id, slot_uri)
            
            # Step 2: Build insert quads for updated slot data
            insert_quads = await self._build_insert_quads_for_objects(updated_objects, graph_id)
            
            # Step 3: Execute atomic update using validated update_quads function
            success = await backend.update_quads(space_id, graph_id, delete_quads, insert_quads)
            
            if success:
                self.logger.info(f"✅ Successfully updated slot atomically: {slot_uri}")
                return SlotUpdateResponse(
                    message=f"Successfully updated slot: {slot_uri}",
                    updated_uri=slot_uri
                )
            else:
                self.logger.error(f"❌ Atomic slot update failed: {slot_uri}")
                return SlotUpdateResponse(
                    message=f"Failed to update slot atomically: {slot_uri}",
                    updated_uri=""
                )
                
        except Exception as e:
            self.logger.error(f"Error in atomic slot update {slot_uri}: {e}")
            return SlotUpdateResponse(
                message=f"Error updating slot: {str(e)}",
                updated_uri=""
            )
    
    async def update_slots_batch(self, backend, space_id: str, graph_id: str, 
                                slot_updates: Dict[str, List[GraphObject]]) -> SlotUpdateResponse:
        """
        Update multiple slots using complete replacement (DELETE + INSERT) for each.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            slot_updates: Dictionary mapping slot URIs to their updated objects
            
        Returns:
            SlotUpdateResponse: Response indicating success/failure of batch update
        """
        try:
            self.logger.info(f"Batch updating {len(slot_updates)} slots in graph: {graph_id}")
            
            updated_uris = []
            failed_uris = []
            
            for slot_uri, updated_objects in slot_updates.items():
                try:
                    # Update each slot individually using the same DELETE + INSERT pattern
                    result = await self.update_slot(backend, space_id, graph_id, slot_uri, updated_objects)
                    
                    if result.updated_uri:
                        updated_uris.append(slot_uri)
                    else:
                        failed_uris.append(slot_uri)
                        self.logger.warning(f"Failed to update slot {slot_uri}: {result.message}")
                        
                except Exception as e:
                    failed_uris.append(slot_uri)
                    self.logger.error(f"Error updating slot {slot_uri}: {e}")
            
            # Determine overall success
            if len(updated_uris) == len(slot_updates):
                self.logger.info(f"Successfully updated all {len(updated_uris)} slots")
                return SlotUpdateResponse(
                    message=f"Successfully updated {len(updated_uris)} slots",
                    updated_uri=",".join(updated_uris)
                )
            elif len(updated_uris) > 0:
                self.logger.warning(f"Partial success: updated {len(updated_uris)}/{len(slot_updates)} slots")
                return SlotUpdateResponse(
                    message=f"Partial success: updated {len(updated_uris)}/{len(slot_updates)} slots. Failed: {failed_uris}",
                    updated_uri=",".join(updated_uris)
                )
            else:
                self.logger.error(f"Failed to update any slots")
                return SlotUpdateResponse(
                    message=f"Failed to update any slots. All {len(failed_uris)} updates failed.",
                    updated_uri=""
                )
                
        except Exception as e:
            self.logger.error(f"Error in batch update operation: {e}")
            return SlotUpdateResponse(
                message=f"Error in batch update: {str(e)}",
                updated_uri=""
            )
    
    async def _build_delete_quads_for_slot(self, backend, space_id: str, graph_id: str, slot_uri: str) -> List[tuple]:
        """
        Build delete quads for existing slot data.
        
        This method finds all triples related to the slot (including related objects
        via kGGraphURI) and creates delete quads for them.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            slot_uri: URI of the slot to delete data for
            
        Returns:
            List[tuple]: List of (subject, predicate, object, graph) tuples to delete
        """
        try:
            self.logger.info(f"Building delete quads for slot: {slot_uri}")
            
            # Get the kGGraphURI for this slot to find all related objects
            kg_graph_uri = await self._get_slot_kg_graph_uri(backend, space_id, graph_id, slot_uri)
            
            delete_quads = []
            
            if kg_graph_uri:
                # Find all objects with the same kGGraphURI and build delete quads for them
                related_objects = await self._find_objects_by_kg_graph_uri(backend, space_id, graph_id, kg_graph_uri)
                
                for obj_uri in related_objects:
                    # Get all triples for this object
                    obj_quads = await self._get_object_quads(backend, space_id, graph_id, obj_uri)
                    delete_quads.extend(obj_quads)
                    
                self.logger.info(f"Built {len(delete_quads)} delete quads for slot graph")
            else:
                # Fallback: just delete the slot itself
                slot_quads = await self._get_object_quads(backend, space_id, graph_id, slot_uri)
                delete_quads.extend(slot_quads)
                self.logger.info(f"Built {len(delete_quads)} delete quads for single slot")
            
            return delete_quads
            
        except Exception as e:
            self.logger.error(f"Error building delete quads for slot {slot_uri}: {e}")
            return []
    
    async def _build_insert_quads_for_objects(self, objects: List[GraphObject], graph_id: str) -> List[tuple]:
        """
        Build insert quads for VitalSigns objects.
        
        Args:
            objects: List of VitalSigns GraphObjects
            graph_id: Graph identifier (complete URI)
            
        Returns:
            List[tuple]: List of (subject, predicate, object, graph) tuples to insert
        """
        try:
            self.logger.info(f"Building insert quads for {len(objects)} objects")
            
            from rdflib import Graph, URIRef
            
            # Create RDF graph and add objects
            rdf_graph = Graph()
            
            # Convert each object to RDF and add to graph
            for obj in objects:
                try:
                    # Use VitalSigns to_rdf method to get RDF representation
                    obj_rdf = obj.to_rdf()
                    # Parse the RDF and add to our graph
                    rdf_graph.parse(data=obj_rdf, format='turtle')
                except Exception as e:
                    self.logger.warning(f"Failed to convert object to RDF: {e}")
                    continue
            
            # Convert to quads
            graph_uri = URIRef(graph_id)
            insert_quads = []
            
            for s, p, o in rdf_graph:
                # Keep RDFLib objects to preserve type information
                insert_quads.append((s, p, o, graph_uri))
            
            self.logger.info(f"Built {len(insert_quads)} insert quads")
            return insert_quads
            
        except Exception as e:
            self.logger.error(f"Error building insert quads: {e}")
            return []
    
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
            # Use SPARQL query to get kGGraphURI
            sparql_query = f"""
            SELECT ?kgGraphURI WHERE {{
                GRAPH <{graph_id}> {{
                    <{slot_uri}> <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> ?kgGraphURI .
                }}
            }}
            """
            
            result = await backend.execute_sparql_query(space_id, sparql_query)
            
            # Extract kgGraphURI from SPARQL results
            if isinstance(result, dict) and 'results' in result:
                bindings = result.get('results', {}).get('bindings', [])
                if bindings and 'kgGraphURI' in bindings[0]:
                    return bindings[0]['kgGraphURI']['value']
            elif isinstance(result, list) and result:
                if isinstance(result[0], dict) and 'kgGraphURI' in result[0]:
                    return result[0]['kgGraphURI']['value']
            
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
            
            # Extract URIs from SPARQL results
            object_uris = []
            if isinstance(result, dict) and 'results' in result:
                bindings = result.get('results', {}).get('bindings', [])
                for binding in bindings:
                    if 'uri' in binding:
                        uri_value = binding['uri']['value']
                        object_uris.append(uri_value)
            elif isinstance(result, list):
                for binding in result:
                    if isinstance(binding, dict) and 'uri' in binding:
                        uri_value = binding['uri']['value']
                        object_uris.append(uri_value)
            
            return object_uris
            
        except Exception as e:
            self.logger.error(f"Error finding objects by kgGraphURI {kg_graph_uri}: {e}")
            return []
    
    async def _get_object_quads(self, backend, space_id: str, graph_id: str, obj_uri: str) -> List[tuple]:
        """
        Get all quads for a specific object.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            obj_uri: URI of the object
            
        Returns:
            List[tuple]: List of (subject, predicate, object, graph) tuples
        """
        try:
            # Use SPARQL query to get all triples for the object
            # Note: Include ALL triples (including materialized) for deletion during updates
            sparql_query = f"""
            SELECT ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    <{obj_uri}> ?p ?o .
                }}
            }}
            """
            
            result = await backend.execute_sparql_query(space_id, sparql_query)
            
            # Convert to quads
            from rdflib import URIRef, Literal
            
            quads = []
            graph_uri = URIRef(graph_id)
            subject_uri = URIRef(obj_uri)
            
            if isinstance(result, dict) and 'results' in result:
                bindings = result.get('results', {}).get('bindings', [])
                for binding in bindings:
                    if 'p' in binding and 'o' in binding:
                        predicate = URIRef(binding['p']['value'])
                        
                        # Handle object type (URI or Literal)
                        obj_data = binding['o']
                        if obj_data['type'] == 'uri':
                            obj = URIRef(obj_data['value'])
                        else:
                            obj = Literal(obj_data['value'])
                        
                        quads.append((subject_uri, predicate, obj, graph_uri))
            elif isinstance(result, list):
                for binding in result:
                    if isinstance(binding, dict) and 'p' in binding and 'o' in binding:
                        predicate = URIRef(binding['p']['value'])
                        
                        # Handle object type (URI or Literal)
                        obj_data = binding['o']
                        if obj_data['type'] == 'uri':
                            obj = URIRef(obj_data['value'])
                        else:
                            obj = Literal(obj_data['value'])
                        
                        quads.append((subject_uri, predicate, obj, graph_uri))
            
            return quads
            
        except Exception as e:
            self.logger.error(f"Error getting quads for object {obj_uri}: {e}")
            return []
