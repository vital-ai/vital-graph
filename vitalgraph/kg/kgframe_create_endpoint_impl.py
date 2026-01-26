"""
KGFrame Create Operations Implementation

This module contains the implementation functions for KGFrame creation operations,
extracted from MockKGFramesEndpoint to improve code organization and maintainability.
"""

from typing import List, Optional, Any
from vitalgraph.model.jsonld_model import JsonLdDocument
from vitalgraph.model.kgframes_model import FrameCreateResponse, SlotCreateResponse, FrameUpdateResponse
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from vital_ai_vitalsigns.model.GraphObject import GraphObject
import traceback


def create_kgframes_impl(endpoint_instance, space_id: str, graph_id: str, document: JsonLdDocument) -> FrameCreateResponse:
    """
    Create KGFrames from JSON-LD document with VitalSigns integration and grouping URI enforcement.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        document: JsonLdDocument containing KGFrame data
        
    Returns:
        FrameCreateResponse with created URIs and count
    """
    endpoint_instance._log_method_call("create_kgframes", space_id=space_id, graph_id=graph_id, document=document)
    
    try:
        endpoint_instance.logger.info("=== Starting create_kgframes method ===")
        
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return FrameCreateResponse(
                message=f"Space {space_id} not found",
                created_count=0,
                created_uris=[]
            )
        
        # Step 1: Strip any existing grouping URIs from client document
        stripped_document = endpoint_instance._strip_grouping_uris(document)
        endpoint_instance.logger.info("Step 1: Stripped grouping URIs from document")
        
        # Step 2: Create VitalSigns objects from JSON-LD using the same approach as MockKGEntitiesEndpoint
        document_dict = stripped_document.model_dump(by_alias=True)
        objects = endpoint_instance._create_vitalsigns_objects_from_jsonld(document_dict)
        endpoint_instance.logger.info(f"Step 2: Created {len(objects) if objects else 0} VitalSigns objects")
        
        if not objects:
            endpoint_instance.logger.warning("No objects created, returning early")
            return FrameCreateResponse(
                message="No valid KGFrame objects found in document",
                created_count=0,
                created_uris=[]
            )
        
        # Step 3: Identify primary frame for grouping URI
        primary_frame_uri = None
        endpoint_instance.logger.info(f"Looking for primary frame in {len(objects)} objects")
        for obj in objects:
            endpoint_instance.logger.info(f"Checking object: {obj.__class__.__name__} - isinstance(KGFrame): {isinstance(obj, KGFrame)}")
            if isinstance(obj, KGFrame) and hasattr(obj, 'URI') and obj.URI:
                primary_frame_uri = str(obj.URI)  # Cast Property object to string
                endpoint_instance.logger.info(f"Found primary frame URI: {primary_frame_uri}")
                break
        
        # Step 4: Set grouping URIs for frame graph components
        if primary_frame_uri:
            endpoint_instance.logger.info(f"Setting frame grouping URIs with primary_frame_uri: {primary_frame_uri}")
            endpoint_instance._set_frame_grouping_uris(objects, primary_frame_uri)
        else:
            endpoint_instance.logger.warning("No primary frame URI found for grouping URI assignment")
        
        # Step 5: Store objects using existing base class method
        stored_count = endpoint_instance._store_vitalsigns_objects_in_pyoxigraph(space, objects, graph_id)
        
        # Get created URIs with proper Property object casting
        created_uris = []
        for obj in objects:
            if isinstance(obj, GraphObject) and hasattr(obj, 'URI') and obj.URI:
                # Cast URI Property object to string
                uri_str = str(obj.URI)
                created_uris.append(uri_str)
                endpoint_instance.logger.info(f"Created {obj.__class__.__name__} with URI: {uri_str}")
        
        return FrameCreateResponse(
            message=f"Created {len(created_uris)} KGFrame objects with grouping URI enforcement",
            created_count=len(created_uris),
            created_uris=created_uris
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error creating KGFrames: {e}")
        endpoint_instance.logger.error(f"Traceback: {traceback.format_exc()}")
        return FrameCreateResponse(
            message=f"Error creating KGFrames: {e}",
            created_count=0,
            created_uris=[]
        )


def create_frame_slots_impl(endpoint_instance, space_id: str, graph_id: str, frame_uri: str, 
                          document: JsonLdDocument, operation_mode: str = "create") -> SlotCreateResponse:
    """
    Create slots within frame context using /kgframes/kgslots sub-endpoint.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        frame_uri: Parent frame URI
        document: JsonLdDocument containing slots and related objects
        operation_mode: "create", "update", or "upsert"
        
    Returns:
        SlotCreateResponse with creation details
    """
    endpoint_instance._log_method_call("create_frame_slots", space_id=space_id, graph_id=graph_id, 
                         frame_uri=frame_uri, document=document, operation_mode=operation_mode)
    
    try:
        # Import response model
        from vitalgraph.model.kgframes_model import SlotCreateResponse
        
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return SlotCreateResponse(
                message="Space not found",
                created_count=0,
                created_uris=[]
            )
        
        # Step 1: Validate parent frame exists
        frame_exists = endpoint_instance._validate_frame_exists(space, graph_id, frame_uri)
        if not frame_exists:
            return SlotCreateResponse(
                message=f"Parent frame not found: {frame_uri}",
                created_count=0,
                created_uris=[]
            )
        
        # Step 2: Create VitalSigns objects from JSON-LD
        document_dict = document.model_dump(by_alias=True) if hasattr(document, 'model_dump') else document
        incoming_objects = endpoint_instance._create_vitalsigns_objects_from_jsonld(document_dict)
        if not incoming_objects:
            return SlotCreateResponse(
                message="No valid objects found in document",
                created_count=0,
                created_uris=[]
            )
        
        # Step 3: Validate slot structure and extract slot URIs
        slot_structure = endpoint_instance._validate_slot_structure(incoming_objects)
        if not slot_structure['valid']:
            return SlotCreateResponse(
                message=f"Invalid slot structure: {slot_structure['error']}",
                created_count=0,
                created_uris=[]
            )
        
        slot_uris = slot_structure['slot_uris']
        
        # Step 4: Handle operation mode-specific logic for slots
        if operation_mode == "create":
            # Validate no slots exist
            for slot_uri in slot_uris:
                if endpoint_instance._slot_exists(space, graph_id, slot_uri):
                    return SlotCreateResponse(
                        message=f"Slot already exists: {slot_uri}",
                        created_count=0,
                        created_uris=[]
                    )
        elif operation_mode == "update":
            # Validate all slots exist and are connected to frame
            for slot_uri in slot_uris:
                if not endpoint_instance._slot_exists(space, graph_id, slot_uri):
                    return SlotCreateResponse(
                        message=f"Slot not found for update: {slot_uri}",
                        created_count=0,
                        created_uris=[]
                    )
                if not endpoint_instance._validate_frame_slot_connection(space, graph_id, frame_uri, slot_uri):
                    return SlotCreateResponse(
                        message=f"Slot not connected to frame: {slot_uri}",
                        created_count=0,
                        created_uris=[]
                    )
        elif operation_mode == "upsert":
            # Mixed mode - validate connections for existing slots
            for slot_uri in slot_uris:
                if endpoint_instance._slot_exists(space, graph_id, slot_uri):
                    if not endpoint_instance._validate_frame_slot_connection(space, graph_id, frame_uri, slot_uri):
                        return SlotCreateResponse(
                            message=f"Existing slot not connected to frame: {slot_uri}",
                            created_count=0,
                            created_uris=[]
                        )
        
        # Step 5: Set dual grouping URIs (entity-level and frame-level)
        endpoint_instance._set_slot_grouping_uris(incoming_objects, frame_uri)
        
        # Step 6: Create frame-slot edges for new slots
        endpoint_instance._create_frame_slot_edges(incoming_objects, frame_uri, operation_mode)
        
        # Step 7: Handle update mode - delete existing triples first
        if operation_mode == "update":
            for slot_uri in slot_uris:
                endpoint_instance._delete_slot_triples(space, graph_id, slot_uri)
        elif operation_mode == "upsert":
            # Delete existing slots only
            for slot_uri in slot_uris:
                if endpoint_instance._slot_exists(space, graph_id, slot_uri):
                    endpoint_instance._delete_slot_triples(space, graph_id, slot_uri)
        
        # Step 8: Store all objects in pyoxigraph
        success = endpoint_instance._store_vitalsigns_objects_in_pyoxigraph(space, incoming_objects, graph_id)
        if not success:
            return SlotCreateResponse(
                message="Failed to store objects in graph database",
                created_count=0,
                created_uris=[]
            )
        
        return SlotCreateResponse(
            message=f"Successfully {operation_mode}d {len(slot_uris)} slots for frame",
            created_count=len(slot_uris),
            created_uris=slot_uris
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error in create_frame_slots: {e}")
        import traceback
        endpoint_instance.logger.error(f"Traceback: {traceback.format_exc()}")
        return SlotCreateResponse(
            message=f"Error creating frame slots: {e}",
            created_count=0,
            created_uris=[]
        )


def handle_create_mode_impl(endpoint_instance, space, graph_id: str, frame_uri: str, incoming_objects: list, 
                           incoming_uris: set, parent_uri: str = None) -> FrameUpdateResponse:
    """
    Handle CREATE mode: verify none of the objects already exist.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space: Space instance
        graph_id: Graph identifier
        frame_uri: Frame URI being created
        incoming_objects: List of objects to create
        incoming_uris: Set of URIs being created
        parent_uri: Optional parent object URI
        
    Returns:
        FrameUpdateResponse with creation result
    """
    try:
        # Check if any objects already exist
        for uri in incoming_uris:
            if endpoint_instance._object_exists_in_store(space, uri, graph_id):
                return FrameUpdateResponse(
                    message=f"Object {uri} already exists - cannot create in 'create' mode",
                    updated_uri=""
                )
        
        # Validate parent connection if provided
        if parent_uri:
            connection_valid = endpoint_instance._validate_parent_connection(space, parent_uri, frame_uri, graph_id, incoming_objects)
            if not connection_valid:
                return FrameUpdateResponse(
                    message=f"Invalid connection to parent {parent_uri}",
                    updated_uri=""
                )
        
        # Set grouping URIs and store objects
        endpoint_instance._set_frame_grouping_uris(incoming_objects, frame_uri)
        stored_count = endpoint_instance._store_vitalsigns_objects_in_pyoxigraph(space, incoming_objects, graph_id)
        
        if stored_count > 0:
            return FrameUpdateResponse(
                message=f"Successfully created frame: {frame_uri}",
                updated_uri=frame_uri
            )
        else:
            return FrameUpdateResponse(
                message=f"Failed to store frame objects",
                updated_uri=""
            )
            
    except Exception as e:
        endpoint_instance.logger.error(f"Error in create mode: {e}")
        return FrameUpdateResponse(
            message=f"Error creating frame: {e}",
            updated_uri=""
        )


def create_kgframes_with_slots_impl(endpoint_instance, space_id: str, graph_id: str, document: JsonLdDocument) -> FrameCreateResponse:
    """
    Create KGFrames with their associated slots from JSON-LD document using VitalSigns native functionality.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        document: JsonLdDocument containing KGFrame and KGSlot data
        
    Returns:
        FrameCreateResponse with created URIs and count
    """
    endpoint_instance._log_method_call("create_kgframes_with_slots", space_id=space_id, graph_id=graph_id, document=document)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return FrameCreateResponse(
                message="Space not found",
                created_count=0, 
                created_uris=[]
            )
        
        # Convert JSON-LD document to VitalSigns objects
        document_dict = document.model_dump(by_alias=True)
        objects = endpoint_instance._jsonld_to_vitalsigns_objects(document_dict)
        
        if not objects:
            return FrameCreateResponse(
                message="No valid objects found in document",
                created_count=0, 
                created_uris=[]
            )
        
        # Filter for KGFrame and KGSlot objects and edges
        frame_objects = [obj for obj in objects if isinstance(obj, (KGFrame, KGSlot)) or hasattr(obj, 'edgeSource')]
        
        if not frame_objects:
            return FrameCreateResponse(
                message="No KGFrame, KGSlot, or Edge objects found in document",
                created_count=0, 
                created_uris=[]
            )
        
        # Store all objects in pyoxigraph
        stored_count = endpoint_instance._store_vitalsigns_objects_in_pyoxigraph(space, frame_objects, graph_id)
        
        # Get created URIs (convert VitalSigns CombinedProperty to string)
        created_uris = [str(obj.URI) for obj in frame_objects]
        
        return FrameCreateResponse(
            message=f"Successfully created {stored_count} KGFrame/KGSlot object(s)",
            created_count=stored_count,
            created_uris=created_uris
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error creating KGFrames with slots: {e}")
        return FrameCreateResponse(
            message=f"Error creating KGFrames with slots: {e}",
            created_count=0, 
            created_uris=[]
        )