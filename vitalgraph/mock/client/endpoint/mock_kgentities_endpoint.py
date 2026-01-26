"""
Mock implementation of KGEntitiesEndpoint for testing with VitalSigns native JSON-LD functionality.

This implementation uses:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store for data persistence
- Proper vitaltype handling for KGEntity objects
- Complete CRUD operations following real endpoint patterns
"""

from typing import Dict, Any, Optional, List
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.kgentities_model import (
    EntitiesResponse, EntityCreateResponse, EntityUpdateResponse, EntityDeleteResponse,
    EntityQueryRequest, EntityQueryResponse, EntityGraphResponse, EntityGraphDeleteResponse,
    EntitiesGraphResponse
)
from vitalgraph.model.kgframes_model import FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse
from vitalgraph.model.jsonld_model import JsonLdDocument
from vitalgraph.sparql.grouping_uri_queries import GroupingURIQueryBuilder, GroupingURIGraphRetriever
from vitalgraph.sparql.graph_validation import EntityGraphValidator
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge


class MockKGEntitiesEndpoint(MockBaseEndpoint):
    """Mock implementation of KGEntitiesEndpoint with VitalSigns native functionality."""
    
    def __init__(self, client=None, space_manager=None, *, config=None):
        """Initialize with SPARQL grouping URI functionality and graph validators."""
        super().__init__(client, space_manager, config=config)
        self.grouping_uri_builder = GroupingURIQueryBuilder()
        self.graph_retriever = GroupingURIGraphRetriever(self.grouping_uri_builder)
        self.entity_validator = EntityGraphValidator()
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
        
        # Initialize relations sub-endpoint
        from .mock_kgrelations_endpoint import MockKGRelationsEndpoint
        self.relations = MockKGRelationsEndpoint(client, space_manager, config=config)
    
    def list_kgentities(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None, include_entity_graph: bool = False) -> EntitiesResponse:
        """
        List KGEntities with pagination and optional search using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of entities per page
            offset: Offset for pagination
            search: Optional search term
            include_entity_graph: If True, include complete entity graphs with frames and slots
            
        Returns:
            EntitiesResponse with VitalSigns native JSON-LD document
        """
        from vitalgraph.kg.kgentity_list_endpoint_impl import list_kgentities_impl
        return list_kgentities_impl(self, space_id, graph_id, page_size, offset, search, include_entity_graph)
    
    def get_kgentity(self, space_id: str, graph_id: str, uri: str, include_entity_graph: bool = False) -> EntityGraphResponse:
        """
        Get a specific KGEntity by URI with optional complete graph using grouping URIs.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Entity URI
            include_entity_graph: If True, include complete entity graph using hasKGGraphURI
            
        Returns:
            EntityGraphResponse with entity and optional complete graph
        """
        from vitalgraph.kg.kgentity_get_endpoint_impl import get_kgentity_impl
        return get_kgentity_impl(self, space_id, graph_id, uri, include_entity_graph)
    
    def create_kgentities(self, space_id: str, graph_id: str, document: JsonLdDocument) -> EntityCreateResponse:
        """Create KGEntities from JSON-LD document with grouping URI enforcement."""
        from vitalgraph.kg.kgentity_create_endpoint_impl import create_kgentities_impl
        return create_kgentities_impl(self, space_id, graph_id, document)
    
    def update_kgentities(self, space_id: str, graph_id: str, document: JsonLdDocument, 
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
            space_id: Space identifier
            graph_id: Graph identifier  
            document: JsonLdDocument containing complete entity graph structure
            operation_mode: "create", "update", or "upsert"
            parent_uri: Optional parent object URI (entity or parent frame)
            
        Returns:
            EntityUpdateResponse with updated URI and operation details
        """
        from vitalgraph.kg.kgentity_update_endpoint_impl import update_kgentities_impl
        return update_kgentities_impl(self, space_id, graph_id, document, operation_mode, parent_uri)
    
    def delete_kgentity(self, space_id: str, graph_id: str, uri: str, delete_entity_graph: bool = False) -> EntityDeleteResponse:
        """Delete a KGEntity by URI using pyoxigraph SPARQL DELETE."""
        from vitalgraph.kg.kgentity_delete_endpoint_impl import delete_kgentity_impl
        return delete_kgentity_impl(self, space_id, graph_id, uri, delete_entity_graph)
    
    def delete_kgentities_batch(self, space_id: str, graph_id: str, uri_list: str) -> EntityDeleteResponse:
        """
        Delete multiple KGEntities by URI list using pyoxigraph batch operations.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of URIs to delete
            
        Returns:
            EntityDeleteResponse with total deletion count
        """
        from vitalgraph.kg.kgentity_delete_endpoint_impl import delete_kgentities_batch_impl
        return delete_kgentities_batch_impl(self, space_id, graph_id, uri_list)
    
    def get_kgentity_frames(self, space_id: str, graph_id: str, entity_uri: Optional[str] = None, 
                           page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> Dict[str, Any]:
        """
        Get frames associated with KGEntities using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Optional specific entity URI
            page_size: Number of frames per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            Dictionary with entity frames data
        """
        from vitalgraph.kg.kgentity_get_endpoint_impl import get_kgentity_frames_impl
        return get_kgentity_frames_impl(self, space_id, graph_id, entity_uri, page_size, offset, search)
    
    def query_entities(self, space_id: str, graph_id: str, query_request: EntityQueryRequest) -> EntityQueryResponse:
        """
        Query KGEntities using criteria-based search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            query_request: EntityQueryRequest containing search criteria and pagination
            
        Returns:
            EntityQueryResponse containing list of matching entity URIs and pagination info
        """
        from vitalgraph.kg.kgentity_query_endpoint_impl import query_entities_impl
        return query_entities_impl(self, space_id, graph_id, query_request)
    
    def list_kgentities_with_graphs(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0,
                                   search: Optional[str] = None, include_entity_graphs: bool = False) -> EntitiesGraphResponse:
        """
        List KGEntities with optional complete graphs.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            include_entity_graphs: If True, include complete entity graphs for all entities
            
        Returns:
            EntitiesGraphResponse containing entities and optional complete graphs
        """
        from vitalgraph.kg.kgentity_list_endpoint_impl import list_kgentities_with_graphs_impl
        return list_kgentities_with_graphs_impl(self, space_id, graph_id, page_size, offset, search, include_entity_graphs)
    
    # New Entity-Frame Relationship Methods (Phase 1A)
    
    def create_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, document: JsonLdDocument, operation_mode: str = "create") -> FrameCreateResponse:
        """Create frames within entity context using Edge_hasKGFrame relationships."""
        from vitalgraph.kg.kgentity_create_endpoint_impl import create_entity_frames_complex_impl
        return create_entity_frames_complex_impl(self, space_id, graph_id, entity_uri, document, operation_mode)
    
    def update_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, document: JsonLdDocument) -> FrameUpdateResponse:
        """
        Update frames within entity context using Edge_hasKGFrame relationships.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to update frames for
            document: JSON-LD document containing updated frames
            
        Returns:
            FrameUpdateResponse with update details
        """
        from vitalgraph.kg.kgentity_update_endpoint_impl import update_entity_frames_impl
        return update_entity_frames_impl(self, space_id, graph_id, entity_uri, document)
    
    def delete_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, frame_uris: List[str]) -> FrameDeleteResponse:
        """Delete frames within entity context using Edge_hasKGFrame relationships."""
        from vitalgraph.kg.kgentity_delete_endpoint_impl import delete_entity_frames_complex_impl
        return delete_entity_frames_complex_impl(self, space_id, graph_id, entity_uri, frame_uris)
    
    # Helper methods for entity graph lifecycle management
    
    def _validate_parent_object(self, space, parent_uri: str, graph_id: str) -> bool:
        """Validate that parent object exists (entity or frame)."""
        from vitalgraph.utils.endpoint_validation import validate_parent_object
        return validate_parent_object(space, parent_uri, graph_id, self.logger)
    
    def _validate_entity_graph_structure(self, objects: list) -> dict:
        """Validate that objects form a complete entity graph structure."""
        from vitalgraph.utils.validation_utils import validate_entity_graph_structure
        return validate_entity_graph_structure(objects)
    
    def _handle_entity_create_mode(self, space, graph_id: str, entity_uri: str, incoming_objects: list, 
                                  incoming_uris: set, parent_uri: str = None) -> EntityUpdateResponse:
        """Handle CREATE mode: verify none of the objects already exist."""
        from vitalgraph.kg.kgentity_create_endpoint_impl import handle_entity_create_mode_impl
        return handle_entity_create_mode_impl(self, space, graph_id, entity_uri, incoming_objects, incoming_uris, parent_uri)
    
    def _handle_entity_update_mode(self, space, graph_id: str, entity_uri: str, incoming_objects: list,
                                  incoming_uris: set, parent_uri: str = None) -> EntityUpdateResponse:
        """Handle UPDATE mode: verify entity exists and replace with new content."""
        from vitalgraph.kg.kgentity_update_endpoint_impl import handle_entity_update_mode_impl
        return handle_entity_update_mode_impl(self, space, graph_id, entity_uri, incoming_objects, incoming_uris, parent_uri)
    
    def _handle_entity_upsert_mode(self, space, graph_id: str, entity_uri: str, incoming_objects: list,
                                  incoming_uris: set, parent_uri: str = None) -> EntityUpdateResponse:
        """Handle UPSERT mode: create or update, verify structure and entity URI consistency."""
        from vitalgraph.kg.kgentity_upsert_endpoint_impl import handle_entity_upsert_mode_impl
        return handle_entity_upsert_mode_impl(self, space, graph_id, entity_uri, incoming_objects, incoming_uris, parent_uri)
    
    def _object_exists_in_store(self, space, uri: str, graph_id: str) -> bool:
        """Check if any object with the given URI exists in the store."""
        from vitalgraph.utils.sparql_helpers import check_object_exists_in_graph
        return check_object_exists_in_graph(space, uri, graph_id)
    
    def _entity_exists_in_store(self, space, entity_uri: str, graph_id: str) -> bool:
        """Check if entity exists in the store."""
        try:
            if graph_id:
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                ASK {{
                    GRAPH <{graph_id}> {{
                        <{entity_uri}> a haley:KGEntity .
                    }}
                }}
                """
            else:
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                ASK {{
                    <{entity_uri}> a haley:KGEntity .
                }}
                """
            return space.store.query(query)
        except Exception:
            return False
    
    def _get_current_entity_objects(self, space, entity_uri: str, graph_id: str) -> list:
        """Get all current objects belonging to an entity via grouping URIs."""
        from vitalgraph.kg.kgentity_get_endpoint_impl import get_current_entity_objects_impl
        return get_current_entity_objects_impl(self, space, entity_uri, graph_id)
    
    def _validate_parent_connection(self, space, parent_uri: str, entity_uri: str, graph_id: str, incoming_objects: list) -> bool:
        """Validate that there's a proper connection between parent and entity in the incoming objects."""
        from vitalgraph.utils.endpoint_validation import validate_parent_connection
        return validate_parent_connection(space, parent_uri, entity_uri, graph_id, incoming_objects, 
                                        "Edge_hasEntityKGFrame", self.logger)
    
    def _backup_entity_graph(self, space, entity_uri: str, graph_id: str) -> dict:
        """Backup entity graph for rollback capability."""
        try:
            # This is a simplified implementation
            # In practice, would need to backup all triples for the entity graph
            return {"entity_uri": entity_uri, "backup_created": True}
        except Exception as e:
            self.logger.error(f"Error backing up entity graph: {e}")
            return {}
    
    def _restore_entity_graph_from_backup(self, space, entity_uri: str, graph_id: str, backup_data: dict) -> bool:
        """Restore entity graph from backup."""
        try:
            # This is a simplified implementation
            # In practice, would restore all backed up triples
            self.logger.info(f"Entity graph backup restore for {entity_uri} - simplified implementation")
            return True
        except Exception as e:
            self.logger.error(f"Error restoring entity graph from backup: {e}")
            return False

    # Helper methods for SPARQL-based graph retrieval
    
    def _object_to_triples(self, obj, graph_id: str) -> List[tuple]:
        """Convert a single VitalSigns object to RDF triples."""
        try:
            # Use base class method to convert objects to triples
            triples = self._convert_objects_to_triples([obj])
            # Add graph context to each triple
            quads = []
            for triple in triples:
                if len(triple) == 3:
                    # Add graph_id as fourth element to make it a quad
                    quads.append((triple[0], triple[1], triple[2], graph_id))
                else:
                    quads.append(triple)
            return quads
        except Exception as e:
            self.logger.error(f"Error converting object to triples: {e}")
            return []
    
    def _store_triples(self, space, triples: List[tuple]) -> bool:
        """Store RDF triples/quads in the pyoxigraph store."""
        try:
            # Use base class method to insert quads
            return self._insert_quads_to_store(space, triples)
        except Exception as e:
            self.logger.error(f"Error storing triples: {e}")
            return False
    
    def _generate_uuid(self) -> str:
        """Generate a UUID for new objects."""
        from vitalgraph.utils.vitalsigns_helpers import generate_uuid
        return generate_uuid()
    
    def _execute_sparql_update(self, space, update_query: str) -> bool:
        """
        Execute SPARQL update query using pyoxigraph capabilities.
        
        Args:
            space: Mock space instance with pyoxigraph
            update_query: SPARQL update query string
            
        Returns:
            True if successful, False otherwise
        """
        try:
            space.update_sparql(update_query)
            return True
            
        except Exception as e:
            self.logger.error(f"Error executing SPARQL update: {e}")
            return False
    
    def _get_single_entity(self, space, graph_id: str, entity_uri: str) -> EntityGraphResponse:
        """Get just the entity itself (standard retrieval)."""
        from vitalgraph.kg.kgentity_get_endpoint_impl import get_single_entity_impl
        return get_single_entity_impl(self, space, graph_id, entity_uri)
    
    def _get_entity_with_complete_graph(self, space, graph_id: str, entity_uri: str) -> EntityGraphResponse:
        """Get entity with complete graph using hasKGGraphURI."""
        from vitalgraph.kg.kgentity_get_endpoint_impl import get_entity_with_complete_graph_impl
        return get_entity_with_complete_graph_impl(self, space, graph_id, entity_uri)
    
    def _convert_triples_to_jsonld(self, triples: List[Dict[str, str]]) -> Dict[str, Any]:
        """Convert list of triples to JSON-LD document."""
        from vitalgraph.utils.vitalsigns_helpers import convert_triples_to_jsonld
        return convert_triples_to_jsonld(triples, self.logger)
    
    def _convert_triples_to_vitalsigns_objects(self, triples: List[Dict[str, str]]) -> List[Any]:
        """Convert triples to VitalSigns objects using list-specific RDF functions."""
        from vitalgraph.utils.vitalsigns_helpers import convert_triples_to_vitalsigns_objects
        return convert_triples_to_vitalsigns_objects(triples, self.logger)
    
    def _simple_triples_to_jsonld(self, triples: List[Dict[str, str]]) -> Dict[str, Any]:
        """Fallback simple conversion of triples to JSON-LD."""
        from vitalgraph.utils.vitalsigns_helpers import simple_triples_to_jsonld
        return simple_triples_to_jsonld(triples)
    
    def _strip_grouping_uris(self, document: JsonLdDocument) -> JsonLdDocument:
        """Strip any existing hasKGGraphURI values from client document."""
        from vitalgraph.utils.vitalsigns_helpers import strip_grouping_uris_from_document
        return strip_grouping_uris_from_document(document)
    
    def _set_entity_grouping_uris(self, objects: List[Any], entity_uri: str) -> None:
        """Set hasKGGraphURI to entity_uri for all entity graph components."""
        from vitalgraph.utils.graph_operations import set_entity_grouping_uris
        set_entity_grouping_uris(objects, entity_uri, self.logger)
    
    def _set_dual_grouping_uris(self, objects: List[Any], entity_uri: str) -> None:
        """Set both entity-level and frame-level grouping URIs for proper graph retrieval."""
        from vitalgraph.utils.graph_operations import set_dual_grouping_uris
        set_dual_grouping_uris(objects, entity_uri, self.logger)
    
    def _process_complete_entity_document(self, document: JsonLdDocument, entity_uri: str) -> List[Any]:
        """Process complete entity document to extract and validate all KG objects using VitalSigns."""
        from vitalgraph.kg.kgentity_create_endpoint_impl import process_complete_entity_document_impl
        return process_complete_entity_document_impl(self, document, entity_uri)
    
    def _create_vitalsigns_objects_from_jsonld(self, jsonld_document: Dict[str, Any]) -> List[Any]:
        """Create VitalSigns objects from JSON-LD document using VitalSigns native methods."""
        from vitalgraph.utils.vitalsigns_helpers import create_vitalsigns_objects_from_jsonld
        return create_vitalsigns_objects_from_jsonld(jsonld_document, self.logger)
    
    def _jsonld_to_triples(self, jsonld_document: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Convert JSON-LD document to triples using pyoxigraph.
        
        Args:
            jsonld_document: JSON-LD document dict
            
        Returns:
            List of triple dicts with 'subject', 'predicate', 'object' keys
        """
        from vitalgraph.utils.vitalsigns_conversion_utils import jsonld_to_triples_impl
        return jsonld_to_triples_impl(self, jsonld_document)
    
    def _delete_entity_graph_from_store(self, space, entity_uri: str, graph_id: str) -> bool:
        """
        Delete complete entity graph using hasKGGraphURI grouping property.
        
        Args:
            space: Space object
            entity_uri: URI of the entity whose graph should be deleted
            graph_id: Graph ID
            
        Returns:
            True if deletion was successful
        """
        try:
            # Use grouping URI query to find all subjects with hasKGGraphURI = entity_uri
            query = self.grouping_uri_builder.build_entity_graph_subjects_query(entity_uri, graph_id)
            results = self._execute_sparql_query(space, query)
            
            # Delete all subjects that belong to this entity graph
            deleted_count = 0
            if results.get("bindings"):
                for binding in results["bindings"]:
                    subject_uri = binding.get("subject", {}).get("value", "")
                    if subject_uri:
                        if self._delete_quads_from_store(space, subject_uri, graph_id):
                            deleted_count += 1
            
            self.logger.debug(f"Deleted {deleted_count} subjects from entity graph {entity_uri}")
            return deleted_count > 0
            
        except Exception as e:
            self.logger.error(f"Failed to delete entity graph {entity_uri}: {e}")
            return False
    
    def _build_entity_query_from_criteria(self, criteria, graph_id: str, page_size: int, offset: int) -> str:
        """Build SPARQL query from EntityQueryCriteria."""
        
        # Start with basic entity query
        query_parts = [
            f"SELECT DISTINCT ?entity WHERE {{",
            f"  GRAPH <{graph_id}> {{",
            f"    ?entity a <{self.haley_prefix}KGEntity> ."
        ]
        
        # Add search string filter if provided
        if criteria.search_string:
            query_parts.extend([
                f"    ?entity ?searchProp ?searchValue .",
                f"    FILTER(CONTAINS(LCASE(STR(?searchValue)), LCASE(\"{criteria.search_string}\")))"
            ])
        
        # Add entity type filter if provided
        if criteria.entity_type:
            query_parts.append(f"    ?entity a <{criteria.entity_type}> .")
        
        # Add frame type filter if provided
        if criteria.frame_type:
            query_parts.extend([
                f"    ?edge_frame a <{self.haley_prefix}Edge_hasKGFrame> .",
                f"    ?edge_frame <http://vital.ai/ontology/vital-core#hasEdgeSource> ?entity .",
                f"    ?edge_frame <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?frame .",
                f"    ?frame a <{criteria.frame_type}> ."
            ])
        
        # Add slot criteria filters if provided
        if criteria.slot_criteria:
            for i, slot_criterion in enumerate(criteria.slot_criteria):
                slot_var = f"slot{i}"
                query_parts.extend([
                    f"    ?edge_frame{i} a <{self.haley_prefix}Edge_hasKGFrame> .",
                    f"    ?edge_frame{i} <http://vital.ai/ontology/vital-core#hasEdgeSource> ?entity .",
                    f"    ?edge_frame{i} <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?frame{i} .",
                    f"    ?edge_slot{i} a <{self.haley_prefix}Edge_hasKGSlot> .",
                    f"    ?edge_slot{i} <http://vital.ai/ontology/vital-core#hasEdgeSource> ?frame{i} .",
                    f"    ?edge_slot{i} <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?{slot_var} .",
                    f"    ?{slot_var} a <{slot_criterion.slot_type}> ."
                ])
                
                # Add value comparison if provided
                if slot_criterion.value and slot_criterion.comparator != "exists":
                    if slot_criterion.comparator == "contains":
                        query_parts.extend([
                            f"    ?{slot_var} ?slotProp{i} ?slotValue{i} .",
                            f"    FILTER(CONTAINS(LCASE(STR(?slotValue{i})), LCASE(\"{slot_criterion.value}\")))"
                        ])
                    else:
                        # For other comparators, we'd need more sophisticated handling
                        query_parts.extend([
                            f"    ?{slot_var} ?slotProp{i} \"{slot_criterion.value}\" ."
                        ])
        
        # Close the query
        query_parts.extend([
            "  }",
            "}",
            f"LIMIT {page_size}",
            f"OFFSET {offset}"
        ])
        
        return "\n".join(query_parts)
    
    # ========================================
    # Sub-Endpoint Operations: /kgentities/kgframes
    # ========================================
    
    
    def get_entity_frames(self, space_id: str, graph_id: str, entity_uri: str) -> JsonLdDocument:
        """Get frames for an entity using Edge_hasKGFrame relationships."""
        from vitalgraph.kg.kgentity_get_endpoint_impl import get_entity_frames_complex_impl
        return get_entity_frames_complex_impl(self, space_id, graph_id, entity_uri)
    
    
    # ========================================
    # Helper Methods for Sub-Endpoint Operations
    # ========================================
    
    def _validate_entity_exists(self, space, graph_id: str, entity_uri: str) -> bool:
        """Check if entity exists in the graph."""
        query = f"""
        ASK {{
            GRAPH <{graph_id}> {{
                <{entity_uri}> a <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
            }}
        }}
        """
        return bool(space.store.query(query))
    
    def _frame_exists(self, space, graph_id: str, frame_uri: str) -> bool:
        """Check if frame exists in the graph."""
        query = f"""
        ASK {{
            GRAPH <{graph_id}> {{
                <{frame_uri}> a <http://vital.ai/ontology/haley-ai-kg#KGFrame> .
            }}
        }}
        """
        return bool(space.store.query(query))
    
    def _validate_entity_frame_connection(self, space, graph_id: str, entity_uri: str, frame_uri: str) -> bool:
        """Check if frame is connected to entity via Edge_hasEntityKGFrame."""
        query = f"""
        ASK {{
            GRAPH <{graph_id}> {{
                ?edge a <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> ;
                      <http://vital.ai/ontology/vital-core#hasEdgeSource> <{entity_uri}> ;
                      <http://vital.ai/ontology/vital-core#hasEdgeDestination> <{frame_uri}> .
            }}
        }}
        """
        return bool(space.store.query(query))
    
    def _get_entity_frame_edge(self, space, graph_id: str, entity_uri: str, frame_uri: str) -> Any:
        """Get the specific Edge_hasEntityKGFrame object between entity and frame."""
        try:
            # Query for the specific edge
            edge_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?edge ?prop ?value WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a haley:Edge_hasEntityKGFrame ;
                          vital:hasEdgeSource <{entity_uri}> ;
                          vital:hasEdgeDestination <{frame_uri}> ;
                          ?prop ?value .
                }}
            }}
            """
            
            edge_results = list(space.store.query(edge_query))
            if not edge_results:
                return None
            
            # Convert to triples and then to VitalSigns object
            edge_triples = []
            for result in edge_results:
                edge_uri = str(result['edge']).strip('<>')
                prop_uri = str(result['prop'])
                
                value_obj = result['value']
                if hasattr(value_obj, 'value'):
                    value = str(value_obj.value)
                else:
                    value = str(value_obj)
                
                from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                edge_triples.append({
                    'subject': f'<{edge_uri}>',
                    'predicate': f'<{prop_uri}>',
                    'object': f'<{value}>' if validate_rfc3986(str(value), rule='URI') else f'"{value}"'
                })
            
            # Convert to VitalSigns object
            edge_objects = self._convert_triples_to_vitalsigns_objects(edge_triples)
            return edge_objects[0] if edge_objects else None
            
        except Exception as e:
            self.logger.error(f"Error getting entity-frame edge: {e}")
            return None
    
    def _create_entity_frame_edges(self, objects: List[Any], entity_uri: str, operation_mode: str) -> None:
        """Create Edge_hasEntityKGFrame relationships between entity and frames."""
        from ai_haley_kg_domain.model.KGFrame import KGFrame
        from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
        
        # Find all frames in the objects
        frames = [obj for obj in objects if isinstance(obj, KGFrame)]
        self.logger.info(f"Creating entity-frame edges for {len(frames)} frames")
        
        for frame in frames:
            # Check if edge already exists (for upsert mode)
            edge_exists = any(
                isinstance(obj, Edge_hasEntityKGFrame) and 
                str(obj.edgeSource) == entity_uri and 
                str(obj.edgeDestination) == str(frame.URI)
                for obj in objects
            )
            
            if not edge_exists:
                # Create new edge
                edge = Edge_hasEntityKGFrame()
                edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasEntityKGFrame/{entity_uri.split('/')[-1]}_{frame.URI.split('/')[-1]}_edge"
                edge.edgeSource = entity_uri
                edge.edgeDestination = str(frame.URI)
                
                # Set grouping URIs
                edge.kGGraphURI = entity_uri
                # Note: Edge_hasEntityKGFrame doesn't have frameGraphURI attribute
                
                self.logger.info(f"Created entity-frame edge: {edge.URI} ({entity_uri} -> {frame.URI})")
                objects.append(edge)
            else:
                self.logger.info(f"Entity-frame edge already exists for {entity_uri} -> {frame.URI}")
    
    def _delete_frame_with_components(self, space, graph_id: str, frame_uri: str) -> bool:
        """Delete frame and all its components (slots, edges)."""
        try:
            # Delete all triples where frame is subject
            delete_query = f"""
            DELETE WHERE {{
                GRAPH <{graph_id}> {{
                    <{frame_uri}> ?p ?o .
                }}
            }}
            """
            space.store.update(delete_query)
            
            # Delete all edges pointing to this frame
            delete_edges_query = f"""
            DELETE WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge ?p <{frame_uri}> .
                }}
            }}
            """
            space.store.update(delete_edges_query)
            
            # Delete slots connected to this frame
            delete_slots_query = f"""
            DELETE WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> ;
                          <http://vital.ai/ontology/vital-core#hasEdgeSource> <{frame_uri}> ;
                          <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?slot .
                    ?slot ?p ?o .
                    ?edge ?ep ?eo .
                }}
            }}
            """
            space.store.update(delete_slots_query)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error deleting frame components: {e}")
            return False
    
    def _delete_entity_frame_edge(self, space, graph_id: str, entity_uri: str, frame_uri: str) -> None:
        """Delete Edge_hasEntityKGFrame between entity and frame."""
        try:
            delete_query = f"""
            DELETE WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> ;
                          <http://vital.ai/ontology/vital-core#hasEdgeSource> <{entity_uri}> ;
                          <http://vital.ai/ontology/vital-core#hasEdgeDestination> <{frame_uri}> .
                    ?edge ?p ?o .
                }}
            }}
            """
            space.store.update(delete_query)
            
        except Exception as e:
            self.logger.error(f"Error deleting entity-frame edge: {e}")
    
    def _validate_frame_structure(self, objects: List[Any]) -> Dict[str, Any]:
        """Validate frame structure and extract frame URIs."""
        try:
            from ai_haley_kg_domain.model.KGFrame import KGFrame
            
            frame_uris = []
            
            for obj in objects:
                if isinstance(obj, KGFrame):
                    if hasattr(obj, 'URI') and obj.URI:
                        frame_uris.append(str(obj.URI))
            
            if not frame_uris:
                return {'valid': False, 'error': 'No valid frames found', 'frame_uris': []}
            
            return {'valid': True, 'error': None, 'frame_uris': frame_uris}
            
        except Exception as e:
            return {'valid': False, 'error': str(e), 'frame_uris': []}
    
    
    def _delete_frame_triples(self, space, graph_id: str, frame_uri: str) -> bool:
        """Delete all triples for a frame."""
        try:
            delete_query = f"""
            DELETE WHERE {{
                GRAPH <{graph_id}> {{
                    <{frame_uri}> ?p ?o .
                }}
            }}
            """
            space.store.update(delete_query)
            return True
            
        except Exception as e:
            self.logger.error(f"Error deleting frame triples: {e}")
            return False
