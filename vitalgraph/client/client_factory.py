"""VitalGraph Client Factory

Factory function to create the appropriate VitalGraph client implementation
based on configuration settings.
"""

import logging
from typing import Optional
from .vitalgraph_client import VitalGraphClient
from .vitalgraph_client_inf import VitalGraphClientInterface
from .config.client_config_loader import VitalGraphClientConfig, ClientConfigurationError
from .utils.client_utils import VitalGraphClientError

logger = logging.getLogger(__name__)


def create_vitalgraph_client(config_path: Optional[str] = None, *, config: Optional[VitalGraphClientConfig] = None) -> VitalGraphClientInterface:
    """
    Create a VitalGraph client based on configuration settings.
    
    This factory function reads the client configuration and returns a
    VitalGraphClient instance.
    
    Args:
        config_path: Path to the client configuration YAML file (optional if config provided)
        config: Pre-configured VitalGraphClientConfig object (takes precedence over config_path)
        
    Returns:
        VitalGraphClientInterface: VitalGraphClient instance
        
    Raises:
        VitalGraphClientError: If configuration loading fails
        ClientConfigurationError: If configuration is invalid
    """
    try:
        # Load or use provided configuration
        if config is not None:
            # Use provided config object
            client_config = config
            logger.info("Using provided config object for client creation")
        elif config_path is not None:
            # Load configuration from path
            client_config = VitalGraphClientConfig(config_path)
            logger.info(f"Loaded config from {config_path} for client creation")
        else:
            # Use default configuration
            client_config = VitalGraphClientConfig()
            logger.info("Using default config for client creation")
        
        client_config.validate_config()
        
        logger.info("Creating VitalGraphClient based on configuration setting")
        return VitalGraphClient(config_path, config=client_config)
            
    except ClientConfigurationError as e:
        logger.error(f"Configuration error while creating client: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error while creating client: {e}")
        raise VitalGraphClientError(f"Failed to create client: {e}")


def create_real_client(config_path: Optional[str] = None, *, config: Optional[VitalGraphClientConfig] = None) -> VitalGraphClient:
    """
    Create a real VitalGraph client (forces real client regardless of config).
    
    Args:
        config_path: Path to the client configuration YAML file (optional if config provided)
        config: Pre-configured VitalGraphClientConfig object (takes precedence over config_path)
        
    Returns:
        VitalGraphClient: Real client instance
        
    Raises:
        VitalGraphClientError: If configuration loading fails
        ClientConfigurationError: If configuration is invalid
    """
    logger.info("Creating VitalGraphClient (forced real client)")
    return VitalGraphClient(config_path, config=config)
