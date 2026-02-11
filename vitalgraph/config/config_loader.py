"""
VitalGraphDB Configuration Loader

This module provides functionality to load and validate VitalGraphDB configuration
from environment variables. Supports profile-specific .env files.
Configuration comes from environment variables with sensible defaults.
"""

import os
from typing import Dict, Any, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Raised when there are configuration loading or validation errors."""
    pass


class VitalGraphConfig:
    """
    VitalGraphDB configuration loader and manager.
    
    Loads configuration entirely from environment variables with sensible defaults.
    No YAML files required.
    """
    
    def __init__(self):
        """
        Initialize configuration from environment variables.
        Uses VITALGRAPH_ENVIRONMENT to determine which profile prefix to use.
        Example: VITALGRAPH_ENVIRONMENT=local uses LOCAL_* variables
        """
        self.environment = os.getenv('VITALGRAPH_ENVIRONMENT', 'local').upper()
        self.config_data: Dict[str, Any] = self._load_from_env()
        self.config_path: Optional[str] = None  # No file path
        logger.info(f"Loaded configuration from {self.environment}_* environment variables")
    
    def _get_profile_env(self, key: str, default: str = '') -> str:
        """
        Get environment variable with profile prefix.
        
        Example: If VITALGRAPH_ENVIRONMENT=local and key='DB_HOST',
                 looks for LOCAL_DB_HOST, falls back to DB_HOST, then default.
        
        Args:
            key: Environment variable key (without profile prefix)
            default: Default value if not found
            
        Returns:
            Environment variable value
        """
        # Try profile-prefixed variable first (e.g., LOCAL_DB_HOST)
        profile_key = f"{self.environment}_{key}"
        value = os.getenv(profile_key)
        if value is not None:
            return value
        
        # Fall back to unprefixed variable (e.g., DB_HOST)
        value = os.getenv(key)
        if value is not None:
            return value
        
        # Use default
        return default
    
    def _load_from_env(self) -> Dict[str, Any]:
        """
        Load configuration from profile-prefixed environment variables.
        
        Uses VITALGRAPH_ENVIRONMENT to determine prefix (LOCAL_, PROD_, etc.)
        Falls back to unprefixed variables, then defaults.
        
        Example:
            VITALGRAPH_ENVIRONMENT=local
            LOCAL_DB_HOST=localhost
            LOCAL_DB_PORT=5432
            LOCAL_FUSEKI_URL=http://localhost:3030
        
        Returns:
            Complete configuration dictionary
        """
        return {
            'backend': {
                'type': self._get_profile_env('BACKEND_TYPE', 'fuseki_postgresql')
            },
            'database': {
                'host': self._get_profile_env('DB_HOST', 'localhost'),
                'port': int(self._get_profile_env('DB_PORT', '5432')),
                'database': self._get_profile_env('DB_NAME', 'vitalgraph'),
                'username': self._get_profile_env('DB_USERNAME', 'postgres'),
                'password': self._get_profile_env('DB_PASSWORD', ''),
                'pool_size': int(self._get_profile_env('DB_POOL_SIZE', '10')),
                'max_overflow': int(self._get_profile_env('DB_MAX_OVERFLOW', '20')),
                'pool_timeout': int(self._get_profile_env('DB_POOL_TIMEOUT', '30')),
                'pool_recycle': int(self._get_profile_env('DB_POOL_RECYCLE', '3600')),
                'enable_quad_logging': self._get_profile_env('DB_ENABLE_QUAD_LOGGING', 'false').lower() == 'true'
            },
            'fuseki': {
                'server_url': self._get_profile_env('FUSEKI_URL', 'http://localhost:3030'),
                'dataset_name': self._get_profile_env('FUSEKI_DATASET', 'vitalgraph'),
                'username': self._get_profile_env('FUSEKI_USERNAME', ''),
                'password': self._get_profile_env('FUSEKI_PASSWORD', ''),
                'connection_limit': int(self._get_profile_env('FUSEKI_CONNECTION_LIMIT', '20')),
                'auto_register_datasets': self._get_profile_env('FUSEKI_AUTO_REGISTER_DATASETS', 'false').lower() == 'true',
                'enable_authentication': self._get_profile_env('FUSEKI_ENABLE_AUTH', 'false').lower() == 'true',
                'keycloak': {
                    'url': self._get_profile_env('KEYCLOAK_URL', ''),
                    'realm': self._get_profile_env('KEYCLOAK_REALM', ''),
                    'client_id': self._get_profile_env('KEYCLOAK_CLIENT_ID', ''),
                    'client_secret': self._get_profile_env('KEYCLOAK_CLIENT_SECRET', ''),
                    'username': self._get_profile_env('KEYCLOAK_USERNAME', ''),
                    'password': self._get_profile_env('KEYCLOAK_PASSWORD', '')
                }
            },
            'fuseki_postgresql': {
                'database': {
                    'host': self._get_profile_env('DB_HOST', 'localhost'),
                    'port': int(self._get_profile_env('DB_PORT', '5432')),
                    'database': self._get_profile_env('DB_NAME', 'vitalgraph'),
                    'username': self._get_profile_env('DB_USERNAME', 'postgres'),
                    'password': self._get_profile_env('DB_PASSWORD', ''),
                    'pool_size': int(self._get_profile_env('DB_POOL_SIZE', '10')),
                    'max_overflow': int(self._get_profile_env('DB_MAX_OVERFLOW', '20')),
                    'pool_timeout': int(self._get_profile_env('DB_POOL_TIMEOUT', '30')),
                    'pool_recycle': int(self._get_profile_env('DB_POOL_RECYCLE', '3600'))
                },
                'fuseki': {
                    'server_url': self._get_profile_env('FUSEKI_URL', 'http://localhost:3030'),
                    'dataset_name': self._get_profile_env('FUSEKI_DATASET', 'vitalgraph'),
                    'username': self._get_profile_env('FUSEKI_USERNAME', ''),
                    'password': self._get_profile_env('FUSEKI_PASSWORD', ''),
                    'connection_limit': int(self._get_profile_env('FUSEKI_CONNECTION_LIMIT', '20')),
                    'auto_register_datasets': self._get_profile_env('FUSEKI_AUTO_REGISTER_DATASETS', 'false').lower() == 'true',
                    'enable_authentication': self._get_profile_env('FUSEKI_ENABLE_AUTH', 'false').lower() == 'true',
                    'keycloak': {
                        'url': self._get_profile_env('KEYCLOAK_URL', ''),
                        'realm': self._get_profile_env('KEYCLOAK_REALM', ''),
                        'client_id': self._get_profile_env('KEYCLOAK_CLIENT_ID', ''),
                        'client_secret': self._get_profile_env('KEYCLOAK_CLIENT_SECRET', ''),
                        'username': self._get_profile_env('KEYCLOAK_USERNAME', ''),
                        'password': self._get_profile_env('KEYCLOAK_PASSWORD', '')
                    }
                },
                'transaction': {
                    'timeout': int(self._get_profile_env('TRANSACTION_TIMEOUT', '30')),
                    'isolation_level': self._get_profile_env('TRANSACTION_ISOLATION', 'READ_COMMITTED')
                },
                'backup': {
                    'enabled': self._get_profile_env('BACKUP_ENABLED', 'false').lower() == 'true',
                    'directory': self._get_profile_env('BACKUP_DIR', '/var/backups/vitalgraph')
                },
                'sparql': {
                    'query_timeout': int(self._get_profile_env('SPARQL_QUERY_TIMEOUT', '300')),
                    'max_results': int(self._get_profile_env('SPARQL_MAX_RESULTS', '10000'))
                },
                'table_prefix': self._get_profile_env('TABLE_PREFIX', 'vitalgraph_')
            },
            'tables': {
                'prefix': self._get_profile_env('TABLE_PREFIX', 'vg_')
            },
            'auth': {
                'root_username': self._get_profile_env('AUTH_ROOT_USERNAME', 'admin'),
                'root_password': self._get_profile_env('AUTH_ROOT_PASSWORD', 'admin')
            },
            'file_storage': {
                'backend': self._get_profile_env('STORAGE_BACKEND', 'minio'),
                'minio': {
                    'endpoint_url': self._get_profile_env('STORAGE_ENDPOINT', 'http://localhost:9000'),
                    'access_key_id': self._get_profile_env('STORAGE_ACCESS_KEY', 'minioadmin'),
                    'secret_access_key': self._get_profile_env('STORAGE_SECRET_KEY', 'minioadmin'),
                    'bucket_name': self._get_profile_env('STORAGE_BUCKET', 'vitalgraph-files'),
                    'use_ssl': self._get_profile_env('STORAGE_USE_SSL', 'false').lower() == 'true'
                },
                's3': {
                    'endpoint_url': self._get_profile_env('STORAGE_ENDPOINT', ''),
                    'access_key_id': self._get_profile_env('STORAGE_ACCESS_KEY', ''),
                    'secret_access_key': self._get_profile_env('STORAGE_SECRET_KEY', ''),
                    'bucket_name': self._get_profile_env('STORAGE_BUCKET', 'vitalgraph-files'),
                    'region': self._get_profile_env('STORAGE_REGION', 'us-east-1'),
                    'use_ssl': self._get_profile_env('STORAGE_USE_SSL', 'true').lower() == 'true'
                }
            },
            'app': {
                'log_level': self._get_profile_env('LOG_LEVEL', 'INFO')
            }
        }
    

    
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
    
    def get_backend_config(self) -> Dict[str, Any]:
        """
        Get backend configuration section.
        
        Returns:
            Dictionary containing backend configuration
        """
        return self.config_data.get('backend', {})
    
    def get_fuseki_config(self) -> Dict[str, Any]:
        """
        Get Fuseki backend configuration section.
        
        Returns:
            Dictionary containing Fuseki configuration
        """
        return self.config_data.get('fuseki', {})
    
    def get_fuseki_postgresql_config(self) -> Dict[str, Any]:
        """
        Get Fuseki-PostgreSQL hybrid backend configuration section.
        
        Returns:
            Dictionary containing Fuseki-PostgreSQL hybrid configuration
        """
        return self.config_data.get('fuseki_postgresql', {})
    
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
        
        Configuration is loaded from environment variables:
        - VITALGRAPH_DB_HOST: Database host
        - VITALGRAPH_DB_PORT: Database port
        - VITALGRAPH_DB_NAME: Database name
        - VITALGRAPH_DB_USERNAME: Database username
        - VITALGRAPH_DB_PASSWORD: Database password
        
        Returns:
            PostgreSQL connection URL string
        """
        db_config = self.get_database_config()
        
        # Get values from config (already loaded from environment variables)
        host = db_config.get('host', 'localhost')
        port = db_config.get('port', 5432)
        database = db_config.get('database', 'vitalgraph')
        username = db_config.get('username', 'postgres')
        password = db_config.get('password', '')
         
        return f"postgresql://{username}:{password}@{host}:{port}/{database}"
    
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


def get_config() -> VitalGraphConfig:
    """
    Get the global configuration instance.
    
    Returns:
        VitalGraphConfig instance
    """
    global _config_instance
    
    if _config_instance is None:
        _config_instance = VitalGraphConfig()
        _config_instance.validate_config()
    
    return _config_instance


def reload_config() -> VitalGraphConfig:
    """
    Reload the global configuration instance.
    
    Returns:
        New VitalGraphConfig instance
    """
    global _config_instance
    
    _config_instance = VitalGraphConfig()
    _config_instance.validate_config()
    
    return _config_instance
