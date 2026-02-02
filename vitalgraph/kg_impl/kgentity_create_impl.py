"""
KGEntity Create Implementation

This module contains the core implementation logic for KGEntity creation operations.
It provides backend-agnostic functions that can be used by both REST endpoints and
direct API calls, with proper error handling and validation.
"""

import logging
from typing import List, Dict, Any, Optional, Union
from enum import Enum

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame

# Model imports
from ..model.kgentities_model import EntityCreateResponse, EntityUpdateResponse

# Local imports
from .kg_backend_utils import KGBackendInterface, BackendOperationResult
from .kg_validation_utils import KGEntityValidator, KGGroupingURIManager, ValidationResult


class OperationMode(str, Enum):
    """Operation modes for entity lifecycle management."""
    CREATE = "create"
    UPDATE = "update"
    UPSERT = "upsert"


class KGEntityCreateProcessor:
    """Processor for KGEntity creation operations with backend abstraction."""
    
    def __init__(self, backend: KGBackendInterface):
        """
        Initialize with backend interface.
        
        Args:
            backend: Backend interface implementation
        """
        self.backend = backend
        self.validator = KGEntityValidator()
        self.grouping_manager = KGGroupingURIManager()
        self.logger = logging.getLogger(f"{__name__}.KGEntityCreateProcessor")
    
    async def create_or_update_entities(self, space_id: str, graph_id: str, 
                                      vitalsigns_objects: List[GraphObject], operation_mode: OperationMode,
                                      parent_uri: Optional[str] = None) -> Union[EntityCreateResponse, EntityUpdateResponse]:
        """
        Create or update KG entities using backend abstraction.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            vitalsigns_objects: List of VitalSigns GraphObjects to create/update
            operation_mode: CREATE, UPDATE, or UPSERT
            parent_uri: Optional parent entity URI
            
        Returns:
            EntityCreateResponse or EntityUpdateResponse based on operation mode
        """
        try:
            self.logger.info(f"Processing KG entities in space '{space_id}', graph '{graph_id}', "
                           f"operation_mode='{operation_mode}', parent_uri='{parent_uri}'")
            
            # Step 1: Validate VitalSigns objects
            if not vitalsigns_objects:
                return self._create_error_response(operation_mode, "No valid objects provided")
            
            self.logger.info(f"Processing {len(vitalsigns_objects)} VitalSigns objects")
            
            # Step 2: Extract and validate entities
            entities = [obj for obj in vitalsigns_objects if isinstance(obj, KGEntity)]
            
            if not entities:
                return self._create_error_response(operation_mode, "No KGEntity objects found in request")
            
            self.logger.info(f"Found {len(entities)} KGEntity objects")
            
            # Step 3: Validate entity structure
            self.logger.info(f"🔍 Step 3: Validating entity structure...")
            validation_result = self.validator.validate_entity_structure(vitalsigns_objects)
            self.logger.info(f"🔍 Validation result: valid={validation_result.valid}")
            if not validation_result.valid:
                error_msg = f"Entity validation failed: {'; '.join(validation_result.errors)}"
                self.logger.error(f"❌ Validation failed: {error_msg}")
                return self._create_error_response(operation_mode, error_msg)
            
            # Step 4: Set dual grouping URIs
            entity_uri = str(entities[0].URI)
            self.logger.info(f"🔍 Step 4: Setting dual grouping URIs for entity {entity_uri}")
            self.grouping_manager.set_dual_grouping_uris_with_frame_separation(vitalsigns_objects, entity_uri)
            self.logger.info(f"🔍 Dual grouping URIs set successfully")
            
            # Step 5: Handle parent relationships if specified
            self.logger.info(f"🔍 Step 5: Handling parent relationships (parent_uri={parent_uri})")
            if parent_uri:
                enhanced_objects = await self._handle_parent_relationships(
                    space_id, graph_id, entities, vitalsigns_objects, parent_uri
                )
                self.logger.info(f"🔍 Enhanced objects count: {len(enhanced_objects)}")
            else:
                enhanced_objects = vitalsigns_objects
                self.logger.info(f"🔍 No parent URI, using original {len(enhanced_objects)} objects")
            
            # Step 6: Execute operation based on mode
            self.logger.info(f"🔍 Step 6: Executing operation mode: {operation_mode}")
            if operation_mode == OperationMode.CREATE:
                self.logger.info(f"🔍 Calling _handle_create_mode with {len(entities)} entities and {len(enhanced_objects)} objects")
                result = await self._handle_create_mode(space_id, graph_id, entities, enhanced_objects)
                self.logger.info(f"🔍 _handle_create_mode returned: created_count={result.created_count if hasattr(result, 'created_count') else 'N/A'}")
                return result
            elif operation_mode == OperationMode.UPDATE:
                return await self._handle_update_mode(space_id, graph_id, entities, enhanced_objects)
            elif operation_mode == OperationMode.UPSERT:
                return await self._handle_upsert_mode(space_id, graph_id, entities, enhanced_objects)
            else:
                return self._create_error_response(operation_mode, f"Invalid operation_mode: {operation_mode}")
                
        except Exception as e:
            self.logger.error(f"Error processing entities: {e}")
            return self._create_error_response(operation_mode, f"Failed to process entities: {str(e)}")
    
    async def _handle_create_mode(self, space_id: str, graph_id: str, 
                                entities: List[KGEntity], objects: List[GraphObject]) -> EntityCreateResponse:
        """Handle CREATE mode: verify none of the objects already exist."""
        try:
            # Check if any entities already exist
            self.logger.info(f"🔍 Checking if {len(entities)} entities already exist...")
            for entity in entities:
                entity_uri = str(entity.URI)
                exists = await self.backend.object_exists(space_id, graph_id, entity_uri)
                self.logger.info(f"🔍 Entity {entity_uri} exists check: {exists}")
                if exists:
                    self.logger.warning(f"❌ Entity {entity_uri} already exists - returning early")
                    return EntityCreateResponse(
                        message=f"Entity {entity_uri} already exists - cannot create in 'create' mode",
                        created_count=0,
                        created_uris=[]
                    )
            
            # Store all objects
            self.logger.info(f"🔥 CALLING BACKEND.STORE_OBJECTS with {len(objects)} objects")
            result = await self.backend.store_objects(space_id, graph_id, objects)
            self.logger.info(f"🔥 BACKEND.STORE_OBJECTS RESULT: {result.success if result else 'None'}")
            
            if result.success:
                entity_uris = [str(entity.URI) for entity in entities]
                return EntityCreateResponse(
                    message=f"Successfully created {len(entities)} entities",
                    created_count=len(entities),
                    created_uris=entity_uris
                )
            else:
                return EntityCreateResponse(
                    message=f"Failed to store entities: {result.message}",
                    created_count=0,
                    created_uris=[]
                )
                
        except Exception as e:
            self.logger.error(f"Error in create mode: {e}")
            return EntityCreateResponse(
                message=f"Error creating entities: {str(e)}",
                created_count=0,
                created_uris=[]
            )
    
    async def _handle_update_mode(self, space_id: str, graph_id: str,
                                entities: List[KGEntity], objects: List[GraphObject]) -> EntityUpdateResponse:
        """Handle UPDATE mode: verify all entities exist before updating."""
        try:
            # Check if all entities exist
            for entity in entities:
                entity_uri = str(entity.URI)
                if not await self.backend.object_exists(space_id, graph_id, entity_uri):
                    return EntityUpdateResponse(
                        message=f"Entity {entity_uri} not found - cannot update in 'update' mode",
                        updated_uri=""
                    )
            
            # Delete existing entity data first (for clean update)
            for entity in entities:
                entity_uri = str(entity.URI)
                await self.backend.delete_object(space_id, graph_id, entity_uri)
            
            # Store updated objects
            result = await self.backend.store_objects(space_id, graph_id, objects)
            
            if result.success:
                entity_uri = str(entities[0].URI)
                return EntityUpdateResponse(
                    message=f"Successfully updated entity: {entity_uri}",
                    updated_uri=entity_uri
                )
            else:
                return EntityUpdateResponse(
                    message=f"Failed to update entity: {result.message}",
                    updated_uri=""
                )
                
        except Exception as e:
            self.logger.error(f"Error in update mode: {e}")
            return EntityUpdateResponse(
                message=f"Error updating entity: {str(e)}",
                updated_uri=""
            )
    
    async def _handle_upsert_mode(self, space_id: str, graph_id: str,
                                entities: List[KGEntity], objects: List[GraphObject]) -> EntityUpdateResponse:
        """Handle UPSERT mode: create if not exists, update if exists."""
        try:
            # Check which entities exist
            existing_entities = []
            new_entities = []
            
            for entity in entities:
                entity_uri = str(entity.URI)
                if await self.backend.object_exists(space_id, graph_id, entity_uri):
                    existing_entities.append(entity)
                else:
                    new_entities.append(entity)
            
            # Delete existing entity data for clean upsert
            for entity in existing_entities:
                entity_uri = str(entity.URI)
                await self.backend.delete_object(space_id, graph_id, entity_uri)
            
            # Store all objects (both new and updated)
            result = await self.backend.store_objects(space_id, graph_id, objects)
            
            if result.success:
                entity_uri = str(entities[0].URI)
                action = "updated" if existing_entities else "created"
                return EntityUpdateResponse(
                    message=f"Successfully {action} entity: {entity_uri}",
                    updated_uri=entity_uri
                )
            else:
                return EntityUpdateResponse(
                    message=f"Failed to upsert entity: {result.message}",
                    updated_uri=""
                )
                
        except Exception as e:
            self.logger.error(f"Error in upsert mode: {e}")
            return EntityUpdateResponse(
                message=f"Error upserting entity: {str(e)}",
                updated_uri=""
            )
    
    async def _handle_parent_relationships(self, space_id: str, graph_id: str,
                                         entities: List[KGEntity], objects: List[GraphObject],
                                         parent_uri: str) -> List[GraphObject]:
        """Handle parent-child relationships by creating appropriate edges."""
        try:
            # Validate parent exists
            if not await self.backend.object_exists(space_id, graph_id, parent_uri):
                raise ValueError(f"Parent entity not found: {parent_uri}")
            
            # Create parent-child edges for each entity
            enhanced_objects = list(objects)  # Copy original objects
            
            for entity in entities:
                entity_uri = str(entity.URI)
                
                # Create edge from parent to child entity
                edge = Edge_hasEntityKGFrame()
                edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasEntityKGFrame/{self._generate_uuid()}"
                edge.edgeSource = parent_uri
                edge.edgeDestination = entity_uri
                
                # Set grouping URIs on the edge
                edge.kGGraphURI = entity_uri  # Entity-level grouping
                
                enhanced_objects.append(edge)
                self.logger.info(f"Created parent-child edge: {parent_uri} -> {entity_uri}")
            
            return enhanced_objects
            
        except Exception as e:
            self.logger.error(f"Error handling parent relationships: {e}")
            raise
    
    
    def _create_error_response(self, operation_mode: OperationMode, message: str) -> Union[EntityCreateResponse, EntityUpdateResponse]:
        """Create appropriate error response based on operation mode."""
        if operation_mode == OperationMode.CREATE:
            return EntityCreateResponse(
                message=message,
                created_count=0,
                created_uris=[]
            )
        else:  # UPDATE or UPSERT
            return EntityUpdateResponse(
                message=message,
                updated_uri=""
            )
    

    def _generate_uuid(self) -> str:
        """Generate a UUID for new entities."""
        import uuid
        return str(uuid.uuid4())


# Convenience functions for direct usage

async def create_kgentities(backend: KGBackendInterface, space_id: str, graph_id: str, 
                          vitalsigns_objects: List[GraphObject], parent_uri: Optional[str] = None) -> EntityCreateResponse:
    """
    Create KGEntities from VitalSigns GraphObjects.
    
    Args:
        backend: Backend interface implementation
        space_id: Space identifier
        graph_id: Graph identifier
        vitalsigns_objects: List of VitalSigns GraphObjects containing KGEntity data
        parent_uri: Optional parent entity URI
        
    Returns:
        EntityCreateResponse: Response containing creation results
    """
    processor = KGEntityCreateProcessor(backend)
    return await processor.create_or_update_entities(space_id, graph_id, vitalsigns_objects, OperationMode.CREATE, parent_uri)


async def update_kgentities(backend: KGBackendInterface, space_id: str, graph_id: str,
                          vitalsigns_objects: List[GraphObject], parent_uri: Optional[str] = None) -> EntityUpdateResponse:
    """
    Update KGEntities from VitalSigns GraphObjects.
    
    Args:
        backend: Backend interface implementation
        space_id: Space identifier
        graph_id: Graph identifier
        vitalsigns_objects: List of VitalSigns GraphObjects containing KGEntity data
        parent_uri: Optional parent entity URI
        
    Returns:
        EntityUpdateResponse: Response containing update results
    """
    processor = KGEntityCreateProcessor(backend)
    return await processor.create_or_update_entities(space_id, graph_id, vitalsigns_objects, OperationMode.UPDATE, parent_uri)


async def upsert_kgentities(backend: KGBackendInterface, space_id: str, graph_id: str,
                          vitalsigns_objects: List[GraphObject], parent_uri: Optional[str] = None) -> EntityUpdateResponse:
    """
    Upsert KGEntities from VitalSigns GraphObjects.
    
    Args:
        backend: Backend interface implementation
        space_id: Space identifier
        graph_id: Graph identifier
        vitalsigns_objects: List of VitalSigns GraphObjects containing KGEntity data
        parent_uri: Optional parent entity URI
        
    Returns:
        EntityUpdateResponse: Response containing upsert results
    """
    processor = KGEntityCreateProcessor(backend)
    return await processor.create_or_update_entities(space_id, graph_id, vitalsigns_objects, OperationMode.UPSERT, parent_uri)
