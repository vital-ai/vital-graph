"""
New PostgreSQL SPARQL Implementation for VitalGraph

This module provides the new function-based SPARQL implementation that maintains
the same public API as the original PostgreSQLSparqlImpl while using the new
orchestrator helper functions for better maintainability and modularity.
"""

import logging
import re
from typing import Dict, List, Tuple, Optional, Any
from rdflib import Variable, URIRef, Literal, BNode
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.algebra import translateQuery

from .postgresql_space_impl import PostgreSQLSpaceImpl
from .postgresql_cache_term import PostgreSQLCacheTerm

# Import orchestrator helper functions
from .sparql.postgresql_sparql_orchestrator import (
    execute_sparql_query, execute_sparql_update, execute_sql_query,
    initialize_graph_cache, create_table_config, _has_distinct_pattern, 
    _extract_limit_offset, _translate_ask_query, _translate_describe_query
)

# Import pattern translation functions
from .sparql.postgresql_sparql_patterns import (
    translate_algebra_pattern_to_components
)

# Import query building functions  
from .sparql.postgresql_sparql_queries import (
    build_select_query, build_construct_query
)

# Import core utilities
from .sparql.postgresql_sparql_core import (
    AliasGenerator, TableConfig, SQLComponents, SparqlContext
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
    
    def _format_sql_for_logging(self, sql_query: str) -> str:
        """
        Format SQL query for better readability in logs.
        
        Args:
            sql_query: Raw SQL query string
            
        Returns:
            Formatted SQL query string
        """
        # Basic SQL formatting - add line breaks after major clauses
        formatted = sql_query
        
        # Add line breaks after major SQL keywords
        keywords = ['SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT JOIN', 'INNER JOIN', 'CROSS JOIN', 
                    'GROUP BY', 'HAVING', 'ORDER BY', 'LIMIT', 'OFFSET', 'UNION']
        
        for keyword in keywords:
            formatted = formatted.replace(f' {keyword} ', f'\n{keyword} ')
            formatted = formatted.replace(f'\n{keyword} ', f'\n{keyword} ')
        
        # Clean up extra whitespace
        lines = [line.strip() for line in formatted.split('\n') if line.strip()]
        return '\n'.join(lines)
    
    def _analyze_sql_structure(self, sql_query: str) -> Dict[str, Any]:
        """
        Analyze the structure of generated SQL for logging insights.
        
        Args:
            sql_query: Generated SQL query string
            
        Returns:
            Dictionary with analysis results
        """
        analysis = {
            'query_length': len(sql_query),
            'line_count': len(sql_query.split('\n')),
            'has_cross_join': 'CROSS JOIN' in sql_query,
            'has_union': 'UNION' in sql_query,
            'has_distinct': 'DISTINCT' in sql_query,
            'has_like': 'LIKE' in sql_query or 'ILIKE' in sql_query,
            'cross_join_count': sql_query.count('CROSS JOIN'),
            'union_count': sql_query.count('UNION'),
        }
        
        # Count table aliases
        quad_tables = re.findall(r'\b(q\d+)\b', sql_query)
        term_tables = re.findall(r'\b(\w+_term_\w+)\s+(\w+_term_\d+)', sql_query)
        
        analysis['quad_table_count'] = len(set(quad_tables))
        analysis['term_table_count'] = len(term_tables)
        analysis['total_table_count'] = analysis['quad_table_count'] + analysis['term_table_count']
        
        return analysis
    
    async def execute_sparql_query(self, space_id: str, sparql_query: str) -> List[Dict[str, Any]]:
        """
        Execute a SPARQL query against the specified space.
        
        This is the main public API method that maintains compatibility with
        the original implementation while using the new orchestrator helper functions.
        It now includes automatic SQL logging before execution.
        
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
            
            # Generate SQL for logging (without executing)
            try:
                generated_sql = await self._translate_sparql_to_sql(space_id, sparql_query)
                
                # Analyze SQL structure
                analysis = self._analyze_sql_structure(generated_sql)
                
                # Log SQL analysis summary
                self.logger.info(
                    f"Generated SQL Analysis: {analysis['query_length']} chars, "
                    f"{analysis['total_table_count']} tables "
                    f"({analysis['quad_table_count']} quad + {analysis['term_table_count']} term), "
                    f"{analysis['cross_join_count']} CROSS JOINs, "
                    f"{analysis['union_count']} UNIONs"
                )
                
                # Log formatted SQL
                formatted_sql = self._format_sql_for_logging(generated_sql)
                self.logger.info(f"Generated SQL:\n{formatted_sql}")
                
                # Log optimizer insights
                if analysis['has_cross_join']:
                    self.logger.info(
                        "SQL uses CROSS JOINs for optimizer flexibility - "
                        "PostgreSQL will choose optimal join order based on statistics"
                    )
                
                if analysis['has_like']:
                    self.logger.info(
                        "SQL contains text search (LIKE/ILIKE) - "
                        "consider trigram indexes for better performance"
                    )
                    
            except Exception as sql_error:
                self.logger.warning(f"Could not generate SQL for logging: {sql_error}")
            
            # Execute the query using orchestrator
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
        
        This method generates SQL without executing it, useful for logging and debugging.
        
        Args:
            space_id: Space identifier for table name resolution
            sparql_query: SPARQL query string
            
        Returns:
            SQL query string
        """
        try:
            # Parse SPARQL query using RDFLib
            from rdflib.plugins.sparql import prepareQuery
            from rdflib import Variable
            prepared_query = prepareQuery(sparql_query)
            query_algebra = prepared_query.algebra
            
            # Determine query type
            query_type = query_algebra.name
            
            # Get table configuration
            table_config = create_table_config(self.space_impl, space_id)
            
            # Get term cache from space implementation
            term_cache = self.space_impl.get_term_cache()
            
            # Use datatype cache from space implementation
            datatype_cache = self.space_impl.get_datatype_cache(space_id)
            
            # Create translation context
            context = SparqlContext(
                alias_generator=AliasGenerator(),
                term_cache=term_cache,
                space_impl=self.space_impl,
                table_config=table_config,
                datatype_cache=datatype_cache,
                space_id=space_id
            )
            # Add logger and graph_cache as attributes
            context.logger = self.logger
            context.graph_cache = self.graph_cache
            
            # Translate query based on type - follow exact original implementation pattern
            if query_type == "SelectQuery":
                # Extract projection variables
                projection_vars = getattr(query_algebra, 'PV', [])
                
                # Check if we have a DISTINCT pattern and extract LIMIT/OFFSET
                pattern = query_algebra.p
                has_explicit_distinct = _has_distinct_pattern(pattern)
                limit_info = _extract_limit_offset(pattern)
                
                # Translate the main pattern to get SQLComponents with ORDER BY support
                sql_components = await translate_algebra_pattern_to_components(pattern, context, projection_vars)
                
                # SPARQL BGP queries with CROSS JOINs need DISTINCT to eliminate duplicates
                # Check if this query uses CROSS JOINs (multiple quad tables) that require deduplication
                needs_bgp_distinct = any('CROSS JOIN' in join for join in sql_components.joins) if sql_components.joins else False
                
                # Use DISTINCT if explicitly specified OR if BGP query uses CROSS JOINs
                use_distinct = has_explicit_distinct or needs_bgp_distinct
                
                # Use the proper query builder that includes ORDER BY support
                sql_query = build_select_query(
                    sql_components=sql_components,
                    projection_vars=projection_vars,
                    distinct=use_distinct,
                    limit_offset=(limit_info['limit'], limit_info['offset'])
                )
                
            elif query_type == "ConstructQuery":
                # Extract construct template
                construct_template = getattr(query_algebra, 'template', [])
                
                # Extract variables from CONSTRUCT template to ensure proper mappings
                construct_vars = set()
                for triple in construct_template:
                    for term in triple:
                        from rdflib import Variable
                        if isinstance(term, Variable):
                            construct_vars.add(term)
                
                # Convert to list for projected_vars parameter
                projected_vars = list(construct_vars) if construct_vars else None
                
                # Extract LIMIT/OFFSET for CONSTRUCT queries
                pattern = query_algebra.p
                limit_info = _extract_limit_offset(pattern)
                
                # Translate the WHERE clause pattern to get SQL components
                sql_components = await translate_algebra_pattern_to_components(pattern, context, projected_vars)
                
                # Build CONSTRUCT query using the newer SQLComponents-based function
                sql_query = build_construct_query(sql_components, construct_template)
                
            elif query_type == "AskQuery":
                # Extract LIMIT/OFFSET for ASK queries
                pattern = query_algebra.p
                limit_info = _extract_limit_offset(pattern)
                
                base_sql_query = await _translate_ask_query(query_algebra, context)
                
                # Apply LIMIT/OFFSET to ASK queries
                sql_parts = [base_sql_query]
                if limit_info['offset'] is not None:
                    sql_parts.append(f"OFFSET {limit_info['offset']}")
                if limit_info['limit'] is not None:
                    sql_parts.append(f"LIMIT {limit_info['limit']}")
                
                sql_query = '\n'.join(sql_parts)
                
            elif query_type == "DescribeQuery":
                # Extract LIMIT/OFFSET for DESCRIBE queries
                pattern = query_algebra.p
                limit_info = _extract_limit_offset(pattern)
                
                base_sql_query = await _translate_describe_query(query_algebra, context)
                
                # Apply LIMIT/OFFSET to DESCRIBE queries
                sql_parts = [base_sql_query]
                if limit_info['offset'] is not None:
                    sql_parts.append(f"OFFSET {limit_info['offset']}")
                if limit_info['limit'] is not None:
                    sql_parts.append(f"LIMIT {limit_info['limit']}")
                
                sql_query = '\n'.join(sql_parts)
            else:
                raise NotImplementedError(f"Unsupported query type: {query_type}")
            
            return sql_query
            
        except Exception as e:
            self.logger.error(f"Error translating SPARQL to SQL: {e}")
            raise
    
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