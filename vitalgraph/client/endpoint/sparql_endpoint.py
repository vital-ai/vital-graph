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
    
