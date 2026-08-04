"""VitalGraph Client

REST API client for connecting to VitalGraph servers with JWT authentication.
"""

from __future__ import annotations

import httpx
import logging
import time
import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict, Any, List, Union
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
from .endpoint.entity_registry_endpoint import EntityRegistryClientEndpoint
from .endpoint.agent_registry_endpoint import AgentRegistryClientEndpoint
from .endpoint.process_endpoint import ProcessClientEndpoint
from .endpoint.admin_endpoint import AdminClientEndpoint
from .endpoint.api_keys_endpoint import ApiKeysClientEndpoint
from .endpoint.fuzzy_mappings_endpoint import FuzzyMappingsClientEndpoint
from .endpoint.vector_indexes_endpoint import VectorIndexesClientEndpoint
from .endpoint.search_mappings_endpoint import SearchMappingsClientEndpoint
from .endpoint.fts_indexes_endpoint import FtsIndexesClientEndpoint
from .endpoint.geo_config_endpoint import GeoConfigClientEndpoint
from .endpoint.geo_points_endpoint import GeoPointsClientEndpoint
from .endpoint.kgdocuments_endpoint import KGDocumentsEndpoint as KGDocumentsClientEndpoint
from .endpoint.metrics_endpoint import MetricsClientEndpoint
from .endpoint.ontology_endpoint import OntologyClientEndpoint
from .utils.client_utils import (
    VitalGraphClientError,
    VitalGraphClientConnectionError,
    VitalGraphClientTimeoutError,
    VitalGraphClientUnavailableError,
)
from .retry import (
    CircuitBreaker,
    FailureClass,
    IDEMPOTENT_METHODS,
    RetryPolicy,
    RetryStats,
    classify_exception,
    classify_status,
    parse_retry_after,
    safe_log_url,
)
from .utils.format_helpers import ClientWireFormat
from .vitalgraph_client_inf import VitalGraphClientInterface
from ..model.sparql_model import GraphInfo, SPARQLGraphResponse
from .response.client_response import (
    GraphResponse, GraphsListResponse, GraphCreateResponse, GraphDeleteResponse, GraphClearResponse,
    SpaceResponse, SpacesListResponse, SpaceCreateResponse, SpaceUpdateResponse, SpaceDeleteResponse,
    KGTypesListResponse, KGTypeResponse, KGTypeCreateResponse, KGTypeUpdateResponse, KGTypeDeleteResponse,
    ObjectsListResponse, ObjectResponse, ObjectCreateResponse, ObjectUpdateResponse, ObjectDeleteResponse,
    PaginatedGraphObjectResponse, FrameGraphResponse, CreateEntityResponse, UpdateEntityResponse, DeleteResponse,
    EntityResponse,
    FilesListResponse, FileResponse, FileCreateResponse, FileUpdateResponse, FileDeleteResponse, FileUploadResponse,
)

if TYPE_CHECKING:
    from ..model.quad_model import QuadRequest
    from ..model.sparql_model import (
        SPARQLQueryRequest, SPARQLQueryResponse, SPARQLUpdateRequest, SPARQLUpdateResponse,
        SPARQLInsertRequest, SPARQLInsertResponse, SPARQLDeleteRequest, SPARQLDeleteResponse,
    )
    from ..model.triples_model import TripleListResponse, TripleOperationResponse
    from ..model.users_model import User, UserCreate, UsersListResponse, UserCreateResponse, UserUpdateResponse, UserDeleteResponse
    from ..model.spaces_model import Space
    from ..model.import_model import (
        ImportJobCreate, ImportJobResponse, ImportDeleteResponse, ImportExecuteResponse,
        ImportStatusResponse, ImportLogResponse, ImportUploadResponse,
    )
    from ..model.export_model import (
        ExportJobCreate, ExportJobResponse, ExportDeleteResponse, ExportExecuteResponse, ExportStatusResponse,
    )

logger = logging.getLogger(__name__)


class VitalGraphClient(VitalGraphClientInterface):
    """
    VitalGraph REST API client with JWT authentication.
    
    Provides functionality to connect to VitalGraph API servers using
    JWT-based authentication with automatic token refresh and connection management.
    """
    
    def __init__(self, *, config: Optional[VitalGraphClientConfig] = None, 
                 token_expiry_seconds: Optional[int] = None,
                 disable_proactive_refresh: bool = False,
                 wire_format: ClientWireFormat = ClientWireFormat.JSON_QUADS,
                 api_key: Optional[str] = None):
        """
        Initialize the VitalGraph client.
        
        Configuration is loaded from profile-prefixed environment variables.
        Set VITALGRAPH_CLIENT_ENVIRONMENT to select profile (local, dev, staging, prod).
        
        Args:
            config: Pre-configured VitalGraphClientConfig object (optional, for testing)
            token_expiry_seconds: Optional token expiry override in seconds for testing (max 1800 = 30 min)
            disable_proactive_refresh: If True, skip proactive token refresh to test reactive 401 retry (testing only)
            api_key: Optional API key (vg_...) for authentication. When provided, skips JWT
                     login entirely — the key is sent as Bearer token on every request.
        
        Environment Variables (profile-prefixed):
            {PROFILE}_CLIENT_SERVER_URL: Server endpoint URL
            {PROFILE}_CLIENT_AUTH_USERNAME: Authentication username
            {PROFILE}_CLIENT_AUTH_PASSWORD: Authentication password
            {PROFILE}_CLIENT_TIMEOUT: Read/write timeout in seconds per attempt
            {PROFILE}_CLIENT_CONNECT_TIMEOUT: Connection timeout in seconds
            {PROFILE}_CLIENT_POOL_TIMEOUT: Pool acquisition timeout in seconds
            {PROFILE}_CLIENT_REQUEST_BUDGET: Total per-call ceiling across retries
            {PROFILE}_CLIENT_MAX_RETRIES: Maximum retry attempts
            {PROFILE}_CLIENT_RETRY_DELAY: Base backoff delay in seconds
            {PROFILE}_CLIENT_RETRY_BACKOFF_BASE: Exponential backoff factor
            {PROFILE}_CLIENT_RETRY_MAX_DELAY: Backoff ceiling in seconds
            {PROFILE}_CLIENT_MAX_CONNECTIONS: Connection pool size
            {PROFILE}_CLIENT_MAX_KEEPALIVE: Idle keep-alive connections
            {PROFILE}_CLIENT_MAX_CONCURRENCY: In-flight request cap (0 = unlimited)
            {PROFILE}_CLIENT_BREAKER_THRESHOLD: Consecutive failures before the
                circuit breaker opens (0 disables)
            {PROFILE}_CLIENT_BREAKER_RESET: Breaker reset timeout in seconds

        Example:
            # Use LOCAL profile with username/password
            export VITALGRAPH_CLIENT_ENVIRONMENT=local
            export LOCAL_CLIENT_SERVER_URL=http://localhost:8001
            export LOCAL_CLIENT_AUTH_USERNAME=admin
            export LOCAL_CLIENT_AUTH_PASSWORD=admin
            client = VitalGraphClient()
            
            # Use API key (no login step needed)
            client = VitalGraphClient(api_key="vg_Ab3kLm92...")
        """
        self.config: Optional[VitalGraphClientConfig] = None
        self.async_session: Optional[httpx.AsyncClient] = None
        self.is_open: bool = False
        self.wire_format: ClientWireFormat = wire_format
        
        # API key authentication (alternative to JWT)
        self._api_key: Optional[str] = api_key
        
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

        # Retry policy, circuit breaker, and counters
        self.retry_policy = RetryPolicy(
            max_retries=self.config.get_max_retries(),
            retry_delay=self.config.get_retry_delay(),
            backoff_base=self.config.get_retry_backoff_base(),
            max_delay=self.config.get_retry_max_delay(),
            request_budget=self.config.get_request_budget(),
        )
        self.circuit_breaker = CircuitBreaker(
            threshold=self.config.get_breaker_threshold(),
            reset_timeout=self.config.get_breaker_reset(),
        )
        self.retry_stats = RetryStats()
        self._concurrency_limiter: Optional[asyncio.Semaphore] = None
        # Seam for tests: the budget clock. Mirrors CircuitBreaker's clock.
        self._clock = time.monotonic

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
        self.entity_registry = EntityRegistryClientEndpoint(self)
        self.agent_registry = AgentRegistryClientEndpoint(self)
        self.processes = ProcessClientEndpoint(self)
        self.admin = AdminClientEndpoint(self)
        self.api_keys = ApiKeysClientEndpoint(self)
        self.fuzzy_mappings = FuzzyMappingsClientEndpoint(self)
        self.vector_indexes = VectorIndexesClientEndpoint(self)
        self.search_mappings = SearchMappingsClientEndpoint(self)
        self.fts_indexes = FtsIndexesClientEndpoint(self)
        self.kgdocuments = KGDocumentsClientEndpoint(self)
        self.geo_config = GeoConfigClientEndpoint(self)
        self.geo_points = GeoPointsClientEndpoint(self)
        self.metrics = MetricsClientEndpoint(self)
        self.ontology = OntologyClientEndpoint(self)
    
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
            from .utils.format_helpers import FORMAT_TO_ACCEPT
            accept_mime = FORMAT_TO_ACCEPT.get(self.wire_format, 'application/json')
            headers = {
                'Accept': accept_mime,
                'User-Agent': 'VitalGraph-Client/1.0'
            }
            
            # Per-phase timeouts rather than one scalar: a 30s connect timeout is
            # never useful, and an unbounded pool wait is what turns load into
            # PoolTimeout instead of backpressure.
            timeout_config = httpx.Timeout(
                connect=self.config.get_connect_timeout(),
                read=timeout,
                write=timeout,
                pool=self.config.get_pool_timeout(),
            )
            limits = httpx.Limits(
                max_connections=self.config.get_max_connections(),
                max_keepalive_connections=self.config.get_max_keepalive(),
                keepalive_expiry=self.config.get_keepalive_expiry(),
            )

            self.async_session = httpx.AsyncClient(
                timeout=timeout_config,
                limits=limits,
                headers=headers,
                follow_redirects=True
            )

            # Optional client-side in-flight cap, so one client cannot saturate
            # its own pool and then retry the timeouts it caused.
            max_concurrency = self.config.get_max_concurrency()
            self._concurrency_limiter = (
                asyncio.Semaphore(max_concurrency) if max_concurrency > 0 else None
            )

            # Authenticate with the server
            if self._api_key:
                # API key mode: set Bearer header directly, no login needed
                auth_header = {'Authorization': f'Bearer {self._api_key}'}
                self.async_session.headers.update(auth_header)
                self.access_token = self._api_key
                self.is_open = True
                logger.info("VitalGraph client opened with API key authentication")
            else:
                # JWT mode: login with username/password
                server_url = self.config.get_server_url()
                api_base_path = self.config.get_api_base_path()
                await self._authenticate(server_url, api_base_path, timeout)
                self.is_open = True
                logger.info("VitalGraph client opened successfully")
            
        except Exception as e:
            logger.error(f"Failed to open VitalGraph client: {e}")
            await self._cleanup_session()
            raise VitalGraphClientError(f"Failed to open client: {e}")
    
    async def _authenticate(self, server_url: str, api_base_path: str, timeout: float) -> None:
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
        assert self.config is not None
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
            login_data["token_expiry_seconds"] = str(self.token_expiry_seconds)
            logger.info(f"Requesting custom token expiry: {self.token_expiry_seconds} seconds")
        
        try:
            logger.info(f"Authenticating with VitalGraph server at {login_url}")
            # Set content type for form data and send authentication request
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            assert self.async_session is not None
            # auth=False: there is no token to refresh yet, and a 401 here means
            # bad credentials, not an expired session. idempotent=False keeps a
            # login that reached the server from being replayed — only connect
            # failures are retried.
            response = await self._send_with_retry(
                "POST", login_url,
                auth=False, idempotent=False, timeout=timeout,
                data=login_data, headers=headers,
            )

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
                
        except VitalGraphClientError:
            # Already typed and described by the retry core — do not re-wrap,
            # or callers lose the connection/timeout/unavailable distinction.
            raise
        except httpx.HTTPError as e:
            error_msg = f"Failed to connect to authentication endpoint: {e}"
            logger.error(error_msg)
            raise VitalGraphClientError(error_msg) from e
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
            
            assert self.config is not None
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
            assert self.config is not None
            server_url = self.config.get_server_url()
            refresh_url = f"{server_url.rstrip('/')}/api/refresh"
            
            # Send refresh request with refresh token as Bearer token
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.refresh_token}'
            }
            
            refresh_data = {"refresh_token": self.refresh_token}
            # auth=False avoids recursing into _ensure_valid_token; idempotent=False
            # keeps a refresh that reached the server from being replayed (it may
            # have already rotated the token).
            response = await self._send_with_retry(
                "POST", refresh_url,
                auth=False, idempotent=False,
                json=refresh_data, headers=headers,
            )

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
        API key mode never expires client-side, so we skip refresh entirely.
        
        Raises:
            VitalGraphClientError: If token refresh fails
        """
        if not self.access_token:
            raise VitalGraphClientError("No access token available")
        
        # API keys don't need client-side refresh
        if self._api_key:
            return
        
        if self._is_token_expired():
            logger.info("Access token expired or expiring soon, attempting refresh...")
            
            if not await self._refresh_access_token():
                raise VitalGraphClientError("Failed to refresh access token - please re-authenticate")
    
    # Below this much remaining budget, another attempt cannot accomplish
    # anything useful, so we stop rather than burn a socket on it.
    _MIN_ATTEMPT_WINDOW = 0.1

    def _build_attempt_timeout(
        self, remaining: float, timeout_override: Any = None
    ) -> httpx.Timeout:
        """Build the timeout for a single attempt, clamped to the remaining budget.

        Clamping is what makes the budget a real ceiling: without it a final
        attempt started just under the deadline could still run for the full
        read timeout past it.
        """
        assert self.config is not None
        if isinstance(timeout_override, httpx.Timeout):
            connect, read = timeout_override.connect, timeout_override.read
            write, pool = timeout_override.write, timeout_override.pool
        elif timeout_override is not None:
            connect = read = write = pool = float(timeout_override)
        else:
            read = write = self.config.get_timeout()
            connect = self.config.get_connect_timeout()
            pool = self.config.get_pool_timeout()

        def clamp(value: Optional[float]) -> float:
            return remaining if value is None else min(float(value), remaining)

        return httpx.Timeout(
            connect=clamp(connect), read=clamp(read), write=clamp(write), pool=clamp(pool)
        )

    async def _send_once(
        self, method: str, url: str, remaining: float, timeout_override: Any, **kwargs
    ) -> httpx.Response:
        """Issue exactly one request, honoring the optional concurrency cap."""
        assert self.async_session is not None
        attempt_timeout = self._build_attempt_timeout(remaining, timeout_override)
        if self._concurrency_limiter is not None:
            async with self._concurrency_limiter:
                return await self.async_session.request(
                    method, url, timeout=attempt_timeout, **kwargs
                )
        return await self.async_session.request(
            method, url, timeout=attempt_timeout, **kwargs
        )

    async def _handle_401(self) -> None:
        """Refresh credentials after a 401, by refresh token or full re-auth."""
        logger.warning("Received 401 Unauthorized - refreshing credentials")
        if self.refresh_token:
            logger.info("Attempting token refresh with refresh token")
            if not await self._refresh_access_token():
                raise VitalGraphClientError(
                    "Token refresh failed after 401 - please re-authenticate"
                )
        else:
            logger.info("No refresh token available - re-authenticating with credentials")
            await self._reauthenticate()

    @staticmethod
    def _status_error(exc: httpx.HTTPStatusError) -> VitalGraphClientError:
        """Build the error for a non-retryable status, preserving server detail."""
        detail = ""
        try:
            body = exc.response.json()
            detail = body.get("detail", "")
        except Exception:
            pass
        msg = f"Request failed ({exc.response.status_code}): {detail or exc}"
        return VitalGraphClientError(msg, status_code=exc.response.status_code)

    @staticmethod
    def _terminal_error(
        method: str,
        url: str,
        failure_class: Optional[FailureClass],
        attempts: int,
        exc: Optional[BaseException],
        reason: str,
        retry_after: Optional[float] = None,
    ) -> VitalGraphClientError:
        """Map an exhausted/abandoned retry sequence onto a typed exception.

        Callers (Celery tasks in particular) need to tell "the server is down"
        from "this call is too slow" from "this will never work".
        """
        msg = (
            f"{method} {safe_log_url(url)} failed after {attempts} attempt(s): "
            f"{reason}"
        )
        if exc is not None:
            msg = f"{msg} ({type(exc).__name__}: {exc})"

        status_code = (
            exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        )
        if failure_class is None:
            # No class means the deadline ended the call, whatever the last
            # underlying failure was.
            return VitalGraphClientTimeoutError(msg, status_code=status_code)
        if failure_class is FailureClass.DECLINED:
            return VitalGraphClientUnavailableError(
                msg, status_code=status_code, retry_after=retry_after
            )
        if failure_class is FailureClass.PRE_SEND:
            return VitalGraphClientConnectionError(msg, status_code=status_code)
        if isinstance(exc, httpx.TimeoutException) or status_code == 504:
            return VitalGraphClientTimeoutError(msg, status_code=status_code)
        return VitalGraphClientConnectionError(msg, status_code=status_code)

    async def _send_with_retry(
        self,
        method: str,
        url: str,
        *,
        auth: bool = True,
        idempotent: Optional[bool] = None,
        replayable: bool = True,
        budget: Optional[float] = None,
        max_retries: Optional[int] = None,
        timeout: Any = None,
        **kwargs,
    ) -> httpx.Response:
        """Send a request with classification-driven retry, backoff, and a budget.

        Every HTTP call the client makes goes through here, so the retry
        semantics are the same for authenticated endpoints, health probes, and
        the login/refresh round trips.

        Args:
            method: HTTP method.
            url: Request URL.
            auth: Whether to attach/refresh credentials and handle 401.
            idempotent: Whether replaying this request is safe. Defaults to the
                method's own semantics; pass True for a POST that is really a
                read (search, query) to opt it into post-send retry.
            replayable: Whether the request body can be produced a second time.
                Pass False for streamed bodies (generators, open file handles):
                they are consumed on the first attempt, so a retry would send a
                truncated or empty body. Disables retry entirely.
            budget: Total wall-clock ceiling for this call, defaulting to the
                configured request budget.
            max_retries: Per-call override of the retry count.
            timeout: Per-call timeout override (seconds or ``httpx.Timeout``).

        Returns:
            The successful response.

        Raises:
            VitalGraphClientUnavailableError: Server declined, or breaker open.
            VitalGraphClientTimeoutError: Budget exhausted.
            VitalGraphClientConnectionError: Server unreachable.
            VitalGraphClientError: Any non-retryable failure.
        """
        method = method.upper()
        if idempotent is None:
            idempotent = method in IDEMPOTENT_METHODS
        if self.async_session is None:
            raise VitalGraphClientError("Client is not connected")

        policy = self.retry_policy
        retry_limit = policy.max_retries if max_retries is None else max_retries
        total_budget = policy.request_budget if budget is None else budget
        deadline = self._clock() + total_budget
        self.retry_stats.requests += 1

        if not self.circuit_breaker.allows_request():
            self.retry_stats.breaker_rejections += 1
            wait = self.circuit_breaker.retry_after()
            raise VitalGraphClientUnavailableError(
                f"Circuit breaker open for {safe_log_url(url)}; "
                f"failing fast for another {wait:.1f}s",
                retry_after=wait,
            )

        last_exc: Optional[BaseException] = None
        reauthed = False
        attempt = 0

        while True:
            remaining = deadline - self._clock()
            if remaining <= self._MIN_ATTEMPT_WINDOW:
                self.retry_stats.budget_exhausted += 1
                raise self._terminal_error(
                    method, url, None, attempt, last_exc,
                    f"exceeded {total_budget:.1f}s request budget",
                ) from last_exc

            if auth and not self.disable_proactive_refresh:
                await self._ensure_valid_token()

            failure_class: Optional[FailureClass] = None
            retry_after: Optional[float] = None

            try:
                self.retry_stats.attempts += 1
                response = await self._send_once(
                    method, url, remaining, timeout, **kwargs
                )
                response.raise_for_status()
                self.circuit_breaker.record_success()
                return response

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                # A 401 is not a retry: refresh credentials once, then re-enter
                # the loop so the refreshed attempt gets full retry coverage.
                if auth and status == 401 and not reauthed:
                    reauthed = True
                    await self._handle_401()
                    logger.info("Retrying request with refreshed credentials")
                    continue

                failure_class = classify_status(status)
                if failure_class is FailureClass.FATAL:
                    raise self._status_error(e) from e
                if failure_class is FailureClass.DECLINED:
                    self.circuit_breaker.record_failure()
                    retry_after = parse_retry_after(e.response.headers.get("Retry-After"))
                last_exc = e

            except (httpx.TransportError, ConnectionResetError) as e:
                failure_class = classify_exception(e)
                if failure_class is FailureClass.PRE_SEND:
                    # Only pre-send failures say anything about server health.
                    self.circuit_breaker.record_failure()
                last_exc = e

            except httpx.HTTPError as e:
                # Malformed URL, too many redirects, local protocol error, ...
                raise VitalGraphClientError(f"Request failed: {e}") from e

            # --- retry decision -------------------------------------------------
            if not replayable:
                # A consumed generator or file handle cannot be re-sent; a retry
                # would upload a truncated body, which is worse than failing.
                raise self._terminal_error(
                    method, url, failure_class, attempt + 1, last_exc,
                    "request body cannot be replayed; not retrying",
                    retry_after=retry_after,
                ) from last_exc

            if failure_class is FailureClass.POST_SEND and not idempotent:
                self.retry_stats.non_retryable_writes += 1
                raise self._terminal_error(
                    method, url, failure_class, attempt + 1, last_exc,
                    "non-idempotent request may already have been processed; "
                    "not retrying",
                ) from last_exc

            if attempt >= retry_limit:
                raise self._terminal_error(
                    method, url, failure_class, attempt + 1, last_exc,
                    f"exhausted {retry_limit} retries",
                    retry_after=retry_after,
                ) from last_exc

            sleep_for = policy.compute_sleep(attempt, retry_after)
            remaining = deadline - self._clock()
            if sleep_for + self._MIN_ATTEMPT_WINDOW >= remaining:
                self.retry_stats.budget_exhausted += 1
                # failure_class is deliberately dropped here: what ended this
                # call is the deadline, not the underlying failure, and callers
                # keying on the budget need a stable type to catch.
                raise self._terminal_error(
                    method, url, None, attempt + 1, last_exc,
                    f"exceeded {total_budget:.1f}s request budget",
                    retry_after=retry_after,
                ) from last_exc

            self.retry_stats.record_retry(failure_class)
            # First retry is worth a warning; the rest are detail.
            log_at = logger.warning if attempt == 0 else logger.debug
            log_at(
                "Retrying %s %s after %s (%s): attempt %d/%d, sleeping %.2fs, "
                "%.1fs budget left",
                method, safe_log_url(url),
                type(last_exc).__name__ if last_exc else "unknown",
                failure_class.value if failure_class else "unknown",
                attempt + 1, retry_limit + 1, sleep_for, remaining,
            )
            await asyncio.sleep(sleep_for)
            attempt += 1

    async def _make_authenticated_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """
        Make an authenticated async request with automatic token refresh
        and classification-driven retry.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            url: Request URL
            **kwargs: Additional request parameters. ``idempotent``, ``budget``,
                ``max_retries``, and ``timeout`` are consumed as retry controls;
                anything else is passed through to httpx.

        Returns:
            Response object

        Raises:
            VitalGraphClientError: If request fails after all retries
        """
        if not self.is_connected():
            raise VitalGraphClientError("Client is not connected")

        return await self._send_with_retry(method, url, auth=True, **kwargs)

    def stats(self) -> Dict[str, Any]:
        """
        Get in-process retry and circuit breaker counters.

        Returns:
            Dictionary of counters plus current breaker state
        """
        data = self.retry_stats.as_dict()
        data["breaker_state"] = self.circuit_breaker.state.value
        data["breaker_trips"] = self.circuit_breaker.trip_count
        return data

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
            'connect_timeout': self.config.get_connect_timeout(),
            'pool_timeout': self.config.get_pool_timeout(),
            'request_budget': self.config.get_request_budget(),
            'max_retries': self.config.get_max_retries(),
            'retry_delay': self.config.get_retry_delay(),
            'retry_backoff_base': self.config.get_retry_backoff_base(),
            'retry_max_delay': self.config.get_retry_max_delay(),
            'max_concurrency': self.config.get_max_concurrency(),
            'breaker_threshold': self.config.get_breaker_threshold(),
            'is_connected': self.is_connected(),
            'authentication': auth_info,
            'retry_stats': self.stats(),
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
    
    # ------------------------------------------------------------------
    # Health / diagnostics (unauthenticated)
    # ------------------------------------------------------------------

    # A health probe that retries for a minute is not a health probe. These get
    # a short budget and a single retry, and they still go through the retry
    # core so the breaker and counters see them.
    _HEALTH_BUDGET = 5.0

    async def health(self) -> Dict[str, Any]:
        """Check service health via GET /health (no auth required)."""
        if not self.async_session or not self.config:
            raise VitalGraphClientError("Client is not open")
        url = f"{self.config.get_server_url()}/health"
        resp = await self._send_with_retry(
            "GET", url, auth=False, budget=self._HEALTH_BUDGET, max_retries=1,
            timeout=self._HEALTH_BUDGET,
        )
        return resp.json()

    async def cache_stats(self) -> Dict[str, Any]:
        """Fetch entity graph cache statistics via GET /health/cache (no auth required)."""
        if not self.async_session or not self.config:
            raise VitalGraphClientError("Client is not open")
        url = f"{self.config.get_server_url()}/health/cache"
        resp = await self._send_with_retry(
            "GET", url, auth=False, budget=self._HEALTH_BUDGET, max_retries=1,
            timeout=self._HEALTH_BUDGET,
        )
        return resp.json()

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
    
    async def get_space(self, space_id: str) -> SpaceResponse:
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
    
    async def add_user(self, user: 'UserCreate') -> 'UserCreateResponse':
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
    
    async def list_kgtypes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> KGTypesListResponse:
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
    
    async def get_kgtype(self, space_id: str, graph_id: str, uri: str) -> KGTypeResponse:
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
    
    async def create_kgtypes(self, space_id: str, graph_id: str, objects: List) -> KGTypeCreateResponse:
        """
        Create KGTypes from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances to create
            
        Returns:
            KGTypeCreateResponse containing operation result
        """
        return await self.kgtypes.create_kgtypes(space_id, graph_id, objects)
    
    async def update_kgtypes(self, space_id: str, graph_id: str, objects: List) -> KGTypeUpdateResponse:
        """
        Update KGTypes from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances to update
            
        Returns:
            KGTypeUpdateResponse containing operation result
        """
        return await self.kgtypes.update_kgtypes(space_id, graph_id, objects)
    
    async def delete_kgtype(self, space_id: str, graph_id: str, uri: str) -> KGTypeDeleteResponse:
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
    
    async def delete_kgtypes_batch(self, space_id: str, graph_id: str, uri_list: str) -> KGTypeDeleteResponse:
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
    
    # KGDocument CRUD Methods - Delegated to KGDocumentsEndpoint
    
    async def list_kgdocuments(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0,
                               search: Optional[str] = None, include_segments: bool = False,
                               document_type_uri: Optional[str] = None):
        """List KGDocuments with pagination and optional filtering."""
        return await self.kgdocuments.list_kgdocuments(space_id, graph_id, page_size, offset, search, include_segments, document_type_uri)
    
    async def get_kgdocument(self, space_id: str, graph_id: str, uri: str):
        """Get a single KGDocument by URI."""
        return await self.kgdocuments.get_kgdocument(space_id, graph_id, uri)
    
    async def list_kgdocument_segments(self, space_id: str, graph_id: str, parent_uri: str):
        """List segments for a parent KGDocument."""
        return await self.kgdocuments.list_segments(space_id, graph_id, parent_uri)
    
    async def create_kgdocuments(self, space_id: str, graph_id: str, objects: List):
        """Create KGDocuments from GraphObjects."""
        return await self.kgdocuments.create_kgdocuments(space_id, graph_id, objects)
    
    async def update_kgdocuments(self, space_id: str, graph_id: str, objects: List):
        """Update KGDocuments from GraphObjects."""
        return await self.kgdocuments.update_kgdocuments(space_id, graph_id, objects)
    
    async def delete_kgdocument(self, space_id: str, graph_id: str, uri: str):
        """Delete a KGDocument by URI (cascades to segments)."""
        return await self.kgdocuments.delete_kgdocument(space_id, graph_id, uri)
    
    async def delete_kgdocuments_batch(self, space_id: str, graph_id: str, uri_list: str):
        """Delete multiple KGDocuments by URI list (cascades to segments)."""
        return await self.kgdocuments.delete_kgdocuments_batch(space_id, graph_id, uri_list)
    
    async def segment_document(self, space_id: str, graph_id: str, document_uri: str,
                               segment_method_uri: Optional[str] = None,
                               max_segment_tokens: Optional[int] = None):
        """Trigger segmentation for a KGDocument."""
        return await self.kgdocuments.segment_document(space_id, graph_id, document_uri, segment_method_uri, max_segment_tokens)
    
    async def get_segmentation_status(self, space_id: str, document_uri: Optional[str] = None,
                                      status: Optional[str] = None, limit: int = 50, offset: int = 0):
        """Get segmentation job status for a space or specific document."""
        return await self.kgdocuments.get_segmentation_status(space_id, document_uri, status, limit, offset)
    
    async def list_segmentation_configs(self, space_id: str, enabled_only: bool = False):
        """List segmentation configs for a space."""
        return await self.kgdocuments.list_segmentation_configs(space_id, enabled_only)

    async def create_segmentation_config(self, space_id: str, document_type_uri: str,
                                         segment_method_uri: str, max_segment_tokens: int = 512,
                                         min_segment_tokens: int = 50, overlap_tokens: int = 0,
                                         enabled: bool = True, auto_vectorize: bool = True):
        """Create a segmentation config."""
        return await self.kgdocuments.create_segmentation_config(
            space_id, document_type_uri, segment_method_uri,
            max_segment_tokens, min_segment_tokens, overlap_tokens, enabled, auto_vectorize)

    async def update_segmentation_config(self, space_id: str, config_id: int,
                                         document_type_uri: str, segment_method_uri: str,
                                         max_segment_tokens: int = 512, min_segment_tokens: int = 50,
                                         overlap_tokens: int = 0, enabled: bool = True,
                                         auto_vectorize: bool = True):
        """Update an existing segmentation config."""
        return await self.kgdocuments.update_segmentation_config(
            space_id, config_id, document_type_uri, segment_method_uri,
            max_segment_tokens, min_segment_tokens, overlap_tokens, enabled, auto_vectorize)

    async def delete_segmentation_config(self, space_id: str, config_id: int):
        """Delete a segmentation config."""
        return await self.kgdocuments.delete_segmentation_config(space_id, config_id)

    # KGFrame CRUD Methods - Delegated to KGFramesEndpoint
    
    async def list_kgframes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0,
                            search: Optional[str] = None, **kwargs) -> PaginatedGraphObjectResponse:
        """
        List KGFrames with pagination, filtering, and sorting.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            **kwargs: Additional filter params (sort_by, sort_order, form_type, etc.)
            
        Returns:
            PaginatedGraphObjectResponse containing KGFrame GraphObjects
        """
        return await self.kgframes.list_kgframes(space_id, graph_id, page_size, offset, search=search, **kwargs)
    
    async def get_kgframe(self, space_id: str, graph_id: str, uri: str) -> FrameGraphResponse:
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
    
    async def create_kgframes(self, space_id: str, graph_id: str, objects: List) -> CreateEntityResponse:
        """
        Create KGFrames from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances (KGFrames)
            
        Returns:
            FrameCreateResponse containing operation result
        """
        return await self.kgframes.create_kgframes(space_id, graph_id, objects)
    
    async def update_kgframes(self, space_id: str, graph_id: str, objects: List) -> UpdateEntityResponse:
        """
        Update KGFrames from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances (KGFrames)
            
        Returns:
            FrameUpdateResponse containing operation result
        """
        return await self.kgframes.update_kgframes(space_id, graph_id, objects)
    
    async def delete_kgframe(self, space_id: str, graph_id: str, uri: str) -> DeleteResponse:
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
    
    async def delete_kgframes_batch(self, space_id: str, graph_id: str, uri_list: str) -> DeleteResponse:
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
    
    async def get_kgframes_with_slots(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> PaginatedGraphObjectResponse:
        """
        Get KGFrames with their associated slots using pagination.
        
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

    async def get_entity_frame_slots(self, space_id: str, graph_id: str, frame_uri: str,
                                     entity_uri: Optional[str] = None,
                                     kg_slot_type: Optional[str] = None,
                                     sort_by: Optional[str] = None,
                                     sort_order: str = "asc",
                                     page_size: int = 10,
                                     offset: int = 0) -> PaginatedGraphObjectResponse:
        """
        Get the slots of one frame, sorted and paged.

        Counterpart to get_kgentity_frames — page an entity's frames, then page
        each frame's slots. sort_by takes a property URI such as
        haley-ai-kg#hasSlotSequence; unsequenced slots sort last either way.
        """
        return await self.kgframes.get_entity_frame_slots(
            space_id=space_id, graph_id=graph_id, frame_uri=frame_uri,
            entity_uri=entity_uri, kg_slot_type=kg_slot_type,
            sort_by=sort_by, sort_order=sort_order,
            page_size=page_size, offset=offset)
    
    async def create_kgframes_with_slots(self, space_id: str, graph_id: str, objects: List) -> CreateEntityResponse:
        """
        Create KGFrames with their associated slots from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances (KGFrames with slots)
            
        Returns:
            FrameCreateResponse containing operation result
        """
        return await self.kgframes.create_kgframes_with_slots(space_id, graph_id, objects)
    
    async def update_kgframes_with_slots(self, space_id: str, graph_id: str, objects: List) -> UpdateEntityResponse:
        """
        Update KGFrames with their associated slots from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances (KGFrames with slots)
            
        Returns:
            FrameUpdateResponse containing operation result
        """
        return await self.kgframes.update_kgframes_with_slots(space_id, graph_id, objects)
    
    async def delete_kgframes_with_slots(self, space_id: str, graph_id: str, uri_list: str) -> DeleteResponse:
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
    
    async def list_kgentities(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> PaginatedGraphObjectResponse:
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
    
    async def get_kgentity(self, space_id: str, graph_id: str, uri: str) -> EntityResponse:
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
    
    async def create_kgentities(self, space_id: str, graph_id: str, objects: List) -> CreateEntityResponse:
        """
        Create KGEntities from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances (KGEntities)
            
        Returns:
            EntityCreateResponse containing operation result
        """
        return await self.kgentities.create_kgentities(space_id, graph_id, objects)
    
    async def update_kgentities(self, space_id: str, graph_id: str, objects: List) -> UpdateEntityResponse:
        """
        Update KGEntities from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances (KGEntities)
            
        Returns:
            EntityUpdateResponse containing operation result
        """
        return await self.kgentities.update_kgentities(space_id, graph_id, objects)
    
    async def delete_kgentity(self, space_id: str, graph_id: str, uri: str) -> DeleteResponse:
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
    
    async def delete_kgentities_batch(self, space_id: str, graph_id: str, uri_list: str) -> DeleteResponse:
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
                           page_size: int = 10, offset: int = 0, search: Optional[str] = None,
                           sort_by: Optional[str] = None, sort_order: str = "asc",
                           include_slot_counts: bool = False) -> Dict[str, Any]:
        """
        Get frames associated with KGEntities.

        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Specific entity URI to get frames for (optional)
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            sort_by: Optional property URI to order frames by, e.g.
                haley-ai-kg#hasFrameSequence
            sort_order: 'asc' or 'desc'

        Returns:
            Dictionary containing entity frames data and pagination info
        """
        # Keyword args are required here: the endpoint signature has
        # frame_uris/parent_frame_uri between entity_uri and page_size, so a
        # positional call silently passed page_size as frame_uris.
        return await self.kgentities.get_kgentity_frames(
            space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
            page_size=page_size, offset=offset, search=search,
            sort_by=sort_by, sort_order=sort_order,
            include_slot_counts=include_slot_counts)
    
    # Object CRUD Methods - Delegated to ObjectsEndpoint
    
    async def list_objects(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> ObjectsListResponse:
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
    
    async def get_object(self, space_id: str, graph_id: str, uri: str) -> ObjectResponse:
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
    
    async def create_objects(self, space_id: str, graph_id: str, objects: List) -> ObjectCreateResponse:
        """
        Create Objects from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances
            
        Returns:
            ObjectCreateResponse containing operation result
        """
        return await self.objects.create_objects(space_id, graph_id, objects)
    
    async def update_objects(self, space_id: str, graph_id: str, objects: List) -> ObjectUpdateResponse:
        """
        Update Objects from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances
            
        Returns:
            ObjectUpdateResponse containing operation result
        """
        return await self.objects.update_objects(space_id, graph_id, objects)
    
    async def delete_object(self, space_id: str, graph_id: str, uri: str) -> ObjectDeleteResponse:
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
    
    async def delete_objects_batch(self, space_id: str, graph_id: str, uri_list: str) -> ObjectDeleteResponse:
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
    
    async def list_files(self, space_id: str, graph_id: Optional[str] = None, page_size: int = 100, offset: int = 0, file_filter: Optional[str] = None) -> FilesListResponse:
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
    
    async def get_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> FileResponse:
        """
        Get a specific file by URI.
        
        Args:
            space_id: Space identifier
            uri: File URI
            graph_id: Graph identifier (optional)
            
        Returns:
            FileResponse containing File data
        """
        return await self.files.get_file(space_id, uri, graph_id)
    
    async def create_file(self, space_id: str, objects: List, graph_id: Optional[str] = None) -> FileCreateResponse:
        """
        Create new file node (metadata only).
        
        Args:
            space_id: Space identifier
            objects: List of GraphObjects containing File metadata
            graph_id: Graph identifier (optional)
            
        Returns:
            FileCreateResponse containing operation result
        """
        return await self.files.create_file(space_id, objects, graph_id)
    
    async def update_file(self, space_id: str, objects: List, graph_id: Optional[str] = None) -> FileUpdateResponse:
        """
        Update file metadata.
        
        Args:
            space_id: Space identifier
            objects: List of GraphObjects containing File metadata
            graph_id: Graph identifier (optional)
            
        Returns:
            FileUpdateResponse containing operation result
        """
        return await self.files.update_file(space_id, objects, graph_id)
    
    async def delete_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> FileDeleteResponse:
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
    
    async def get_files_by_uris(self, space_id: str, uri_list: str, graph_id: Optional[str] = None) -> FilesListResponse:
        """
        Get multiple files by URI list.
        
        Args:
            space_id: Space identifier
            uri_list: Comma-separated list of File URIs
            graph_id: Graph identifier (optional)
            
        Returns:
            FilesListResponse containing multiple files
        """
        return await self.files.get_files_by_uris(space_id, uri_list, graph_id)
    
    async def upload_file_content(self, space_id: str, uri: str, file_path: str, graph_id: Optional[str] = None) -> FileUploadResponse:
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
    
    # Data Import Methods - Delegated to ImportEndpoint

    async def create_import_job(self, request: 'ImportJobCreate'):
        """Create a new import job."""
        return await self.imports.create_import_job(request)

    async def list_import_jobs(self, space_id: Optional[str] = None, status: Optional[str] = None,
                               page_size: int = 50, offset: int = 0) -> Dict[str, Any]:
        """List import jobs with optional filtering."""
        return await self.imports.list_import_jobs(space_id, status, page_size, offset)

    async def get_import_job(self, job_id: str) -> 'ImportJobResponse':
        """Get import job details by ID."""
        return await self.imports.get_import_job(job_id)

    async def delete_import_job(self, job_id: str) -> 'ImportDeleteResponse':
        """Cancel (if running) and delete import job."""
        return await self.imports.delete_import_job(job_id)

    async def upload_import_file(self, job_id: str, file_path: str) -> 'ImportUploadResponse':
        """Upload a file for an import job."""
        return await self.imports.upload_import_file(job_id, file_path)

    async def execute_import_job(self, job_id: str) -> 'ImportExecuteResponse':
        """Start background import execution."""
        return await self.imports.execute_import_job(job_id)

    async def get_import_status(self, job_id: str) -> 'ImportStatusResponse':
        """Get import progress / status."""
        return await self.imports.get_import_status(job_id)

    async def get_import_log(self, job_id: str) -> 'ImportLogResponse':
        """Get import log entries."""
        return await self.imports.get_import_log(job_id)

    # Data Export Methods - Delegated to ExportEndpoint

    async def create_export_job(self, request: 'ExportJobCreate'):
        """Create a new export job."""
        return await self.exports.create_export_job(request)

    async def list_export_jobs(self, space_id: Optional[str] = None, status: Optional[str] = None,
                               page_size: int = 50, offset: int = 0) -> Dict[str, Any]:
        """List export jobs with optional filtering."""
        return await self.exports.list_export_jobs(space_id, status, page_size, offset)

    async def get_export_job(self, job_id: str) -> 'ExportJobResponse':
        """Get export job details by ID."""
        return await self.exports.get_export_job(job_id)

    async def delete_export_job(self, job_id: str) -> 'ExportDeleteResponse':
        """Cancel (if running) and delete export job."""
        return await self.exports.delete_export_job(job_id)

    async def execute_export_job(self, job_id: str) -> 'ExportExecuteResponse':
        """Start background export execution."""
        return await self.exports.execute_export_job(job_id)

    async def get_export_status(self, job_id: str) -> 'ExportStatusResponse':
        """Get export progress / status."""
        return await self.exports.get_export_status(job_id)

    async def download_export_file(self, job_id: str, output_path: str) -> bool:
        """Download completed export file."""
        return await self.exports.download_export_file(job_id, output_path)
    
    # Graph Management Methods - Delegated to GraphsEndpoint
    
    async def list_graphs(self, space_id: str) -> GraphsListResponse:
        """
        List graphs in a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            GraphsListResponse with graphs list
        """
        return await self.graphs.list_graphs(space_id)
    
    async def get_graph_info(self, space_id: str, graph_uri: str) -> GraphResponse:
        """
        Get information about a specific graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI
            
        Returns:
            GraphResponse with graph info
        """
        return await self.graphs.get_graph_info(space_id, graph_uri)
    
    async def create_graph(self, space_id: str, graph_uri: str) -> GraphCreateResponse:
        """
        Create a new graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to create
            
        Returns:
            GraphCreateResponse with creation result
        """
        return await self.graphs.create_graph(space_id, graph_uri)
    
    async def drop_graph(self, space_id: str, graph_uri: str, silent: bool = False) -> GraphDeleteResponse:
        """
        Drop (delete) a graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to drop
            silent: Execute silently (optional)
            
        Returns:
            GraphDeleteResponse with deletion result
        """
        return await self.graphs.drop_graph(space_id, graph_uri, silent)
    
    async def clear_graph(self, space_id: str, graph_uri: str) -> GraphClearResponse:
        """
        Clear a graph (remove all triples but keep the graph).
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to clear
            
        Returns:
            GraphClearResponse with clear operation result
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
    
    async def add_triples(self, space_id: str, graph_id: str, quad_request: 'QuadRequest') -> 'TripleOperationResponse':
        """
        Add new triples/quads to the specified graph.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            quad_request: QuadRequest containing raw quads to add
            
        Returns:
            TripleOperationResponse containing operation result
        """
        return await self.triples.add_triples(space_id, graph_id, quad_request)
    
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
