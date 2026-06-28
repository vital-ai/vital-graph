"""
PostgreSQL SPARQL Query Functions for VitalGraph

This module provides pure functions for building different SPARQL query types
(SELECT, CONSTRUCT, ASK, DESCRIBE) from SQL components.
No inter-dependencies with other SPARQL modules - only imports utilities.
"""

import logging
from typing import Dict, List, Tuple, Set, Optional, Any, Union
from rdflib import Variable, URIRef, Literal, BNode

# Import only from core module and utilities
from .postgresql_sparql_core import SQLComponents, TableConfig, AliasGenerator, SparqlContext


def build_select_query(sql_components: SQLComponents, projection_vars: List, 
                      distinct: bool = False, limit_offset: tuple = None, *, sparql_context: SparqlContext = None) -> str:
    """
    Build SELECT query from SQL components using exact logic from original implementation.
    Exact port of PostgreSQLSparqlImpl._translate_select_query method.
    
    Args:
        sql_components: SQL components containing FROM, WHERE, JOINs, and variable mappings
        projection_vars: List of variables to project in SELECT clause
        distinct: Whether to include DISTINCT modifier
        limit_offset: Optional tuple of (limit, offset) values
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        Complete SQL SELECT query string
    """
    function_name = "build_select_query"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, 
                                         num_projection_vars=len(projection_vars) if projection_vars else 0,
                                         distinct=distinct,
                                         has_limit_offset=limit_offset is not None)
    else:
        logger = logging.getLogger(__name__)
    
    # Debug: Log what we're receiving (reduced logging for performance)
    logger.debug(f"🔍 BUILD_SELECT_QUERY: Called with {len(projection_vars) if projection_vars else 0} projection vars")
    if projection_vars:
        logger.debug(f"🔍 BUILD_SELECT_QUERY: Projection vars: {[str(v) for v in projection_vars]}")
    
    # Build SELECT clause, GROUP BY clause, and HAVING clause with variable mappings
    select_clause, group_by_clause, having_clause, case_mapping = _build_select_clause(projection_vars, sql_components.variable_mappings, distinct, sparql_context=sparql_context)
    
    # Build complete SQL query - exact logic from original implementation
    sql_parts = [select_clause]
    if sql_components.from_clause:
        # Add FROM keyword if not already present
        if not sql_components.from_clause.strip().upper().startswith('FROM'):
            sql_parts.append(f"FROM {sql_components.from_clause}")
        else:
            sql_parts.append(sql_components.from_clause)
    
    if sql_components.joins:
        sql_parts.extend(sql_components.joins)
    
    # Check if this is a UNION-derived table - if so, don't apply outer WHERE conditions
    # UNION patterns are self-contained and all conditions are already within subqueries
    is_union_derived = "union_" in sql_components.from_clause and "FROM (" in sql_components.from_clause
    
    if sql_components.where_conditions and not is_union_derived:
        sql_parts.append(f"WHERE {' AND '.join(sql_components.where_conditions)}")
    elif sql_components.where_conditions and is_union_derived:
        logger.debug(f"Skipping {len(sql_components.where_conditions)} WHERE conditions for UNION-derived table")
    
    # Add GROUP BY clause if present
    if group_by_clause:
        sql_parts.append(group_by_clause)
    
    # CRITICAL: Add HAVING clause AFTER GROUP BY (this is the fix for HAVING clause support)
    if having_clause:
        sql_parts.append(having_clause)
    
    # Add ORDER BY clause if present
    if sql_components.order_by:
        sql_parts.append(sql_components.order_by)
    
    # Add LIMIT and OFFSET if present - exact logic from original
    if limit_offset:
        limit, offset = limit_offset
        if offset is not None:
            sql_parts.append(f"OFFSET {offset}")
        if limit is not None:
            sql_parts.append(f"LIMIT {limit}")
    
    result = '\n'.join(sql_parts)
    
    if sparql_context:
        sparql_context.log_function_exit(function_name, "SQL_query", query_length=len(result))
    
    return result


def _build_select_clause(projection_vars: List, variable_mappings: Dict, has_distinct: bool = False, *, sparql_context: SparqlContext = None) -> tuple:
    """
    Build SQL SELECT clause, GROUP BY clause, and HAVING clause from SPARQL projection variables.
    Exact port from original implementation.
    
    Args:
        projection_vars: List of variables to project in SELECT clause
        variable_mappings: Variable to SQL column mappings
        has_distinct: Whether to include DISTINCT modifier
        sparql_context: SparqlContext for logging and configuration (optional)
    
    Returns:
        Tuple of (select_clause, group_by_clause, having_clause, case_mapping)
        where case_mapping maps lowercase column names to original SPARQL variable names
    """
    function_name = "_build_select_clause"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, 
                                         num_projection_vars=len(projection_vars) if projection_vars else 0,
                                         has_distinct=has_distinct)
    else:
        logger = logging.getLogger(__name__)
    logger.debug(f"Building SELECT clause with projection_vars: {projection_vars}")
    logger.debug(f"Building SELECT clause with variable_mappings: {variable_mappings}")
    
    if not projection_vars:
        distinct_keyword = "DISTINCT " if has_distinct else ""
        return f"SELECT {distinct_keyword}*", "", "", {}
    
    select_items = []
    case_mapping = {}  # Maps unique SQL aliases to original SPARQL variable names
    alias_counter = {}  # Tracks collision counters for case-insensitive names
    
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
        
        # Debug: Log what we're trying to look up
        logger.debug(f"🔍 SELECT CLAUSE: Processing var={var} (type={type(var)}), var_name='{var_name}', unique_alias='{unique_alias}'")
        
        # Get the term text for this variable using the mapping
        # PRIORITY ORDER: Use global optimization state first, then string keys, then Variable objects
        term_column = None
        

        
        # SECOND PRIORITY: Try string name lookup (these have the correct term table mappings)
        if not term_column and var_name in variable_mappings:
            term_column = variable_mappings[var_name]
            logger.debug(f"🔍 FOUND MAPPING VIA STRING: {var_name} -> {term_column}")
        
        # LOWEST PRIORITY: Try Variable object lookup (these might have wrong alias mappings)
        if not term_column and var in variable_mappings:
            term_column = variable_mappings[var]
            logger.debug(f"🔍 FOUND MAPPING VIA VARIABLE OBJECT: {var} -> {term_column}")
        
        if term_column:
            # Use unique alias to avoid PostgreSQL case conflicts
            select_items.append(f'{term_column} AS "{unique_alias}"')
            logger.warning(f"🔍 SELECT ITEM SUCCESS: {var} -> {term_column} AS \"{unique_alias}\"")
        else:
            # Fallback - shouldn't happen with proper mapping
            select_items.append(f"'UNMAPPED_VAR_{var_name}' AS \"{unique_alias}\"")
            logger.warning(f"⚠️ UNMAPPED VARIABLE: {var} (tried var object, '{var_name}' string, alias lookup)")
            logger.warning(f"⚠️ AVAILABLE MAPPINGS: {list(variable_mappings.keys())}")
        
    distinct_keyword = "DISTINCT " if has_distinct else ""
    select_clause = f"SELECT {distinct_keyword}{', '.join(select_items)}"
    
    # Build GROUP BY clause if GROUP BY variables are present
    group_by_clause = ""
    group_by_vars = variable_mappings.get('__GROUP_BY_VARS__')
    if group_by_vars:
        group_by_items = []
        for group_var in group_by_vars:
            if group_var in variable_mappings:
                group_by_items.append(variable_mappings[group_var])
            else:
                logger.warning(f"GROUP BY variable {group_var} not found in mappings")
        
        if group_by_items:
            group_by_clause = f"GROUP BY {', '.join(group_by_items)}"
            logger.debug(f"Built GROUP BY clause: {group_by_clause}")
    
    # Build HAVING clause if HAVING conditions are present
    having_clause = ""
    having_conditions = variable_mappings.get('__HAVING_CONDITIONS__')
    if having_conditions:
        having_clause = f"HAVING {' AND '.join(having_conditions)}"
        logger.debug(f"Built HAVING clause: {having_clause}")
    
    result = (select_clause, group_by_clause, having_clause, case_mapping)
    
    if sparql_context:
        sparql_context.log_function_exit(function_name, "tuple", 
                                        select_clause_length=len(select_clause),
                                        has_group_by=bool(group_by_clause),
                                        has_having=bool(having_clause))
    
    return result


def build_construct_query(sql_components: SQLComponents, construct_template: List[Tuple], *, sparql_context: SparqlContext = None) -> str:
    """
    Build CONSTRUCT query from SQL components and template.
    
    Args:
        sql_components: SQL components for the WHERE clause
        construct_template: List of (subject, predicate, object) triples to construct
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        SQL query string that returns data for CONSTRUCT template processing
    """
    function_name = "build_construct_query"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, 
                                         num_template_triples=len(construct_template) if construct_template else 0)
    else:
        logger = logging.getLogger(__name__)
    logger = logging.getLogger(__name__)
    logger.debug(f"Building CONSTRUCT query with {len(construct_template)} template triples")
    
    # For CONSTRUCT, we need to return all variable bindings that will be used
    # to instantiate the construct template
    construct_vars = set()
    for triple in construct_template:
        for term in triple:
            if isinstance(term, Variable):
                construct_vars.add(term)
    
    # 🌍 COORDINATION FIX: Use consistent sorted variable ordering to match UNION pattern translation
    # This ensures variable indexing matches between UNION subqueries and final CONSTRUCT query
    construct_vars_sorted = sorted(construct_vars, key=str)  # Same ordering as UNION pattern
    logger.debug(f"CONSTRUCT variables (sorted): {[str(v) for v in construct_vars_sorted]}")
    
    # Build SELECT clause for construct variables using consistent ordering
    select_items = []
    for var in construct_vars_sorted:
        if var in sql_components.variable_mappings:
            var_mapping = sql_components.variable_mappings[var]
            var_name = str(var).replace('?', '')
            select_items.append(f"{var_mapping} AS {var_name}")
        else:
            # 🌍 COORDINATION FIX: Check master variable mappings before UNMAPPED fallback
            # This completes the two-phase coordination fix for CONSTRUCT queries
            var_name = str(var).replace('?', '')
            master_mapping = None
            
            if var_name in variable_mappings:
                select_items.append(f"{variable_mappings[var_name]} AS {var_name}")
            elif var in variable_mappings:
                select_items.append(f"{variable_mappings[var]} AS {var_name}")
            else:
                logger.warning(f"No mapping found for {var}, using UNMAPPED fallback")
                select_items.append(f"'UNMAPPED_{var_name}' AS {var_name}")
    
    if not select_items:
        select_items = ["*"]
    
    # CONSTRUCT queries with CROSS JOINs need DISTINCT to eliminate duplicates
    # Check if this query uses CROSS JOINs that require deduplication
    needs_distinct = any('CROSS JOIN' in join for join in sql_components.joins) if sql_components.joins else False
    distinct_keyword = "DISTINCT " if needs_distinct else ""
    
    # Build complete query
    query_parts = [f"SELECT {distinct_keyword}{', '.join(select_items)}"]
    
    if sql_components.from_clause:
        query_parts.append(sql_components.from_clause)
    
    if sql_components.joins:
        query_parts.extend(sql_components.joins)
    
    if sql_components.where_conditions:
        query_parts.append(f"WHERE {' AND '.join(sql_components.where_conditions)}")
    
    # Add ORDER BY clause if present
    if sql_components.order_by:
        query_parts.append(sql_components.order_by)
    
    result = " ".join(query_parts)
    
    if sparql_context:
        sparql_context.log_function_exit(function_name, "SQL_query", query_length=len(result))
    
    return result


def build_ask_query(sql_components: SQLComponents, *, sparql_context: SparqlContext = None) -> str:
    """
    Build ASK query from SQL components.
    
    Args:
        sql_components: SQL components for the pattern to check
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        SQL query string that returns data if pattern exists (for boolean conversion)
    """
    function_name = "build_ask_query"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name)
    else:
        logger = logging.getLogger(__name__)
    logger = logging.getLogger(__name__)
    logger.debug("Building ASK query")
    
    # ASK queries just need to check if the pattern exists
    # Return a simple SELECT 1 with LIMIT 1 for efficiency
    query_parts = ["SELECT 1 AS ask_result"]
    
    if sql_components.from_clause:
        query_parts.append(sql_components.from_clause)
    
    if sql_components.joins:
        query_parts.extend(sql_components.joins)
    
    if sql_components.where_conditions:
        query_parts.append(f"WHERE {' AND '.join(sql_components.where_conditions)}")
    
    query_parts.append("LIMIT 1")
    
    result = " ".join(query_parts)
    
    if sparql_context:
        sparql_context.log_function_exit(function_name, "SQL_query", query_length=len(result))
    
    return result


def build_describe_query(resources: List[Union[URIRef, Variable]], table_config: TableConfig,
                        alias_gen: AliasGenerator, *, sparql_context: SparqlContext = None) -> str:
    """
    Build DESCRIBE query from resources and optional WHERE clause.
    
    Args:
        resources: List of resources to describe (URIRef for specific resources, Variable for pattern-based)
        table_config: Table configuration
        alias_gen: Alias generator for consistent naming
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        SQL query string that returns all triples for the described resources
    """
    function_name = "build_describe_query"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, num_resources=len(resources) if resources else 0)
    else:
        logger = logging.getLogger(__name__)
    logger.debug(f"Building DESCRIBE query for {len(resources)} resources")
    
    # DESCRIBE returns all triples where the described resource(s) are subjects
    select_clause = f"""
        SELECT 
            s.term_text AS subject,
            p.term_text AS predicate,
            o.term_text AS object
        FROM {table_config.quad_table} q
        JOIN {table_config.term_table} s ON q.subject_uuid = s.term_uuid
        JOIN {table_config.term_table} p ON q.predicate_uuid = p.term_uuid
        JOIN {table_config.term_table} o ON q.object_uuid = o.term_uuid
    """
    
    query_parts = [select_clause.strip()]
    
    # Build WHERE conditions for described resources
    describe_conditions = []
    
    for resource in resources:
        if isinstance(resource, URIRef):
            # Specific resource - add direct condition
            resource_condition = f"s.term_text = '{str(resource)}' AND s.term_type = 'U'"
            describe_conditions.append(resource_condition)
        elif isinstance(resource, Variable):
            # Variable resource - use WHERE clause if provided
            if where_sql and resource in where_sql.variable_mappings:
                var_mapping = where_sql.variable_mappings[resource]
                describe_conditions.append(f"s.term_text = {var_mapping}")
    
    # Combine all conditions
    all_conditions = []
    
    if describe_conditions:
        if len(describe_conditions) == 1:
            all_conditions.append(describe_conditions[0])
        else:
            all_conditions.append(f"({' OR '.join(describe_conditions)})")
    
    if where_sql and where_sql.where_conditions:
        all_conditions.extend(where_sql.where_conditions)
    
    if all_conditions:
        query_parts.append(f"WHERE {' AND '.join(all_conditions)}")
    
    result = " ".join(query_parts)
    
    if sparql_context:
        sparql_context.log_function_exit(function_name, "SQL_query", query_length=len(result))
    
    return result


def build_aggregation_query(sql_components: SQLComponents, projection_vars: List[Variable],
                          group_by_vars: List[Variable], having_conditions: List[str] = None, *, sparql_context: SparqlContext = None) -> str:
    """
    Build aggregation query with GROUP BY and HAVING clauses.
    
    Args:
        sql_components: SQL components for the base query
        projection_vars: Variables to project (including aggregate expressions)
        group_by_vars: Variables to group by
        having_conditions: Optional HAVING conditions
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        SQL query string with aggregation
    """
    function_name = "build_aggregation_query"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, 
                                         num_projection_vars=len(projection_vars) if projection_vars else 0,
                                         num_group_by_vars=len(group_by_vars) if group_by_vars else 0,
                                         has_having_conditions=having_conditions is not None)
    else:
        logger = logging.getLogger(__name__)
    logger = logging.getLogger(__name__)
    logger.debug(f"Building aggregation query with {len(group_by_vars)} GROUP BY variables")
    
    # Build SELECT clause
    select_items = []
    for var in projection_vars:
        if var in sql_components.variable_mappings:
            var_mapping = sql_components.variable_mappings[var]
            var_name = str(var).replace('?', '')
            select_items.append(f"{var_mapping} AS {var_name}")
        else:
            var_name = str(var).replace('?', '')
            select_items.append(f"'UNMAPPED_{var_name}' AS {var_name}")
    
    query_parts = [f"SELECT {', '.join(select_items)}"]
    
    if sql_components.from_clause:
        query_parts.append(sql_components.from_clause)
    
    if sql_components.joins:
        query_parts.extend(sql_components.joins)
    
    if sql_components.where_conditions:
        query_parts.append(f"WHERE {' AND '.join(sql_components.where_conditions)}")
    
    # Add GROUP BY clause
    if group_by_vars:
        group_by_items = []
        for var in group_by_vars:
            if var in sql_components.variable_mappings:
                group_by_items.append(sql_components.variable_mappings[var])
        
        if group_by_items:
            query_parts.append(f"GROUP BY {', '.join(group_by_items)}")
    
    # Add HAVING clause
    if having_conditions:
        query_parts.append(f"HAVING {' AND '.join(having_conditions)}")
    
    # Add ORDER BY clause if present
    if sql_components.order_by:
        query_parts.append(sql_components.order_by)
    
    result = " ".join(query_parts)
    
    if sparql_context:
        sparql_context.log_function_exit(function_name, "SQL_query", query_length=len(result))
    
    return result


def build_subquery(sql_components: SQLComponents, alias: str, *, sparql_context: SparqlContext = None) -> str:
    """
    Build a subquery from SQL components with the given alias.
    
    Args:
        sql_components: SQL components to wrap in subquery
        alias: Alias for the subquery
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        SQL subquery string
    """
    function_name = "build_subquery"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, alias=alias)
    else:
        logger = logging.getLogger(__name__)
    logger = logging.getLogger(__name__)
    logger.debug(f"Building subquery with alias: {alias}")
    
    # Build inner query
    inner_parts = ["SELECT *"]
    
    if sql_components.from_clause:
        inner_parts.append(sql_components.from_clause)
    
    if sql_components.joins:
        inner_parts.extend(sql_components.joins)
    
    if sql_components.where_conditions:
        inner_parts.append(f"WHERE {' AND '.join(sql_components.where_conditions)}")
    
    inner_query = " ".join(inner_parts)
    
    return f"({inner_query}) {alias}"


def build_union_query(left_sql: str, right_sql: str, alias: str, *, sparql_context: SparqlContext = None) -> str:
    """
    Build UNION query from left and right SQL queries.
    
    Args:
        left_sql: Left operand SQL query
        right_sql: Right operand SQL query
        alias: Alias for the UNION result
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        SQL UNION query string
    """
    function_name = "build_union_query"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, alias=alias)
    else:
        logger = logging.getLogger(__name__)
    logger = logging.getLogger(__name__)
    logger.debug("Building UNION query")
    
    union_query = f"({left_sql}) UNION ({right_sql})"
    
    if alias:
        return f"({union_query}) {alias}"
    else:
        return union_query


def optimize_query_structure(query: str, *, sparql_context: SparqlContext = None) -> str:
    """
    Apply basic optimizations to the generated SQL query.
    
    Args:
        query: SQL query string to optimize
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        Optimized SQL query string
    """
    function_name = "optimize_query_structure"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, query_length=len(query))
    else:
        logger = logging.getLogger(__name__)
    logger = logging.getLogger(__name__)
    logger.debug("Optimizing query structure")
    
    import re
    
    optimized = query.strip()
    
    # Remove duplicate spaces
    optimized = re.sub(r'\s+', ' ', optimized)
    
    # Remove redundant parentheses in WHERE conditions
    optimized = re.sub(r'WHERE \(([^()]+)\)$', r'WHERE \1', optimized)
    
    # Remove empty WHERE clauses
    optimized = re.sub(r'WHERE\s*$', '', optimized)
    
    # Remove redundant AND conditions
    optimized = re.sub(r'\s+AND\s+AND\s+', ' AND ', optimized)
    
    # Remove trailing AND/OR in WHERE clauses
    optimized = re.sub(r'WHERE\s+(.*)\s+(AND|OR)\s*$', r'WHERE \1', optimized)
    
    # Simplify UNION ALL when possible
    if 'UNION' in optimized and 'DISTINCT' not in optimized.upper():
        optimized = optimized.replace('UNION', 'UNION ALL')
    
    return optimized


def validate_query_syntax(query: str, *, sparql_context: SparqlContext = None) -> bool:
    """
    Perform basic validation of SQL query syntax.
    
    Args:
        query: SQL query string to validate
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        True if the query appears to be syntactically valid
    """
    function_name = "validate_query_syntax"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, query_length=len(query))
    else:
        logger = logging.getLogger(__name__)
    logger = logging.getLogger(__name__)
    logger.debug("Validating query syntax")
    
    try:
        if not query or not query.strip():
            logger.error("Empty query")
            return False
        
        query_upper = query.upper().strip()
        
        # Check for required keywords
        if not any(keyword in query_upper for keyword in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'WITH']):
            logger.error("Query missing required SQL keyword")
            return False
        
        # Check for balanced parentheses
        if query.count('(') != query.count(')'):
            logger.error("Unbalanced parentheses in query")
            return False
        
        # Check for balanced quotes
        single_quotes = query.count("'") % 2
        double_quotes = query.count('"') % 2
        if single_quotes != 0 or double_quotes != 0:
            logger.error("Unbalanced quotes in query")
            return False
        
        # Check for basic SQL structure
        if 'SELECT' in query_upper and 'FROM' not in query_upper:
            # Allow simple SELECT statements like SELECT 1
            if not any(simple in query_upper for simple in ['SELECT 1', 'SELECT TRUE', 'SELECT FALSE']):
                logger.warning("SELECT query without FROM clause")
        
        # Check for SQL injection patterns
        suspicious_patterns = [';--', '/*', '*/', 'xp_', 'sp_']
        for pattern in suspicious_patterns:
            if pattern in query.lower():
                logger.warning(f"Potentially suspicious pattern found: {pattern}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error validating query syntax: {e}")
        return False


def estimate_query_cost(query: str, table_config: TableConfig, *, sparql_context: SparqlContext = None) -> int:
    """
    Estimate the computational cost of a SQL query.
    
    Args:
        query: SQL query string
        table_config: Table configuration for cost estimation
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        Estimated cost score (higher = more expensive)
    """
    function_name = "estimate_query_cost"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, query_length=len(query))
    else:
        logger = logging.getLogger(__name__)
    logger = logging.getLogger(__name__)
    logger.debug("Estimating query cost")
    
    cost = 1
    query_upper = query.upper()
    
    # Add cost for different operations
    if 'JOIN' in query_upper:
        cost += query_upper.count('JOIN') * 2
    
    if 'UNION' in query_upper:
        cost += query_upper.count('UNION') * 3
    
    if 'SUBQUERY' in query_upper or '(' in query:
        cost += query.count('(') * 2
    
    if 'GROUP BY' in query_upper:
        cost += 3
    
    if 'ORDER BY' in query_upper:
        cost += 2
    
    if 'DISTINCT' in query_upper:
        cost += 2
    
    return cost


def add_limit_offset_clause(base_query: str, limit: Optional[int] = None, 
                           offset: Optional[int] = None, *, sparql_context: SparqlContext = None) -> str:
    """
    Add LIMIT and OFFSET clauses to a query.
    
    Args:
        base_query: Base SQL query
        limit: Optional limit value
        offset: Optional offset value
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        Query with LIMIT/OFFSET clauses added
    """
    function_name = "add_limit_offset_clause"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, limit=limit, offset=offset)
    else:
        logger = logging.getLogger(__name__)
    query_parts = [base_query]
    
    if limit is not None and limit > 0:
        query_parts.append(f"LIMIT {limit}")
    
    if offset is not None and offset > 0:
        query_parts.append(f"OFFSET {offset}")
    
    result = " ".join(query_parts)
    
    if sparql_context:
        sparql_context.log_function_exit(function_name, "SQL_query", query_length=len(result))
    
    return result


def build_values_clause(values_data: List[Dict[Variable, str]], 
                       variable_mappings: Dict[Variable, str], *, sparql_context: SparqlContext = None) -> str:
    """
    Build VALUES clause from data and variable mappings.
    
    Args:
        values_data: List of variable bindings
        variable_mappings: Variable to column mappings
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        SQL VALUES clause
    """
    function_name = "build_values_clause"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, num_values=len(values_data) if values_data else 0)
    else:
        logger = logging.getLogger(__name__)
    if not values_data:
        return ""
    
    # Get all variables from the first row to determine column order
    variables = list(values_data[0].keys())
    
    # Build column list
    columns = []
    for var in variables:
        if var in variable_mappings:
            columns.append(variable_mappings[var])
        else:
            columns.append(str(var).replace('?', ''))
    
    # Build value rows
    value_rows = []
    for row in values_data:
        row_values = []
        for var in variables:
            value = row.get(var, 'NULL')
            if value != 'NULL' and not value.startswith("'"):
                value = f"'{value}'"
            row_values.append(value)
        value_rows.append(f"({', '.join(row_values)})")
    
    return f"VALUES {', '.join(value_rows)} AS values_table({', '.join(columns)})"


def extract_projection_variables(query: str) -> List[str]:
    """
    Extract projection variables from a SELECT query.
    
    Args:
        query: SQL SELECT query
        
    Returns:
        List of projected variable names
    """
    import re
    
    # Find SELECT clause
    select_match = re.search(r'SELECT\s+(.*?)\s+FROM', query, re.IGNORECASE | re.DOTALL)
    if not select_match:
        return []
    
    select_clause = select_match.group(1)
    
    # Extract variable names (looking for AS clauses)
    variables = []
    as_matches = re.findall(r'\s+AS\s+(\w+)', select_clause, re.IGNORECASE)
    variables.extend(as_matches)
    
    return variables


def normalize_query_whitespace(query: str) -> str:
    """
    Normalize whitespace in SQL query for consistent formatting.
    
    Args:
        query: SQL query to normalize
        
    Returns:
        Query with normalized whitespace
    """
    import re
    
    # Replace multiple whitespace with single space
    normalized = re.sub(r'\s+', ' ', query.strip())
    
    # Add proper spacing around keywords
    keywords = ['SELECT', 'FROM', 'WHERE', 'JOIN', 'ON', 'GROUP BY', 'ORDER BY', 'HAVING', 'UNION', 'LIMIT', 'OFFSET']
    for keyword in keywords:
        normalized = re.sub(rf'\s*{keyword}\s*', f' {keyword} ', normalized, flags=re.IGNORECASE)
    
    # Clean up extra spaces
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    return normalized
