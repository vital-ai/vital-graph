"""VitalGraph Client

REST API client for connecting to VitalGraph servers with JWT authentication.
"""

import httpx
import logging
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Union
from pathlib import Path

from .config.client_config_loader import VitalGraphClientConfig, ClientConfigurationError
from .endpoint.kgtypes_endpoint import KGTypesEndpoint
from .endpoint.kgframes_endpoint import KGFramesEndpoint
from .endpoint.kgentities_endpoint import KGEntitiesEndpoint
from .endpoint.kgrelations_endpoint import KGRelationsEndpoint
from .endpoint.kgqueries_endpoint import KGQueriesEndpoint
from .endpoint.objects_endpoint import ObjectsEndpoint
from .endpoint.files_endpoint import FilesEndpoint
from .endpoint.spaces_endpoint import SpacesEndpoint
from .endpoint.users_endpoint import UsersEndpoint
from .endpoint.sparql_endpoint import SparqlEndpoint
from .endpoint.graphs_endpoint import GraphsEndpoint
from .endpoint.triples_endpoint import TriplesEndpoint
from .endpoint.import_endpoint import ImportEndpoint
from .endpoint.export_endpoint import ExportEndpoint
from .utils.client_utils import VitalGraphClientError
from .vitalgraph_client_inf import VitalGraphClientInterface
from ..model.sparql_model import GraphInfo, SPARQLGraphResponse

logger = logging.getLogger(__name__)


class VitalGraphClient(VitalGraphClientInterface):
    """
    VitalGraph REST API client with JWT authentication.
    
    Provides functionality to connect to VitalGraph API servers using
    JWT-based authentication with automatic token refresh and connection management.
    """
    
    def __init__(self, *, config: Optional[VitalGraphClientConfig] = None, 
                 token_expiry_seconds: Optional[int] = None,
                 disable_proactive_refresh: bool = False):
        """
        Initialize the VitalGraph client.
        
        Configuration is loaded from profile-prefixed environment variables.
        Set VITALGRAPH_CLIENT_ENVIRONMENT to select profile (local, dev, staging, prod).
        
        Args:
            config: Pre-configured VitalGraphClientConfig object (optional, for testing)
            token_expiry_seconds: Optional token expiry override in seconds for testing (max 1800 = 30 min)
            disable_proactive_refresh: If True, skip proactive token refresh to test reactive 401 retry (testing only)
        
        Environment Variables (profile-prefixed):
            {PROFILE}_CLIENT_SERVER_URL: Server endpoint URL
            {PROFILE}_CLIENT_AUTH_USERNAME: Authentication username
            {PROFILE}_CLIENT_AUTH_PASSWORD: Authentication password
            {PROFILE}_CLIENT_TIMEOUT: Request timeout in seconds
            {PROFILE}_CLIENT_MAX_RETRIES: Maximum retry attempts
            
        Example:
            # Use LOCAL profile
            export VITALGRAPH_CLIENT_ENVIRONMENT=local
            export LOCAL_CLIENT_SERVER_URL=http://localhost:8001
            export LOCAL_CLIENT_AUTH_USERNAME=admin
            export LOCAL_CLIENT_AUTH_PASSWORD=admin
            client = VitalGraphClient()
            
            # Use PROD profile
            export VITALGRAPH_CLIENT_ENVIRONMENT=prod
            export PROD_CLIENT_SERVER_URL=https://api.production.com
            client = VitalGraphClient()
        """
        self.config: Optional[VitalGraphClientConfig] = None
        self.async_session: Optional[httpx.AsyncClient] = None
        self.is_open: bool = False
        
        # JWT Authentication data
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self.auth_data: Optional[Dict[str, Any]] = None
        self.token_expiry_seconds: Optional[int] = token_expiry_seconds
        self.disable_proactive_refresh: bool = disable_proactive_refresh
        
        # Load configuration from environment variables or provided config object
        try:
            if config is not None:
                # Use provided config object (for testing)
                self.config = config
                logger.info(f"VitalGraph client initialized with provided config object: {self.config}")
            else:
                # Load from environment variables
                self.config = VitalGraphClientConfig()
                logger.info(f"VitalGraph client initialized with environment variable config: {self.config}")
        except ClientConfigurationError as e:
            logger.error(f"Failed to load client configuration: {e}")
            raise VitalGraphClientError(f"Configuration error: {e}")
        
        # Initialize endpoint handlers
        self.kgtypes = KGTypesEndpoint(self)
        self.kgframes = KGFramesEndpoint(self)
        self.kgentities = KGEntitiesEndpoint(self)
        self.kgrelations = KGRelationsEndpoint(self)
        self.kgqueries = KGQueriesEndpoint(self)
        self.objects = ObjectsEndpoint(self)
        self.files = FilesEndpoint(self)
        self.spaces = SpacesEndpoint(self)
        self.users = UsersEndpoint(self)
        self.sparql = SparqlEndpoint(self)
        self.graphs = GraphsEndpoint(self)
        self.triples = TriplesEndpoint(self)
        self.imports = ImportEndpoint(self)
        self.exports = ExportEndpoint(self)
    
    async def open(self) -> None:
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
            # Create async HTTP session
            timeout = self.config.get_timeout()
            headers = {
                'Accept': 'application/json',
                'User-Agent': 'VitalGraph-Client/1.0'
            }
            
            self.async_session = httpx.AsyncClient(
                timeout=timeout,
                headers=headers,
                follow_redirects=True
            )
            
            # Authenticate with the server using /api/login
            server_url = self.config.get_server_url()
            api_base_path = self.config.get_api_base_path()
            
            # Perform authentication
            await self._authenticate(server_url, api_base_path, timeout)
            
            self.is_open = True
            logger.info("VitalGraph client opened successfully")
            
        except Exception as e:
            logger.error(f"Failed to open VitalGraph client: {e}")
            await self._cleanup_session()
            raise VitalGraphClientError(f"Failed to open client: {e}")
    
    async def _authenticate(self, server_url: str, api_base_path: str, timeout: int) -> None:
        """
        Authenticate with the VitalGraph server using JWT authentication via /api/login endpoint.
        
        Args:
            server_url: The server URL
            api_base_path: The API base path
            timeout: Request timeout
            
        Raises:
            VitalGraphClientError: If JWT authentication fails
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
        
        # Add optional token_expiry_seconds if provided (for testing)
        if self.token_expiry_seconds is not None:
            login_data["token_expiry_seconds"] = self.token_expiry_seconds
            logger.info(f"Requesting custom token expiry: {self.token_expiry_seconds} seconds")
        
        try:
            logger.info(f"Authenticating with VitalGraph server at {login_url}")
            # Set content type for form data and send authentication request
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            response = await self.async_session.post(login_url, data=login_data, headers=headers)
            
            if response.status_code == 200:
                # Authentication successful - parse JWT response
                auth_result = response.json()
                self.auth_data = auth_result
                
                # Store JWT tokens (JWT-only, no backward compatibility)
                if 'access_token' in auth_result:
                    self.access_token = auth_result['access_token']
                    self.refresh_token = auth_result.get('refresh_token')
                    
                    # Calculate token expiry time
                    expires_in = auth_result.get('expires_in', 1800)  # Default 30 minutes
                    self.token_expiry = datetime.now() + timedelta(seconds=expires_in)
                    
                    # Add access token to session headers
                    auth_header = {'Authorization': f'Bearer {self.access_token}'}
                    self.async_session.headers.update(auth_header)
                    
                    logger.info("JWT authentication successful")
                    logger.info(f"Access token expires in {expires_in} seconds")
                    if self.refresh_token:
                        logger.info("Refresh token stored for automatic renewal")
                    else:
                        logger.warning("No refresh token provided - manual re-authentication will be required on expiry")
                    
                else:
                    raise VitalGraphClientError("Server response missing required 'access_token' field - JWT authentication required")
                
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
                
        except httpx.HTTPError as e:
            error_msg = f"Failed to connect to authentication endpoint: {e}"
            logger.error(error_msg)
            raise VitalGraphClientError(error_msg)
        except Exception as e:
            error_msg = f"Authentication error: {e}"
            logger.error(error_msg)
            raise VitalGraphClientError(error_msg)
    
    async def _reauthenticate(self) -> None:
        """
        Re-authenticate with the server using stored credentials.
        Fallback method when refresh token is not available.
        
        Raises:
            VitalGraphClientError: If re-authentication fails
        """
        try:
            logger.info("Re-authenticating with server (no refresh token available)...")
            
            server_url = self.config.get_server_url()
            api_base_path = self.config.get_api_base_path()
            timeout = self.config.get_timeout()
            
            # Call existing authenticate method
            await self._authenticate(server_url, api_base_path, timeout)
            
            logger.info("Re-authentication successful")
            
        except Exception as e:
            logger.error(f"Re-authentication failed: {e}")
            raise VitalGraphClientError(f"Failed to re-authenticate: {e}")
    
    async def close(self) -> None:
        """
        Close the client connection.
        
        Cleans up the HTTP session and resets connection state.
        """
        if not self.is_open:
            logger.warning("Client is already closed")
            return
        
        try:
            await self._cleanup_session()
            self.is_open = False
            logger.info("VitalGraph client closed successfully")
            
        except Exception as e:
            logger.error(f"Error closing VitalGraph client: {e}")
            # Still mark as closed even if cleanup failed
            self.is_open = False
            raise VitalGraphClientError(f"Error closing client: {e}")
    
    async def _cleanup_session(self) -> None:
        """
        Clean up the HTTP session and authentication data.
        """
        if self.async_session:
            try:
                await self.async_session.aclose()
            except Exception as e:
                logger.warning(f"Error closing async session: {e}")
            finally:
                self.async_session = None
        
        # Clear JWT authentication data
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None
        self.auth_data = None
    
    def is_connected(self) -> bool:
        """
        Check if the client is currently connected.
        
        Returns:
            True if the client is open and has an active session
        """
        return self.is_open and self.async_session is not None
    
    def _is_token_expired(self) -> bool:
        """
        Check if the current access token is expired or will expire soon.
        
        Returns:
            True if token is expired or will expire soon (with proportional buffer)
        """
        if not self.token_expiry:
            logger.debug("Token expiry not set - considering token expired")
            return True
        
        # Use proportional buffer: 10% of token lifetime or 5 minutes, whichever is smaller
        # This allows short-lived test tokens to work properly
        now = datetime.now()
        time_until_expiry = (self.token_expiry - now).total_seconds()
        
        logger.debug(f"Token expiry check: expires at {self.token_expiry}, time until expiry: {time_until_expiry:.1f}s")
        
        # For very short tokens (< 60 seconds), use 10% buffer
        # For longer tokens, use up to 5 minutes (300 seconds)
        if time_until_expiry > 0:
            # Calculate 10% of original token lifetime
            # Estimate original lifetime from current remaining time
            buffer_seconds = min(300, max(5, time_until_expiry * 0.1))
            is_expired = time_until_expiry <= buffer_seconds
            logger.debug(f"Token buffer: {buffer_seconds:.1f}s, expired: {is_expired}")
            return is_expired
        else:
            # Already expired
            logger.debug(f"Token already expired by {abs(time_until_expiry):.1f}s")
            return True
    
    async def _refresh_access_token(self) -> bool:
        """
        Refresh the access token using the refresh token.
        
        Returns:
            True if refresh was successful, False otherwise
        """
        if not self.refresh_token or not self.async_session:
            logger.warning("Cannot refresh token: no refresh token or session available")
            return False
        
        try:
            logger.info("Refreshing access token...")
            
            # Build refresh URL
            server_url = self.config.get_server_url()
            refresh_url = f"{server_url.rstrip('/')}/api/refresh"
            
            # Send refresh request with refresh token as Bearer token
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.refresh_token}'
            }
            
            refresh_data = {"refresh_token": self.refresh_token}
            response = await self.async_session.post(refresh_url, json=refresh_data, headers=headers)
            
            if response.status_code == 200:
                # Refresh successful
                refresh_result = response.json()
                
                if 'access_token' in refresh_result:
                    self.access_token = refresh_result['access_token']
                    
                    # Update token expiry
                    expires_in = refresh_result.get('expires_in', 1800)
                    self.token_expiry = datetime.now() + timedelta(seconds=expires_in)
                    
                    # Update session headers with new access token
                    auth_header = {'Authorization': f'Bearer {self.access_token}'}
                    self.async_session.headers.update(auth_header)
                    
                    logger.info("Access token refreshed successfully")
                    logger.info(f"New token expires in {expires_in} seconds")
                    return True
                else:
                    logger.error("Refresh response missing access_token")
                    return False
            else:
                logger.error(f"Token refresh failed with status {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error refreshing access token: {e}")
            return False
    
    async def _ensure_valid_token(self) -> None:
        """
        Ensure we have a valid access token, refreshing if necessary.
        
        Raises:
            VitalGraphClientError: If token refresh fails
        """
        if not self.access_token:
            raise VitalGraphClientError("No access token available")
        
        if self._is_token_expired():
            logger.info("Access token expired or expiring soon, attempting refresh...")
            
            if not await self._refresh_access_token():
                raise VitalGraphClientError("Failed to refresh access token - please re-authenticate")
    
    # Transient connection errors worth retrying
    _RETRYABLE_EXCEPTIONS = (
        httpx.ConnectError,
        httpx.RemoteProtocolError,
        httpx.ReadError,
        httpx.WriteError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        ConnectionResetError,
    )

    async def _make_authenticated_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """
        Make an authenticated async request with automatic token refresh
        and retry on transient connection errors.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            url: Request URL
            **kwargs: Additional request parameters
            
        Returns:
            Response object
            
        Raises:
            VitalGraphClientError: If request fails after all retries
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")
        
        max_retries = self.config.get_max_retries() if self.config else 3
        retry_delay = self.config.get_retry_delay() if self.config else 1
        last_exception = None

        for attempt in range(max_retries + 1):
            # Proactive: Ensure we have a valid access token (unless disabled for testing)
            if not self.disable_proactive_refresh:
                await self._ensure_valid_token()
            
            try:
                response = await self.async_session.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                # Reactive: Handle 401 Unauthorized with token refresh and retry
                if e.response.status_code == 401:
                    logger.warning("Received 401 Unauthorized - attempting token refresh and retry")
                    
                    # Determine authentication mode and handle accordingly
                    if self.refresh_token:
                        logger.info("Attempting token refresh with refresh token")
                        if not await self._refresh_access_token():
                            raise VitalGraphClientError("Token refresh failed after 401 - please re-authenticate")
                    else:
                        logger.info("No refresh token available - re-authenticating with credentials")
                        await self._reauthenticate()
                    
                    # Retry the request ONCE with new token
                    logger.info("Retrying request with refreshed token")
                    try:
                        response = await self.async_session.request(method, url, **kwargs)
                        response.raise_for_status()
                        return response
                    except httpx.HTTPError as retry_error:
                        raise VitalGraphClientError(f"Request failed after token refresh: {retry_error}")
                elif e.response.status_code in (502, 503, 504):
                    # Transient server errors — retry
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"⚠️ HTTP {e.response.status_code} on {method} {url} "
                            f"(attempt {attempt + 1}/{max_retries + 1}) — retrying in {retry_delay}s"
                        )
                        await asyncio.sleep(retry_delay)
                        continue
                    raise VitalGraphClientError(f"Request failed after {max_retries + 1} attempts: {e}")
                else:
                    # Not a retryable error
                    raise VitalGraphClientError(f"Request failed: {e}")
            except self._RETRYABLE_EXCEPTIONS as e:
                # Transient connection errors — retry
                last_exception = e
                if attempt < max_retries:
                    logger.warning(
                        f"⚠️ Connection error on {method} {url}: {type(e).__name__}: {e} "
                        f"(attempt {attempt + 1}/{max_retries + 1}) — retrying in {retry_delay}s"
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                raise VitalGraphClientError(
                    f"Request failed after {max_retries + 1} attempts: {e}"
                )
            except httpx.HTTPError as e:
                # Non-retryable HTTP error
                raise VitalGraphClientError(f"Request failed: {e}")
        
        # Should not reach here, but safety net
        raise VitalGraphClientError(f"Request failed after {max_retries + 1} attempts: {last_exception}")
    
    def get_server_info(self) -> Dict[str, Any]:
        """
        Get information about the configured server.
        
        Returns:
            Dictionary containing server configuration information
        """
        if not self.config:
            return {}
        
        auth_info = {}
        if self.access_token:
            auth_info['has_access_token'] = True
            auth_info['has_refresh_token'] = bool(self.refresh_token)
            if self.token_expiry:
                auth_info['token_expires_at'] = self.token_expiry.isoformat()
                auth_info['token_expired'] = self._is_token_expired()
        else:
            auth_info['has_access_token'] = False
        
        return {
            'server_url': self.config.get_server_url(),
            'api_base_path': self.config.get_api_base_path(),
            'timeout': self.config.get_timeout(),
            'max_retries': self.config.get_max_retries(),
            'is_connected': self.is_connected(),
            'authentication': auth_info
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.open()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    def __str__(self) -> str:
        """String representation of the client."""
        server_url = self.config.get_server_url() if self.config else "unknown"
        status = "connected" if self.is_connected() else "disconnected"
        return f"VitalGraphClient(server={server_url}, status={status})"
    
    def __repr__(self) -> str:
        """Detailed string representation of the client."""
        return self.__str__()
    
    # Space CRUD Methods - Delegated to SpacesEndpoint
    
    async def list_spaces(self, tenant: Optional[str] = None) -> 'SpacesListResponse':
        """
        List all spaces.
        
        Args:
            tenant: Optional tenant filter
            
        Returns:
            SpacesListResponse containing spaces and pagination info
        """
        return await self.spaces.list_spaces(tenant)
    
    async def add_space(self, space: 'Space') -> 'SpaceCreateResponse':
        """
        Add a new space.
        
        Args:
            space: Space object with space data
            
        Returns:
            SpaceCreateResponse containing creation result
        """
        return await self.spaces.add_space(space)
    
    async def get_space(self, space_id: str) -> 'Space':
        """
        Get a space by ID.
        
        Args:
            space_id: Space ID
            
        Returns:
            Space model
        """
        return await self.spaces.get_space(space_id)
    
    async def update_space(self, space_id: str, space: 'Space') -> 'SpaceUpdateResponse':
        """
        Update a space.
        
        Args:
            space_id: Space ID
            space: Space object with updated data
            
        Returns:
            SpaceUpdateResponse containing update result
        """
        return await self.spaces.update_space(space_id, space)
    
    async def delete_space(self, space_id: str) -> 'SpaceDeleteResponse':
        """
        Delete a space.
        
        Args:
            space_id: Space ID
            
        Returns:
            SpaceDeleteResponse containing deletion result
        """
        return await self.spaces.delete_space(space_id)
    
    async def filter_spaces(self, name_filter: str, tenant: Optional[str] = None) -> 'SpacesListResponse':
        """
        Filter spaces by name.
        
        Args:
            name_filter: Name filter string
            tenant: Optional tenant filter
            
        Returns:
            SpacesListResponse containing filtered spaces
        """
        return await self.spaces.filter_spaces(name_filter, tenant)
    
    # User CRUD Methods - Delegated to UsersEndpoint
    
    async def list_users(self, tenant: Optional[str] = None) -> 'UsersListResponse':
        """
        List all users.
        
        Args:
            tenant: Optional tenant filter
            
        Returns:
            UsersListResponse containing users and pagination info
        """
        return await self.users.list_users(tenant)
    
    async def add_user(self, user: 'User') -> 'UserCreateResponse':
        """
        Add a new user.
        
        Args:
            user: User object with user data
            
        Returns:
            UserCreateResponse containing creation result
        """
        return await self.users.add_user(user)
    
    async def get_user(self, user_id: str) -> 'User':
        """
        Get a user by ID.
        
        Args:
            user_id: User ID
            
        Returns:
            User model
        """
        return await self.users.get_user(user_id)
    
    async def update_user(self, user_id: str, user: 'User') -> 'UserUpdateResponse':
        """
        Update a user.
        
        Args:
            user_id: User ID
            user: User object with updated data
            
        Returns:
            UserUpdateResponse containing update result
        """
        return await self.users.update_user(user_id, user)
    
    async def delete_user(self, user_id: str) -> 'UserDeleteResponse':
        """
        Delete a user.
        
        Args:
            user_id: User ID
            
        Returns:
            UserDeleteResponse containing deletion result
        """
        return await self.users.delete_user(user_id)
    
    async def filter_users(self, name_filter: str, tenant: Optional[str] = None) -> 'UsersListResponse':
        """
        Filter users by name.
        
        Args:
            name_filter: Name filter string
            tenant: Optional tenant filter
            
        Returns:
            UsersListResponse containing filtered users
        """
        return await self.users.filter_users(name_filter, tenant)
    
    # SPARQL Methods - Delegated to SparqlEndpoint
    
    async def execute_sparql_query(self, space_id: str, request: 'SPARQLQueryRequest') -> 'SPARQLQueryResponse':
        """
        Execute a SPARQL query.
        
        Args:
            space_id: Space identifier
            request: SPARQL query request object
            
        Returns:
            SPARQLQueryResponse containing query results
        """
        return await self.sparql.execute_sparql_query(space_id, request)
    
    async def execute_sparql_insert(self, space_id: str, request: 'SPARQLInsertRequest') -> 'SPARQLInsertResponse':
        """
        Execute a SPARQL insert operation (W3C SPARQL 1.1 Protocol compliant).
        
        Args:
            space_id: Space identifier
            request: SPARQL insert request object
            
        Returns:
            SPARQLInsertResponse containing insert results
        """
        return await self.sparql.execute_sparql_insert(space_id, request)
    
    async def execute_sparql_update(self, space_id: str, request: 'SPARQLUpdateRequest') -> 'SPARQLUpdateResponse':
        """
        Execute a SPARQL update operation (W3C SPARQL 1.1 Protocol compliant).
        
        Args:
            space_id: Space identifier
            request: SPARQL update request object
            
        Returns:
            SPARQLUpdateResponse containing update results
        """
        return await self.sparql.execute_sparql_update(space_id, request)
    
    async def execute_sparql_delete(self, space_id: str, request: 'SPARQLDeleteRequest') -> 'SPARQLDeleteResponse':
        """
        Execute a SPARQL delete operation (W3C SPARQL 1.1 Protocol compliant).
        
        Args:
            space_id: Space identifier
            request: SPARQL delete request object
            
        Returns:
            SPARQLDeleteResponse containing delete results
        """
        return await self.sparql.execute_sparql_delete(space_id, request)
    
    # KGType CRUD Methods - Delegated to KGTypesEndpoint
    
    async def list_kgtypes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> 'KGTypeListResponse':
        """
        List KGTypes with pagination and optional search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            KGTypeListResponse containing KGTypes data and pagination info
        """
        return await self.kgtypes.list_kgtypes(space_id, graph_id, page_size, offset, search)
    
    async def get_kgtype(self, space_id: str, graph_id: str, uri: str) -> 'KGTypeListResponse':
        """
        Get a specific KGType by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGType URI
            
        Returns:
            KGTypeListResponse containing KGType data
        """
        return await self.kgtypes.get_kgtype(space_id, graph_id, uri)
    
    async def create_kgtypes(self, space_id: str, graph_id: str, data: 'Union[JsonLdObject, JsonLdDocument]') -> 'KGTypeCreateResponse':
        """
        Create KGTypes from JSON-LD data.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            data: JSON-LD data - either single object or document with @graph array
            
        Returns:
            KGTypeCreateResponse containing operation result
        """
        return await self.kgtypes.create_kgtypes(space_id, graph_id, data)
    
    async def update_kgtypes(self, space_id: str, graph_id: str, data: 'Union[JsonLdObject, JsonLdDocument]') -> 'KGTypeUpdateResponse':
        """
        Update KGTypes from JSON-LD data.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            data: JSON-LD data - either single object or document with @graph array
            
        Returns:
            KGTypeUpdateResponse containing operation result
        """
        return await self.kgtypes.update_kgtypes(space_id, graph_id, data)
    
    async def delete_kgtype(self, space_id: str, graph_id: str, uri: str) -> 'KGTypeDeleteResponse':
        """
        Delete a KGType by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGType URI to delete
            
        Returns:
            KGTypeDeleteResponse containing operation result
        """
        return await self.kgtypes.delete_kgtype(space_id, graph_id, uri)
    
    async def delete_kgtypes_batch(self, space_id: str, graph_id: str, uri_list: str) -> 'KGTypeDeleteResponse':
        """
        Delete multiple KGTypes by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGType URIs
            
        Returns:
            KGTypeDeleteResponse containing operation result
        """
        return await self.kgtypes.delete_kgtypes_batch(space_id, graph_id, uri_list)
    
    # KGFrame CRUD Methods - Delegated to KGFramesEndpoint
    
    async def list_kgframes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> 'FramesResponse':
        """
        List KGFrames with pagination and optional search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            FramesResponse containing KGFrames data and pagination info
        """
        return await self.kgframes.list_kgframes(space_id, graph_id, page_size, offset, search)
    
    async def get_kgframe(self, space_id: str, graph_id: str, uri: str) -> 'FramesResponse':
        """
        Get a specific KGFrame by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGFrame URI
            
        Returns:
            FramesResponse containing KGFrame data
        """
        return await self.kgframes.get_kgframe(space_id, graph_id, uri)
    
    async def create_kgframes(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'FrameCreateResponse':
        """
        Create KGFrames from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGFrames
            
        Returns:
            FrameCreateResponse containing operation result
        """
        return await self.kgframes.create_kgframes(space_id, graph_id, document)
    
    async def update_kgframes(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'FrameUpdateResponse':
        """
        Update KGFrames from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGFrames
            
        Returns:
            FrameUpdateResponse containing operation result
        """
        return await self.kgframes.update_kgframes(space_id, graph_id, document)
    
    async def delete_kgframe(self, space_id: str, graph_id: str, uri: str) -> 'FrameDeleteResponse':
        """
        Delete a KGFrame by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGFrame URI to delete
            
        Returns:
            FrameDeleteResponse containing operation result
        """
        return await self.kgframes.delete_kgframe(space_id, graph_id, uri)
    
    async def delete_kgframes_batch(self, space_id: str, graph_id: str, uri_list: str) -> 'FrameDeleteResponse':
        """
        Delete multiple KGFrames by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGFrame URIs
            
        Returns:
            FrameDeleteResponse containing operation result
        """
        return await self.kgframes.delete_kgframes_batch(space_id, graph_id, uri_list)
    
    # KGFrames with Slots Methods - Delegated to KGFramesEndpoint
    
    async def get_kgframes_with_slots(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> 'FramesResponse':
        """
        Get KGFrames with their associated slots.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            FramesResponse containing KGFrames with slots data and pagination info
        """
        return await self.kgframes.get_kgframes_with_slots(space_id, graph_id, page_size, offset, search)
    
    async def create_kgframes_with_slots(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'FrameCreateResponse':
        """
        Create KGFrames with their associated slots from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGFrames with slots
            
        Returns:
            FrameCreateResponse containing operation result
        """
        return await self.kgframes.create_kgframes_with_slots(space_id, graph_id, document)
    
    async def update_kgframes_with_slots(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'FrameUpdateResponse':
        """
        Update KGFrames with their associated slots from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGFrames with slots
            
        Returns:
            FrameUpdateResponse containing operation result
        """
        return await self.kgframes.update_kgframes_with_slots(space_id, graph_id, document)
    
    async def delete_kgframes_with_slots(self, space_id: str, graph_id: str, uri_list: str) -> 'FrameDeleteResponse':
        """
        Delete KGFrames with their associated slots by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGFrame URIs
            
        Returns:
            FrameDeleteResponse containing operation result
        """
        return await self.kgframes.delete_kgframes_with_slots(space_id, graph_id, uri_list)
    
    # KGEntity CRUD Methods - Delegated to KGEntitiesEndpoint
    
    async def list_kgentities(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> 'EntityListResponse':
        """
        List KGEntities with pagination and optional search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            EntityListResponse containing KGEntities data and pagination info
        """
        return await self.kgentities.list_kgentities(space_id, graph_id, page_size, offset, search)
    
    async def get_kgentity(self, space_id: str, graph_id: str, uri: str) -> 'EntityResponse':
        """
        Get a specific KGEntity by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGEntity URI
            
        Returns:
            EntityResponse containing KGEntity data
        """
        return await self.kgentities.get_kgentity(space_id, graph_id, uri)
    
    async def create_kgentities(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'EntityCreateResponse':
        """
        Create KGEntities from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGEntities
            
        Returns:
            EntityCreateResponse containing operation result
        """
        return await self.kgentities.create_kgentities(space_id, graph_id, document)
    
    async def update_kgentities(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'EntityUpdateResponse':
        """
        Update KGEntities from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGEntities
            
        Returns:
            EntityUpdateResponse containing operation result
        """
        return await self.kgentities.update_kgentities(space_id, graph_id, document)
    
    async def delete_kgentity(self, space_id: str, graph_id: str, uri: str) -> 'EntityDeleteResponse':
        """
        Delete a KGEntity by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGEntity URI to delete
            
        Returns:
            EntityDeleteResponse containing operation result
        """
        return await self.kgentities.delete_kgentity(space_id, graph_id, uri)
    
    async def delete_kgentities_batch(self, space_id: str, graph_id: str, uri_list: str) -> 'EntityDeleteResponse':
        """
        Delete multiple KGEntities by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGEntity URIs
            
        Returns:
            EntityDeleteResponse containing operation result
        """
        return await self.kgentities.delete_kgentities_batch(space_id, graph_id, uri_list)
    
    async def get_kgentity_frames(self, space_id: str, graph_id: str, entity_uri: Optional[str] = None, 
                           page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> Dict[str, Any]:
        """
        Get frames associated with KGEntities.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Specific entity URI to get frames for (optional)
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            Dictionary containing entity frames data and pagination info
        """
        return await self.kgentities.get_kgentity_frames(space_id, graph_id, entity_uri, page_size, offset, search)
    
    # Object CRUD Methods - Delegated to ObjectsEndpoint
    
    async def list_objects(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> 'ObjectsResponse':
        """
        List Objects with pagination and optional search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            ObjectsResponse containing Objects data and pagination info
        """
        return await self.objects.list_objects(space_id, graph_id, page_size, offset, search)
    
    async def get_object(self, space_id: str, graph_id: str, uri: str) -> 'ObjectsResponse':
        """
        Get a specific Object by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Object URI
            
        Returns:
            ObjectsResponse containing Object data
        """
        return await self.objects.get_object(space_id, graph_id, uri)
    
    async def create_objects(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'ObjectCreateResponse':
        """
        Create Objects from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing Objects
            
        Returns:
            ObjectCreateResponse containing operation result
        """
        return await self.objects.create_objects(space_id, graph_id, document)
    
    async def update_objects(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'ObjectUpdateResponse':
        """
        Update Objects from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing Objects
            
        Returns:
            ObjectUpdateResponse containing operation result
        """
        return await self.objects.update_objects(space_id, graph_id, document)
    
    async def delete_object(self, space_id: str, graph_id: str, uri: str) -> 'ObjectDeleteResponse':
        """
        Delete an Object by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Object URI to delete
            
        Returns:
            ObjectDeleteResponse containing operation result
        """
        return await self.objects.delete_object(space_id, graph_id, uri)
    
    async def delete_objects_batch(self, space_id: str, graph_id: str, uri_list: str) -> 'ObjectDeleteResponse':
        """
        Delete multiple Objects by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of Object URIs
            
        Returns:
            ObjectDeleteResponse containing operation result
        """
        return await self.objects.delete_objects_batch(space_id, graph_id, uri_list)
    
    # File Management Methods - Delegated to FilesEndpoint
    
    async def list_files(self, space_id: str, graph_id: Optional[str] = None, page_size: int = 100, offset: int = 0, file_filter: Optional[str] = None) -> 'FilesResponse':
        """
        List files with pagination and optional filtering.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (optional)
            page_size: Number of items per page
            offset: Offset for pagination
            file_filter: Optional file filter
            
        Returns:
            FilesResponse containing Files data and pagination info
        """
        return await self.files.list_files(space_id, graph_id, page_size, offset, file_filter)
    
    async def get_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> 'JsonLdDocument':
        """
        Get a specific file by URI.
        
        Args:
            space_id: Space identifier
            uri: File URI
            graph_id: Graph identifier (optional)
            
        Returns:
            JsonLdDocument containing File data
        """
        return await self.files.get_file(space_id, uri, graph_id)
    
    async def create_file(self, space_id: str, document: 'JsonLdDocument', graph_id: Optional[str] = None) -> 'FileCreateResponse':
        """
        Create new file node (metadata only).
        
        Args:
            space_id: Space identifier
            document: JSON-LD document containing File metadata
            graph_id: Graph identifier (optional)
            
        Returns:
            FileCreateResponse containing operation result
        """
        return await self.files.create_file(space_id, document, graph_id)
    
    async def update_file(self, space_id: str, document: 'JsonLdDocument', graph_id: Optional[str] = None) -> 'FileUpdateResponse':
        """
        Update file metadata.
        
        Args:
            space_id: Space identifier
            document: JSON-LD document containing File metadata
            graph_id: Graph identifier (optional)
            
        Returns:
            FileUpdateResponse containing operation result
        """
        return await self.files.update_file(space_id, document, graph_id)
    
    async def delete_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> 'FileDeleteResponse':
        """
        Delete file node by URI.
        
        Args:
            space_id: Space identifier
            uri: File URI to delete
            graph_id: Graph identifier (optional)
            
        Returns:
            FileDeleteResponse containing operation result
        """
        return await self.files.delete_file(space_id, uri, graph_id)
    
    async def get_files_by_uris(self, space_id: str, uri_list: str, graph_id: Optional[str] = None) -> 'JsonLdDocument':
        """
        Get multiple files by URI list.
        
        Args:
            space_id: Space identifier
            uri_list: Comma-separated list of File URIs
            graph_id: Graph identifier (optional)
            
        Returns:
            JsonLdDocument containing multiple files
        """
        return await self.files.get_files_by_uris(space_id, uri_list, graph_id)
    
    async def upload_file_content(self, space_id: str, uri: str, file_path: str, graph_id: Optional[str] = None) -> 'FileUploadResponse':
        """
        Upload binary file content to existing file node.
        
        Args:
            space_id: Space identifier
            uri: File node URI
            file_path: Path to file to upload
            graph_id: Graph identifier (optional)
            
        Returns:
            FileUploadResponse containing upload result
        """
        return await self.files.upload_file_content(space_id, uri, file_path, graph_id)
    
    async def download_file_content(self, space_id: str, graph_id: str, file_uri: str, 
                             destination=None, chunk_size: int = 8192):
        """
        Download file content from a File node using streaming consumers.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            destination: Optional destination (path, stream, or BinaryConsumer)
            chunk_size: Size of chunks for streaming (default: 8192)
            
        Returns:
            File content as bytes if destination is None, otherwise operation result dict
        """
        return await self.files.download_file_content(space_id, graph_id, file_uri, destination, chunk_size)
    
    async def download_to_consumer(self, space_id: str, graph_id: str, file_uri: str, 
                            consumer, chunk_size: int = 8192) -> Dict[str, Any]:
        """
        Download file content to a BinaryConsumer.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            consumer: BinaryConsumer instance
            chunk_size: Size of chunks for streaming
            
        Returns:
            Dictionary containing download result
        """
        return await self.files.download_to_consumer(space_id, graph_id, file_uri, consumer, chunk_size)
    
    async def pump_file(self, source_space_id: str, source_graph_id: str, source_file_uri: str,
                  target_space_id: str, target_graph_id: str, target_file_uri: str,
                  chunk_size: int = 8192) -> Dict[str, Any]:
        """
        Pump file content from one file node to another (download + upload).
        
        Args:
            source_space_id: Source space identifier
            source_graph_id: Source graph identifier
            source_file_uri: Source file URI
            target_space_id: Target space identifier
            target_graph_id: Target graph identifier
            target_file_uri: Target file URI
            chunk_size: Size of chunks for streaming
            
        Returns:
            Dictionary containing pump result
        """
        return await self.files.pump_file(source_space_id, source_graph_id, source_file_uri,
                                   target_space_id, target_graph_id, target_file_uri, chunk_size)
    
    # Interface-required file methods (delegated to existing implementations)
    
    async def create_file(self, space_id: str, document: 'JsonLdDocument', graph_id: Optional[str] = None) -> 'FileCreateResponse':
        """Create new file node (metadata only) - Interface method."""
        return await self.files.create_file_node(space_id, graph_id or "default", document)
    
    async def update_file(self, space_id: str, document: 'JsonLdDocument', graph_id: Optional[str] = None) -> 'FileUpdateResponse':
        """Update file metadata - Interface method.""" 
        return await self.files.update_file_metadata(space_id, graph_id or "default", document)
    
    async def delete_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> 'FileDeleteResponse':
        """Delete file node by URI - Interface method."""
        return await self.files.delete_file_node(space_id, graph_id or "default", uri)
    
    async def get_files_by_uris(self, space_id: str, uri_list: str, graph_id: Optional[str] = None) -> 'JsonLdDocument':
        """Get multiple files by URI list - Interface method."""
        # This delegates to the batch delete method since there's no get_files_by_uris in FilesEndpoint
        # For now, return empty document - this method may need proper implementation
        from ..model.jsonld_model import JsonLdDocument
        return JsonLdDocument(graph=[])
    
    # Data Import Methods - Delegated to ImportEndpoint
    
    async def create_import_job(self, name: str, import_type: str, space_id: str, 
                         description: Optional[str] = None, graph_id: Optional[str] = None,
                         config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Create new data import job.
        
        Args:
            name: Import job name
            import_type: Type of import (rdf_turtle, rdf_xml, json_ld, csv, excel, json)
            space_id: Target space ID
            description: Optional job description
            graph_id: Optional target graph ID
            config: Optional import configuration
            
        Returns:
            Dictionary containing creation result with import_id and job details
        """
        return await self.imports.create_import_job(name, import_type, space_id, description, graph_id, config)
    
    async def list_import_jobs(self, space_id: Optional[str] = None, graph_id: Optional[str] = None,
                        page_size: int = 100, offset: int = 0) -> Dict[str, Any]:
        """
        List import jobs with optional filtering.
        
        Args:
            space_id: Optional space ID filter
            graph_id: Optional graph ID filter
            page_size: Number of jobs per page (default: 100, max: 1000)
            offset: Offset for pagination (default: 0)
            
        Returns:
            Dictionary containing import jobs list and pagination info
        """
        return await self.imports.list_import_jobs(space_id, graph_id, page_size, offset)
    
    async def get_import_job(self, import_id: str) -> 'ImportJobResponse':
        """
        Get import job details by ID.
        
        Args:
            import_id: Import job ID
            
        Returns:
            ImportJobResponse containing import job details
        """
        return await self.imports.get_import_job(import_id)
    
    async def update_import_job(self, import_id: str, name: Optional[str] = None, 
                         description: Optional[str] = None, import_type: Optional[str] = None,
                         space_id: Optional[str] = None, graph_id: Optional[str] = None,
                         config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Update import job.
        
        Args:
            import_id: Import job ID
            name: Optional new job name
            description: Optional new job description
            import_type: Optional new import type
            space_id: Optional new target space ID
            graph_id: Optional new target graph ID
            config: Optional new import configuration
            
        Returns:
            Dictionary containing update result
        """
        return await self.imports.update_import_job(import_id, name, description, import_type, space_id, graph_id, config)
    
    async def delete_import_job(self, import_id: str) -> 'ImportDeleteResponse':
        """
        Delete import job.
        
        Args:
            import_id: Import job ID
            
        Returns:
            ImportDeleteResponse containing deletion result
        """
        return await self.imports.delete_import_job(import_id)
    
    async def execute_import_job(self, import_id: str) -> 'ImportExecuteResponse':
        """
        Execute import job.
        
        Args:
            import_id: Import job ID
            
        Returns:
            ImportExecuteResponse containing execution result
        """
        return await self.imports.execute_import_job(import_id)
    
    async def get_import_status(self, import_id: str) -> 'ImportStatusResponse':
        """
        Get import execution status.
        
        Args:
            import_id: Import job ID
            
        Returns:
            ImportStatusResponse containing import status
        """
        return await self.imports.get_import_status(import_id)
    
    async def get_import_log(self, import_id: str) -> 'ImportLogResponse':
        """
        Get import execution log.
        
        Args:
            import_id: Import job ID
            
        Returns:
            ImportLogResponse containing import log
        """
        return await self.imports.get_import_log(import_id)
    
    async def upload_import_file(self, import_id: str, file_path: str) -> 'ImportUploadResponse':
        """
        Upload file to import job.
        
        Args:
            import_id: Import job ID
            file_path: Path to file to upload
            
        Returns:
            ImportUploadResponse containing upload result
        """
        return await self.imports.upload_import_file(import_id, file_path)
    
    async def upload_import_from_generator(self, import_id: str, generator) -> Dict[str, Any]:
        """
        Upload file to import job from a BinaryGenerator.
        
        Args:
            import_id: Import job ID
            generator: BinaryGenerator instance
            
        Returns:
            Dictionary containing upload result
        """
        return await self.imports.upload_from_generator(import_id, generator)
    
    # Data Export Methods - Delegated to ExportEndpoint
    
    async def create_export_job(self, name: str, export_format: str, space_id: str, 
                         description: Optional[str] = None, graph_id: Optional[str] = None,
                         query_filter: Optional[str] = None, 
                         config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Create new data export job.
        
        Args:
            name: Export job name
            export_format: Export format (rdf_turtle, rdf_xml, json_ld, csv, excel, json, parquet)
            space_id: Source space ID
            description: Optional job description
            graph_id: Optional source graph ID
            query_filter: Optional SPARQL query filter for export
            config: Optional export configuration
            
        Returns:
            Dictionary containing creation result with export_id and job details
        """
        return await self.exports.create_export_job(name, export_format, space_id, description, graph_id, query_filter, config)
    
    async def list_export_jobs(self, space_id: Optional[str] = None, graph_id: Optional[str] = None,
                        page_size: int = 100, offset: int = 0) -> Dict[str, Any]:
        """
        List export jobs with optional filtering.
        
        Args:
            space_id: Optional space ID filter
            graph_id: Optional graph ID filter
            page_size: Number of jobs per page (default: 100, max: 1000)
            offset: Offset for pagination (default: 0)
            
        Returns:
            Dictionary containing export jobs list and pagination info
        """
        return await self.exports.list_export_jobs(space_id, graph_id, page_size, offset)
    
    async def get_export_job(self, export_id: str) -> 'ExportJobResponse':
        """
        Get export job details by ID.
        
        Args:
            export_id: Export job ID
            
        Returns:
            ExportJobResponse containing export job details
        """
        return await self.exports.get_export_job(export_id)
    
    async def update_export_job(self, export_id: str, name: Optional[str] = None, 
                         description: Optional[str] = None, export_format: Optional[str] = None,
                         space_id: Optional[str] = None, graph_id: Optional[str] = None,
                         query_filter: Optional[str] = None,
                         config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Update export job.
        
        Args:
            export_id: Export job ID
            name: Optional new job name
            description: Optional new job description
            export_format: Optional new export format
            space_id: Optional new source space ID
            graph_id: Optional new source graph ID
            query_filter: Optional new SPARQL query filter
            config: Optional new export configuration
            
        Returns:
            Dictionary containing update result
        """
        return await self.exports.update_export_job(export_id, name, description, export_format, space_id, graph_id, query_filter, config)
    
    async def delete_export_job(self, export_id: str) -> 'ExportDeleteResponse':
        """
        Delete export job.
        
        Args:
            export_id: Export job ID
            
        Returns:
            ExportDeleteResponse containing deletion result
        """
        return await self.exports.delete_export_job(export_id)
    
    async def execute_export_job(self, export_id: str) -> 'ExportExecuteResponse':
        """
        Execute export job.
        
        Args:
            export_id: Export job ID
            
        Returns:
            ExportExecuteResponse containing execution result
        """
        return await self.exports.execute_export_job(export_id)
    
    async def get_export_status(self, export_id: str) -> 'ExportStatusResponse':
        """
        Get export execution status.
        
        Args:
            export_id: Export job ID
            
        Returns:
            ExportStatusResponse containing export status
        """
        return await self.exports.get_export_status(export_id)
    
    async def download_export_results(self, export_id: str, binary_id: str, destination=None, 
                               chunk_size: int = 8192):
        """
        Download export results using streaming consumers.
        
        Args:
            export_id: Export job ID
            binary_id: Binary file ID to download
            destination: Optional destination (path, stream, or BinaryConsumer)
            chunk_size: Size of chunks for streaming (default: 8192)
            
        Returns:
            File content as bytes if destination is None, otherwise operation result dict
        """
        return await self.exports.download_export_results(export_id, binary_id, destination, chunk_size)
    
    async def download_export_to_consumer(self, export_id: str, binary_id: str, 
                                   consumer, chunk_size: int = 8192) -> Dict[str, Any]:
        """
        Download export results to a BinaryConsumer.
        
        Args:
            export_id: Export job ID
            binary_id: Binary file ID to download
            consumer: BinaryConsumer instance
            chunk_size: Size of chunks for streaming
            
        Returns:
            Dictionary containing download result
        """
        return await self.exports.download_to_consumer(export_id, binary_id, consumer, chunk_size)
    
    async def get_export_files(self, export_id: str) -> List[Dict[str, Any]]:
        """
        Get list of available export output files.
        
        Args:
            export_id: Export job ID
            
        Returns:
            List of output file dictionaries with binary_id, filename, size, mime_type
        """
        return await self.exports.get_export_files(export_id)
    
    async def download_all_export_files(self, export_id: str, destination_dir, 
                                 chunk_size: int = 8192) -> Dict[str, Any]:
        """
        Download all export output files to a directory.
        
        Args:
            export_id: Export job ID
            destination_dir: Directory to save files
            chunk_size: Size of chunks for streaming
            
        Returns:
            Dictionary containing download results for all files
        """
        return await self.exports.download_all_export_files(export_id, destination_dir, chunk_size)
    
    # Graph Management Methods - Delegated to GraphsEndpoint
    
    async def list_graphs(self, space_id: str) -> List[GraphInfo]:
        """
        List graphs in a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            List of GraphInfo objects
        """
        return await self.graphs.list_graphs(space_id)
    
    async def get_graph_info(self, space_id: str, graph_uri: str) -> Optional[GraphInfo]:
        """
        Get information about a specific graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI
            
        Returns:
            GraphInfo object or None if graph doesn't exist
        """
        return await self.graphs.get_graph_info(space_id, graph_uri)
    
    async def create_graph(self, space_id: str, graph_uri: str) -> SPARQLGraphResponse:
        """
        Create a new graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to create
            
        Returns:
            SPARQLGraphResponse with creation result
        """
        return await self.graphs.create_graph(space_id, graph_uri)
    
    async def drop_graph(self, space_id: str, graph_uri: str, silent: bool = False) -> SPARQLGraphResponse:
        """
        Drop (delete) a graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to drop
            silent: Execute silently (optional)
            
        Returns:
            SPARQLGraphResponse with deletion result
        """
        return await self.graphs.drop_graph(space_id, graph_uri, silent)
    
    async def clear_graph(self, space_id: str, graph_uri: str) -> SPARQLGraphResponse:
        """
        Clear a graph (remove all triples but keep the graph).
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to clear
            
        Returns:
            SPARQLGraphResponse with clear operation result
        """
        return await self.graphs.clear_graph(space_id, graph_uri)
    
    async def execute_graph_operation(self, space_id: str, operation: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a graph management operation.
        
        Args:
            space_id: Space identifier
            operation: Graph operation (CREATE, DROP, CLEAR, etc.)
            **kwargs: Additional operation parameters
            
        Returns:
            Operation result dictionary
        """
        return await self.graphs.execute_graph_operation(space_id, operation, **kwargs)
    
    # Triples Management Methods - Delegated to TriplesEndpoint
    
    async def list_triples(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, 
                    subject: Optional[str] = None, predicate: Optional[str] = None, 
                    object: Optional[str] = None, object_filter: Optional[str] = None) -> 'TripleListResponse':
        """
        List/search triples with pagination and filtering options.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            subject: Subject URI filter (optional)
            predicate: Predicate URI filter (optional)
            object: Object value filter (optional)
            object_filter: Object filter (optional)
            
        Returns:
            TripleListResponse containing triples data and pagination info
        """
        return await self.triples.list_triples(space_id, graph_id, page_size, offset, subject, predicate, object, object_filter)
    
    async def search_triples(self, space_id: str, graph_id: Optional[str] = None, subject: Optional[str] = None, 
                      predicate: Optional[str] = None, object_value: Optional[str] = None, 
                      limit: Optional[int] = None, offset: Optional[int] = None) -> Dict[str, Any]:
        """
        Search triples with filtering (alias for list_triples for clarity).
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (optional)
            subject: Subject URI filter (optional)
            predicate: Predicate URI filter (optional)
            object_value: Object value filter (optional)
            limit: Maximum number of triples to return (optional)
            offset: Offset for pagination (optional)
            
        Returns:
            Dictionary containing matching triples data and pagination info
        """
        return await self.triples.search_triples(space_id, graph_id, subject, predicate, object_value, limit, offset)
    
    async def add_triples(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'TripleOperationResponse':
        """
        Add new triples to the specified graph.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing triples to add
            
        Returns:
            TripleOperationResponse containing operation result
        """
        return await self.triples.add_triples(space_id, graph_id, document)
    
    async def delete_triples(self, space_id: str, graph_id: str, 
                      subject: Optional[str] = None, predicate: Optional[str] = None, 
                      object: Optional[str] = None) -> 'TripleOperationResponse':
        """
        Delete specific triples by pattern.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            subject: Subject URI filter for pattern-based deletion (optional)
            predicate: Predicate URI filter for pattern-based deletion (optional)
            object: Object value filter for pattern-based deletion (optional)
            
        Returns:
            TripleOperationResponse containing operation result
        """
        return await self.triples.delete_triples(space_id, graph_id, subject, predicate, object)
