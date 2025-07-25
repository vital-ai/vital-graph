"""
VitalGraphDB Configuration Loader

This module provides functionality to load and validate VitalGraphDB configuration
from YAML files. It supports loading from multiple possible locations and provides
default values for missing configuration sections.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Raised when there are configuration loading or validation errors."""
    pass


class VitalGraphConfig:
    """
    VitalGraphDB configuration loader and manager.
    
    Loads configuration from YAML files and provides access to configuration
    sections with validation and default values.
    """
    
    def __init__(self, config_path: str):
        """
        Initialize the configuration loader.
        
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
            ConfigurationError: If the file cannot be loaded or parsed
        """
        config_file = Path(config_path)
        
        if not config_file.exists():
            raise ConfigurationError(f"Configuration file not found: {config_path}")
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                self.config_data = yaml.safe_load(f) or {}
            
            self.config_path = str(config_file.absolute())
            logger.info(f"Loaded configuration from: {self.config_path}")
            
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Error parsing YAML configuration: {e}")
        except Exception as e:
            raise ConfigurationError(f"Error loading configuration file: {e}")
    

    
    def _get_default_config(self) -> Dict[str, Any]:
        """
        Get the default configuration values.
        
        Returns:
            Dictionary containing default configuration values
        """
        return {
            'database': {
                'host': 'localhost',
                'port': 5432,
                'database': 'vitalgraphdb',
                'username': 'vitalgraph_user',
                'password': 'vitalgraph_password',
                'pool_size': 10,
                'max_overflow': 20,
                'pool_timeout': 30,
                'pool_recycle': 3600
            },
            'rdf_pool': {
                'min_size': 0,
                'max_size': 5,
                'timeout': 5,
                'max_lifetime': 3600,
                'max_idle': 300,
                'reconnect_failed': True
            },
            'tables': {
                'prefix': 'vg_'
            },
            'auth': {
                'root_username': 'admin',
                'root_password': 'admin'
            },
            'app': {
                'log_level': 'INFO'
            }
        }
    
    def get_database_config(self) -> Dict[str, Any]:
        """
        Get database configuration section.
        
        Returns:
            Dictionary containing database configuration
        """
        return self.config_data.get('database', {})
    
    def get_tables_config(self) -> Dict[str, Any]:
        """
        Get tables configuration section.
        
        Returns:
            Dictionary containing tables configuration
        """
        return self.config_data.get('tables', {})
    
    def get_table_config(self) -> Dict[str, Any]:
        """
        Get table configuration section.
        
        Returns:
            Dictionary containing table configuration
        """
        return self.config_data.get('tables', {})
    
    def get_auth_config(self) -> Dict[str, Any]:
        """
        Get authentication configuration section.
        
        Returns:
            Dictionary containing auth configuration
        """
        return self.config_data.get('auth', {})
    
    def get_app_config(self) -> Dict[str, Any]:
        """
        Get application configuration section.
        
        Returns:
            Dictionary containing app configuration
        """
        return self.config_data.get('app', {})
    
    def get_rdf_pool_config(self) -> Dict[str, Any]:
        """
        Get RDF connection pool configuration section.
        
        Returns:
            Dictionary containing RDF pool configuration
        """
        defaults = self._get_default_config()['rdf_pool']
        config = self.config_data.get('rdf_pool', {})
        # Merge with defaults
        return {**defaults, **config}
    
    def get_database_url(self) -> str:
        """
        Build PostgreSQL database URL from configuration.
        
        Supports environment variable overrides and automatic host.docker.internal resolution:
        - VITALGRAPH_DB_HOST: Override database host
        - VITALGRAPH_DB_PORT: Override database port
        - VITALGRAPH_DB_NAME: Override database name
        - VITALGRAPH_DB_USER: Override database username
        - VITALGRAPH_DB_PASSWORD: Override database password
        
        Special handling:
        - host.docker.internal is automatically resolved to localhost when running locally
        
        Returns:
            PostgreSQL connection URL string
        """
        db_config = self.get_database_config()
        
        # Get values from config with environment variable overrides
        host = os.getenv('VITALGRAPH_DB_HOST', db_config.get('host', 'localhost'))
        port = int(os.getenv('VITALGRAPH_DB_PORT', str(db_config.get('port', 5432))))
        database = os.getenv('VITALGRAPH_DB_NAME', db_config.get('database', 'vitalgraphdb'))
        username = os.getenv('VITALGRAPH_DB_USER', db_config.get('username', 'vitalgraph_user'))
        password = os.getenv('VITALGRAPH_DB_PASSWORD', db_config.get('password', 'vitalgraph_password'))
        
        # Special handling for host.docker.internal -> localhost resolution
        # This allows the same config to work in Docker and locally
        if host == 'host.docker.internal':
            resolved_host = 'localhost'
            logger.info(f"Resolved host.docker.internal -> localhost for local execution")
        else:
            resolved_host = host
        
        return f"postgresql://{username}:{password}@{resolved_host}:{port}/{database}"
    
    def get_table_prefix(self) -> str:
        """
        Get the table prefix for VitalGraph tables.
        
        Returns:
            Table prefix string
        """
        return self.get_table_config().get('prefix', 'vg_')
    
    def get_root_credentials(self) -> tuple[str, str]:
        """
        Get root username and password.
        
        Returns:
            Tuple of (username, password)
        """
        auth_config = self.get_auth_config()
        username = auth_config.get('root_username', 'admin')
        password = auth_config.get('root_password', 'admin')
        return username, password
    
    def validate_config(self) -> None:
        """
        Validate the loaded configuration.
        
        Raises:
            ConfigurationError: If configuration is invalid
        """
        # Validate database configuration
        db_config = self.get_database_config()
        required_db_fields = ['host', 'port', 'database', 'username']
        
        for field in required_db_fields:
            if not db_config.get(field):
                raise ConfigurationError(f"Missing required database configuration: {field}")
        
        # Password is optional (can be empty for trust authentication)
        if 'password' not in db_config:
            raise ConfigurationError("Missing required database configuration: password")
        
        # Validate port is a number
        try:
            port = int(db_config.get('port', 5432))
            if port < 1 or port > 65535:
                raise ConfigurationError(f"Invalid database port: {port}")
        except (ValueError, TypeError):
            raise ConfigurationError("Database port must be a valid integer")
        
        # Validate table prefix
        prefix = self.get_table_prefix()
        if not prefix or not isinstance(prefix, str):
            raise ConfigurationError("Table prefix must be a non-empty string")
        
        logger.info("Configuration validation passed")
    
    def __str__(self) -> str:
        """String representation of the configuration."""
        return f"VitalGraphConfig(path={self.config_path}, sections={list(self.config_data.keys())})"


# Global configuration instance
_config_instance: Optional[VitalGraphConfig] = None


def get_config(config_path: Optional[str] = None) -> VitalGraphConfig:
    """
    Get the global configuration instance.
    
    Args:
        config_path: Optional path to configuration file. Only used on first call.
        
    Returns:
        VitalGraphConfig instance
    """
    global _config_instance
    
    if _config_instance is None:
        _config_instance = VitalGraphConfig(config_path)
        _config_instance.validate_config()
    
    return _config_instance


def reload_config(config_path: Optional[str] = None) -> VitalGraphConfig:
    """
    Reload the global configuration instance.
    
    Args:
        config_path: Optional path to configuration file
        
    Returns:
        New VitalGraphConfig instance
    """
    global _config_instance
    
    _config_instance = VitalGraphConfig(config_path)
    _config_instance.validate_config()
    
    return _config_instance
