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
        self._log_method_call("list_kgentities", space_id=space_id, graph_id=graph_id, page_size=page_size, offset=offset, search=search)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                # Return empty response for non-existent space
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return EntitiesResponse(
                    entities=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Get KGEntity vitaltype URI
            kgentity_vitaltype = self._get_vitaltype_uri("KGEntity")
            
            # Build SPARQL query with optional search
            if search:
                query = f"""
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject a <{kgentity_vitaltype}> .
                        ?subject ?predicate ?object .
                        ?subject vital:hasName ?name .
                        FILTER(CONTAINS(LCASE(?name), LCASE("{search}")))
                    }}
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
            else:
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject a <{kgentity_vitaltype}> .
                        ?subject ?predicate ?object .
                    }}
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
            
            # Execute query
            results = self._execute_sparql_query(space, query)
            
            if not results.get("bindings"):
                # No results found
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return EntitiesResponse(
                    entities=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Group results by subject to reconstruct entities
            subjects_data = {}
            for binding in results["bindings"]:
                subject = binding.get("subject", {}).get("value", "")
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                if subject not in subjects_data:
                    subjects_data[subject] = {}
                
                subjects_data[subject][predicate] = obj_value
            
            # Convert to VitalSigns KGEntity objects
            entities = []
            for subject_uri, properties in subjects_data.items():
                entity = self._convert_sparql_to_vitalsigns_object(kgentity_vitaltype, subject_uri, properties)
                if entity:
                    entities.append(entity)
            
            # Get total count (separate query)
            count_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT (COUNT(DISTINCT ?subject) as ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject a <{kgentity_vitaltype}> .
                }}
            }}
            """
            
            count_results = self._execute_sparql_query(space, count_query)
            total_count = 0
            if count_results.get("bindings"):
                count_value = count_results["bindings"][0].get("count", {}).get("value", "0")
                # Handle typed literals like "3"^^<http://www.w3.org/2001/XMLSchema#integer>
                if isinstance(count_value, str) and "^^" in count_value:
                    count_value = count_value.split("^^")[0].strip('"')
                total_count = int(count_value)
            
            # Convert to JSON-LD document using VitalSigns
            entities_jsonld = self._objects_to_jsonld_document(entities)
            
            return EntitiesResponse(
                entities=JsonLdDocument(**entities_jsonld),
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Error listing KGEntities: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return EntitiesResponse(
                entities=JsonLdDocument(**empty_jsonld),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
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
        self._log_method_call("get_kgentity", space_id=space_id, graph_id=graph_id, uri=uri, include_entity_graph=include_entity_graph)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                # Return empty response for non-existent space
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return EntityGraphResponse(
                    entity=JsonLdDocument(**empty_jsonld),
                    complete_graph=None
                )
            
            # Clean URI
            clean_uri = uri.strip('<>')
            
            if not include_entity_graph:
                # Standard entity retrieval - just get the entity itself
                return self._get_single_entity(space, graph_id, clean_uri)
            else:
                # Complete graph retrieval using hasKGGraphURI
                return self._get_entity_with_complete_graph(space, graph_id, clean_uri)
                
        except Exception as e:
            self.logger.error(f"Error getting KGEntity {uri}: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return EntityGraphResponse(
                entity=JsonLdDocument(**empty_jsonld),
                complete_graph=None
            )
    
    def create_kgentities(self, space_id: str, graph_id: str, document: JsonLdDocument) -> EntityCreateResponse:
        """
        Create KGEntities from JSON-LD document with grouping URI enforcement.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing KGEntity data
            
        Returns:
            EntityCreateResponse with created URIs and count
        """
        self._log_method_call("create_kgentities", space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return EntityCreateResponse(
                    message="Space not found",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Step 1: Strip any existing grouping URIs from client document
            cleaned_document = self._strip_grouping_uris(document)
            
            # Step 2: Convert JSON-LD document to VitalSigns objects using direct object creation
            document_dict = cleaned_document.model_dump(by_alias=True)
            all_objects = self._create_vitalsigns_objects_from_jsonld(document_dict)
            
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
                entity_objects = self._process_complete_entity_document(cleaned_document, entity_uri)
                all_processed_objects.extend(entity_objects)
            
            # Step 5: Store all processed objects in pyoxigraph
            stored_count = self._store_vitalsigns_objects_in_pyoxigraph(space, all_processed_objects, graph_id)
            
            # Get created URIs (convert VitalSigns CombinedProperty to string)
            created_uris = [str(entity.URI) for entity in kgentities]
            
            return EntityCreateResponse(
                message=f"Successfully created {len(kgentities)} KGEntity(s)",
                created_count=len(kgentities),
                created_uris=created_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error creating KGEntities: {e}")
            return EntityCreateResponse(
                message=f"Error creating KGEntities: {e}",
                created_count=0, 
                created_uris=[]
            )
    
    def update_kgentities(self, space_id: str, graph_id: str, document: JsonLdDocument) -> EntityUpdateResponse:
        """
        Update KGEntities from JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing updated KGEntity data
            
        Returns:
            EntityUpdateResponse with updated URI
        """
        self._log_method_call("update_kgentities", space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return EntityUpdateResponse(
                    message="Space not found",
                    updated_uri=""
                )
            
            # Step 1: Strip any existing grouping URIs from client document
            cleaned_document = self._strip_grouping_uris(document)
            
            # Step 2: Convert JSON-LD document to VitalSigns objects using direct object creation
            document_dict = cleaned_document.model_dump(by_alias=True)
            all_objects = self._create_vitalsigns_objects_from_jsonld(document_dict)
            
            if not all_objects:
                return EntityUpdateResponse(
                    message="No valid objects found in document",
                    updated_uri=""
                )
            
            # Step 3: Find KGEntity objects to determine entity URIs
            kgentities = [obj for obj in all_objects if isinstance(obj, KGEntity)]
            
            if not kgentities:
                return EntityUpdateResponse(
                    message="No KGEntity objects found in document",
                    updated_uri=""
                )
            
            # Step 4: Process and update complete entity graphs
            updated_uri = None
            for entity in kgentities:
                entity_uri = str(entity.URI)
                updated_uri = entity_uri  # Track the last updated URI
                
                # Process complete entity document to get all related objects
                entity_objects = self._process_complete_entity_document(cleaned_document, entity_uri)
                
                # Delete existing triples for this entire entity graph
                if self._delete_entity_graph_from_store(space, entity_uri, graph_id):
                    # Insert updated triples for all entity graph objects
                    if self._store_vitalsigns_objects_in_pyoxigraph(space, entity_objects, graph_id) > 0:
                        updated_uri = entity_uri
                        break  # Return first successfully updated entity
            
            if updated_uri:
                return EntityUpdateResponse(
                    message=f"Successfully updated KGEntity: {updated_uri}",
                    updated_uri=updated_uri
                )
            else:
                return EntityUpdateResponse(
                    message="No KGEntities were updated",
                    updated_uri=""
                )
            
        except Exception as e:
            self.logger.error(f"Error updating KGEntities: {e}")
            return EntityUpdateResponse(
                message=f"Error updating KGEntities: {e}",
                updated_uri=""
            )
    
    def delete_kgentity(self, space_id: str, graph_id: str, uri: str, delete_entity_graph: bool = False) -> EntityDeleteResponse:
        """
        Delete a KGEntity by URI using pyoxigraph SPARQL DELETE.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Entity URI to delete
            delete_entity_graph: If True, delete complete entity graph including frames and slots
            
        Returns:
            EntityDeleteResponse with deletion count
        """
        self._log_method_call("delete_kgentity", space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return EntityDeleteResponse(
                    message="Space not found",
                    deleted_count=0
                )
            
            # Delete quads from pyoxigraph
            if self._delete_quads_from_store(space, uri, graph_id):
                return EntityDeleteResponse(
                    message=f"Successfully deleted KGEntity: {uri}",
                    deleted_count=1
                )
            else:
                return EntityDeleteResponse(
                    message=f"KGEntity not found: {uri}",
                    deleted_count=0
                )
                
        except Exception as e:
            self.logger.error(f"Error deleting KGEntity {uri}: {e}")
            return EntityDeleteResponse(
                message=f"Error deleting KGEntity {uri}: {e}",
                deleted_count=0
            )
    
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
        self._log_method_call("delete_kgentities_batch", space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
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
                if self._delete_quads_from_store(space, uri, graph_id):
                    deleted_count += 1
            
            return EntityDeleteResponse(
                message=f"Successfully deleted {deleted_count} of {len(uris)} KGEntity(s)",
                deleted_count=deleted_count
            )
            
        except Exception as e:
            self.logger.error(f"Error batch deleting KGEntities: {e}")
            return EntityDeleteResponse(
                message=f"Error batch deleting KGEntities: {e}",
                deleted_count=0
            )
    
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
        self._log_method_call("get_kgentity_frames", space_id=space_id, graph_id=graph_id, entity_uri=entity_uri, page_size=page_size, offset=offset, search=search)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return {"entity_frames": [], "total_count": 0}
            
            # Build SPARQL query to find frame relationships using Edge classes
            if entity_uri:
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                
                SELECT ?frame ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?edge a haley:Edge_hasKGFrame .
                        ?edge vital:hasEdgeSource <{entity_uri}> .
                        ?edge vital:hasEdgeDestination ?frame .
                        ?frame ?predicate ?object .
                    }}
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
            else:
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                
                SELECT ?entity ?frame ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?entity a haley:KGEntity .
                        ?edge a haley:Edge_hasKGFrame .
                        ?edge vital:hasEdgeSource ?entity .
                        ?edge vital:hasEdgeDestination ?frame .
                        ?frame ?predicate ?object .
                    }}
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
            
            results = self._execute_sparql_query(space, query)
            
            # Process results (simplified for now)
            entity_frames = []
            if results.get("bindings"):
                # Group and process frame data
                # This would need more sophisticated processing based on actual frame relationships
                entity_frames = [{"frame_uri": binding.get("frame", {}).get("value", "")} 
                               for binding in results["bindings"]]
            
            return {
                "entity_frames": entity_frames,
                "total_count": len(entity_frames)
            }
            
        except Exception as e:
            self.logger.error(f"Error getting KGEntity frames: {e}")
            return {"entity_frames": [], "total_count": 0}
    
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
        self._log_method_call("query_entities", space_id=space_id, graph_id=graph_id, query_request=query_request)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return EntityQueryResponse(
                    entity_uris=[],
                    total_count=0,
                    page_size=query_request.page_size,
                    offset=query_request.offset
                )
            
            # Build SPARQL query based on criteria
            query = self._build_entity_query_from_criteria(query_request.criteria, graph_id, 
                                                         query_request.page_size, query_request.offset)
            
            # Execute query
            results = self._execute_sparql_query(space, query)
            
            # Extract entity URIs from results
            entity_uris = []
            if results.get("bindings"):
                for binding in results["bindings"]:
                    entity_uri = binding.get("entity", {}).get("value", "")
                    if entity_uri and entity_uri not in entity_uris:
                        entity_uris.append(entity_uri)
            
            # For mock implementation, we'll use the actual count as total_count
            # In real implementation, this would be a separate COUNT query
            total_count = len(entity_uris)
            
            return EntityQueryResponse(
                entity_uris=entity_uris,
                total_count=total_count,
                page_size=query_request.page_size,
                offset=query_request.offset
            )
            
        except Exception as e:
            self.logger.error(f"Error querying entities: {e}")
            return EntityQueryResponse(
                entity_uris=[],
                total_count=0,
                page_size=query_request.page_size,
                offset=query_request.offset
            )
    
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
        self._log_method_call("list_kgentities_with_graphs", space_id=space_id, graph_id=graph_id, 
                             page_size=page_size, offset=offset, search=search, include_entity_graphs=include_entity_graphs)
        
        try:
            # Get basic entity list
            entities_response = self.list_kgentities(space_id, graph_id, page_size, offset, search)
            
            if not include_entity_graphs:
                # Return standard response without complete graphs
                return EntitiesGraphResponse(
                    entities=entities_response.entities,
                    total_count=entities_response.total_count,
                    page_size=entities_response.page_size,
                    offset=entities_response.offset,
                    complete_graphs=None
                )
            
            # Get complete graphs for all entities
            # This is a simplified implementation - in practice, this would be optimized
            complete_graphs = {}
            
            # Extract entity URIs from the entities response
            # This would need proper JSON-LD parsing in a real implementation
            # For now, we'll return the basic response
            
            return EntitiesGraphResponse(
                entities=entities_response.entities,
                total_count=entities_response.total_count,
                page_size=entities_response.page_size,
                offset=entities_response.offset,
                complete_graphs=complete_graphs if complete_graphs else None
            )
            
        except Exception as e:
            self.logger.error(f"Error listing entities with graphs: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return EntitiesGraphResponse(
                entities=JsonLdDocument(**empty_jsonld),
                total_count=0,
                page_size=page_size,
                offset=offset,
                complete_graphs=None
            )
    
    # New Entity-Frame Relationship Methods (Phase 1A)
    
    def create_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, document: JsonLdDocument) -> FrameCreateResponse:
        """
        Create frames within entity context using Edge_hasKGFrame relationships.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier  
            entity_uri: Entity URI to create frames for
            document: JSON-LD document containing frames
            
        Returns:
            FrameCreateResponse with creation details
        """
        self._log_method_call("create_entity_frames", space_id=space_id, graph_id=graph_id, entity_uri=entity_uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
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
                objects = self.vitalsigns.from_jsonld_list(jsonld_data)
                
                # Handle None return from VitalSigns
                if objects is None:
                    self.logger.warning("VitalSigns from_jsonld_list returned None, trying alternative approach")
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
                self.logger.error(f"Error converting JSON-LD to VitalSigns objects: {e}")
                return FrameCreateResponse(
                    message=f"Error processing document: {e}",
                    created_count=0,
                    created_uris=[]
                )
            
            # Filter for KGFrame objects and create Edge_hasKGFrame relationships
            frames = [obj for obj in objects if isinstance(obj, KGFrame)]
            created_uris = []
            
            self.logger.info(f"DEBUG: Processing {len(frames)} frames for entity {entity_uri}")
            for frame in frames:
                self.logger.info(f"DEBUG: Storing frame {frame.URI}")
                # Store the frame
                frame_triples = self._object_to_triples(frame, graph_id)
                self.logger.info(f"DEBUG: Frame generated {len(frame_triples)} triples")
                self._store_triples(space, frame_triples)
                
                # Create Edge_hasKGFrame relationship
                from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
                edge = Edge_hasKGFrame()
                edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGFrame/{self._generate_uuid()}"
                edge.edgeSource = str(entity_uri)
                edge.edgeDestination = str(frame.URI)
                
                self.logger.info(f"DEBUG: Creating edge {edge.URI} from {edge.edgeSource} to {edge.edgeDestination}")
                # Store the edge
                edge_triples = self._object_to_triples(edge, graph_id)
                self.logger.info(f"DEBUG: Edge generated {len(edge_triples)} triples")
                self._store_triples(space, edge_triples)
                
                created_uris.append(str(frame.URI))
            
            # Also store any slots and their edges that were included
            slots = [obj for obj in objects if isinstance(obj, KGSlot)]
            edges = [obj for obj in objects if hasattr(obj, 'edgeSource') and hasattr(obj, 'edgeDestination')]
            
            self.logger.info(f"DEBUG: Also storing {len(slots)} slots and {len(edges)} edges from the document")
            for slot in slots:
                self.logger.info(f"DEBUG: Storing slot {slot.URI}")
                slot_triples = self._object_to_triples(slot, graph_id)
                self.logger.info(f"DEBUG: Slot generated {len(slot_triples)} triples")
                self._store_triples(space, slot_triples)
            
            for edge in edges:
                self.logger.info(f"DEBUG: Storing edge {edge.URI}")
                edge_triples = self._object_to_triples(edge, graph_id)
                self.logger.info(f"DEBUG: Edge generated {len(edge_triples)} triples")
                self._store_triples(space, edge_triples)
            
            return FrameCreateResponse(
                message=f"Successfully created {len(created_uris)} frames for entity {entity_uri}",
                created_count=len(created_uris),
                created_uris=created_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error creating entity frames: {e}")
            return FrameCreateResponse(
                message=f"Error creating entity frames: {e}",
                created_count=0,
                created_uris=[]
            )
    
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
        self._log_method_call("update_entity_frames", space_id=space_id, graph_id=graph_id, entity_uri=entity_uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return FrameUpdateResponse(
                    message=f"Space {space_id} not found",
                    updated_uri=""
                )
            
            # Convert JSON-LD document to VitalSigns objects
            try:
                jsonld_data = document.model_dump(by_alias=True)
                self.logger.info(f"Update frames JSON-LD data structure: {jsonld_data}")
                
                # Check if the document has a @graph array
                if '@graph' in jsonld_data and jsonld_data['@graph']:
                    # Process each object in the @graph array
                    objects = []
                    for graph_obj in jsonld_data['@graph']:
                        # Check if this is a KGFrame object
                        obj_type = graph_obj.get('@type', '')
                        if 'KGFrame' in obj_type or obj_type.endswith('#KGFrame'):
                            # Create a KGFrame object for update
                            frame = KGFrame()
                            if '@id' in graph_obj:
                                frame.URI = graph_obj['@id']
                            # Handle different name field formats
                            if 'vital-core:hasName' in graph_obj:
                                frame.name = graph_obj['vital-core:hasName']
                            elif 'hasName' in graph_obj:
                                frame.name = graph_obj['hasName']
                            elif 'name' in graph_obj:
                                frame.name = graph_obj['name']
                            
                            self.logger.info(f"Parsed KGFrame for update: URI={frame.URI}, name={getattr(frame, 'name', 'None')}")
                            objects.append(frame)
                elif 'type' in jsonld_data and 'KGFrame' in jsonld_data.get('type', ''):
                    # Single object at root level (VitalSigns format)
                    objects = []
                    frame = KGFrame()
                    if 'id' in jsonld_data:
                        frame.URI = jsonld_data['id']
                    # Handle name field - it's nested in VitalSigns format
                    name_field = jsonld_data.get('http://vital.ai/ontology/vital-core#hasName', {})
                    if isinstance(name_field, dict) and '@value' in name_field:
                        frame.name = name_field['@value']
                    
                    self.logger.info(f"Parsed single KGFrame for update: URI={frame.URI}, name={getattr(frame, 'name', 'None')}")
                    objects.append(frame)
                else:
                    # Try VitalSigns conversion as fallback
                    try:
                        objects = self.vitalsigns.from_jsonld_list(jsonld_data)
                        if objects is None:
                            objects = []
                    except Exception as vs_error:
                        self.logger.warning(f"VitalSigns conversion failed: {vs_error}, using manual parsing")
                        # Try to manually parse the document structure
                        objects = []
                        if isinstance(jsonld_data, dict):
                            # Single object case
                            if '@type' in jsonld_data and 'KGFrame' in jsonld_data.get('@type', ''):
                                frame = KGFrame()
                                if '@id' in jsonld_data:
                                    frame.URI = jsonld_data['@id']
                                if 'vital-core:hasName' in jsonld_data:
                                    frame.name = jsonld_data['vital-core:hasName']
                                objects.append(frame)
                
                # Ensure objects is a list
                if not isinstance(objects, list):
                    objects = [objects] if objects is not None else []
                
                if not objects:
                    return FrameUpdateResponse(
                        message="No valid frames found in document",
                        updated_uri=""
                    )
                
            except Exception as e:
                self.logger.error(f"Error converting JSON-LD to VitalSigns objects: {e}")
                return FrameUpdateResponse(
                    message=f"Error processing document: {e}",
                    updated_uri=""
                )
            
            # Filter for KGFrame objects and update them
            frames = [obj for obj in objects if isinstance(obj, KGFrame)]
            updated_uris = []
            
            for frame in frames:
                frame_uri = str(frame.URI)
                
                # Delete existing frame triples
                delete_query = f"""
                DELETE WHERE {{
                    GRAPH <{graph_id}> {{
                        <{frame_uri}> ?p ?o .
                    }}
                }}
                """
                self._execute_sparql_update(space, delete_query)
                
                # Insert updated frame triples
                frame_triples = self._object_to_triples(frame, graph_id)
                self._store_triples(space, frame_triples)
                
                updated_uris.append(frame_uri)
            
            return FrameUpdateResponse(
                message=f"Successfully updated {len(updated_uris)} frames for entity {entity_uri}",
                updated_uri=updated_uris[0] if updated_uris else ""
            )
            
        except Exception as e:
            self.logger.error(f"Error updating entity frames: {e}")
            return FrameUpdateResponse(
                message=f"Error updating entity frames: {e}",
                updated_uri=""
            )
    
    def delete_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, frame_uris: List[str]) -> FrameDeleteResponse:
        """
        Delete frames within entity context using Edge_hasKGFrame relationships.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to delete frames from
            frame_uris: List of frame URIs to delete
            
        Returns:
            FrameDeleteResponse with deletion details
        """
        self._log_method_call("delete_entity_frames", space_id=space_id, graph_id=graph_id, entity_uri=entity_uri, frame_uris=frame_uris)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return FrameDeleteResponse(
                    message=f"Space {space_id} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            deleted_uris = []
            
            for frame_uri in frame_uris:
                # Delete frame triples
                delete_frame_query = f"""
                DELETE WHERE {{
                    GRAPH <{graph_id}> {{
                        <{frame_uri}> ?p ?o .
                    }}
                }}
                """
                self._execute_sparql_update(space, delete_frame_query)
                
                # Delete Edge_hasKGFrame relationship
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
                self._execute_sparql_update(space, delete_edge_query)
                
                deleted_uris.append(frame_uri)
            
            return FrameDeleteResponse(
                message=f"Successfully deleted {len(deleted_uris)} frames from entity {entity_uri}",
                deleted_count=len(deleted_uris),
                deleted_uris=deleted_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error deleting entity frames: {e}")
            return FrameDeleteResponse(
                message=f"Error deleting entity frames: {e}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    def get_entity_frames(self, space_id: str, graph_id: str, entity_uri: str) -> JsonLdDocument:
        """
        Get frames for an entity using Edge_hasKGFrame relationships.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to get frames for
            
        Returns:
            JsonLdDocument containing frames linked to the entity
        """
        self._log_method_call("get_entity_frames", space_id=space_id, graph_id=graph_id, entity_uri=entity_uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Query for frames linked to entity via Edge_hasKGFrame
            query = f"""
            SELECT ?frame ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame> .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeSource> <{entity_uri}> .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?frame .
                    ?frame ?predicate ?object .
                }}
            }}
            """
            
            # Debug: Log all triples in the store for this graph
            debug_query = f"""
            SELECT ?subject ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject ?predicate ?object .
                }}
            }}
            """
            debug_results = self._execute_sparql_query(space, debug_query)
            self.logger.info(f"DEBUG: Total triples in graph {graph_id}: {len(debug_results.get('bindings', []))}")
            
            # Log Edge_hasKGFrame triples specifically
            edge_query = f"""
            SELECT ?edge ?source ?dest WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame> .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeSource> ?source .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?dest .
                }}
            }}
            """
            edge_results = self._execute_sparql_query(space, edge_query)
            self.logger.info(f"DEBUG: Found {len(edge_results.get('bindings', []))} Edge_hasKGFrame relationships")
            for binding in edge_results.get("bindings", []):
                edge = binding.get("edge", {}).get("value", "")
                source = binding.get("source", {}).get("value", "")
                dest = binding.get("dest", {}).get("value", "")
                self.logger.info(f"DEBUG Edge: {edge} connects {source} -> {dest}")
            
            # Execute the actual query
            self.logger.info(f"DEBUG get_entity_frames: Looking for frames linked to entity {entity_uri}")
            self.logger.info(f"DEBUG get_entity_frames: Executing query: {query}")
            results = self._execute_sparql_query(space, query)
            self.logger.info(f"DEBUG get_entity_frames: Query returned {len(results.get('bindings', []))} results")
            
            # If no results, let's debug why
            if not results.get("bindings"):
                # Check if the frame exists at all
                frame_check_query = f"""
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject ?predicate ?object .
                        FILTER(CONTAINS(STR(?subject), "KGFrame"))
                    }}
                }}
                """
                frame_check_results = self._execute_sparql_query(space, frame_check_query)
                self.logger.info(f"DEBUG get_entity_frames: Found {len(frame_check_results.get('bindings', []))} frame-related triples in total")
            
            if not results.get("bindings"):
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Group results by subject (frame URI)
            subjects_data = {}
            for binding in results["bindings"]:
                subject = binding.get("frame", {}).get("value", "")
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                # Clean angle brackets from URIs if present
                if subject.startswith('<') and subject.endswith('>'):
                    subject = subject[1:-1]
                if predicate.startswith('<') and predicate.endswith('>'):
                    predicate = predicate[1:-1]
                if obj_value.startswith('<') and obj_value.endswith('>'):
                    obj_value = obj_value[1:-1]
                
                if subject not in subjects_data:
                    subjects_data[subject] = {}
                
                subjects_data[subject][predicate] = obj_value
            
            # Convert to VitalSigns frame objects
            objects = []
            self.logger.info(f"DEBUG get_entity_frames: Processing {len(subjects_data)} subjects")
            for subject_uri, properties in subjects_data.items():
                self.logger.info(f"DEBUG get_entity_frames: Processing subject {subject_uri} with {len(properties)} properties")
                # Get the actual vitaltype from the RDF data (brackets already cleaned)
                vitaltype_uri = properties.get('http://vital.ai/ontology/vital-core#vitaltype', '')
                self.logger.info(f"DEBUG get_entity_frames: Found vitaltype {vitaltype_uri}")
                
                # Use the actual vitaltype, fallback to KGFrame if not found
                if not vitaltype_uri:
                    vitaltype_uri = self._get_vitaltype_uri("KGFrame")
                    self.logger.info(f"DEBUG get_entity_frames: Using fallback vitaltype {vitaltype_uri}")
                
                obj = self._convert_sparql_to_vitalsigns_object(vitaltype_uri, subject_uri, properties)
                if obj:
                    self.logger.info(f"DEBUG get_entity_frames: Successfully converted object {obj.URI}")
                    objects.append(obj)
                else:
                    self.logger.info(f"DEBUG get_entity_frames: Failed to convert object for {subject_uri}")
            
            self.logger.info(f"DEBUG get_entity_frames: Final object count: {len(objects)}")
            
            # Convert to JSON-LD
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            raw_jsonld = GraphObject.to_jsonld_list(objects)
            
            # Create proper @graph structure for JsonLdDocument
            if '@context' in raw_jsonld and '@graph' not in raw_jsonld:
                # Single object format - wrap in @graph array
                jsonld_document = {
                    '@context': raw_jsonld['@context'],
                    '@graph': [raw_jsonld]
                }
            else:
                # Already in @graph format or empty
                jsonld_document = raw_jsonld
            
            self.logger.info(f"DEBUG get_entity_frames: Final JSON-LD has @graph: {'@graph' in jsonld_document}")
            
            return JsonLdDocument(**jsonld_document)
            
        except Exception as e:
            self.logger.error(f"Error getting entity frames: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
    
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
        import uuid
        return str(uuid.uuid4())
    
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
        # Query for entity data
        query = f"""
        SELECT ?predicate ?object WHERE {{
            GRAPH <{graph_id}> {{
                <{entity_uri}> ?predicate ?object .
            }}
        }}
        """
        
        results = self._execute_sparql_query(space, query)
        
        if not results.get("bindings"):
            # Entity not found
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return EntityGraphResponse(
                entity=JsonLdDocument(**empty_jsonld),
                complete_graph=None
            )
        
        # Convert SPARQL results to triples format
        triples = []
        for binding in results["bindings"]:
            predicate = binding.get("predicate", {}).get("value", "")
            obj_value = binding.get("object", {}).get("value", "")
            if predicate and obj_value:
                triples.append((entity_uri, predicate, obj_value))
        
        # Use VitalSigns to convert triples to proper GraphObjects
        vitalsigns_objects = self._triples_to_vitalsigns_objects(triples)
        
        if vitalsigns_objects:
            # Find the entity object (should be KGEntity, KGFrame, KGSlot, etc.)
            entity_object = None
            for obj in vitalsigns_objects:
                if str(obj.URI) == entity_uri:
                    entity_object = obj
                    break
            
            if entity_object:
                # Convert to JSON-LD using VitalSigns native functionality
                entity_jsonld = entity_object.to_jsonld()
                return EntityGraphResponse(
                    entity=JsonLdDocument(**entity_jsonld),
                    complete_graph=None
                )
        
        # Fallback to empty response
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        empty_jsonld = GraphObject.to_jsonld_list([])
        return EntityGraphResponse(
            entity=JsonLdDocument(**empty_jsonld),
            complete_graph=None
        )
    
    def _get_entity_with_complete_graph(self, space, graph_id: str, entity_uri: str) -> EntityGraphResponse:
        """Get entity with complete graph using hasKGGraphURI."""
        
        # Step 1: Get the entity itself
        entity_response = self._get_single_entity(space, graph_id, entity_uri)
        
        # Step 2: Get complete graph using SPARQL grouping URI retrieval
        def sparql_executor(query):
            """Execute SPARQL query and return results in expected format."""
            results = self._execute_sparql_query(space, query)
            if not results.get("bindings"):
                return []
            
            # Convert to expected format for GroupingURIGraphRetriever
            formatted_results = []
            for binding in results["bindings"]:
                formatted_results.append({
                    'subject': binding.get("subject", {}).get("value", ""),
                    'predicate': binding.get("predicate", {}).get("value", ""),
                    'object': binding.get("object", {}).get("value", "")
                })
            return formatted_results
        
        # Get complete entity graph triples
        graph_triples = self.graph_retriever.get_entity_graph_triples(
            entity_uri, graph_id, sparql_executor
        )
        
        if graph_triples:
            # Convert triples to JSON-LD document
            complete_graph_jsonld = self._convert_triples_to_jsonld(graph_triples)
            return EntityGraphResponse(
                entity=entity_response.entity,
                complete_graph=JsonLdDocument(**complete_graph_jsonld)
            )
        else:
            # No complete graph found
            return entity_response
    
    def _convert_triples_to_jsonld(self, triples: List[Dict[str, str]]) -> Dict[str, Any]:
        """Convert list of triples to JSON-LD document."""
        try:
            # First try to convert via VitalSigns objects for validation
            vitalsigns_objects = self._convert_triples_to_vitalsigns_objects(triples)
            
            if vitalsigns_objects:
                # Convert VitalSigns objects to JSON-LD using to_json and JSON parsing
                jsonld_objects = []
                for obj in vitalsigns_objects:
                    try:
                        # VitalSigns objects have to_json() method that returns JSON string
                        obj_json_str = obj.to_json()
                        if obj_json_str:
                            import json
                            obj_dict = json.loads(obj_json_str)
                            jsonld_objects.append(obj_dict)
                    except Exception as e:
                        self.logger.warning(f"Failed to convert VitalSigns object {obj.URI} to JSON-LD: {e}")
                        continue
                
                return {
                    "@context": {},
                    "@graph": jsonld_objects
                }
            else:
                # Fallback to simple JSON-LD conversion
                return self._simple_triples_to_jsonld(triples)
                
        except Exception as e:
            self.logger.error(f"Error converting triples to JSON-LD: {e}")
            # Fallback to simple conversion
            return self._simple_triples_to_jsonld(triples)
    
    def _convert_triples_to_vitalsigns_objects(self, triples: List[Dict[str, str]]) -> List[Any]:
        """Convert triples to VitalSigns objects using N-Triples format and from_rdf method."""
        try:
            # Convert triples to N-Triples format string
            rdf_lines = []
            for triple in triples:
                subject = triple['subject']
                predicate = triple['predicate']
                obj = triple['object']
                
                # Clean URIs by removing any existing angle brackets
                subject = subject.strip('<>')
                predicate = predicate.strip('<>')
                obj = obj.strip('<>')
                
                # Format as N-Triple based on object type
                from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                if validate_rfc3986(obj, rule='URI'):
                    # URI object - ensure proper angle bracket formatting
                    rdf_lines.append(f'<{subject}> <{predicate}> <{obj}> .')
                else:
                    # Literal object - escape quotes in literals
                    escaped_obj = obj.replace('"', '\\"')
                    rdf_lines.append(f'<{subject}> <{predicate}> "{escaped_obj}" .')
            
            rdf_data = '\n'.join(rdf_lines)
            
            # Use VitalSigns instance to convert RDF to proper GraphObjects
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vitalsigns = VitalSigns()
            
            self.logger.debug(f"Converting {len(triples)} triples to VitalSigns objects using from_rdf")
            self.logger.debug(f"RDF data:\n{rdf_data}")
            
            vitalsigns_objects = vitalsigns.from_rdf(rdf_data)
            
            # Ensure we return a list
            if not isinstance(vitalsigns_objects, list):
                vitalsigns_objects = [vitalsigns_objects] if vitalsigns_objects else []
            
            if vitalsigns_objects:
                self.logger.debug(f"Converted {len(triples)} triples to {len(vitalsigns_objects)} VitalSigns objects")
                return vitalsigns_objects
            else:
                self.logger.warning("VitalSigns conversion returned no objects")
                return []
                
        except Exception as e:
            self.logger.error(f"Error converting triples to VitalSigns objects: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
    def _simple_triples_to_jsonld(self, triples: List[Dict[str, str]]) -> Dict[str, Any]:
        """Fallback simple conversion of triples to JSON-LD."""
        # Group triples by subject
        subjects = {}
        for triple in triples:
            subject = triple['subject']
            predicate = triple['predicate']
            obj = triple['object']
            
            if subject not in subjects:
                subjects[subject] = {"@id": subject}
            
            # Handle different predicate types
            if predicate == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type":
                subjects[subject]["@type"] = obj
            else:
                # Simple property assignment (could be enhanced for complex objects)
                subjects[subject][predicate] = obj
        
        # Convert to JSON-LD format
        return {
            "@context": {},
            "@graph": list(subjects.values())
        }
    
    def _strip_grouping_uris(self, document: JsonLdDocument) -> JsonLdDocument:
        """Strip any existing hasKGGraphURI values from client document."""
        # This would implement the server-side stripping of client-provided grouping URIs
        # For now, return the document as-is since this is a mock implementation
        return document
    
    def _set_entity_grouping_uris(self, objects: List[Any], entity_uri: str) -> None:
        """Set hasKGGraphURI to entity_uri for all entity graph components."""
        
        for obj in objects:
            try:
                # Use short name property access - hasKGGraphURI short name is 'kGGraphURI'
                obj.kGGraphURI = entity_uri
                self.logger.debug(f"Set kGGraphURI={entity_uri} on object {obj.URI}")
            except Exception as e:
                self.logger.error(f"Failed to set kGGraphURI on object {obj.URI}: {e}")
    
    def _process_complete_entity_document(self, document: JsonLdDocument, entity_uri: str) -> List[Any]:
        """
        Process complete entity document to extract and validate all KG objects using VitalSigns.
        
        Args:
            document: JSON-LD document containing entity graph
            entity_uri: URI of the main entity
            
        Returns:
            List of all VitalSigns objects (KGEntity, KGFrame, KGSlot, edges)
        """
        try:
            # Convert entire document to VitalSigns objects using direct object creation
            document_dict = document.model_dump(by_alias=True)
            all_objects = self._create_vitalsigns_objects_from_jsonld(document_dict)
            
            if not all_objects:
                self.logger.warning("No valid VitalSigns objects found in document")
                return []
            
            # Categorize objects by type
            entities = []
            frames = []
            slots = []
            edges = []
            
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
                        self.logger.debug(f"Unknown object type: {obj_type} for object {obj.URI}")
                            
                except Exception as e:
                    self.logger.warning(f"Failed to categorize object {obj.URI}: {e}")
                    continue
            
            # Set grouping URIs on all objects
            all_entity_objects = entities + frames + slots + edges
            self._set_entity_grouping_uris(all_entity_objects, entity_uri)
            
            self.logger.info(f"Processed entity document: {len(entities)} entities, {len(frames)} frames, "
                           f"{len(slots)} slots, {len(edges)} edges")
            
            return all_entity_objects
            
        except Exception as e:
            self.logger.error(f"Failed to process complete entity document: {e}")
            return []
    
    def _create_vitalsigns_objects_from_jsonld(self, jsonld_document: Dict[str, Any]) -> List[Any]:
        """
        Create VitalSigns objects from JSON-LD document using VitalSigns native methods.
        
        Args:
            jsonld_document: JSON-LD document dict
            
        Returns:
            List of VitalSigns objects
        """
        try:
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vitalsigns = VitalSigns()
            
            # Use VitalSigns native from_jsonld_list method
            if "@graph" in jsonld_document and isinstance(jsonld_document["@graph"], list):
                # Document with @graph array
                objects = vitalsigns.from_jsonld_list(jsonld_document)
            else:
                # Single object document
                objects = [vitalsigns.from_jsonld(jsonld_document)]
            
            # Ensure we return a list
            if not isinstance(objects, list):
                objects = [objects] if objects else []
            
            # Filter out None objects
            objects = [obj for obj in objects if obj is not None]
            
            self.logger.debug(f"Created {len(objects)} VitalSigns objects from JSON-LD")
            return objects
            
        except Exception as e:
            self.logger.error(f"Failed to create VitalSigns objects from JSON-LD: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
    def _jsonld_to_triples(self, jsonld_document: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Convert JSON-LD document to triples using pyoxigraph.
        
        Args:
            jsonld_document: JSON-LD document dict
            
        Returns:
            List of triple dicts with 'subject', 'predicate', 'object' keys
        """
        try:
            import json
            from pyoxigraph import Store
            
            # Create temporary store
            temp_store = Store()
            
            # Convert dict to JSON string for pyoxigraph
            jsonld_str = json.dumps(jsonld_document)
            
            # Parse JSON-LD into the store
            temp_store.load(jsonld_str.encode('utf-8'), "application/ld+json")
            
            # Extract all triples
            triples = []
            subjects_seen = set()
            
            for quad in temp_store:
                # Clean up URI formatting - remove angle brackets and quotes
                subject = str(quad.subject).strip('<>')
                predicate = str(quad.predicate).strip('<>')
                obj = str(quad.object)
                
                # Remove quotes from literal values but keep URIs clean
                if obj.startswith('"') and obj.endswith('"'):
                    obj = obj[1:-1]  # Remove quotes from literals
                elif obj.startswith('<') and obj.endswith('>'):
                    obj = obj[1:-1]  # Remove angle brackets from URIs
                
                triple = {
                    'subject': subject,
                    'predicate': predicate, 
                    'object': obj
                }
                triples.append(triple)
                subjects_seen.add(subject)
            
            # Add required URI triples for VitalSigns
            for subject in subjects_seen:
                uri_triple = {
                    'subject': subject,
                    'predicate': 'http://vital.ai/ontology/vital-core#URI',
                    'object': subject
                }
                triples.append(uri_triple)
            
            self.logger.debug(f"Converted JSON-LD to {len(triples)} triples")
            
            # Debug: Log first few triples
            for i, triple in enumerate(triples[:5]):
                self.logger.debug(f"Triple {i}: {triple}")
            
            return triples
            
        except Exception as e:
            self.logger.error(f"Failed to convert JSON-LD to triples: {e}")
            return []
    
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
