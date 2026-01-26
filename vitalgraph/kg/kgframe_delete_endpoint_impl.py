"""
KGFrame Delete Operations Implementation

This module contains the implementation functions for KGFrame deletion operations,
extracted from MockKGFramesEndpoint to improve code organization and maintainability.
"""

from typing import List, Optional, Any
from vitalgraph.model.kgframes_model import FrameDeleteResponse, SlotDeleteResponse


def delete_kgframe_impl(endpoint_instance, space_id: str, graph_id: str, uri: str) -> FrameDeleteResponse:
    """
    Delete a KGFrame by URI using pyoxigraph SPARQL DELETE.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        uri: Frame URI to delete
        
    Returns:
        FrameDeleteResponse with deletion count
    """
    endpoint_instance._log_method_call("delete_kgframe", space_id=space_id, graph_id=graph_id, uri=uri)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return FrameDeleteResponse(
                message="Space not found",
                deleted_count=0
            )
        
        # Delete quads from pyoxigraph
        if endpoint_instance._delete_quads_from_store(space, uri, graph_id):
            return FrameDeleteResponse(
                message=f"Successfully deleted KGFrame: {uri}",
                deleted_count=1
            )
        else:
            return FrameDeleteResponse(
                message=f"KGFrame not found: {uri}",
                deleted_count=0
            )
            
    except Exception as e:
        endpoint_instance.logger.error(f"Error deleting KGFrame {uri}: {e}")
        return FrameDeleteResponse(
            message=f"Error deleting KGFrame {uri}: {e}",
            deleted_count=0
        )


def delete_frame_slots_impl(endpoint_instance, space_id: str, graph_id: str, frame_uri: str, 
                          slot_uris: List[str]) -> SlotDeleteResponse:
    """
    Delete specific slots from frame using /kgframes/kgslots sub-endpoint.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        frame_uri: Parent frame URI
        slot_uris: List of slot URIs to delete
        
    Returns:
        SlotDeleteResponse with deletion details
    """
    endpoint_instance._log_method_call("delete_frame_slots", space_id=space_id, graph_id=graph_id, 
                         frame_uri=frame_uri, slot_uris=slot_uris)
    
    try:
        # Import response model
        from vitalgraph.model.kgframes_model import SlotDeleteResponse
        
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return SlotDeleteResponse(
                message="Space not found",
                deleted_count=0
            )
        
        # Validate parent frame exists
        frame_exists = endpoint_instance._validate_frame_exists(space, graph_id, frame_uri)
        if not frame_exists:
            return SlotDeleteResponse(
                message=f"Parent frame not found: {frame_uri}",
                deleted_count=0
            )
        
        deleted_count = 0
        
        # Delete each slot and validate connection
        for slot_uri in slot_uris:
            # Validate slot exists and is connected to frame
            if not endpoint_instance._slot_exists(space, graph_id, slot_uri):
                endpoint_instance.logger.warning(f"Slot not found: {slot_uri}")
                continue
            
            if not endpoint_instance._validate_frame_slot_connection(space, graph_id, frame_uri, slot_uri):
                endpoint_instance.logger.warning(f"Slot not connected to frame: {slot_uri}")
                continue
            
            # Delete slot triples
            success = endpoint_instance._delete_slot_triples(space, graph_id, slot_uri)
            if success:
                deleted_count += 1
                
            # Delete the frame-slot edge
            endpoint_instance._delete_frame_slot_edge(space, graph_id, frame_uri, slot_uri)
        
        return SlotDeleteResponse(
            message=f"Successfully deleted {deleted_count} slots from frame",
            deleted_count=deleted_count
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error deleting frame slots: {e}")
        return SlotDeleteResponse(
            message=f"Error deleting frame slots: {e}",
            deleted_count=0
        )


def delete_frame_graph_from_store_impl(endpoint_instance, space, frame_uri: str, graph_id: str) -> bool:
    """Delete complete frame graph (frame + slots + edges) to prevent stale triples."""
    try:
        import pyoxigraph as px
        
        # Step 1: Find and delete connected slots
        if graph_id:
            slot_delete_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            DELETE {{
                GRAPH <{graph_id}> {{
                    ?slot ?predicate ?object .
                }}
            }}
            WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a haley:Edge_hasKGSlot .
                    ?edge vital:hasEdgeSource <{frame_uri}> .
                    ?edge vital:hasEdgeDestination ?slot .
                    ?slot ?predicate ?object .
                }}
            }}
            """
        else:
            slot_delete_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            DELETE {{
                ?slot ?predicate ?object .
            }}
            WHERE {{
                ?edge a haley:Edge_hasKGSlot .
                ?edge vital:hasEdgeSource <{frame_uri}> .
                ?edge vital:hasEdgeDestination ?slot .
                ?slot ?predicate ?object .
            }}
            """
        
        space.store.update(slot_delete_query)
        
        # Step 2: Delete Edge_hasKGSlot relationships
        if graph_id:
            edge_delete_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            DELETE {{
                GRAPH <{graph_id}> {{
                    ?edge ?predicate ?object .
                }}
            }}
            WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a haley:Edge_hasKGSlot .
                    ?edge vital:hasEdgeSource <{frame_uri}> .
                    ?edge ?predicate ?object .
                }}
            }}
            """
        else:
            edge_delete_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            DELETE {{
                ?edge ?predicate ?object .
            }}
            WHERE {{
                ?edge a haley:Edge_hasKGSlot .
                ?edge vital:hasEdgeSource <{frame_uri}> .
                ?edge ?predicate ?object .
            }}
            """
        
        space.store.update(edge_delete_query)
        
        # Step 3: Delete frame itself
        if graph_id:
            frame_delete_query = f"""
            DELETE {{
                GRAPH <{graph_id}> {{
                    <{frame_uri}> ?predicate ?object .
                }}
            }}
            WHERE {{
                GRAPH <{graph_id}> {{
                    <{frame_uri}> ?predicate ?object .
                }}
            }}
            """
        else:
            frame_delete_query = f"""
            DELETE {{
                <{frame_uri}> ?predicate ?object .
            }}
            WHERE {{
                <{frame_uri}> ?predicate ?object .
            }}
            """
        
        space.store.update(frame_delete_query)
        
        endpoint_instance.logger.info(f"Successfully deleted complete frame graph for {frame_uri}")
        return True
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error deleting frame graph for {frame_uri}: {e}")
        return False


def delete_kgframes_batch_impl(endpoint_instance, space_id: str, graph_id: str, uri_list: str):
    """
    Delete multiple KGFrames by URI list using pyoxigraph batch operations.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        uri_list: Comma-separated list of URIs to delete
        
    Returns:
        FrameDeleteResponse with total deletion count
    """
    from vitalgraph.model.kgframes_model import FrameDeleteResponse
    
    endpoint_instance._log_method_call("delete_kgframes_batch", space_id=space_id, graph_id=graph_id, uri_list=uri_list)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return FrameDeleteResponse(
                message="Space not found",
                deleted_count=0
            )
        
        # Parse URI list
        uris = [uri.strip() for uri in uri_list.split(',') if uri.strip()]
        
        if not uris:
            return FrameDeleteResponse(
                message="No URIs provided",
                deleted_count=0
            )
        
        # Delete each frame
        deleted_count = 0
        for uri in uris:
            if endpoint_instance._delete_quads_from_store(space, uri, graph_id):
                deleted_count += 1
        
        return FrameDeleteResponse(
            message=f"Successfully deleted {deleted_count} of {len(uris)} KGFrame(s)",
            deleted_count=deleted_count
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error batch deleting KGFrames: {e}")
        return FrameDeleteResponse(
            message=f"Error batch deleting KGFrames: {e}",
            deleted_count=0
        )

