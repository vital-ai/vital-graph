"""
Abstract interface for VitalGraph SPARQL backend implementations.

This module defines the abstract base class for SPARQL query processing
that each backend must implement according to its capabilities.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List


class SparqlBackendInterface(ABC):
    """
    Abstract interface for backend-specific SPARQL implementations.
    
    This interface defines the minimal contract for SPARQL query processing
    based on actual external usage patterns. Only two methods are used externally:
    - execute_sparql_query() for SELECT, CONSTRUCT, ASK, DESCRIBE queries
    - execute_sparql_update() for INSERT, DELETE, UPDATE operations
    """
    
    @abstractmethod
    async def execute_sparql_query(self, space_id: str, sparql_query: str) -> List[Dict[str, Any]]:
        """
        Execute a SPARQL query against the specified space.
        
        Handles SELECT, CONSTRUCT, ASK, and DESCRIBE queries.
        
        Args:
            space_id: The space identifier
            sparql_query: SPARQL query string
            
        Returns:
            List of result dictionaries with variable bindings (SELECT)
            or List of RDF triple dictionaries (CONSTRUCT/DESCRIBE)
            or List with single boolean result (ASK)
        """
        pass
    
    @abstractmethod
    async def execute_sparql_update(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute a SPARQL 1.1 UPDATE operation.
        
        Handles INSERT DATA, DELETE DATA, INSERT WHERE, DELETE WHERE, and MODIFY operations.
        
        Args:
            space_id: The space identifier
            sparql_update: SPARQL UPDATE query string
            
        Returns:
            True if update was successful, False otherwise
        """
        pass
    
    # Optional capability methods for backend-specific features
    def supports_construct(self) -> bool:
        """Check if backend supports CONSTRUCT queries. Default: True"""
        return True
    
    def supports_ask(self) -> bool:
        """Check if backend supports ASK queries. Default: True"""
        return True
    
    def supports_describe(self) -> bool:
        """Check if backend supports DESCRIBE queries. Default: True"""
        return True
    
    def supports_property_paths(self) -> bool:
        """Check if backend supports SPARQL 1.1 property paths. Default: False"""
        return False
    
    def get_query_capabilities(self) -> Dict[str, Any]:
        """
        Get backend-specific query capabilities and limitations.
        
        Returns:
            Dictionary with capability flags and limits
        """
        return {
            'supports_construct': self.supports_construct(),
            'supports_ask': self.supports_ask(), 
            'supports_describe': self.supports_describe(),
            'supports_property_paths': self.supports_property_paths(),
            'max_query_timeout': None,
            'max_result_size': None
        }
