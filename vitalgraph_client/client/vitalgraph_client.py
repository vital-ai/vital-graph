"""VitalGraph Client

REST API client for connecting to VitalGraph servers.
"""

import requests
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

from ..config.client_config_loader import VitalGraphClientConfig, ClientConfigurationError

logger = logging.getLogger(__name__)


class VitalGraphClientError(Exception):
    """Base exception for VitalGraph client errors."""
    pass


class VitalGraphClient:
    """
    VitalGraph REST API client.
    
    Provides functionality to connect to VitalGraph API servers using
    configuration-based authentication and connection management.
    """
    
    def __init__(self, config_path: str):
        """
        Initialize the VitalGraph client.
        
        Args:
            config_path: Path to the client configuration YAML file.
        """
        self.config: Optional[VitalGraphClientConfig] = None
        self.session: Optional[requests.Session] = None
        self.is_open: bool = False
        self.auth_token: Optional[str] = None
        self.auth_data: Optional[Dict[str, Any]] = None
        
        # Load configuration
        try:
            self.config = VitalGraphClientConfig(config_path)
            logger.info(f"VitalGraph client initialized with config: {self.config}")
        except ClientConfigurationError as e:
            logger.error(f"Failed to load client configuration: {e}")
            raise VitalGraphClientError(f"Configuration error: {e}")
    
    def open(self) -> None:
        """
        Open the client connection to the VitalGraph server.
        
        Initializes the HTTP session with authentication and connection settings.
        
        Raises:
            VitalGraphClientError: If the client is already open or connection fails
        """
        if self.is_open:
            logger.warning("Client is already open")
            return
        
        if not self.config:
            raise VitalGraphClientError("No configuration loaded")
        
        try:
            # Create HTTP session
            self.session = requests.Session()
            
            # Set timeout
            timeout = self.config.get_timeout()
            self.session.timeout = timeout
            
            # Set headers
            self.session.headers.update({
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': 'VitalGraph-Client/1.0'
            })
            
            # Authenticate with the server using /api/login
            server_url = self.config.get_server_url()
            api_base_path = self.config.get_api_base_path()
            
            # Perform authentication
            self._authenticate(server_url, api_base_path, timeout)
            
            self.is_open = True
            logger.info("VitalGraph client opened successfully")
            
        except Exception as e:
            logger.error(f"Failed to open VitalGraph client: {e}")
            self._cleanup_session()
            raise VitalGraphClientError(f"Failed to open client: {e}")
    
    def _authenticate(self, server_url: str, api_base_path: str, timeout: int) -> None:
        """
        Authenticate with the VitalGraph server using /api/login endpoint.
        
        Args:
            server_url: The server URL
            api_base_path: The API base path
            timeout: Request timeout
            
        Raises:
            VitalGraphClientError: If authentication fails
        """
        # Get credentials from config
        username, password = self.config.get_credentials()
        
        # Build login URL
        login_url = f"{server_url.rstrip('/')}/api/login"
        
        # Prepare login data as form data (OAuth2PasswordRequestForm format)
        login_data = {
            "username": username,
            "password": password
        }
        
        try:
            logger.info(f"Authenticating with VitalGraph server at {login_url}")
            # Set content type for form data and send authentication request
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            response = self.session.post(login_url, data=login_data, headers=headers, timeout=timeout)
            
            if response.status_code == 200:
                # Authentication successful
                auth_result = response.json()
                self.auth_data = auth_result
                
                # Store authentication token if provided
                if 'token' in auth_result:
                    self.auth_token = auth_result['token']
                    # Add token to session headers for subsequent requests
                    self.session.headers.update({
                        'Authorization': f'Bearer {self.auth_token}'
                    })
                    logger.info("Authentication successful - token stored")
                elif 'access_token' in auth_result:
                    self.auth_token = auth_result['access_token']
                    self.session.headers.update({
                        'Authorization': f'Bearer {self.auth_token}'
                    })
                    logger.info("Authentication successful - access token stored")
                else:
                    logger.info("Authentication successful - no token provided")
                
                logger.info(f"Connected to VitalGraph server at {server_url}")
                
            else:
                # Authentication failed
                error_msg = f"Authentication failed with status {response.status_code}"
                if response.text:
                    try:
                        error_data = response.json()
                        if 'error' in error_data:
                            error_msg += f": {error_data['error']}"
                        elif 'message' in error_data:
                            error_msg += f": {error_data['message']}"
                    except:
                        error_msg += f": {response.text}"
                
                logger.error(error_msg)
                raise VitalGraphClientError(error_msg)
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to connect to authentication endpoint: {e}"
            logger.error(error_msg)
            raise VitalGraphClientError(error_msg)
        except Exception as e:
            error_msg = f"Authentication error: {e}"
            logger.error(error_msg)
            raise VitalGraphClientError(error_msg)
    
    def close(self) -> None:
        """
        Close the client connection.
        
        Cleans up the HTTP session and resets connection state.
        """
        if not self.is_open:
            logger.warning("Client is already closed")
            return
        
        try:
            self._cleanup_session()
            self.is_open = False
            logger.info("VitalGraph client closed successfully")
            
        except Exception as e:
            logger.error(f"Error closing VitalGraph client: {e}")
            # Still mark as closed even if cleanup failed
            self.is_open = False
            raise VitalGraphClientError(f"Error closing client: {e}")
    
    def _cleanup_session(self) -> None:
        """
        Clean up the HTTP session and authentication data.
        """
        if self.session:
            try:
                self.session.close()
            except Exception as e:
                logger.warning(f"Error closing session: {e}")
            finally:
                self.session = None
        
        # Clear authentication data
        self.auth_token = None
        self.auth_data = None
    
    def is_connected(self) -> bool:
        """
        Check if the client is currently connected.
        
        Returns:
            True if the client is open and has an active session
        """
        return self.is_open and self.session is not None
    
    def get_server_info(self) -> Dict[str, Any]:
        """
        Get information about the configured server.
        
        Returns:
            Dictionary containing server configuration information
        """
        if not self.config:
            return {}
        
        return {
            'server_url': self.config.get_server_url(),
            'api_base_path': self.config.get_api_base_path(),
            'timeout': self.config.get_timeout(),
            'max_retries': self.config.get_max_retries(),
            'is_connected': self.is_connected()
        }
    
    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
    
    def __str__(self) -> str:
        """String representation of the client."""
        server_url = self.config.get_server_url() if self.config else "unknown"
        status = "connected" if self.is_connected() else "disconnected"
        return f"VitalGraphClient(server={server_url}, status={status})"
    
    def __repr__(self) -> str:
        """Detailed string representation of the client."""
        return self.__str__()
    
    # Space CRUD Methods
    
    def list_spaces(self, tenant: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all spaces.
        
        Args:
            tenant: Optional tenant filter
            
        Returns:
            List of space dictionaries
            
        Raises:
            VitalGraphClientError: If request fails
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")
        
        try:
            url = f"{self.config.get_server_url().rstrip('/')}/api/spaces"
            params = {}
            if tenant:
                params['tenant'] = tenant
            
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to list spaces: {e}")
    
    def add_space(self, space_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a new space.
        
        Args:
            space_data: Space data dictionary
            
        Returns:
            Created space dictionary
            
        Raises:
            VitalGraphClientError: If request fails
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")
        
        try:
            print(f"➕ CLIENT: Adding new space...")
            print(f"   📤 Space data to send: {space_data}")
            
            url = f"{self.config.get_server_url().rstrip('/')}/api/spaces"
            print(f"   🌐 Sending POST request to: {url}")
            response = self.session.post(url, json=space_data)
            response.raise_for_status()
            
            result = response.json()
            print(f"   📥 Server response: {result}")
            return result
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to add space: {e}")
    
    def get_space(self, space_id: int) -> Dict[str, Any]:
        """
        Get a space by ID.
        
        Args:
            space_id: Space ID
            
        Returns:
            Space dictionary
            
        Raises:
            VitalGraphClientError: If request fails
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")
        
        try:
            url = f"{self.config.get_server_url().rstrip('/')}/api/spaces/{space_id}"
            response = self.session.get(url)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to get space {space_id}: {e}")
    
    def update_space(self, space_id: int, space_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update a space.
        
        Args:
            space_id: Space ID
            space_data: Updated space data dictionary
            
        Returns:
            Updated space dictionary
            
        Raises:
            VitalGraphClientError: If request fails
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")
        
        try:
            # First get the existing space data
            print(f"🔍 CLIENT: Getting existing space {space_id} for update...")
            existing_space = self.get_space(space_id)
            print(f"   📥 Existing space data: {existing_space}")
            
            # Merge the updates with existing data to create complete object
            complete_space_data = existing_space.copy()
            complete_space_data.update(space_data)
            print(f"   📤 Complete space data to send: {complete_space_data}")
            
            # Send complete object - server will ignore id and set update_time itself
            url = f"{self.config.get_server_url().rstrip('/')}/api/spaces/{space_id}"
            print(f"   🌐 Sending PUT request to: {url}")
            response = self.session.put(url, json=complete_space_data)
            response.raise_for_status()
            
            result = response.json()
            print(f"   📥 Server response: {result}")
            return result
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to update space {space_id}: {e}")
    
    def delete_space(self, space_id: int) -> Dict[str, Any]:
        """
        Delete a space.
        
        Args:
            space_id: Space ID
            
        Returns:
            Deletion confirmation dictionary
            
        Raises:
            VitalGraphClientError: If request fails
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")
        
        try:
            url = f"{self.config.get_server_url().rstrip('/')}/api/spaces/{space_id}"
            response = self.session.delete(url)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to delete space {space_id}: {e}")
    
    def filter_spaces(self, name_filter: str, tenant: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Filter spaces by name.
        
        Args:
            name_filter: Name filter string
            tenant: Optional tenant filter
            
        Returns:
            List of filtered space dictionaries
            
        Raises:
            VitalGraphClientError: If request fails
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")
        
        try:
            url = f"{self.config.get_server_url().rstrip('/')}/api/spaces/filter/{name_filter}"
            params = {}
            if tenant:
                params['tenant'] = tenant
            
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to filter spaces: {e}")
    
    # User CRUD Methods
    
    def list_users(self, tenant: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all users.
        
        Args:
            tenant: Optional tenant filter
            
        Returns:
            List of user dictionaries (passwords excluded)
            
        Raises:
            VitalGraphClientError: If request fails
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")
        
        try:
            url = f"{self.config.get_server_url().rstrip('/')}/api/users"
            params = {}
            if tenant:
                params['tenant'] = tenant
            
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to list users: {e}")
    
    def add_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a new user.
        
        Args:
            user_data: User data dictionary
            
        Returns:
            Created user dictionary (password excluded)
            
        Raises:
            VitalGraphClientError: If request fails
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")
        
        try:
            url = f"{self.config.get_server_url().rstrip('/')}/api/users"
            response = self.session.post(url, json=user_data)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to add user: {e}")
    
    def get_user(self, user_id: int) -> Dict[str, Any]:
        """
        Get a user by ID.
        
        Args:
            user_id: User ID
            
        Returns:
            User dictionary (password excluded)
            
        Raises:
            VitalGraphClientError: If request fails
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")
        
        try:
            url = f"{self.config.get_server_url().rstrip('/')}/api/users/{user_id}"
            response = self.session.get(url)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to get user {user_id}: {e}")
    
    def update_user(self, user_id: int, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update a user.
        
        Args:
            user_id: User ID
            user_data: Updated user data dictionary
            
        Returns:
            Updated user dictionary (password excluded)
            
        Raises:
            VitalGraphClientError: If request fails
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")
        
        try:
            url = f"{self.config.get_server_url().rstrip('/')}/api/users/{user_id}"
            response = self.session.put(url, json=user_data)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to update user {user_id}: {e}")
    
    def delete_user(self, user_id: int) -> Dict[str, Any]:
        """
        Delete a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Deletion confirmation dictionary
            
        Raises:
            VitalGraphClientError: If request fails
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")
        
        try:
            url = f"{self.config.get_server_url().rstrip('/')}/api/users/{user_id}"
            response = self.session.delete(url)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to delete user {user_id}: {e}")
    
    def filter_users(self, name_filter: str, tenant: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Filter users by name.
        
        Args:
            name_filter: Name filter string
            tenant: Optional tenant filter
            
        Returns:
            List of filtered user dictionaries (passwords excluded)
            
        Raises:
            VitalGraphClientError: If request fails
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")
        
        try:
            url = f"{self.config.get_server_url().rstrip('/')}/api/users/filter/{name_filter}"
            params = {}
            if tenant:
                params['tenant'] = tenant
            
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to filter users: {e}")
