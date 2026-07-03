"""
VitalGraph Client SPARQL Endpoint

Client-side implementation for SPARQL operations.
"""

import httpx
from typing import Dict, Any, Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.sparql_model import (
    SPARQLQueryRequest, SPARQLQueryResponse, SPARQLUpdateRequest, SPARQLUpdateResponse,
    SPARQLInsertRequest, SPARQLInsertResponse, SPARQLDeleteRequest, SPARQLDeleteResponse
)


class SparqlEndpoint(BaseEndpoint):
    """Client endpoint for SPARQL operations."""
    
    async def execute_sparql_query(self, space_id: str, request: SPARQLQueryRequest) -> SPARQLQueryResponse:
        """
        Execute a SPARQL query.
        
        Args:
            space_id: Space identifier
            request: SPARQL query request with query string and options
            
        Returns:
            SPARQLQueryResponse containing query results
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, request=request)
        
        url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/query"
        
        return await self._make_typed_request('POST', url, SPARQLQueryResponse, params={'space_id': space_id}, json=request.model_dump())
    
    async def execute_sparql_insert(self, space_id: str, request: SPARQLInsertRequest) -> SPARQLInsertResponse:
        """
        Execute a SPARQL insert operation (W3C SPARQL 1.1 Protocol compliant).
        
        Args:
            space_id: Space identifier
            request: SPARQL insert request with query and options
            
        Returns:
            SPARQLInsertResponse containing insert results
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, request=request)
        
        url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/insert"
        
        return await self._make_typed_request('POST', url, SPARQLInsertResponse, params={'space_id': space_id}, json=request.model_dump())
    
    async def execute_sparql_update(self, space_id: str, request: SPARQLUpdateRequest) -> SPARQLUpdateResponse:
        """
        Execute a SPARQL update operation (W3C SPARQL 1.1 Protocol compliant).
        
        Args:
            space_id: Space identifier
            request: SPARQL update request with query and options
            
        Returns:
            SPARQLUpdateResponse containing update results
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, request=request)
        
        url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/update"
        
        return await self._make_typed_request('POST', url, SPARQLUpdateResponse, params={'space_id': space_id}, json=request.model_dump())
    
    async def execute_sparql_query_get(self, space_id: str, query: str, format: str = "application/sparql-results+json") -> SPARQLQueryResponse:
        """
        Execute a SPARQL query via GET (for simple queries).

        Args:
            space_id: Space identifier
            query: SPARQL query string
            format: Response format (default: application/sparql-results+json)

        Returns:
            SPARQLQueryResponse containing query results

        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, query=query)

        url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/query"
        params = {'space_id': space_id, 'query': query, 'format': format}

        return await self._make_typed_request('GET', url, SPARQLQueryResponse, params=params)

    async def execute_sparql_delete(self, space_id: str, request: SPARQLDeleteRequest) -> SPARQLDeleteResponse:
        """
        Execute a SPARQL delete operation (W3C SPARQL 1.1 Protocol compliant).
        
        Args:
            space_id: Space identifier
            request: SPARQL delete request with query and options
            
        Returns:
            SPARQLDeleteResponse containing delete results
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, request=request)
        
        url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/delete"
        
        return await self._make_typed_request('POST', url, SPARQLDeleteResponse, params={'space_id': space_id}, json=request.model_dump())

    # ------------------------------------------------------------------
    # Form-based endpoints (W3C SPARQL 1.1 Protocol compatibility)
    # ------------------------------------------------------------------

    async def execute_sparql_insert_form(self, space_id: str, update: str, graph_uri: Optional[str] = None) -> SPARQLInsertResponse:
        """
        Execute a SPARQL insert via form-encoded POST.

        Args:
            space_id: Space identifier
            update: SPARQL update string
            graph_uri: Optional target graph URI

        Returns:
            SPARQLInsertResponse containing insert results
        """
        self._check_connection()
        validate_required_params(space_id=space_id, update=update)

        url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/insert-form"
        data = {'update': update}
        if graph_uri:
            data['graph_uri'] = graph_uri

        return await self._make_typed_request('POST', url, SPARQLInsertResponse, params={'space_id': space_id}, data=data)

    async def execute_sparql_delete_form(self, space_id: str, update: str, graph_uri: Optional[str] = None) -> SPARQLDeleteResponse:
        """
        Execute a SPARQL delete via form-encoded POST.

        Args:
            space_id: Space identifier
            update: SPARQL update string
            graph_uri: Optional target graph URI

        Returns:
            SPARQLDeleteResponse containing delete results
        """
        self._check_connection()
        validate_required_params(space_id=space_id, update=update)

        url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/delete-form"
        data = {'update': update}
        if graph_uri:
            data['graph_uri'] = graph_uri

        return await self._make_typed_request('POST', url, SPARQLDeleteResponse, params={'space_id': space_id}, data=data)

    async def execute_sparql_update_form(self, space_id: str, update: str) -> SPARQLUpdateResponse:
        """
        Execute a SPARQL update via form-encoded POST.

        Args:
            space_id: Space identifier
            update: SPARQL update string

        Returns:
            SPARQLUpdateResponse containing update results
        """
        self._check_connection()
        validate_required_params(space_id=space_id, update=update)

        url = f"{self._get_server_url().rstrip('/')}/api/graphs/sparql/update-form"
        data = {'update': update}

        return await self._make_typed_request('POST', url, SPARQLUpdateResponse, params={'space_id': space_id}, data=data)
    
