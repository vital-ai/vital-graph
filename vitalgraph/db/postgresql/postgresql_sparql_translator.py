"""
PostgreSQL SPARQL Translator Implementation for VitalGraph

This module handles the translation of SPARQL queries to PostgreSQL SQL.
Supports SELECT, ASK, DESCRIBE, and CONSTRUCT query types with full
SPARQL 1.1 algebra translation.
"""

import logging
from typing import List, Dict, Tuple, Set, Optional, Any, Union
from rdflib import Variable, URIRef, Literal, BNode
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.algebra import translateQuery

# Import shared utilities
from .postgresql_sparql_utils import TableConfig, AliasGenerator, SparqlUtils


class PostgreSQLSparqlTranslator:
    """Handles translation of SPARQL queries to PostgreSQL SQL."""
    
    def __init__(self, space_impl, logger: Optional[logging.Logger] = None):
        """Initialize the SPARQL translator.
        
        Args:
            space_impl: PostgreSQL space implementation instance
            logger: Optional logger instance. If None, creates a new logger.
        """
        self.space_impl = space_impl
        self.logger = logger or logging.getLogger(__name__)
        self.variable_counter = 0
        self.join_counter = 0
    
    async def translate_sparql_to_sql(self, space_id: str, sparql_query: str) -> str:
        """
        Translate SPARQL query to SQL using RDFLib's algebra representation.
        
        Args:
            space_id: Space identifier for table name resolution
            sparql_query: SPARQL query string
            
        Returns:
            SQL query string
        """
        try:
            # Create table configuration for logged tables (testing logged table performance)
            table_config = TableConfig.from_space_impl(self.space_impl, space_id)
            
            # Parse and get algebra
            prepared_query = prepareQuery(sparql_query)
            algebra = prepared_query.algebra
            
            self.logger.info(f"Translating SPARQL query with algebra: {algebra.name}")
            
            # Log detailed algebra structure for debugging OPTIONAL patterns
            self._log_algebra_structure(algebra, "ROOT", 0)
            
            # Reset counters for each query
            self.variable_counter = 0
            self.join_counter = 0
            
            # Translate based on query type
            if algebra.name == "SelectQuery":
                sql_query = await self.translate_select_query(algebra, table_config)
            elif algebra.name == "ConstructQuery":
                sql_query = await self.translate_construct_query(algebra, table_config)
            elif algebra.name == "AskQuery":
                sql_query = await self.translate_ask_query(algebra, table_config)
            elif algebra.name == "DescribeQuery":
                sql_query = await self.translate_describe_query(algebra, table_config)
            else:
                raise NotImplementedError(f"Query type {algebra.name} not yet supported")
            
            # Log generated SQL for debugging
            self.logger.info(f"Generated SQL query ({len(sql_query)} chars):")
            self.logger.info(f"SQL: {sql_query}")
            
            return sql_query
                
        except Exception as e:
            self.logger.error(f"Error translating SPARQL query: {e}")
            raise

    async def translate_select_query(self, algebra, table_config: TableConfig) -> str:
        """Translate SELECT query algebra to SQL."""
        
        # Extract projection variables
        projection_vars = algebra.get('PV', [])
        
        # Check if we have a DISTINCT pattern and extract LIMIT/OFFSET
        pattern = algebra['p']
        has_distinct = self._has_distinct_pattern(pattern)
        limit_info = self._extract_limit_offset(pattern)
        
        # Extract and translate the main pattern
        from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern(pattern, table_config, projection_vars)
        
        # Build SELECT clause, GROUP BY clause, and HAVING clause with variable mappings
        select_clause, group_by_clause, having_clause = self._build_select_clause(projection_vars, variable_mappings, has_distinct)
        
        # Build complete SQL query
        sql_parts = [select_clause]
        sql_parts.append(from_clause)
        
        if joins:
            sql_parts.extend(joins)
        
        # Check if this is a UNION-derived table - if so, don't apply outer WHERE conditions
        # UNION patterns are self-contained and all conditions are already within subqueries
        is_union_derived = "union_" in from_clause and "FROM (" in from_clause
        
        if where_conditions and not is_union_derived:
            sql_parts.append(f"WHERE {' AND '.join(where_conditions)}")
        elif where_conditions and is_union_derived:
            self.logger.debug(f"Skipping {len(where_conditions)} WHERE conditions for UNION-derived table")
        
        # Add GROUP BY clause if present
        if group_by_clause:
            sql_parts.append(group_by_clause)
        
        # CRITICAL: Add HAVING clause AFTER GROUP BY (this is the fix for HAVING clause support)
        if having_clause:
            sql_parts.append(having_clause)
        
        # Add LIMIT and OFFSET if present
        if limit_info['offset'] is not None:
            sql_parts.append(f"OFFSET {limit_info['offset']}")
        if limit_info['limit'] is not None:
            sql_parts.append(f"LIMIT {limit_info['limit']}")
            
        return '\n'.join(sql_parts)

    
    async def translate_ask_query(self, algebra, table_config: TableConfig) -> str:
        """
        Translate ASK query to SQL.
        
        ASK queries check if a pattern exists in the graph and return a boolean result.
        Implementation strategy: Convert to SELECT with LIMIT 1, then check if any results exist.
        
        Args:
            algebra: RDFLib AskQuery algebra object
            table_config: Table configuration for SQL generation
            
        Returns:
            SQL query string that returns data if pattern exists (for boolean conversion)
        """
        try:
            self.logger.info("Translating ASK query")
            
            # Extract WHERE clause pattern from algebra.p
            if not hasattr(algebra, 'p') or not algebra.p:
                raise ValueError("ASK query missing WHERE clause")
            
            where_pattern = algebra.p
            self.logger.debug(f"ASK WHERE pattern type: {where_pattern.name}")
            
            # Get variables from the pattern (needed for SQL generation)
            all_vars = list(where_pattern.get('_vars', set()))
            if not all_vars:
                # If no variables found in pattern, try to extract from sub-patterns
                all_vars = self._extract_variables_from_pattern(where_pattern)
            
            # If still no variables, create a dummy variable for SQL generation
            if not all_vars:
                all_vars = [Variable('dummy')]
            
            self.logger.debug(f"ASK pattern variables: {all_vars}")
            
            # Translate the pattern to SQL components
            from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern(
                where_pattern, table_config, all_vars
            )
            
            # Build a simple SELECT query with LIMIT 1 to check existence
            # We only need to know if any results exist, not the actual data
            select_clause = "SELECT 1"
            
            # Build complete SQL query
            sql_parts = [select_clause]
            sql_parts.append(from_clause)
            
            if joins:
                sql_parts.extend(joins)
                
            if where_conditions:
                sql_parts.append(f"WHERE {' AND '.join(where_conditions)}")
            
            # Add LIMIT 1 for efficiency - we only need to know if any results exist
            sql_parts.append("LIMIT 1")
            
            sql_query = " ".join(sql_parts)
            
            # Clean up SQL before execution
            sql_query = self._cleanup_sql_before_execution(sql_query)
            
            self.logger.info("Successfully translated ASK query")
            return sql_query
            
        except Exception as e:
            self.logger.error(f"Error translating ASK query: {e}")
            raise NotImplementedError(f"ASK query translation failed: {e}")


    async def translate_describe_query(self, algebra, table_config: TableConfig) -> str:
        """
        Translate DESCRIBE query to SQL.
        
        DESCRIBE queries return all properties (triples) of specified resources.
        Implementation strategy: Generate SQL to find all quads where the described resource(s) are subjects.
        
        Args:
            algebra: RDFLib DescribeQuery algebra object
            table_config: Table configuration for SQL generation
            
        Returns:
            SQL query string that returns all triples for the described resources
        """
        try:
            self.logger.info("Translating DESCRIBE query")
            
            # Extract the resources to describe from algebra
            describe_vars = []
            describe_uris = []
            
            # Check if there's a WHERE clause (DESCRIBE ?var WHERE { ... })
            if hasattr(algebra, 'p') and algebra.p:
                # DESCRIBE with WHERE clause - extract variables from WHERE pattern
                where_pattern = algebra.p
                self.logger.debug(f"DESCRIBE with WHERE clause, pattern type: {where_pattern.name}")
                
                # Get variables from the WHERE pattern
                where_vars = list(where_pattern.get('_vars', set()))
                if not where_vars:
                    where_vars = self._extract_variables_from_pattern(where_pattern)
                
                # First, execute the WHERE clause to find the resources to describe
                from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern(
                    where_pattern, table_config, where_vars
                )
                
                # Build SELECT query for the WHERE clause to get resource URIs
                select_vars = [var for var in where_vars if var in variable_mappings]
                if not select_vars:
                    raise ValueError("No valid variables found in DESCRIBE WHERE clause")
                
                # Use the first variable as the resource to describe
                describe_var = select_vars[0]
                describe_var_sql = variable_mappings[describe_var]
                
                # Build subquery to get the resources to describe
                subquery_parts = [f"SELECT DISTINCT {describe_var_sql} AS resource_uri"]
                subquery_parts.append(from_clause)
                
                if joins:
                    subquery_parts.extend(joins)
                    
                if where_conditions:
                    subquery_parts.append(f"WHERE {' AND '.join(where_conditions)}")
                
                # Add ORDER BY and LIMIT if present in the algebra
                if hasattr(algebra, 'orderBy') and algebra.orderBy:
                    # Handle ORDER BY clause
                    pass  # TODO: Implement ORDER BY for DESCRIBE
                
                if hasattr(algebra, 'length') and algebra.length:
                    subquery_parts.append(f"LIMIT {algebra.length}")
                
                subquery_sql = " ".join(subquery_parts)
                
                # Now build the main query to get all triples for the found resources
                main_sql = f"""
                SELECT 
                    s_term.term_text AS subject,
                    p_term.term_text AS predicate, 
                    o_term.term_text AS object
                FROM ({subquery_sql}) resources
                JOIN {table_config.quad_table} q ON q.subject_uuid = (
                    SELECT term_uuid FROM {table_config.term_table} 
                    WHERE term_text = resources.resource_uri AND term_type = 'U'
                )
                JOIN {table_config.term_table} s_term ON q.subject_uuid = s_term.term_uuid
                JOIN {table_config.term_table} p_term ON q.predicate_uuid = p_term.term_uuid  
                JOIN {table_config.term_table} o_term ON q.object_uuid = o_term.term_uuid
                ORDER BY subject, predicate, object
                """
                
            else:
                # Simple DESCRIBE <uri> without WHERE clause
                # Try multiple ways to extract the resource(s) from algebra
                describe_resources = []
                
                # Method 1: Check algebra.res
                if hasattr(algebra, 'res') and algebra.res:
                    describe_resources = algebra.res if isinstance(algebra.res, list) else [algebra.res]
                
                # Method 2: Check algebra.term (alternative attribute name)
                elif hasattr(algebra, 'term') and algebra.term:
                    describe_resources = algebra.term if isinstance(algebra.term, list) else [algebra.term]
                
                # Method 3: Check if algebra itself contains the resource info
                elif hasattr(algebra, '__dict__'):
                    # Look for any attribute that might contain the resource
                    for attr_name, attr_value in algebra.__dict__.items():
                        if attr_value and not attr_name.startswith('_') and attr_name not in ['name', 'p']:
                            if isinstance(attr_value, (list, tuple)):
                                describe_resources = list(attr_value)
                                break
                            else:
                                describe_resources = [attr_value]
                                break
                
                if describe_resources:
                    # Convert RDFLib terms to SQL-safe strings
                    resource_conditions = []
                    for resource in describe_resources:
                        if hasattr(resource, 'toPython'):
                            resource_uri = str(resource)
                        else:
                            resource_uri = str(resource)
                        
                        # Escape single quotes in URI for SQL safety
                        resource_uri = resource_uri.replace("'", "''")
                        
                        # Add condition to find this resource as subject
                        resource_conditions.append(f"s_term.term_text = '{resource_uri}'")
                    
                    self.logger.debug(f"DESCRIBE resources: {[str(r) for r in describe_resources]}")
                    
                    # Build SQL to get all triples where the specified resource(s) are subjects
                    main_sql = f"""
                    SELECT 
                        s_term.term_text AS subject,
                        p_term.term_text AS predicate,
                        o_term.term_text AS object
                    FROM {table_config.quad_table} q
                    JOIN {table_config.term_table} s_term ON q.subject_uuid = s_term.term_uuid
                    JOIN {table_config.term_table} p_term ON q.predicate_uuid = p_term.term_uuid
                    JOIN {table_config.term_table} o_term ON q.object_uuid = o_term.term_uuid
                    WHERE ({' OR '.join(resource_conditions)})
                    ORDER BY subject, predicate, object
                    """
                else:
                    # If no resources found, return empty result set instead of error
                    self.logger.warning("No resources specified in DESCRIBE query, returning empty result")
                    main_sql = f"""
                    SELECT 
                        '' AS subject,
                        '' AS predicate,
                        '' AS object
                    WHERE 1=0
                    """
            
            # Clean up SQL before execution
            sql_query = self._cleanup_sql_before_execution(main_sql)
            
            self.logger.info("Successfully translated DESCRIBE query")
            return sql_query
            
        except Exception as e:
            self.logger.error(f"Error translating DESCRIBE query: {e}")
            raise NotImplementedError(f"DESCRIBE query translation failed: {e}")


    async def translate_construct_query(self, algebra, table_config: TableConfig) -> str:
        """Translate CONSTRUCT query algebra to SQL.
        
        CONSTRUCT queries work by:
        1. Extracting the CONSTRUCT template (what triples to build)
        2. Translating the WHERE clause to SQL (like SELECT queries)
        3. Mapping SQL results back to RDF triples/quads per template
        
        Args:
            algebra: RDFLib ConstructQuery algebra object
            table_config: Table configuration for SQL generation
            
        Returns:
            SQL query string that returns data for CONSTRUCT template
        """
        try:
            self.logger.info("Translating CONSTRUCT query")
            
            # Extract CONSTRUCT template - list of (subject, predicate, object) triples
            if not hasattr(algebra, 'template') or not algebra.template:
                raise ValueError("CONSTRUCT query missing template")
            
            construct_template = algebra.template
            self.logger.debug(f"CONSTRUCT template has {len(construct_template)} triples")
            
            # Extract WHERE clause pattern from algebra.p
            if not hasattr(algebra, 'p') or not algebra.p:
                raise ValueError("CONSTRUCT query missing WHERE clause")
            
            where_pattern = algebra.p
            self.logger.debug(f"WHERE pattern type: {where_pattern.name}")
            
            # Translate the WHERE clause to SQL (reuse existing SELECT logic)
            # The WHERE clause contains the pattern that finds variable bindings
            sql_query = await self._translate_select_pattern(where_pattern, table_config)
            
            # Store the template for result processing
            # Note: In a full implementation, we'd need to return both SQL and template
            # For now, we'll add template info as SQL comments for debugging
            template_comment = "-- CONSTRUCT template:\n"
            for i, (s, p, o) in enumerate(construct_template):
                template_comment += f"--   [{i+1}] {s} {p} {o}\n"
            
            final_sql = template_comment + sql_query
            
            self.logger.info(f"Successfully translated CONSTRUCT query with {len(construct_template)} template triples")
            return final_sql
            
        except Exception as e:
            self.logger.error(f"Error translating CONSTRUCT query: {e}")
            raise NotImplementedError(f"CONSTRUCT query translation failed: {e}")
    
    def get_supported_query_types(self) -> Set[str]:
        """Get the set of supported SPARQL query types.
        
        Returns:
            Set of supported query type names
        """
        return {"SelectQuery", "ConstructQuery", "AskQuery", "DescribeQuery"}
    
    def is_supported_query_type(self, query_type: str) -> bool:
        """Check if a query type is supported.
        
        Args:
            query_type: Name of the query type to check
            
        Returns:
            True if the query type is supported
        """
        return query_type in self.get_supported_query_types()
    
    def validate_sparql_query(self, sparql_query: str) -> bool:
        """Validate that a SPARQL query can be parsed.
        
        Args:
            sparql_query: SPARQL query string to validate
            
        Returns:
            True if the query is valid
        """
        try:
            prepared_query = prepareQuery(sparql_query)
            return prepared_query is not None and hasattr(prepared_query, 'algebra')
        except Exception as e:
            self.logger.error(f"SPARQL query validation failed: {e}")
            return False
    
    def extract_query_type(self, sparql_query: str) -> Optional[str]:
        """Extract the query type from a SPARQL query.
        
        Args:
            sparql_query: SPARQL query string
            
        Returns:
            Query type name or None if extraction fails
        """
        try:
            prepared_query = prepareQuery(sparql_query)
            return prepared_query.algebra.name if prepared_query.algebra else None
        except Exception as e:
            self.logger.error(f"Query type extraction failed: {e}")
            return None
    
    def extract_projection_variables(self, algebra) -> List[Variable]:
        """Extract projection variables from query algebra.
        
        Args:
            algebra: RDFLib query algebra object
            
        Returns:
            List of projection variables
        """
        if hasattr(algebra, 'get'):
            return algebra.get('PV', [])
        elif hasattr(algebra, 'PV'):
            return algebra.PV or []
        else:
            return []
    
    def has_distinct_pattern(self, pattern) -> bool:
        """Check if a pattern contains a DISTINCT modifier.
        
        Args:
            pattern: SPARQL algebra pattern
            
        Returns:
            True if pattern has DISTINCT
        """
        if hasattr(pattern, 'name') and pattern.name == 'Distinct':
            return True
        elif hasattr(pattern, 'p'):
            return self.has_distinct_pattern(pattern.p)
        else:
            return False
    
    def extract_limit_offset(self, pattern) -> Tuple[Optional[int], Optional[int]]:
        """Extract LIMIT and OFFSET values from a pattern.
        
        Args:
            pattern: SPARQL algebra pattern
            
        Returns:
            Tuple of (limit, offset) values
        """
        limit = None
        offset = None
        
        # Check for Slice pattern (LIMIT/OFFSET)
        if hasattr(pattern, 'name') and pattern.name == 'Slice':
            if hasattr(pattern, 'start'):
                offset = pattern.start
            if hasattr(pattern, 'length'):
                limit = pattern.length
        elif hasattr(pattern, 'p'):
            # Recursively check nested patterns
            return self.extract_limit_offset(pattern.p)
        
        return limit, offset
    
    def build_select_clause(self, projection_vars: List[Variable], 
                           variable_mappings: Dict[Variable, str], 
                           has_distinct: bool = False) -> Tuple[str, Optional[str], Optional[str]]:
        """Build SELECT clause with GROUP BY and HAVING clauses.
        
        Args:
            projection_vars: Variables to project
            variable_mappings: Variable to SQL column mappings
            has_distinct: Whether to include DISTINCT
            
        Returns:
            Tuple of (select_clause, group_by_clause, having_clause)
        """
        if not projection_vars:
            # SELECT * equivalent
            select_parts = ['*']
        else:
            select_parts = []
            for var in projection_vars:
                if var in variable_mappings:
                    column_expr = variable_mappings[var]
                    var_name = var.toPython().lower()
                    select_parts.append(f"{column_expr} AS {var_name}")
                else:
                    # Variable not mapped - use NULL
                    var_name = var.toPython().lower()
                    select_parts.append(f"NULL AS {var_name}")
                    self.logger.warning(f"Variable {var} not found in mappings")
        
        # Build SELECT clause
        distinct_keyword = "DISTINCT " if has_distinct else ""
        select_clause = f"SELECT {distinct_keyword}{', '.join(select_parts)}"
        
        # Check for GROUP BY requirements (aggregate functions)
        group_by_clause = None
        having_clause = None
        
        # Extract HAVING conditions from variable mappings
        if '__HAVING_CONDITIONS__' in variable_mappings:
            having_conditions = variable_mappings['__HAVING_CONDITIONS__']
            if having_conditions:
                having_clause = f"HAVING {' AND '.join(having_conditions)}"
        
        return select_clause, group_by_clause, having_clause
    
    def log_algebra_structure(self, algebra, label: str = "ROOT", depth: int = 0) -> None:
        """Log the structure of SPARQL algebra for debugging.
        
        Args:
            algebra: SPARQL algebra object
            label: Label for this algebra node
            depth: Current nesting depth
        """
        indent = "  " * depth
        algebra_name = getattr(algebra, 'name', type(algebra).__name__)
        self.logger.debug(f"{indent}{label}: {algebra_name}")
        
        # Log key attributes
        if hasattr(algebra, 'PV') and algebra.PV:
            self.logger.debug(f"{indent}  Projection: {algebra.PV}")
        
        # Recursively log nested patterns
        if hasattr(algebra, 'p'):
            self.log_algebra_structure(algebra.p, "Pattern", depth + 1)
        if hasattr(algebra, 'p1'):
            self.log_algebra_structure(algebra.p1, "Left", depth + 1)
        if hasattr(algebra, 'p2'):
            self.log_algebra_structure(algebra.p2, "Right", depth + 1)
    
    def cleanup_sql_before_execution(self, sql: str) -> str:
        """Clean up SQL query before execution.
        
        Args:
            sql: Raw SQL query
            
        Returns:
            Cleaned SQL query
        """
        # Remove extra whitespace and normalize line endings
        cleaned = ' '.join(sql.split())
        
        # Remove any trailing semicolons (they can cause issues with some drivers)
        cleaned = cleaned.rstrip(';')
        
        return cleaned
    
    def estimate_query_complexity(self, algebra) -> int:
        """Estimate the computational complexity of a query.
        
        Args:
            algebra: SPARQL algebra object
            
        Returns:
            Complexity score (higher = more complex)
        """
        if not hasattr(algebra, 'name'):
            return 1
        
        complexity = 1
        algebra_name = algebra.name
        
        # Base complexity by query type
        if algebra_name == "SelectQuery":
            complexity = 2
        elif algebra_name == "ConstructQuery":
            complexity = 3
        elif algebra_name == "AskQuery":
            complexity = 1
        elif algebra_name == "DescribeQuery":
            complexity = 2
        
        # Add complexity for nested patterns
        if hasattr(algebra, 'p'):
            complexity += self.estimate_pattern_complexity(algebra.p)
        
        return complexity
    
    def estimate_pattern_complexity(self, pattern) -> int:
        """Estimate the complexity of a SPARQL pattern.
        
        Args:
            pattern: SPARQL algebra pattern
            
        Returns:
            Complexity score
        """
        if not hasattr(pattern, 'name'):
            return 1
        
        pattern_name = pattern.name
        complexity = 1
        
        if pattern_name == "BGP":
            # Complexity based on number of triples
            if hasattr(pattern, 'triples'):
                complexity = len(pattern.triples)
        elif pattern_name == "Union":
            complexity = 5  # Unions are expensive
        elif pattern_name == "LeftJoin":
            complexity = 3  # OPTIONAL patterns
        elif pattern_name == "Minus":
            complexity = 4  # MINUS patterns
        elif pattern_name == "Filter":
            complexity = 2  # Filter conditions
        elif pattern_name == "AggregateJoin":
            complexity = 6  # Aggregates are expensive
        elif pattern_name == "Group":
            complexity = 4  # GROUP BY operations
        
        # Add complexity for nested patterns
        if hasattr(pattern, 'p'):
            complexity += self.estimate_pattern_complexity(pattern.p)
        if hasattr(pattern, 'p1'):
            complexity += self.estimate_pattern_complexity(pattern.p1)
        if hasattr(pattern, 'p2'):
            complexity += self.estimate_pattern_complexity(pattern.p2)
        
        return complexity
    
    def generate_query_statistics(self, sparql_query: str) -> Dict[str, Any]:
        """Generate statistics about a SPARQL query.
        
        Args:
            sparql_query: SPARQL query string
            
        Returns:
            Dictionary of query statistics
        """
        try:
            prepared_query = prepareQuery(sparql_query)
            algebra = prepared_query.algebra
            
            stats = {
                'query_type': algebra.name,
                'query_length': len(sparql_query),
                'complexity_score': self.estimate_query_complexity(algebra),
                'projection_variables': len(self.extract_projection_variables(algebra)),
                'has_distinct': self.has_distinct_pattern(algebra.get('p') if hasattr(algebra, 'get') else getattr(algebra, 'p', None)),
                'has_limit_offset': any(self.extract_limit_offset(algebra.get('p') if hasattr(algebra, 'get') else getattr(algebra, 'p', None))),
                'supported': self.is_supported_query_type(algebra.name)
            }
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Error generating query statistics: {e}")
            return {
                'query_type': 'unknown',
                'query_length': len(sparql_query),
                'complexity_score': 0,
                'projection_variables': 0,
                'has_distinct': False,
                'has_limit_offset': False,
                'supported': False,
                'error': str(e)
            }

    