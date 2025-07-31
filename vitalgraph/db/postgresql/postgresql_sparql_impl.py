"""
New PostgreSQL SPARQL Implementation for VitalGraph

This module provides the new function-based SPARQL implementation that maintains
the same public API as the original PostgreSQLSparqlImpl while using the new
orchestrator helper functions for better maintainability and modularity.
"""

import logging
from typing import Dict, List, Tuple, Optional, Any
from rdflib import Variable, URIRef, Literal, BNode
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.algebra import translateQuery

from .postgresql_space_impl import PostgreSQLSpaceImpl
from .postgresql_cache_term import PostgreSQLCacheTerm

# Import orchestrator helper functions
from .sparql.postgresql_sparql_orchestrator import (
    execute_sparql_query, execute_sparql_update, execute_sql_query,
    initialize_graph_cache
)

# Import core utilities
from .sparql.postgresql_sparql_core import (
    AliasGenerator, TableConfig, SQLComponents
)


class PostgreSQLSparqlImpl:
    """
    New PostgreSQL SPARQL implementation using function-based orchestrator architecture.
    
    This class maintains the same public API as the original PostgreSQLSparqlImpl
    for seamless replacement while delegating all operations to orchestrator helper
    functions that use pure functions with minimal inter-dependencies.
    """
    
    def __init__(self, space_impl: PostgreSQLSpaceImpl):
        """
        Initialize PostgreSQL SPARQL implementation.
        
        Args:
            space_impl: PostgreSQLSpaceImpl instance for database operations
        """
        self.space_impl = space_impl
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Initialize components that maintain compatibility with original API
        self.alias_generator = AliasGenerator()
        self.graph_cache = {}
        
        self.logger.info("New PostgreSQL SPARQL implementation initialized")
    
    async def execute_sparql_query(self, space_id: str, sparql_query: str) -> List[Dict[str, Any]]:
        """
        Execute a SPARQL query against the specified space.
        
        This is the main public API method that maintains compatibility with
        the original implementation while using the new orchestrator helper functions.
        
        Args:
            space_id: Space identifier
            sparql_query: SPARQL query string
            
        Returns:
            List of result dictionaries with variable bindings (SELECT)
            or List of RDF triple dictionaries (CONSTRUCT/DESCRIBE)
        """
        try:
            self.logger.info(f"Executing SPARQL query in space '{space_id}'")
            self.logger.debug(f"Query: {sparql_query}")
            
            # Delegate to orchestrator helper function
            results = await execute_sparql_query(
                space_impl=self.space_impl,
                space_id=space_id,
                sparql_query=sparql_query,
                graph_cache=self.graph_cache
            )
            
            self.logger.info(f"Query executed successfully, returned {len(results)} results")
            return results
            
        except Exception as e:
            self.logger.error(f"Error executing SPARQL query: {e}")
            raise
    
    async def execute_sparql_update(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute a SPARQL 1.1 UPDATE operation.
        
        Args:
            space_id: The space identifier
            sparql_update: SPARQL UPDATE query string
            
        Returns:
            bool: True if update was successful
            
        Raises:
            Exception: If update operation fails
        """
        try:
            self.logger.info(f"Executing SPARQL UPDATE in space '{space_id}'")
            self.logger.debug(f"Update: {sparql_update}")
            
            # Delegate to orchestrator helper function
            success = await execute_sparql_update(
                space_impl=self.space_impl,
                space_id=space_id,
                sparql_update=sparql_update,
                graph_cache=self.graph_cache
            )
            
            if success:
                self.logger.info("SPARQL UPDATE executed successfully")
            else:
                self.logger.warning("SPARQL UPDATE completed but may not have made changes")
                
            return success
            
        except Exception as e:
            self.logger.error(f"Error executing SPARQL UPDATE: {e}")
            raise
    
    # Additional methods for backward compatibility with original implementation
    
    async def _get_term_uuids_batch(self, terms: List[Tuple[str, str]], table_config: TableConfig, space_id: str) -> Dict[Tuple[str, str], str]:
        """
        Get term UUIDs for multiple terms using cache and batch database lookup.
        
        Args:
            terms: List of (term_text, term_type) tuples
            table_config: Table configuration for database queries
            space_id: Space identifier for the batch lookup
            
        Returns:
            Dictionary mapping (term_text, term_type) to term_uuid
        """
        if not terms:
            return {}
        
        result = {}
        remaining_terms = []
        
        # Check cache first if available
        if self.term_cache:
            for term_text, term_type in terms:
                term_key = (term_text, term_type)
                cached_uuid = self.term_cache.get_term_uuid(term_key)
                if cached_uuid:
                    result[term_key] = cached_uuid
                else:
                    remaining_terms.append(term_key)
        else:
            remaining_terms = [(term_text, term_type) for term_text, term_type in terms]
        
        # Batch lookup remaining terms with proper type matching
        if remaining_terms:
            try:
                table_names = self.space_impl._get_table_names(space_id)
                async with self.space_impl.core.get_dict_connection() as conn:
                    # Connection already configured with dict_row factory
                    cursor = conn.cursor()
                    
                    # Build parameterized query for batch lookup with term types
                    conditions = []
                    params = []
                    
                    for term_text, term_type in remaining_terms:
                        conditions.append("(term_text = %s AND term_type = %s)")
                        params.extend([term_text, term_type])
                    
                    if conditions:
                        sql = f"""
                            SELECT term_uuid, term_text, term_type 
                            FROM {table_names['term']} 
                            WHERE {' OR '.join(conditions)}
                        """
                        
                        cursor.execute(sql, params)
                        rows = cursor.fetchall()
                        
                        # Process results
                        for row in rows:
                            term_uuid, term_text, term_type = row
                            term_key = (term_text, term_type)
                            result[term_key] = str(term_uuid)
                            
                            # Update cache if available
                            if self.term_cache:
                                self.term_cache.put_term_uuid(term_key, str(term_uuid))
                            
            except Exception as e:
                self.logger.warning(f"Batch term lookup failed: {e}")
                # If batch fails, return what we have from cache
        
        return result
    
    async def _initialize_graph_cache_if_needed(self, space_id: str) -> None:
        """
        Initialize the graph cache if it's empty (lazy loading).
        
        This method is kept for backward compatibility with any code that
        might call it directly.
        
        Args:
            space_id: The space identifier
        """
        if space_id not in self.graph_cache:
            self.graph_cache[space_id] = await initialize_graph_cache(
                space_impl=self.space_impl,
                space_id=space_id
            )
    
    async def _execute_sql_query(self, sql_query: str) -> List[Dict[str, Any]]:
        """
        Execute SQL query using space implementation.
        
        This method is kept for backward compatibility.
        
        Args:
            sql_query: SQL query string
            
        Returns:
            List of result dictionaries
        """
        return await execute_sql_query(
            space_impl=self.space_impl,
            sql_query=sql_query
        )
    
    # Methods that delegate to the original monolithic implementation for complex operations
    # These are placeholders that would need to be implemented using the orchestrator functions
    
    async def _translate_sparql_to_sql(self, space_id: str, sparql_query: str) -> str:
        """
        Translate SPARQL query to SQL using orchestrator functions.
        
        This is a compatibility method that delegates to the orchestrator.
        
        Args:
            space_id: Space identifier for table name resolution
            sparql_query: SPARQL query string
            
        Returns:
            SQL query string
        """
        # This would be implemented using the orchestrator helper functions
        # For now, this is a placeholder that raises NotImplementedError
        raise NotImplementedError("Direct SQL translation not implemented in orchestrator architecture")
    
    def _log_algebra_structure(self, pattern, label: str, depth: int) -> None:
        """
        Log the structure of a SPARQL algebra pattern for debugging.
        
        This method is kept for backward compatibility.
        
        Args:
            pattern: SPARQL algebra pattern
            label: Label for logging
            depth: Nesting depth for indentation
        """
        indent = "  " * depth
        pattern_name = getattr(pattern, 'name', type(pattern).__name__)
        self.logger.debug(f"{indent}{label}: {pattern_name}")
        
        # Log child patterns recursively
        if hasattr(pattern, 'p'):
            self._log_algebra_structure(pattern.p, "child", depth + 1)
        if hasattr(pattern, 'p1'):
            self._log_algebra_structure(pattern.p1, "left", depth + 1)
        if hasattr(pattern, 'p2'):
            self._log_algebra_structure(pattern.p2, "right", depth + 1)
    
    # Property accessors for backward compatibility
    
    @property
    def logger(self) -> logging.Logger:
        """Access to logger for backward compatibility."""
        return self._logger if hasattr(self, '_logger') else logging.getLogger(__name__)
    
    @logger.setter
    def logger(self, value: logging.Logger) -> None:
        """Set logger for backward compatibility."""
        self._logger = value