"""
Mock implementation of KGFramesEndpoint for testing with VitalSigns native JSON-LD functionality.

This implementation uses:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store for data persistence
- Proper vitaltype handling for KGFrame and KGSlot objects
- Complete CRUD operations following real endpoint patterns
- Frame-slot relationship handling
- VitalSigns integration patterns from MockKGEntitiesEndpoint
- Grouping URI enforcement for frame operations
- isinstance() type checking and Property object handling
"""

from typing import Dict, Any, Optional, List
import traceback
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.kgframes_model import (
    FramesResponse, FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse,
    SlotCreateResponse, SlotUpdateResponse, SlotDeleteResponse,
    FrameQueryRequest, FrameQueryResponse
)
from vitalgraph.model.jsonld_model import JsonLdDocument
from vitalgraph.sparql.grouping_uri_queries import GroupingURIQueryBuilder, GroupingURIGraphRetriever
from vitalgraph.sparql.graph_validation import FrameGraphValidator
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge
from vital_ai_vitalsigns.model.GraphObject import GraphObject
# Property import - will be used for Property object handling patterns


class MockKGFramesEndpoint(MockBaseEndpoint):
    """Mock implementation of KGFramesEndpoint with VitalSigns native functionality and integration patterns."""
    
    def __init__(self, client=None, space_manager=None, *, config=None):
        """Initialize with SPARQL grouping URI functionality and frame validators."""
        super().__init__(client, space_manager, config=config)
        self.grouping_uri_builder = GroupingURIQueryBuilder()
        self.graph_retriever = GroupingURIGraphRetriever(self.grouping_uri_builder)
        self.frame_validator = FrameGraphValidator()
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
    
    def list_kgframes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> FramesResponse:
        """
        List KGFrames with pagination and optional search using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of frames per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            FramesResponse with VitalSigns native JSON-LD document
        """
        from vitalgraph.kg.kgframe_list_endpoint_impl import list_kgframes_impl
        return list_kgframes_impl(self, space_id, graph_id, page_size, offset, search)
    
    def get_kgframe(self, space_id: str, graph_id: str, uri: str, include_frame_graph: bool = False) -> JsonLdDocument:
        """
        Get a specific KGFrame by URI with optional complete graph using pyoxigraph SPARQL query.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGFrame URI
            include_frame_graph: If True, include complete frame graph (frames + slots + frame-to-frame edges)
            
        Returns:
            JsonLdDocument with VitalSigns native JSON-LD conversion
        """
        from vitalgraph.kg.kgframe_get_endpoint_impl import get_kgframe_impl
        return get_kgframe_impl(self, space_id, graph_id, uri, include_frame_graph)
    
    def query_frames(self, space_id: str, graph_id: str, query_request: FrameQueryRequest) -> FrameQueryResponse:
        """
        Query KGFrames using enhanced criteria-based search with sorting support.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            query_request: FrameQueryRequest containing search criteria, sorting, and pagination
            
        Returns:
            FrameQueryResponse containing list of matching frame URIs and pagination info
        """
        from vitalgraph.kg.kgframe_query_endpoint_impl import query_frames_impl
        return query_frames_impl(self, space_id, graph_id, query_request)
    
    def create_kgframes(self, space_id: str, graph_id: str, document: JsonLdDocument) -> FrameCreateResponse:
        """Create KGFrames from JSON-LD document with VitalSigns integration and grouping URI enforcement."""
        from vitalgraph.kg.kgframe_create_endpoint_impl import create_kgframes_impl
        return create_kgframes_impl(self, space_id, graph_id, document)
    
    def update_kgframes(self, space_id: str, graph_id: str, document: JsonLdDocument, 
                       operation_mode: str = "update", parent_uri: str = None, entity_uri: str = None) -> FrameUpdateResponse:
        """
        Update KGFrames with proper frame lifecycle management.
        
        This method implements the complete frame update requirements:
        - Parent object URI validation (if provided)
        - Complete frame structure validation (frame + edges + slots)
        - URI set matching validation for updates
        - Proper structure verification
        - Atomic operations with rollback
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier  
            document: JsonLdDocument containing complete frame structure
            operation_mode: "create", "update", or "upsert"
            parent_uri: Optional parent object URI (entity or parent frame)
            
        Returns:
            FrameUpdateResponse with updated URI and operation details
        """
        from vitalgraph.kg.kgframe_update_endpoint_impl import update_kgframes_impl
        # Use entity_uri as parent_uri if provided, otherwise use parent_uri
        effective_parent_uri = entity_uri if entity_uri else parent_uri
        return update_kgframes_impl(self, space_id, graph_id, document, operation_mode, effective_parent_uri)
    
    def _validate_parent_object(self, space, parent_uri: str, graph_id: str) -> bool:
        """Validate that parent object exists (entity or parent frame)."""
        from vitalgraph.utils.endpoint_validation import validate_parent_object
        return validate_parent_object(space, parent_uri, graph_id, self.logger)
    
    def _validate_frame_structure(self, objects: list) -> dict:
        """Validate that objects form a complete frame structure."""
        from vitalgraph.utils.validation_utils import validate_frame_graph_structure
        return validate_frame_graph_structure(objects)
    
    def _handle_create_mode(self, space, graph_id: str, frame_uri: str, incoming_objects: list, 
                           incoming_uris: set, parent_uri: str = None) -> FrameUpdateResponse:
        """Handle CREATE mode: verify none of the objects already exist."""
        from vitalgraph.kg.kgframe_create_endpoint_impl import handle_create_mode_impl
        return handle_create_mode_impl(self, space, graph_id, frame_uri, incoming_objects, incoming_uris, parent_uri)
    
    def _handle_update_mode(self, space, graph_id: str, frame_uri: str, incoming_objects: list,
                           incoming_uris: set, parent_uri: str = None) -> FrameUpdateResponse:
        """Handle UPDATE mode: verify frame exists and replace with new content."""
        from vitalgraph.kg.kgframe_update_endpoint_impl import handle_update_mode_impl
        return handle_update_mode_impl(self, space, graph_id, frame_uri, incoming_objects, incoming_uris, parent_uri)
    
    def _handle_upsert_mode(self, space, graph_id: str, frame_uri: str, incoming_objects: list,
                           incoming_uris: set, parent_uri: str = None) -> FrameUpdateResponse:
        """Handle UPSERT mode: create or update, verify structure and frame URI consistency."""
        from vitalgraph.kg.kgframe_upsert_endpoint_impl import handle_upsert_mode_impl
        return handle_upsert_mode_impl(self, space, graph_id, frame_uri, incoming_objects, incoming_uris, parent_uri)
    
    def _object_exists_in_store(self, space, uri: str, graph_id: str) -> bool:
        """Check if any object with the given URI exists in the store."""
        from vitalgraph.utils.sparql_helpers import check_object_exists_in_graph
        return check_object_exists_in_graph(space, uri, graph_id)
    
    def _get_current_frame_objects(self, space, frame_uri: str, graph_id: str) -> list:
        """Get all current objects belonging to a frame via grouping URIs."""
        from vitalgraph.kg.kgframe_get_endpoint_impl import get_current_frame_objects_impl
        return get_current_frame_objects_impl(self, space, frame_uri, graph_id)
    
    def _validate_parent_connection(self, space, parent_uri: str, frame_uri: str, graph_id: str, incoming_objects: list) -> bool:
        """Validate that there's a proper connection between parent and frame in the incoming objects."""
        from vitalgraph.utils.endpoint_validation import validate_parent_connection
        
        # Determine the correct edge type based on parent type
        # If parent is an entity, use Edge_hasEntityKGFrame
        # If parent is a frame, use Edge_hasKGFrame
        try:
            # Check if parent is an entity
            entity_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            ASK {{ <{parent_uri}> a haley:KGEntity . }}
            """ if not graph_id else f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            ASK {{ GRAPH <{graph_id}> {{ <{parent_uri}> a haley:KGEntity . }} }}
            """
            
            is_entity = space.store.query(entity_query)
            edge_type = "Edge_hasEntityKGFrame" if is_entity else "Edge_hasKGFrame"
            
        except Exception:
            # Default to Edge_hasKGFrame if we can't determine parent type
            edge_type = "Edge_hasKGFrame"
        
        return validate_parent_connection(space, parent_uri, frame_uri, graph_id, incoming_objects, 
                                        edge_type, self.logger)
    
    def _is_frame_parent(self, space, parent_uri: str, graph_id: str) -> bool:
        """Check if parent is a frame (vs entity)."""
        from vitalgraph.utils.endpoint_validation import is_frame_parent
        return is_frame_parent(space, parent_uri, graph_id, self.logger)
    
    def _delete_frame_graph_excluding_parent_edges(self, space, frame_uri: str, graph_id: str, parent_uri: str) -> bool:
        """Delete frame graph but preserve edges to parent frame."""
        try:
            # This is a simplified implementation
            # In practice, would need to identify and preserve specific parent edges
            return self._delete_frame_graph_from_store(space, frame_uri, graph_id)
        except Exception as e:
            self.logger.error(f"Error deleting frame graph excluding parent edges: {e}")
            return False

    def delete_kgframe(self, space_id: str, graph_id: str, uri: str) -> FrameDeleteResponse:
        """Delete a KGFrame by URI using pyoxigraph SPARQL DELETE."""
        from vitalgraph.kg.kgframe_delete_endpoint_impl import delete_kgframe_impl
        return delete_kgframe_impl(self, space_id, graph_id, uri)
    
    def delete_kgframes_batch(self, space_id: str, graph_id: str, uri_list: str) -> FrameDeleteResponse:
        """
        Delete multiple KGFrames by URI list using pyoxigraph batch operations.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of URIs to delete
            
        Returns:
            FrameDeleteResponse with total deletion count
        """
        from vitalgraph.kg.kgframe_delete_endpoint_impl import delete_kgframes_batch_impl
        return delete_kgframes_batch_impl(self, space_id, graph_id, uri_list)
    
    def get_kgframe_with_slots(self, space_id: str, graph_id: str, uri: str) -> JsonLdDocument:
        """
        Get a specific KGFrame with its associated slots using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Frame URI
            
        Returns:
            JsonLdDocument containing frame and its slots with VitalSigns native JSON-LD conversion
        """
        from vitalgraph.kg.kgframe_get_endpoint_impl import get_kgframe_with_slots_impl
        return get_kgframe_with_slots_impl(self, space_id, graph_id, uri)
    
    def create_kgframes_with_slots(self, space_id: str, graph_id: str, document: JsonLdDocument) -> FrameCreateResponse:
        """
        Create KGFrames with their associated slots from JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing KGFrame and KGSlot data
            
        Returns:
            FrameCreateResponse with created URIs and count
        """
        from vitalgraph.kg.kgframe_create_endpoint_impl import create_kgframes_with_slots_impl
        return create_kgframes_with_slots_impl(self, space_id, graph_id, document)
    
    # Frame-Slot Sub-Endpoint Operations
    
    def create_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, document: JsonLdDocument, operation_mode: str = "create") -> SlotCreateResponse:
        """Create slots for a specific frame using Edge_hasKGSlot relationships."""
        from vitalgraph.kg.kgframe_create_endpoint_impl import create_frame_slots_impl
        return create_frame_slots_impl(self, space_id, graph_id, frame_uri, document, operation_mode)
    
    def update_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, document: JsonLdDocument) -> SlotUpdateResponse:
        """
        Update slots for a specific frame using Edge_hasKGSlot relationships.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to update slots for
            document: JsonLdDocument containing updated KGSlots
            
        Returns:
            SlotUpdateResponse containing operation result
        """
        from vitalgraph.kg.kgframe_update_endpoint_impl import update_frame_slots_impl
        return update_frame_slots_impl(self, space_id, graph_id, frame_uri, document)
    
    def delete_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, slot_uris: List[str]) -> SlotDeleteResponse:
        """Delete specific slots from a frame using Edge_hasKGSlot relationships."""
        from vitalgraph.kg.kgframe_delete_endpoint_impl import delete_frame_slots_impl
        return delete_frame_slots_impl(self, space_id, graph_id, frame_uri, slot_uris)
    
    def get_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, kGSlotType: Optional[str] = None) -> JsonLdDocument:
        """Get slots for a specific frame using Edge_hasKGSlot relationships."""
        from vitalgraph.kg.kgframe_get_endpoint_impl import get_frame_slots_complex_impl
        return get_frame_slots_complex_impl(self, space_id, graph_id, frame_uri, kGSlotType)

    # Helper methods for frame graph retrieval
    
    def _get_single_frame(self, space, graph_id: str, frame_uri: str) -> JsonLdDocument:
        """Get just the frame itself (standard retrieval)."""
        from vitalgraph.kg.kgframe_get_endpoint_impl import get_single_frame_impl
        return get_single_frame_impl(self, space, graph_id, frame_uri)
    
    def _get_frame_with_complete_graph(self, space, graph_id: str, frame_uri: str) -> JsonLdDocument:
        """Get frame with complete graph using hasFrameGraphURI."""
        from vitalgraph.kg.kgframe_get_endpoint_impl import get_frame_with_complete_graph_impl
        return get_frame_with_complete_graph_impl(self, space, graph_id, frame_uri)

    # Helper methods for data lifecycle management and atomic operations
    
    def _frame_exists_in_store(self, space, frame_uri: str, graph_id: str) -> bool:
        """Check if a frame exists in the RDF store."""
        try:
            import pyoxigraph as px
            
            if graph_id:
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                ASK {{
                    GRAPH <{graph_id}> {{
                        <{frame_uri}> a haley:KGFrame .
                    }}
                }}
                """
            else:
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                ASK {{
                    <{frame_uri}> a haley:KGFrame .
                }}
                """
            
            result = space.store.query(query)
            return bool(result)
            
        except Exception as e:
            self.logger.error(f"Error checking frame existence for {frame_uri}: {e}")
            return False
    
    def _backup_frame_graph(self, space, frame_uri: str, graph_id: str) -> dict:
        """Backup complete frame graph (frame + slots + edges) for rollback capability."""
        from vitalgraph.kg.kgframe_update_endpoint_impl import backup_frame_graph_impl
        return backup_frame_graph_impl(self, space, frame_uri, graph_id)
    
    def _delete_frame_graph_from_store(self, space, frame_uri: str, graph_id: str) -> bool:
        """Delete complete frame graph (frame + slots + edges) to prevent stale triples."""
        from vitalgraph.kg.kgframe_delete_endpoint_impl import delete_frame_graph_from_store_impl
        return delete_frame_graph_from_store_impl(self, space, frame_uri, graph_id)
    
    def _restore_frame_graph_from_backup(self, space, frame_uri: str, graph_id: str, backup_data: dict) -> bool:
        """Restore frame graph from backup data for rollback operations."""
        from vitalgraph.kg.kgframe_update_endpoint_impl import restore_frame_graph_from_backup_impl
        return restore_frame_graph_from_backup_impl(self, space, frame_uri, graph_id, backup_data)
    
    def detect_stale_triples(self, space, graph_id: str) -> dict:
        """
        Detect stale triples and orphaned objects in the frame graph.
        
        Returns:
            dict: Report of stale triples categorized by type
        """
        from vitalgraph.utils.kgframe_diagnostics_impl import detect_stale_triples_impl
        return detect_stale_triples_impl(self, space, graph_id)
    
    def cleanup_stale_triples(self, space, graph_id: str, stale_report: dict = None) -> dict:
        """
        Clean up stale triples based on detection report.
        
        Args:
            space: Space object
            graph_id: Graph identifier
            stale_report: Optional pre-generated stale report
            
        Returns:
            dict: Cleanup results
        """
        from vitalgraph.utils.kgframe_diagnostics_impl import cleanup_stale_triples_impl
        return cleanup_stale_triples_impl(self, space, graph_id, stale_report)
    
    # Helper methods for VitalSigns integration patterns (from MockKGEntitiesEndpoint)
    
    def _strip_grouping_uris(self, document: JsonLdDocument) -> JsonLdDocument:
        """Strip any existing hasKGGraphURI and hasFrameGraphURI values from client document."""
        from vitalgraph.utils.vitalsigns_helpers import strip_grouping_uris_from_document
        return strip_grouping_uris_from_document(document)
    
    def _set_frame_grouping_uris(self, objects: List[Any], frame_uri: str) -> None:
        """Set frameGraphURI for all frame graph components (distinct from entity grouping)."""
        from vitalgraph.utils.graph_operations import set_frame_grouping_uris
        set_frame_grouping_uris(objects, frame_uri, self.logger)
    
    def _create_vitalsigns_objects_from_jsonld(self, jsonld_document: Dict[str, Any]) -> List[Any]:
        """
        Create VitalSigns objects from JSON-LD document using VitalSigns native methods.
        
        This method uses isinstance() type checking and Property object handling patterns.
        """
        from vitalgraph.utils.vitalsigns_conversion_utils import create_vitalsigns_objects_from_jsonld_impl
        return create_vitalsigns_objects_from_jsonld_impl(self, jsonld_document)
    
    def _object_to_triples(self, obj, graph_id: str) -> List[tuple]:
        """Convert a single VitalSigns object to RDF triples."""
        from vitalgraph.utils.vitalsigns_conversion_utils import object_to_triples_impl
        return object_to_triples_impl(self, obj, graph_id)
    
    def _store_triples(self, space, triples: List[tuple]) -> bool:
        """Store RDF triples/quads in the pyoxigraph store."""
        from vitalgraph.utils.vitalsigns_conversion_utils import store_triples_impl
        return store_triples_impl(self, space, triples)
    
    def _convert_triples_to_vitalsigns_objects(self, triples: List[Dict[str, str]]) -> List[Any]:
        """Convert triples to VitalSigns objects using list-specific RDF functions."""
        from vitalgraph.utils.vitalsigns_conversion_utils import convert_triples_to_vitalsigns_objects_impl
        return convert_triples_to_vitalsigns_objects_impl(self, triples)
    
    # ========================================
    # Sub-Endpoint Operations: /kgframes/kgslots
    # ========================================
    
    
    
    
    # ========================================
    # Helper Methods for Sub-Endpoint Operations
    # ========================================
    
    def _validate_frame_exists(self, space, graph_id: str, frame_uri: str) -> bool:
        """Check if frame exists in the graph."""
        query = f"""
        ASK {{
            GRAPH <{graph_id}> {{
                <{frame_uri}> a <http://vital.ai/ontology/haley-ai-kg#KGFrame> .
            }}
        }}
        """
        return bool(space.store.query(query))
    
    def _slot_exists(self, space, graph_id: str, slot_uri: str) -> bool:
        """Check if slot exists in the graph."""
        query = f"""
        ASK {{
            GRAPH <{graph_id}> {{
                <{slot_uri}> ?p ?o .
                <{slot_uri}> a ?type .
                FILTER(STRSTARTS(STR(?type), "http://vital.ai/ontology/haley-ai-kg#KG") && STRENDS(STR(?type), "Slot"))
            }}
        }}
        """
        return bool(space.store.query(query))
    
    def _validate_frame_slot_connection(self, space, graph_id: str, frame_uri: str, slot_uri: str) -> bool:
        """Check if slot is connected to frame via Edge_hasKGSlot."""
        query = f"""
        ASK {{
            GRAPH <{graph_id}> {{
                ?edge a <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> ;
                      <http://vital.ai/ontology/vital-core#hasEdgeSource> <{frame_uri}> ;
                      <http://vital.ai/ontology/vital-core#hasEdgeDestination> <{slot_uri}> .
            }}
        }}
        """
        return bool(space.store.query(query))
    
    def _validate_slot_structure(self, objects: List[Any]) -> Dict[str, Any]:
        """Validate slot structure and extract slot URIs."""
        try:
            from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
            from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
            from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
            
            slot_uris = []
            
            for obj in objects:
                if isinstance(obj, (KGTextSlot, KGIntegerSlot, KGBooleanSlot)):
                    if hasattr(obj, 'URI') and obj.URI:
                        slot_uris.append(str(obj.URI))
            
            if not slot_uris:
                return {'valid': False, 'error': 'No valid slots found', 'slot_uris': []}
            
            return {'valid': True, 'error': None, 'slot_uris': slot_uris}
            
        except Exception as e:
            return {'valid': False, 'error': str(e), 'slot_uris': []}
    
    def _set_slot_grouping_uris(self, objects: List[Any], frame_uri: str) -> None:
        """Set grouping URIs for slots based on frame context."""
        try:
            # Get entity URI from frame's grouping URI
            entity_uri = self._get_entity_uri_from_frame(frame_uri)
            
            for obj in objects:
                # Set entity-level grouping URI
                if entity_uri and hasattr(obj, 'kGGraphURI'):
                    obj.kGGraphURI = entity_uri
                
                # Set frame-level grouping URI
                if hasattr(obj, 'frameGraphURI'):
                    obj.frameGraphURI = frame_uri
                    
        except Exception as e:
            self.logger.error(f"Error setting slot grouping URIs: {e}")
    
    def _get_entity_uri_from_frame(self, frame_uri: str) -> str:
        """Get entity URI that owns this frame."""
        # This would query the graph to find the entity connected to this frame
        # For now, return a placeholder - this should be implemented based on actual graph structure
        return None
    
    def _create_frame_slot_edges(self, objects: List[Any], frame_uri: str, operation_mode: str) -> None:
        """Create Edge_hasKGSlot relationships between frame and slots."""
        from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
        from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
        from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
        from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
        
        # Find all slots in the objects
        slots = [obj for obj in objects if isinstance(obj, (KGTextSlot, KGIntegerSlot, KGBooleanSlot))]
        
        for slot in slots:
            # Check if edge already exists (for upsert mode)
            edge_exists = any(
                isinstance(obj, Edge_hasKGSlot) and 
                str(obj.edgeSource) == frame_uri and 
                str(obj.edgeDestination) == str(slot.URI)
                for obj in objects
            )
            
            if not edge_exists:
                # Create new edge
                edge = Edge_hasKGSlot()
                edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGSlot/{frame_uri.split('/')[-1]}_{slot.URI.split('/')[-1]}_edge"
                edge.edgeSource = frame_uri
                edge.edgeDestination = str(slot.URI)
                
                # Set grouping URIs
                if hasattr(slot, 'kGGraphURI'):
                    edge.kGGraphURI = slot.kGGraphURI
                # Note: Edge_hasKGSlot doesn't have frameGraphURI attribute
                
                objects.append(edge)
    
    def _delete_slot_triples(self, space, graph_id: str, slot_uri: str) -> bool:
        """Delete all triples for a slot."""
        try:
            delete_query = f"""
            DELETE WHERE {{
                GRAPH <{graph_id}> {{
                    <{slot_uri}> ?p ?o .
                }}
            }}
            """
            space.store.update(delete_query)
            return True
            
        except Exception as e:
            self.logger.error(f"Error deleting slot triples: {e}")
            return False
    
    def _delete_frame_slot_edge(self, space, graph_id: str, frame_uri: str, slot_uri: str) -> None:
        """Delete Edge_hasKGSlot between frame and slot."""
        try:
            delete_query = f"""
            DELETE WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> ;
                          <http://vital.ai/ontology/vital-core#hasEdgeSource> <{frame_uri}> ;
                          <http://vital.ai/ontology/vital-core#hasEdgeDestination> <{slot_uri}> .
                    ?edge ?p ?o .
                }}
            }}
            """
            space.store.update(delete_query)
            
        except Exception as e:
            self.logger.error(f"Error deleting frame-slot edge: {e}")
