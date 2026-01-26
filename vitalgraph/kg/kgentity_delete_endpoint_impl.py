"""
KGEntity Delete Operations Implementation

This module contains the implementation functions for KGEntity deletion operations,
extracted from MockKGEntitiesEndpoint to improve code organization and maintainability.
"""

from typing import List, Optional, Any
from vitalgraph.model.kgentities_model import EntityDeleteResponse
from vitalgraph.model.kgframes_model import FrameDeleteResponse


def delete_kgentity_impl(endpoint_instance, space_id: str, graph_id: str, uri: str, delete_entity_graph: bool = False) -> EntityDeleteResponse:
    """
    Delete a KGEntity by URI using pyoxigraph SPARQL DELETE.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        uri: Entity URI to delete
        delete_entity_graph: If True, delete complete entity graph including frames and slots
        
    Returns:
        EntityDeleteResponse with deletion count
    """
    endpoint_instance._log_method_call("delete_kgentity", space_id=space_id, graph_id=graph_id, uri=uri, delete_entity_graph=delete_entity_graph)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return EntityDeleteResponse(
                message="Space not found",
                deleted_count=0
            )
        
        deleted_count = 0
        
        if delete_entity_graph:
            # Delete complete entity graph including all frames, slots, and edges
            # Use hasKGGraphURI to find all objects belonging to this entity graph
            if graph_id:
                delete_graph_query = f"""
                DELETE WHERE {{
                    GRAPH <{graph_id}> {{
                        ?s <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> <{uri}> .
                        ?s ?p ?o .
                    }}
                }}
                """
            else:
                delete_graph_query = f"""
                DELETE WHERE {{
                    ?s <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> <{uri}> .
                    ?s ?p ?o .
                }}
                """
            
            endpoint_instance._execute_sparql_update(space, delete_graph_query)
            endpoint_instance.logger.info(f"Deleted complete entity graph for: {uri}")
            deleted_count = 1
        else:
            # Delete only the entity itself
            if endpoint_instance._delete_quads_from_store(space, uri, graph_id):
                deleted_count = 1
        
        if deleted_count > 0:
            return EntityDeleteResponse(
                message=f"Successfully deleted KGEntity: {uri}" + (" with complete graph" if delete_entity_graph else ""),
                deleted_count=deleted_count
            )
        else:
            return EntityDeleteResponse(
                message=f"KGEntity not found: {uri}",
                deleted_count=0
            )
            
    except Exception as e:
        endpoint_instance.logger.error(f"Error deleting KGEntity {uri}: {e}")
        return EntityDeleteResponse(
            message=f"Error deleting KGEntity: {e}",
            deleted_count=0
        )


def delete_kgentities_batch_impl(endpoint_instance, space_id: str, graph_id: str, uri_list: str) -> EntityDeleteResponse:
    """
    Delete multiple KGEntities by URI list using pyoxigraph batch operations.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        uri_list: Comma-separated list of URIs to delete
        
    Returns:
        EntityDeleteResponse with total deletion count
    """
    endpoint_instance._log_method_call("delete_kgentities_batch", space_id=space_id, graph_id=graph_id, uri_list=uri_list)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return EntityDeleteResponse(
                message="Space not found",
                deleted_count=0
            )
        
        # Parse URI list
        uris = [uri.strip() for uri in uri_list.split(',') if uri.strip()]
        
        if not uris:
            return EntityDeleteResponse(
                message="No URIs provided",
                deleted_count=0
            )
        
        # Delete each entity
        deleted_count = 0
        for uri in uris:
            if endpoint_instance._delete_quads_from_store(space, uri, graph_id):
                deleted_count += 1
        
        return EntityDeleteResponse(
            message=f"Successfully deleted {deleted_count} of {len(uris)} KGEntity(s)",
            deleted_count=deleted_count
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error batch deleting KGEntities: {e}")
        return EntityDeleteResponse(
            message=f"Error batch deleting KGEntities: {e}",
            deleted_count=0
        )


def delete_entity_frames_impl(endpoint_instance, space_id: str, graph_id: str, entity_uri: str, frame_uris: List[str]) -> FrameDeleteResponse:
    """
    Delete frames within entity context using Edge_hasKGFrame relationships.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        entity_uri: Entity URI to delete frames from
        frame_uris: List of frame URIs to delete
        
    Returns:
        FrameDeleteResponse with deletion details
    """
    endpoint_instance._log_method_call("delete_entity_frames", space_id=space_id, graph_id=graph_id, entity_uri=entity_uri, frame_uris=frame_uris)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return FrameDeleteResponse(
                message=f"Space {space_id} not found",
                deleted_count=0,
                deleted_uris=[]
            )
        
        deleted_uris = []
        
        for frame_uri in frame_uris:
            # Delete frame triples
            if graph_id:
                delete_frame_query = f"""
                DELETE WHERE {{
                    GRAPH <{graph_id}> {{
                        <{frame_uri}> ?p ?o .
                    }}
                }}
                """
            else:
                delete_frame_query = f"""
                DELETE WHERE {{
                    <{frame_uri}> ?p ?o .
                }}
                """
            endpoint_instance._execute_sparql_update(space, delete_frame_query)
            
            # Delete Edge_hasKGFrame relationship
            if graph_id:
                delete_edge_query = f"""
                DELETE WHERE {{
                    GRAPH <{graph_id}> {{
                        ?edge a <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame> .
                        ?edge <http://vital.ai/ontology/vital-core#hasEdgeSource> <{entity_uri}> .
                        ?edge <http://vital.ai/ontology/vital-core#hasEdgeDestination> <{frame_uri}> .
                        ?edge ?p ?o .
                    }}
                }}
                """
            else:
                delete_edge_query = f"""
                DELETE WHERE {{
                    ?edge a <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame> .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeSource> <{entity_uri}> .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeDestination> <{frame_uri}> .
                    ?edge ?p ?o .
                }}
                """
            endpoint_instance._execute_sparql_update(space, delete_edge_query)
            
            deleted_uris.append(frame_uri)
        
        return FrameDeleteResponse(
            message=f"Successfully deleted {len(deleted_uris)} frames from entity {entity_uri}",
            deleted_count=len(deleted_uris),
            deleted_uris=deleted_uris
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error deleting entity frames: {e}")
        return FrameDeleteResponse(
            message=f"Error deleting entity frames: {e}",
            deleted_count=0,
            deleted_uris=[]
        )


def delete_entity_frames_complex_impl(endpoint_instance, space_id: str, graph_id: str, entity_uri: str, 
                           frame_uris: List[str]) -> FrameDeleteResponse:
    """
    Delete specific frames from entity using /kgentities/kgframes sub-endpoint.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        entity_uri: Parent entity URI
        frame_uris: List of frame URIs to delete
        
    Returns:
        FrameDeleteResponse with deletion details
    """
    endpoint_instance._log_method_call("delete_entity_frames", space_id=space_id, graph_id=graph_id, 
                         entity_uri=entity_uri, frame_uris=frame_uris)
    
    try:
        # Import response model
        from vitalgraph.model.kgframes_model import FrameDeleteResponse
        
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return FrameDeleteResponse(
                message="Space not found",
                deleted_count=0
            )
        
        # Validate parent entity exists
        entity_exists = endpoint_instance._validate_entity_exists(space, graph_id, entity_uri)
        if not entity_exists:
            return FrameDeleteResponse(
                message=f"Parent entity not found: {entity_uri}",
                deleted_count=0
            )
        
        deleted_count = 0
        
        # Delete each frame and validate connection
        for frame_uri in frame_uris:
            # Validate frame exists and is connected to entity
            if not endpoint_instance._frame_exists(space, graph_id, frame_uri):
                endpoint_instance.logger.warning(f"Frame not found: {frame_uri}")
                continue
            
            if not endpoint_instance._validate_entity_frame_connection(space, graph_id, entity_uri, frame_uri):
                endpoint_instance.logger.warning(f"Frame not connected to entity: {frame_uri}")
                continue
            
            # Delete frame and all its components (slots, edges)
            success = endpoint_instance._delete_frame_with_components(space, graph_id, frame_uri)
            if success:
                deleted_count += 1
                
            # Delete the entity-frame edge
            endpoint_instance._delete_entity_frame_edge(space, graph_id, entity_uri, frame_uri)
        
        return FrameDeleteResponse(
            message=f"Successfully deleted {deleted_count} frames from entity",
            deleted_count=deleted_count
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error deleting entity frames: {e}")
        return FrameDeleteResponse(
            message=f"Error deleting entity frames: {e}",
            deleted_count=0
        )