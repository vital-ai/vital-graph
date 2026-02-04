"""
KGRelations Create Implementation

This module contains the core implementation logic for KGRelation creation operations.
It provides backend-agnostic functions that can be used by both REST endpoints and
direct API calls, with proper error handling and validation.
"""

import logging
from typing import List, Dict, Any, Optional, Union
from enum import Enum

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation

# Model imports
from ..model.kgrelations_model import RelationCreateResponse, RelationUpdateResponse, RelationUpsertResponse

# Local imports
from .kg_backend_utils import KGBackendInterface, BackendOperationResult


class OperationMode(str, Enum):
    """Operation modes for relation lifecycle management."""
    CREATE = "create"
    UPDATE = "update"
    UPSERT = "upsert"


class KGRelationsCreateProcessor:
    """Processor for KGRelation creation operations with backend abstraction."""
    
    def __init__(self, backend: KGBackendInterface):
        """
        Initialize with backend interface.
        
        Args:
            backend: Backend interface implementation
        """
        self.backend = backend
        self.logger = logging.getLogger(f"{__name__}.KGRelationsCreateProcessor")
    
    async def create_or_update_relations(self, space_id: str, graph_id: str, 
                                        vitalsigns_objects: List[GraphObject], 
                                        operation_mode: OperationMode) -> Union[RelationCreateResponse, RelationUpdateResponse, RelationUpsertResponse]:
        """
        Create, update, or upsert KG relations using backend abstraction.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            vitalsigns_objects: List of VitalSigns GraphObjects (Edge_hasKGRelation)
            operation_mode: CREATE, UPDATE, or UPSERT
            
        Returns:
            RelationCreateResponse, RelationUpdateResponse, or RelationUpsertResponse
        """
        try:
            self.logger.debug(f"Processing KG relations in space '{space_id}', graph '{graph_id}', "
                           f"operation_mode='{operation_mode}'")
            
            # Step 1: Validate VitalSigns objects
            if not vitalsigns_objects:
                return self._create_error_response(operation_mode, "No valid objects provided")
            
            self.logger.debug(f"Processing {len(vitalsigns_objects)} VitalSigns objects")
            
            # Step 2: Extract and validate relations
            relations = [obj for obj in vitalsigns_objects if isinstance(obj, Edge_hasKGRelation)]
            
            if not relations:
                return self._create_error_response(operation_mode, "No Edge_hasKGRelation objects found in request")
            
            self.logger.debug(f"Found {len(relations)} relation objects")
            
            # Step 3: Handle operation mode
            if operation_mode == OperationMode.CREATE:
                return await self._handle_create_mode(space_id, graph_id, relations)
            elif operation_mode == OperationMode.UPDATE:
                return await self._handle_update_mode(space_id, graph_id, relations)
            else:  # UPSERT
                return await self._handle_upsert_mode(space_id, graph_id, relations)
            
        except Exception as e:
            self.logger.error(f"Error processing KG relations: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return self._create_error_response(operation_mode, str(e))
    
    async def _handle_create_mode(self, space_id: str, graph_id: str, relations: List) -> RelationCreateResponse:
        """Handle CREATE mode: store relation objects."""
        try:
            # Store all relation objects
            result = await self.backend.store_objects(space_id, graph_id, relations)
            
            if result.success:
                relation_uris = [str(relation.URI) for relation in relations if hasattr(relation, 'URI')]
                return RelationCreateResponse(
                    message=f"Successfully created {len(relations)} KG relations",
                    created_count=len(relations),
                    created_uris=relation_uris
                )
            else:
                return RelationCreateResponse(
                    message=f"Failed to store relations: {result.message}",
                    created_count=0,
                    created_uris=[]
                )
                
        except Exception as e:
            self.logger.error(f"Error in create mode: {e}")
            return RelationCreateResponse(
                message=f"Error creating relations: {str(e)}",
                created_count=0,
                created_uris=[]
            )
    
    async def _handle_update_mode(self, space_id: str, graph_id: str, relations: List) -> RelationUpdateResponse:
        """Handle UPDATE mode: delete existing then store updated relations."""
        try:
            # Delete existing relation data first (for clean update)
            for relation in relations:
                if hasattr(relation, 'URI'):
                    relation_uri = str(relation.URI)
                    await self.backend.delete_object(space_id, graph_id, relation_uri)
            
            # Store updated objects
            result = await self.backend.store_objects(space_id, graph_id, relations)
            
            if result.success:
                # Return first relation URI as updated_uri (singular)
                updated_uri = str(relations[0].URI) if relations and hasattr(relations[0], 'URI') else ""
                return RelationUpdateResponse(
                    message=f"Successfully updated {len(relations)} KG relations",
                    updated_uri=updated_uri
                )
            else:
                return RelationUpdateResponse(
                    message=f"Failed to update relations: {result.message}",
                    updated_uri=""
                )
                
        except Exception as e:
            self.logger.error(f"Error in update mode: {e}")
            return RelationUpdateResponse(
                message=f"Error updating relations: {str(e)}",
                updated_uri=""
            )
    
    async def _handle_upsert_mode(self, space_id: str, graph_id: str, relations: List) -> RelationUpsertResponse:
        """Handle UPSERT mode: create if not exists, update if exists."""
        try:
            # Delete existing relation data for clean upsert
            for relation in relations:
                if hasattr(relation, 'URI'):
                    relation_uri = str(relation.URI)
                    # Check if exists and delete
                    if await self.backend.object_exists(space_id, graph_id, relation_uri):
                        await self.backend.delete_object(space_id, graph_id, relation_uri)
            
            # Store all objects (both new and updated)
            result = await self.backend.store_objects(space_id, graph_id, relations)
            
            if result.success:
                relation_uris = [str(relation.URI) for relation in relations if hasattr(relation, 'URI')]
                return RelationUpsertResponse(
                    message=f"Successfully upserted {len(relations)} KG relations",
                    created_count=len(relations),
                    created_uris=relation_uris
                )
            else:
                return RelationUpsertResponse(
                    message=f"Failed to upsert relations: {result.message}",
                    created_count=0,
                    created_uris=[]
                )
                
        except Exception as e:
            self.logger.error(f"Error in upsert mode: {e}")
            return RelationUpsertResponse(
                message=f"Error upserting relations: {str(e)}",
                created_count=0,
                created_uris=[]
            )
    
    async def _check_relation_exists(self, space_id: str, graph_id: str, relation_uri: str) -> bool:
        """Check if a relation exists in the graph."""
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
            self.logger.error(f"Error checking relation existence: {e}")
            return False
    
    async def _delete_relation(self, space_id: str, graph_id: str, relation_uri: str) -> BackendOperationResult:
        """Delete a relation from the graph."""
        try:
            delete_query = f"""
            DELETE WHERE {{
                GRAPH <{graph_id}> {{
                    <{relation_uri}> ?p ?o .
                }}
            }}
            """
            
            await self.backend.execute_sparql_update(space_id, delete_query)
            
            return BackendOperationResult(
                success=True,
                message=f"Successfully deleted relation {relation_uri}"
            )
            
        except Exception as e:
            self.logger.error(f"Error deleting relation: {e}")
            return BackendOperationResult(
                success=False,
                message=f"Failed to delete relation: {str(e)}",
                error=str(e)
            )
    
    def _create_error_response(self, operation_mode: OperationMode, error_message: str) -> Union[RelationCreateResponse, RelationUpdateResponse, RelationUpsertResponse]:
        """Create an error response based on operation mode."""
        if operation_mode == OperationMode.CREATE:
            return RelationCreateResponse(
                message=f"Failed to create relations: {error_message}",
                created_count=0,
                created_uris=[]
            )
        elif operation_mode == OperationMode.UPDATE:
            return RelationUpdateResponse(
                message=f"Failed to update relations: {error_message}",
                updated_count=0,
                updated_uris=[]
            )
        else:  # UPSERT
            return RelationUpsertResponse(
                message=f"Failed to upsert relations: {error_message}",
                created_count=0,
                created_uris=[]
            )
