"""
KGEntity Upsert Endpoint Implementation

This module contains the implementation functions for KGEntity upsert operations
that have been extracted from MockKGEntitiesEndpoint for better code organization.
"""

from typing import List, Set, Optional, Any
from vitalgraph.model.kgentities_model import EntityUpdateResponse


def handle_entity_upsert_mode_impl(endpoint_instance, space, graph_id: str, entity_uri: str, 
                                 incoming_objects: list, incoming_uris: set, parent_uri: str = None) -> EntityUpdateResponse:
    """Handle UPSERT mode: create or update, verify structure and entity URI consistency.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space: The space object containing the data store
        graph_id: Graph identifier
        entity_uri: URI of the entity to upsert
        incoming_objects: List of VitalSigns objects to store
        incoming_uris: Set of URIs from incoming objects
        parent_uri: Optional parent URI for validation
        
    Returns:
        EntityUpdateResponse with success/failure information
    """
    try:
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        entity_exists = endpoint_instance._entity_exists_in_store(space, entity_uri, graph_id)
        
        if entity_exists:
            # Get current objects and verify top-level entity URI matches
            current_objects = endpoint_instance._get_current_entity_objects(space, entity_uri, graph_id)
            current_entity = next((obj for obj in current_objects if isinstance(obj, KGEntity)), None)
            
            if current_entity and str(current_entity.URI) != entity_uri:
                return EntityUpdateResponse(
                    message=f"Entity URI mismatch: expected {entity_uri}, found {current_entity.URI}",
                    updated_uri=""
                )
            
            # Delete existing entity objects
            deletion_success = endpoint_instance._delete_entity_graph_from_store(space, entity_uri, graph_id)
            if not deletion_success:
                return EntityUpdateResponse(
                    message="Failed to delete existing entity objects",
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
        
        # Insert new version of entity with dual grouping URIs
        endpoint_instance._set_dual_grouping_uris(incoming_objects, entity_uri)
        stored_count = endpoint_instance._store_vitalsigns_objects_in_pyoxigraph(space, incoming_objects, graph_id)
        
        if stored_count > 0:
            action = "updated" if entity_exists else "created"
            return EntityUpdateResponse(
                message=f"Successfully {action} entity: {entity_uri}",
                updated_uri=entity_uri
            )
        else:
            return EntityUpdateResponse(
                message="Failed to store entity objects",
                updated_uri=""
            )
            
    except Exception as e:
        endpoint_instance.logger.error(f"Error in entity upsert mode: {e}")
        return EntityUpdateResponse(
            message=f"Error upserting entity: {e}",
            updated_uri=""
        )