"""
Backend configuration and factory for VitalGraph space backends.

This module provides configuration classes and factory methods for creating
different backend implementations (sparql_sql, Oxigraph) based on configuration
settings.
"""

from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass
import logging

from .space_backend_interface import SpaceBackendInterface, SparqlBackendInterface, SignalManagerInterface

logger = logging.getLogger(__name__)


class BackendType(Enum):
    """Backend types that EXIST. `issues/241`.

    Members are not a wish list or a history — every one names a package a caller
    can actually get. Three were removed 2026-09-26 for failing that test, one of
    which had outlived its implementation by long enough that the only thing the
    member still did was carry an error message. See `issues/241` for which and
    why.

    Retired NAMES are still recognised, but as strings where the config is read
    (`impl/vitalgraph_impl.py`), which is where that diagnostic belongs — an enum
    member is not needed to tell someone their configured value is out of date,
    and keeping one for that purpose is exactly how a member comes to sit here
    with nothing behind it.
    """
    SPARQL_SQL = "sparql_sql"
    OXIGRAPH = "oxigraph"


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
        
        if config.backend_type == BackendType.SPARQL_SQL:
            try:
                from .sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
                postgresql_config = config.connection_params.get('database', {})
                sidecar_config = config.connection_params.get('sidecar', {})
                return SparqlSQLSpaceImpl(
                    postgresql_config=postgresql_config,
                    sidecar_config=sidecar_config,
                )
            except ImportError as e:
                raise ImportError(f"SPARQL SQL backend dependencies not available: {e}")
                
        elif config.backend_type == BackendType.OXIGRAPH:
            try:
                from .oxigraph.oxigraph_space_impl import OxigraphSpaceImpl
                return OxigraphSpaceImpl(**config.connection_params)
            except ImportError as e:
                raise ImportError(f"Oxigraph backend dependencies not available: {e}")
                
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
        
        if config.backend_type == BackendType.SPARQL_SQL:
            try:
                from .sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
                postgresql_config = config.connection_params.get('database', {})
                sidecar_config = config.connection_params.get('sidecar', {})
                space_impl = SparqlSQLSpaceImpl(
                    postgresql_config=postgresql_config,
                    sidecar_config=sidecar_config,
                )
                return space_impl
            except ImportError as e:
                raise ImportError(f"SPARQL SQL SPARQL backend dependencies not available: {e}")
                
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
        
        if config.backend_type == BackendType.SPARQL_SQL:
            try:
                # Lives at the `db/` level, not inside a backend package: it was
                # moved there 2026-09-26 (`issues/241`) because this arm had been
                # importing the live store's signal manager out of a package that
                # was about to be archived.
                from .postgresql_signal_manager import PostgreSQLSignalManager
                return PostgreSQLSignalManager(**signal_config)
            except ImportError as e:
                raise ImportError(f"SPARQL SQL signal manager dependencies not available: {e}")
                
        else:
            raise ValueError(f"Signal manager not supported for: {config.backend_type}")
    
    @staticmethod
    def get_default_backend_type() -> BackendType:
        """
        Get the default backend type.
        
        Returns:
            BackendType: Default backend type (PostgreSQL)
        """
        return BackendType.SPARQL_SQL
    
    @staticmethod
    def create_default_config(**connection_params) -> BackendConfig:
        """
        Create default backend configuration (SPARQL_SQL).
        
        Args:
            **connection_params: Connection parameters for the backend
            
        Returns:
            BackendConfig: Default backend configuration
        """
        return BackendConfig(
            backend_type=BackendFactory.get_default_backend_type(),
            connection_params=connection_params
        )
