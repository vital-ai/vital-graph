"""
VitalGraph Client KGEntities Endpoint - Refactored with Standardized Responses

Client-side implementation for KGEntities operations using standardized response objects.
All responses contain VitalSigns GraphObjects, hiding JSON-LD complexity.
"""

import requests
import time
import logging
from typing import Dict, Any, Optional, List

from vital_ai_vitalsigns.vitalsigns import VitalSigns

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ..response.client_response import (
    EntityResponse,
    CreateEntityResponse,
    UpdateEntityResponse,
    EntityGraphResponse,
    FrameResponse,
    FrameGraphResponse,
    PaginatedGraphObjectResponse,
    MultiEntityGraphResponse,
    MultiFrameGraphResponse,
    DeleteResponse,
    QueryResponse,
    EntityGraph,
    FrameGraph
)
from ..response.response_builder import (
    jsonld_to_graph_objects,
    build_success_response,
    build_error_response,
    extract_pagination_metadata,
    build_entity_graph,
    build_frame_graph,
    count_object_types
)

logger = logging.getLogger(__name__)


class KGEntitiesEndpoint(BaseEndpoint):
    """Client endpoint for KGEntities operations with standardized responses."""
    
    def __init__(self, client):
        """Initialize the endpoint with VitalSigns instance."""
        super().__init__(client)
        self.vs = VitalSigns()
    
    def _make_request(self, method: str, url: str, params=None, json=None):
        """
        Make HTTP request and return response object.
        """
        try:
            url_parts = url.split('/')
            operation = url_parts[-1] if url_parts else 'request'
            
            start_time = time.time()
            if method == 'GET':
                response = self.client.session.get(url, params=params)
            elif method == 'POST':
                response = self.client.session.post(url, params=params, json=json)
            elif method == 'DELETE':
                response = self.client.session.delete(url, params=params)
            else:
                raise VitalGraphClientError(f"Unsupported HTTP method: {method}")
            
            duration = time.time() - start_time
            logger.info(f"⏱️  {method} {operation}: {duration:.3f}s")
            
            response.raise_for_status()
            return response
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Request failed: {str(e)}")
    
    def list_kgentities(
        self, 
        space_id: str, 
        graph_id: str, 
        page_size: int = 10, 
        offset: int = 0, 
        entity_type_uri: Optional[str] = None, 
        search: Optional[str] = None, 
        include_entity_graph: bool = False
    ):
        """
        List KGEntities with pagination and optional filtering.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            entity_type_uri: Optional entity type URI to filter by
            search: Optional search term
            include_entity_graph: If True, include complete entity graphs
            
        Returns:
            PaginatedGraphObjectResponse if include_entity_graph=False
            MultiEntityGraphResponse if include_entity_graph=True
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgentities"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                entity_type_uri=entity_type_uri,
                search=search,
                include_entity_graph=include_entity_graph
            )
            
            response = self._make_request('GET', url, params=params)
            response_data = response.json()
            
            # Use VitalSigns instance
            vs = self.vs
            
            if include_entity_graph:
                # Log complete server response for debugging
                import json
                logger.info(f"=== SERVER RESPONSE FOR list_kgentities with include_entity_graph=True ===")
                logger.info(json.dumps(response_data, indent=2, default=str))
                logger.info(f"=== END SERVER RESPONSE ===")
                
                # Server returns all entities with their complete graphs in the entities field
                # Parse all objects first
                entities_jsonld = response_data.get('entities', {})
                all_objects = jsonld_to_graph_objects(entities_jsonld, vs)
                
                # Group objects by their kGGraphURI to create separate entity graphs
                entity_graphs_dict = {}
                for obj in all_objects:
                    # Get the graph URI for this object
                    graph_uri = None
                    if hasattr(obj, 'kGGraphURI') and obj.kGGraphURI:
                        graph_uri = str(obj.kGGraphURI)
                    
                    if graph_uri:
                        if graph_uri not in entity_graphs_dict:
                            entity_graphs_dict[graph_uri] = []
                        entity_graphs_dict[graph_uri].append(obj)
                
                # Build EntityGraph containers
                entity_graphs = []
                for entity_uri, objects in entity_graphs_dict.items():
                    entity_graphs.append(build_entity_graph(entity_uri, objects))
                
                return build_success_response(
                    MultiEntityGraphResponse,
                    graph_list=entity_graphs,
                    status_code=response.status_code,
                    message=f"Retrieved {len(entity_graphs)} entity graphs",
                    space_id=space_id,
                    graph_id=graph_id,
                    metadata={'total_graphs': len(entity_graphs)}
                )
            else:
                # Response contains flat list of entities with pagination
                entities_jsonld = response_data.get('entities', {})
                objects = jsonld_to_graph_objects(entities_jsonld, vs)
                
                pagination = extract_pagination_metadata(response_data)
                
                return build_success_response(
                    PaginatedGraphObjectResponse,
                    objects=objects,
                    status_code=response.status_code,
                    message=f"Retrieved {len(objects)} entities",
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_type_uri=entity_type_uri,
                    search=search,
                    **pagination,
                    metadata={'object_types': count_object_types(objects)}
                )
                
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error listing entities: {e}")
            response_class = MultiEntityGraphResponse if include_entity_graph else PaginatedGraphObjectResponse
            return build_error_response(
                response_class,
                error_code=1,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
    
    def get_kgentity(
        self, 
        space_id: str, 
        graph_id: str, 
        uri: Optional[str] = None, 
        reference_id: Optional[str] = None, 
        include_entity_graph: bool = False
    ):
        """
        Get a specific KGEntity by URI or reference ID with optional complete graph.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGEntity URI (mutually exclusive with reference_id)
            reference_id: Reference ID (mutually exclusive with uri)
            include_entity_graph: If True, include complete entity graph
            
        Returns:
            EntityResponse if include_entity_graph=False
            EntityGraphResponse if include_entity_graph=True
            
        Raises:
            VitalGraphClientError: If request fails or both uri and reference_id are provided
        """
        self._check_connection()
        
        if uri and reference_id:
            raise VitalGraphClientError("Cannot specify both uri and reference_id")
        if not uri and not reference_id:
            raise VitalGraphClientError("Must specify either uri or reference_id")
        
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgentities"
            
            params_dict = {
                'space_id': space_id,
                'graph_id': graph_id,
                'include_entity_graph': include_entity_graph
            }
            
            if uri:
                params_dict['uri'] = uri
            else:
                params_dict['id'] = reference_id
            
            params = build_query_params(**params_dict)
            
            response = self._make_request('GET', url, params=params)
            response_data = response.json()
            
            vs = self.vs
            
            if include_entity_graph:
                # Server returns raw JSON-LD directly (JsonLdDocument with @graph)
                objects = jsonld_to_graph_objects(response_data, vs)
                
                # Extract entity URI from the objects
                entity_uri = uri or reference_id
                for obj in objects:
                    if hasattr(obj, 'URI'):
                        from ai_haley_kg_domain.model.KGEntity import KGEntity
                        if isinstance(obj, KGEntity):
                            entity_uri = str(obj.URI)
                            break
                
                entity_graph = build_entity_graph(entity_uri, objects)
                
                return build_success_response(
                    EntityGraphResponse,
                    objects=entity_graph,
                    status_code=response.status_code,
                    message=f"Retrieved entity graph with {len(objects)} objects",
                    space_id=space_id,
                    graph_id=graph_id,
                    requested_uri=uri,
                    requested_reference_id=reference_id,
                    metadata={'object_types': count_object_types(objects)}
                )
            else:
                # Response contains just the entity
                objects = jsonld_to_graph_objects(response_data, vs)
                
                return build_success_response(
                    EntityResponse,
                    objects=objects,
                    status_code=response.status_code,
                    message=f"Retrieved entity",
                    space_id=space_id,
                    graph_id=graph_id,
                    metadata={'object_types': count_object_types(objects)}
                )
                
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error getting entity: {e}")
            response_class = EntityGraphResponse if include_entity_graph else EntityResponse
            return build_error_response(
                response_class,
                error_code=2,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id,
                requested_uri=uri,
                requested_reference_id=reference_id
            )
    
    def get_kgentities_by_reference_ids(
        self, 
        space_id: str, 
        graph_id: str, 
        reference_ids: List[str], 
        include_entity_graph: bool = False
    ):
        """
        Get multiple KGEntities by reference ID list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            reference_ids: List of reference IDs
            include_entity_graph: If True, include complete entity graphs
            
        Returns:
            PaginatedGraphObjectResponse if include_entity_graph=False
            MultiEntityGraphResponse if include_entity_graph=True
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, reference_ids=reference_ids)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgentities"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                id_list=",".join(reference_ids),
                include_entity_graph=include_entity_graph
            )
            
            response = self._make_request('GET', url, params=params)
            response_data = response.json()
            
            vs = self.vs
            
            if include_entity_graph:
                # Server returns EntitiesGraphResponse with complete_graphs dict
                complete_graphs_dict = response_data.get('complete_graphs', {})
                entity_graphs = []
                
                for entity_uri, graph_jsonld in complete_graphs_dict.items():
                    objects = jsonld_to_graph_objects(graph_jsonld, vs)
                    entity_graphs.append(build_entity_graph(entity_uri, objects))
                
                return build_success_response(
                    MultiEntityGraphResponse,
                    graph_list=entity_graphs,
                    status_code=response.status_code,
                    message=f"Retrieved {len(entity_graphs)} entity graphs",
                    space_id=space_id,
                    graph_id=graph_id,
                    requested_reference_ids=reference_ids,
                    metadata={'total_graphs': len(entity_graphs)}
                )
            else:
                # Response contains flat list of entities
                entities_jsonld = response_data.get('entities', response_data)
                objects = jsonld_to_graph_objects(entities_jsonld, vs)
                
                pagination = extract_pagination_metadata(response_data)
                
                return build_success_response(
                    PaginatedGraphObjectResponse,
                    objects=objects,
                    status_code=response.status_code,
                    message=f"Retrieved {len(objects)} entities",
                    space_id=space_id,
                    graph_id=graph_id,
                    **pagination,
                    metadata={'object_types': count_object_types(objects)}
                )
                
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error getting entities by reference IDs: {e}")
            response_class = MultiEntityGraphResponse if include_entity_graph else PaginatedGraphObjectResponse
            return build_error_response(
                response_class,
                error_code=3,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id,
                requested_reference_ids=reference_ids
            )
    
    def create_kgentities(
        self, 
        space_id: str, 
        graph_id: str, 
        objects: List,
        parent_uri: Optional[str] = None
    ) -> EntityResponse:
        """
        Create KGEntities from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances to create
            parent_uri: Optional parent URI for relationships
            
        Returns:
            EntityResponse containing created entities
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, objects=objects)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgentities"
            
            # Convert GraphObjects to JsonLdObject or JsonLdDocument (matching old endpoint)
            from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            vs = self.vs
            
            if len(objects) == 1:
                # Single object - create JsonLdObject
                jsonld_dict = GraphObject.to_jsonld_list([objects[0]])
                data = JsonLdObject(**jsonld_dict['@graph'][0])
                data.jsonld_type = 'object'
            else:
                # Multiple objects - create JsonLdDocument
                jsonld_dict = GraphObject.to_jsonld_list(objects)
                data = JsonLdDocument(
                    context=jsonld_dict.get('@context', 'http://vital.ai/ontology/vital-core'),
                    graph=jsonld_dict['@graph']
                )
                data.jsonld_type = 'document'
            
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                operation_mode="create",
                parent_uri=parent_uri
            )
            
            # Send exactly like old endpoint
            response = self._make_request('POST', url, params=params, json=data.model_dump(by_alias=True))
            response_data = response.json()
            
            # Server returns EntityCreateResponse with metadata (created_count, created_uris)
            # It doesn't return the actual entity data, so we return an empty objects list
            # Client can do a GET request if they need the actual objects
            created_count = response_data.get('created_count', 0)
            created_uris = response_data.get('created_uris', [])
            
            return build_success_response(
                CreateEntityResponse,
                status_code=response.status_code,
                message=response_data.get('message', f"Created {created_count} entities"),
                created_count=created_count,
                created_uris=created_uris
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error creating entities: {e}")
            return build_error_response(
                CreateEntityResponse,
                error_code=4,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
    
    def update_kgentities(
        self, 
        space_id: str, 
        graph_id: str, 
        objects: List,
        parent_uri: Optional[str] = None
    ) -> EntityResponse:
        """
        Update KGEntities from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances to update
            parent_uri: Optional parent URI for relationships
            
        Returns:
            EntityResponse containing updated entities
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, objects=objects)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgentities"
            
            # Convert GraphObjects to JsonLdObject or JsonLdDocument (matching old endpoint)
            from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            vs = self.vs
            
            if len(objects) == 1:
                # Single object - create JsonLdObject
                jsonld_dict = GraphObject.to_jsonld_list([objects[0]])
                data = JsonLdObject(**jsonld_dict['@graph'][0])
                data.jsonld_type = 'object'
            else:
                # Multiple objects - create JsonLdDocument
                jsonld_dict = GraphObject.to_jsonld_list(objects)
                data = JsonLdDocument(
                    context=jsonld_dict.get('@context', 'http://vital.ai/ontology/vital-core'),
                    graph=jsonld_dict['@graph']
                )
                data.jsonld_type = 'document'
            
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                operation_mode="update",
                parent_uri=parent_uri
            )
            
            # Send exactly like old endpoint
            response = self._make_request('POST', url, params=params, json=data.model_dump(by_alias=True))
            response_data = response.json()
            
            # Server returns EntityUpdateResponse with metadata (updated_uri)
            # It doesn't return the actual entity data
            updated_uri = response_data.get('updated_uri')
            
            return build_success_response(
                UpdateEntityResponse,
                status_code=response.status_code,
                message=response_data.get('message', 'Updated entities'),
                updated_uri=updated_uri
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error updating entities: {e}")
            return build_error_response(
                UpdateEntityResponse,
                error_code=5,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
    
    def delete_kgentity(
        self, 
        space_id: str, 
        graph_id: str, 
        uri: str, 
        delete_entity_graph: bool = False
    ) -> DeleteResponse:
        """
        Delete a KGEntity by URI with optional complete graph deletion.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGEntity URI to delete
            delete_entity_graph: If True, delete entire entity graph
            
        Returns:
            DeleteResponse containing deletion results
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgentities"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=uri,
                delete_entity_graph=delete_entity_graph
            )
            
            response = self._make_request('DELETE', url, params=params)
            response_data = response.json()
            
            deleted_count = response_data.get('deleted_count', 1)
            deleted_uris = response_data.get('deleted_uris', [uri])
            
            return build_success_response(
                DeleteResponse,
                status_code=response.status_code,
                message=f"Deleted {deleted_count} items",
                space_id=space_id,
                graph_id=graph_id,
                requested_uris=[uri],
                deleted_count=deleted_count,
                deleted_uris=deleted_uris,
                metadata={'delete_entity_graph': delete_entity_graph}
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error deleting entity: {e}")
            return build_error_response(
                DeleteResponse,
                error_code=6,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id,
                requested_uris=[uri]
            )
    
    def delete_kgentities_batch(
        self, 
        space_id: str, 
        graph_id: str, 
        uri_list: List[str]
    ) -> DeleteResponse:
        """
        Delete multiple KGEntities by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: List of KGEntity URIs to delete
            
        Returns:
            DeleteResponse containing deletion results
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgentities"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri_list=",".join(uri_list)
            )
            
            response = self._make_request('DELETE', url, params=params)
            response_data = response.json()
            
            deleted_count = response_data.get('deleted_count', len(uri_list))
            deleted_uris = response_data.get('deleted_uris', uri_list)
            
            return build_success_response(
                DeleteResponse,
                status_code=response.status_code,
                message=f"Deleted {deleted_count} entities",
                space_id=space_id,
                graph_id=graph_id,
                requested_uris=uri_list,
                deleted_count=deleted_count,
                deleted_uris=deleted_uris
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error deleting entities batch: {e}")
            return build_error_response(
                DeleteResponse,
                error_code=7,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id,
                requested_uris=uri_list
            )
    
    def get_kgentity_frames(
        self,
        space_id: str,
        graph_id: str,
        entity_uri: str,
        frame_uris: Optional[List[str]] = None,
        parent_frame_uri: Optional[str] = None,
        page_size: int = 10,
        offset: int = 0,
        search: Optional[str] = None
    ):
        """
        Get frames associated with a KGEntity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to get frames for
            frame_uris: Specific frame URIs to retrieve (optional)
            parent_frame_uri: Parent frame URI for hierarchical filtering
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            FrameResponse if frame_uris is None (list of frames)
            FrameGraphResponse if frame_uris contains one URI (single frame graph)
            MultiFrameGraphResponse if frame_uris contains multiple URIs
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, entity_uri=entity_uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgentities/kgframes"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=frame_uris,
                parent_frame_uri=parent_frame_uri,
                page_size=page_size,
                offset=offset,
                search=search
            )
            
            response = self._make_request('GET', url, params=params)
            response_data = response.json()
            
            vs = self.vs
            
            if frame_uris:
                # Server returns FrameGraphsResponse with frame_graphs dict
                frame_graphs_dict = response_data.get('frame_graphs', {})
                
                if len(frame_uris) == 1:
                    # Single frame graph
                    frame_uri = frame_uris[0]
                    frame_jsonld = frame_graphs_dict.get(frame_uri, {})
                    
                    # Check if it's an error response
                    if isinstance(frame_jsonld, dict) and 'error' in frame_jsonld:
                        # Frame returned an error
                        return build_error_response(
                            FrameGraphResponse,
                            error_code=3,
                            error_message=frame_jsonld.get('message', 'Frame not found'),
                            status_code=404,
                            space_id=space_id,
                            graph_id=graph_id,
                            entity_uri=entity_uri,
                            requested_frame_uri=frame_uri
                        )
                    
                    # Convert Pydantic model to dict if needed
                    if hasattr(frame_jsonld, 'model_dump'):
                        frame_jsonld = frame_jsonld.model_dump(by_alias=True)
                    
                    # The frame_jsonld is a dict with structure: {"jsonld_type": "document", "@context": {}, "@graph": [...]}
                    # We need to pass this whole structure to jsonld_to_graph_objects
                    objects = jsonld_to_graph_objects(frame_jsonld, vs)
                    
                    frame_graph = build_frame_graph(frame_uri, objects)
                    
                    return build_success_response(
                        FrameGraphResponse,
                        frame_graph=frame_graph,
                        status_code=response.status_code,
                        message=f"Retrieved frame graph with {len(objects)} objects",
                        space_id=space_id,
                        graph_id=graph_id,
                        entity_uri=entity_uri,
                        parent_frame_uri=parent_frame_uri,
                        requested_frame_uri=frame_uri,
                        metadata={'object_types': count_object_types(objects)}
                    )
                else:
                    # Multiple frame graphs - parse each from frame_graphs dict
                    frame_graphs = []
                    
                    for frame_uri in frame_uris:
                        frame_jsonld = frame_graphs_dict.get(frame_uri, {})
                        if frame_jsonld:
                            # Skip error responses
                            if isinstance(frame_jsonld, dict) and 'error' in frame_jsonld:
                                logger.debug(f"Skipping frame {frame_uri} - error: {frame_jsonld.get('error')}")
                                continue
                            
                            # Convert Pydantic model to dict if needed
                            if hasattr(frame_jsonld, 'model_dump'):
                                frame_jsonld = frame_jsonld.model_dump(by_alias=True)
                            
                            objects = jsonld_to_graph_objects(frame_jsonld, vs)
                            if objects:  # Only add if we got objects
                                frame_graphs.append(build_frame_graph(frame_uri, objects))
                    
                    return build_success_response(
                        MultiFrameGraphResponse,
                        frame_graph_list=frame_graphs,
                        status_code=response.status_code,
                        message=f"Retrieved {len(frame_graphs)} frame graphs",
                        space_id=space_id,
                        graph_id=graph_id,
                        entity_uri=entity_uri,
                        requested_frame_uris=frame_uris,
                        metadata={'total_graphs': len(frame_graphs)}
                    )
            else:
                # Response contains flat list of frames
                frames_jsonld = response_data.get('frames', response_data)
                objects = jsonld_to_graph_objects(frames_jsonld, vs)
                
                return build_success_response(
                    FrameResponse,
                    objects=objects,
                    status_code=response.status_code,
                    message=f"Retrieved {len(objects)} frames",
                    space_id=space_id,
                    graph_id=graph_id,
                    metadata={'object_types': count_object_types(objects)}
                )
                
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error getting frames: {e}")
            if frame_uris:
                response_class = FrameGraphResponse if len(frame_uris) == 1 else MultiFrameGraphResponse
            else:
                response_class = FrameResponse
            return build_error_response(
                response_class,
                error_code=8,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
    
    def create_entity_frames(
        self,
        space_id: str,
        graph_id: str,
        entity_uri: str,
        objects: List,
        parent_frame_uri: Optional[str] = None
    ) -> FrameResponse:
        """
        Create frames for a specific entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to create frames for
            objects: List of GraphObject instances (frames and slots)
            parent_frame_uri: Optional parent frame URI
            
        Returns:
            FrameResponse containing created frames
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, entity_uri=entity_uri, objects=objects)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgentities/kgframes"
            
            # Convert GraphObjects to JsonLdObject or JsonLdDocument (matching old endpoint)
            from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            vs = self.vs
            
            if len(objects) == 1:
                # Single object - create JsonLdObject
                jsonld_dict = GraphObject.to_jsonld_list([objects[0]])
                data = JsonLdObject(**jsonld_dict['@graph'][0])
                data.jsonld_type = 'object'
            else:
                # Multiple objects - create JsonLdDocument
                jsonld_dict = GraphObject.to_jsonld_list(objects)
                data = JsonLdDocument(
                    context=jsonld_dict.get('@context', 'http://vital.ai/ontology/vital-core'),
                    graph=jsonld_dict['@graph']
                )
                data.jsonld_type = 'document'
            
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                parent_frame_uri=parent_frame_uri
            )
            
            # Send exactly like old endpoint
            response = self._make_request('POST', url, params=params, json=data.model_dump(by_alias=True))
            response_data = response.json()
            
            # Parse created frames from response
            created_jsonld = response_data.get('frames', response_data)
            created_objects = jsonld_to_graph_objects(created_jsonld, vs)
            
            return build_success_response(
                FrameResponse,
                objects=created_objects,
                status_code=response.status_code,
                message=f"Created {len(created_objects)} frames",
                space_id=space_id,
                graph_id=graph_id,
                metadata={'object_types': count_object_types(created_objects)}
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error creating frames: {e}")
            return build_error_response(
                FrameResponse,
                error_code=9,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
    
    def update_entity_frames(
        self,
        space_id: str,
        graph_id: str,
        entity_uri: str,
        objects: List,
        parent_frame_uri: Optional[str] = None
    ) -> FrameResponse:
        """
        Update frames for a specific entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to update frames for
            objects: List of GraphObject instances (frames and slots)
            parent_frame_uri: Optional parent frame URI
            
        Returns:
            FrameResponse containing updated frames
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, entity_uri=entity_uri, objects=objects)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgentities/kgframes"
            
            # Convert GraphObjects to JsonLdObject or JsonLdDocument (matching old endpoint)
            from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            vs = self.vs
            
            if len(objects) == 1:
                # Single object - create JsonLdObject
                jsonld_dict = GraphObject.to_jsonld_list([objects[0]])
                data = JsonLdObject(**jsonld_dict['@graph'][0])
                data.jsonld_type = 'object'
            else:
                # Multiple objects - create JsonLdDocument
                jsonld_dict = GraphObject.to_jsonld_list(objects)
                data = JsonLdDocument(
                    context=jsonld_dict.get('@context', 'http://vital.ai/ontology/vital-core'),
                    graph=jsonld_dict['@graph']
                )
                data.jsonld_type = 'document'
            
            # Log what we're sending for debugging
            import json
            logger.info(f"=== UPDATE FRAMES REQUEST ===")
            logger.info(f"Sending {len(objects)} objects")
            logger.info(f"Data: {json.dumps(jsonld_dict, indent=2, default=str)}")
            logger.info(f"=== END REQUEST ===")
            
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                parent_frame_uri=parent_frame_uri,
                operation_mode="update"
            )
            
            # Send exactly like old endpoint
            response = self._make_request('POST', url, params=params, json=data.model_dump(by_alias=True))
            response_data = response.json()
            
            # Log complete server response for debugging
            import json
            logger.info(f"=== UPDATE RESPONSE FROM SERVER ===")
            logger.info(f"Status: {response.status_code}")
            logger.info(f"Response: {json.dumps(response_data, indent=2, default=str)}")
            logger.info(f"=== END RESPONSE ===")
            
            # Check if update actually succeeded (frames_updated > 0)
            frames_updated = response_data.get('frames_updated', 0)
            if frames_updated == 0:
                error_msg = response_data.get('message', 'Frame update failed')
                return build_error_response(
                    FrameResponse,
                    error_code=12,
                    error_message=error_msg,
                    status_code=response.status_code,
                    space_id=space_id,
                    graph_id=graph_id
                )
            
            # Parse updated frames from response
            updated_jsonld = response_data.get('frames', response_data)
            updated_objects = jsonld_to_graph_objects(updated_jsonld, vs)
            
            return build_success_response(
                FrameResponse,
                objects=updated_objects,
                status_code=response.status_code,
                message=f"Updated {len(updated_objects)} frames",
                space_id=space_id,
                graph_id=graph_id,
                metadata={'object_types': count_object_types(updated_objects)}
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error updating frames: {e}")
            return build_error_response(
                FrameResponse,
                error_code=10,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
    
    def delete_entity_frames(
        self,
        space_id: str,
        graph_id: str,
        entity_uri: str,
        frame_uris: List[str],
        parent_frame_uri: Optional[str] = None
    ) -> DeleteResponse:
        """
        Delete specific frames from an entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to delete frames from
            frame_uris: List of frame URIs to delete
            parent_frame_uri: Optional parent frame URI for validation
            
        Returns:
            DeleteResponse containing deletion results
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, entity_uri=entity_uri, frame_uris=frame_uris)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgentities/kgframes"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=','.join(frame_uris),
                parent_frame_uri=parent_frame_uri
            )
            
            response = self._make_request('DELETE', url, params=params)
            response_data = response.json()
            
            # Check if response indicates failure (success=false)
            if response_data.get('success') is False:
                error_msg = response_data.get('message') or 'Delete operation failed'
                error_code = response_data.get('error_code', 11)
                return build_error_response(
                    DeleteResponse,
                    error_code=error_code,
                    error_message=error_msg,
                    status_code=response.status_code,
                    space_id=space_id,
                    graph_id=graph_id,
                    requested_uris=frame_uris
                )
            
            deleted_count = response_data.get('deleted_count', len(frame_uris))
            deleted_uris = response_data.get('deleted_uris', frame_uris)
            
            return build_success_response(
                DeleteResponse,
                status_code=response.status_code,
                message=f"Deleted {deleted_count} frames",
                space_id=space_id,
                graph_id=graph_id,
                requested_uris=frame_uris,
                deleted_count=deleted_count,
                deleted_uris=deleted_uris,
                metadata={'entity_uri': entity_uri}
            )
            
        except VitalGraphClientError as e:
            logger.error(f"Error deleting frames: {e}")
            return build_error_response(
                DeleteResponse,
                error_code=11,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id,
                requested_uris=frame_uris
            )
        except Exception as e:
            logger.error(f"Error deleting frames: {e}")
            return build_error_response(
                DeleteResponse,
                error_code=11,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id,
                requested_uris=frame_uris
            )
    
    def query_entities(
        self,
        space_id: str,
        graph_id: str,
        query_criteria: Dict[str, Any]
    ) -> QueryResponse:
        """
        Query KGEntities using criteria-based search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            query_criteria: Query criteria dictionary
            
        Returns:
            QueryResponse containing matching entities
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, query_criteria=query_criteria)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgentities/query"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id
            )
            
            response = self._make_request('POST', url, params=params, json=query_criteria)
            response_data = response.json()
            
            vs = self.vs
            
            # Parse query results
            results_jsonld = response_data.get('results', response_data)
            objects = jsonld_to_graph_objects(results_jsonld, vs)
            
            query_info = {
                'execution_time': response_data.get('execution_time'),
                'total_results': response_data.get('total_results', len(objects))
            }
            
            return build_success_response(
                QueryResponse,
                objects=objects,
                status_code=response.status_code,
                message=f"Query returned {len(objects)} results",
                space_id=space_id,
                graph_id=graph_id,
                query_criteria=query_criteria,
                query_info=query_info,
                metadata={'object_types': count_object_types(objects)}
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error querying entities: {e}")
            return build_error_response(
                QueryResponse,
                error_code=12,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id,
                query_criteria=query_criteria
            )
