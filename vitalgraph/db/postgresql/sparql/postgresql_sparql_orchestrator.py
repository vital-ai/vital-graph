"""
PostgreSQL SPARQL Orchestrator for VitalGraph

This is the main orchestrator class that coordinates all SPARQL operations
using the new function-based modular architecture. It maintains the same public API
as the original PostgreSQLSparqlImpl for seamless replacement.
"""

import logging
from typing import Dict, List, Tuple, Optional, Any
from rdflib import Variable, URIRef, Literal, BNode
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.algebra import translateQuery

# Import PostgreSQL space implementation and utilities
from ..postgresql_space_impl import PostgreSQLSpaceImpl
from ..postgresql_utils import PostgreSQLUtils
from ..postgresql_term_cache import PostgreSQLTermCache

# Import all function modules
from .postgresql_sparql_core import (
    SQLComponents, TableConfig, AliasGenerator, GraphConstants, TranslationContext,
    validate_sql_components
)
from .postgresql_sparql_core import generate_bgp_sql, generate_term_lookup_sql, build_join_conditions
from .postgresql_sparql_cache_integration import generate_bgp_sql_with_cache
from .postgresql_sparql_patterns import (
    translate_union_pattern, translate_optional_pattern, translate_minus_pattern,
    translate_values_pattern, translate_join_pattern, translate_bind_pattern,
    translate_filter_pattern, translate_graph_pattern, translate_subquery_pattern,
    find_shared_variables, extract_variables_from_triples, validate_pattern_structure,
    translate_algebra_pattern
)
from .postgresql_sparql_expressions import (
    translate_filter_expression, translate_bind_expression, translate_aggregate_expression,
    extract_variables_from_expression
)
from .postgresql_sparql_queries import (
    build_select_query, build_construct_query, build_ask_query, build_describe_query,
    build_aggregation_query, build_subquery, build_union_query,
    optimize_query_structure, validate_query_syntax, estimate_query_cost
)
from .postgresql_sparql_updates import (
    translate_insert_data, translate_delete_data, translate_modify_operation,
    translate_load_operation, translate_clear_operation, translate_create_operation,
    translate_drop_operation, translate_copy_operation, translate_move_operation,
    translate_add_operation, validate_update_operation, estimate_update_cost
)


def _extract_variables_from_pattern(pattern):
    """Extract variables from a pattern recursively.
    
    Args:
        pattern: RDFLib pattern algebra object
        
    Returns:
        List of variables found in the pattern
    """
    variables = set()
    
    # Check if pattern has _vars attribute
    if hasattr(pattern, '_vars') and pattern._vars:
        variables.update(pattern._vars)
    
    # Check for variables in common pattern attributes
    for attr in ['p', 'triples', 'PV']:
        if hasattr(pattern, attr):
            attr_value = getattr(pattern, attr)
            if attr == 'triples' and isinstance(attr_value, list):
                # Extract variables from triples
                for triple in attr_value:
                    if triple:  # Check if triple is not None
                        for term in triple:
                            if hasattr(term, 'n3') and str(term).startswith('?'):
                                variables.add(term)
            elif attr == 'PV' and isinstance(attr_value, list):
                # Projection variables
                variables.update(attr_value)
            elif hasattr(attr_value, '_vars') and attr_value._vars:
                # Nested pattern with variables
                variables.update(attr_value._vars)
    
    return list(variables)


async def _translate_ask_query(algebra, table_config: TableConfig, context: TranslationContext) -> str:
    """
    Translate ASK query to SQL - exact copy from original implementation.
    
    ASK queries check if a pattern exists in the graph and return a boolean result.
    Implementation strategy: Convert to SELECT with LIMIT 1, then check if any results exist.
    
    Args:
        algebra: RDFLib AskQuery algebra object
        table_config: Table configuration for SQL generation
        context: Translation context
        
    Returns:
        SQL query string that returns data if pattern exists (for boolean conversion)
    """
    try:
        logger = context.logger
        logger.info("Translating ASK query")
        
        # Extract WHERE clause pattern from algebra.p
        if not hasattr(algebra, 'p') or not algebra.p:
            raise ValueError("ASK query missing WHERE clause")
        
        where_pattern = algebra.p
        logger.debug(f"ASK WHERE pattern type: {where_pattern.name}")
        
        # Get variables from the pattern (needed for SQL generation)
        all_vars = list(where_pattern.get('_vars', set()))
        if not all_vars:
            # If no variables found in pattern, try to extract from sub-patterns
            all_vars = _extract_variables_from_pattern(where_pattern)
        
        # If still no variables, create a dummy variable for SQL generation
        if not all_vars:
            from rdflib import Variable
            all_vars = [Variable('dummy')]
        
        logger.debug(f"ASK pattern variables: {all_vars}")
        
        # Translate the pattern to SQL components using the new architecture
        sql_components = await translate_algebra_pattern(where_pattern, context, all_vars)
        
        # Build a simple SELECT query with LIMIT 1 to check existence
        # We only need to know if any results exist, not the actual data
        select_clause = "SELECT 1"
        
        # Build complete SQL query
        sql_parts = [select_clause]
        sql_parts.append(sql_components.from_clause)
        
        if sql_components.joins:
            sql_parts.extend(sql_components.joins)
            
        if sql_components.where_conditions:
            sql_parts.append(f"WHERE {' AND '.join(sql_components.where_conditions)}")
        
        # Add LIMIT 1 for efficiency - we only need to know if any results exist
        sql_parts.append("LIMIT 1")
        
        sql_query = " ".join(sql_parts)
        
        # Clean up SQL before execution (port from original if needed)
        # sql_query = _cleanup_sql_before_execution(sql_query)
        
        logger.debug(f"Generated ASK SQL: {sql_query}")
        logger.info("Successfully translated ASK query")
        return sql_query
        
    except Exception as e:
        logger.error(f"Error translating ASK query: {e}")
        raise NotImplementedError(f"ASK query translation failed: {e}")


async def _translate_describe_query(algebra, table_config: TableConfig, context: TranslationContext) -> str:
    """Translate DESCRIBE query to SQL - exact copy from original implementation."""
    logger = context.logger
    logger.info("Translating DESCRIBE query")
    
    try:
        # Extract the resources to describe from algebra
        describe_vars = []
        describe_uris = []
        
        # Check if there's a WHERE clause (DESCRIBE ?var WHERE { ... })
        if hasattr(algebra, 'p') and algebra.p:
            # DESCRIBE with WHERE clause - extract variables from WHERE pattern
            where_pattern = algebra.p
            logger.debug(f"DESCRIBE with WHERE clause, pattern type: {where_pattern.name}")
            
            # Get variables from the WHERE pattern - EXACT original logic
            # The original implementation assumes where_pattern has _vars as a set-like attribute
            if hasattr(where_pattern, '_vars') and where_pattern._vars is not None:
                where_vars = list(where_pattern._vars)
            else:
                where_vars = _extract_variables_from_pattern(where_pattern)
            
            # First, execute the WHERE clause to find the resources to describe
            sql_components = await translate_algebra_pattern(where_pattern, context, where_vars)
            
            # Build SELECT query for the WHERE clause to get resource URIs - exact original logic
            select_vars = [var for var in where_vars if var in sql_components.variable_mappings]
            if not select_vars:
                raise ValueError("No valid variables found in DESCRIBE WHERE clause")
            
            # Use the first variable as the resource to describe
            describe_var = select_vars[0]
            describe_var_sql = sql_components.variable_mappings[describe_var]
            
            # Build subquery to get the resources to describe
            subquery_parts = [f"SELECT DISTINCT {describe_var_sql} AS resource_uri"]
            subquery_parts.append(sql_components.from_clause)
            
            if sql_components.joins:
                subquery_parts.extend(sql_components.joins)
                
            if sql_components.where_conditions:
                subquery_parts.append(f"WHERE {' AND '.join(sql_components.where_conditions)}")
            
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
            # Extract URIs or variables from the algebra
            if hasattr(algebra, 'vars') and algebra.vars:
                describe_vars = list(algebra.vars)
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
                else:
                    logger.warning("No resources specified in DESCRIBE query, returning empty result")
                    return "SELECT '' AS subject, '' AS predicate, '' AS object WHERE FALSE"
                
                # Convert resources to URIs
                describe_uris = []
                for resource in describe_resources:
                    if hasattr(resource, 'n3'):
                        uri_str = resource.n3()
                        if uri_str.startswith('<') and uri_str.endswith('>'):
                            uri_str = uri_str[1:-1]  # Remove angle brackets
                        describe_uris.append(uri_str)
                    else:
                        describe_uris.append(str(resource))
                
                if not describe_uris:
                    logger.warning("No valid URIs found in DESCRIBE query, returning empty result")
                    return "SELECT '' AS subject, '' AS predicate, '' AS object WHERE FALSE"
                
                # Build SQL for simple DESCRIBE
                uri_conditions = []
                for uri in describe_uris:
                    uri_conditions.append(f"s_term.term_text = '{uri}'")
                
                main_sql = f"""
                SELECT 
                    s_term.term_text AS subject,
                    p_term.term_text AS predicate,
                    o_term.term_text AS object
                FROM {table_config.quad_table} q
                JOIN {table_config.term_table} s_term ON q.subject_uuid = s_term.term_uuid
                JOIN {table_config.term_table} p_term ON q.predicate_uuid = p_term.term_uuid
                JOIN {table_config.term_table} o_term ON q.object_uuid = o_term.term_uuid
                WHERE ({' OR '.join(uri_conditions)})
                ORDER BY subject, predicate, object
                """
        
        logger.info("Successfully translated DESCRIBE query")
        return main_sql
        
    except Exception as e:
        logger.error(f"Error translating DESCRIBE query: {e}")
        raise NotImplementedError(f"DESCRIBE query translation failed: {e}")


async def _execute_sql_query_with_space_impl(space_impl: PostgreSQLSpaceImpl, sql_query: str) -> List[Dict[str, Any]]:
    """
    Execute SQL query using the space_impl's connection method.
    This follows the same pattern as the original implementation.
    """
    try:
        # Use the space_impl's get_connection method to get a database connection
        with space_impl.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql_query)
                
                # Check if this is a SELECT query that returns results
                query_type = sql_query.strip().upper().split()[0]
                
                if query_type == 'SELECT':
                    # Get column names
                    columns = [desc[0] for desc in cursor.description] if cursor.description else []
                    
                    # Fetch all results
                    rows = cursor.fetchall()
                    
                    # Convert to list of dictionaries
                    results = []
                    for row in rows:
                        if isinstance(row, dict):
                            # Row is already a dictionary (some cursor configurations)
                            results.append(row)
                        else:
                            # Row is a tuple/list - convert to dictionary
                            result_dict = {}
                            for i, value in enumerate(row):
                                if i < len(columns):
                                    result_dict[columns[i]] = value
                            results.append(result_dict)
                    
                    return results
                else:
                    # For INSERT/UPDATE/DELETE operations, return row count information
                    rows_affected = cursor.rowcount if hasattr(cursor, 'rowcount') else 0
                    return [{'operation': query_type, 'rows_affected': rows_affected}]
            
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error executing SQL query: {e}")
        logger.error(f"SQL query was: {sql_query}")
        raise


def create_table_config(space_impl: PostgreSQLSpaceImpl, space_id: str) -> TableConfig:
    """
    Create table configuration for the specified space.
    
    Args:
        space_impl: PostgreSQL space implementation
        space_id: Space identifier
        
    Returns:
        TableConfig with table names for the space
    """
    return TableConfig.from_space_impl(space_impl, space_id)


def _has_distinct_pattern(pattern) -> bool:
    """Check if pattern contains DISTINCT modifier. Exact port from original."""
    if hasattr(pattern, 'name') and pattern.name == "Distinct":
        return True
    if hasattr(pattern, 'p'):
        return _has_distinct_pattern(pattern.p)
    return False


def _build_select_clause(projection_vars: List, variable_mappings: Dict, has_distinct: bool = False) -> Tuple[str, str, str]:
    """Build SELECT clause, GROUP BY clause, and HAVING clause. Exact port from original."""
    if not projection_vars:
        # No projection variables - return all mapped variables
        select_items = []
        for var, mapping in variable_mappings.items():
            if not str(var).startswith('__'):  # Skip internal variables
                var_name = str(var).replace('?', '')
                select_items.append(f"{mapping} AS {var_name}")
        
        if not select_items:
            select_items = ["*"]
    else:
        # Build SELECT items from projection variables
        select_items = []
        for var in projection_vars:
            var_name = str(var).replace('?', '')
            if var in variable_mappings:
                var_mapping = variable_mappings[var]
                select_items.append(f"{var_mapping} AS {var_name}")
            else:
                # Variable not found in mappings - use UNMAPPED placeholder
                select_items.append(f"'UNMAPPED_VAR_{var_name}' AS {var_name}")
    
    # Build SELECT clause
    distinct_modifier = "DISTINCT " if has_distinct else ""
    select_clause = f"SELECT {distinct_modifier}{', '.join(select_items)}"
    
    # Build GROUP BY clause if GROUP BY variables are present (matching original logic)
    group_by_clause = ""
    group_by_vars = variable_mappings.get('__GROUP_BY_VARS__')
    if group_by_vars:
        group_by_items = []
        for group_var in group_by_vars:
            if group_var in variable_mappings:
                group_by_items.append(variable_mappings[group_var])
        
        if group_by_items:
            group_by_clause = f"GROUP BY {', '.join(group_by_items)}"
    
    # Build HAVING clause if HAVING conditions are present
    having_conditions = variable_mappings.get('__HAVING_CONDITIONS__', [])
    having_clause = f"HAVING {' AND '.join(having_conditions)}" if having_conditions else ''
    
    return select_clause, group_by_clause, having_clause


def build_construct_query_from_components(from_clause: str, where_conditions: List[str], 
                                        joins: List[str], variable_mappings: Dict, 
                                        construct_template: List) -> str:
    """Build CONSTRUCT query from SQL components. Exact port from original."""
    # For CONSTRUCT, we need to return all variable bindings that will be used
    # to instantiate the construct template
    construct_vars = set()
    for triple in construct_template:
        for term in triple:
            if hasattr(term, 'n3') and str(term).startswith('?'):
                construct_vars.add(term)
    
    # Build SELECT clause for construct variables
    select_items = []
    for var in construct_vars:
        if var in variable_mappings:
            var_mapping = variable_mappings[var]
            var_name = str(var).replace('?', '')
            select_items.append(f"{var_mapping} AS {var_name}")
        else:
            var_name = str(var).replace('?', '')
            select_items.append(f"'UNMAPPED_{var_name}' AS {var_name}")
    
    if not select_items:
        select_items = ["*"]
    
    # Build complete query
    query_parts = [f"SELECT {', '.join(select_items)}"]
    
    if from_clause:
        query_parts.append(from_clause)
    
    if joins:
        query_parts.extend(joins)
    
    if where_conditions:
        query_parts.append(f"WHERE {' AND '.join(where_conditions)}")
    
    return " ".join(query_parts)


def _extract_limit_offset(pattern) -> dict:
    """Recursively extract LIMIT and OFFSET from Slice patterns. Exact port from original."""
    result = {'limit': None, 'offset': None}
    
    if hasattr(pattern, 'name') and pattern.name == "Slice":
        # Slice pattern has start (offset) and length (limit)
        if hasattr(pattern, 'start') and pattern.start is not None:
            result['offset'] = pattern.start
        if hasattr(pattern, 'length') and pattern.length is not None:
            result['limit'] = pattern.length
    
    # Check nested patterns
    if hasattr(pattern, 'p'):
        nested_result = _extract_limit_offset(pattern.p)
        # Use nested values if current pattern doesn't have them
        if result['limit'] is None:
            result['limit'] = nested_result['limit']
        if result['offset'] is None:
            result['offset'] = nested_result['offset']
    
    return result


async def orchestrate_sparql_query(space_impl: PostgreSQLSpaceImpl, space_id: str, 
                                 sparql_query: str, term_cache: Optional[PostgreSQLTermCache] = None,
                                 graph_cache: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """
    Orchestrate SPARQL query execution by coordinating parsing, translation, and execution.
    
    Args:
        space_impl: PostgreSQL space implementation
        space_id: Space identifier
        sparql_query: SPARQL query string
        term_cache: Optional term cache for performance
        graph_cache: Optional graph cache for performance
        
    Returns:
        List of result dictionaries with variable bindings (SELECT)
        or List of RDF triple dictionaries (CONSTRUCT/DESCRIBE)
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Orchestrating SPARQL query for space '{space_id}'")
    
    try:
        # Parse SPARQL query using RDFLib
        from rdflib.plugins.sparql import prepareQuery
        from rdflib import Variable
        prepared_query = prepareQuery(sparql_query)
        query_algebra = prepared_query.algebra
        
        # Determine query type
        query_type = query_algebra.name
        logger.debug(f"Query type: {query_type}")
        
        # Get table configuration
        table_config = create_table_config(space_impl, space_id)
        
        # Create translation context
        context = TranslationContext(
            alias_generator=AliasGenerator(),
            term_cache=term_cache,
            space_impl=space_impl,
            table_config=table_config
        )
        # Add logger and graph_cache as attributes
        context.logger = logger
        context.graph_cache = graph_cache or {}
        
        # Translate query based on type - follow exact original implementation pattern
        if query_type == "SelectQuery":
            # Extract projection variables
            projection_vars = query_algebra.get('PV', [])
            
            # Check if we have a DISTINCT pattern and extract LIMIT/OFFSET
            pattern = query_algebra['p']
            has_distinct = _has_distinct_pattern(pattern)
            limit_info = _extract_limit_offset(pattern)
            
            # Extract and translate the main pattern - this returns (from_clause, where_conditions, joins, variable_mappings)
            from_clause, where_conditions, joins, variable_mappings = await translate_algebra_pattern(pattern, context, projection_vars)
            
            # Build SELECT clause, GROUP BY clause, and HAVING clause with variable mappings
            select_clause, group_by_clause, having_clause = _build_select_clause(projection_vars, variable_mappings, has_distinct)
            
            # Build complete SQL query - exact logic from original implementation
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
                logger.debug(f"Skipping {len(where_conditions)} WHERE conditions for UNION-derived table")
            
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
                
            sql_query = '\n'.join(sql_parts)
            
        elif query_type == "ConstructQuery":
            # Extract construct template
            construct_template = getattr(query_algebra, 'template', [])
            
            # Translate the WHERE clause pattern to get variable bindings
            pattern = query_algebra['p']
            from_clause, where_conditions, joins, variable_mappings = await translate_algebra_pattern(pattern, context)
            
            # Build CONSTRUCT query from components
            sql_query = build_construct_query_from_components(from_clause, where_conditions, joins, variable_mappings, construct_template)
        elif query_type == "AskQuery":
            sql_query = await _translate_ask_query(query_algebra, table_config, context)
        elif query_type == "DescribeQuery":
            sql_query = await _translate_describe_query(query_algebra, table_config, context)
        else:
            raise NotImplementedError(f"Unsupported query type: {query_type}")
        
        logger.debug(f"Generated SQL: {sql_query}")
        
        # Execute SQL query using the space_impl's connection method (like original implementation)
        sql_results = await _execute_sql_query_with_space_impl(space_impl, sql_query)
        
        # Process results based on query type
        if query_type == "SelectQuery":
            # Return results as-is for SELECT queries
            return sql_results
        elif query_type == "ConstructQuery":
            # Return RDF triples for CONSTRUCT queries
            return sql_results
        elif query_type == "AskQuery":
            # Return boolean result for ASK queries
            logger.debug(f"ASK query SQL results: {sql_results}")
            ask_result = len(sql_results) > 0
            logger.debug(f"ASK query boolean result: {ask_result}")
            return [{"ask": ask_result}]
        elif query_type == "DescribeQuery":
            # Return RDF triples for DESCRIBE queries
            return sql_results
        else:
            return sql_results
            
    except Exception as e:
        logger.error(f"Error orchestrating SPARQL query: {e}")
        raise


# Alias for backward compatibility with public interface
execute_sparql_query = orchestrate_sparql_query


async def execute_sparql_update(space_impl: PostgreSQLSpaceImpl, space_id: str, 
                               sparql_update: str, term_cache: Optional[PostgreSQLTermCache] = None,
                               graph_cache: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """
    Execute SPARQL UPDATE operations.
    
    Args:
        space_impl: PostgreSQL space implementation
        space_id: Space identifier
        sparql_update: SPARQL UPDATE string
        term_cache: Optional term cache for performance
        graph_cache: Optional graph cache for performance
        
    Returns:
        List of result dictionaries
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Executing SPARQL UPDATE for space '{space_id}'")
    
    # TODO: Implement SPARQL UPDATE support
    raise NotImplementedError("SPARQL UPDATE operations not yet implemented in refactored architecture")


async def execute_sql_query(space_impl: PostgreSQLSpaceImpl, sql_query: str) -> List[Dict[str, Any]]:
    """
    Execute raw SQL query.
    
    Args:
        space_impl: PostgreSQL space implementation
        sql_query: Raw SQL query string
        
    Returns:
        List of result dictionaries
    """
    return await _execute_sql_query_with_space_impl(space_impl, sql_query)


async def batch_lookup_term_uuids(space_impl: PostgreSQLSpaceImpl, terms: List[str], 
                                 term_cache: Optional[PostgreSQLTermCache] = None) -> Dict[str, str]:
    """
    Batch lookup term UUIDs.
    
    Args:
        space_impl: PostgreSQL space implementation
        terms: List of term strings to lookup
        term_cache: Optional term cache for performance
        
    Returns:
        Dictionary mapping term strings to UUIDs
    """
    # TODO: Implement batch term lookup
    raise NotImplementedError("Batch term lookup not yet implemented in refactored architecture")


def initialize_graph_cache() -> Dict:
    """
    Initialize graph cache for performance.
    
    Returns:
        Empty graph cache dictionary
    """
    return {}
