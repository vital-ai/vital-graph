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
    find_shared_variables, extract_variables_from_triples, validate_pattern_structure
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


# Helper functions for SPARQL orchestration

# Module-level logger
logger = logging.getLogger(__name__)


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


def _extract_variables_from_expression(expr):
    """Extract all variables referenced in a SPARQL expression.
    
    This is critical for BIND+OPTIONAL bug fix - ensures that all variables
    used in BIND expressions are included in projected_vars so they get
    proper mappings from OPTIONAL patterns.
    
    Ported from original implementation.
    """
    from rdflib.term import Variable
    variables = set()
    
    try:
        if isinstance(expr, Variable):
            variables.add(expr)
        elif hasattr(expr, '_vars') and expr._vars:
            # Expression has _vars attribute (common in rdflib expressions)
            variables.update(expr._vars)
        elif hasattr(expr, 'args') and expr.args:
            # Recursively extract from arguments
            for arg in expr.args:
                variables.update(_extract_variables_from_expression(arg))
        elif hasattr(expr, '__dict__'):
            # Check all attributes for variables
            for attr_name, attr_value in expr.__dict__.items():
                if isinstance(attr_value, Variable):
                    variables.add(attr_value)
                elif hasattr(attr_value, '_vars') and attr_value._vars:
                    variables.update(attr_value._vars)
                    
        logger.debug(f"Extracted variables from expression {expr}: {[str(v) for v in variables]}")
        return list(variables)
        
    except Exception as e:
        logger.warning(f"Failed to extract variables from expression {expr}: {e}")
        return []


async def _translate_describe_query(algebra, table_config: TableConfig, context: TranslationContext) -> str:
    """
    Translate DESCRIBE query to SQL - exact copy from original implementation.
    """
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
            WHERE ({' OR '.join(uri_conditions)})
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
                WHERE 1=0
                """
        
        logger.info("Successfully translated DESCRIBE query")
        return main_sql
        
    except Exception as e:
        logger.error(f"Error translating DESCRIBE query: {e}")
        raise NotImplementedError(f"DESCRIBE query translation failed: {e}")


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
        
        # Create stateful context object to maintain shared state across all pattern translations
        # CRITICAL FIX: This replaces the original class-based approach where self.alias_generator
        # and other state was automatically shared across all method calls
        alias_generator = AliasGenerator()
        context = TranslationContext(
            alias_generator=alias_generator,
            term_cache=term_cache,
            space_impl=space_impl,
            table_config=table_config
        )
        
        # Translate SPARQL algebra to SQL components
        if query_type == "SelectQuery":
            # Extract projection variables
            projection_vars = query_algebra.get('PV', [])
            
            # Extract LIMIT/OFFSET information like original implementation
            where_pattern = query_algebra['p']
            limit_info = _extract_limit_offset(where_pattern)
            limit_offset = None
            if limit_info['limit'] is not None or limit_info['offset'] is not None:
                limit_offset = (limit_info['limit'], limit_info['offset'])
                logger.debug(f"Extracted LIMIT/OFFSET: {limit_offset}")
            
            # Extract and translate the main pattern
            sql_components = await translate_algebra_pattern(where_pattern, context, projection_vars)
            
            # Build SELECT query with LIMIT/OFFSET
            sql_query = build_select_query(sql_components, projection_vars, limit_offset=limit_offset)
            
        elif query_type == "ConstructQuery":
            # Handle CONSTRUCT queries
            construct_template = query_algebra.get('template', [])
            where_pattern = query_algebra['p']
            # For CONSTRUCT, we need all variables from the template
            construct_vars = []
            sql_components = await translate_algebra_pattern(where_pattern, context, construct_vars)
            
            # Build CONSTRUCT query
            sql_query = build_construct_query(sql_components, construct_template)
            
        elif query_type == "AskQuery":
            # Handle ASK queries
            where_pattern = query_algebra['p']
            # For ASK, we don't need specific projected vars, just check existence
            sql_components = await translate_algebra_pattern(where_pattern, context, None)
            
            # Build ASK query
            sql_query = build_ask_query(sql_components)
            
        elif query_type == "DescribeQuery":
            # Handle DESCRIBE queries
            sql_query = await _translate_describe_query(query_algebra, table_config, context)
            
        else:
            raise ValueError(f"Unsupported query type: {query_type}")
        
        # Execute SQL query
        sql_results = await execute_sql_query(space_impl, sql_query)
        
        # Process results based on query type
        if query_type == "ConstructQuery":
            # Convert SQL results to RDF triples for CONSTRUCT
            construct_results = await process_construct_results(sql_results, space_impl)
            logger.info(f"CONSTRUCT query executed successfully, returned {len(construct_results)} triples")
            return construct_results
        elif query_type == "DescribeQuery":
            # Convert SQL results to RDF triples for DESCRIBE
            describe_results = await process_describe_results(sql_results)
            logger.info(f"DESCRIBE query executed successfully, returned {len(describe_results)} triples")
            return describe_results
        elif query_type == "AskQuery":
            # Convert SQL results to boolean for ASK
            ask_result = len(sql_results) > 0
            logger.info(f"ASK query executed successfully, result: {ask_result}")
            return [{"ask": ask_result}]
        else:
            # For SELECT queries, return SQL results as-is
            logger.info(f"SELECT query executed successfully, returned {len(sql_results)} results")
            return sql_results
        
    except Exception as e:
        logger.error(f"Error orchestrating SPARQL query: {e}")
        raise


async def translate_algebra_pattern(pattern, context: TranslationContext, 
                                   projected_vars: Optional[List[Variable]] = None) -> SQLComponents:
    """
    Translate SPARQL algebra pattern to SQL components.
    
    This is the core function that maps different SPARQL algebra patterns
    to their corresponding SQL translation functions.
    
    Args:
        pattern: SPARQL algebra pattern from RDFLib
        context: TranslationContext with shared state (alias_gen, term_cache, etc.)
        projected_vars: Variables to project in SELECT clause
        
    Returns:
        SQLComponents with FROM, WHERE, JOINs, and variable mappings
    """
    from rdflib import Variable
    logger = logging.getLogger(__name__)
    
    if pattern is None:
        # Empty pattern
        return SQLComponents(
            from_clause="",
            where_conditions=[],
            joins=[],
            variable_mappings={}
        )
    
    pattern_name = getattr(pattern, 'name', str(type(pattern).__name__))
    logger.debug(f"🔍 PROCESSING PATTERN: {pattern_name}")
    logger.debug(f"Translating algebra pattern: {pattern_name}")
    logger.debug(f"Pattern details: {pattern}")
    
    # Log pattern attributes for debugging
    if hasattr(pattern, 'p'):
        inner_pattern = pattern.p
        inner_name = getattr(inner_pattern, 'name', str(type(inner_pattern).__name__))
        logger.debug(f"Pattern has inner pattern 'p': {inner_name}")
    if hasattr(pattern, 'triples'):
        triples = pattern.triples
        if triples is not None:
            logger.debug(f"Pattern has triples: {len(triples)} triples")
        else:
            logger.debug(f"Pattern has triples: None")
    
    # Basic Graph Pattern (BGP) - most common case
    if pattern_name == "BGP" or (hasattr(pattern, 'triples') and pattern_name not in ["Slice", "Project", "Join", "Union", "LeftJoin", "Minus", "Filter", "ToMultiSet", "Extend", "Group", "SubSelect", "AggregateJoin", "OrderBy", "Graph"]):
        triples = getattr(pattern, 'triples', [])
        # Use term cache for BGP generation if available
        if context.term_cache:
            return await generate_bgp_sql_with_cache(triples, context.table_config, context.alias_generator, projected_vars, context.term_cache, context.space_impl)
        else:
            return generate_bgp_sql(triples, context.table_config, context.alias_generator, projected_vars)
    
    # Join patterns
    elif pattern_name == "Join":
        left_sql = await translate_algebra_pattern(pattern.p1, context, projected_vars)
        right_sql = await translate_algebra_pattern(pattern.p2, context, projected_vars)
        
        # Use the ported original JOIN implementation
        return await translate_join_pattern(left_sql, right_sql, context.alias_generator)
    
    # Union patterns
    elif pattern_name == "Union":
        # CRITICAL FIX: Use the same alias generator for both operands to ensure consistency
        # This prevents "missing FROM-clause entry" errors where context constraints
        # reference aliases that don't match the final FROM clause
        left_sql = await translate_algebra_pattern(pattern.p1, context, projected_vars)
        right_sql = await translate_algebra_pattern(pattern.p2, context, projected_vars)
        return await translate_union_pattern(left_sql, right_sql, context.alias_generator)
    
    # Optional patterns (LEFT JOIN)
    elif pattern_name == "LeftJoin":
        # Translate required and optional parts
        required_sql = await translate_algebra_pattern(pattern.p1, context, projected_vars)
        optional_sql = await translate_algebra_pattern(pattern.p2, context, projected_vars)
        
        # Find shared variables
        required_vars = set(required_sql.variable_mappings.keys())
        optional_vars = set(optional_sql.variable_mappings.keys())
        shared_vars = required_vars & optional_vars
        
        return await translate_optional_pattern(required_sql, optional_sql, context.alias_generator)
    
    # Minus patterns (NOT EXISTS)
    elif pattern_name == "Minus":
        # Translate positive and negative parts
        positive_sql = await translate_algebra_pattern(pattern.p1, context, projected_vars)
        negative_sql = await translate_algebra_pattern(pattern.p2, context, projected_vars)
        return translate_minus_pattern(positive_sql, negative_sql, context.alias_generator)
    
    # Filter patterns
    elif pattern_name == "Filter":
        logger.debug(f"🔍 FILTER PATTERN DEBUG:")
        logger.debug(f"   pattern type: {type(pattern).__name__}")
        logger.debug(f"   pattern has 'p': {hasattr(pattern, 'p')}")
        logger.debug(f"   pattern has 'expr': {hasattr(pattern, 'expr')}")
        
        # Use dictionary access like the original implementation
        try:
            inner_pattern = pattern['p']
            filter_expr = pattern['expr']
            logger.debug(f"   inner_pattern: {type(inner_pattern).__name__}")
            logger.debug(f"   filter_expr: {type(filter_expr).__name__}")
        except (KeyError, TypeError) as e:
            logger.debug(f"   dictionary access failed: {e}, trying attribute access")
            inner_pattern = pattern.p
            filter_expr = pattern.expr
        
        base_sql = await translate_algebra_pattern(inner_pattern, context, projected_vars)
        logger.debug(f"   base_sql variable_mappings: {base_sql.variable_mappings}")
        
        filter_condition = await translate_filter_expression(filter_expr, base_sql.variable_mappings)
        logger.debug(f"   filter_condition: {filter_condition}")
        
        return translate_filter_pattern(base_sql, filter_condition)
    
    # Values patterns
    elif pattern_name == "ToMultiSet":
        # Call with the exact same signature as original implementation
        from_clause, where_conditions, joins, variable_mappings = await translate_values_pattern(pattern, context.table_config, context.alias_generator, projected_vars)
        return SQLComponents(from_clause, where_conditions, joins, variable_mappings)
    elif pattern_name == "Values":
        # Call with the exact same signature as original implementation
        from_clause, where_conditions, joins, variable_mappings = await translate_values_pattern(pattern, context.table_config, context.alias_generator, projected_vars)
        return SQLComponents(from_clause, where_conditions, joins, variable_mappings)
    
    # Bind patterns
    elif pattern_name == "Extend":
        logger.debug(f"Processing Extend pattern - BIND variable: {pattern.var}, expression: {pattern.expr}")
        logger.debug(f"Extend pattern nested pattern: {getattr(pattern.p, 'name', 'Unknown')}")
        
        bind_var = pattern.var
        bind_expr = pattern.expr
        
        # CRITICAL FIX: Extract all variables referenced in the BIND expression
        # This ensures variables used in BIND expressions are properly mapped
        # (ported from original implementation)
        extended_projected_vars = list(projected_vars) if projected_vars else []
        
        # Add the BIND variable if not already included
        if bind_var not in extended_projected_vars:
            extended_projected_vars.append(bind_var)
        
        # Extract all variables referenced in the BIND expression
        bind_expr_vars = _extract_variables_from_expression(bind_expr)
        for var in bind_expr_vars:
            if var not in extended_projected_vars:
                extended_projected_vars.append(var)
                logger.debug(f"Added BIND expression variable {var} to projected_vars")
        
        # Translate the nested pattern first with extended projection
        base_sql = await translate_algebra_pattern(pattern.p, context, extended_projected_vars)
        logger.debug(f"Extend recursion returned {len(base_sql.variable_mappings)} variables: {list(base_sql.variable_mappings.keys())}")
        
        # Debug: Log all available variable mappings before BIND translation
        logger.debug(f"Variable mappings available for BIND {bind_var}: {list(base_sql.variable_mappings.keys())}")
        
        # Translate the BIND expression to SQL
        try:
            from .postgresql_sparql_expressions import translate_bind_expression
            sql_expr = translate_bind_expression(bind_expr, base_sql.variable_mappings)
            
            # CRITICAL FIX: Check for unmapped variables and log warnings
            if 'UNMAPPED_' in sql_expr:
                logger.warning(f"BIND expression contains unmapped variables: {sql_expr}")
                logger.warning(f"Available variable mappings: {list(base_sql.variable_mappings.keys())}")
                # Still set the mapping but log the issue
            
            logger.debug(f"✅ Translated BIND expression to SQL: {sql_expr}")
            
        except Exception as expr_error:
            logger.warning(f"Failed to translate BIND expression for {bind_var}: {expr_error}")
            logger.warning(f"Available mappings were: {list(base_sql.variable_mappings.keys())}")
            # Fall back to placeholder to avoid query failure
            sql_expr = f"'BIND_FAILED_{bind_var}'"
        
        # Use flat structure like original - just add BIND variable to mappings
        updated_mappings = base_sql.variable_mappings.copy()
        updated_mappings[bind_var] = sql_expr
        logger.debug(f"✅ Added BIND variable {bind_var} -> {sql_expr} to mappings")
        logger.debug(f"Final Extend mappings ({len(updated_mappings)}): {list(updated_mappings.keys())}")
        
        return SQLComponents(
            from_clause=base_sql.from_clause,
            where_conditions=base_sql.where_conditions,
            joins=base_sql.joins,
            variable_mappings=updated_mappings
        )
    
    # AggregateJoin patterns (for aggregation functions like COUNT, SUM, etc.)
    elif pattern_name == "AggregateJoin":
        logger.debug(f"Processing AggregateJoin pattern with aggregates: {pattern.A}")
        
        # CRITICAL FIX: Extract all aggregate input variables and ensure they're included in projected_vars
        # This matches the original implementation's approach for proper SQL column mappings
        aggregate_input_vars = set()
        for agg in pattern.A:
            if hasattr(agg, 'vars') and agg.vars:
                aggregate_input_vars.add(agg.vars)
        
        # Combine original projected_vars with aggregate input variables
        extended_projected_vars = list(projected_vars) if projected_vars else []
        for var in aggregate_input_vars:
            if var not in extended_projected_vars:
                extended_projected_vars.append(var)
                logger.debug(f"Added aggregate input variable {var} to projected_vars")
        
        logger.debug(f"Extended projected_vars for aggregates: {extended_projected_vars}")
        
        base_sql = await translate_algebra_pattern(pattern.p, context, extended_projected_vars)
        logger.debug(f"AggregateJoin base SQL has {len(base_sql.variable_mappings)} variables: {list(base_sql.variable_mappings.keys())}")
        
        # Process aggregation functions
        for aggregate in pattern.A:
            agg_name = aggregate.name if hasattr(aggregate, 'name') else str(type(aggregate).__name__)
            agg_var = aggregate.vars  # Input variable (e.g., ?person)
            result_var = aggregate.res  # Result variable (e.g., __agg_1__)
            
            logger.debug(f"Processing aggregate {agg_name}: {agg_var} -> {result_var}")
            
            # Handle different aggregate types
            # CRITICAL FIX: Handle both "Aggregate_Count_" and "Aggregate_Count" formats like original
            if agg_name in ["Aggregate_Count_", "Aggregate_Count"]:
                if hasattr(agg, 'distinct') and agg.distinct:
                    # COUNT(DISTINCT ?var)
                    if agg_var in base_sql.variable_mappings:
                        sql_expr = f"COUNT(DISTINCT {base_sql.variable_mappings[agg_var]})"
                    else:
                        # COUNT(DISTINCT *) is invalid SQL - use a specific column instead
                        sql_expr = "COUNT(*)"
                        logger.warning(f"COUNT(DISTINCT) without mapped variable - using COUNT(*) as fallback")
                else:
                    # COUNT(?var) or COUNT(*)
                    if agg_var in base_sql.variable_mappings:
                        sql_expr = f"COUNT({base_sql.variable_mappings[agg_var]})"
                    else:
                        sql_expr = "COUNT(*)"
                        
            elif agg_name in ["Aggregate_Sum_", "Aggregate_Sum"]:
                if agg_var in base_sql.variable_mappings:
                    sql_expr = f"SUM(CAST({base_sql.variable_mappings[agg_var]} AS DECIMAL))"
                else:
                    sql_expr = f"'UNMAPPED_SUM_{agg_var}'"
                    
            elif agg_name in ["Aggregate_Avg_", "Aggregate_Avg"]:
                if agg_var in base_sql.variable_mappings:
                    sql_expr = f"AVG(CAST({base_sql.variable_mappings[agg_var]} AS DECIMAL))"
                else:
                    sql_expr = f"'UNMAPPED_AVG_{agg_var}'"
                    
            elif agg_name in ["Aggregate_Min_", "Aggregate_Min"]:
                if agg_var in base_sql.variable_mappings:
                    sql_expr = f"MIN({base_sql.variable_mappings[agg_var]})"
                else:
                    sql_expr = f"'UNMAPPED_MIN_{agg_var}'"
                    
            elif agg_name in ["Aggregate_Max_", "Aggregate_Max"]:
                if agg_var in base_sql.variable_mappings:
                    sql_expr = f"MAX({base_sql.variable_mappings[agg_var]})"
                else:
                    sql_expr = f"'UNMAPPED_MAX_{agg_var}'"
                    
            elif agg_name in ["Aggregate_Sample_", "Aggregate_Sample"]:
                # Sample is used for GROUP BY non-aggregated variables
                if agg_var in base_sql.variable_mappings:
                    sql_expr = base_sql.variable_mappings[agg_var]
                else:
                    sql_expr = f"'UNMAPPED_SAMPLE_{agg_var}'"
                    
            else:
                logger.warning(f"Unknown aggregate function: {agg_name}")
                sql_expr = f"'UNKNOWN_AGG_{agg_name}'"
            
            # Map the result variable to the SQL expression
            base_sql.variable_mappings[result_var] = sql_expr
            logger.debug(f"Mapped {result_var} -> {sql_expr}")
        
        logger.debug(f"AggregateJoin returning {len(base_sql.variable_mappings)} variables: {base_sql.variable_mappings}")
        return base_sql
    
    # Group patterns (GROUP BY)
    elif pattern_name == "Group":
        logger.debug(f"Processing Group pattern")
        logger.debug(f"Group pattern details: {pattern}")
        if hasattr(pattern, 'p'):
            inner_pattern = pattern.p
            inner_name = getattr(inner_pattern, 'name', str(type(inner_pattern).__name__))
            logger.debug(f"Group has inner pattern: {inner_name}")
        base_sql = await translate_algebra_pattern(pattern.p, context, projected_vars)
        logger.debug(f"Group base SQL has {len(base_sql.variable_mappings)} variables: {list(base_sql.variable_mappings.keys())}")
        
        # Store GROUP BY information like the original implementation
        group_expr = getattr(pattern, 'expr', None)
        if group_expr:
            logger.debug(f"GROUP BY variables: {group_expr}")
            # Store the GROUP BY variables for later SQL generation
            updated_mappings = base_sql.variable_mappings.copy()
            updated_mappings['__GROUP_BY_VARS__'] = group_expr
            logger.debug(f"Stored GROUP BY variables: {group_expr}")
            
            return SQLComponents(
                from_clause=base_sql.from_clause,
                where_conditions=base_sql.where_conditions,
                joins=base_sql.joins,
                variable_mappings=updated_mappings
            )
        else:
            logger.debug("No GROUP BY variables (aggregate without grouping)")
            return base_sql
    
    # Subquery patterns
    elif pattern_name == "SubSelect":
        # Recursively translate subquery
        subquery_sql = await translate_algebra_pattern(pattern.query, context, projected_vars)
        subquery_alias = context.alias_generator.next_subquery_alias()
        
        return SQLComponents(
            from_clause=f"({subquery_sql.from_clause}) AS {subquery_alias}",
            where_conditions=subquery_sql.where_conditions,
            joins=subquery_sql.joins,
            variable_mappings=subquery_sql.variable_mappings
        )
    
    # OrderBy patterns (ORDER BY) - transparent wrapper like original implementation
    elif pattern_name == "OrderBy":
        logger.debug(f"🔄 Processing OrderBy pattern, recursing into nested pattern")
        # OrderBy wraps another pattern - drill down to the nested pattern
        nested_pattern = pattern.p
        nested_pattern_name = getattr(nested_pattern, 'name', str(type(nested_pattern).__name__))
        logger.debug(f"🔄 OrderBy nested pattern: {nested_pattern_name}")
        
        try:
            inner_sql = await translate_algebra_pattern(nested_pattern, context, projected_vars)
            logger.debug(f"✅ OrderBy recursion returned: {len(inner_sql.variable_mappings)} variables: {list(inner_sql.variable_mappings.keys())}")
            # The ORDER BY clause will be handled at the query building level
            return inner_sql
        except Exception as e:
            logger.error(f"❌ OrderBy recursion failed: {e}")
            import traceback
            logger.error(f"❌ OrderBy recursion traceback: {traceback.format_exc()}")
            raise
    
    # Slice patterns (LIMIT/OFFSET)
    elif pattern_name == "Slice":
        logger.debug(f"Processing Slice pattern, recursing into inner pattern")
        # Recursively translate the inner pattern
        inner_sql = await translate_algebra_pattern(pattern.p, context, projected_vars)
        logger.debug(f"Slice recursion returned: {len(inner_sql.variable_mappings)} variables")
        # The LIMIT/OFFSET will be handled at the query building level
        # For now, just return the inner SQL components
        return inner_sql
    
    # Project patterns (SELECT clause variable projection)
    elif pattern_name == "Project":
        logger.debug(f"Processing Project pattern, recursing into inner pattern")
        # Recursively translate the inner pattern
        inner_sql = await translate_algebra_pattern(pattern.p, context, projected_vars)
        logger.debug(f"Project recursion returned: {len(inner_sql.variable_mappings)} variables")
        # The variable projection will be handled at the query building level
        # For now, just return the inner SQL components
        return inner_sql
    
    # Graph patterns (GRAPH clause)
    elif pattern_name == "Graph":
        logger.debug(f"🔍 Processing Graph pattern")
        # Get the graph term and nested pattern
        graph_term = getattr(pattern, 'term', None)
        nested_pattern = pattern.p
        
        logger.debug(f"Graph term: {graph_term} (type: {type(graph_term)}), nested pattern: {getattr(nested_pattern, 'name', type(nested_pattern).__name__)}")
        
        # Check if this is a variable graph or fixed URI graph
        if isinstance(graph_term, Variable):
            # Variable graph - GRAPH ?var { ... }
            logger.debug(f"🔍 Processing variable graph: {graph_term}")
            
            # First translate the inner pattern
            nested_sql = await translate_algebra_pattern(nested_pattern, context, projected_vars)
            
            # Add graph variable to projected variables if needed
            if projected_vars is None or graph_term in projected_vars:
                # Create JOIN to term table for graph variable
                context_term_alias = context.alias_generator.next_term_alias('g')
                
                # Extract quad aliases from the nested SQL to add context JOINs
                quad_aliases = []
                if nested_sql.from_clause:
                    # Extract quad table aliases from FROM clause
                    import re
                    quad_matches = re.findall(r'\b(q\d+)\b', nested_sql.from_clause)
                    quad_aliases.extend(quad_matches)
                
                # Add context term JOIN for the first quad table
                if quad_aliases:
                    first_quad_alias = quad_aliases[0]
                    context_join = f"JOIN {table_config.term_table} {context_term_alias} ON {first_quad_alias}.context_uuid = {context_term_alias}.term_uuid"
                    
                    # For additional quad tables, ensure they have the same context
                    additional_conditions = []
                    for quad_alias in quad_aliases[1:]:
                        additional_conditions.append(f"{quad_alias}.context_uuid = {first_quad_alias}.context_uuid")
                    
                    # Create new SQL components with graph variable mapping
                    new_variable_mappings = dict(nested_sql.variable_mappings)
                    new_variable_mappings[graph_term] = f"{context_term_alias}.term_text"
                    
                    logger.debug(f"✅ Mapped graph variable {graph_term} to {context_term_alias}.term_text")
                    
                    return SQLComponents(
                        from_clause=nested_sql.from_clause,
                        where_conditions=nested_sql.where_conditions + additional_conditions,
                        joins=nested_sql.joins + [context_join],
                        variable_mappings=new_variable_mappings
                    )
                else:
                    logger.warning(f"No quad aliases found for variable graph {graph_term}")
                    return nested_sql
            else:
                # Graph variable not projected - no additional JOINs needed
                logger.debug(f"Graph variable {graph_term} not projected - no JOINs added")
                return nested_sql
        
        else:
            # Fixed URI graph - GRAPH <uri> { ... }
            # Convert graph URI to string if it's a URIRef
            if hasattr(graph_term, '__str__'):
                graph_uri_str = str(graph_term)
            else:
                graph_uri_str = graph_term
                
            logger.debug(f"🔍 Processing fixed URI graph: {graph_uri_str}")
            
            # EXACT logic from original implementation _translate_graph method
            # Named graph - resolve URI to UUID
            logger.debug(f"Processing named graph: {graph_uri_str}")
            graph_text = graph_uri_str
            graph_type = 'U'  # URI type
            graph_terms = [(graph_text, graph_type)]
            
            # Get term UUID for the graph URI - exact logic from original
            graph_key = (graph_text, graph_type)
            
            if context.term_cache and context.space_impl:
                # Use term cache if available - check cache first
                cached_results = context.term_cache.get_batch(graph_terms)
                if graph_key in cached_results:
                    graph_uuid_mappings = cached_results
                else:
                    # Need to query database and update cache
                    graph_uuid_mappings = await _get_term_uuids_from_db(graph_terms, context.table_config, context.space_impl)
                    context.term_cache.put_batch(graph_uuid_mappings)
            else:
                # Fallback to direct DB query
                graph_uuid_mappings = await _get_term_uuids_from_db(graph_terms, context.table_config, context.space_impl)
            # First translate the nested pattern, then apply graph constraints
            nested_sql = await translate_algebra_pattern(nested_pattern, context, projected_vars)
            
            # Apply graph context constraints using the fixed translate_graph_pattern function
            return await translate_graph_pattern(nested_sql, graph_uri_str, context.table_config, context)
    
    # Property path patterns
    elif hasattr(pattern, 'path'):
        # TODO: Implement property path translation
        logger.warning(f"Property path pattern not fully implemented: {pattern}")
        # For now, treat as simple triple pattern
        if hasattr(pattern, 'subject') and hasattr(pattern, 'object'):
            triples = [(pattern.subject, pattern.path, pattern.object)]
            return generate_bgp_sql(triples, table_config, alias_gen)
    
    # Fallback for unknown patterns
    else:
        logger.error(f"❌ UNKNOWN PATTERN FALLBACK: {pattern_name}, pattern: {pattern}")
        logger.error(f"❌ Available pattern handlers: BGP, Join, Union, LeftJoin, Minus, Filter, Extend, AggregateJoin, Group, OrderBy, Slice, Project")
        # Try to extract triples if available
        if hasattr(pattern, 'triples'):
            return generate_bgp_sql(pattern.triples, table_config, alias_gen)
        else:
            # Return empty SQL components
            return SQLComponents(
                from_clause="",
                where_conditions=[],
                joins=[],
                variable_mappings={}
            )


async def _translate_pattern_with_context(pattern, context: TranslationContext,
                                         projected_vars: Optional[List[Variable]] = None, 
                                         context_constraint: str = None) -> SQLComponents:
    """
    Translate any pattern with additional context constraint - exact logic from original implementation.
    
    Args:
        pattern: The SPARQL pattern to translate
        context: TranslationContext with shared state (alias_gen, term_cache, etc.)
        projected_vars: Variables to project in SELECT clause
        context_constraint: SQL constraint for context_uuid column
        
    Returns:
        SQLComponents with context constraint applied
    """
    pattern_name = pattern.name
    
    if pattern_name == "BGP":
        # BGP with context constraint - exact logic from original
        triples = getattr(pattern, 'triples', [])
        if context.term_cache:
            return await generate_bgp_sql_with_cache(triples, context.table_config, context.alias_generator, projected_vars, context.term_cache, context.space_impl, context_constraint)
        else:
            return generate_bgp_sql(triples, context.table_config, context.alias_generator, projected_vars, context_constraint)
    elif pattern_name == "Filter":
        # Handle filter with context constraint - exact logic from original
        inner_pattern = pattern['p']
        inner_sql = await _translate_pattern_with_context(inner_pattern, context, projected_vars, context_constraint)
        
        # Add filter conditions
        filter_expr = pattern['expr']
        filter_sql = await translate_filter_expression(filter_expr, inner_sql.variable_mappings)
        if filter_sql:
            where_conditions = inner_sql.where_conditions + [filter_sql]
        else:
            where_conditions = inner_sql.where_conditions
        
        return SQLComponents(
            from_clause=inner_sql.from_clause,
            where_conditions=where_conditions,
            joins=inner_sql.joins,
            variable_mappings=inner_sql.variable_mappings
        )
    else:
        # For other patterns, fall back to regular translation and add context constraint - exact logic from original
        pattern_sql = await translate_algebra_pattern(pattern, context, projected_vars)
        if context_constraint:
            # CRITICAL FIX: Special handling for UNION patterns
            # Context constraints cannot be applied to UNION patterns after they're formed
            # because the individual branch aliases (q0, q1) are not accessible
            if pattern.name == "Union":
                # For UNION patterns, context constraints must be applied within each branch
                # This should have been handled during the UNION translation itself
                # Return the UNION SQL as-is since constraints should already be applied
                return pattern_sql
            else:
                # Extract quad aliases from FROM clause and JOINs to apply context constraint
                quad_aliases = _extract_quad_aliases_from_sql(pattern_sql.from_clause, pattern_sql.joins)
                additional_where = []
                for quad_alias in quad_aliases:
                    additional_where.append(f"{quad_alias}.{context_constraint}")
                
                return SQLComponents(
                    from_clause=pattern_sql.from_clause,
                    where_conditions=pattern_sql.where_conditions + additional_where,
                    joins=pattern_sql.joins,
                    variable_mappings=pattern_sql.variable_mappings
                )
        return pattern_sql


def _extract_quad_aliases_from_sql(from_clause: str, joins: List[str]) -> List[str]:
    """
    Extract quad table aliases from SQL FROM clause and JOINs - exact logic from original implementation.
    
    Args:
        from_clause: SQL FROM clause
        joins: List of JOIN clauses
        
    Returns:
        List of quad table aliases
    """
    import re
    quad_aliases = []
    
    # Extract from FROM clause
    if from_clause:
        quad_matches = re.findall(r'\b(q\d+|\w*_q\d+)\b', from_clause)
        quad_aliases.extend(quad_matches)
    
    # Extract from JOINs
    for join in joins:
        quad_matches = re.findall(r'\b(q\d+|\w*_q\d+)\b', join)
        for alias in quad_matches:
            if alias not in quad_aliases:
                quad_aliases.append(alias)
    
    return quad_aliases


async def orchestrate_sparql_update(space_impl: PostgreSQLSpaceImpl, space_id: str, 
                                  sparql_update: str) -> bool:
    """
    Orchestrate the execution of a SPARQL 1.1 UPDATE operation using modular functions.
    
    Args:
        space_impl: PostgreSQL space implementation
        space_id: The space identifier
        sparql_update: SPARQL UPDATE query string
        
    Returns:
        True if update was successful, False otherwise
    """
    try:
        # Validate space exists
        PostgreSQLUtils.validate_space_id(space_id)
        
        logger.info(f"Orchestrating SPARQL update in space '{space_id}'")
        logger.debug(f"Update: {sparql_update}")
        
        # Get table configuration
        table_config = create_table_config(space_impl, space_id)
        
        # Parse and determine update operation type
        update_type = determine_update_type(sparql_update)
        
        # Execute update using appropriate modular function
        success = await execute_update_operation(space_impl, space_id, sparql_update, update_type, table_config)
        
        if success:
            logger.info(f"SPARQL update executed successfully")
        else:
            logger.warning(f"SPARQL update completed with warnings")
            
        return success
        
    except Exception as e:
        logger.error(f"Error orchestrating SPARQL update: {e}")
        raise


def determine_update_type(sparql_update: str) -> str:
    """
    Determine the type of SPARQL update operation.
    
    Args:
        sparql_update: SPARQL update string
        
    Returns:
        Update operation type
    """
    update_upper = sparql_update.upper().strip()
    
    if "INSERT DATA" in update_upper:
        return "INSERT_DATA"
    elif "DELETE DATA" in update_upper:
        return "DELETE_DATA"
    elif "DELETE" in update_upper and "INSERT" in update_upper:
        return "MODIFY"
    elif "DELETE" in update_upper and "WHERE" in update_upper:
        return "DELETE_WHERE"
    elif "INSERT" in update_upper and "WHERE" in update_upper:
        return "INSERT_WHERE"
    elif "LOAD" in update_upper:
        return "LOAD"
    elif "CLEAR" in update_upper:
        return "CLEAR"
    elif "CREATE" in update_upper:
        return "CREATE"
    elif "DROP" in update_upper:
        return "DROP"
    elif "COPY" in update_upper:
        return "COPY"
    elif "MOVE" in update_upper:
        return "MOVE"
    elif "ADD" in update_upper:
        return "ADD"
    else:
        raise ValueError(f"Unsupported SPARQL update operation: {sparql_update[:100]}...")


async def execute_update_operation(space_impl: PostgreSQLSpaceImpl, space_id: str, 
                                 sparql_update: str, update_type: str, 
                                 table_config: TableConfig) -> bool:
    """
    Execute SPARQL update operations using modular functions.
    
    Args:
        space_impl: PostgreSQL space implementation
        space_id: Space identifier
        sparql_update: SPARQL update string
        update_type: Type of update operation
        table_config: Table configuration
        
    Returns:
        True if successful, False otherwise
    """
    try:
        if update_type == "INSERT_DATA":
            return await translate_insert_data(space_id, sparql_update, table_config, space_impl)
        elif update_type == "DELETE_DATA":
            return await translate_delete_data(space_id, sparql_update, table_config, space_impl)
        elif update_type == "MODIFY":
            return await translate_modify_operation(space_id, sparql_update, table_config, space_impl)
        elif update_type == "LOAD":
            return await translate_load_operation(space_id, sparql_update, table_config, space_impl)
        elif update_type == "CLEAR":
            return await translate_clear_operation(space_id, sparql_update, table_config, space_impl)
        elif update_type == "CREATE":
            return await translate_create_operation(space_id, sparql_update, table_config, space_impl)
        elif update_type == "DROP":
            return await translate_drop_operation(space_id, sparql_update, table_config, space_impl)
        elif update_type == "COPY":
            return await translate_copy_operation(space_id, sparql_update, table_config, space_impl)
        elif update_type == "MOVE":
            return await translate_move_operation(space_id, sparql_update, table_config, space_impl)
        elif update_type == "ADD":
            return await translate_add_operation(space_id, sparql_update, table_config, space_impl)
        else:
            raise ValueError(f"Unsupported update type: {update_type}")
            
    except Exception as e:
        logger.error(f"Error executing {update_type} operation: {e}")
        return False


async def execute_sql_query(space_impl: PostgreSQLSpaceImpl, sql_query: str) -> List[Dict[str, Any]]:
    """
    Execute SQL query against the database.
    
    Args:
        space_impl: PostgreSQL space implementation
        sql_query: SQL query string
        
    Returns:
        List of result dictionaries
    """
    try:
        logger.debug(f"Executing SQL query: {sql_query[:200]}...")
        
        # Use space_impl's connection to execute the query (matching original implementation)
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
                            # Row is already a dictionary
                            results.append(row)
                        else:
                            # Row is a tuple/list - convert to dictionary
                            result_dict = {}
                            for i, value in enumerate(row):
                                if i < len(columns):
                                    result_dict[columns[i]] = value
                            results.append(result_dict)
                else:
                    # For non-SELECT operations, return empty list
                    results = []
        
        logger.debug(f"SQL query returned {len(results)} results")
        return results
        
    except Exception as e:
        logger.error(f"Error executing SQL query: {e}")
        raise


async def process_construct_results(sql_results: List[Dict[str, Any]], 
                                  construct_template: List) -> List[Dict[str, Any]]:
    """
    Process SQL results for CONSTRUCT queries to build RDF graph.
    
    Args:
        sql_results: SQL query results
        construct_template: CONSTRUCT template from query algebra
        
    Returns:
        List of RDF triple dictionaries
    """
    # TODO: Implement CONSTRUCT result processing using modular functions
    # This would use functions from postgresql_sparql_queries module
    logger.debug(f"Processing CONSTRUCT results: {len(sql_results)} rows")
    
    # Placeholder implementation - return empty list for now
    return []


async def process_describe_results(sql_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Process SQL results for DESCRIBE queries.
    
    Args:
        sql_results: SQL query results
        
    Returns:
        List of RDF triple dictionaries
    """
    # TODO: Implement DESCRIBE result processing using modular functions
    # This would use functions from postgresql_sparql_queries module
    logger.debug(f"Processing DESCRIBE results: {len(sql_results)} rows")
    
    # Placeholder implementation - return empty list for now
    return []


async def _get_term_uuids_from_db(graph_terms: List[Tuple[str, str]], table_config: TableConfig, space_impl) -> Dict[Tuple[str, str], str]:
    """
    Get term UUIDs from database - exact logic from original implementation.
    
    Args:
        graph_terms: List of (term_text, term_type) tuples
        table_config: Table configuration
        space_impl: Space implementation for database operations
        
    Returns:
        Dictionary mapping (term_text, term_type) to UUID
    """
    if not graph_terms or not space_impl:
        return {}
    
    try:
        # Build optimized batch query using exact logic from original _get_term_uuids_batch
        if len(graph_terms) == 1:
            # Single term - use simple equality for better readability
            term_text, term_type = graph_terms[0]
            escaped_text = term_text.replace("'", "''")
            batch_query = f"""
                SELECT term_text, term_type, term_uuid 
                FROM {table_config.term_table} 
                WHERE term_text = '{escaped_text}' AND term_type = '{term_type}'
            """
        else:
            # Multiple terms - use IN clause with VALUES for better performance
            values_list = []
            for term_text, term_type in graph_terms:
                escaped_text = term_text.replace("'", "''")
                values_list.append(f"('{escaped_text}', '{term_type}')")
            
            batch_query = f"""
                SELECT t.term_text, t.term_type, t.term_uuid 
                FROM {table_config.term_table} t
                INNER JOIN (VALUES {', '.join(values_list)}) AS v(term_text, term_type)
                    ON t.term_text = v.term_text AND t.term_type = v.term_type
            """
        
        # Execute batch query using space_impl connection - exact logic from original _execute_sql_query
        term_uuid_mappings = {}
        with space_impl.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(batch_query)
                
                # Get column names
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                
                # Fetch all results
                rows = cursor.fetchall()
                
                # Convert to list of dictionaries - exact logic from original
                db_results = []
                for row in rows:
                    if isinstance(row, dict):
                        # Row is already a dictionary
                        db_results.append(row)
                    else:
                        # Row is a tuple/list - convert to dictionary
                        result_dict = {}
                        for i, value in enumerate(row):
                            if i < len(columns):
                                result_dict[columns[i]] = value
                        db_results.append(result_dict)
                
                # Process database results - exact logic from original
                for row in db_results:
                    key = (row['term_text'], row['term_type'])
                    uuid = row['term_uuid']
                    term_uuid_mappings[key] = uuid
        
        logger.debug(f"Retrieved {len(term_uuid_mappings)} term UUIDs from database")
        return term_uuid_mappings
        
    except Exception as e:
        logger.error(f"Error querying term UUIDs from database: {e}")
        return {}


async def get_term_uuids_batch(space_impl: PostgreSQLSpaceImpl, 
                             terms: List[Tuple[str, str]], 
                             table_config: TableConfig,
                             term_cache: Optional[PostgreSQLTermCache] = None) -> Dict[Tuple[str, str], str]:
    """
    Helper function to get term UUIDs for multiple terms using cache and batch database lookup.
    
    Args:
        space_impl: PostgreSQL space implementation
        terms: List of (term_text, term_type) tuples
        table_config: Table configuration for database queries
        term_cache: Optional term cache for performance
        
    Returns:
        Dictionary mapping (term_text, term_type) to term_uuid
    """
    if not terms:
        return {}
    
    # Initialize result dictionary
    result = {}
    uncached_terms = terms
    
    # First, check cache for all terms if cache is provided
    if term_cache:
        cached_results = term_cache.get_batch(terms)
        result.update(cached_results)
        
        # Find terms that need database lookup
        cached_keys = set(cached_results.keys())
        uncached_terms = [term for term in terms if term not in cached_keys]
    
    # Batch lookup uncached terms from database
    if uncached_terms:
        logger.debug(f"Batch database lookup for {len(uncached_terms)} uncached terms")
        
        # Use core function for batch term lookup
        batch_sql = generate_term_lookup_sql(uncached_terms, table_config)
        db_results = await execute_sql_query(space_impl, batch_sql)
        
        # Process database results and update cache
        for row in db_results:
            term_key = (row['term_text'], row['term_type'])
            term_uuid = row['term_uuid']
            result[term_key] = term_uuid
            
            # Update cache if provided
            if term_cache:
                term_cache.put_term_uuid(term_key, term_uuid)
    
    return result


async def initialize_graph_cache(space_impl: PostgreSQLSpaceImpl, space_id: str) -> set:
    """
    Initialize graph cache for the specified space.
    
    Args:
        space_impl: PostgreSQL space implementation
        space_id: Space identifier
        
    Returns:
        Set of graph URIs in the space
    """
    logger.debug(f"Initializing graph cache for space '{space_id}'")
    
    # Query all graphs in the space
    table_config = create_table_config(space_impl, space_id)
    graph_query = f"SELECT DISTINCT graph_uri FROM {table_config.graph_table}"
    
    try:
        graph_results = await execute_sql_query(space_impl, graph_query)
        graph_uris = {row['graph_uri'] for row in graph_results}
        logger.debug(f"Cached {len(graph_uris)} graphs for space '{space_id}'")
        return graph_uris
    except Exception as e:
        logger.warning(f"Could not initialize graph cache for space '{space_id}': {e}")
        return set()


# Wrapper functions for backward compatibility with postgres_sparql_impl.py imports

async def execute_sparql_query(space_impl: PostgreSQLSpaceImpl, space_id: str, 
                              sparql_query: str, term_cache: Optional[PostgreSQLTermCache] = None,
                              graph_cache: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """
    Wrapper function for orchestrate_sparql_query to maintain import compatibility.
    
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
    return await orchestrate_sparql_query(space_impl, space_id, sparql_query, term_cache, graph_cache)


async def execute_sparql_update(space_impl: PostgreSQLSpaceImpl, space_id: str, 
                               sparql_update: str) -> bool:
    """
    Wrapper function for orchestrate_sparql_update to maintain import compatibility.
    
    Args:
        space_impl: PostgreSQL space implementation
        space_id: The space identifier
        sparql_update: SPARQL UPDATE query string
        
    Returns:
        bool: True if update was successful
    """
    return await orchestrate_sparql_update(space_impl, space_id, sparql_update)


async def batch_lookup_term_uuids(space_impl: PostgreSQLSpaceImpl, 
                                 terms: List[Tuple[str, str]], 
                                 table_config: TableConfig,
                                 term_cache: Optional[PostgreSQLTermCache] = None) -> Dict[Tuple[str, str], str]:
    """
    Wrapper function for get_term_uuids_batch to maintain import compatibility.
    
    Args:
        space_impl: PostgreSQL space implementation
        terms: List of (term_text, term_type) tuples
        table_config: Table configuration for database queries
        term_cache: Optional term cache for performance
        
    Returns:
        Dictionary mapping (term_text, term_type) to term_uuid
    """
    return await get_term_uuids_batch(space_impl, terms, table_config, term_cache)
