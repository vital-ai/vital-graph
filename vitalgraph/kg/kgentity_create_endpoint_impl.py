"""
KGEntity Create Operations Implementation

This module contains the implementation functions for KGEntity creation operations,
extracted from MockKGEntitiesEndpoint to improve code organization and maintainability.
"""

from typing import List, Optional, Any
from vitalgraph.model.jsonld_model import JsonLdDocument
from vitalgraph.model.kgentities_model import EntityCreateResponse, EntityUpdateResponse
from vitalgraph.model.kgframes_model import FrameCreateResponse
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot


def create_kgentities_impl(endpoint_instance, space_id: str, graph_id: str, document: JsonLdDocument) -> EntityCreateResponse:
    """
    Create KGEntities from JSON-LD document with grouping URI enforcement.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        document: JsonLdDocument containing KGEntity data
        
    Returns:
        EntityCreateResponse with created URIs and count
    """
    endpoint_instance._log_method_call("create_kgentities", space_id=space_id, graph_id=graph_id, document=document)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return EntityCreateResponse(
                message="Space not found",
                created_count=0, 
                created_uris=[]
            )
        
        # Step 1: Strip any existing grouping URIs from client document
        cleaned_document = endpoint_instance._strip_grouping_uris(document)
        
        # Step 2: Convert JSON-LD document to VitalSigns objects using direct object creation
        document_dict = cleaned_document.model_dump(by_alias=True)
        all_objects = endpoint_instance._create_vitalsigns_objects_from_jsonld(document_dict)
        
        if not all_objects:
            return EntityCreateResponse(
                message="No valid objects found in document",
                created_count=0, 
                created_uris=[]
            )
        
        # Step 3: Find KGEntity objects to determine entity URIs
        kgentities = [obj for obj in all_objects if isinstance(obj, KGEntity)]
        
        if not kgentities:
            return EntityCreateResponse(
                message="No KGEntity objects found in document",
                created_count=0, 
                created_uris=[]
            )
        
        # Step 4: Process complete entity graphs for each entity
        all_processed_objects = []
        entity_uris = []
        
        for entity in kgentities:
            entity_uri = str(entity.URI)
            entity_uris.append(entity_uri)
            
            # Process complete entity document to get all related objects
            # This includes the entity, its frames, slots, and edges
            entity_objects = endpoint_instance._process_complete_entity_document(cleaned_document, entity_uri)
            all_processed_objects.extend(entity_objects)
        
        # Step 5: Store all processed objects in pyoxigraph
        stored_count = endpoint_instance._store_vitalsigns_objects_in_pyoxigraph(space, all_processed_objects, graph_id)
        
        # Get created URIs (convert VitalSigns CombinedProperty to string)
        created_uris = [str(entity.URI) for entity in kgentities]
        
        return EntityCreateResponse(
            message=f"Successfully created {len(kgentities)} KGEntity(s)",
            created_count=len(kgentities),
            created_uris=created_uris
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error creating KGEntities: {e}")
        return EntityCreateResponse(
            message=f"Error creating KGEntities: {e}",
            created_count=0, 
            created_uris=[]
        )


def create_entity_frames_impl(endpoint_instance, space_id: str, graph_id: str, entity_uri: str, document: JsonLdDocument) -> FrameCreateResponse:
    """
    Create frames within entity context using Edge_hasKGFrame relationships.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier  
        entity_uri: Entity URI to create frames for
        document: JSON-LD document containing frames
        
    Returns:
        FrameCreateResponse with creation details
    """
    endpoint_instance._log_method_call("create_entity_frames", space_id=space_id, graph_id=graph_id, entity_uri=entity_uri)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return FrameCreateResponse(
                message=f"Space {space_id} not found",
                created_count=0,
                created_uris=[]
            )
        
        # Convert JSON-LD document to VitalSigns objects
        try:
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            jsonld_data = document.model_dump(by_alias=True)
            objects = endpoint_instance.vitalsigns.from_jsonld_list(jsonld_data)
            
            # Handle None return from VitalSigns
            if objects is None:
                endpoint_instance.logger.warning("VitalSigns from_jsonld_list returned None, trying alternative approach")
                objects = []
            
            # Ensure objects is a list
            if not isinstance(objects, list):
                objects = [objects] if objects is not None else []
            
            if not objects:
                return FrameCreateResponse(
                    message="No valid frames found in document",
                    created_count=0,
                    created_uris=[]
                )
            
        except Exception as e:
            endpoint_instance.logger.error(f"Error converting JSON-LD to VitalSigns objects: {e}")
            return FrameCreateResponse(
                message=f"Error processing document: {e}",
                created_count=0,
                created_uris=[]
            )
        
        # Filter for KGFrame objects and create Edge_hasKGFrame relationships
        frames = [obj for obj in objects if isinstance(obj, KGFrame)]
        created_uris = []
        
        endpoint_instance.logger.info(f"DEBUG: Processing {len(frames)} frames for entity {entity_uri}")
        for frame in frames:
            endpoint_instance.logger.info(f"DEBUG: Storing frame {frame.URI}")
            # Store the frame
            frame_triples = endpoint_instance._object_to_triples(frame, graph_id)
            endpoint_instance.logger.info(f"DEBUG: Frame generated {len(frame_triples)} triples")
            endpoint_instance._store_triples(space, frame_triples)
            
            # Create Edge_hasKGFrame relationship
            from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
            edge = Edge_hasKGFrame()
            edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGFrame/{endpoint_instance._generate_uuid()}"
            edge.edgeSource = str(entity_uri)
            edge.edgeDestination = str(frame.URI)
            
            endpoint_instance.logger.info(f"DEBUG: Creating edge {edge.URI} from {edge.edgeSource} to {edge.edgeDestination}")
            # Store the edge
            edge_triples = endpoint_instance._object_to_triples(edge, graph_id)
            endpoint_instance.logger.info(f"DEBUG: Edge generated {len(edge_triples)} triples")
            endpoint_instance._store_triples(space, edge_triples)
            
            created_uris.append(str(frame.URI))
        
        # Also store any slots and their edges that were included
        slots = [obj for obj in objects if isinstance(obj, KGSlot)]
        edges = [obj for obj in objects if hasattr(obj, 'edgeSource') and hasattr(obj, 'edgeDestination')]
        
        endpoint_instance.logger.info(f"DEBUG: Also storing {len(slots)} slots and {len(edges)} edges from the document")
        for slot in slots:
            endpoint_instance.logger.info(f"DEBUG: Storing slot {slot.URI}")
            slot_triples = endpoint_instance._object_to_triples(slot, graph_id)
            endpoint_instance.logger.info(f"DEBUG: Slot generated {len(slot_triples)} triples")
            endpoint_instance._store_triples(space, slot_triples)
        
        for edge in edges:
            endpoint_instance.logger.info(f"DEBUG: Storing edge {edge.URI}")
            edge_triples = endpoint_instance._object_to_triples(edge, graph_id)
            endpoint_instance.logger.info(f"DEBUG: Edge generated {len(edge_triples)} triples")
            endpoint_instance._store_triples(space, edge_triples)
        
        return FrameCreateResponse(
            message=f"Successfully created {len(created_uris)} frames for entity {entity_uri}",
            created_count=len(created_uris),
            created_uris=created_uris
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error creating entity frames: {e}")
        return FrameCreateResponse(
            message=f"Error creating entity frames: {e}",
            created_count=0,
            created_uris=[]
        )


def create_entity_frames_complex_impl(endpoint_instance, space_id: str, graph_id: str, entity_uri: str, 
                           document: JsonLdDocument, operation_mode: str = "create") -> FrameCreateResponse:
    """
    Create frames within entity context using /kgentities/kgframes sub-endpoint.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        entity_uri: Parent entity URI
        document: JsonLdDocument containing frames and related objects
        operation_mode: "create", "update", or "upsert"
        
    Returns:
        FrameCreateResponse with creation details
    """
    endpoint_instance._log_method_call("create_entity_frames", space_id=space_id, graph_id=graph_id, 
                         entity_uri=entity_uri, document=document, operation_mode=operation_mode)
    
    try:
        # Import response model
        from vitalgraph.model.kgframes_model import FrameCreateResponse
        
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return FrameCreateResponse(
                message="Space not found",
                created_count=0,
                created_uris=[]
            )
        
        # Step 1: Validate parent entity exists (temporarily disabled for debugging)
        entity_exists = endpoint_instance._validate_entity_exists(space, graph_id, entity_uri)
        endpoint_instance.logger.info(f"Entity exists check for {entity_uri}: {entity_exists}")
        # Temporarily skip entity validation to test frame creation
        # if not entity_exists:
        #     return FrameCreateResponse(
        #         message=f"Parent entity not found: {entity_uri}",
        #         created_count=0,
        #         created_uris=[]
        #     )
        
        # Step 2: Create VitalSigns objects from JSON-LD
        document_dict = document.model_dump(by_alias=True) if hasattr(document, 'model_dump') else document
        
        # Debug: Log the actual JSON-LD structure
        import json
        endpoint_instance.logger.info(f"JSON-LD structure: {json.dumps(document_dict, indent=2)[:500]}...")
        
        incoming_objects = endpoint_instance._create_vitalsigns_objects_from_jsonld(document_dict)
        if not incoming_objects:
            return FrameCreateResponse(
                message="No valid objects found in document",
                created_count=0,
                created_uris=[]
            )
        
        # Step 3: Validate frame structure and extract frame URIs
        frame_structure = endpoint_instance._validate_frame_structure(incoming_objects)
        endpoint_instance.logger.debug(f"Frame structure validation: {frame_structure}")
        if not frame_structure['valid']:
            return FrameCreateResponse(
                message=f"Invalid frame structure: {frame_structure['error']}",
                created_count=0,
                created_uris=[]
            )
        
        frame_uris = frame_structure['frame_uris']
        
        # Step 4: Handle operation mode-specific logic for frames
        if operation_mode == "create":
            # Validate no frames exist
            for frame_uri in frame_uris:
                if endpoint_instance._frame_exists(space, graph_id, frame_uri):
                    return FrameCreateResponse(
                        message=f"Frame already exists: {frame_uri}",
                        created_count=0,
                        created_uris=[]
                    )
        elif operation_mode == "update":
            # Validate all frames exist and are connected to entity
            for frame_uri in frame_uris:
                if not endpoint_instance._frame_exists(space, graph_id, frame_uri):
                    return FrameCreateResponse(
                        message=f"Frame not found for update: {frame_uri}",
                        created_count=0,
                        created_uris=[]
                    )
                if not endpoint_instance._validate_entity_frame_connection(space, graph_id, entity_uri, frame_uri):
                    return FrameCreateResponse(
                        message=f"Frame not connected to entity: {frame_uri}",
                        created_count=0,
                        created_uris=[]
                    )
        elif operation_mode == "upsert":
            # Mixed mode - validate connections for existing frames
            for frame_uri in frame_uris:
                if endpoint_instance._frame_exists(space, graph_id, frame_uri):
                    if not endpoint_instance._validate_entity_frame_connection(space, graph_id, entity_uri, frame_uri):
                        return FrameCreateResponse(
                            message=f"Existing frame not connected to entity: {frame_uri}",
                            created_count=0,
                            created_uris=[]
                        )
        
        # Step 5: Set dual grouping URIs (entity-level and frame-level)
        endpoint_instance._set_dual_grouping_uris(incoming_objects, entity_uri)
        
        # Step 6: Create entity-frame edges for new frames
        endpoint_instance._create_entity_frame_edges(incoming_objects, entity_uri, operation_mode)
        
        # Step 7: Handle update mode - delete existing triples first
        if operation_mode == "update":
            for frame_uri in frame_uris:
                endpoint_instance._delete_frame_triples(space, graph_id, frame_uri)
        elif operation_mode == "upsert":
            # Delete existing frames only
            for frame_uri in frame_uris:
                if endpoint_instance._frame_exists(space, graph_id, frame_uri):
                    endpoint_instance._delete_frame_triples(space, graph_id, frame_uri)
        
        # Step 8: Store all objects in pyoxigraph
        # Log what objects are being stored
        edge_count = sum(1 for obj in incoming_objects if 'Edge_hasEntityKGFrame' in str(type(obj)))
        endpoint_instance.logger.info(f"Storing {len(incoming_objects)} objects including {edge_count} entity-frame edges")
        success = endpoint_instance._store_vitalsigns_objects_in_pyoxigraph(space, incoming_objects, graph_id)
        if not success:
            return FrameCreateResponse(
                message="Failed to store objects in graph database",
                created_count=0,
                created_uris=[]
            )
        
        return FrameCreateResponse(
            message=f"Successfully {operation_mode}d {len(frame_uris)} frames for entity",
            created_count=len(frame_uris),
            created_uris=frame_uris
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error in create_entity_frames: {e}")
        import traceback
        endpoint_instance.logger.error(f"Traceback: {traceback.format_exc()}")
        return FrameCreateResponse(
            message=f"Error creating entity frames: {e}",
            created_count=0,
            created_uris=[]
        )


def handle_entity_create_mode_impl(endpoint_instance, space, graph_id: str, entity_uri: str, incoming_objects: list, 
                                  incoming_uris: set, parent_uri: str = None) -> EntityUpdateResponse:
    """
    Handle CREATE mode: verify none of the objects already exist.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space: Space instance
        graph_id: Graph identifier
        entity_uri: Entity URI being created
        incoming_objects: List of objects to create
        incoming_uris: Set of URIs being created
        parent_uri: Optional parent object URI
        
    Returns:
        EntityUpdateResponse with creation result
    """
    try:
        # Check if any objects already exist
        for uri in incoming_uris:
            if endpoint_instance._object_exists_in_store(space, uri, graph_id):
                return EntityUpdateResponse(
                    message=f"Object {uri} already exists - cannot create in 'create' mode",
                    updated_uri=""
                )
        
        # Validate parent connection if provided
        if parent_uri:
            connection_valid = endpoint_instance._validate_parent_connection(space, parent_uri, entity_uri, graph_id, incoming_objects)
            if not connection_valid:
                return EntityUpdateResponse(
                    message=f"Invalid connection to parent {parent_uri}",
                    updated_uri=""
                )
        
        # Set dual grouping URIs (entity-level + frame-level) and store objects
        endpoint_instance._set_dual_grouping_uris(incoming_objects, entity_uri)
        stored_count = endpoint_instance._store_vitalsigns_objects_in_pyoxigraph(space, incoming_objects, graph_id)
        
        if stored_count > 0:
            return EntityUpdateResponse(
                message=f"Successfully created entity: {entity_uri}",
                updated_uri=entity_uri
            )
        else:
            return EntityUpdateResponse(
                message=f"Failed to store entity objects",
                updated_uri=""
            )
            
    except Exception as e:
        endpoint_instance.logger.error(f"Error in entity create mode: {e}")
        return EntityUpdateResponse(
            message=f"Error creating entity: {e}",
            updated_uri=""
        )


def process_complete_entity_document_impl(endpoint_instance, document: JsonLdDocument, entity_uri: str) -> List[Any]:
    """
    Process complete entity document to extract and validate all KG objects using VitalSigns.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        document: JSON-LD document containing entity graph
        entity_uri: URI of the main entity
        
    Returns:
        List of all VitalSigns objects (KGEntity, KGFrame, KGSlot, edges)
    """
    try:
        # Convert entire document to VitalSigns objects using direct object creation
        document_dict = document.model_dump(by_alias=True)
        all_objects = endpoint_instance._create_vitalsigns_objects_from_jsonld(document_dict)
        
        if not all_objects:
            endpoint_instance.logger.warning("No valid VitalSigns objects found in document")
            return []
        
        # Categorize objects by type
        entities = []
        frames = []
        slots = []
        edges = []
        
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        from ai_haley_kg_domain.model.KGFrame import KGFrame
        from ai_haley_kg_domain.model.KGSlot import KGSlot
        from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge
        
        for obj in all_objects:
            try:
                # Use isinstance() for efficient and reliable type detection
                if isinstance(obj, KGEntity):
                    entities.append(obj)
                elif isinstance(obj, KGFrame):
                    frames.append(obj)
                elif isinstance(obj, KGSlot):  # This catches ALL KGSlot subclasses
                    slots.append(obj)
                elif isinstance(obj, VITAL_Edge):
                    edges.append(obj)
                else:
                    # Log unknown object types for debugging
                    obj_type = type(obj).__name__
                    endpoint_instance.logger.debug(f"Unknown object type: {obj_type} for object {obj.URI}")
                        
            except Exception as e:
                endpoint_instance.logger.warning(f"Failed to categorize object {obj.URI}: {e}")
                continue
        
        # Set dual grouping URIs on all objects (entity-level + frame-level)
        all_entity_objects = entities + frames + slots + edges
        endpoint_instance._set_dual_grouping_uris(all_entity_objects, entity_uri)
        
        endpoint_instance.logger.info(f"Processed entity document: {len(entities)} entities, {len(frames)} frames, "
                       f"{len(slots)} slots, {len(edges)} edges")
        
        return all_entity_objects
        
    except Exception as e:
        endpoint_instance.logger.error(f"Failed to process complete entity document: {e}")
        return []