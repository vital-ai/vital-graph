"""
KGSlot Create Implementation

This module contains the core implementation logic for KGSlot creation operations.
It provides backend-agnostic functions that can be used by both REST endpoints and
direct API calls, with proper error handling and validation.

Follows the same pattern as KGEntityCreateProcessor for consistency.
"""

import logging
from typing import List, Dict, Any, Optional, Union
from enum import Enum

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGSlot import KGSlot
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

# Model imports
from ..model.kgframes_model import SlotCreateResponse, SlotUpdateResponse

# Local imports
from .kg_backend_utils import KGBackendInterface, BackendOperationResult
from .kg_validation_utils import KGEntityValidator, KGGroupingURIManager, ValidationResult


class OperationMode(str, Enum):
    """Operation modes for slot lifecycle management."""
    CREATE = "create"
    UPDATE = "update"
    UPSERT = "upsert"


class KGSlotCreateProcessor:
    """Processor for KGSlot creation operations with backend abstraction."""
    
    def __init__(self, backend: KGBackendInterface):
        """
        Initialize with backend interface.
        
        Args:
            backend: Backend interface implementation
        """
        self.backend = backend
        self.validator = KGEntityValidator()
        self.grouping_manager = KGGroupingURIManager()
        self.logger = logging.getLogger(f"{__name__}.KGSlotCreateProcessor")
    
    async def create_or_update_slots(self, space_id: str, graph_id: str, 
                                   vitalsigns_objects: List[GraphObject], operation_mode: OperationMode,
                                   frame_uri: Optional[str] = None) -> Union[SlotCreateResponse, SlotUpdateResponse]:
        """
        Create or update KG slots using backend abstraction.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            vitalsigns_objects: List of VitalSigns GraphObjects to create/update
            operation_mode: CREATE, UPDATE, or UPSERT
            frame_uri: Optional parent frame URI
            
        Returns:
            SlotCreateResponse or SlotUpdateResponse based on operation mode
        """
        try:
            self.logger.info(f"Processing KG slots in space '{space_id}', graph '{graph_id}', "
                           f"operation_mode='{operation_mode}', frame_uri='{frame_uri}'")
            
            # Step 1: Validate VitalSigns objects
            if not vitalsigns_objects:
                return self._create_error_response(operation_mode, "No valid objects provided")
            
            self.logger.info(f"Processing {len(vitalsigns_objects)} VitalSigns objects")
            
            # Step 2: Extract and validate slots
            slots = [obj for obj in vitalsigns_objects if isinstance(obj, KGSlot)]
            
            if not slots:
                return self._create_error_response(operation_mode, "No KGSlot objects found in request")
            
            self.logger.info(f"Found {len(slots)} KGSlot objects")
            
            # Step 3: Validate slot structure (standalone validation for slots only)
            slot_validation_errors = []
            for slot in slots:
                # Basic slot validation - check required properties
                if not hasattr(slot, 'URI') or not slot.URI:
                    slot_validation_errors.append(f"Slot missing required URI property")
                
                # Check slot type if present
                if hasattr(slot, 'kGSlotType') and slot.kGSlotType:
                    # kGSlotType should be a URI object, validate its string representation
                    slot_type_str = str(slot.kGSlotType)
                    if not slot_type_str.startswith('http://'):
                        slot_validation_errors.append(f"Slot {slot.URI} has invalid kGSlotType format: {slot_type_str}")
            
            if slot_validation_errors:
                error_msg = f"Slot validation failed: {'; '.join(slot_validation_errors)}"
                return self._create_error_response(operation_mode, error_msg)
            
            # Step 4: Set dual grouping URIs (use frame URI as entity-level grouping)
            if frame_uri:
                self.grouping_manager.set_dual_grouping_uris_with_frame_separation(vitalsigns_objects, frame_uri)
            
            # Step 5: Handle frame relationships if specified
            if frame_uri:
                enhanced_objects = await self._handle_frame_relationships(
                    space_id, graph_id, slots, vitalsigns_objects, frame_uri
                )
            else:
                enhanced_objects = vitalsigns_objects
            
            # Step 6: Execute operation based on mode
            if operation_mode == OperationMode.CREATE:
                return await self._handle_create_mode(space_id, graph_id, slots, enhanced_objects)
            elif operation_mode == OperationMode.UPDATE:
                return await self._handle_update_mode(space_id, graph_id, slots, enhanced_objects)
            elif operation_mode == OperationMode.UPSERT:
                return await self._handle_upsert_mode(space_id, graph_id, slots, enhanced_objects)
            else:
                return self._create_error_response(operation_mode, f"Invalid operation_mode: {operation_mode}")
                
        except Exception as e:
            self.logger.error(f"Error processing slots: {e}")
            return self._create_error_response(operation_mode, f"Failed to process slots: {str(e)}")
    
    async def _handle_create_mode(self, space_id: str, graph_id: str, 
                                slots: List[KGSlot], objects: List[GraphObject]) -> SlotCreateResponse:
        """Handle CREATE mode: verify none of the objects already exist."""
        try:
            # Check if any slots already exist
            for slot in slots:
                slot_uri = str(slot.URI)
                if await self.backend.object_exists(space_id, graph_id, slot_uri):
                    return SlotCreateResponse(
                        message=f"Slot {slot_uri} already exists - cannot create in 'create' mode",
                        created_count=0,
                        created_uris=[]
                    )
            
            # Store all objects
            self.logger.info(f"🔥 CALLING BACKEND.STORE_OBJECTS with {len(objects)} objects")
            result = await self.backend.store_objects(space_id, graph_id, objects)
            self.logger.info(f"🔥 BACKEND.STORE_OBJECTS RESULT: {result.success if result else 'None'}")
            
            if result.success:
                slot_uris = [str(slot.URI) for slot in slots]
                return SlotCreateResponse(
                    message=f"Successfully created {len(slots)} slots",
                    created_count=len(slots),
                    created_uris=slot_uris
                )
            else:
                return SlotCreateResponse(
                    message=f"Failed to store slots: {result.message}",
                    created_count=0,
                    created_uris=[]
                )
                
        except Exception as e:
            self.logger.error(f"Error in create mode: {e}")
            return SlotCreateResponse(
                message=f"Error creating slots: {str(e)}",
                created_count=0,
                created_uris=[]
            )
    
    async def _handle_update_mode(self, space_id: str, graph_id: str,
                                slots: List[KGSlot], objects: List[GraphObject]) -> SlotUpdateResponse:
        """Handle UPDATE mode: verify all slots exist before updating."""
        try:
            # Check if all slots exist
            for slot in slots:
                slot_uri = str(slot.URI)
                if not await self.backend.object_exists(space_id, graph_id, slot_uri):
                    return SlotUpdateResponse(
                        message=f"Slot {slot_uri} not found - cannot update in 'update' mode",
                        updated_uri=""
                    )
            
            # Delete existing slot data first (for clean update)
            for slot in slots:
                slot_uri = str(slot.URI)
                await self.backend.delete_object(space_id, graph_id, slot_uri)
            
            # Store updated objects
            result = await self.backend.store_objects(space_id, graph_id, objects)
            
            if result.success:
                slot_uri = str(slots[0].URI)
                return SlotUpdateResponse(
                    message=f"Successfully updated slot: {slot_uri}",
                    updated_uri=slot_uri
                )
            else:
                return SlotUpdateResponse(
                    message=f"Failed to update slot: {result.message}",
                    updated_uri=""
                )
                
        except Exception as e:
            self.logger.error(f"Error in update mode: {e}")
            return SlotUpdateResponse(
                message=f"Error updating slot: {str(e)}",
                updated_uri=""
            )
    
    async def _handle_upsert_mode(self, space_id: str, graph_id: str,
                                slots: List[KGSlot], objects: List[GraphObject]) -> SlotUpdateResponse:
        """Handle UPSERT mode: create if not exists, update if exists."""
        try:
            # Check which slots exist
            existing_slots = []
            new_slots = []
            
            for slot in slots:
                slot_uri = str(slot.URI)
                if await self.backend.object_exists(space_id, graph_id, slot_uri):
                    existing_slots.append(slot)
                else:
                    new_slots.append(slot)
            
            # Delete existing slot data for clean upsert
            for slot in existing_slots:
                slot_uri = str(slot.URI)
                await self.backend.delete_object(space_id, graph_id, slot_uri)
            
            # Store all objects (both new and updated)
            result = await self.backend.store_objects(space_id, graph_id, objects)
            
            if result.success:
                slot_uri = str(slots[0].URI)
                action = "updated" if existing_slots else "created"
                return SlotUpdateResponse(
                    message=f"Successfully {action} slot: {slot_uri}",
                    updated_uri=slot_uri
                )
            else:
                return SlotUpdateResponse(
                    message=f"Failed to upsert slot: {result.message}",
                    updated_uri=""
                )
                
        except Exception as e:
            self.logger.error(f"Error in upsert mode: {e}")
            return SlotUpdateResponse(
                message=f"Error upserting slot: {str(e)}",
                updated_uri=""
            )
    
    async def _handle_frame_relationships(self, space_id: str, graph_id: str,
                                        slots: List[KGSlot], objects: List[GraphObject],
                                        frame_uri: str) -> List[GraphObject]:
        """Handle frame-slot relationships by creating appropriate edges."""
        try:
            # Validate frame exists
            if not await self.backend.object_exists(space_id, graph_id, frame_uri):
                raise ValueError(f"Parent frame not found: {frame_uri}")
            
            # Create frame-slot edges for each slot
            enhanced_objects = list(objects)  # Copy original objects
            
            for slot in slots:
                slot_uri = str(slot.URI)
                
                # Create edge from frame to slot
                edge = Edge_hasKGSlot()
                edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGSlot/{self._generate_uuid()}"
                edge.hasEdgeSource = frame_uri
                edge.hasEdgeDestination = slot_uri
                
                # Set grouping URIs on the edge
                edge.kGGraphURI = frame_uri  # Frame-level grouping
                
                enhanced_objects.append(edge)
                self.logger.info(f"Created frame-slot edge: {frame_uri} -> {slot_uri}")
            
            return enhanced_objects
            
        except Exception as e:
            self.logger.error(f"Error handling frame relationships: {e}")
            raise
    
    def _create_error_response(self, operation_mode: OperationMode, message: str) -> Union[SlotCreateResponse, SlotUpdateResponse]:
        """Create appropriate error response based on operation mode."""
        if operation_mode == OperationMode.CREATE:
            return SlotCreateResponse(
                message=message,
                created_count=0,
                created_uris=[]
            )
        else:  # UPDATE or UPSERT
            return SlotUpdateResponse(
                message=message,
                updated_uri=""
            )

    def _generate_uuid(self) -> str:
        """Generate a UUID for new slots."""
        import uuid
        return str(uuid.uuid4())


# Convenience functions for direct usage

async def create_kgslots(backend: KGBackendInterface, space_id: str, graph_id: str, 
                       vitalsigns_objects: List[GraphObject], frame_uri: Optional[str] = None) -> SlotCreateResponse:
    """
    Create KGSlots from VitalSigns GraphObjects.
    
    Args:
        backend: Backend interface implementation
        space_id: Space identifier
        graph_id: Graph identifier
        vitalsigns_objects: List of VitalSigns GraphObjects containing KGSlot data
        frame_uri: Optional parent frame URI
        
    Returns:
        SlotCreateResponse: Response containing creation results
    """
    processor = KGSlotCreateProcessor(backend)
    return await processor.create_or_update_slots(space_id, graph_id, vitalsigns_objects, OperationMode.CREATE, frame_uri)


async def update_kgslots(backend: KGBackendInterface, space_id: str, graph_id: str,
                       vitalsigns_objects: List[GraphObject], frame_uri: Optional[str] = None) -> SlotUpdateResponse:
    """
    Update KGSlots from VitalSigns GraphObjects.
    
    Args:
        backend: Backend interface implementation
        space_id: Space identifier
        graph_id: Graph identifier
        vitalsigns_objects: List of VitalSigns GraphObjects containing KGSlot data
        frame_uri: Optional parent frame URI
        
    Returns:
        SlotUpdateResponse: Response containing update results
    """
    processor = KGSlotCreateProcessor(backend)
    return await processor.create_or_update_slots(space_id, graph_id, vitalsigns_objects, OperationMode.UPDATE, frame_uri)


async def upsert_kgslots(backend: KGBackendInterface, space_id: str, graph_id: str,
                       vitalsigns_objects: List[GraphObject], frame_uri: Optional[str] = None) -> SlotUpdateResponse:
    """
    Upsert KGSlots from VitalSigns GraphObjects.
    
    Args:
        backend: Backend interface implementation
        space_id: Space identifier
        graph_id: Graph identifier
        vitalsigns_objects: List of VitalSigns GraphObjects containing KGSlot data
        frame_uri: Optional parent frame URI
        
    Returns:
        SlotUpdateResponse: Response containing upsert results
    """
    processor = KGSlotCreateProcessor(backend)
    return await processor.create_or_update_slots(space_id, graph_id, vitalsigns_objects, OperationMode.UPSERT, frame_uri)
