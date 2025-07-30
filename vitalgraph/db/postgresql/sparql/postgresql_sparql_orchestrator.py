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
from ..postgresql_cache_term import PostgreSQLCacheTerm
from ..postgresql_cache_datatype import PostgreSQLCacheDatatype

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
        all_vars = list(getattr(where_pattern, '_vars', set()))
        if not all_vars:
            # If no variables found in pattern, try to extract from sub-patterns
            all_vars = _extract_variables_from_pattern(where_pattern)
        
        # If still no variables, create a dummy variable for SQL generation
        if not all_vars:
            from rdflib import Variable
            all_vars = [Variable('dummy')]
        
        logger.debug(f"ASK pattern variables: {all_vars}")
        
        # Translate the pattern to SQL components using the new architecture
        # translate_algebra_pattern returns a tuple: (from_clause, where_conditions, joins, variable_mappings)
        from_clause, where_conditions, joins, variable_mappings = await translate_algebra_pattern(where_pattern, context, all_vars)
        
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
            # translate_algebra_pattern returns a tuple: (from_clause, where_conditions, joins, variable_mappings)
            from_clause, where_conditions, joins, variable_mappings = await translate_algebra_pattern(where_pattern, context, where_vars)
            
            # Build SELECT query for the WHERE clause to get resource URIs - exact original logic
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
            
            logger.info("Successfully translated DESCRIBE query with WHERE clause")
            return main_sql
                
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
                
                logger.info("Successfully translated DESCRIBE query without WHERE clause")
                return main_sql
        
        logger.error("No valid DESCRIBE query structure found")
        return "SELECT '' AS subject, '' AS predicate, '' AS object WHERE FALSE"
        
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


def _substitute_template_term(template_term, variable_bindings: Dict[str, Any]) -> str:
    """Substitute a template term with values from variable bindings.
    
    Args:
        template_term: RDFLib term from CONSTRUCT template (Variable, URIRef, Literal)
        variable_bindings: Dictionary of variable -> value mappings from SQL
        
    Returns:
        String value for the term, or None if substitution fails
    """
    try:
        from rdflib import Variable, URIRef, Literal, BNode
        
        logger = logging.getLogger(__name__)
        
        if isinstance(template_term, Variable):
            # Variable - substitute with value from bindings
            var_name = str(template_term)  # Variable name (e.g., '?entity')
            
            # Try to find the variable in bindings (case-sensitive first)
            if var_name in variable_bindings:
                return str(variable_bindings[var_name])
            else:
                # Try without '?' prefix if present
                clean_var_name = var_name.lstrip('?')
                if clean_var_name in variable_bindings:
                    return str(variable_bindings[clean_var_name])
                else:
                    # PostgreSQL returns lowercase column names, so try case-insensitive lookup
                    # Create a case-insensitive mapping
                    lower_bindings = {k.lower(): v for k, v in variable_bindings.items()}
                    
                    # Try lowercase version of variable name
                    if clean_var_name.lower() in lower_bindings:
                        return str(lower_bindings[clean_var_name.lower()])
                    else:
                        logger.debug(f"Variable {var_name} not found in bindings: {list(variable_bindings.keys())}")
                        return None
                    
        elif isinstance(template_term, (URIRef, Literal)):
            # Constant term - return as-is
            return str(template_term)
            
        elif isinstance(template_term, BNode):
            # Blank node - return as string
            return str(template_term)
            
        else:
            # Unknown term type - convert to string
            logger.warning(f"Unknown template term type: {type(template_term)}")
            return str(template_term)
            
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error substituting template term {template_term}: {e}")
        return None


async def _convert_sql_results_to_rdf_triples(sql_results: List[Dict[str, Any]], 
                                            construct_template: List, 
                                            variable_mappings: Dict, 
                                            term_cache: Optional[PostgreSQLCacheTerm] = None) -> List[Dict[str, Any]]:
    """
    Convert SQL query results to RDF triples for CONSTRUCT queries.
    Based on the original _process_construct_results function.
    
    Args:
        sql_results: Raw SQL query results from database
        construct_template: CONSTRUCT template triples
        variable_mappings: Variable to SQL column mappings
        term_cache: Optional term cache for performance
        
    Returns:
        List of RDF triple dictionaries
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Converting {len(sql_results)} SQL results to RDF triples")
    logger.debug(f"Construct template has {len(construct_template)} triples")
    
    if sql_results and len(sql_results) > 0:
        logger.debug(f"First SQL result keys: {list(sql_results[0].keys())}")
        logger.debug(f"First SQL result sample: {dict(list(sql_results[0].items())[:3])}")
    
    rdf_triples = []
    triple_count = 0
    
    # For each SQL result row (variable binding)
    for row in sql_results:
        # For each triple template in the CONSTRUCT clause
        for template_triple in construct_template:
            subject_term, predicate_term, object_term = template_triple
            
            # Substitute variables with values from SQL result
            subject_value = _substitute_template_term(subject_term, row)
            predicate_value = _substitute_template_term(predicate_term, row)
            object_value = _substitute_template_term(object_term, row)
            
            # Only create triple if all terms are successfully substituted
            if (subject_value is not None and 
                predicate_value is not None and 
                object_value is not None):
                
                # Create RDF triple dictionary
                triple_dict = {
                    'subject': subject_value,
                    'predicate': predicate_value,
                    'object': object_value
                }
                
                rdf_triples.append(triple_dict)
                triple_count += 1
            else:
                logger.debug(f"Skipping incomplete triple: {subject_value} {predicate_value} {object_value}")
    
    logger.debug(f"Generated {triple_count} RDF triples from {len(sql_results)} SQL results")
    return rdf_triples


def create_table_config(space_impl: PostgreSQLSpaceImpl, space_id: str) -> TableConfig:
    """
    Create table configuration for the specified space.
    
    Args:
        space_impl: PostgreSQL space implementation
        space_id: Space identifier
        
    Returns:
        TableConfig with table names for the space
    """
    return TableConfig.from_space_impl(space_impl, space_id, use_unlogged=space_impl.use_unlogged)


def _has_distinct_pattern(pattern) -> bool:
    """Check if pattern contains DISTINCT modifier. Exact port from original."""
    if hasattr(pattern, 'name') and pattern.name == "Distinct":
        return True
    if hasattr(pattern, 'p'):
        return _has_distinct_pattern(pattern.p)
    return False


def _restore_variable_case(sql_results: List[Dict[str, Any]], case_mapping: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    Restore original SPARQL variable case in SQL result dictionaries.
    PostgreSQL returns lowercase column names even when quoted, so we need to map them back.
    
    Args:
        sql_results: List of result dictionaries with lowercase keys
        case_mapping: Maps lowercase column names to original SPARQL variable names
        
    Returns:
        List of result dictionaries with original case variable names
    """
    if not case_mapping:
        return sql_results
        
    restored_results = []
    for result in sql_results:
        restored_result = {}
        for key, value in result.items():
            # Use case mapping to restore original variable name, or keep original key
            original_key = case_mapping.get(key.lower(), key)
            restored_result[original_key] = value
        restored_results.append(restored_result)
    
    return restored_results


def _build_select_clause(projection_vars: List, variable_mappings: Dict, has_distinct: bool = False) -> Tuple[str, str, str, Dict]:
    """Build SELECT clause, GROUP BY clause, and HAVING clause. Exact port from original."""
    case_mapping = {}  # Maps unique SQL aliases to original SPARQL variable names
    alias_counter = {}  # Tracks collision counters for case-insensitive names
    
    if not projection_vars:
        # No projection variables - return all mapped variables
        select_items = []
        for var, mapping in variable_mappings.items():
            if not str(var).startswith('__'):  # Skip internal variables
                var_name = str(var).replace('?', '')
                lowercase_name = var_name.lower()
                
                # Handle case collisions for non-projection variables too
                if lowercase_name in alias_counter:
                    alias_counter[lowercase_name] += 1
                    unique_alias = f"{lowercase_name}_{alias_counter[lowercase_name]}"
                else:
                    alias_counter[lowercase_name] = 0
                    unique_alias = lowercase_name
                
                case_mapping[unique_alias] = var_name
                select_items.append(f'{mapping} AS "{unique_alias}"')
        
        if not select_items:
            select_items = ["*"]
    else:
        # Build SELECT items from projection variables
        select_items = []
        for var in projection_vars:
            var_name = str(var).replace('?', '')
            lowercase_name = var_name.lower()
            
            # Handle case-sensitive variable collisions by generating unique aliases
            if lowercase_name in alias_counter:
                # Collision detected - generate unique alias
                alias_counter[lowercase_name] += 1
                unique_alias = f"{lowercase_name}_{alias_counter[lowercase_name]}"
            else:
                # First occurrence - use lowercase as alias
                alias_counter[lowercase_name] = 0
                unique_alias = lowercase_name
            
            # Store the mapping from unique alias to original variable name
            case_mapping[unique_alias] = var_name
            
            if var in variable_mappings:
                var_mapping = variable_mappings[var]
                select_items.append(f'{var_mapping} AS "{unique_alias}"')
            else:
                # Variable not found in mappings - use UNMAPPED placeholder
                select_items.append(f"'UNMAPPED_VAR_{var_name}' AS \"{unique_alias}\"")
    
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
    
    return select_clause, group_by_clause, having_clause, case_mapping


def build_construct_query_from_components(from_clause: str, where_conditions: List[str], 
                                        joins: List[str], variable_mappings: Dict, 
                                        construct_template: List) -> str:
    """Build CONSTRUCT query from SQL components. Exact port from original."""
    logger = logging.getLogger(__name__)
    logger.debug(f"Building CONSTRUCT query from components")
    logger.debug(f"Variable mappings: {variable_mappings}")
    logger.debug(f"Construct template: {construct_template}")
    
    # For CONSTRUCT, we need to return all variable bindings that will be used
    # to instantiate the construct template
    construct_vars = set()
    for triple in construct_template:
        for term in triple:
            # Check if term is a Variable using isinstance
            from rdflib import Variable
            if isinstance(term, Variable):
                construct_vars.add(term)
                logger.debug(f"Found construct variable: {term}")
            # Also check the old way as fallback
            elif hasattr(term, 'n3') and str(term).startswith('?'):
                construct_vars.add(term)
                logger.debug(f"Found construct variable (fallback): {term}")
    
    # Build SELECT clause for construct variables
    select_items = []
    logger.debug(f"Construct vars to process: {construct_vars}")
    for var in construct_vars:
        var_name = str(var).replace('?', '')
        if var in variable_mappings:
            var_mapping = variable_mappings[var]
            select_item = f"{var_mapping} AS {var_name}"
            select_items.append(select_item)
            logger.debug(f"Mapped variable {var} -> {var_mapping} AS {var_name}")
        else:
            select_item = f"'UNMAPPED_{var_name}' AS {var_name}"
            select_items.append(select_item)
            logger.debug(f"UNMAPPED variable {var} -> {select_item}")
    
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
                                 sparql_query: str, term_cache: Optional[PostgreSQLCacheTerm] = None,
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
        
        # Use datatype cache from space implementation
        datatype_cache = space_impl.get_datatype_cache(space_id)
        
        # Create translation context
        context = TranslationContext(
            alias_generator=AliasGenerator(),
            term_cache=term_cache,
            space_impl=space_impl,
            table_config=table_config,
            datatype_cache=datatype_cache,
            space_id=space_id
        )
        # Add logger and graph_cache as attributes
        context.logger = logger
        context.graph_cache = graph_cache or {}
        
        # Initialize case_mapping for all query types
        case_mapping = {}
        
        # Translate query based on type - follow exact original implementation pattern
        if query_type == "SelectQuery":
            # Extract projection variables
            projection_vars = getattr(query_algebra, 'PV', [])
            
            # Check if we have a DISTINCT pattern and extract LIMIT/OFFSET
            pattern = query_algebra.p
            has_distinct = _has_distinct_pattern(pattern)
            limit_info = _extract_limit_offset(pattern)
            
            # Extract and translate the main pattern - this returns (from_clause, where_conditions, joins, variable_mappings)
            from_clause, where_conditions, joins, variable_mappings = await translate_algebra_pattern(pattern, context, projection_vars)
            
            # Build SELECT clause, GROUP BY clause, and HAVING clause with variable mappings
            select_clause, group_by_clause, having_clause, case_mapping = _build_select_clause(projection_vars, variable_mappings, has_distinct)
            
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
            
            # CRITICAL FIX: Extract variables from CONSTRUCT template to ensure proper mappings
            # This ensures that variables used in the CONSTRUCT template are included in projected_vars
            construct_vars = set()
            for triple in construct_template:
                for term in triple:
                    from rdflib import Variable
                    if isinstance(term, Variable):
                        construct_vars.add(term)
                        logger.debug(f"Found CONSTRUCT template variable: {term}")
            
            # Convert to list for projected_vars parameter
            projected_vars = list(construct_vars) if construct_vars else None
            logger.debug(f"CONSTRUCT projected_vars: {projected_vars}")
            
            # Translate the WHERE clause pattern to get variable bindings
            pattern = query_algebra.p
            from_clause, where_conditions, joins, variable_mappings = await translate_algebra_pattern(pattern, context, projected_vars)
            
            # Build case mapping for CONSTRUCT variables with unique alias handling
            alias_counter = {}
            for var in construct_vars:
                var_name = str(var).replace('?', '')
                lowercase_name = var_name.lower()
                
                # Handle case-sensitive variable collisions
                if lowercase_name in alias_counter:
                    alias_counter[lowercase_name] += 1
                    unique_alias = f"{lowercase_name}_{alias_counter[lowercase_name]}"
                else:
                    alias_counter[lowercase_name] = 0
                    unique_alias = lowercase_name
                
                case_mapping[unique_alias] = var_name
            
            # Build CONSTRUCT query from components
            sql_query = build_construct_query_from_components(from_clause, where_conditions, joins, variable_mappings, construct_template)
        elif query_type == "AskQuery":
            sql_query = await _translate_ask_query(query_algebra, table_config, context)
        elif query_type == "DescribeQuery":
            sql_query = await _translate_describe_query(query_algebra, table_config, context)
        else:
            raise NotImplementedError(f"Unsupported query type: {query_type}")
        
        # Log the generated SQL query with formatting for readability
        logger.info(f"🔍 Generated SQL Query:")
        logger.info(f"{'='*60}")
        logger.info(sql_query)
        logger.info(f"{'='*60}")
        
        # Execute SQL query using the space_impl's connection method (like original implementation)
        logger.info(f"⚡ Executing SQL query...")
        sql_results = await _execute_sql_query_with_space_impl(space_impl, sql_query)
        
        # Restore original variable case in results
        sql_results = _restore_variable_case(sql_results, case_mapping)
        
        logger.info(f"✅ SQL execution completed. Result count: {len(sql_results) if sql_results else 0}")
        
        # Process results based on query type
        if query_type == "SelectQuery":
            # Return results as-is for SELECT queries
            return sql_results
        elif query_type == "ConstructQuery":
            # Convert SQL results to RDF triples for CONSTRUCT queries
            construct_template = getattr(query_algebra, 'template', [])
            rdf_triples = await _convert_sql_results_to_rdf_triples(sql_results, construct_template, variable_mappings, term_cache)
            return rdf_triples
        elif query_type == "AskQuery":
            # Return boolean result for ASK queries
            logger.debug(f"ASK query SQL results: {sql_results}")
            ask_result = len(sql_results) > 0
            logger.debug(f"ASK query boolean result: {ask_result}")
            return [{"ask": ask_result}]
        elif query_type == "DescribeQuery":
            # DESCRIBE queries already return RDF triples in the correct format (subject, predicate, object)
            # No need for complex conversion - just return the SQL results as-is
            logger.debug(f"DESCRIBE query returned {len(sql_results)} triples")
            return sql_results
        else:
            return sql_results
            
    except Exception as e:
        logger.error(f"Error orchestrating SPARQL query: {e}")
        raise


# Alias for backward compatibility with public interface
execute_sparql_query = orchestrate_sparql_query


async def execute_sparql_update(space_impl: PostgreSQLSpaceImpl, space_id: str, 
                               sparql_update: str, term_cache: Optional[PostgreSQLCacheTerm] = None,
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
                                 term_cache: Optional[PostgreSQLCacheTerm] = None) -> Dict[str, str]:
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
