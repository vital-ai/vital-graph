"""
KGRelations Delete Implementation

This module contains the core implementation logic for KGRelation deletion operations.
It provides backend-agnostic functions for deleting relations.
"""

import logging
from typing import List, Dict, Any

# Model imports
from ..model.kgrelations_model import RelationDeleteResponse

# Local imports
from .kg_backend_utils import KGBackendInterface, BackendOperationResult


class KGRelationsDeleteProcessor:
    """Processor for KGRelation deletion operations with backend abstraction."""
    
    def __init__(self, backend: KGBackendInterface):
        """
        Initialize with backend interface.
        
        Args:
            backend: Backend interface implementation
        """
        self.backend = backend
        self.logger = logging.getLogger(f"{__name__}.KGRelationsDeleteProcessor")
    
    async def delete_relations(self, space_id: str, graph_id: str, relation_uris: List[str]) -> RelationDeleteResponse:
        """
        Delete KG Relations by URIs.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            relation_uris: List of relation URIs to delete
            
        Returns:
            RelationDeleteResponse with deletion results
        """
        try:
            self.logger.info(f"Deleting {len(relation_uris)} KG Relations")
            
            if not relation_uris:
                return RelationDeleteResponse(
                    message="No relation URIs provided for deletion",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            deleted_uris = []
            
            for relation_uri in relation_uris:
                # Build SPARQL DELETE query with explicit DELETE/WHERE pattern
                delete_query = f"""
                DELETE {{
                    GRAPH <{graph_id}> {{
                        <{relation_uri}> ?p ?o .
                    }}
                }}
                WHERE {{
                    GRAPH <{graph_id}> {{
                        <{relation_uri}> ?p ?o .
                    }}
                }}
                """
                
                try:
                    # Execute delete
                    await self.backend.execute_sparql_update(space_id, delete_query)
                    deleted_uris.append(relation_uri)
                    self.logger.info(f"✅ Deleted relation: {relation_uri}")
                    
                except Exception as e:
                    self.logger.error(f"❌ Failed to delete relation {relation_uri}: {e}")
                    # Continue with other deletions
            
            return RelationDeleteResponse(
                message=f"Successfully deleted {len(deleted_uris)} KG relations",
                deleted_count=len(deleted_uris),
                deleted_uris=deleted_uris
            )
            
        except Exception as e:
            self.logger.error(f"❌ Error deleting KG Relations: {e}")
            return RelationDeleteResponse(
                message=f"Failed to delete relations: {str(e)}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    async def check_relation_exists(self, space_id: str, graph_id: str, relation_uri: str) -> bool:
        """
        Check if a relation exists in the graph.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            relation_uri: URI of the relation to check
            
        Returns:
            bool: True if relation exists, False otherwise
        """
        try:
            check_query = f"""
            ASK {{
                GRAPH <{graph_id}> {{
                    <{relation_uri}> ?p ?o .
                }}
            }}
            """
            
            result = await self.backend.execute_sparql_query(space_id, check_query)
            
            # Handle dictionary response format
            if isinstance(result, dict):
                return result.get('boolean', False)
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking relation existence {relation_uri}: {e}")
            return False
