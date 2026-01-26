"""
Backend configuration and factory for VitalGraph space backends.

This module provides configuration classes and factory methods for creating
different backend implementations (PostgreSQL, Fuseki, Oxigraph, Mock) based
on configuration settings.
"""

from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass
import logging

from .space_backend_interface import SpaceBackendInterface, SparqlBackendInterface
from .space_inf import SignalManagerInterface

logger = logging.getLogger(__name__)


class BackendType(Enum):
    """Supported backend types."""
    POSTGRESQL = "postgresql"
    FUSEKI = "fuseki"
    FUSEKI_POSTGRESQL = "fuseki_postgresql"
    OXIGRAPH = "oxigraph"
    MOCK = "mock"


@dataclass
class BackendConfig:
    """Configuration for a space backend."""
    backend_type: BackendType
    connection_params: Dict[str, Any]
    pool_config: Optional[Dict[str, Any]] = None
    signal_manager_config: Optional[Dict[str, Any]] = None


class BackendFactory:
    """Factory for creating space backend implementations."""
    
    @staticmethod
    def create_space_backend(config: BackendConfig) -> SpaceBackendInterface:
        """
        Create space backend implementation based on configuration.
        
        Args:
            config: Backend configuration
            
        Returns:
            SpaceBackendInterface: Backend implementation instance
            
        Raises:
            ValueError: If backend type is not supported
            ImportError: If required backend dependencies are not available
        """
        logger.info(f"Creating space backend: {config.backend_type.value}")
        
        if config.backend_type == BackendType.POSTGRESQL:
            try:
                from .postgresql.postgresql_space_impl import PostgreSQLSpaceImpl
                return PostgreSQLSpaceImpl(**config.connection_params)
            except ImportError as e:
                raise ImportError(f"PostgreSQL backend dependencies not available: {e}")
                
        elif config.backend_type == BackendType.FUSEKI:
            try:
                from .fuseki.fuseki_space_impl import FusekiSpaceImpl
                return FusekiSpaceImpl(**config.connection_params)
            except ImportError as e:
                raise ImportError(f"Fuseki backend dependencies not available: {e}")
                
        elif config.backend_type == BackendType.FUSEKI_POSTGRESQL:
            try:
                from .fuseki_postgresql.fuseki_postgresql_space_impl import FusekiPostgreSQLSpaceImpl
                # Extract fuseki and postgresql configs from connection_params
                fuseki_config = config.connection_params.get('fuseki', {})
                postgresql_config = config.connection_params.get('database', {})
                return FusekiPostgreSQLSpaceImpl(fuseki_config=fuseki_config, postgresql_config=postgresql_config)
            except ImportError as e:
                raise ImportError(f"Fuseki PostgreSQL hybrid backend dependencies not available: {e}")
                
        elif config.backend_type == BackendType.OXIGRAPH:
            try:
                from .oxigraph.oxigraph_space_impl import OxigraphSpaceImpl
                return OxigraphSpaceImpl(**config.connection_params)
            except ImportError as e:
                raise ImportError(f"Oxigraph backend dependencies not available: {e}")
                
        elif config.backend_type == BackendType.MOCK:
            try:
                from .mock.mock_space_impl import MockSpaceImpl
                return MockSpaceImpl(**config.connection_params)
            except ImportError as e:
                raise ImportError(f"Mock backend dependencies not available: {e}")
                
        else:
            raise ValueError(f"Unsupported backend type: {config.backend_type}")
    
    @staticmethod
    def create_sparql_backend(config: BackendConfig) -> SparqlBackendInterface:
        """
        Create SPARQL backend implementation based on configuration.
        
        Args:
            config: Backend configuration
            
        Returns:
            SparqlBackendInterface: SPARQL backend implementation instance
            
        Raises:
            ValueError: If backend type is not supported
            ImportError: If required backend dependencies are not available
        """
        logger.info(f"Creating SPARQL backend: {config.backend_type.value}")
        
        if config.backend_type == BackendType.POSTGRESQL:
            try:
                from .postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl
                from .postgresql.postgresql_space_impl import PostgreSQLSpaceImpl
                
                # PostgreSQL SPARQL implementation requires a space implementation
                space_impl = PostgreSQLSpaceImpl(**config.connection_params)
                return PostgreSQLSparqlImpl(space_impl)
            except ImportError as e:
                raise ImportError(f"PostgreSQL SPARQL backend dependencies not available: {e}")
                
        elif config.backend_type == BackendType.FUSEKI:
            try:
                from .fuseki.fuseki_sparql_impl import FusekiSparqlImpl
                from .fuseki.fuseki_space_impl import FusekiSpaceImpl
                
                # Fuseki SPARQL implementation requires a space implementation
                space_impl = FusekiSpaceImpl(**config.connection_params)
                # FusekiSparqlImpl needs space_impl and space_id, but we'll use a default space_id
                return FusekiSparqlImpl(space_impl, "default")
            except ImportError as e:
                raise ImportError(f"Fuseki SPARQL backend dependencies not available: {e}")
                
        elif config.backend_type == BackendType.FUSEKI_POSTGRESQL:
            try:
                from .fuseki_postgresql.fuseki_postgresql_space_impl import FusekiPostgreSQLSpaceImpl
                
                # Fuseki PostgreSQL hybrid backend handles SPARQL through its space implementation
                space_impl = FusekiPostgreSQLSpaceImpl(**config.connection_params)
                # The hybrid backend implements SPARQL operations directly
                return space_impl
            except ImportError as e:
                raise ImportError(f"Fuseki PostgreSQL hybrid SPARQL backend dependencies not available: {e}")
                
        elif config.backend_type == BackendType.MOCK:
            try:
                from .mock.mock_sparql_impl import MockSparqlImpl
                return MockSparqlImpl(**config.connection_params)
            except ImportError as e:
                raise ImportError(f"Mock SPARQL backend dependencies not available: {e}")
                
        else:
            raise ValueError(f"SPARQL backend not supported for: {config.backend_type}")
    
    @staticmethod
    def create_signal_manager(config: BackendConfig) -> SignalManagerInterface:
        """
        Create signal manager implementation based on configuration.
        
        Args:
            config: Backend configuration
            
        Returns:
            SignalManagerInterface: Signal manager implementation instance
            
        Raises:
            ValueError: If backend type is not supported
            ImportError: If required backend dependencies are not available
        """
        logger.info(f"Creating signal manager: {config.backend_type.value}")
        
        signal_config = config.signal_manager_config or {}
        
        if config.backend_type == BackendType.POSTGRESQL:
            try:
                from .postgresql.postgresql_signal_manager import PostgreSQLSignalManager
                return PostgreSQLSignalManager(**signal_config)
            except ImportError as e:
                raise ImportError(f"PostgreSQL signal manager dependencies not available: {e}")
                
        elif config.backend_type == BackendType.FUSEKI:
            try:
                from .fuseki.fuseki_signal_manager import FusekiSignalManager
                return FusekiSignalManager(**signal_config)
            except ImportError as e:
                raise ImportError(f"Fuseki signal manager dependencies not available: {e}")
                
        elif config.backend_type == BackendType.FUSEKI_POSTGRESQL:
            try:
                from .fuseki_postgresql.postgresql_signal_manager import PostgreSQLSignalManager
                return PostgreSQLSignalManager(**signal_config)
            except ImportError as e:
                raise ImportError(f"Fuseki PostgreSQL hybrid signal manager dependencies not available: {e}")
                
        elif config.backend_type == BackendType.MOCK:
            try:
                from .mock.mock_signal_manager import MockSignalManager
                return MockSignalManager(**signal_config)
            except ImportError as e:
                raise ImportError(f"Mock signal manager dependencies not available: {e}")
                
        else:
            raise ValueError(f"Signal manager not supported for: {config.backend_type}")
    
    @staticmethod
    def get_default_backend_type() -> BackendType:
        """
        Get the default backend type.
        
        Returns:
            BackendType: Default backend type (PostgreSQL)
        """
        return BackendType.POSTGRESQL
    
    @staticmethod
    def create_default_config(**connection_params) -> BackendConfig:
        """
        Create default backend configuration (PostgreSQL).
        
        Args:
            **connection_params: Connection parameters for the backend
            
        Returns:
            BackendConfig: Default backend configuration
        """
        return BackendConfig(
            backend_type=BackendFactory.get_default_backend_type(),
            connection_params=connection_params
        )
