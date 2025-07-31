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
import psycopg

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
    translate_algebra_pattern, translate_algebra_pattern_to_components
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
        # Use async context manager with dict pool for SPARQL result compatibility
        async with space_impl.core.get_dict_connection() as conn:
            # Connection already configured with dict_row factory
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
                # Connection automatically returned to pool when context exits
            
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
    Create table configuration from PostgreSQL space implementation.
    
    Args:
        space_impl: PostgreSQL space implementation
        space_id: Space identifier
        
    Returns:
        TableConfig instance for SQL generation
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
    
    # CONSTRUCT queries with CROSS JOINs need DISTINCT to eliminate duplicates
    # Check if this query uses CROSS JOINs that require deduplication
    needs_distinct = any('CROSS JOIN' in join for join in joins) if joins else False
    distinct_keyword = "DISTINCT " if needs_distinct else ""
    
    # Build complete query
    query_parts = [f"SELECT {distinct_keyword}{', '.join(select_items)}"]
    
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
                                 sparql_query: str, graph_cache: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """
    Orchestrate SPARQL query execution by coordinating parsing, translation, and execution.
    
    Args:
        space_impl: PostgreSQL space implementation
        space_id: Space identifier
        sparql_query: SPARQL query string
        graph_cache: Optional graph cache for performance
        
    Returns:
        List of result dictionaries with variable bindings (SELECT)
        or List of RDF triple dictionaries (CONSTRUCT/DESCRIBE)
    """
    logger = logging.getLogger(__name__)
    # print(f"🚀 ORCHESTRATOR PRINT: Called for space '{space_id}'")
    # print(f"📝 ORCHESTRATOR PRINT: Query preview: {sparql_query[:100]}...")
    logger.info(f"🚀 ORCHESTRATOR CALLED: Orchestrating SPARQL query for space '{space_id}'")
    logger.info(f"📝 Query preview: {sparql_query[:100]}...")
    
    try:
        # print(f"🔍 ORCHESTRATOR PRINT: Starting to parse SPARQL query...")
        # Parse SPARQL query using RDFLib
        from rdflib.plugins.sparql import prepareQuery
        from rdflib import Variable
        prepared_query = prepareQuery(sparql_query)
        query_algebra = prepared_query.algebra
        # print(f"🔍 ORCHESTRATOR PRINT: Successfully parsed SPARQL query")
        
        # Determine query type
        query_type = query_algebra.name
        # print(f"🎯 ORCHESTRATOR PRINT: Query type detected: {query_type}")
        logger.info(f"🎯 Query type detected: {query_type}")
        
        # Get table configuration
        table_config = create_table_config(space_impl, space_id)
        
        # Get term cache from space implementation
        term_cache = space_impl.get_term_cache()
        
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
            has_explicit_distinct = _has_distinct_pattern(pattern)
            limit_info = _extract_limit_offset(pattern)
            
            # Translate the main pattern to get SQLComponents with ORDER BY support
            sql_components = await translate_algebra_pattern_to_components(pattern, context, projection_vars)
            
            # Build case mapping for SELECT variables
            case_mapping = {}
            for var in projection_vars:
                var_name = str(var).replace('?', '')
                case_mapping[var_name.lower()] = var_name
            
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
            
            # DEBUG: Log the query algebra structure
            logger.info(f"🔍 CONSTRUCT query algebra structure: {query_algebra}")
            logger.info(f"🔍 Query algebra attributes: {dir(query_algebra)}")
            
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
            
            # Extract LIMIT/OFFSET for CONSTRUCT queries - try multiple approaches
            pattern = query_algebra.p
            limit_info = _extract_limit_offset(pattern)
            logger.info(f"🔍 CONSTRUCT LIMIT/OFFSET from pattern: {limit_info}")
            
            # Also try extracting from the top-level query algebra
            top_level_limit = _extract_limit_offset(query_algebra)
            logger.info(f"🔍 CONSTRUCT LIMIT/OFFSET from top-level: {top_level_limit}")
            
            # Translate the WHERE clause pattern to get variable bindings
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
            # Note: Don't apply LIMIT/OFFSET to SQL query for CONSTRUCT queries
            # because we need to apply it to the final RDF triples instead
            sql_query = build_construct_query_from_components(from_clause, where_conditions, joins, variable_mappings, construct_template)
        elif query_type == "AskQuery":
            # Extract LIMIT/OFFSET for ASK queries
            pattern = query_algebra.p
            limit_info = _extract_limit_offset(pattern)
            logger.debug(f"ASK LIMIT/OFFSET info: {limit_info}")
            
            base_sql_query = await _translate_ask_query(query_algebra, table_config, context)
            
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
            logger.debug(f"DESCRIBE LIMIT/OFFSET info: {limit_info}")
            
            base_sql_query = await _translate_describe_query(query_algebra, table_config, context)
            
            # Apply LIMIT/OFFSET to DESCRIBE queries
            sql_parts = [base_sql_query]
            if limit_info['offset'] is not None:
                sql_parts.append(f"OFFSET {limit_info['offset']}")
            if limit_info['limit'] is not None:
                sql_parts.append(f"LIMIT {limit_info['limit']}")
            
            sql_query = '\n'.join(sql_parts)
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
            
            # Check if we need to apply SQL-level optimization for CONSTRUCT pagination
            # This is more efficient than retrieving all rows and filtering RDF triples
            limit_info = None
            if hasattr(query_algebra, 'p'):
                limit_info = _extract_limit_offset(query_algebra.p)
            if (not limit_info or (limit_info['limit'] is None and limit_info['offset'] is None)):
                limit_info = _extract_limit_offset(query_algebra)
            
            # If we have LIMIT/OFFSET and didn't apply it at SQL level, we might need to re-execute
            # with optimized SQL limits for better performance
            if limit_info and (limit_info['offset'] is not None or limit_info['limit'] is not None):
                # Estimate triples per SQL row based on CONSTRUCT template
                estimated_triples_per_row = len(construct_template) if construct_template else 1
                
                # Calculate optimized SQL limits
                sql_offset = None
                sql_limit = None
                
                if limit_info['offset'] is not None and estimated_triples_per_row > 0:
                    # Estimate SQL offset (conservative - start a bit earlier)
                    sql_offset = max(0, (limit_info['offset'] // estimated_triples_per_row) - 1)
                
                if limit_info['limit'] is not None and estimated_triples_per_row > 0:
                    # Estimate SQL limit with buffer (get extra rows to ensure we have enough triples)
                    buffer_multiplier = 1.5  # 50% buffer
                    estimated_sql_limit = int((limit_info['limit'] / estimated_triples_per_row) * buffer_multiplier) + 10
                    sql_limit = max(estimated_sql_limit, limit_info['limit'])  # At least as many as requested
                
                # print(f"🚀 ORCHESTRATOR PRINT: CONSTRUCT optimization - estimated {estimated_triples_per_row} triples/row")
                # print(f"🚀 ORCHESTRATOR PRINT: RDF LIMIT/OFFSET: {limit_info['limit']}/{limit_info['offset']}")
                # print(f"🚀 ORCHESTRATOR PRINT: Optimized SQL LIMIT/OFFSET: {sql_limit}/{sql_offset}")
                
                # Apply SQL-level optimization if we have limits and it's likely to be more efficient
                # Only optimize if we're requesting a reasonable subset of data
                original_row_count = len(sql_results)
                should_optimize = (
                    sql_limit is not None and 
                    sql_limit < original_row_count and 
                    sql_limit < 1000  # Only optimize for reasonably small result sets
                )
                
                if should_optimize:
                    # print(f"🚀 ORCHESTRATOR PRINT: Re-executing SQL with optimized limits for better performance")
                    
                    # Add LIMIT/OFFSET to the SQL query
                    optimized_sql = sql_query
                    if sql_limit is not None:
                        optimized_sql += f" LIMIT {sql_limit}"
                    if sql_offset is not None:
                        optimized_sql += f" OFFSET {sql_offset}"
                    
                    # Re-execute with optimized query
                    optimized_sql_results = await _execute_sql_query_with_space_impl(space_impl, optimized_sql)
                    # print(f"🚀 ORCHESTRATOR PRINT: Optimized SQL returned {len(optimized_sql_results)} rows (vs {original_row_count} original)")
                    sql_results = optimized_sql_results
            
            rdf_triples = await _convert_sql_results_to_rdf_triples(sql_results, construct_template, variable_mappings, term_cache)
            
            # With SQL-level optimization, we should already have approximately the right number of triples
            # No need for additional RDF-level LIMIT/OFFSET filtering
            original_count = len(rdf_triples)
            # print(f"📊 ORCHESTRATOR PRINT: Final RDF triples count: {original_count}")
            
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
                               sparql_update: str, graph_cache: Optional[Dict] = None) -> bool:
    """
    Execute SPARQL UPDATE operations.
    
    Args:
        space_impl: PostgreSQL space implementation
        space_id: Space identifier
        sparql_update: SPARQL UPDATE string
        graph_cache: Optional graph cache for performance
        
    Returns:
        bool: True if update was successful
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Executing SPARQL UPDATE for space '{space_id}'")
    logger.debug(f"UPDATE query: {sparql_update}")
    
    try:
        # Get term cache from space implementation
        term_cache = space_impl.get_term_cache()
        
        # Detect update operation type
        update_type = _detect_update_type(sparql_update)
        logger.debug(f"Detected update type: {update_type}")
        
        # Route to appropriate handler
        if update_type == "INSERT_DATA":
            return await _execute_insert_data(space_impl, space_id, sparql_update, term_cache, graph_cache)
        elif update_type == "DELETE_DATA":
            return await _execute_delete_data(space_impl, space_id, sparql_update, term_cache, graph_cache)
        elif update_type == "INSERT_DELETE_PATTERN":
            return await _execute_insert_delete_pattern(space_impl, space_id, sparql_update, term_cache, graph_cache)
        elif sparql_update.strip().upper().startswith('CREATE'):
            return await _execute_create_graph(space_impl, space_id, sparql_update, term_cache, graph_cache)
        elif sparql_update.strip().upper().startswith('DROP'):
            return await _execute_drop_graph(space_impl, space_id, sparql_update, term_cache, graph_cache)
        elif sparql_update.strip().upper().startswith('CLEAR'):
            return await _execute_clear_graph(space_impl, space_id, sparql_update, term_cache, graph_cache)
        elif sparql_update.strip().upper().startswith('COPY'):
            return await _execute_copy_graph(space_impl, space_id, sparql_update, term_cache, graph_cache)
        elif sparql_update.strip().upper().startswith('MOVE'):
            return await _execute_move_graph(space_impl, space_id, sparql_update, term_cache, graph_cache)
        elif sparql_update.strip().upper().startswith('ADD'):
            return await _execute_add_graph(space_impl, space_id, sparql_update, term_cache, graph_cache)
        elif sparql_update.strip().upper().startswith('LOAD'):
            return await _execute_load_operation(space_impl, space_id, sparql_update, term_cache, graph_cache)
        else:
            raise ValueError(f"Unsupported UPDATE operation type: {update_type}")
            
    except Exception as e:
        logger.error(f"Error executing SPARQL UPDATE: {e}")
        raise


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





def initialize_graph_cache() -> Dict:
    """
    Initialize graph cache for performance.
    
    Returns:
        Empty graph cache dictionary
    """
    return {}


# SPARQL UPDATE Helper Functions
# ==============================

def _detect_update_type(sparql_update: str) -> str:
    """
    Detect the type of SPARQL UPDATE operation.
    
    Args:
        sparql_update: SPARQL UPDATE query string
        
    Returns:
        str: Update operation type
    """
    import re
    
    # Normalize query for pattern matching
    normalized = re.sub(r'\s+', ' ', sparql_update.strip().upper())
    
    # Check for different update patterns
    if 'INSERT DATA' in normalized:
        return "INSERT_DATA"
    elif 'DELETE DATA' in normalized:
        return "DELETE_DATA"
    elif 'CREATE GRAPH' in normalized or 'CREATE SILENT GRAPH' in normalized:
        return "CREATE_GRAPH"
    elif 'DROP GRAPH' in normalized or 'DROP SILENT GRAPH' in normalized:
        return "DROP_GRAPH"
    elif 'CLEAR GRAPH' in normalized or 'CLEAR SILENT GRAPH' in normalized:
        return "CLEAR_GRAPH"
    elif 'COPY' in normalized and 'TO' in normalized:
        return "COPY_GRAPH"
    elif 'MOVE' in normalized and 'TO' in normalized:
        return "MOVE_GRAPH"
    elif 'ADD' in normalized and 'TO' in normalized:
        return "ADD_GRAPH"
    elif ('INSERT' in normalized and 'WHERE' in normalized) or ('DELETE' in normalized and 'WHERE' in normalized):
        return "INSERT_DELETE_PATTERN"
    else:
        return "UNKNOWN"


async def _execute_insert_data(space_impl: PostgreSQLSpaceImpl, space_id: str, sparql_update: str, 
                              term_cache: Optional[PostgreSQLCacheTerm] = None,
                              graph_cache: Optional[Dict] = None) -> bool:
    """
    Execute INSERT DATA operation with ground triples.
    
    Args:
        space_impl: PostgreSQL space implementation
        space_id: Space identifier
        sparql_update: INSERT DATA SPARQL query
        term_cache: Optional term cache for performance
        graph_cache: Optional graph cache for performance
        
    Returns:
        bool: True if successful
    """
    logger = logging.getLogger(__name__)
    logger.debug("Executing INSERT DATA operation")
    
    try:
        # Parse INSERT DATA query to extract triples
        triples, graph_uri = _parse_insert_data_query(sparql_update)
        logger.debug(f"Parsed {len(triples)} triples for insertion")
        
        if not triples:
            logger.warning("No triples found in INSERT DATA operation")
            return True
        
        # Convert triples to quads and collect unique graph URIs
        from rdflib import URIRef
        quads = []
        unique_graphs = set()
        
        for subject, predicate, obj in triples:
            # Use provided graph URI or default global graph
            if graph_uri:
                graph = URIRef(graph_uri)
            else:
                # Use global graph if no graph specified
                from .postgresql_sparql_core import GraphConstants
                graph = URIRef(GraphConstants.GLOBAL_GRAPH_URI)
            
            quads.append((subject, predicate, obj, graph))
            unique_graphs.add(str(graph))
        
        # Use the PostgreSQL space implementation method for batch insertion
        await space_impl.add_rdf_quads_batch(space_id, quads)
        
        logger.info(f"Successfully inserted {len(quads)} quads")
        return True
        
    except Exception as e:
        logger.error(f"Error in INSERT DATA operation: {e}")
        raise


async def _execute_delete_data(space_impl: PostgreSQLSpaceImpl, space_id: str, sparql_update: str,
                              term_cache: Optional[PostgreSQLCacheTerm] = None,
                              graph_cache: Optional[Dict] = None) -> bool:
    """
    Execute DELETE DATA operation with ground triples.
    
    Args:
        space_impl: PostgreSQL space implementation
        space_id: Space identifier
        sparql_update: DELETE DATA SPARQL query
        term_cache: Optional term cache for performance
        graph_cache: Optional graph cache for performance
        
    Returns:
        bool: True if successful
    """
    logger = logging.getLogger(__name__)
    logger.debug("Executing DELETE DATA operation")
    
    try:
        # Parse DELETE DATA query to extract triples
        triples, graph_uri = _parse_delete_data_query(sparql_update)
        logger.debug(f"Parsed {len(triples)} triples for deletion")
        
        if not triples:
            logger.warning("No triples found in DELETE DATA operation")
            return True
        
        # Convert triples to quads for deletion
        from rdflib import URIRef
        quads = []
        
        for subject, predicate, obj in triples:
            # Use provided graph URI or default global graph
            if graph_uri:
                graph = URIRef(graph_uri)
            else:
                # Use global graph if no graph specified
                from .postgresql_sparql_core import GraphConstants
                graph = URIRef(GraphConstants.GLOBAL_GRAPH_URI)
            
            quads.append((subject, predicate, obj, graph))
        
        # Use the existing working space implementation method
        await space_impl.remove_rdf_quads_batch(space_id, quads)
        
        logger.info(f"Successfully deleted {len(quads)} quads")
        return True
        
    except Exception as e:
        logger.error(f"Error in DELETE DATA operation: {e}")
        raise


# SPARQL UPDATE operations using existing translation functions

async def _execute_insert_delete_pattern(space_impl: PostgreSQLSpaceImpl, space_id: str, sparql_update: str,
                                        term_cache: Optional[PostgreSQLCacheTerm] = None,
                                        graph_cache: Optional[Dict] = None) -> bool:
    """Execute INSERT/DELETE operations with WHERE patterns."""
    logger = logging.getLogger(__name__)
    logger.debug("Executing INSERT/DELETE with WHERE patterns")
    
    try:
        # Create table configuration
        table_config = TableConfig.from_space_impl(space_impl, space_id)
        
        # Parse the MODIFY operation (this would need proper parsing implementation)
        # For now, use placeholder parsing
        delete_template, insert_template, where_sql = _parse_modify_operation(sparql_update, table_config)
        
        # Use the existing translation function
        sql_statements = translate_modify_operation(delete_template, insert_template, where_sql, table_config)
        
        # Execute the SQL statements
        async with space_impl.core.get_dict_connection() as conn:
            # Connection already configured with dict_row factory
            async with conn.cursor() as cursor:
                for sql in sql_statements:
                    logger.debug(f"Executing SQL: {sql}")
                    await cursor.execute(sql)
        
        logger.info("Successfully executed INSERT/DELETE with WHERE patterns")
        return True
        
    except Exception as e:
        logger.error(f"Error in INSERT/DELETE with WHERE patterns: {e}")
        raise


async def _execute_create_graph(space_impl: PostgreSQLSpaceImpl, space_id: str, sparql_update: str,
                               term_cache: Optional[PostgreSQLCacheTerm] = None,
                               graph_cache: Optional[Dict] = None) -> bool:
    """Execute CREATE GRAPH operation."""
    logger = logging.getLogger(__name__)
    logger.debug("Executing CREATE GRAPH operation")
    
    try:
        # Parse graph URI from CREATE GRAPH statement
        graph_uri = _parse_graph_uri_from_create(sparql_update)
        
        if not graph_uri:
            raise ValueError("No graph URI found in CREATE GRAPH query")
        
        logger.info(f"Creating graph: {graph_uri}")
        
        # Use the new graph management class
        success = await space_impl.graphs.create_graph(space_id, graph_uri)
        
        if success:
            # Add to graph cache
            graph_cache_instance = space_impl.get_graph_cache(space_id)
            graph_cache_instance.add_graph_to_cache(graph_uri)
            logger.info(f"Successfully created graph: {graph_uri}")
        else:
            logger.warning(f"Graph creation may have failed: {graph_uri}")
            
        return success
        
    except Exception as e:
        logger.error(f"Error in CREATE GRAPH operation: {e}")
        raise


async def _execute_drop_graph(space_impl: PostgreSQLSpaceImpl, space_id: str, sparql_update: str,
                             term_cache: Optional[PostgreSQLCacheTerm] = None,
                             graph_cache: Optional[Dict] = None) -> bool:
    """Execute DROP GRAPH operation."""
    logger = logging.getLogger(__name__)
    logger.debug("Executing DROP GRAPH operation")
    
    try:
        # Parse graph URI from DROP GRAPH statement
        graph_uri = _parse_graph_uri_from_drop(sparql_update)
        
        if not graph_uri:
            raise ValueError("No graph URI found in DROP GRAPH query")
        
        logger.info(f"Dropping graph: {graph_uri}")
        
        # Use the new graph management class
        success = await space_impl.graphs.drop_graph(space_id, graph_uri)
        
        if success:
            # Remove from graph cache
            graph_cache_instance = space_impl.get_graph_cache(space_id)
            graph_cache_instance.remove_graph_from_cache(graph_uri)
            logger.info(f"Successfully dropped graph: {graph_uri}")
        else:
            logger.warning(f"Graph dropping may have failed: {graph_uri}")
        
        return success
        
    except Exception as e:
        logger.error(f"Error in DROP GRAPH operation: {e}")
        raise


async def _execute_clear_graph(space_impl: PostgreSQLSpaceImpl, space_id: str, sparql_update: str,
                              term_cache: Optional[PostgreSQLCacheTerm] = None,
                              graph_cache: Optional[Dict] = None) -> bool:
    """Execute CLEAR GRAPH operation."""
    logger = logging.getLogger(__name__)
    logger.debug("Executing CLEAR GRAPH operation")
    
    try:
        # Parse graph URI from CLEAR GRAPH statement
        graph_uri = _parse_graph_uri_from_clear(sparql_update)
        
        if not graph_uri:
            raise ValueError("No graph URI found in CLEAR GRAPH query")
        
        logger.info(f"Clearing graph: {graph_uri}")
        
        # Use the new graph management class
        success = await space_impl.graphs.clear_graph(space_id, graph_uri)
        
        if success:
            logger.info(f"Successfully cleared graph: {graph_uri}")
        else:
            logger.warning(f"Graph clearing may have failed: {graph_uri}")
        
        return success
        
    except Exception as e:
        logger.error(f"Error in CLEAR GRAPH operation: {e}")
        raise


async def _execute_copy_graph(space_impl: PostgreSQLSpaceImpl, space_id: str, sparql_update: str,
                             term_cache: Optional[PostgreSQLCacheTerm] = None,
                             graph_cache: Optional[Dict] = None) -> bool:
    """Execute COPY GRAPH operation."""
    logger = logging.getLogger(__name__)
    logger.debug("Executing COPY GRAPH operation")
    
    try:
        # Parse source and target graph URIs from COPY statement
        source_graph, target_graph = _parse_copy_graphs(sparql_update)
        
        # Create table configuration
        table_config = TableConfig.from_space_impl(space_impl, space_id)
        
        # Use the existing translation function
        sql_statements = translate_copy_operation(source_graph, target_graph, table_config)
        
        # Execute the SQL statements
        async with space_impl.core.get_dict_connection() as conn:
            # Connection already configured with dict_row factory
            async with conn.cursor() as cursor:
                for sql in sql_statements:
                    logger.debug(f"Executing SQL: {sql}")
                    await cursor.execute(sql)
        
        logger.info(f"Successfully copied from {source_graph} to {target_graph}")
        return True
        
    except Exception as e:
        logger.error(f"Error in COPY GRAPH operation: {e}")
        raise


async def _execute_move_graph(space_impl: PostgreSQLSpaceImpl, space_id: str, sparql_update: str,
                             term_cache: Optional[PostgreSQLCacheTerm] = None,
                             graph_cache: Optional[Dict] = None) -> bool:
    """Execute MOVE GRAPH operation."""
    logger = logging.getLogger(__name__)
    logger.debug("Executing MOVE GRAPH operation")
    
    try:
        # Parse source and target graph URIs from MOVE statement
        source_graph, target_graph = _parse_move_graphs(sparql_update)
        
        # Create table configuration
        table_config = TableConfig.from_space_impl(space_impl, space_id)
        
        # Use the existing translation function
        sql_statements = translate_move_operation(source_graph, target_graph, table_config)
        
        # Execute the SQL statements
        async with space_impl.core.get_dict_connection() as conn:
            # Connection already configured with dict_row factory
            async with conn.cursor() as cursor:
                for sql in sql_statements:
                    logger.debug(f"Executing SQL: {sql}")
                    await cursor.execute(sql)
        
        logger.info(f"Successfully moved from {source_graph} to {target_graph}")
        return True
        
    except Exception as e:
        logger.error(f"Error in MOVE GRAPH operation: {e}")
        raise


async def _execute_add_graph(space_impl: PostgreSQLSpaceImpl, space_id: str, sparql_update: str,
                            term_cache: Optional[PostgreSQLCacheTerm] = None,
                            graph_cache: Optional[Dict] = None) -> bool:
    """Execute ADD GRAPH operation."""
    logger = logging.getLogger(__name__)
    logger.debug("Executing ADD GRAPH operation")
    
    try:
        # Parse source and target graph URIs from ADD statement
        source_graph, target_graph = _parse_add_graphs(sparql_update)
        
        # Create table configuration
        table_config = TableConfig.from_space_impl(space_impl, space_id)
        
        # Use the existing translation function
        sql_statements = translate_add_operation(source_graph, target_graph, table_config)
        
        # Execute the SQL statements
        async with space_impl.core.get_dict_connection() as conn:
            # Connection already configured with dict_row factory
            async with conn.cursor() as cursor:
                for sql in sql_statements:
                    logger.debug(f"Executing SQL: {sql}")
                    await cursor.execute(sql)
        
        logger.info(f"Successfully added from {source_graph} to {target_graph}")
        return True
        
    except Exception as e:
        logger.error(f"Error in ADD GRAPH operation: {e}")
        raise


async def _execute_load_operation(space_impl: PostgreSQLSpaceImpl, space_id: str, sparql_update: str,
                                 term_cache: Optional[PostgreSQLCacheTerm] = None,
                                 graph_cache: Optional[Dict] = None) -> bool:
    """Execute LOAD operation."""
    logger = logging.getLogger(__name__)
    logger.debug("Executing LOAD operation")
    
    try:
        # Parse source URI and target graph from LOAD statement
        source_uri, target_graph = _parse_load_operation(sparql_update)
        
        # Create table configuration
        table_config = TableConfig.from_space_impl(space_impl, space_id)
        
        # Use the existing translation function
        sql_statements = translate_load_operation(source_uri, target_graph, table_config)
        
        # Execute the SQL statements
        async with space_impl.core.get_dict_connection() as conn:
            # Connection already configured with dict_row factory
            async with conn.cursor() as cursor:
                for sql in sql_statements:
                    logger.debug(f"Executing SQL: {sql}")
                    await cursor.execute(sql)
        
        logger.info(f"Successfully loaded from {source_uri} into {target_graph}")
        return True
        
    except Exception as e:
        logger.error(f"Error in LOAD operation: {e}")
        raise


# SPARQL UPDATE Parsing Functions
# ===============================

def _parse_insert_data_query(sparql_update: str) -> Tuple[List[Tuple], Optional[str]]:
    """
    Parse INSERT DATA query to extract triples and graph URI using RDFLib.
    
    Args:
        sparql_update: INSERT DATA SPARQL query string
        
    Returns:
        Tuple of (triples_list, graph_uri)
    """
    logger = logging.getLogger(__name__)
    logger.debug("Parsing INSERT DATA query")
    
    try:
        from rdflib import Graph, ConjunctiveGraph, URIRef
        from rdflib.plugins.sparql.processor import SPARQLUpdateProcessor
        
        logger.debug(f"Parsing INSERT DATA query: {sparql_update}")
        
        # Create a temporary graph to capture the INSERT DATA triples
        temp_graph = ConjunctiveGraph()
        
        # Use RDFLib's SPARQL UPDATE processor to parse and extract the data
        processor = SPARQLUpdateProcessor(temp_graph)
        
        # Execute the update on the temporary graph to extract triples
        processor.update(sparql_update)
        
        logger.debug(f"Temp graph has {len(temp_graph)} triples after update")
        
        # Extract all quads from the temporary graph
        triples = []
        default_graph_uri = None
        
        for context in temp_graph.contexts():
            graph_uri = context.identifier if context.identifier != temp_graph.default_context.identifier else None
            
            for subject, predicate, obj in context:
                # Store triples as 3-tuples (subject, predicate, object)
                triples.append((subject, predicate, obj))
                logger.debug(f"  Triple: {subject} {predicate} {obj} (graph: {graph_uri})")
                
                # Track if we have a specific graph URI
                if graph_uri and not default_graph_uri:
                    default_graph_uri = str(graph_uri)
        
        logger.debug(f"Successfully parsed {len(triples)} triples from INSERT DATA")
        
        # Return triples and the primary graph URI (if any)
        return triples, default_graph_uri
        
    except Exception as e:
        logger.error(f"Error parsing INSERT DATA triples with RDFLib: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        # Fallback to simple parsing for basic cases
        return _parse_data_triples_fallback(sparql_update, "INSERT DATA")


def _parse_delete_data_query(sparql_update: str) -> Tuple[List[Tuple], Optional[str]]:
    """
    Parse DELETE DATA query to extract triples and graph URI using RDFLib.
    
    Args:
        sparql_update: DELETE DATA SPARQL query string
        
    Returns:
        Tuple of (triples_list, graph_uri)
    """
    logger = logging.getLogger(__name__)
    logger.debug("Parsing DELETE DATA query")
    
    try:
        from rdflib import Graph, ConjunctiveGraph, URIRef
        from rdflib.plugins.sparql.processor import SPARQLUpdateProcessor
        
        logger.debug(f"Parsing DELETE DATA query: {sparql_update}")
        
        # Create a temporary graph to capture the DELETE DATA triples
        temp_graph = ConjunctiveGraph()
        
        # Use RDFLib's SPARQL UPDATE processor to parse and extract the data
        processor = SPARQLUpdateProcessor(temp_graph)
        
        # Execute the update on the temporary graph to extract triples
        processor.update(sparql_update)
        
        logger.debug(f"Temp graph has {len(temp_graph)} triples after update")
        
        # Extract all quads from the temporary graph
        triples = []
        default_graph_uri = None
        
        for context in temp_graph.contexts():
            graph_uri = context.identifier if context.identifier != temp_graph.default_context.identifier else None
            
            for subject, predicate, obj in context:
                # Store triples as 3-tuples (subject, predicate, object)
                triples.append((subject, predicate, obj))
                logger.debug(f"  Triple: {subject} {predicate} {obj} (graph: {graph_uri})")
                
                # Track if we have a specific graph URI
                if graph_uri and not default_graph_uri:
                    default_graph_uri = str(graph_uri)
        
        logger.debug(f"Successfully parsed {len(triples)} triples from DELETE DATA")
        
        # Return triples and the primary graph URI (if any)
        return triples, default_graph_uri
        
    except Exception as e:
        logger.error(f"Error parsing DELETE DATA triples with RDFLib: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        # Fallback to simple parsing for basic cases
        return _parse_data_triples_fallback(sparql_update, "DELETE DATA")


def _parse_modify_operation(sparql_update: str, table_config: TableConfig) -> Tuple[List[Tuple], List[Tuple], SQLComponents]:
    """
    Parse MODIFY operation (DELETE/INSERT with WHERE).
    
    Args:
        sparql_update: SPARQL MODIFY query string
        table_config: Table configuration
        
    Returns:
        Tuple of (delete_template, insert_template, where_sql)
    """
    logger = logging.getLogger(__name__)
    logger.warning("MODIFY operation parsing not yet fully implemented - using placeholder")
    
    # Return empty templates for now
    delete_template = []
    insert_template = []
    where_sql = SQLComponents(select="", from_clause="", where="", group_by="", order_by="")
    
    return delete_template, insert_template, where_sql


def _parse_graph_uri_from_create(sparql_update: str) -> str:
    """
    Parse graph URI from CREATE GRAPH statement.
    
    Args:
        sparql_update: CREATE GRAPH SPARQL statement
        
    Returns:
        Graph URI string
    """
    import re
    
    # Extract graph URI from CREATE GRAPH statement
    match = re.search(r'CREATE\s+(?:SILENT\s+)?GRAPH\s*<([^>]+)>', sparql_update, re.IGNORECASE)
    if match:
        return match.group(1)
    else:
        raise ValueError("Could not parse graph URI from CREATE GRAPH statement")


def _parse_graph_uri_from_drop(sparql_update: str) -> str:
    """
    Parse graph URI from DROP GRAPH statement.
    
    Args:
        sparql_update: DROP GRAPH SPARQL statement
        
    Returns:
        Graph URI string
    """
    import re
    
    # Extract graph URI from DROP GRAPH statement
    match = re.search(r'DROP\s+(?:SILENT\s+)?GRAPH\s*<([^>]+)>', sparql_update, re.IGNORECASE)
    if match:
        return match.group(1)
    else:
        raise ValueError("Could not parse graph URI from DROP GRAPH statement")


def _parse_graph_uri_from_clear(sparql_update: str) -> str:
    """
    Parse graph URI from CLEAR GRAPH statement.
    
    Args:
        sparql_update: CLEAR GRAPH SPARQL statement
        
    Returns:
        Graph URI string
    """
    import re
    
    # Extract graph URI from CLEAR GRAPH statement
    match = re.search(r'CLEAR\s+(?:SILENT\s+)?GRAPH\s*<([^>]+)>', sparql_update, re.IGNORECASE)
    if match:
        return match.group(1)
    else:
        raise ValueError("Could not parse graph URI from CLEAR GRAPH statement")


def _parse_copy_graphs(sparql_update: str) -> Tuple[str, str]:
    """
    Parse source and target graph URIs from COPY statement.
    
    Args:
        sparql_update: COPY SPARQL statement
        
    Returns:
        Tuple of (source_graph, target_graph)
    """
    import re
    
    # Extract source and target graph URIs from COPY statement
    match = re.search(r'COPY\s+(?:SILENT\s+)?GRAPH\s*<([^>]+)>\s+TO\s+GRAPH\s*<([^>]+)>', sparql_update, re.IGNORECASE)
    if match:
        return match.group(1), match.group(2)
    else:
        raise ValueError("Could not parse graph URIs from COPY statement")


def _parse_move_graphs(sparql_update: str) -> Tuple[str, str]:
    """
    Parse source and target graph URIs from MOVE statement.
    
    Args:
        sparql_update: MOVE SPARQL statement
        
    Returns:
        Tuple of (source_graph, target_graph)
    """
    import re
    
    # Extract source and target graph URIs from MOVE statement
    match = re.search(r'MOVE\s+(?:SILENT\s+)?GRAPH\s*<([^>]+)>\s+TO\s+GRAPH\s*<([^>]+)>', sparql_update, re.IGNORECASE)
    if match:
        return match.group(1), match.group(2)
    else:
        raise ValueError("Could not parse graph URIs from MOVE statement")


def _parse_add_graphs(sparql_update: str) -> Tuple[str, str]:
    """
    Parse source and target graph URIs from ADD statement.
    
    Args:
        sparql_update: ADD SPARQL statement
        
    Returns:
        Tuple of (source_graph, target_graph)
    """
    import re
    
    # Extract source and target graph URIs from ADD statement
    match = re.search(r'ADD\s+(?:SILENT\s+)?GRAPH\s*<([^>]+)>\s+TO\s+GRAPH\s*<([^>]+)>', sparql_update, re.IGNORECASE)
    if match:
        return match.group(1), match.group(2)
    else:
        raise ValueError("Could not parse graph URIs from ADD statement")


def _parse_load_operation(sparql_update: str) -> Tuple[str, Optional[str]]:
    """
    Parse source URI and target graph from LOAD statement.
    
    Args:
        sparql_update: LOAD SPARQL statement
        
    Returns:
        Tuple of (source_uri, target_graph)
    """
    import re
    
    # Extract source URI and optional target graph from LOAD statement
    match = re.search(r'LOAD\s+(?:SILENT\s+)?<([^>]+)>(?:\s+INTO\s+GRAPH\s*<([^>]+)>)?', sparql_update, re.IGNORECASE)
    if match:
        source_uri = match.group(1)
        target_graph = match.group(2) if match.group(2) else None
        return source_uri, target_graph
    else:
        raise ValueError("Could not parse URIs from LOAD statement")


def _parse_data_triples_fallback(sparql_update: str, operation_type: str) -> Tuple[List[Tuple], Optional[str]]:
    """
    Fallback parser for INSERT DATA and DELETE DATA operations using simple regex.
    
    Args:
        sparql_update: SPARQL UPDATE query string
        operation_type: Type of operation ("INSERT DATA" or "DELETE DATA")
        
    Returns:
        Tuple of (triples_list, graph_uri)
    """
    logger = logging.getLogger(__name__)
    logger.warning(f"Using fallback parsing for {operation_type} operation")
    
    import re
    from rdflib import URIRef, Literal, BNode
    
    try:
        # Extract graph URI if present
        graph_match = re.search(r'GRAPH\s*<([^>]+)>', sparql_update, re.IGNORECASE)
        graph_uri = graph_match.group(1) if graph_match else None
        
        # Simple regex-based triple extraction (very basic)
        # This is a simplified fallback - would need more sophisticated parsing for production
        triples = []
        
        # Look for simple triple patterns like: <subject> <predicate> "object" .
        triple_pattern = r'<([^>]+)>\s+<([^>]+)>\s+(?:"([^"]+)"|<([^>]+)>)\s*[;.]'
        matches = re.findall(triple_pattern, sparql_update)
        
        for match in matches:
            subject_uri, predicate_uri, literal_obj, uri_obj = match
            subject = URIRef(subject_uri)
            predicate = URIRef(predicate_uri)
            
            if literal_obj:
                obj = Literal(literal_obj)
            elif uri_obj:
                obj = URIRef(uri_obj)
            else:
                continue
                
            # Store triples as 3-tuples (subject, predicate, object)
            triples.append((subject, predicate, obj))
            logger.debug(f"Fallback parsed triple: {subject} {predicate} {obj} (graph: {graph_uri})")
        
        logger.debug(f"Fallback parsing extracted {len(triples)} triples")
        return triples, graph_uri
        
    except Exception as e:
        logger.error(f"Error in fallback parsing for {operation_type}: {e}")
        return [], None
