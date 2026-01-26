"""
KGTypes CREATE Implementation for VitalGraph

This module provides atomic CREATE operations for KGTypes using the proven update_quads function.
Implements CREATE and batch CREATE operations with proper VitalSigns integration.
"""

import logging
from typing import List, Dict, Any, Optional
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGType import KGType
from .kg_backend_utils import FusekiPostgreSQLBackendAdapter


class KGTypesCreateProcessor:
    """Processor for atomic KGTypes CREATE operations."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.KGTypesCreateProcessor")
    
    async def create_kgtype(self, backend, space_id: str, graph_id: str, kgtype_object: GraphObject) -> str:
        """
        Create a single KGType atomically using update_quads.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_object: VitalSigns KGType object to create
            
        Returns:
            str: URI of the created KGType
        """
        try:
            self.logger.info(f"🔄 Atomic KGType create: {kgtype_object.URI} in graph: {graph_id}")
            
            # Check if KGType already exists
            if await self.kgtype_exists(backend, space_id, graph_id, str(kgtype_object.URI)):
                raise ValueError(f"KGType {kgtype_object.URI} already exists. Use UPDATE mode to modify existing types.")
            
            # Build insert quads for the new KGType
            insert_quads = self._build_insert_quads_for_kgtype(kgtype_object, graph_id)
            
            self.logger.info(f"🔍 Built {len(insert_quads)} insert quads for KGType")
            
            # Perform atomic create using update_quads (no delete quads needed for CREATE)
            delete_quads = []  # Empty for CREATE operation
            
            success = await backend.update_quads(
                space_id=space_id,
                graph_id=graph_id,
                delete_quads=delete_quads,
                insert_quads=insert_quads
            )
            
            if success:
                self.logger.info(f"✅ Successfully created KGType atomically: {kgtype_object.URI}")
                return str(kgtype_object.URI)
            else:
                raise Exception("Failed to create KGType - update_quads returned False")
                
        except Exception as e:
            self.logger.error(f"❌ Failed to create KGType {kgtype_object.URI}: {e}")
            raise
    
    async def create_kgtypes_batch(self, backend, space_id: str, graph_id: str, kgtype_objects: List[GraphObject]) -> List[str]:
        """
        Create multiple KGTypes atomically in a single transaction.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_objects: List of VitalSigns KGType objects to create
            
        Returns:
            List[str]: List of URIs of the created KGTypes
        """
        try:
            self.logger.info(f"🔄 Atomic KGTypes batch create: {len(kgtype_objects)} types in graph: {graph_id}")
            
            # Check for existing KGTypes
            for kgtype_obj in kgtype_objects:
                if await self.kgtype_exists(backend, space_id, graph_id, str(kgtype_obj.URI)):
                    raise ValueError(f"KGType {kgtype_obj.URI} already exists. Use UPDATE mode to modify existing types.")
            
            # Build insert quads for all KGTypes
            all_insert_quads = []
            created_uris = []
            
            for kgtype_obj in kgtype_objects:
                insert_quads = self._build_insert_quads_for_kgtype(kgtype_obj, graph_id)
                all_insert_quads.extend(insert_quads)
                created_uris.append(str(kgtype_obj.URI))
            
            self.logger.info(f"🔍 Built {len(all_insert_quads)} insert quads for {len(kgtype_objects)} KGTypes")
            
            # Perform atomic batch create using update_quads
            delete_quads = []  # Empty for CREATE operation
            
            success = await backend.update_quads(
                space_id=space_id,
                graph_id=graph_id,
                delete_quads=delete_quads,
                insert_quads=all_insert_quads
            )
            
            if success:
                self.logger.info(f"✅ Successfully created {len(kgtype_objects)} KGTypes atomically")
                return created_uris
            else:
                raise Exception("Failed to create KGTypes - update_quads returned False")
                
        except Exception as e:
            self.logger.error(f"❌ Failed to create KGTypes batch: {e}")
            raise
    
    async def kgtype_exists(self, backend, space_id: str, graph_id: str, kgtype_uri: str) -> bool:
        """
        Check if a KGType exists in the backend.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_uri: URI of the KGType to check
            
        Returns:
            bool: True if KGType exists, False otherwise
        """
        try:
            # Use SELECT query for reliable existence checking
            check_query = f"""
            SELECT ?s WHERE {{
                GRAPH <{graph_id}> {{
                    <{kgtype_uri}> ?p ?o .
                    BIND(<{kgtype_uri}> AS ?s)
                }}
            }} LIMIT 1
            """
            
            result = await backend.execute_sparql_query(space_id, check_query)
            
            # Handle dictionary response format from backend
            if isinstance(result, dict):
                result = result.get('results', {}).get('bindings', [])
            
            # If we get any results, the KGType exists
            exists = result and len(result) > 0
            self.logger.info(f"🔍 KGType existence check: {exists} (URI: {kgtype_uri})")
            return exists
            
        except Exception as e:
            self.logger.error(f"Error checking if KGType exists {kgtype_uri}: {e}")
            return False
    
    def _build_insert_quads_for_kgtype(self, kgtype_object: GraphObject, graph_id: str) -> List[tuple]:
        """
        Build insert quads for a KGType object using VitalSigns native functionality.
        
        Args:
            kgtype_object: VitalSigns KGType object
            graph_id: Graph identifier (complete URI)
            
        Returns:
            List[tuple]: List of (subject, predicate, object, graph) tuads
        """
        try:
            # Use VitalSigns native to_triples() method
            triples = kgtype_object.to_triples()
            
            # Log the actual URI value to debug the format issue
            actual_uri = str(kgtype_object.URI)
            self.logger.info(f"🔍 KGType URI value: '{actual_uri}' (type: {type(kgtype_object.URI)})")
            self.logger.info(f"🔍 VitalSigns to_triples() generated {len(triples)} triples for KGType: {actual_uri}")
            
            # Log the first few triples for debugging
            for i, triple in enumerate(triples[:5]):
                self.logger.info(f"  Triple {i+1}: {triple}")
            if len(triples) > 5:
                self.logger.info(f"  ... and {len(triples) - 5} more triples")
            
            # Convert triples to quads by adding graph_id
            # Extract proper URI from VitalSigns CombinedProperty objects
            proper_uri = str(kgtype_object.URI)
            if proper_uri.startswith("[{'@id': '") and proper_uri.endswith("'}]"):
                # Extract the actual URI from the JSON-like format
                import json
                try:
                    parsed = json.loads(proper_uri)
                    if isinstance(parsed, list) and len(parsed) > 0 and '@id' in parsed[0]:
                        proper_uri = parsed[0]['@id']
                except:
                    pass  # Keep original if parsing fails
            
            quads = []
            for i, triple in enumerate(triples):
                if len(triple) == 3:  # (subject, predicate, object)
                    subject, predicate, obj = triple
                    
                    # Fix subject URI if it's malformed
                    subject_str = str(subject)
                    if subject_str.startswith("[{'@id': '") and subject_str.endswith("'}]"):
                        try:
                            parsed = json.loads(subject_str)
                            if isinstance(parsed, list) and len(parsed) > 0 and '@id' in parsed[0]:
                                subject_str = parsed[0]['@id']
                        except:
                            pass
                    
                    # Fix object URI if it's malformed
                    obj_str = str(obj)
                    if obj_str.startswith("[{'@id': '") and obj_str.endswith("'}]"):
                        try:
                            parsed = json.loads(obj_str)
                            if isinstance(parsed, list) and len(parsed) > 0 and '@id' in parsed[0]:
                                obj_str = parsed[0]['@id']
                        except:
                            pass
                    
                    quad = (subject_str, str(predicate), obj_str, graph_id)
                    quads.append(quad)
                    
                    # Log first few quads for debugging
                    if i < 5:
                        self.logger.info(f"  Quad {i+1}: {quad}")
                else:
                    self.logger.warning(f"Unexpected triple format: {triple}")
            
            self.logger.info(f"🔍 Built {len(quads)} quads from {len(triples)} triples for KGType: {kgtype_object.URI}")
            return quads
            
        except Exception as e:
            self.logger.error(f"Error building insert quads for KGType using VitalSigns: {e}")
            raise
