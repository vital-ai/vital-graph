"""
VitalGraph Client Configuration Loader

This module provides functionality to load and validate VitalGraph client configuration
from profile-based environment variables for connecting to VitalGraph API servers.
"""

import os
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ClientConfigurationError(Exception):
    """Raised when there are client configuration loading or validation errors."""
    pass


class VitalGraphClientConfig:
    """
    VitalGraph client configuration loader and manager.
    
    Loads configuration from profile-based environment variables.
    Uses VITALGRAPH_CLIENT_ENVIRONMENT to determine which profile to load.
    """
    
    def __init__(self):
        """
        Initialize the client configuration loader.
        
        Configuration is loaded from profile-prefixed environment variables.
        Set VITALGRAPH_CLIENT_ENVIRONMENT to select profile (local, dev, staging, prod).
        
        Example:
            export VITALGRAPH_CLIENT_ENVIRONMENT=local
            export LOCAL_CLIENT_SERVER_URL=http://localhost:8001
            export LOCAL_CLIENT_AUTH_USERNAME=admin
            export LOCAL_CLIENT_AUTH_PASSWORD=admin
        """
        self.environment = os.getenv('VITALGRAPH_CLIENT_ENVIRONMENT', 'local').upper()
        self.config_data: Dict[str, Any] = self._load_from_env()
        self.config_path: Optional[str] = None
        logger.info(f"Loaded client configuration from {self.environment}_CLIENT_* environment variables")
    
    def _get_profile_env(self, key: str, default: str = '') -> str:
        """
        Get environment variable with profile prefix.
        
        Example: If VITALGRAPH_CLIENT_ENVIRONMENT=local and key='SERVER_URL',
                 looks for LOCAL_CLIENT_SERVER_URL, falls back to CLIENT_SERVER_URL, then default.
        
        Args:
            key: Environment variable key (without profile prefix)
            default: Default value if not found
            
        Returns:
            Environment variable value
        """
        # Try profile-prefixed variable first (e.g., LOCAL_CLIENT_SERVER_URL)
        profile_key = f"{self.environment}_CLIENT_{key}"
        value = os.getenv(profile_key)
        if value is not None:
            return value
        
        # Fall back to unprefixed variable (e.g., CLIENT_SERVER_URL)
        unprefixed_key = f"CLIENT_{key}"
        value = os.getenv(unprefixed_key)
        if value is not None:
            return value
        
        # Use default
        return default
    
    def _load_from_env(self) -> Dict[str, Any]:
        """
        Load configuration from profile-prefixed environment variables.
        
        Uses VITALGRAPH_CLIENT_ENVIRONMENT to determine prefix (LOCAL_, PROD_, etc.)
        Falls back to unprefixed variables, then defaults.
        
        Returns:
            Complete configuration dictionary
        """
        return {
            'server': {
                # NO DEFAULT. A client that silently picks a server picks the
                # WRONG one: this used to fall back to http://localhost:8001,
                # which is the dev app talking to the host database, while the
                # test stack is :8002 against the container database. Anything
                # constructed without configuration — 109 bare
                # `VitalGraphClient()` calls in this repo — went to dev and said
                # nothing, so a suite could call one database and assert against
                # another (issues/099).
                #
                # Empty here; `get_server_url` raises. Failing at the point of
                # use with the variable names is worth more than a default that
                # is right on one machine.
                'url': self._get_profile_env('SERVER_URL', ''),
                'api_base_path': self._get_profile_env('API_BASE_PATH', '/api/v1')
            },
            'auth': {
                'username': self._get_profile_env('AUTH_USERNAME', 'admin'),
                'password': self._get_profile_env('AUTH_PASSWORD', 'admin')
            },
            'client': {
                # Transport timeouts (seconds). 'timeout' is the read/write
                # timeout; connect and pool get their own, much shorter, values.
                'timeout': float(self._get_profile_env('TIMEOUT', '30')),
                'connect_timeout': float(self._get_profile_env('CONNECT_TIMEOUT', '5')),
                'pool_timeout': float(self._get_profile_env('POOL_TIMEOUT', '5')),
                # Total wall-clock ceiling for one logical call, covering every
                # retry attempt and every backoff sleep between them.
                'request_budget': float(self._get_profile_env('REQUEST_BUDGET', '60')),
                # Retry policy
                'max_retries': int(self._get_profile_env('MAX_RETRIES', '3')),
                'retry_delay': float(self._get_profile_env('RETRY_DELAY', '1')),
                'retry_backoff_base': float(self._get_profile_env('RETRY_BACKOFF_BASE', '2.0')),
                'retry_max_delay': float(self._get_profile_env('RETRY_MAX_DELAY', '10')),
                # Connection pool
                'max_connections': int(self._get_profile_env('MAX_CONNECTIONS', '100')),
                'max_keepalive': int(self._get_profile_env('MAX_KEEPALIVE', '20')),
                'keepalive_expiry': float(self._get_profile_env('KEEPALIVE_EXPIRY', '5')),
                # Client-side in-flight cap; 0 disables.
                'max_concurrency': int(self._get_profile_env('MAX_CONCURRENCY', '0')),
                # Circuit breaker; threshold 0 disables.
                'breaker_threshold': int(self._get_profile_env('BREAKER_THRESHOLD', '5')),
                'breaker_reset': float(self._get_profile_env('BREAKER_RESET', '30')),
            }
        }
    
    def get_server_config(self) -> Dict[str, Any]:
        """
        Get server configuration section.
        
        Returns:
            Dictionary containing server configuration
        """
        return self.config_data.get('server', {})
    
    def get_auth_config(self) -> Dict[str, Any]:
        """
        Get authentication configuration section.
        
        Returns:
            Dictionary containing auth configuration
        """
        return self.config_data.get('auth', {})
    
    def get_client_config(self) -> Dict[str, Any]:
        """
        Get client configuration section.
        
        Returns:
            Dictionary containing client configuration
        """
        return self.config_data.get('client', {})
    
    def get_server_url(self) -> str:
        """Get the VitalGraph API server URL.

        Raises:
            ClientConfigurationError: if no URL is configured. There is
                deliberately no default — see `_load_from_env`.
        """
        server_config = self.get_server_config()
        url = (server_config.get('url') or '').strip()
        if not url:
            raise ClientConfigurationError(
                f"No VitalGraph server URL configured. Set "
                f"{self.environment}_CLIENT_SERVER_URL (or CLIENT_SERVER_URL) — "
                f"for example http://localhost:8002 for the docker test stack, "
                f"or http://localhost:8001 for a local dev server. "
                f"VITALGRAPH_CLIENT_ENVIRONMENT is currently "
                f"{self.environment!r}.")
        return url
    
    def get_api_base_path(self) -> str:
        """
        Get the API base path.
        
        Returns:
            API base path string
        """
        server_config = self.get_server_config()
        return server_config.get('api_base_path', '/api/v1')
    
    def get_credentials(self) -> tuple[str, str]:
        """
        Get username and password for authentication.
        
        Returns:
            Tuple of (username, password)
        """
        auth_config = self.get_auth_config()
        username = auth_config.get('username', 'admin')
        password = auth_config.get('password', 'admin')
        return username, password
    
    def get_timeout(self) -> float:
        """
        Get the read/write timeout in seconds for a single attempt.

        Must not be below the server's own per-statement fence, currently 60s
        (`command_timeout` in sparql_sql_db_impl). At 30s the client always gave
        up first, so the server never got to surface the error — it just kept
        executing an abandoned query while the client retried and started a
        second copy of it. See issues/044.

        Matching the 60s request budget also means a timed-out request is not
        retried, which is the intent: a query cancelled for taking too long is
        not a transient fault, and retrying it doubles load at the worst moment.

        Returns:
            Timeout in seconds
        """
        client_config = self.get_client_config()
        return float(client_config.get('timeout', 60))

    def get_connect_timeout(self) -> float:
        """
        Get the connection-establishment timeout in seconds.

        A long connect timeout is never useful: a server that will accept the
        connection accepts it in well under a second.

        Returns:
            Connect timeout in seconds
        """
        client_config = self.get_client_config()
        return float(client_config.get('connect_timeout', 5))

    def get_pool_timeout(self) -> float:
        """
        Get the timeout for acquiring a connection from the pool.

        Returns:
            Pool acquisition timeout in seconds
        """
        client_config = self.get_client_config()
        return float(client_config.get('pool_timeout', 5))

    def get_request_budget(self) -> float:
        """
        Get the total wall-clock ceiling for one logical call.

        This bounds all attempts and all backoff sleeps together, so a single
        call can never hold a caller (a request handler, a Celery slot) for
        longer than this regardless of how the retries play out.

        Returns:
            Per-call budget in seconds
        """
        client_config = self.get_client_config()
        return float(client_config.get('request_budget', 60))

    def get_max_retries(self) -> int:
        """
        Get the maximum number of retry attempts (after the first attempt).

        Returns:
            Maximum retry attempts
        """
        client_config = self.get_client_config()
        return int(client_config.get('max_retries', 3))

    def get_retry_delay(self) -> float:
        """
        Get the base delay for retry backoff in seconds.

        Returns:
            Base retry delay in seconds
        """
        client_config = self.get_client_config()
        return float(client_config.get('retry_delay', 1))

    def get_retry_backoff_base(self) -> float:
        """
        Get the exponential growth factor applied per retry attempt.

        Returns:
            Backoff base (1.0 disables growth)
        """
        client_config = self.get_client_config()
        return float(client_config.get('retry_backoff_base', 2.0))

    def get_retry_max_delay(self) -> float:
        """
        Get the ceiling on the pre-jitter backoff delay.

        Returns:
            Maximum retry delay in seconds
        """
        client_config = self.get_client_config()
        return float(client_config.get('retry_max_delay', 10))

    def get_max_connections(self) -> int:
        """
        Get the maximum number of pooled connections.

        Returns:
            Maximum connections
        """
        client_config = self.get_client_config()
        return int(client_config.get('max_connections', 100))

    def get_max_keepalive(self) -> int:
        """
        Get the maximum number of idle keep-alive connections.

        Returns:
            Maximum keep-alive connections
        """
        client_config = self.get_client_config()
        return int(client_config.get('max_keepalive', 20))

    def get_keepalive_expiry(self) -> float:
        """
        Get the idle keep-alive connection expiry in seconds.

        Returns:
            Keep-alive expiry in seconds
        """
        client_config = self.get_client_config()
        return float(client_config.get('keepalive_expiry', 5))

    def get_max_concurrency(self) -> int:
        """
        Get the client-side cap on in-flight requests (0 disables).

        Prevents a single client from saturating its own connection pool and
        generating the pool timeouts it would then retry.

        Returns:
            Maximum concurrent requests, or 0 for unlimited
        """
        client_config = self.get_client_config()
        return int(client_config.get('max_concurrency', 0))

    def get_breaker_threshold(self) -> int:
        """
        Get the consecutive-failure count that opens the circuit breaker
        (0 disables the breaker).

        Returns:
            Failure threshold
        """
        client_config = self.get_client_config()
        return int(client_config.get('breaker_threshold', 5))

    def get_breaker_reset(self) -> float:
        """
        Get the circuit breaker reset timeout in seconds.

        Returns:
            Reset timeout in seconds
        """
        client_config = self.get_client_config()
        return float(client_config.get('breaker_reset', 30))

    def validate_config(self) -> None:
        """
        Validate the loaded configuration.
        
        Raises:
            ClientConfigurationError: If configuration is invalid
        """
        # Validate server URL
        server_url = self.get_server_url()
        if not server_url or not isinstance(server_url, str):
            raise ClientConfigurationError("Server URL must be a non-empty string")
        
        if not server_url.startswith(('http://', 'https://')):
            raise ClientConfigurationError("Server URL must start with http:// or https://")
        
        # Validate credentials
        username, password = self.get_credentials()
        if not username or not isinstance(username, str):
            raise ClientConfigurationError("Username must be a non-empty string")
        
        if not password or not isinstance(password, str):
            raise ClientConfigurationError("Password must be a non-empty string")
        
        # Validate positive-valued timing settings
        for name, value in (
            ('Timeout', self.get_timeout()),
            ('Connect timeout', self.get_connect_timeout()),
            ('Pool timeout', self.get_pool_timeout()),
            ('Request budget', self.get_request_budget()),
            ('Retry max delay', self.get_retry_max_delay()),
            ('Keepalive expiry', self.get_keepalive_expiry()),
        ):
            if not isinstance(value, (int, float)) or value <= 0:
                raise ClientConfigurationError(f"{name} must be a positive number")

        # Validate non-negative settings
        for name, value in (
            ('Max retries', self.get_max_retries()),
            ('Retry delay', self.get_retry_delay()),
            ('Max concurrency', self.get_max_concurrency()),
            ('Breaker threshold', self.get_breaker_threshold()),
            ('Breaker reset', self.get_breaker_reset()),
        ):
            if not isinstance(value, (int, float)) or value < 0:
                raise ClientConfigurationError(f"{name} must be a non-negative number")

        if self.get_retry_backoff_base() < 1.0:
            raise ClientConfigurationError("Retry backoff base must be >= 1.0")

        if self.get_max_connections() <= 0:
            raise ClientConfigurationError("Max connections must be a positive integer")

        if self.get_max_keepalive() < 0:
            raise ClientConfigurationError("Max keepalive must be a non-negative integer")

        # A budget smaller than a single attempt's timeout means retries can
        # never happen; that is legal but almost always a misconfiguration.
        if self.get_request_budget() < self.get_timeout():
            logger.warning(
                "Request budget (%.1fs) is below the per-attempt timeout (%.1fs); "
                "requests will be cut off before the transport timeout fires",
                self.get_request_budget(), self.get_timeout()
            )

        logger.info("Client configuration validation passed")
    
    def __str__(self) -> str:
        """String representation of the configuration."""
        return f"VitalGraphClientConfig(path={self.config_path}, server_url={self.get_server_url()})"


# Global client configuration instance
_client_config_instance: Optional[VitalGraphClientConfig] = None


def get_client_config() -> VitalGraphClientConfig:
    """
    Get the global client configuration instance.
    
    Configuration is loaded from profile-based environment variables.
        
    Returns:
        VitalGraphClientConfig instance
    """
    global _client_config_instance
    
    if _client_config_instance is None:
        _client_config_instance = VitalGraphClientConfig()
        _client_config_instance.validate_config()
    
    return _client_config_instance


def reload_client_config() -> VitalGraphClientConfig:
    """
    Reload the global client configuration instance.
    
    Useful when environment variables have changed.
        
    Returns:
        New VitalGraphClientConfig instance
    """
    global _client_config_instance
    
    _client_config_instance = VitalGraphClientConfig()
    _client_config_instance.validate_config()
    
    return _client_config_instance
