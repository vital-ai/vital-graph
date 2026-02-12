"""
KGEntity Update Implementation for VitalGraph.

This module provides the implementation for updating KG entities in the backend storage,
using the DELETE + INSERT pattern for complete entity replacement with proper dual-write
coordination (PostgreSQL first, then Fuseki).
"""

import logging
import time
from typing import List, Optional, Dict, Any, Union
from ..model.kgentities_model import EntityUpdateResponse

# VitalSigns imports for proper integration
import vital_ai_vitalsigns as vitalsigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# RDFLib helper for datatype preservation in SPARQL result parsing
from vitalgraph.kg_impl.kgentity_frame_create_impl import _sparql_binding_to_rdflib

# KG domain model imports
from ai_haley_kg_domain.model.KGEntity import KGEntity


class KGEntityUpdateProcessor:
    """
    Processor for KGEntity update operations with atomic backend integration.
    
    Handles complete entity replacement using atomic update_quads operation for true
    atomicity and consistency with proper dual-write coordination.
    
    Atomic Update Strategy:
    1. Build delete quads for existing entity data (entity + related objects via kGGraphURI)
    2. Build insert quads for new entity data (VitalSigns objects to triples)
    3. Execute atomic update_quads operation (single transaction)
    4. PostgreSQL-first dual-write with Fuseki synchronization
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def update_entity(self, backend, space_id: str, graph_id: str, 
                           entity_uri: str, updated_objects: List[GraphObject]) -> EntityUpdateResponse:
        """
        Update a single KGEntity using atomic update_quads operation.
        
        This method now uses the validated atomic update_quads function for true atomicity
        instead of separate delete and insert operations.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            entity_uri: URI of the entity to update
            updated_objects: List of VitalSigns objects representing the updated entity
            
        Returns:
            EntityUpdateResponse: Response indicating success/failure of update
        """
        try:
            t0 = time.time()
            self.logger.info(f"🔄 Entity update START: {entity_uri} ({len(updated_objects)} objects)")
            
            # Step 1: Build delete quads for existing entity data
            t1 = time.time()
            delete_quads = await self._build_delete_quads_for_entity(backend, space_id, graph_id, entity_uri)
            t2 = time.time()
            self.logger.info(f"🔄 Step 1 build_delete_quads: {len(delete_quads)} quads in {t2-t1:.3f}s")
            
            # Step 2: Build insert quads for updated entity data
            insert_quads = await self._build_insert_quads_for_objects(updated_objects, graph_id)
            t3 = time.time()
            self.logger.info(f"🔄 Step 2 build_insert_quads: {len(insert_quads)} quads in {t3-t2:.3f}s")
            
            # Step 3: Execute atomic update using validated update_quads function
            success = await backend.update_quads(space_id, graph_id, delete_quads, insert_quads)
            t4 = time.time()
            self.logger.info(f"🔄 Step 3 update_quads: success={success} in {t4-t3:.3f}s")
            self.logger.info(f"🔄 Entity update DONE: {entity_uri} total={t4-t0:.3f}s")
            
            if success:
                return EntityUpdateResponse(
                    message=f"Successfully updated entity: {entity_uri}",
                    updated_uri=entity_uri
                )
            else:
                self.logger.error(f"❌ Atomic entity update failed: {entity_uri}")
                return EntityUpdateResponse(
                    message=f"Failed to update entity atomically: {entity_uri}",
                    updated_uri=""
                )
                
        except Exception as e:
            self.logger.error(f"Error in atomic entity update {entity_uri}: {e}")
            return EntityUpdateResponse(
                message=f"Error updating entity: {str(e)}",
                updated_uri=""
            )
    
    async def update_entities_batch(self, backend, space_id: str, graph_id: str, 
                                   entity_updates: Dict[str, List[GraphObject]]) -> EntityUpdateResponse:
        """
        Update multiple entities using complete replacement (DELETE + INSERT) for each.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            entity_updates: Dictionary mapping entity URIs to their updated objects
            
        Returns:
            EntityUpdateResponse: Response indicating success/failure of batch update
        """
        try:
            self.logger.debug(f"Batch updating {len(entity_updates)} entities in graph: {graph_id}")
            
            updated_uris = []
            failed_uris = []
            
            for entity_uri, updated_objects in entity_updates.items():
                try:
                    # Update each entity individually using the same DELETE + INSERT pattern
                    result = await self.update_entity(backend, space_id, graph_id, entity_uri, updated_objects)
                    
                    if result.updated_uri:
                        updated_uris.append(entity_uri)
                    else:
                        failed_uris.append(entity_uri)
                        self.logger.warning(f"Failed to update entity {entity_uri}: {result.message}")
                        
                except Exception as e:
                    failed_uris.append(entity_uri)
                    self.logger.error(f"Error updating entity {entity_uri}: {e}")
            
            # Determine overall success
            if len(updated_uris) == len(entity_updates):
                self.logger.debug(f"Successfully updated all {len(updated_uris)} entities")
                return EntityUpdateResponse(
                    message=f"Successfully updated {len(updated_uris)} entities",
                    updated_uri=",".join(updated_uris)
                )
            elif len(updated_uris) > 0:
                self.logger.warning(f"Partial success: updated {len(updated_uris)}/{len(entity_updates)} entities")
                return EntityUpdateResponse(
                    message=f"Partial success: updated {len(updated_uris)}/{len(entity_updates)} entities. Failed: {failed_uris}",
                    updated_uri=",".join(updated_uris)
                )
            else:
                self.logger.error(f"Failed to update any entities")
                return EntityUpdateResponse(
                    message=f"Failed to update any entities. All {len(failed_uris)} updates failed.",
                    updated_uri=""
                )
                
        except Exception as e:
            self.logger.error(f"Error in batch update operation: {e}")
            return EntityUpdateResponse(
                message=f"Error in batch update: {str(e)}",
                updated_uri=""
            )
    
    
    async def entity_exists(self, backend, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """
        Check if an entity exists in the backend before updating.
        
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
            
            # Fallback: entity does not exist if we can't check
            self.logger.warning(f"Cannot check entity existence for {entity_uri} - backend method not available")
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking if entity exists {entity_uri}: {e}")
            return False
    
    async def _build_delete_quads_for_entity(self, backend, space_id: str, graph_id: str, entity_uri: str) -> List[tuple]:
        """
        Build delete quads for existing entity data that needs to be replaced.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: URI of the entity being updated
            
        Returns:
            List[tuple]: List of quad tuples (subject, predicate, object, graph) to delete
        """
        try:
            delete_quads = []
            
            self.logger.debug(f"🔍 Building delete quads for entity: {entity_uri}")
            
            # Query to find all triples for this entity and related objects via kGGraphURI
            find_entity_data_query = f"""
            SELECT DISTINCT ?subject ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    {{
                        # Get the entity itself
                        <{entity_uri}> ?predicate ?object .
                        BIND(<{entity_uri}> AS ?subject)
                    }}
                    UNION
                    {{
                        # Get objects with hasKGGraphURI pointing to this entity
                        ?subject <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> <{entity_uri}> .
                        ?subject ?predicate ?object .
                    }}
                }}
            }}
            """
            
            self.logger.debug(f"🔍 Delete query for entity: {entity_uri}")
            results = await backend.execute_sparql_query(space_id, find_entity_data_query)
            
            # Convert SPARQL results to delete quads — handle both result formats
            bindings = []
            if isinstance(results, dict) and 'results' in results and isinstance(results['results'], dict):
                bindings = results['results'].get('bindings', [])
            elif isinstance(results, list):
                bindings = results
            
            for result in bindings:
                if isinstance(result, dict) and all(key in result for key in ['subject', 'predicate', 'object']):
                    subject = str(result['subject'].get('value', '')) if isinstance(result['subject'], dict) else str(result['subject'])
                    predicate = str(result['predicate'].get('value', '')) if isinstance(result['predicate'], dict) else str(result['predicate'])
                    # Reconstruct RDFLib object from full binding to preserve datatype/language
                    obj = _sparql_binding_to_rdflib(result.get('object', ''))
                    
                    if subject and predicate and obj is not None:
                        delete_quads.append((subject, predicate, obj, graph_id))
            
            self.logger.debug(f"🔍 Built {len(delete_quads)} delete quads for entity")
            return delete_quads
            
        except Exception as e:
            self.logger.error(f"Error building delete quads for entity: {e}")
            return []
    
    async def _build_insert_quads_for_objects(self, objects: List[GraphObject], graph_id: str) -> List[tuple]:
        """
        Build insert quads for new entity data.
        
        Args:
            objects: List of VitalSigns objects to insert
            graph_id: Graph identifier
            
        Returns:
            List[tuple]: List of quad tuples (subject, predicate, object, graph) to insert
        """
        try:
            # Convert VitalSigns objects to triples
            triples = GraphObject.to_triples_list(objects)
            
            # Convert triples to quads by adding graph_id
            # Keep RDFLib objects (especially Literal with datatype/language)
            # so downstream formatters can preserve type information.
            insert_quads = []
            for triple in triples:
                s, p, o = triple
                insert_quads.append((str(s), str(p), o, graph_id))
            
            self.logger.debug(f"🔍 Built {len(insert_quads)} insert quads for entity")
            return insert_quads
            
        except Exception as e:
            self.logger.error(f"Error building insert quads for entity: {e}")
            return []
