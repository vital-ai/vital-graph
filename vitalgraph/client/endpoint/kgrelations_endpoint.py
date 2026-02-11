"""
VitalGraph Client KGRelations Endpoint - Standardized Responses

Client-side implementation for KGRelations operations using standardized response objects.
All responses contain VitalSigns GraphObjects (Edge_hasKGRelation), hiding JSON-LD complexity.
"""

import httpx
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
    PaginatedGraphObjectResponse,
    DeleteResponse
)
from ..response.response_builder import (
    jsonld_to_graph_objects,
    build_success_response,
    build_error_response,
    extract_pagination_metadata,
    count_object_types
)

logger = logging.getLogger(__name__)


class KGRelationsEndpoint(BaseEndpoint):
    """Client endpoint for KGRelations operations with standardized responses."""
    
    def __init__(self, client):
        """Initialize the endpoint with VitalSigns instance."""
        super().__init__(client)
        self.vs = VitalSigns()
    
    async def _make_request(self, method: str, url: str, params=None, json=None):
        """
        Make authenticated HTTP request with automatic token refresh.
        Uses base endpoint's authenticated request method.
        """
        try:
            url_parts = url.split('/')
            operation = url_parts[-1] if url_parts else 'request'
            
            start_time = time.time()
            
            # Use base endpoint's authenticated request method for token refresh
            kwargs = {}
            if params:
                kwargs['params'] = params
            if json:
                kwargs['json'] = json
            
            response = await self._make_authenticated_request(method, url, **kwargs)
            
            duration = time.time() - start_time
            logger.info(f"⏱️  {method} {operation}: {duration:.3f}s")
            
            return response
            
        except httpx.HTTPError as e:
            raise VitalGraphClientError(f"Request failed: {str(e)}")
    
    async def list_relations(
        self, 
        space_id: str, 
        graph_id: str, 
        entity_source_uri: Optional[str] = None,
        entity_destination_uri: Optional[str] = None,
        relation_type_uri: Optional[str] = None,
        direction: str = "all",
        page_size: int = 10, 
        offset: int = 0
    ) -> PaginatedGraphObjectResponse:
        """
        List KGRelations with pagination and enhanced filtering.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_source_uri: Filter by source entity URI
            entity_destination_uri: Filter by destination entity URI
            relation_type_uri: Filter by relation type URI (e.g., MakesProductRelation)
            direction: Direction filter: "all", "incoming", "outgoing"
            page_size: Number of items per page
            offset: Offset for pagination
            
        Returns:
            PaginatedGraphObjectResponse with Edge_hasKGRelation objects
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgrelations"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                entity_source_uri=entity_source_uri,
                entity_destination_uri=entity_destination_uri,
                relation_type_uri=relation_type_uri,
                direction=direction,
                page_size=page_size,
                offset=offset
            )
            
            logger.debug(f"DEBUG list_relations params: {params}")
            logger.debug(f"DEBUG relation_type_uri value: {relation_type_uri}, type: {type(relation_type_uri)}")
            
            response = await self._make_request('GET', url, params=params)
            response_data = response.json()
            
            # Convert JSON-LD to VitalSigns objects
            relations_jsonld = response_data.get('relations', {})
            relations = jsonld_to_graph_objects(relations_jsonld, self.vs)
            
            # Extract pagination metadata
            pagination = extract_pagination_metadata(response_data)
            
            return build_success_response(
                PaginatedGraphObjectResponse,
                objects=relations,
                status_code=response.status_code,
                message=f"Retrieved {len(relations)} relations",
                space_id=space_id,
                graph_id=graph_id,
                entity_source_uri=entity_source_uri,
                entity_destination_uri=entity_destination_uri,
                relation_type_uri=relation_type_uri,
                direction=direction,
                **pagination,
                metadata={'object_types': count_object_types(relations)}
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error listing relations: {e}")
            return build_error_response(
                PaginatedGraphObjectResponse,
                error_code=1,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
    
    async def get_relation(
        self, 
        space_id: str, 
        graph_id: str, 
        relation_uri: str
    ) -> EntityResponse:
        """
        Get a specific KGRelation by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            relation_uri: Relation URI
            
        Returns:
            EntityResponse with single Edge_hasKGRelation object
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, relation_uri=relation_uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgrelations"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                relation_uri=relation_uri
            )
            
            response = await self._make_request('GET', url, params=params)
            response_data = response.json()
            
            # Convert JSON-LD to VitalSigns object
            relation_jsonld = response_data.get('relation', {})
            relations = jsonld_to_graph_objects(relation_jsonld, self.vs)
            
            return build_success_response(
                EntityResponse,
                objects=relations,
                status_code=response.status_code,
                message=f"Retrieved {len(relations)} relation(s)" if relations else "Relation not found",
                space_id=space_id,
                graph_id=graph_id
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error getting relation: {e}")
            return build_error_response(
                EntityResponse,
                error_code=1,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id,
                uri=relation_uri
            )
    
    async def create_relations(
        self, 
        space_id: str, 
        graph_id: str, 
        relations: List
    ) -> CreateEntityResponse:
        """
        Create new KGRelations from VitalSigns Edge_hasKGRelation objects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            relations: List of VitalSigns Edge_hasKGRelation objects
            
        Returns:
            CreateEntityResponse with created relation URIs
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, relations=relations)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgrelations"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                operation_mode='create'
            )
            
            # Convert VitalSigns objects to JSON-LD and wrap in JsonLdDocument
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument
            
            jsonld_dict = GraphObject.to_jsonld_list(relations)
            
            if len(relations) == 1:
                # Single relation - create JsonLdObject
                data = JsonLdObject(**jsonld_dict['@graph'][0])
                data.jsonld_type = 'object'
            else:
                # Multiple relations - create JsonLdDocument
                data = JsonLdDocument(
                    context=jsonld_dict.get('@context', 'http://vital.ai/ontology/vital-core'),
                    graph=jsonld_dict['@graph']
                )
                data.jsonld_type = 'document'
            
            response = await self._make_request('POST', url, params=params, json=data.model_dump(by_alias=True))
            response_data = response.json()
            
            # Extract created URIs from response
            created_uris = response_data.get('created_uris', [])
            created_count = response_data.get('created_count', len(created_uris))
            
            return build_success_response(
                CreateEntityResponse,
                created_uris=created_uris,
                created_count=created_count,
                status_code=response.status_code,
                message=f"Created {created_count} relation(s)",
                space_id=space_id,
                graph_id=graph_id
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error creating relations: {e}")
            return build_error_response(
                CreateEntityResponse,
                error_code=1,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
    
    async def update_relations(
        self, 
        space_id: str, 
        graph_id: str, 
        relations: List
    ) -> UpdateEntityResponse:
        """
        Update existing KGRelations.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            relations: List of VitalSigns Edge_hasKGRelation objects with URIs
            
        Returns:
            UpdateEntityResponse with update results
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, relations=relations)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgrelations"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                operation_mode='update'
            )
            
            # Convert VitalSigns objects to JSON-LD and wrap in JsonLdDocument
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument
            
            jsonld_dict = GraphObject.to_jsonld_list(relations)
            
            if len(relations) == 1:
                data = JsonLdObject(**jsonld_dict['@graph'][0])
                data.jsonld_type = 'object'
            else:
                data = JsonLdDocument(
                    context=jsonld_dict.get('@context', 'http://vital.ai/ontology/vital-core'),
                    graph=jsonld_dict['@graph']
                )
                data.jsonld_type = 'document'
            
            response = await self._make_request('POST', url, params=params, json=data.model_dump(by_alias=True))
            response_data = response.json()
            
            # Extract updated URIs from response
            updated_uris = response_data.get('updated_uris', [])
            updated_count = len(updated_uris)
            
            return build_success_response(
                UpdateEntityResponse,
                updated_uri=updated_uris[0] if updated_uris else None,
                status_code=response.status_code,
                message=f"Updated {updated_count} relation(s)",
                space_id=space_id,
                graph_id=graph_id
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error updating relations: {e}")
            return build_error_response(
                UpdateEntityResponse,
                error_code=1,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
    
    async def upsert_relations(
        self, 
        space_id: str, 
        graph_id: str, 
        relations: List
    ) -> UpdateEntityResponse:
        """
        Upsert (create or update) KGRelations.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            relations: List of VitalSigns Edge_hasKGRelation objects
            
        Returns:
            UpdateEntityResponse with upsert results
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, relations=relations)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgrelations"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                operation_mode='upsert'
            )
            
            # Convert VitalSigns objects to JSON-LD and wrap in JsonLdDocument
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument
            
            jsonld_dict = GraphObject.to_jsonld_list(relations)
            
            if len(relations) == 1:
                data = JsonLdObject(**jsonld_dict['@graph'][0])
                data.jsonld_type = 'object'
            else:
                data = JsonLdDocument(
                    context=jsonld_dict.get('@context', 'http://vital.ai/ontology/vital-core'),
                    graph=jsonld_dict['@graph']
                )
                data.jsonld_type = 'document'
            
            response = await self._make_request('POST', url, params=params, json=data.model_dump(by_alias=True))
            response_data = response.json()
            
            # Extract upserted URIs from response
            upserted_uris = response_data.get('upserted_uris', [])
            upserted_count = len(upserted_uris)
            
            return build_success_response(
                UpdateEntityResponse,
                updated_uri=upserted_uris[0] if upserted_uris else None,
                status_code=response.status_code,
                message=f"Upserted {upserted_count} relation(s)",
                space_id=space_id,
                graph_id=graph_id
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error upserting relations: {e}")
            return build_error_response(
                UpdateEntityResponse,
                error_code=1,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
    
    async def delete_relations(
        self, 
        space_id: str, 
        graph_id: str, 
        relation_uris: List[str]
    ) -> DeleteResponse:
        """
        Delete KGRelations by URIs.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            relation_uris: List of relation URIs to delete
            
        Returns:
            DeleteResponse with deletion results
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, relation_uris=relation_uris)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgrelations"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id
            )
            
            # Build delete request body
            delete_request = {
                'relation_uris': relation_uris
            }
            
            response = await self._make_request('DELETE', url, params=params, json=delete_request)
            response_data = response.json()
            
            # Extract deletion results
            deleted_count = response_data.get('deleted_count', 0)
            deleted_uris = response_data.get('deleted_uris', relation_uris)
            
            return build_success_response(
                DeleteResponse,
                deleted_count=deleted_count,
                deleted_uris=deleted_uris,
                status_code=response.status_code,
                message=f"Deleted {deleted_count} relation(s)",
                space_id=space_id,
                graph_id=graph_id
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error deleting relations: {e}")
            return build_error_response(
                DeleteResponse,
                error_code=1,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
