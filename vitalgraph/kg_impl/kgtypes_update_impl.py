"""
KGTypes UPDATE Implementation for VitalGraph.

This module provides the implementation for updating KG types in the backend storage,
using the atomic update_quads function for true atomicity and consistency with proper
dual-write coordination (PostgreSQL first, then Fuseki).
"""

import logging
from typing import List, Optional, Dict, Any, Union
from ..model.kgtypes_model import KGTypeFilter

# VitalSigns imports for proper integration
import vital_ai_vitalsigns as vitalsigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# KG domain model imports
from ai_haley_kg_domain.model.KGType import KGType

# RDFLib helper for datatype preservation in SPARQL result parsing
from vitalgraph.kg_impl.kgentity_frame_create_impl import _sparql_binding_to_rdflib


class KGTypesUpdateProcessor:
    """
    Processor for KGTypes update operations with atomic backend integration.
    
    Handles complete type replacement using atomic update_quads operation for true
    atomicity and consistency with proper dual-write coordination.
    
    Atomic Update Strategy:
    1. Build delete quads for existing type data (type + related objects)
    2. Build insert quads for new type data (VitalSigns objects to triples)
    3. Execute atomic update_quads operation (single transaction)
    4. PostgreSQL-first dual-write with Fuseki synchronization
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Initialize VitalSigns for vitaltype validation
        self.vitalsigns = None
        self.ontology_manager = None
        self._init_vitalsigns()
    
    def _init_vitalsigns(self):
        """Initialize VitalSigns and ontology manager."""
        try:
            self.vitalsigns = VitalSigns()
            self.ontology_manager = self.vitalsigns.get_ontology_manager()
            self.logger.info("VitalSigns ontology manager initialized")
        except Exception as e:
            self.logger.warning(f"Failed to initialize VitalSigns ontology manager: {e}")
            self.ontology_manager = None
    
    def get_kgtype_vitaltypes(self) -> List[str]:
        """
        Get all vitaltype URIs for KGType and its subclasses.
        
        Returns:
            List of vitaltype URIs including KGType and all its subclasses
        """
        kgtype_uri = "http://vital.ai/ontology/haley-ai-kg#KGType"
        vitaltypes = [kgtype_uri]  # Start with base KGType
        
        if self.ontology_manager:
            try:
                # Get all subclasses of KGType
                subclass_list = self.ontology_manager.get_subclass_uri_list(kgtype_uri)
                vitaltypes.extend(subclass_list)
                self.logger.info(f"Found {len(subclass_list)} KGType subclasses")
                self.logger.debug(f"KGType vitaltypes: {vitaltypes}")
            except Exception as e:
                self.logger.warning(f"Failed to get KGType subclasses: {e}")
        else:
            self.logger.warning("Ontology manager not available, using only base KGType type")
        
        return vitaltypes
    
    def validate_kgtype_vitaltype(self, vitaltype_uri: str) -> bool:
        """
        Validate that a vitaltype URI is a KGType or KGType subclass.
        
        Args:
            vitaltype_uri: The vitaltype URI to validate
            
        Returns:
            True if the vitaltype is a valid KGType or subclass
        """
        valid_vitaltypes = self.get_kgtype_vitaltypes()
        is_valid = vitaltype_uri in valid_vitaltypes
        
        if not is_valid:
            self.logger.warning(f"Invalid KGType vitaltype: {vitaltype_uri}")
            self.logger.debug(f"Valid KGType vitaltypes: {valid_vitaltypes}")
        
        return is_valid
    
    async def update_kgtype(self, backend, space_id: str, graph_id: str, 
                           kgtype_uri: str, updated_objects: List[GraphObject]) -> bool:
        """
        Update a single KGType using atomic update_quads operation.
        
        This method uses the validated atomic update_quads function for true atomicity
        instead of separate delete and insert operations.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_uri: URI of the KGType to update
            updated_objects: List of VitalSigns objects representing the updated type
            
        Returns:
            bool: True if update was successful, False otherwise
        """
        try:
            self.logger.info(f"🔄 Atomic KGType update: {kgtype_uri} in graph: {graph_id}")
            
            # Step 1: Build delete quads for existing type data
            delete_quads = await self._build_delete_quads_for_kgtype(backend, space_id, graph_id, kgtype_uri)
            
            # Step 2: Build insert quads for updated type data
            insert_quads = await self._build_insert_quads_for_objects(updated_objects, graph_id)
            
            # Step 3: Execute atomic update using validated update_quads function
            success = await backend.update_quads(space_id, graph_id, delete_quads, insert_quads)
            
            if success:
                self.logger.info(f"✅ Successfully updated KGType atomically: {kgtype_uri}")
                return True
            else:
                self.logger.error(f"❌ Atomic KGType update failed: {kgtype_uri}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error in atomic KGType update {kgtype_uri}: {e}")
            return False
    
    async def update_kgtypes_batch(self, backend, space_id: str, graph_id: str, 
                                  kgtype_updates: Dict[str, List[GraphObject]]) -> List[str]:
        """
        Update multiple KGTypes using atomic operations for each.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_updates: Dictionary mapping KGType URIs to their updated objects
            
        Returns:
            List[str]: List of successfully updated KGType URIs
        """
        try:
            self.logger.info(f"Batch updating {len(kgtype_updates)} KGTypes in graph: {graph_id}")
            
            updated_uris = []
            failed_uris = []
            
            for kgtype_uri, updated_objects in kgtype_updates.items():
                try:
                    # Update each type individually using atomic operation
                    success = await self.update_kgtype(backend, space_id, graph_id, kgtype_uri, updated_objects)
                    
                    if success:
                        updated_uris.append(kgtype_uri)
                    else:
                        failed_uris.append(kgtype_uri)
                        self.logger.warning(f"Failed to update KGType {kgtype_uri}")
                        
                except Exception as e:
                    failed_uris.append(kgtype_uri)
                    self.logger.error(f"Error updating KGType {kgtype_uri}: {e}")
            
            # Log results
            if len(updated_uris) == len(kgtype_updates):
                self.logger.info(f"Successfully updated all {len(updated_uris)} KGTypes")
            elif len(updated_uris) > 0:
                self.logger.warning(f"Partial success: updated {len(updated_uris)}/{len(kgtype_updates)} KGTypes")
            else:
                self.logger.error(f"Failed to update any KGTypes")
            
            return updated_uris
                
        except Exception as e:
            self.logger.error(f"Error in batch KGType update operation: {e}")
            return []
    
    async def kgtype_exists(self, backend, space_id: str, graph_id: str, kgtype_uri: str) -> bool:
        """
        Check if a KGType exists in the backend before updating.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_uri: URI of the KGType to check
            
        Returns:
            bool: True if KGType exists, False otherwise
        """
        try:
            # Use SELECT query instead of ASK for more reliable existence checking
            check_query = f"""
            SELECT ?s WHERE {{
                GRAPH <{graph_id}> {{
                    <{kgtype_uri}> ?p ?o .
                    BIND(<{kgtype_uri}> AS ?s)
                }}
            }} LIMIT 1
            """
            
            self.logger.info(f"🔍 Checking KGType existence: {kgtype_uri}")
            result = await backend.execute_sparql_query(space_id, check_query)
            
            # If we get any results, the KGType exists
            if isinstance(result, list):
                exists = len(result) > 0
                self.logger.info(f"🔍 KGType existence check result: {exists} (found {len(result)} results)")
                return exists
            elif isinstance(result, dict):
                # Some backends might return dict format
                exists = bool(result)
                self.logger.info(f"🔍 KGType existence check result: {exists}")
                return exists
            
            # Default to False if we can't determine existence
            self.logger.warning(f"Could not determine KGType existence for {kgtype_uri} - unexpected result format: {type(result)}")
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking if KGType exists {kgtype_uri}: {e}")
            return False
    
    async def _build_delete_quads_for_kgtype(self, backend, space_id: str, graph_id: str, kgtype_uri: str) -> List[tuple]:
        """
        Build delete quads for existing KGType data that needs to be replaced.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier
            kgtype_uri: URI of the KGType being updated
            
        Returns:
            List[tuple]: List of quad tuples (subject, predicate, object, graph) to delete
        """
        try:
            delete_quads = []
            
            self.logger.info(f"🔍 Building delete quads for KGType: {kgtype_uri}")
            
            # Query to find all triples for this KGType
            # KGTypes are typically standalone objects without complex relationships
            find_kgtype_data_query = f"""
            SELECT DISTINCT ?subject ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    <{kgtype_uri}> ?predicate ?object .
                    BIND(<{kgtype_uri}> AS ?subject)
                }}
            }}
            """
            
            self.logger.info(f"🔍 Delete query for KGType: {kgtype_uri}")
            results = await backend.execute_sparql_query(space_id, find_kgtype_data_query)
            
            # Handle dictionary response format from backend (same as delete processor)
            if isinstance(results, dict):
                results = results.get('results', {}).get('bindings', [])
            
            # Convert SPARQL results to delete quads
            if results:
                for binding in results:
                    # Use the actual variable names from the SPARQL query
                    subject = binding.get('subject', {}).get('value', '')
                    predicate = binding.get('predicate', {}).get('value', '')
                    # Reconstruct RDFLib object from full binding to preserve datatype/language
                    obj = _sparql_binding_to_rdflib(binding.get('object', ''))
                    
                    if subject and predicate and obj is not None:
                        delete_quads.append((subject, predicate, obj, graph_id))
            
            self.logger.info(f"🔍 Built {len(delete_quads)} delete quads for KGType")
            return delete_quads
            
        except Exception as e:
            self.logger.error(f"Error building delete quads for KGType: {e}")
            return []
    
    async def _build_insert_quads_for_objects(self, objects: List[GraphObject], graph_id: str) -> List[tuple]:
        """
        Build insert quads for new KGType data.
        
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
            
            self.logger.info(f"🔍 Built {len(insert_quads)} insert quads for KGType")
            return insert_quads
            
        except Exception as e:
            self.logger.error(f"Error building insert quads for KGType: {e}")
            return []
