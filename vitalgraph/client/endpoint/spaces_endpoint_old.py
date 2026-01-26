"""
VitalGraph Client Spaces Endpoint

Client-side implementation for Spaces operations.
"""

import requests
from typing import Dict, Any, Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.spaces_model import (
    Space, SpacesListResponse, SpaceCreateResponse, SpaceUpdateResponse, SpaceDeleteResponse
)
from typing import List


class SpacesEndpoint(BaseEndpoint):
    """Client endpoint for Spaces operations."""
    
    def list_spaces(self, tenant: Optional[str] = None) -> SpacesListResponse:
        """
        List all spaces.
        
        Args:
            tenant: Optional tenant filter
            
        Returns:
            SpacesListResponse containing spaces data
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        
        url = f"{self._get_server_url().rstrip('/')}/api/spaces"
        params = build_query_params(tenant=tenant)
        
        return self._make_typed_request('GET', url, SpacesListResponse, params=params)
    
    def add_space(self, space: Space) -> SpaceCreateResponse:
        """
        Add a new space.
        
        Args:
            space: Space object with space data
            
        Returns:
            SpaceCreateResponse containing creation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space=space)
        
        url = f"{self._get_server_url().rstrip('/')}/api/spaces"
        
        return self._make_typed_request('POST', url, SpaceCreateResponse, json=space.model_dump())
    
    def get_space(self, space_id: str) -> Space:
        """
        Get a space by ID.
        
        Args:
            space_id: Space ID
            
        Returns:
            Space model
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/spaces/{space_id}"
        
        return self._make_typed_request('GET', url, Space)
    
    def get_space_info(self, space_id: str) -> Dict[str, Any]:
        """
        Get detailed space information including statistics and quad dumps.
        
        Args:
            space_id: Space ID
            
        Returns:
            Dict containing space info, statistics, and quad logging if enabled
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/spaces/{space_id}/info"
        
        response = requests.get(url, headers=self._get_headers())
        
        if response.status_code != 200:
            raise VitalGraphClientError(
                f"Failed to get space info: {response.status_code} - {response.text}"
            )
        
        return response.json()
    
    def update_space(self, space_id: str, space: Space) -> SpaceUpdateResponse:
        """
        Update a space.
        
        Args:
            space_id: Space ID
            space: Updated space object
            
        Returns:
            SpaceUpdateResponse containing update result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, space=space)
        
        url = f"{self._get_server_url().rstrip('/')}/api/spaces/{space_id}"
        
        return self._make_typed_request('PUT', url, SpaceUpdateResponse, json=space.model_dump())
    
    def delete_space(self, space_id: str) -> SpaceDeleteResponse:
        """
        Delete a space.
        
        Args:
            space_id: Space ID
            
        Returns:
            SpaceDeleteResponse containing deletion result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/spaces/{space_id}"
        
        return self._make_typed_request('DELETE', url, SpaceDeleteResponse)
    
    def filter_spaces(self, name_filter: str, tenant: Optional[str] = None) -> SpacesListResponse:
        """
        Filter spaces by name.
        
        Args:
            name_filter: Name filter string
            tenant: Optional tenant filter
            
        Returns:
            SpacesListResponse containing filtered spaces
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(name_filter=name_filter)
        
        url = f"{self._get_server_url().rstrip('/')}/api/spaces/filter/{name_filter}"
        params = build_query_params(tenant=tenant)
        
        return self._make_typed_request('GET', url, SpacesListResponse, params=params)
