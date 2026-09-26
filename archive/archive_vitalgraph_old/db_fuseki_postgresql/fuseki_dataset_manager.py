"""
Fuseki dataset manager for FUSEKI_POSTGRESQL hybrid backend.
Handles per-space Fuseki datasets and graph operations.
"""

import asyncio
import logging
import random
import time
from typing import Dict, Any, Optional, List
import aiohttp
import json
from urllib.parse import urljoin

from ...utils.resource_manager import track_session
from .fuseki_auth import FusekiAuthManager

logger = logging.getLogger(__name__)

# Transient HTTP status codes that warrant a retry
RETRYABLE_STATUS_CODES = {502, 503, 504}

# Transient exception types that warrant a retry
RETRYABLE_EXCEPTIONS = (
    aiohttp.ServerDisconnectedError,
    aiohttp.ClientConnectorError,
    aiohttp.ClientOSError,
    ConnectionResetError,
    ConnectionRefusedError,
    asyncio.TimeoutError,
)


class FusekiDatasetManager:
    """
    Manages Fuseki datasets for the FUSEKI_POSTGRESQL hybrid backend.
    
    Handles creation, deletion, and operations on per-space Fuseki datasets.
    Each space gets its own dedicated Fuseki dataset for optimal performance.
    Supports both basic authentication and Keycloak JWT authentication.
    """
    
    def __init__(self, fuseki_config: dict):
        """
        Initialize Fuseki dataset manager.
        
        Args:
            fuseki_config: Fuseki server configuration
        """
        self.config = fuseki_config
        self.server_url = fuseki_config.get('server_url', 'http://localhost:3030')
        self.username = fuseki_config.get('username', 'vitalgraph_user')
        self.password = fuseki_config.get('password', 'vitalgraph_pass')
        self.connection_limit = fuseki_config.get('connection_limit', 20)
        self.auto_register_datasets = fuseki_config.get('auto_register_datasets', False)
        self.session = None
        
        # Keycloak JWT authentication
        self.enable_authentication = fuseki_config.get('enable_authentication', False)
        self.auth_manager: Optional[FusekiAuthManager] = None
        
        if self.enable_authentication:
            keycloak_config = fuseki_config.get('keycloak', {})
            if keycloak_config:
                try:
                    self.auth_manager = FusekiAuthManager(keycloak_config)
                    logger.info("Keycloak JWT authentication enabled for Fuseki")
                except Exception as e:
                    logger.error(f"Failed to initialize Keycloak authentication: {e}")
                    self.enable_authentication = False
        
        # Remove trailing slash from server URL
        if self.server_url.endswith('/'):
            self.server_url = self.server_url[:-1]
        
        logger.info(f"FusekiDatasetManager initialized for server: {self.server_url}")
    
    async def connect(self) -> bool:
        """Initialize HTTP session for Fuseki operations."""
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            
            # Configure TCPConnector for ALB compatibility:
            # - keepalive_timeout < ALB idle timeout (default 60s) to avoid stale connections
            # - limit: max simultaneous connections in the pool
            # - enable_cleanup_closed: proactively clean up closed connections
            connector = aiohttp.TCPConnector(
                keepalive_timeout=15,
                limit=self.connection_limit,
                enable_cleanup_closed=True,
            )
            logger.info(f"Fuseki TCPConnector: limit={self.connection_limit}")
            
            # Create HTTP session with appropriate authentication
            if self.enable_authentication and self.auth_manager:
                # JWT authentication - no basic auth
                self.session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector,
                    headers={'Content-Type': 'application/json'}
                )
                
                # Obtain initial JWT token
                token = await self.auth_manager.get_token(self.session)
                if not token:
                    logger.error("Failed to obtain JWT token for Fuseki authentication")
                    await self.session.close()
                    return False
                
                logger.info("JWT token obtained successfully for Fuseki")
            else:
                # Basic authentication
                auth = aiohttp.BasicAuth(self.username, self.password)
                self.session = aiohttp.ClientSession(
                    auth=auth,
                    timeout=timeout,
                    connector=connector,
                    headers={'Content-Type': 'application/json'}
                )
            
            # Track the session for proper cleanup
            track_session(self.session)
            
            # Test connection to Fuseki server
            headers = {}
            if self.enable_authentication and self.auth_manager:
                headers.update(self.auth_manager.get_auth_headers())
            
            async with self.session.get(f"{self.server_url}/$/ping", headers=headers) as response:
                if response.status == 200:
                    logger.info("Connected to Fuseki server successfully")
                    return True
                else:
                    logger.error(f"Fuseki server ping failed: {response.status}")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to connect to Fuseki server: {e}")
            return False
    
    async def _request_with_retry(self, method: str, url: str, max_retries: int = 5,
                                   retry_base_delay: float = 0.5,
                                   additional_headers: Optional[Dict[str, str]] = None,
                                   **kwargs) -> aiohttp.ClientResponse:
        """
        Execute an HTTP request with retry logic for transient failures.
        
        Retries on:
        - HTTP 401 (expired JWT token — refreshes token before retry)
        - HTTP 502, 503, 504 (ALB/proxy transient errors)
        - aiohttp.ServerDisconnectedError (stale connection reuse)
        - aiohttp.ClientConnectorError (connection refused/reset)
        - ConnectionResetError, asyncio.TimeoutError
        
        Auth headers are refreshed on every attempt so retries never use
        a stale JWT token.
        
        Uses exponential backoff with jitter between retries.
        
        Args:
            method: HTTP method ('get', 'post', 'delete', etc.)
            url: Request URL
            max_retries: Maximum number of retry attempts (default: 5)
            retry_base_delay: Base delay in seconds for exponential backoff (default: 0.5)
            additional_headers: Extra headers (Content-Type, Accept, etc.) merged with
                fresh auth headers on every attempt
            **kwargs: Additional arguments passed to aiohttp request
            
        Returns:
            aiohttp.ClientResponse on success
            
        Raises:
            Last exception encountered if all retries exhausted
        """
        last_exception = None
        # Remove any caller-supplied 'headers' from kwargs; we build them ourselves
        kwargs.pop('headers', None)
        
        for attempt in range(max_retries + 1):
            try:
                # Refresh auth headers on every attempt so the JWT token is always current
                headers = await self._get_request_headers(additional_headers)
                
                request_func = getattr(self.session, method)
                response = await request_func(url, headers=headers, **kwargs)
                
                # Handle 401 (expired/invalid JWT) — force token refresh and retry
                if response.status == 401 and attempt < max_retries:
                    error_text = await response.text()
                    response.release()
                    if self.enable_authentication and self.auth_manager:
                        logger.warning(
                            f"Fuseki request {method.upper()} {url} returned 401 "
                            f"(attempt {attempt + 1}/{max_retries + 1}), refreshing JWT token and retrying"
                        )
                        # Force token refresh by resetting expiry
                        self.auth_manager.token_expiry = 0
                        await self.auth_manager.get_token(self.session)
                    else:
                        logger.warning(
                            f"Fuseki request {method.upper()} {url} returned 401 "
                            f"(attempt {attempt + 1}/{max_retries + 1}), retrying: {error_text[:200]}"
                        )
                    delay = retry_base_delay + random.uniform(0, 0.5)
                    await asyncio.sleep(delay)
                    continue
                
                # Check for retryable HTTP status codes
                if response.status in RETRYABLE_STATUS_CODES and attempt < max_retries:
                    error_text = await response.text()
                    response.release()
                    delay = retry_base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        f"Fuseki request {method.upper()} {url} returned {response.status} "
                        f"(attempt {attempt + 1}/{max_retries + 1}), retrying in {delay:.2f}s: {error_text[:200]}"
                    )
                    await asyncio.sleep(delay)
                    continue
                
                # On the final attempt, log if we're still getting a retryable status
                if response.status in RETRYABLE_STATUS_CODES or response.status == 401:
                    logger.error(
                        f"Fuseki request {method.upper()} {url} still returning {response.status} "
                        f"after {max_retries + 1} attempts — returning error response"
                    )
                
                return response
                
            except RETRYABLE_EXCEPTIONS as e:
                last_exception = e
                if attempt < max_retries:
                    delay = retry_base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        f"Fuseki request {method.upper()} {url} failed with {type(e).__name__}: {e} "
                        f"(attempt {attempt + 1}/{max_retries + 1}), retrying in {delay:.2f}s"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Fuseki request {method.upper()} {url} failed after {max_retries + 1} attempts "
                        f"with {type(e).__name__}: {e}"
                    )
                    raise
        
        # Should not reach here, but just in case
        if last_exception:
            raise last_exception
        raise RuntimeError(f"Unexpected retry loop exit for {method.upper()} {url}")
    
    async def _get_request_headers(self, additional_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        Get HTTP headers with authentication for Fuseki requests.
        
        Args:
            additional_headers: Optional additional headers to include
            
        Returns:
            Dictionary of headers including authentication if enabled
        """
        headers = additional_headers.copy() if additional_headers else {}
        
        # Add JWT authentication headers if enabled
        if self.enable_authentication and self.auth_manager:
            # Refresh token if needed
            await self.auth_manager.refresh_token_if_needed(self.session)
            # Add authorization header
            headers.update(self.auth_manager.get_auth_headers())
        
        return headers
    
    async def disconnect(self) -> bool:
        """Close HTTP session with proper cleanup."""
        try:
            if self.session:
                # Ensure all connections are properly closed
                await self.session.close()
                # Give time for the session to fully close
                import asyncio
                await asyncio.sleep(0.1)
                self.session = None
            
            logger.info("Disconnected from Fuseki server")
            return True
            
        except Exception as e:
            logger.error(f"Error disconnecting from Fuseki server: {e}")
            return False
    
    def get_dataset_name(self, space_id: str) -> str:
        """Get Fuseki dataset name for a space."""
        return f"vitalgraph_space_{space_id}"
    
    async def ensure_datasets_registered(self, space_ids: List[str]) -> dict:
        """
        Ensure all known spaces have registered Fuseki datasets.
        
        Checks Fuseki for each dataset one-at-a-time (safe for multiple
        instances starting concurrently) and registers any that are missing.
        Fuseki returns 409 if the dataset already exists, which is handled
        gracefully.
        
        Args:
            space_ids: List of space identifiers to ensure
            
        Returns:
            Dict with 'registered', 'already_existed', 'failed' counts
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        if not self.auto_register_datasets:
            logger.info("Fuseki auto-register disabled by config")
            return {'registered': 0, 'already_existed': 0, 'failed': 0}
        
        logger.info(f"Ensuring {len(space_ids)} Fuseki datasets are registered...")
        
        # Fetch currently registered datasets once
        registered_names = set()
        try:
            headers = await self._get_request_headers()
            async with self.session.get(
                f"{self.server_url}/$/datasets", headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    for ds in data.get('datasets', []):
                        # ds.name includes leading slash: "/vitalgraph_space_foo"
                        name = ds.get('ds.name', '').lstrip('/')
                        registered_names.add(name)
                    logger.info(f"Fuseki has {len(registered_names)} datasets registered")
                else:
                    logger.warning(f"Could not list Fuseki datasets: {response.status}")
        except Exception as e:
            logger.warning(f"Could not list Fuseki datasets: {e}")
        
        stats = {'registered': 0, 'already_existed': 0, 'failed': 0}
        
        for space_id in space_ids:
            dataset_name = self.get_dataset_name(space_id)
            
            if dataset_name in registered_names:
                stats['already_existed'] += 1
                continue
            
            # Dataset not registered — register it one-at-a-time
            try:
                logger.info(f"Registering missing Fuseki dataset: {dataset_name}")
                headers = await self._get_request_headers()
                async with self.session.post(
                    f"{self.server_url}/$/datasets",
                    params={'dbName': dataset_name, 'dbType': 'tdb2'},
                    headers=headers
                ) as response:
                    if response.status in [200, 201]:
                        stats['registered'] += 1
                        logger.info(f"Registered Fuseki dataset: {dataset_name}")
                    elif response.status == 409:
                        stats['already_existed'] += 1
                        logger.debug(f"Fuseki dataset already exists (race): {dataset_name}")
                    else:
                        error_text = await response.text()
                        stats['failed'] += 1
                        logger.error(f"Failed to register Fuseki dataset {dataset_name}: {response.status} - {error_text}")
            except Exception as e:
                stats['failed'] += 1
                logger.error(f"Error registering Fuseki dataset {dataset_name}: {e}")
        
        logger.info(
            f"Fuseki dataset registration complete: "
            f"{stats['registered']} registered, "
            f"{stats['already_existed']} already existed, "
            f"{stats['failed']} failed"
        )
        return stats

    async def create_dataset(self, space_id: str) -> bool:
        """
        Create a new Fuseki dataset for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            True if dataset created successfully, False otherwise
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            logger.debug(f"Creating Fuseki dataset: {dataset_name}")
            
            # Create dataset using Fuseki admin API
            # Use URL parameters instead of form data
            params = {
                "dbName": dataset_name,
                "dbType": "tdb2"
            }
            
            # Get headers with authentication
            headers = await self._get_request_headers()
            
            async with self.session.post(
                f"{self.server_url}/$/datasets",
                params=params,
                headers=headers
            ) as response:
                if response.status in [200, 201]:
                    logger.debug(f"Fuseki dataset created successfully: {dataset_name}")
                    return True
                elif response.status == 409:
                    logger.debug(f"Fuseki dataset already exists: {dataset_name}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to create Fuseki dataset {dataset_name}: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error creating Fuseki dataset {dataset_name}: {e}")
            return False
    
    async def delete_dataset(self, space_id: str) -> bool:
        """
        Delete a Fuseki dataset for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            True if dataset deleted successfully, False otherwise
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            logger.debug(f"Deleting Fuseki dataset: {dataset_name}")
            
            # Get headers with authentication
            headers = await self._get_request_headers()
            
            # Delete dataset using Fuseki admin API
            async with self.session.delete(
                f"{self.server_url}/$/datasets/{dataset_name}",
                headers=headers
            ) as response:
                if response.status in [200, 204]:
                    logger.debug(f"Fuseki dataset deleted successfully: {dataset_name}")
                    return True
                elif response.status == 404:
                    logger.debug(f"Fuseki dataset not found (already deleted): {dataset_name}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to delete Fuseki dataset {dataset_name}: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error deleting Fuseki dataset {dataset_name}: {e}")
            return False
    
    async def list_datasets(self) -> List[str]:
        """
        List all available Fuseki datasets.
        
        Returns:
            List of dataset names
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        try:
            # Get headers with authentication
            headers = await self._get_request_headers()
            
            # Get datasets using Fuseki admin API
            async with self.session.get(f"{self.server_url}/$/datasets", headers=headers) as response:
                if response.status == 200:
                    datasets_info = await response.json()
                    datasets = datasets_info.get('datasets', [])
                    
                    # Extract dataset names (remove leading slash)
                    dataset_names = []
                    for dataset in datasets:
                        name = dataset.get('ds.name', '')
                        if name.startswith('/'):
                            name = name[1:]  # Remove leading slash
                        if name:
                            dataset_names.append(name)
                    
                    return dataset_names
                else:
                    logger.error(f"Failed to list Fuseki datasets: {response.status}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error listing Fuseki datasets: {e}")
            return []
    
    async def dataset_exists(self, space_id: str) -> bool:
        """
        Check if a Fuseki dataset exists for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            True if dataset exists, False otherwise
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            # Get headers with authentication
            headers = await self._get_request_headers()
            
            # Check dataset existence using Fuseki admin API
            async with self.session.get(f"{self.server_url}/$/datasets", headers=headers) as response:
                if response.status == 200:
                    datasets_info = await response.json()
                    datasets = datasets_info.get('datasets', [])
                    
                    logger.debug(f"🔍 Fuseki datasets list: {datasets}")
                    logger.debug(f"🔍 Looking for dataset: {dataset_name}")
                    
                    for dataset in datasets:
                        ds_name = dataset.get('ds.name', '')
                        logger.debug(f"🔍 Found dataset: {ds_name}")
                        if ds_name == f"/{dataset_name}" or ds_name == dataset_name:
                            logger.debug(f"✅ Dataset {dataset_name} found!")
                            return True
                    
                    logger.debug(f"❌ Dataset {dataset_name} not found in list")
                    return False
                else:
                    logger.error(f"Failed to list Fuseki datasets: {response.status}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error checking Fuseki dataset existence {dataset_name}: {e}")
            return False
    
    async def add_quads_to_dataset(self, space_id: str, quads: List[tuple], 
                                   convert_float_to_decimal: bool = False) -> bool:
        """
        Add RDF quads to a Fuseki dataset.
        
        Args:
            space_id: Space identifier
            quads: List of RDF quads to add
            convert_float_to_decimal: If True, convert xsd:float to xsd:decimal
                                     to preserve precision in Fuseki (default: False)
            
        Returns:
            True if quads added successfully, False otherwise
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            logger.debug(f"Adding {len(quads)} quads to Fuseki dataset: {dataset_name}")
            logger.debug(f"🔍 add_quads_to_dataset: space_id={space_id}, dataset_name={dataset_name}")
            
            # Log the type of the first quad's components to diagnose the issue
            if quads:
                first_quad = quads[0]
                if len(first_quad) >= 4:
                    s, p, o, g = first_quad[:4]
                    logger.debug(f"🔍 First quad types: S={type(s).__name__}, P={type(p).__name__}, O={type(o).__name__}, G={type(g).__name__}")
                    logger.debug(f"🔍 First quad values: S={repr(s)}, P={repr(p)}, O={repr(o)[:100] if len(repr(o)) > 100 else repr(o)}")
            
            
            # Convert quads to SPARQL INSERT DATA format with optional float-to-decimal conversion
            insert_data_content = self._quads_to_sparql_insert_data(quads, convert_float_to_decimal)
            # logger.info(f"🔍 Generated SPARQL INSERT DATA content:\n{insert_data_content}")
            
            # Upload data using SPARQL UPDATE with proper graph syntax
            # Ensure proper indentation and no line break issues
            formatted_content = insert_data_content.strip()
            update_query = f"""INSERT DATA {{
{formatted_content}
}}"""
            
            
            # logger.info(f"🔍 Generated SPARQL UPDATE query:\n{update_query}")
            
            fuseki_url = f"{self.server_url}/{dataset_name}/update"
            logger.debug(f"🔍 Fuseki request URL: {fuseki_url}")
            logger.debug(f"🔍 Dataset name: {dataset_name}")
            logger.debug(f"🔍 Space ID: {space_id}")
            # logger.info(f"🔍 Full SPARQL UPDATE request:\n{update_query}")
            
            logger.debug(f"🔍 Sending SPARQL UPDATE to: {fuseki_url}")
            
            response = await self._request_with_retry(
                'post',
                fuseki_url,
                additional_headers={'Content-Type': 'application/sparql-update'},
                data=update_query
            )
            async with response:
                response_text = await response.text()
                response_headers = dict(response.headers)
                logger.debug(f"🔍 Full Fuseki response:")
                logger.debug(f"🔍   Status: {response.status}")
                logger.debug(f"🔍   Headers: {response_headers}")
                logger.debug(f"🔍   Body: '{response_text}'")
                
                if response.status in [200, 204]:
                    logger.debug(f"✅ Fuseki INSERT DATA successful: {dataset_name}")
                    return True
                else:
                    logger.error(f"❌ Failed to add quads to dataset {dataset_name}: {response.status} - {response_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error adding quads to dataset {dataset_name}: {e}")
            return False
    
    async def query_dataset(self, space_id: str, sparql_query: str) -> List[tuple]:
        """
        Execute SPARQL query on a Fuseki dataset.
        
        Args:
            space_id: Space identifier
            sparql_query: SPARQL query to execute
            
        Returns:
            Query results as list of dictionaries
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            logger.debug(f"Executing SPARQL query on dataset: {dataset_name}")
            
            response = await self._request_with_retry(
                'post',
                f"{self.server_url}/{dataset_name}/sparql",
                additional_headers={
                    'Content-Type': 'application/sparql-query',
                    'Accept': 'application/sparql-results+json'
                },
                data=sparql_query
            )
            async with response:
                if response.status == 200:
                    result = await response.json()
                    # Handle ASK queries which return boolean results
                    if 'boolean' in result:
                        return result  # Return the full result for ASK queries
                    else:
                        return result.get('results', {}).get('bindings', [])
                else:
                    error_text = await response.text()
                    logger.error(f"SPARQL query failed on dataset {dataset_name}: {response.status} - {error_text}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error executing SPARQL query on dataset {dataset_name}: {e}")
            return []
    
    async def construct_dataset(self, space_id: str, sparql_construct: str) -> List[tuple]:
        """
        Execute SPARQL CONSTRUCT query on a Fuseki dataset.
        
        Args:
            space_id: Space identifier
            sparql_construct: SPARQL CONSTRUCT query to execute
            
        Returns:
            Constructed triples as list of tuples
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            logger.debug(f"Executing SPARQL CONSTRUCT query on dataset: {dataset_name}")
            
            response = await self._request_with_retry(
                'post',
                f"{self.server_url}/{dataset_name}/sparql",
                additional_headers={
                    'Content-Type': 'application/sparql-query',
                    'Accept': 'application/n-triples'
                },
                data=sparql_construct
            )
            async with response:
                if response.status == 200:
                    ntriples_text = await response.text()
                    # Parse N-Triples format using RDFLib to get proper RDF objects
                    from rdflib import Graph
                    graph = Graph()
                    try:
                        graph.parse(data=ntriples_text, format='nt')
                        triples = list(graph)
                        return triples
                    except Exception as parse_error:
                        logger.error(f"Error parsing N-Triples response: {parse_error}")
                        return []
                else:
                    error_text = await response.text()
                    logger.error(f"SPARQL CONSTRUCT failed on dataset {dataset_name}: {response.status} - {error_text}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error executing SPARQL CONSTRUCT on dataset {dataset_name}: {e}")
            return []
    
    async def update_dataset(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute SPARQL UPDATE against dataset.
        
        Args:
            space_id: Space identifier
            sparql_update: SPARQL UPDATE query
            
        Returns:
            True if update successful, False otherwise
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            logger.debug(f"Executing SPARQL UPDATE on dataset: {dataset_name}")
            
            response = await self._request_with_retry(
                'post',
                f"{self.server_url}/{dataset_name}/update",
                additional_headers={
                    'Content-Type': 'application/sparql-update',
                    'Accept': 'application/json'
                },
                data=sparql_update
            )
            async with response:
                if response.status in [200, 204]:
                    logger.debug(f"SPARQL UPDATE successful on dataset {dataset_name}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"SPARQL UPDATE failed on dataset {dataset_name}: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error executing SPARQL UPDATE on dataset {dataset_name}: {e}")
            return False
    
    async def get_dataset_info(self, space_id: str, graph_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get information about a Fuseki dataset.
        
        Args:
            space_id: Space identifier
            
        Returns:
            Dataset information dictionary or None if not found
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            # Get dataset stats using SPARQL query
            if graph_id:
                count_query = f"SELECT (COUNT(*) AS ?count) WHERE {{ GRAPH <{graph_id}> {{ ?s ?p ?o }} }}"
                logger.debug(f"🔍 Counting triples in specific graph: {graph_id}")
            else:
                count_query = "SELECT (COUNT(*) AS ?count) WHERE { GRAPH ?g { ?s ?p ?o } }"
                logger.debug(f"🔍 Counting triples across all graphs using GRAPH ?g")
            
            # Use POST method for SPARQL queries (standard approach)
            query_url = f"{self.server_url}/{dataset_name}/sparql"
            logger.debug(f"🔍 Querying dataset for count: {query_url}")
            
            response = await self._request_with_retry(
                'post',
                query_url,
                additional_headers={
                    'Content-Type': 'application/sparql-query',
                    'Accept': 'application/json'
                },
                data=count_query
            )
            async with response:
                logger.debug(f"🔍 Fuseki query response status: {response.status}")
                if response.status == 200:
                    result = await response.json()
                    logger.debug(f"🔍 Fuseki query result: {result}")
                    bindings = result.get('results', {}).get('bindings', [])
                    logger.debug(f"🔍 Bindings count: {len(bindings)}")
                    
                    if bindings:
                        # Fuseki HTTP JSON responses always return dict bindings
                        binding = bindings[0]
                        count = int(binding.get('count', {}).get('value', 0))
                        return {
                            'dataset_name': dataset_name,
                            'space_id': space_id,
                            'triple_count': count,
                            'server_url': self.server_url
                        }
                    
                    logger.warning(f"🔍 No bindings returned from Fuseki query for {dataset_name}")
                    return None
                else:
                    response_text = await response.text()
                    logger.error(f"🔍 Fuseki query failed with status {response.status}: {response_text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error getting dataset info for {dataset_name}: {e}")
            return None
    
    def _quads_to_sparql_insert_data(self, quads: List[tuple], convert_float_to_decimal: bool = False) -> str:
        """
        Convert quads to SPARQL INSERT DATA format with proper GRAPH stanzas.
        Groups triples by unique graph URI and creates separate GRAPH blocks.
        
        Args:
            quads: List of quad tuples (subject, predicate, object, graph)
            convert_float_to_decimal: If True, convert xsd:float to xsd:decimal
                                     to preserve precision in Fuseki (default: False)
            
        Returns:
            SPARQL INSERT DATA formatted string with GRAPH blocks
        """
        # Group triples by unique graph URI
        graphs_data = {}
        
        for quad in quads:
            # Handle tuple format: (subject, predicate, object, graph)
            if len(quad) >= 4:
                subject, predicate, obj, graph = quad[:4]
            else:
                subject, predicate, obj = quad[:3]
                graph = 'default'
            
            # Log the types of quad components to diagnose formatting issues
            # logger.info(f"🔍 Quad component types: S={type(subject).__name__}, P={type(predicate).__name__}, O={type(obj).__name__}")
            
            # Format terms with float-to-decimal conversion
            subject = self._format_term(subject, convert_float_to_decimal)
            predicate = self._format_term(predicate, convert_float_to_decimal)
            obj = self._format_term(obj, convert_float_to_decimal)
            
            # Keep graph as raw value for grouping, format later
            graph_key = str(graph) if graph != 'default' else 'default'
            
            # logger.info(f"🔍 Processing quad: S={subject}, P={predicate}, O={obj}, G={graph_key}")
            
            if subject is not None and predicate is not None and obj is not None:
                if graph_key not in graphs_data:
                    graphs_data[graph_key] = []
                graphs_data[graph_key].append(f"                    {subject} {predicate} {obj} .")
        
        # Generate separate GRAPH stanza for each unique graph URI
        graph_stanzas = []
        for graph_uri, triples in graphs_data.items():
            if graph_uri == 'default':
                # Default graph triples (no GRAPH wrapper needed)
                graph_stanzas.extend(triples)
            else:
                # Named graph - create GRAPH stanza
                # Validate that graph_uri is a proper URI
                from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                if not validate_rfc3986(str(graph_uri), rule='URI'):
                    logger.error(f"❌ Invalid graph URI: {graph_uri} - must be a valid URI with scheme")
                    raise ValueError(f"Invalid graph URI: {graph_uri} - must be a valid URI with scheme (e.g., http://...)")
                
                formatted_graph = self._format_term(graph_uri, convert_float_to_decimal)
                if not formatted_graph:
                    logger.error(f"❌ Failed to format graph URI: {graph_uri}")
                    raise ValueError(f"Failed to format graph URI: {graph_uri}")
                    
                graph_stanzas.append(f"                GRAPH {formatted_graph} {{")
                graph_stanzas.extend(triples)
                graph_stanzas.append(f"                }}")
        
        logger.debug(f"🔍 Generated {len(graphs_data)} graph stanzas for {len(quads)} quads")
        return '\n'.join(graph_stanzas)
    
    def _format_term(self, term: Any, convert_float_to_decimal: bool = False) -> Optional[str]:
        """
        Format an RDF term for N-Quads.
        
        Args:
            term: RDF term (URI, literal, or blank node)
            convert_float_to_decimal: If True, convert xsd:float to xsd:decimal
                                     to preserve precision in Fuseki (default: False)
            
        Returns:
            Formatted term string or None
        """
        if term is None:
            return None
        
        # Handle RDFLib objects
        try:
            from rdflib import URIRef, Literal, BNode
            
            # logger.info(f"🔍 _format_term input: {term} (type: {type(term).__name__})")
            
            if isinstance(term, URIRef):
                # Ensure clean URI formatting - strip any existing angle brackets
                clean_uri = str(term).strip('<>')
                result = f"<{clean_uri}>"
                # logger.info(f"🔍 URIRef formatted: {result}")
                return result
            elif isinstance(term, Literal):
                # Escape backslashes and double quotes in literal values for SPARQL
                escaped_value = str(term).replace('\\', '\\\\').replace('"', '\\"')
                
                if term.language:
                    result = f'"{escaped_value}"@{term.language}'
                elif term.datatype:
                    datatype_str = str(term.datatype)
                    # Convert xsd:float to xsd:decimal to preserve precision in Fuseki
                    if convert_float_to_decimal and datatype_str == 'http://www.w3.org/2001/XMLSchema#float':
                        datatype_str = 'http://www.w3.org/2001/XMLSchema#decimal'
                        logger.debug(f"Converting float to decimal for value: {escaped_value}")
                    result = f'"{escaped_value}"^^<{datatype_str}>'
                else:
                    result = f'"{escaped_value}"'
                # logger.info(f"🔍 Literal formatted: {result}")
                return result
            elif isinstance(term, BNode):
                result = f"_:{term}"
                # logger.info(f"🔍 BNode formatted: {result}")
                return result
        except ImportError:
            pass
        
        if isinstance(term, dict):
            term_type = term.get('type')
            value = term.get('value')
            
            if term_type == 'uri':
                # Ensure clean URI formatting - strip any existing angle brackets
                clean_uri = str(value).strip('<>')
                return f"<{clean_uri}>"
            elif term_type == 'literal':
                datatype = term.get('datatype')
                language = term.get('language')
                
                if language:
                    return f'"{value}"@{language}'
                elif datatype:
                    # Convert xsd:float to xsd:decimal to preserve precision in Fuseki
                    if convert_float_to_decimal and datatype == 'http://www.w3.org/2001/XMLSchema#float':
                        datatype = 'http://www.w3.org/2001/XMLSchema#decimal'
                        logger.debug(f"Converting float to decimal for value: {value}")
                    return f'"{value}"^^<{datatype}>'
                else:
                    return f'"{value}"'
            elif term_type == 'bnode':
                return f"_:{value}"
        
        elif isinstance(term, str):
            # Check if string looks like a URI, otherwise treat as literal
            from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
            if validate_rfc3986(term, rule='URI'):
                # Clean URI formatting - strip any existing angle brackets
                clean_uri = term.strip('<>')
                return f"<{clean_uri}>"
            else:
                # Treat as string literal - escape quotes and wrap in quotes
                escaped_literal = term.replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
                return f'"{escaped_literal}"'
        
        return None
    
    async def ask_dataset(self, space_id: str, sparql_query: str) -> bool:
        """
        Execute SPARQL ASK query against a dataset.
        
        Args:
            space_id: Space identifier
            sparql_query: SPARQL ASK query to execute
            
        Returns:
            bool: True if ASK query returns true, False otherwise
        """
        if not self.session:
            logger.error("FusekiDatasetManager not connected")
            return False
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            # Construct query URL for the dataset
            query_url = f"{self.server_url}/{dataset_name}/sparql"
            
            # Execute ASK query using POST with proper headers and retry
            response = await self._request_with_retry(
                'post',
                query_url,
                additional_headers={
                    'Content-Type': 'application/sparql-query',
                    'Accept': 'application/sparql-results+json'
                },
                data=sparql_query
            )
            async with response:
                if response.status == 200:
                    # Parse JSON response for ASK query
                    result = await response.json()
                    
                    # ASK queries return {"boolean": true/false}
                    if isinstance(result, dict) and 'boolean' in result:
                        return result['boolean']
                    else:
                        logger.warning(f"Unexpected ASK query response format: {result}")
                        return False
                        
                else:
                    logger.error(f"ASK query failed with status {response.status}: {await response.text()}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error executing ASK query on dataset {dataset_name}: {e}")
            return False
