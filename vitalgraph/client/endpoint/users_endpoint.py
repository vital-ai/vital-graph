"""
VitalGraph Client Users Endpoint

Client-side implementation for Users operations.
"""

import httpx
from typing import Dict, Any, Optional, List

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.users_model import (
    User, UsersListResponse, UserCreateResponse, UserUpdateResponse, UserDeleteResponse
)


class UsersEndpoint(BaseEndpoint):
    """Client endpoint for Users operations."""
    
    async def list_users(self, tenant: Optional[str] = None) -> UsersListResponse:
        """
        List all users.
        
        Args:
            tenant: Optional tenant filter
            
        Returns:
            UsersListResponse containing users data
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        
        url = f"{self._get_server_url().rstrip('/')}/api/users"
        params = build_query_params(tenant=tenant)
        
        return await self._make_typed_request('GET', url, UsersListResponse, params=params)
    
    async def add_user(self, user: User) -> UserCreateResponse:
        """
        Add a new user.
        
        Args:
            user: User object with user data
            
        Returns:
            UserCreateResponse containing creation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(user=user)
        
        url = f"{self._get_server_url().rstrip('/')}/api/users"
        
        return await self._make_typed_request('POST', url, UserCreateResponse, json=user.model_dump())
    
    async def get_user(self, user_id: str) -> User:
        """
        Get a user by ID.
        
        Args:
            user_id: User ID
            
        Returns:
            User object (password excluded)
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(user_id=user_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/users/{user_id}"
        
        return await self._make_typed_request('GET', url, User)
    
    async def update_user(self, user_id: str, user: User) -> UserUpdateResponse:
        """
        Update a user.
        
        Args:
            user_id: User ID
            user: Updated user object
            
        Returns:
            UserUpdateResponse containing update result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(user_id=user_id, user=user)
        
        url = f"{self._get_server_url().rstrip('/')}/api/users/{user_id}"
        
        return await self._make_typed_request('PUT', url, UserUpdateResponse, json=user.model_dump())
    
    async def delete_user(self, user_id: str) -> UserDeleteResponse:
        """
        Delete a user.
        
        Args:
            user_id: User ID
            
        Returns:
            UserDeleteResponse containing deletion result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(user_id=user_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/users/{user_id}"
        
        return await self._make_typed_request('DELETE', url, UserDeleteResponse)
    
    async def filter_users(self, name_filter: str, tenant: Optional[str] = None) -> UsersListResponse:
        """
        Filter users by name.
        
        Args:
            name_filter: Name filter string
            tenant: Optional tenant filter
            
        Returns:
            UsersListResponse containing filtered users
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(name_filter=name_filter)
        
        url = f"{self._get_server_url().rstrip('/')}/api/users/filter/{name_filter}"
        params = build_query_params(tenant=tenant)
        
        return await self._make_typed_request('GET', url, UsersListResponse, params=params)
