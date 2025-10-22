"""
VitalGraph Client Base Endpoint

Base class for all VitalGraph client endpoint implementations.
"""

import requests
from typing import Dict, Any, Optional, TypeVar, Type

from pydantic import BaseModel
from ..utils.client_utils import VitalGraphClientError

T = TypeVar('T', bound=BaseModel)


class BaseEndpoint:
    """Base class for VitalGraph client endpoints."""
    
    def __init__(self, client):
        """
        Initialize the endpoint with a reference to the main client.
        
        Args:
            client: The main VitalGraphClient instance
        """
        self.client = client
    
    def _make_authenticated_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """
        Make an authenticated request using the main client's method.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            url: Request URL
            **kwargs: Additional request parameters
            
        Returns:
            Response object
            
        Raises:
            VitalGraphClientError: If request fails
        """
        return self.client._make_authenticated_request(method, url, **kwargs)
    
    def _check_connection(self):
        """Check if the client is connected."""
        if not self.client.is_connected():
            raise VitalGraphClientError("Client is not connected")
    
    def _get_server_url(self) -> str:
        """Get the server URL from the client config."""
        return self.client.config.get_server_url()
    
    def _parse_response(self, response_data: Dict[str, Any], model_class: Type[T]) -> T:
        """
        Parse response data into a Pydantic model.
        
        Args:
            response_data: Raw response data from JSON
            model_class: Pydantic model class to parse into
            
        Returns:
            Parsed Pydantic model instance
            
        Raises:
            VitalGraphClientError: If parsing fails
        """
        try:
            return model_class.model_validate(response_data)
        except Exception as e:
            raise VitalGraphClientError(f"Failed to parse response into {model_class.__name__}: {e}")
    
    def _make_typed_request(self, method: str, url: str, response_model: Type[T], **kwargs) -> T:
        """
        Make a request and return a typed Pydantic model response.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            url: Request URL
            response_model: Pydantic model class for response parsing
            **kwargs: Additional request parameters
            
        Returns:
            Parsed Pydantic model instance
            
        Raises:
            VitalGraphClientError: If request or parsing fails
        """
        response = self._make_authenticated_request(method, url, **kwargs)
        return self._parse_response(response.json(), response_model)