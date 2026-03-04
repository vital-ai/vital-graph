"""
KGEntity Update Endpoint Implementation

This module contains the implementation functions for KGEntity update operations
that have been extracted from MockKGEntitiesEndpoint for better code organization.
"""

from typing import List, Set, Optional, Any
from vitalgraph.model.kgentities_model import EntityUpdateResponse
from vitalgraph.model.kgframes_model import FrameUpdateResponse


def handle_entity_update_mode_impl(endpoint_instance, space, graph_id: str, entity_uri: str, 
                                 incoming_objects: list, incoming_uris: set, parent_uri: str = None) -> EntityUpdateResponse:
    """Handle UPDATE mode: verify entity exists and replace with new content.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space: The space object containing the data store
        graph_id: Graph identifier
        entity_uri: URI of the entity to update
        incoming_objects: List of VitalSigns objects to store
        incoming_uris: Set of URIs from incoming objects
        parent_uri: Optional parent URI for validation
        
    Returns:
        EntityUpdateResponse with success/failure information
    """
    try:
        # Check if entity exists
        if not endpoint_instance._entity_exists_in_store(space, entity_uri, graph_id):
            return EntityUpdateResponse(
                message=f"Entity {entity_uri} does not exist - cannot update in 'update' mode",
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
        
        # Backup, delete, and insert atomically
        backup_data = endpoint_instance._backup_entity_graph(space, entity_uri, graph_id)
        
        try:
            deletion_success = endpoint_instance._delete_entity_graph_from_store(space, entity_uri, graph_id)
            if not deletion_success:
                raise Exception("Failed to delete existing entity graph")
            
            endpoint_instance._set_dual_grouping_uris(incoming_objects, entity_uri)
            stored_count = endpoint_instance._store_vitalsigns_objects_in_pyoxigraph(space, incoming_objects, graph_id)
            
            if stored_count > 0:
                return EntityUpdateResponse(
                    message=f"Successfully updated entity: {entity_uri}",
                    updated_uri=entity_uri
                )
            else:
                raise Exception("Failed to store updated objects")
                
        except Exception as update_error:
            # Rollback on failure
            endpoint_instance.logger.info(f"Rolling back entity {entity_uri} due to update failure")
            endpoint_instance._restore_entity_graph_from_backup(space, entity_uri, graph_id, backup_data)
            raise update_error
            
    except Exception as e:
        endpoint_instance.logger.error(f"Error in entity update mode: {e}")
        return EntityUpdateResponse(
            message=f"Error updating entity: {e}",
            updated_uri=""
        )


def update_kgentities_impl(endpoint_instance, space_id: str, graph_id: str, objects: list, 
                          operation_mode: str = "update", parent_uri: str = None) -> EntityUpdateResponse:
    """
    Update KGEntities with proper entity lifecycle management.
    
    This method implements the complete entity update requirements:
    - Parent object URI validation (if provided)
    - Complete entity graph structure validation (entity→frame, frame→frame, frame→slot)
    - URI set matching validation for updates
    - Proper structure verification
    - Atomic operations with rollback
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier  
        objects: List of GraphObjects containing complete entity graph structure
        operation_mode: "create", "update", or "upsert"
        parent_uri: Optional parent object URI (entity or parent frame)
        
    Returns:
        EntityUpdateResponse with updated URI and operation details
    """
    endpoint_instance._log_method_call("update_kgentities", space_id=space_id, graph_id=graph_id, 
                         objects=objects, operation_mode=operation_mode, parent_uri=parent_uri)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return EntityUpdateResponse(
                message="Space not found",
                updated_uri=""
            )
        
        # Step 1: Validate parent object existence and connecting edge (if provided)
        if parent_uri:
            parent_exists = endpoint_instance._validate_parent_object(space, parent_uri, graph_id)
            if not parent_exists:
                return EntityUpdateResponse(
                    message=f"Parent object {parent_uri} does not exist",
                    updated_uri=""
                )
        
        # Step 2: Use incoming GraphObjects directly (server sets grouping URIs)
        incoming_objects = list(objects) if objects else []
        endpoint_instance.logger.info(f"Step 2: Received {len(incoming_objects)} GraphObjects")
        
        if not incoming_objects:
            return EntityUpdateResponse(
                message="No valid objects found",
                updated_uri=""
            )
        
        # Step 4: Validate complete entity graph structure
        entity_structure = endpoint_instance._validate_entity_graph_structure(incoming_objects)
        if not entity_structure['valid']:
            return EntityUpdateResponse(
                message=f"Invalid entity graph structure: {entity_structure['error']}",
                updated_uri=""
            )
        
        entity_uri = entity_structure['entity_uri']
        incoming_uris = entity_structure['all_uris']
        
        # Step 5: Handle operation mode-specific logic
        if operation_mode == "create":
            return endpoint_instance._handle_entity_create_mode(space, graph_id, entity_uri, incoming_objects, incoming_uris, parent_uri)
        elif operation_mode == "update":
            return endpoint_instance._handle_entity_update_mode(space, graph_id, entity_uri, incoming_objects, incoming_uris, parent_uri)
        elif operation_mode == "upsert":
            return endpoint_instance._handle_entity_upsert_mode(space, graph_id, entity_uri, incoming_objects, incoming_uris, parent_uri)
        else:
            return EntityUpdateResponse(
                message=f"Invalid operation mode: {operation_mode}",
                updated_uri=""
            )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error in update_kgentities: {e}")
        return EntityUpdateResponse(
            message=f"Error updating KGEntities: {e}",
            updated_uri=""
        )


def update_entity_frames_impl(endpoint_instance, space_id: str, graph_id: str, entity_uri: str, objects: list) -> FrameUpdateResponse:
    """
    Update frames within entity context using Edge_hasKGFrame relationships.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        entity_uri: Entity URI to update frames for
        objects: List of GraphObjects containing updated frames
        
    Returns:
        FrameUpdateResponse with update details
    """
    from ai_haley_kg_domain.model.KGFrame import KGFrame
    from vitalgraph.model.kgframes_model import FrameUpdateResponse
    
    endpoint_instance._log_method_call("update_entity_frames", space_id=space_id, graph_id=graph_id, entity_uri=entity_uri)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return FrameUpdateResponse(
                message=f"Space {space_id} not found",
                updated_uri=""
            )
        
        if not objects:
            return FrameUpdateResponse(
                message="No valid frames found in objects",
                updated_uri=""
            )
        
        # Filter for KGFrame objects and update them
        frames = [obj for obj in objects if isinstance(obj, KGFrame)]
        updated_uris = []
        
        for frame in frames:
            frame_uri = str(frame.URI)
            
            # Delete existing frame triples
            if graph_id:
                delete_query = f"""
                DELETE WHERE {{
                    GRAPH <{graph_id}> {{
                        <{frame_uri}> ?p ?o .
                    }}
                }}
                """
            else:
                delete_query = f"""
                DELETE WHERE {{
                    <{frame_uri}> ?p ?o .
                }}
                """
            endpoint_instance._execute_sparql_update(space, delete_query)
            
            # Insert updated frame triples
            frame_triples = endpoint_instance._object_to_triples(frame, graph_id)
            endpoint_instance._store_triples(space, frame_triples)
            
            updated_uris.append(frame_uri)
        
        return FrameUpdateResponse(
            message=f"Successfully updated {len(updated_uris)} frames for entity {entity_uri}",
            updated_uri=updated_uris[0] if updated_uris else ""
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error updating entity frames: {e}")
        return FrameUpdateResponse(
            message=f"Error updating entity frames: {e}",
            updated_uri=""
        )