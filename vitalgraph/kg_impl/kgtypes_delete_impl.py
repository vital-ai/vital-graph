"""
KGTypes DELETE Implementation for VitalGraph

This module provides atomic DELETE operations for KGTypes using the proven update_quads function.
Implements DELETE and batch DELETE operations with proper validation.
"""

import logging
from typing import List, Dict, Any, Optional
from .kg_backend_utils import FusekiPostgreSQLBackendAdapter


class KGTypesDeleteProcessor:
    """Processor for atomic KGTypes DELETE operations."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.KGTypesDeleteProcessor")
    
    async def delete_kgtype(self, backend, space_id: str, graph_id: str, kgtype_uri: str) -> bool:
        """
        Delete a single KGType atomically using update_quads.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_uri: URI of the KGType to delete
            
        Returns:
            bool: True if deleted successfully, False if not found
        """
        try:
            self.logger.info(f"🔄 Atomic KGType delete: {kgtype_uri} in graph: {graph_id}")
            
            # Check if KGType exists before deleting
            if not await self.kgtype_exists(backend, space_id, graph_id, kgtype_uri):
                self.logger.info(f"KGType not found for deletion: {kgtype_uri}")
                return False
            
            # Build delete quads for the KGType
            delete_quads = await self._build_delete_quads_for_kgtype(backend, space_id, graph_id, kgtype_uri)
            
            self.logger.info(f"🔍 Built {len(delete_quads)} delete quads for KGType")
            
            # Perform atomic delete using update_quads (no insert quads needed for DELETE)
            insert_quads = []  # Empty for DELETE operation
            
            success = await backend.update_quads(
                space_id=space_id,
                graph_id=graph_id,
                delete_quads=delete_quads,
                insert_quads=insert_quads
            )
            
            if success:
                self.logger.info(f"✅ Successfully deleted KGType atomically: {kgtype_uri}")
                return True
            else:
                raise Exception("Failed to delete KGType - update_quads returned False")
                
        except Exception as e:
            self.logger.error(f"❌ Failed to delete KGType {kgtype_uri}: {e}")
            raise
    
    async def delete_kgtypes_batch(self, backend, space_id: str, graph_id: str, kgtype_uris: List[str]) -> int:
        """
        Delete multiple KGTypes atomically in a single transaction.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_uris: List of KGType URIs to delete
            
        Returns:
            int: Number of KGTypes successfully deleted
        """
        try:
            self.logger.info(f"🔄 Atomic KGTypes batch delete: {len(kgtype_uris)} types in graph: {graph_id}")
            
            # Check which KGTypes exist and build delete quads for them
            all_delete_quads = []
            deleted_count = 0
            
            for kgtype_uri in kgtype_uris:
                if await self.kgtype_exists(backend, space_id, graph_id, kgtype_uri):
                    delete_quads = await self._build_delete_quads_for_kgtype(backend, space_id, graph_id, kgtype_uri)
                    all_delete_quads.extend(delete_quads)
                    deleted_count += 1
                else:
                    self.logger.info(f"KGType not found for deletion: {kgtype_uri}")
            
            if deleted_count == 0:
                self.logger.info("No KGTypes found for deletion")
                return 0
            
            self.logger.info(f"🔍 Built {len(all_delete_quads)} delete quads for {deleted_count} KGTypes")
            
            # Perform atomic batch delete using update_quads
            insert_quads = []  # Empty for DELETE operation
            
            success = await backend.update_quads(
                space_id=space_id,
                graph_id=graph_id,
                delete_quads=all_delete_quads,
                insert_quads=insert_quads
            )
            
            if success:
                self.logger.info(f"✅ Successfully deleted {deleted_count} KGTypes atomically")
                return deleted_count
            else:
                raise Exception("Failed to delete KGTypes - update_quads returned False")
                
        except Exception as e:
            self.logger.error(f"❌ Failed to delete KGTypes batch: {e}")
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
            return exists
            
        except Exception as e:
            self.logger.error(f"Error checking if KGType exists {kgtype_uri}: {e}")
            return False
    
    async def _build_delete_quads_for_kgtype(self, backend, space_id: str, graph_id: str, kgtype_uri: str) -> List[tuple]:
        """
        Build delete quads for a KGType by querying existing data.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_uri: URI of the KGType to delete
            
        Returns:
            List[tuple]: List of (subject, predicate, object, graph) tuples to delete
        """
        try:
            self.logger.info(f"🔍 Building delete quads for KGType: {kgtype_uri}")
            
            # Query to get all triples for this KGType
            # Note: Include ALL triples (including materialized) for deletion
            delete_query = f"""
            SELECT ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    <{kgtype_uri}> ?p ?o .
                }}
            }}
            """
            
            self.logger.info(f"🔍 Delete query for KGType: {kgtype_uri}")
            result = await backend.execute_sparql_query(space_id, delete_query)
            
            # Handle dictionary response format from backend
            if isinstance(result, dict):
                result = result.get('results', {}).get('bindings', [])
            
            # Build delete quads from query results
            delete_quads = []
            if result:
                for binding in result:
                    predicate = binding.get('p', {}).get('value', '')
                    obj_value = binding.get('o', {}).get('value', '')
                    
                    if predicate and obj_value:
                        delete_quads.append((kgtype_uri, predicate, obj_value, graph_id))
            
            self.logger.info(f"🔍 Built {len(delete_quads)} delete quads for KGType")
            return delete_quads
            
        except Exception as e:
            self.logger.error(f"Error building delete quads for KGType {kgtype_uri}: {e}")
            raise
