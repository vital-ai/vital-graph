"""
KGFrame Update Operations Implementation

This module contains the implementation functions for KGFrame update operations,
extracted from MockKGFramesEndpoint to improve code organization and maintainability.
"""

from vitalgraph.model.kgframes_model import FrameUpdateResponse
from vitalgraph.model.jsonld_model import JsonLdDocument


def update_kgframes_impl(endpoint_instance, space_id: str, graph_id: str, document: JsonLdDocument, 
                       operation_mode: str = "update", parent_uri: str = None) -> FrameUpdateResponse:
    """
    Update KGFrames with proper frame lifecycle management.
    
    This method implements the complete frame update requirements:
    - Parent object URI validation (if provided)
    - Complete frame structure validation (frame + edges + slots)
    - URI set matching validation for updates
    - Proper structure verification
    - Atomic operations with rollback
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier  
        document: JsonLdDocument containing complete frame structure
        operation_mode: "create", "update", or "upsert"
        parent_uri: Optional parent object URI (entity or parent frame)
        
    Returns:
        FrameUpdateResponse with updated URI and operation details
    """
    endpoint_instance._log_method_call("update_kgframes", space_id=space_id, graph_id=graph_id, 
                         document=document, operation_mode=operation_mode, parent_uri=parent_uri)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return FrameUpdateResponse(
                message="Space not found",
                updated_uri=""
            )
        
        # Step 1: Validate parent object existence and connecting edge (if provided)
        if parent_uri:
            parent_exists = endpoint_instance._validate_parent_object(space, parent_uri, graph_id)
            if not parent_exists:
                return FrameUpdateResponse(
                    message=f"Parent object {parent_uri} does not exist",
                    updated_uri=""
                )
        
        # Step 2: Strip client-provided grouping URIs (server authority)
        stripped_document = endpoint_instance._strip_grouping_uris(document)
        endpoint_instance.logger.info("Step 2: Stripped client-provided grouping URIs")
        
        # Step 3: Create VitalSigns objects and validate frame structure
        document_dict = stripped_document.model_dump(by_alias=True)
        incoming_objects = endpoint_instance._create_vitalsigns_objects_from_jsonld(document_dict)
        
        if not incoming_objects:
            return FrameUpdateResponse(
                message="No valid objects found in document",
                updated_uri=""
            )
        
        # Step 4: Validate complete frame structure
        frame_structure = endpoint_instance._validate_frame_structure(incoming_objects)
        if not frame_structure['valid']:
            return FrameUpdateResponse(
                message=f"Invalid frame structure: {frame_structure['error']}",
                updated_uri=""
            )
        
        frame_uri = frame_structure['frame_uri']
        incoming_uris = frame_structure['all_uris']
        
        # Step 5: Handle operation mode-specific logic
        if operation_mode == "create":
            return endpoint_instance._handle_create_mode(space, graph_id, frame_uri, incoming_objects, incoming_uris, parent_uri)
        elif operation_mode == "update":
            return endpoint_instance._handle_update_mode(space, graph_id, frame_uri, incoming_objects, incoming_uris, parent_uri)
        elif operation_mode == "upsert":
            return endpoint_instance._handle_upsert_mode(space, graph_id, frame_uri, incoming_objects, incoming_uris, parent_uri)
        else:
            return FrameUpdateResponse(
                message=f"Invalid operation mode: {operation_mode}",
                updated_uri=""
            )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error in update_kgframes: {e}")
        return FrameUpdateResponse(
            message=f"Error updating KGFrames: {e}",
            updated_uri=""
        )


def handle_update_mode_impl(endpoint_instance, space, graph_id: str, frame_uri: str, incoming_objects: list,
                           incoming_uris: set, parent_uri: str = None) -> FrameUpdateResponse:
    """Handle UPDATE mode: verify frame exists and replace with new content."""
    try:
        # Check if frame exists
        if not endpoint_instance._frame_exists_in_store(space, frame_uri, graph_id):
            return FrameUpdateResponse(
                message=f"Frame {frame_uri} does not exist - cannot update in 'update' mode",
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
        
        # Backup, delete, and insert atomically
        backup_data = endpoint_instance._backup_frame_graph(space, frame_uri, graph_id)
        
        try:
            deletion_success = endpoint_instance._delete_frame_graph_from_store(space, frame_uri, graph_id)
            if not deletion_success:
                raise Exception("Failed to delete existing frame graph")
            
            endpoint_instance._set_frame_grouping_uris(incoming_objects, frame_uri)
            stored_count = endpoint_instance._store_vitalsigns_objects_in_pyoxigraph(space, incoming_objects, graph_id)
            
            if stored_count > 0:
                return FrameUpdateResponse(
                    message=f"Successfully updated frame: {frame_uri}",
                    updated_uri=frame_uri
                )
            else:
                raise Exception("Failed to store updated objects")
                
        except Exception as update_error:
            # Rollback on failure
            endpoint_instance.logger.info(f"Rolling back frame {frame_uri} due to update failure")
            endpoint_instance._restore_frame_graph_from_backup(space, frame_uri, graph_id, backup_data)
            raise update_error
            
    except Exception as e:
        endpoint_instance.logger.error(f"Error in update mode: {e}")
        return FrameUpdateResponse(
            message=f"Error updating frame: {e}",
            updated_uri=""
        )


def update_frame_slots_impl(endpoint_instance, space_id: str, graph_id: str, frame_uri: str, document: JsonLdDocument):
    """
    Update slots for a specific frame using Edge_hasKGSlot relationships.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        frame_uri: Frame URI to update slots for
        document: JsonLdDocument containing updated KGSlots
        
    Returns:
        SlotUpdateResponse containing operation result
    """
    from vitalgraph.model.kgframes_model import SlotUpdateResponse
    from ai_haley_kg_domain.model.KGSlot import KGSlot
    
    endpoint_instance._log_method_call("update_frame_slots", space_id=space_id, graph_id=graph_id, frame_uri=frame_uri)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return SlotUpdateResponse(
                message="Space not found",
                updated_uri=""
            )
        
        # Convert JSON-LD document to VitalSigns objects
        document_dict = document.model_dump(by_alias=True)
        objects = endpoint_instance._jsonld_to_vitalsigns_objects(document_dict)
        
        if not objects:
            return SlotUpdateResponse(
                message="No valid objects found in document",
                updated_uri=""
            )
        
        # Filter for KGSlot objects
        slots = [obj for obj in objects if isinstance(obj, KGSlot)]
        
        if not slots:
            return SlotUpdateResponse(
                message="No KGSlot objects found in document",
                updated_uri=""
            )
        
        # Store updated slots in pyoxigraph
        stored_count = endpoint_instance._store_vitalsigns_objects_in_pyoxigraph(space, slots, graph_id)
        
        # Return first slot URI as updated URI
        updated_uri = str(slots[0].URI) if slots else ""
        
        return SlotUpdateResponse(
            message=f"Successfully updated {stored_count} KGSlot(s) for frame {frame_uri}",
            updated_uri=updated_uri
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error updating frame slots: {e}")
        return SlotUpdateResponse(
            message=f"Error updating frame slots: {e}",
            updated_uri=""
        )


def backup_frame_graph_impl(endpoint_instance, space, frame_uri: str, graph_id: str) -> dict:
    """Backup complete frame graph (frame + slots + edges) for rollback capability."""
    try:
        backup_data = {
            'frame_triples': [],
            'slot_triples': [],
            'edge_triples': []
        }
        
        # Query for frame triples
        if graph_id:
            frame_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            SELECT ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    <{frame_uri}> ?predicate ?object .
                }}
            }}
            """
        else:
            frame_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            SELECT ?predicate ?object WHERE {{
                <{frame_uri}> ?predicate ?object .
            }}
            """
        
        frame_results = space.store.query(frame_query)
        for result in frame_results:
            backup_data['frame_triples'].append({
                'subject': frame_uri,
                'predicate': str(result['predicate']),
                'object': str(result['object'])
            })
        
        # Query for connected slots via Edge_hasKGSlot
        if graph_id:
            slot_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            SELECT ?slot ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a haley:Edge_hasKGSlot .
                    ?edge vital:hasEdgeSource <{frame_uri}> .
                    ?edge vital:hasEdgeDestination ?slot .
                    ?slot ?predicate ?object .
                }}
            }}
            """
        else:
            slot_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            SELECT ?slot ?predicate ?object WHERE {{
                ?edge a haley:Edge_hasKGSlot .
                ?edge vital:hasEdgeSource <{frame_uri}> .
                ?edge vital:hasEdgeDestination ?slot .
                ?slot ?predicate ?object .
            }}
            """
        
        slot_results = space.store.query(slot_query)
        for result in slot_results:
            backup_data['slot_triples'].append({
                'subject': str(result['slot']),
                'predicate': str(result['predicate']),
                'object': str(result['object'])
            })
        
        # Query for edge triples
        if graph_id:
            edge_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            SELECT ?edge ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a haley:Edge_hasKGSlot .
                    ?edge vital:hasEdgeSource <{frame_uri}> .
                    ?edge ?predicate ?object .
                }}
            }}
            """
        else:
            edge_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            SELECT ?edge ?predicate ?object WHERE {{
                ?edge a haley:Edge_hasKGSlot .
                ?edge vital:hasEdgeSource <{frame_uri}> .
                ?edge ?predicate ?object .
            }}
            """
        
        edge_results = space.store.query(edge_query)
        for result in edge_results:
            backup_data['edge_triples'].append({
                'subject': str(result['edge']),
                'predicate': str(result['predicate']),
                'object': str(result['object'])
            })
        
        endpoint_instance.logger.info(f"Backed up frame graph for {frame_uri}: "
                       f"{len(backup_data['frame_triples'])} frame triples, "
                       f"{len(backup_data['slot_triples'])} slot triples, "
                       f"{len(backup_data['edge_triples'])} edge triples")
        
        return backup_data
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error backing up frame graph for {frame_uri}: {e}")
        return {'frame_triples': [], 'slot_triples': [], 'edge_triples': []}


def restore_frame_graph_from_backup_impl(endpoint_instance, space, frame_uri: str, graph_id: str, backup_data: dict) -> bool:
    """Restore frame graph from backup data for rollback operations."""
    try:
        import pyoxigraph as px
        
        from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
        
        # Restore frame triples
        for triple in backup_data.get('frame_triples', []):
            obj_str = str(triple['object'])
            quad = px.Quad(
                px.NamedNode(triple['subject']),
                px.NamedNode(triple['predicate']),
                px.NamedNode(obj_str) if validate_rfc3986(obj_str, rule='URI') else px.Literal(obj_str),
                px.NamedNode(graph_id)
            )
            space.store.add(quad)
        
        # Restore slot triples
        for triple in backup_data.get('slot_triples', []):
            obj_str = str(triple['object'])
            quad = px.Quad(
                px.NamedNode(triple['subject']),
                px.NamedNode(triple['predicate']),
                px.NamedNode(obj_str) if validate_rfc3986(obj_str, rule='URI') else px.Literal(obj_str),
                px.NamedNode(graph_id)
            )
            space.store.add(quad)
        
        # Restore edge triples
        for triple in backup_data.get('edge_triples', []):
            obj_str = str(triple['object'])
            quad = px.Quad(
                px.NamedNode(triple['subject']),
                px.NamedNode(triple['predicate']),
                px.NamedNode(obj_str) if validate_rfc3986(obj_str, rule='URI') else px.Literal(obj_str),
                px.NamedNode(graph_id)
            )
            space.store.add(quad)
        
        endpoint_instance.logger.info(f"Successfully restored frame graph backup for {frame_uri}")
        return True
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error restoring frame graph backup for {frame_uri}: {e}")
        return False
