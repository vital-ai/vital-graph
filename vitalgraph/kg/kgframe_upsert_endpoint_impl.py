"""
KGFrame Upsert Operations Implementation

This module contains the implementation functions for KGFrame upsert operations,
extracted from MockKGFramesEndpoint to improve code organization and maintainability.
"""

from vitalgraph.model.kgframes_model import FrameUpdateResponse


def handle_upsert_mode_impl(endpoint_instance, space, graph_id: str, frame_uri: str, incoming_objects: list,
                           incoming_uris: set, parent_uri: str = None) -> FrameUpdateResponse:
    """Handle UPSERT mode: create or update, verify structure and frame URI consistency."""
    from ai_haley_kg_domain.model.KGFrame import KGFrame
    
    try:
        frame_exists = endpoint_instance._frame_exists_in_store(space, frame_uri, graph_id)
        
        if frame_exists:
            # Get current objects and verify top-level frame URI matches
            current_objects = endpoint_instance._get_current_frame_objects(space, frame_uri, graph_id)
            current_frame = next((obj for obj in current_objects if isinstance(obj, KGFrame)), None)
            
            if current_frame and str(current_frame.URI) != frame_uri:
                return FrameUpdateResponse(
                    message=f"Frame URI mismatch: expected {frame_uri}, found {current_frame.URI}",
                    updated_uri=""
                )
            
            # Delete existing frame objects (excluding frame-to-frame connections if parent is frame)
            if parent_uri and endpoint_instance._is_frame_parent(space, parent_uri, graph_id):
                # Preserve frame-to-frame connections
                deletion_success = endpoint_instance._delete_frame_graph_excluding_parent_edges(space, frame_uri, graph_id, parent_uri)
            else:
                deletion_success = endpoint_instance._delete_frame_graph_from_store(space, frame_uri, graph_id)
            
            if not deletion_success:
                return FrameUpdateResponse(
                    message="Failed to delete existing frame objects",
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
        
        # Insert new version of frame
        endpoint_instance._set_frame_grouping_uris(incoming_objects, frame_uri)
        stored_count = endpoint_instance._store_vitalsigns_objects_in_pyoxigraph(space, incoming_objects, graph_id)
        
        if stored_count > 0:
            action = "updated" if frame_exists else "created"
            return FrameUpdateResponse(
                message=f"Successfully {action} frame: {frame_uri}",
                updated_uri=frame_uri
            )
        else:
            return FrameUpdateResponse(
                message="Failed to store frame objects",
                updated_uri=""
            )
            
    except Exception as e:
        endpoint_instance.logger.error(f"Error in upsert mode: {e}")
        return FrameUpdateResponse(
            message=f"Error upserting frame: {e}",
            updated_uri=""
        )