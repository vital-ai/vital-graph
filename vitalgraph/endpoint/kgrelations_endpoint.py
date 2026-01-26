"""
KG Relations REST API endpoint for VitalGraph.

This module provides REST API endpoints for managing KG relations using JSON-LD 1.1 format.
KG relations represent direct entity-to-entity relationships in the knowledge graph.
"""

import logging
from typing import Dict, List, Optional, Union, Any
from fastapi import APIRouter, Query, Depends, HTTPException, Body
from pydantic import BaseModel, Field
from enum import Enum

from ..model.jsonld_model import JsonLdDocument, JsonLdObject, JsonLdRequest
from ..model.kgrelations_model import (
    RelationsResponse,
    RelationResponse,
    RelationCreateResponse,
    RelationUpdateResponse,
    RelationUpsertResponse,
    RelationDeleteRequest,
    RelationDeleteResponse,
    RelationQueryRequest,
    RelationQueryResponse
)

# Import implementation modules
from ..kg_impl.kgrelations_create_impl import KGRelationsCreateProcessor, OperationMode as CreateOperationMode
from ..kg_impl.kgrelations_read_impl import KGRelationsReadProcessor
from ..kg_impl.kgrelations_delete_impl import KGRelationsDeleteProcessor
from ..kg_impl.kg_backend_utils import FusekiPostgreSQLBackendAdapter


class OperationMode(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    UPSERT = "upsert"


class KGRelationsEndpoint:
    """REST API endpoint for KG Relations operations."""
    
    def __init__(self, space_manager, auth_dependency):
        """Initialize KG Relations endpoint with space manager and authentication."""
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(__name__)
        self.router = APIRouter()
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
        self.vital_prefix = "http://vital.ai/ontology/vital-core#"
        
        # Set up routes
        self._setup_routes()
    
    def _setup_routes(self):
        """Set up FastAPI routes for KG Relations operations."""
        
        @self.router.get("/kgrelations", response_model=Union[RelationsResponse, RelationResponse], tags=["KG Relations"])
        async def list_or_get_relations(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            relation_uri: Optional[str] = Query(None, description="Single relation URI to retrieve"),
            entity_source_uri: Optional[str] = Query(None, description="Filter by source entity URI"),
            entity_destination_uri: Optional[str] = Query(None, description="Filter by destination entity URI"),
            relation_type_uri: Optional[str] = Query(None, description="Filter by relation type URI"),
            direction: str = Query("all", description="Direction filter: all, incoming, outgoing"),
            page_size: int = Query(10, ge=1, le=1000, description="Number of relations per page"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            List KG Relations with filtering and pagination, or get specific relation by URI.
            
            - If relation_uri is provided: returns single relation
            - Otherwise: returns paginated list of relations with optional filtering
            
            Args:
                space_id: Space identifier
                graph_id: Graph identifier
                relation_uri: Optional single relation URI to retrieve
                entity_source_uri: Filter by source entity URI
                entity_destination_uri: Filter by destination entity URI
                relation_type_uri: Filter by relation type URI
                direction: Direction filter (all, incoming, outgoing)
                page_size: Number of relations per page
                offset: Offset for pagination
                
            Returns:
                RelationResponse (if relation_uri provided) or RelationsResponse (for list)
            """
            if relation_uri:
                return await self._get_relation(space_id, graph_id, relation_uri, current_user)
            else:
                return await self._list_relations(
                    space_id, graph_id, entity_source_uri, entity_destination_uri,
                    relation_type_uri, direction, page_size, offset, current_user
                )
        
        @self.router.post("/kgrelations", response_model=Union[RelationCreateResponse, RelationUpdateResponse, RelationUpsertResponse], tags=["KG Relations"])
        async def create_or_update_relations(
            request: JsonLdRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            operation_mode: OperationMode = Query(OperationMode.CREATE, description="Operation mode: create, update, or upsert"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Create, update, or upsert KG Relations from JSON-LD document or object.
            Uses discriminated union to automatically handle single objects (JsonLdObject) or multiple objects (JsonLdDocument).
            
            - CREATE: Create new relations (fails if relation URIs already exist)
            - UPDATE: Update existing relations (fails if relation URIs don't exist)
            - UPSERT: Create or update relations (always succeeds)
            """
            return await self._create_or_update_relations(space_id, graph_id, request, operation_mode, current_user)
        
        @self.router.delete("/kgrelations", response_model=RelationDeleteResponse, tags=["KG Relations"])
        async def delete_relations(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            request: RelationDeleteRequest = Body(...),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Delete KG Relations by URIs.
            
            Args:
                request: RelationDeleteRequest containing relation URIs to delete
                space_id: Space identifier
                graph_id: Graph identifier
                
            Returns:
                RelationDeleteResponse with deletion results
            """
            return await self._delete_relations(space_id, graph_id, request, current_user)
        
        @self.router.post("/kgrelations/query", response_model=RelationQueryResponse, tags=["KG Relations"])
        async def query_relations(
            query_request: RelationQueryRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Query KG Relations using complex criteria.
            
            Args:
                query_request: RelationQueryRequest containing search criteria
                space_id: Space identifier
                graph_id: Graph identifier
                
            Returns:
                RelationQueryResponse containing matching relation URIs
            """
            return await self._query_relations(space_id, graph_id, query_request, current_user)
    
    async def _list_relations(self, space_id: str, graph_id: str, entity_source_uri: Optional[str],
                            entity_destination_uri: Optional[str], relation_type_uri: Optional[str],
                            direction: str, page_size: int, offset: int, current_user: Dict) -> RelationsResponse:
        """List KG Relations with filtering and pagination."""
        try:
            self.logger.info(f"Listing KG Relations in space {space_id}, graph {graph_id}")
            
            # Get backend implementation
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                raise HTTPException(status_code=500, detail=f"Space {space_id} not available")
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                raise HTTPException(status_code=500, detail="Backend implementation not available")
            
            # Create backend adapter
            backend = FusekiPostgreSQLBackendAdapter(backend_impl)
            
            # Create read processor
            read_processor = KGRelationsReadProcessor(backend)
            
            # List relations using processor
            triples, total_count = await read_processor.list_relations(
                space_id, graph_id, entity_source_uri, entity_destination_uri,
                relation_type_uri, direction, page_size, offset
            )
            
            # Convert triples to JSON-LD document
            if triples:
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                graph_objects = GraphObject.from_triples_list(triples)
                relations_doc = self._relations_to_jsonld_document(graph_objects)
            else:
                relations_doc = JsonLdDocument(**{
                    "@context": {"@vocab": "http://vital.ai/ontology/"},
                    "@graph": []
                })
            
            return RelationsResponse(
                relations=relations_doc,
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error listing KG Relations: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to list KG Relations: {str(e)}"
            )
    
    async def _get_relation(self, space_id: str, graph_id: str, relation_uri: str, current_user: Dict) -> RelationResponse:
        """Get a specific KG Relation by URI."""
        try:
            self.logger.info(f"Getting KG Relation {relation_uri} in space {space_id}, graph {graph_id}")
            
            # Get backend implementation
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                raise HTTPException(status_code=500, detail=f"Space {space_id} not available")
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                raise HTTPException(status_code=500, detail="Backend implementation not available")
            
            # Create backend adapter
            backend = FusekiPostgreSQLBackendAdapter(backend_impl)
            
            # Create read processor
            read_processor = KGRelationsReadProcessor(backend)
            
            # Get relation using processor
            triples = await read_processor.get_relation_by_uri(space_id, graph_id, relation_uri)
            
            # Convert triples to JSON-LD document
            if triples:
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                graph_objects = GraphObject.from_triples_list(triples)
                relation_doc = self._relations_to_jsonld_document(graph_objects)
            else:
                # Return empty JSON-LD document for not found
                relation_doc = JsonLdDocument(**{
                    "@context": {"@vocab": "http://vital.ai/ontology/"},
                    "@graph": []
                })
            
            return RelationResponse(relation=relation_doc)
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting KG Relation: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get KG Relation: {str(e)}"
            )
    
    async def _create_or_update_relations(self, space_id: str, graph_id: str, request: JsonLdRequest,
                                        operation_mode: OperationMode, current_user: Dict) -> Union[RelationCreateResponse, RelationUpdateResponse, RelationUpsertResponse]:
        """Create, update, or upsert KG Relations."""
        try:
            self.logger.info(f"Processing KG Relations in space {space_id}, graph {graph_id}, mode '{operation_mode.value}'")
            
            # Get backend implementation
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                raise HTTPException(status_code=500, detail=f"Space {space_id} not available")
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                raise HTTPException(status_code=500, detail="Backend implementation not available")
            
            # Create backend adapter
            backend = FusekiPostgreSQLBackendAdapter(backend_impl)
            
            # Convert JSON-LD to VitalSigns relation objects
            relations = self._jsonld_document_to_relations(request)
            
            # Create processor
            create_processor = KGRelationsCreateProcessor(backend)
            
            # Map operation mode
            if operation_mode == OperationMode.CREATE:
                mode = CreateOperationMode.CREATE
            elif operation_mode == OperationMode.UPDATE:
                mode = CreateOperationMode.UPDATE
            else:
                mode = CreateOperationMode.UPSERT
            
            # Process relations using processor
            return await create_processor.create_or_update_relations(
                space_id, graph_id, relations, mode
            )
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error processing KG Relations: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process KG Relations: {str(e)}"
            )
    
    async def _delete_relations(self, space_id: str, graph_id: str, request: RelationDeleteRequest, current_user: Dict) -> RelationDeleteResponse:
        """Delete KG Relations by URIs."""
        try:
            self.logger.info(f"Deleting KG Relations in space {space_id}, graph {graph_id}: {request.relation_uris}")
            
            # Get backend implementation
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                raise HTTPException(status_code=500, detail=f"Space {space_id} not available")
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                raise HTTPException(status_code=500, detail="Backend implementation not available")
            
            # Create backend adapter
            backend = FusekiPostgreSQLBackendAdapter(backend_impl)
            
            # Create delete processor
            delete_processor = KGRelationsDeleteProcessor(backend)
            
            # Delete relations using processor
            return await delete_processor.delete_relations(space_id, graph_id, request.relation_uris)
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting KG Relations: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete KG Relations: {str(e)}"
            )
    
    async def _query_relations(self, space_id: str, graph_id: str, query_request: RelationQueryRequest, current_user: Dict) -> RelationQueryResponse:
        """Query KG Relations using complex criteria."""
        try:
            self.logger.info(f"Querying KG Relations in space {space_id}, graph {graph_id} with criteria: {query_request.criteria}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                raise HTTPException(status_code=500, detail=f"Space {space_id} not available - server configuration error")
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=500, detail="Backend implementation not available")
            
            # Build SPARQL query from criteria
            sparql_query = self._build_query_relations_sparql(
                graph_id, query_request.criteria, query_request.page_size, query_request.offset
            )
            
            # Execute query via backend interface
            results = await backend.execute_sparql_query(space_id, sparql_query)
            
            # Extract relation URIs from results
            relation_uris = []
            if results and results.get("bindings"):
                for binding in results["bindings"]:
                    relation_uri = binding.get("relation", {}).get("value", "")
                    if relation_uri and relation_uri not in relation_uris:
                        relation_uris.append(relation_uri)
            
            # For now, use the actual count as total_count
            total_count = len(relation_uris)
            
            return RelationQueryResponse(
                relation_uris=relation_uris,
                total_count=total_count,
                page_size=query_request.page_size,
                offset=query_request.offset
            )
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error querying KG Relations: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to query KG Relations: {str(e)}"
            )
    
    # Helper methods (placeholder implementations - to be completed based on mock patterns)
    
    def _build_list_relations_query(self, graph_id: str, entity_source_uri: Optional[str],
                                  entity_destination_uri: Optional[str], relation_type_uri: Optional[str],
                                  direction: str, page_size: int, offset: int) -> str:
        """Build SPARQL query for listing relations."""
        # TODO: Implement based on mock implementation patterns
        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        
        SELECT ?relation ?source ?destination ?type WHERE {{
            GRAPH <{graph_id}> {{
                ?relation a haley:Edge_hasKGRelation ;
                         vital:hasEdgeSource ?source ;
                         vital:hasEdgeDestination ?destination .
                OPTIONAL {{ ?relation a ?type }}
            }}
        }}
        LIMIT {page_size}
        OFFSET {offset}
        """
    
    def _build_count_relations_query(self, graph_id: str, entity_source_uri: Optional[str],
                                   entity_destination_uri: Optional[str], relation_type_uri: Optional[str],
                                   direction: str) -> str:
        """Build SPARQL count query for relations."""
        # TODO: Implement based on mock implementation patterns
        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        
        SELECT (COUNT(?relation) as ?count) WHERE {{
            GRAPH <{graph_id}> {{
                ?relation a haley:Edge_hasKGRelation ;
                         vital:hasEdgeSource ?source ;
                         vital:hasEdgeDestination ?destination .
            }}
        }}
        """
    
    def _build_get_relation_query(self, graph_id: str, relation_uri: str) -> str:
        """Build SPARQL query for getting specific relation."""
        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        
        SELECT ?relation ?source ?destination ?type WHERE {{
            GRAPH <{graph_id}> {{
                <{relation_uri}> a haley:Edge_hasKGRelation ;
                                vital:hasEdgeSource ?source ;
                                vital:hasEdgeDestination ?destination .
                OPTIONAL {{ <{relation_uri}> a ?type }}
                BIND(<{relation_uri}> as ?relation)
            }}
        }}
        """
    
    def _build_delete_relation_query(self, graph_id: str, relation_uri: str) -> str:
        """Build SPARQL DELETE query for specific relation."""
        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        
        DELETE {{
            GRAPH <{graph_id}> {{
                <{relation_uri}> ?p ?o .
            }}
        }}
        WHERE {{
            GRAPH <{graph_id}> {{
                <{relation_uri}> ?p ?o .
            }}
        }}
        """
    
    def _build_query_relations_sparql(self, graph_id: str, criteria, page_size: int, offset: int) -> str:
        """Build SPARQL query from relation query criteria."""
        # TODO: Implement based on criteria parameters
        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        
        SELECT ?relation WHERE {{
            GRAPH <{graph_id}> {{
                ?relation a haley:Edge_hasKGRelation ;
                         vital:hasEdgeSource ?source ;
                         vital:hasEdgeDestination ?destination .
            }}
        }}
        LIMIT {page_size}
        OFFSET {offset}
        """
    
    def _sparql_results_to_relations(self, sparql_result: Dict[str, Any]) -> List:
        """Convert SPARQL results to VitalSigns relation objects."""
        # TODO: Implement conversion to VitalSigns Edge_hasKGRelation objects
        return []
    
    def _relations_to_jsonld_document(self, relations: List):
        """Convert relation objects to JSON-LD document or object."""
        try:
            if not relations:
                return JsonLdDocument(**{
                    "@context": {"@vocab": "http://vital.ai/ontology/"},
                    "@graph": []
                })
            
            # Convert VitalSigns objects to JSON-LD
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            from vitalgraph.model.jsonld_model import JsonLdObject
            
            # Handle both list of GraphObjects and single GraphObject
            if isinstance(relations, list):
                jsonld = GraphObject.to_jsonld_list(relations)
            else:
                jsonld = GraphObject.to_jsonld_list([relations])
            
            # Ensure @type fields are present
            if '@graph' in jsonld:
                for obj in jsonld['@graph']:
                    if '@type' not in obj and 'type' in obj:
                        obj['@type'] = obj.pop('type')
            
            # Return JsonLdObject for single relation, JsonLdDocument for multiple
            if '@graph' in jsonld and len(jsonld['@graph']) == 1:
                # Single object - return JsonLdObject
                single_obj = jsonld['@graph'][0]
                if '@context' in jsonld:
                    single_obj['@context'] = jsonld['@context']
                return JsonLdObject(**single_obj)
            else:
                # Multiple objects - return JsonLdDocument
                return JsonLdDocument(**jsonld)
            
        except Exception as e:
            self.logger.error(f"Error converting relations to JSON-LD: {e}")
            return JsonLdDocument(**{
                "@context": {"@vocab": "http://vital.ai/ontology/"},
                "@graph": []
            })
    
    def _jsonld_document_to_relations(self, document: JsonLdRequest) -> List:
        """Convert JSON-LD document or object to VitalSigns relation objects."""
        try:
            # Convert Pydantic model to dict
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vs = VitalSigns()
            
            jsonld_data = document.model_dump(by_alias=True)
            
            # If it's a JsonLdObject (single object), wrap it in a document structure
            if isinstance(document, JsonLdObject):
                # Single object - wrap in @graph array for VitalSigns
                context = jsonld_data.pop('@context', {})
                jsonld_document = {
                    '@context': context,
                    '@graph': [jsonld_data]
                }
            else:
                # Already a document with @graph
                jsonld_document = jsonld_data
            
            # Convert to VitalSigns objects using from_jsonld_list
            graph_objects = vs.from_jsonld_list(jsonld_document)
            
            if not graph_objects:
                self.logger.warning("No objects converted from JSON-LD")
                return []
            
            # Ensure we have a list
            if not isinstance(graph_objects, list):
                graph_objects = [graph_objects]
            
            # Filter for relation objects (Edge_hasKGRelation)
            from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation
            filtered_relations = [obj for obj in graph_objects if isinstance(obj, Edge_hasKGRelation)]
            
            self.logger.info(f"Converted JSON-LD to {len(filtered_relations)} relation objects")
            return filtered_relations
            
        except Exception as e:
            self.logger.error(f"Error converting JSON-LD to relations: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []
    
    def _validate_relations(self, relations: List) -> None:
        """Validate relation objects."""
        # TODO: Implement validation logic
        pass
    
    async def _store_relations_in_space(self, space_id: str, graph_id: str, relations: List) -> List[str]:
        """Store relations in space and return created URIs."""
        if not relations:
            return []
        
        # Get space implementation
        space_record = self.space_manager.get_space(space_id)
        if not space_record:
            return []
        
        space_impl = space_record.space_impl
        backend = space_impl.get_db_space_impl()
        if not backend:
            return []
        
        # Convert relations to RDF quads
        from rdflib import URIRef
        quads = []
        created_uris = []
        
        for relation in relations:
            # Get relation triples using VitalSigns
            relation_triples = relation.to_rdf()
            
            # Convert to quads with graph URI
            graph_uri = URIRef(graph_id)
            for s, p, o in relation_triples:
                quads.append((s, p, o, graph_uri))
            
            # Track created URI
            if hasattr(relation, 'URI'):
                created_uris.append(relation.URI)
        
        # Store quads via backend
        if quads:
            await backend.add_rdf_quads_batch(space_id, quads)
        
        return created_uris
    
    async def _update_relations_in_space(self, space_id: str, graph_id: str, relations: List) -> List[str]:
        """Update relations in space and return updated URIs."""
        if not relations:
            return []
        
        # Get space implementation
        space_record = self.space_manager.get_space(space_id)
        if not space_record:
            return []
        
        space_impl = space_record.space_impl
        backend = space_impl.get_db_space_impl()
        if not backend:
            return []
        
        updated_uris = []
        
        for relation in relations:
            if not hasattr(relation, 'URI'):
                continue
            
            relation_uri = relation.URI
            
            # Delete existing relation triples
            delete_query = self._build_delete_relation_query(graph_id, relation_uri)
            await backend.execute_sparql_update(space_id, delete_query)
            
            # Add updated relation triples
            from rdflib import URIRef
            relation_triples = relation.to_rdf()
            graph_uri = URIRef(graph_id)
            quads = [(s, p, o, graph_uri) for s, p, o in relation_triples]
            
            if quads:
                await backend.add_rdf_quads_batch(space_id, quads)
                updated_uris.append(relation_uri)
        
        return updated_uris
    
    async def _upsert_relations_in_space(self, space_id: str, graph_id: str, relations: List) -> List[str]:
        """Upsert relations in space and return upserted URIs."""
        if not relations:
            return []
        
        # Get space implementation
        space_record = self.space_manager.get_space(space_id)
        if not space_record:
            return []
        
        space_impl = space_record.space_impl
        backend = space_impl.get_db_space_impl()
        if not backend:
            return []
        
        upserted_uris = []
        
        for relation in relations:
            if not hasattr(relation, 'URI'):
                continue
            
            relation_uri = relation.URI
            
            # Check if relation exists
            check_query = f"""
            ASK {{
                GRAPH <{graph_id}> {{
                    <{relation_uri}> ?p ?o .
                }}
            }}
            """
            
            result = await backend.execute_sparql_query(space_id, check_query)
            exists = result.get('boolean', False) if isinstance(result, dict) else False
            
            # Delete if exists
            if exists:
                delete_query = self._build_delete_relation_query(graph_id, relation_uri)
                await backend.execute_sparql_update(space_id, delete_query)
            
            # Add relation triples
            from rdflib import URIRef
            relation_triples = relation.to_rdf()
            graph_uri = URIRef(graph_id)
            quads = [(s, p, o, graph_uri) for s, p, o in relation_triples]
            
            if quads:
                await backend.add_rdf_quads_batch(space_id, quads)
                upserted_uris.append(relation_uri)
        
        return upserted_uris
    
    def _extract_count_from_results(self, count_results: Dict[str, Any]) -> int:
        """Extract count from SPARQL count query results."""
        if count_results and count_results.get("bindings"):
            for binding in count_results["bindings"]:
                count_value = binding.get("count", {}).get("value", "0")
                return int(count_value)
        return 0


def create_kgrelations_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the KG relations router."""
    endpoint = KGRelationsEndpoint(space_manager, auth_dependency)
    return endpoint.router