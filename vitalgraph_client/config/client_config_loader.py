"""
VitalGraph Client Configuration Loader

This module provides functionality to load and validate VitalGraph client configuration
from YAML files for connecting to VitalGraph API servers.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ClientConfigurationError(Exception):
    """Raised when there are client configuration loading or validation errors."""
    pass


class VitalGraphClientConfig:
    """
    VitalGraph client configuration loader and manager.
    
    Loads configuration from YAML files and provides access to configuration
    sections for connecting to VitalGraph API servers.
    """
    
    def __init__(self, config_path: str):
        """
        Initialize the client configuration loader.
        
        Args:
            config_path: Path to configuration file.
        """
        self.config_data: Dict[str, Any] = {}
        self.config_path: Optional[str] = None
        
        self.load_config(config_path)
    
    def load_config(self, config_path: str) -> None:
        """
        Load configuration from a specific file path.
        
        Args:
            config_path: Path to the YAML configuration file
            
        Raises:
            ClientConfigurationError: If the file cannot be loaded or parsed
        """
        config_file = Path(config_path)
        
        if not config_file.exists():
            raise ClientConfigurationError(f"Configuration file not found: {config_path}")
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                self.config_data = yaml.safe_load(f) or {}
            
            self.config_path = str(config_file.absolute())
            logger.info(f"Loaded client configuration from: {self.config_path}")
            
        except yaml.YAMLError as e:
            raise ClientConfigurationError(f"Error parsing YAML configuration: {e}")
        except Exception as e:
            raise ClientConfigurationError(f"Error loading configuration file: {e}")
    


    
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
        
        logger.info("Client configuration validation passed")
    
    def __str__(self) -> str:
        """String representation of the configuration."""
        return f"VitalGraphClientConfig(path={self.config_path}, server_url={self.get_server_url()})"


# Global client configuration instance
_client_config_instance: Optional[VitalGraphClientConfig] = None


def get_client_config(config_path: Optional[str] = None) -> VitalGraphClientConfig:
    """
    Get the global client configuration instance.
    
    Args:
        config_path: Optional path to configuration file. Only used on first call.
        
    Returns:
        VitalGraphClientConfig instance
    """
    global _client_config_instance
    
    if _client_config_instance is None:
        _client_config_instance = VitalGraphClientConfig(config_path)
        _client_config_instance.validate_config()
    
    return _client_config_instance


def reload_client_config(config_path: Optional[str] = None) -> VitalGraphClientConfig:
    """
    Reload the global client configuration instance.
    
    Args:
        config_path: Optional path to configuration file
        
    Returns:
        New VitalGraphClientConfig instance
    """
    global _client_config_instance
    
    _client_config_instance = VitalGraphClientConfig(config_path)
    _client_config_instance.validate_config()
    
    return _client_config_instance
