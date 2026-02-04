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
                'url': self._get_profile_env('SERVER_URL', 'http://localhost:8001'),
                'api_base_path': self._get_profile_env('API_BASE_PATH', '/api/v1')
            },
            'auth': {
                'username': self._get_profile_env('AUTH_USERNAME', 'admin'),
                'password': self._get_profile_env('AUTH_PASSWORD', 'admin')
            },
            'client': {
                'timeout': int(self._get_profile_env('TIMEOUT', '30')),
                'max_retries': int(self._get_profile_env('MAX_RETRIES', '3')),
                'retry_delay': int(self._get_profile_env('RETRY_DELAY', '1')),
                'use_mock_client': self._get_profile_env('USE_MOCK_CLIENT', 'false').lower() == 'true',
                'mock': {
                    'use_temp_storage': self._get_profile_env('MOCK_USE_TEMP_STORAGE', 'true').lower() == 'true',
                    'filePath': self._get_profile_env('MOCK_FILE_PATH', '') or None
                }
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
        """
        Get the VitalGraph API server URL.
        
        Returns:
            Server URL string
        """
        server_config = self.get_server_config()
        return server_config.get('url', 'http://localhost:8001')
    
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
    
    def get_timeout(self) -> int:
        """
        Get the request timeout in seconds.
        
        Returns:
            Timeout in seconds
        """
        client_config = self.get_client_config()
        return client_config.get('timeout', 30)
    
    def get_max_retries(self) -> int:
        """
        Get the maximum number of retry attempts.
        
        Returns:
            Maximum retry attempts
        """
        client_config = self.get_client_config()
        return client_config.get('max_retries', 3)
    
    def get_retry_delay(self) -> int:
        """
        Get the delay between retry attempts in seconds.
        
        Returns:
            Retry delay in seconds
        """
        client_config = self.get_client_config()
        return client_config.get('retry_delay', 1)
    
    def use_mock_client(self) -> bool:
        """
        Get whether to use the mock client instead of real HTTP client.
        
        Returns:
            True if mock client should be used, False otherwise (default: False)
        """
        client_config = self.get_client_config()
        return client_config.get('use_mock_client', False)
    
    def get_mock_config(self) -> Dict[str, Any]:
        """
        Get mock client configuration section.
        
        Returns:
            Dictionary containing mock configuration
        """
        client_config = self.get_client_config()
        return client_config.get('mock', {})
    
    def get_mock_file_path(self) -> Optional[str]:
        """
        Get the mock file path for loading mock data.
        
        Returns:
            Mock file path string, or None if not specified
        """
        mock_config = self.get_mock_config()
        return mock_config.get('filePath')
    
    def use_temp_storage(self) -> bool:
        """
        Get whether to use temporary storage for mock files.
        
        Returns:
            True if temporary storage should be used, False for configured path (default: True)
        """
        mock_config = self.get_mock_config()
        return mock_config.get('use_temp_storage', True)
    
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
        
        # Validate timeout
        timeout = self.get_timeout()
        if not isinstance(timeout, int) or timeout <= 0:
            raise ClientConfigurationError("Timeout must be a positive integer")
        
        # Validate use_mock_client
        use_mock = self.use_mock_client()
        if not isinstance(use_mock, bool):
            raise ClientConfigurationError("use_mock_client must be a boolean value")
        
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
