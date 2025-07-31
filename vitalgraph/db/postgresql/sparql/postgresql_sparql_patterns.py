"""
PostgreSQL SPARQL Patterns Functions for VitalGraph

This module provides pure functions for translating SPARQL algebra patterns
(BGP, UNION, OPTIONAL, MINUS, JOIN, BIND, VALUES, subqueries) to SQL components.
No inter-dependencies with other SPARQL modules - only imports utilities.
"""

import logging
from typing import Dict, List, Tuple, Set, Optional, Any, Union
from rdflib import Variable, URIRef, Literal, BNode

# Import only from core module and utilities
from .postgresql_sparql_core import SQLComponents, AliasGenerator, TableConfig, SparqlContext, SparqlUtils
from .postgresql_sparql_cache_integration import generate_bgp_sql_with_cache

logger = logging.getLogger(__name__)


async def translate_union_pattern(left_sql: SQLComponents, right_sql: SQLComponents, 
                          alias_gen: AliasGenerator, *, sparql_context: SparqlContext = None) -> SQLComponents:
    """
    Translate UNION pattern to SQL UNION operations - exact logic ported from original implementation.
    
    This is a complete port of the original PostgreSQLSparqlImpl._translate_union method
    to ensure 100% functional parity and fix the failing test cases.
    
    Args:
        left_sql: SQL components for left operand
        right_sql: SQL components for right operand
        alias_gen: Alias generator for consistent naming
        sparql_context: Optional SparqlContext for logging and state
        
    Returns:
        SQLComponents with UNION SQL structure
    """
    function_name = "translate_union_pattern"
    
    # Use SparqlContext for logging if available, otherwise fallback
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, 
                                         left_vars=list(left_sql.variable_mappings.keys()),
                                         right_vars=list(right_sql.variable_mappings.keys()))
    else:
        # Import logger for fallback
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"🔗 {function_name}: Starting UNION pattern translation")
    
    # Determine all variables that appear in either branch - exact logic from original
    all_variables = set(left_sql.variable_mappings.keys()) | set(right_sql.variable_mappings.keys())
    logger.debug(f"All variables in UNION: {[str(v) for v in all_variables]}")
    
    # Build SELECT clauses for both branches with consistent variable ordering - exact logic from original
    variable_list = sorted(all_variables, key=str)  # Consistent ordering
    
    left_select_items = []
    right_select_items = []
    final_variable_mappings = {}
    
    for i, var in enumerate(variable_list):
        col_name = f"var_{i}"  # Use consistent column names
        final_variable_mappings[var] = col_name
        
        # Left branch: use mapping if available, otherwise NULL - exact logic from original
        if var in left_sql.variable_mappings:
            left_mapping = left_sql.variable_mappings[var]
            left_select_items.append(f"{left_mapping} AS {col_name}")
            # Debug BIND expressions in UNION
            if "'" in left_mapping and left_mapping.startswith("'") and left_mapping.endswith("'"):
                logger.debug(f"UNION Left: BIND literal {var} -> {left_mapping}")
        else:
            left_select_items.append(f"NULL AS {col_name}")
        
        # Right branch: use mapping if available, otherwise NULL - exact logic from original
        if var in right_sql.variable_mappings:
            right_mapping = right_sql.variable_mappings[var]
            right_select_items.append(f"{right_mapping} AS {col_name}")
            # Debug BIND expressions in UNION
            if "'" in right_mapping and right_mapping.startswith("'") and right_mapping.endswith("'"):
                logger.debug(f"UNION Right: BIND literal {var} -> {right_mapping}")
        else:
            right_select_items.append(f"NULL AS {col_name}")
    
    # Build left branch SQL - EXACT logic ported from original implementation
    left_from = left_sql.from_clause
    
    if left_from and left_from.strip().startswith('FROM (') and 'UNION' in left_from:
        # left_from is already a complete UNION derived table - use it directly
        # Extract the SQL content between FROM ( and ) alias - exact logic from original
        start_idx = left_from.find('FROM (') + 6  # Skip 'FROM ('
        
        # Find the matching closing parenthesis (accounting for nested parentheses)
        paren_count = 1
        end_idx = start_idx
        while end_idx < len(left_from) and paren_count > 0:
            if left_from[end_idx] == '(':
                paren_count += 1
            elif left_from[end_idx] == ')':
                paren_count -= 1
            end_idx += 1
        
        # Extract the raw UNION SQL (without the outer FROM ( and ) alias)
        left_sql_content = left_from[start_idx:end_idx-1]  # -1 to exclude the closing )
        # No need to add joins/where since it's already a complete UNION
    else:
        # Normal case - build SELECT statement - EXACT logic from original
        left_sql_parts = [f"SELECT {', '.join(left_select_items)}"]
        if left_from:
            if not left_from.strip().upper().startswith('FROM'):
                # If from_clause doesn't start with FROM, it's just a table reference
                left_sql_parts.append(f"FROM {left_from}")
            else:
                # from_clause already includes FROM keyword
                left_sql_parts.append(left_from)
        else:
            # No FROM clause - this shouldn't happen but handle gracefully
            left_sql_parts.append(f"FROM quad_table fallback_q0")
            logger.warning("Left branch missing FROM clause, using fallback")
        
        # Add joins and where conditions for normal case - exact logic from original
        if left_sql.joins:
            left_sql_parts.extend(left_sql.joins)
        if left_sql.where_conditions:
            left_sql_parts.append(f"WHERE {' AND '.join(left_sql.where_conditions)}")
        
        left_sql_content = '\n'.join(left_sql_parts)
    
    # Build right branch SQL - EXACT logic ported from original implementation
    right_sql_parts = [f"SELECT {', '.join(right_select_items)}"]
    right_from = right_sql.from_clause
    if right_from:
        if not right_from.strip().upper().startswith('FROM'):
            # If from_clause doesn't start with FROM, it's just a table reference
            right_sql_parts.append(f"FROM {right_from}")
        else:
            # from_clause already includes FROM keyword
            right_sql_parts.append(right_from)
    else:
        # No FROM clause - this shouldn't happen but handle gracefully
        right_sql_parts.append(f"FROM quad_table fallback_q1")
        logger.warning("Right branch missing FROM clause, using fallback")
    
    if right_sql.joins:
        right_sql_parts.extend(right_sql.joins)
        
    if right_sql.where_conditions:
        right_sql_parts.append(f"WHERE {' AND '.join(right_sql.where_conditions)}")
    
    right_sql_content = '\n'.join(right_sql_parts)
    
    # Debug: Log the generated SQL for each branch - exact logic from original
    logger.debug(f"Left branch SQL: {left_sql_content}")
    logger.debug(f"Right branch SQL: {right_sql_content}")
    
    # Validate that both branches have proper FROM clauses - exact logic from original
    if 'FROM' not in left_sql_content.upper():
        logger.error(f"Left branch missing FROM clause: {left_sql_content}")
    if 'FROM' not in right_sql_content.upper():
        logger.error(f"Right branch missing FROM clause: {right_sql_content}")
    
    # Combine with UNION - ensure proper SQL structure - exact logic from original
    union_sql = f"{left_sql_content}\nUNION\n{right_sql_content}"
    logger.debug(f"Combined UNION SQL: {union_sql}")
    
    # CRITICAL FIX: Check if we need FROM keyword fixing - EXACT logic from original
    has_proper_from_keywords = 'FROM vitalgraph' in union_sql and union_sql.count('FROM vitalgraph') >= union_sql.count('SELECT')
    
    if has_proper_from_keywords:
        fixed_union_sql = union_sql
    else:
        # Fix missing FROM keywords and remove duplicates - EXACT logic from original
        lines = union_sql.split('\n')
        fixed_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # Handle duplicate FROM keywords first - exact logic from original
            if stripped.upper().startswith('FROM FROM'):
                # Remove duplicate FROM keywords
                fixed_line = stripped[5:].strip()  # Remove first 'FROM '
                fixed_lines.append(f"FROM {fixed_line}")
                logger.debug(f"Fixed duplicate FROM in: {stripped}")
            # Look for table references that need FROM keywords - exact logic from original
            elif (stripped and 
                  ('vitalgraph1__space_test__rdf_quad' in stripped or 
                   stripped.startswith('right_q') or 
                   stripped.startswith('left_q') or
                   stripped.startswith('q')) and
                  not stripped.upper().startswith('FROM') and
                  not stripped.upper().startswith('SELECT') and
                  not stripped.upper().startswith('JOIN') and
                  not stripped.upper().startswith('WHERE') and
                  not stripped.upper().startswith('AND') and
                  not stripped.upper().startswith('OR') and
                  not stripped.upper().startswith('UNION') and
                  '=' not in stripped and
                  'AS' not in stripped.upper()):
                # This line is likely a table reference that needs FROM
                fixed_lines.append(f"FROM {stripped}")
                logger.debug(f"Added missing FROM keyword to: {stripped}")
            else:
                fixed_lines.append(line)
            i += 1
        fixed_union_sql = '\n'.join(fixed_lines)
    
    # Validate the combined UNION SQL structure - exact logic from original
    if '((' in fixed_union_sql or '))' in fixed_union_sql:
        logger.warning(f"UNION SQL has suspicious parentheses: {fixed_union_sql[:200]}...")
        # Log the full SQL for debugging
        logger.error(f"Full malformed UNION SQL: {fixed_union_sql}")
    
    # Validate that the UNION SQL is properly formed - exact logic from original
    if 'FROM' not in fixed_union_sql.upper():
        logger.error(f"UNION SQL missing FROM clauses: {fixed_union_sql[:300]}...")
        logger.error(f"Left branch SQL: {left_sql_content}")
        logger.error(f"Right branch SQL: {right_sql_content}")
        # This is a critical error - the UNION branches are malformed
        raise ValueError(f"UNION SQL generation failed - missing FROM clauses")
    
    # CRITICAL FIX: Avoid excessive nesting in UNION patterns - EXACT logic from original


    
    # Check the complexity of each branch - exact logic from original
    left_is_simple = left_sql_content.strip().startswith('SELECT') and 'FROM (' not in left_sql_content
    right_is_simple = right_sql_content.strip().startswith('SELECT') and 'FROM (' not in right_sql_content
    left_is_union = 'UNION' in left_sql_content
    right_is_union = 'UNION' in right_sql_content
    
    # Avoid excessive nesting by returning UNION directly in most cases - EXACT logic from original
    if (left_is_simple and right_is_simple) or (left_is_union or right_is_union):
        # Either both branches are simple, or at least one is already a UNION
        # In both cases, we can return the UNION directly without additional wrapping
        # Update variable mappings to not reference a union alias - exact logic from original
        union_variable_mappings = final_variable_mappings.copy()
        
        # Return the UNION SQL directly as the FROM clause - exact logic from original
        union_from_clause = f"FROM ({fixed_union_sql}) union_{alias_gen.next_union_alias()}"
        return SQLComponents(
            from_clause=union_from_clause,
            where_conditions=[],
            joins=[],
            variable_mappings=union_variable_mappings
        )
    else:
        # Complex structure that requires derived table approach - exact logic from original

        union_alias = f"union_{alias_gen.next_union_alias()}"
        union_from_clause = f"FROM ({fixed_union_sql}) {union_alias}"
        
        # Update variable mappings to reference the union table - exact logic from original
        union_variable_mappings = {}
        for var, col_name in final_variable_mappings.items():
            union_variable_mappings[var] = f"{union_alias}.{col_name}"
            # Debug BIND variable mapping preservation
            if var in left_sql.variable_mappings and "'" in str(left_sql.variable_mappings[var]):
                logger.debug(f"UNION: BIND variable {var} mapped from left '{left_sql.variable_mappings[var]}' to '{union_variable_mappings[var]}'")
            elif var in right_sql.variable_mappings and "'" in str(right_sql.variable_mappings[var]):
                logger.debug(f"UNION: BIND variable {var} mapped from right '{right_sql.variable_mappings[var]}' to '{union_variable_mappings[var]}'")
        
        # Debug final variable mappings - exact logic from original
        logger.debug(f"UNION final variable mappings: {union_variable_mappings}")
        logger.debug(f"UNION left vars: {left_sql.variable_mappings}")
        logger.debug(f"UNION right vars: {right_sql.variable_mappings}")
        
        # Debug: Log the final UNION FROM clause - exact logic from original
        logger.debug(f"Final UNION FROM clause: {union_from_clause[:200]}...")
        
        logger.info(f"Successfully translated UNION with {len(variable_list)} variables")
        logger.debug(f"UNION SQL generated: {len(union_sql)} characters")
        
        result = SQLComponents(
            from_clause=union_from_clause,
            where_conditions=[],
            joins=[],
            variable_mappings=union_variable_mappings
        )
        
        # Log function exit
        if sparql_context:
            sparql_context.log_function_exit(function_name, "SQLComponents", 
                                            variable_count=len(variable_list),
                                            sql_length=len(union_sql))
        
        return result


async def translate_optional_pattern(required_sql: SQLComponents, optional_sql: SQLComponents, 
                                   alias_gen: AliasGenerator, *, sparql_context: SparqlContext = None) -> SQLComponents:
    """
    Translate OPTIONAL (LeftJoin) pattern to SQL LEFT JOIN operations.
    Exact port from PostgreSQLSparqlImpl._translate_optional method.
    
    Args:
        required_sql: SQL components for required part
        optional_sql: SQL components for optional part
        alias_gen: Alias generator for unique aliases
        sparql_context: Optional SparqlContext for logging and state
        
    Returns:
        SQLComponents with LEFT JOIN logic
    """
    import re
    function_name = "translate_optional_pattern"
    
    # Use SparqlContext for logging if available, otherwise fallback
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, 
                                         required_vars=list(required_sql.variable_mappings.keys()),
                                         optional_vars=list(optional_sql.variable_mappings.keys()))
    else:
        # Import logger for fallback
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"🔗 {function_name}: Starting OPTIONAL pattern translation")
    
    # Start with required part as the main FROM clause - exact logic from original
    main_from = required_sql.from_clause
    main_joins = required_sql.joins.copy() if required_sql.joins else []
    main_where = required_sql.where_conditions.copy() if required_sql.where_conditions else []
    
    
    all_where_conditions = main_where + (optional_sql.where_conditions if optional_sql.where_conditions else [])
    all_join_conditions = main_joins.copy()
    
    # Add optional JOINs to the analysis (they haven't been processed yet)
    if optional_sql.joins:
        all_join_conditions.extend(optional_sql.joins)
    
    # Find all quad table aliases referenced anywhere in the SQL
    referenced_quad_aliases = set()
    
    # Extract from WHERE conditions
    for condition in all_where_conditions:
        quad_matches = re.findall(r'\b(\w*q\d+)\.[a-z_]+', condition)
        referenced_quad_aliases.update(quad_matches)
    
    # Extract from JOIN ON conditions
    for join in all_join_conditions:
        quad_matches = re.findall(r'\b(\w*q\d+)\.[a-z_]+', join)
        referenced_quad_aliases.update(quad_matches)
    
    logger.debug(f"All referenced quad aliases: {referenced_quad_aliases}")
    
    # Get quad aliases already declared in required FROM and JOINs
    declared_aliases = set()
    
    # Extract from required FROM clause
    req_from_match = re.search(r'FROM\s+\S+\s+(\w+)', main_from)
    if req_from_match:
        declared_aliases.add(req_from_match.group(1))
    
    # Extract from required JOINs (only the ones already in main_joins)
    for join in main_joins:
        join_match = re.search(r'JOIN\s+\S+\s+(\w+)', join)
        if join_match:
            declared_aliases.add(join_match.group(1))
    
    logger.debug(f"Already declared aliases: {declared_aliases}")
    
    # Find aliases that will be added by optional JOINs processing
    aliases_from_opt_joins = set()
    if optional_sql.joins:
        for join in optional_sql.joins:
            join_match = re.search(r'JOIN\s+\S+\s+(\w+)', join)
            if join_match:
                aliases_from_opt_joins.add(join_match.group(1))
    
    logger.debug(f"Aliases that will be added by optional JOINs: {aliases_from_opt_joins}")
    
    # Find missing quad aliases that need to be declared (excluding ones handled by opt_joins)
    missing_aliases = referenced_quad_aliases - declared_aliases - aliases_from_opt_joins
    logger.debug(f"Missing quad aliases that need declaration: {missing_aliases}")
    
    # Add LEFT JOINs for missing quad table aliases with proper ON clauses
    # Assume quad table name from the FROM clause
    quad_table = "vitalgraph1__space_test__rdf_quad"  # Default fallback
    if "rdf_quad" in main_from:
        table_match = re.search(r'FROM\s+(\S+rdf_quad)', main_from)
        if table_match:
            quad_table = table_match.group(1)
    
    # Find a quad alias from the required part to connect to (for JOIN ON conditions)
    connection_alias = None
    req_from_match = re.search(r'FROM\s+\S+\s+(\w+)', main_from)
    if req_from_match:
        connection_alias = req_from_match.group(1)
    
    logger.debug(f"Using connection alias: {connection_alias}")
    
    # Add LEFT JOINs for missing quad aliases, connecting through subject_uuid
    for alias in missing_aliases:
        if connection_alias:
            main_joins.append(f"LEFT JOIN {quad_table} {alias} ON {connection_alias}.subject_uuid = {alias}.subject_uuid")
            logger.debug(f"Added LEFT JOIN for missing quad alias: {alias} connected to {connection_alias}")
        else:
            # Fallback: add without ON clause (will likely cause error but better than missing table)
            main_joins.append(f"LEFT JOIN {quad_table} {alias}")
            logger.warning(f"Added LEFT JOIN for missing quad alias: {alias} WITHOUT ON clause - may cause SQL error")
    
    # Convert all optional JOINs to LEFT JOINs
    if optional_sql.joins:
        for join in optional_sql.joins:
            # Convert regular JOINs to LEFT JOINs for optional part
            if join.strip().startswith('JOIN'):
                left_join = join.replace('JOIN', 'LEFT JOIN', 1)
                main_joins.append(left_join)
            elif join.strip().startswith('LEFT JOIN'):
                # Already a LEFT JOIN, add as-is
                main_joins.append(join)
            else:
                # Other types of joins, add as-is
                main_joins.append(join)
    
    # Handle optional WHERE conditions
    # For OPTIONAL patterns, WHERE conditions from the optional part
    # should remain as WHERE conditions (not moved to JOIN ON clauses)
    # because they filter the optional results, not the join condition
    if optional_sql.where_conditions:
        main_where.extend(optional_sql.where_conditions)
    
    # Combine variable mappings (optional variables can be NULL)
    logger.debug(f"Required variables mapping: {required_sql.variable_mappings}")
    logger.debug(f"Optional variables mapping: {optional_sql.variable_mappings}")
    
    combined_vars = required_sql.variable_mappings.copy()
    combined_vars.update(optional_sql.variable_mappings)
    
    logger.debug(f"Combined variables mapping: {combined_vars}")
    logger.info(f"✅ OPTIONAL translation completed with {len(combined_vars)} variables")
    
    # Debug logging for returned SQL components
    logger.debug(f"OPTIONAL returning FROM: '{main_from}'")
    logger.debug(f"OPTIONAL returning WHERE: {main_where}")
    logger.debug(f"OPTIONAL returning JOINs: {main_joins}")
    logger.debug(f"OPTIONAL returning variables: {list(combined_vars.keys())}")
    
    result = SQLComponents(
        from_clause=main_from,
        where_conditions=main_where,
        joins=main_joins,
        variable_mappings=combined_vars
    )
    
    # Log function exit
    if sparql_context:
        sparql_context.log_function_exit(function_name, "SQLComponents", 
                                        variable_count=len(combined_vars),
                                        join_count=len(main_joins))
    
    return result


def translate_minus_pattern(main_sql: SQLComponents, exclude_sql: SQLComponents,
                          shared_vars: Set[Variable]) -> SQLComponents:
    """
    Translate a MINUS pattern to SQL using NOT EXISTS with proper correlation.
    
    SPARQL MINUS semantics: The main pattern is filtered to exclude solutions
    where the exclude pattern would also match with the same variable bindings.
    
    This requires a correlated NOT EXISTS subquery where shared variables
    are properly linked between outer and inner queries using valid SQL.
    
    Args:
        main_sql: SQL components for the main pattern
        exclude_sql: SQL components for the pattern to exclude
        shared_vars: Variables shared between main and exclude patterns
    
    Returns:
        Updated SQLComponents with NOT EXISTS condition
    """
    logger.debug(f"Translating MINUS pattern with {len(shared_vars)} shared variables")
    
    if not shared_vars:
        # No shared variables - MINUS excludes everything if exclude pattern matches anything
        # This is a simple NOT EXISTS without correlation
        not_exists_subquery = "SELECT 1"
        if exclude_sql.from_clause:
            if exclude_sql.from_clause.strip().upper().startswith('FROM'):
                not_exists_subquery += f" {exclude_sql.from_clause}"
            else:
                not_exists_subquery += f" FROM {exclude_sql.from_clause}"
        if exclude_sql.joins:
            not_exists_subquery += f" {' '.join(exclude_sql.joins)}"
        if exclude_sql.where_conditions:
            not_exists_subquery += f" WHERE {' AND '.join(exclude_sql.where_conditions)}"
    else:
        # Shared variables - build correlated subquery
        # CRITICAL: We need to restructure this to avoid cross-scope table alias references
        
        # The key insight is that for SPARQL MINUS with shared variables,
        # we need to check if there exists a matching pattern in the exclude clause
        # where the shared variables have the same values as in the main pattern.
        
        # For proper correlation, we need to reference the main query's variable values
        # directly in the subquery WHERE clause, not through table aliases.
        
        # Build the exclude pattern subquery structure
        not_exists_subquery = "SELECT 1"
        if exclude_sql.from_clause:
            if exclude_sql.from_clause.strip().upper().startswith('FROM'):
                not_exists_subquery += f" {exclude_sql.from_clause}"
            else:
                not_exists_subquery += f" FROM {exclude_sql.from_clause}"
        if exclude_sql.joins:
            not_exists_subquery += f" {' '.join(exclude_sql.joins)}"
        
        # Build correlation conditions using proper SQL correlation syntax
        # SOLUTION: Instead of trying to correlate table aliases across scopes,
        # we'll modify the subquery to reference the outer query's tables directly.
        
        correlation_conditions = []
        
        # Extract the main query's table information for correlation
        # We need to identify which tables in the main query correspond to shared variables
        main_table_info = {}
        for var in shared_vars:
            if var in main_sql.variable_mappings:
                main_col = main_sql.variable_mappings[var]
                # Extract table alias and column from something like "s_term_0.term_text"
                if '.' in main_col:
                    table_alias, column = main_col.rsplit('.', 1)
                    main_table_info[var] = {'alias': table_alias, 'column': column}
        
        # Now build correlation conditions that reference the outer query properly
        for var in shared_vars:
            if var in exclude_sql.variable_mappings and var in main_table_info:
                exclude_col = exclude_sql.variable_mappings[var]
                main_info = main_table_info[var]
                
                # Create a correlation condition that references the outer query
                # The exclude_col should equal the main query's column value
                # We reference the main query's table alias directly
                correlation_conditions.append(f"{exclude_col} = {main_info['alias']}.{main_info['column']}")
        
        # Combine exclude pattern conditions with correlation conditions
        all_conditions = exclude_sql.where_conditions + correlation_conditions
        if all_conditions:
            not_exists_subquery += f" WHERE {' AND '.join(all_conditions)}"
    
    not_exists_condition = f"NOT EXISTS ({not_exists_subquery})"
    
    logger.debug(f"Generated MINUS NOT EXISTS condition: {not_exists_condition}")
    
    return SQLComponents(
        from_clause=main_sql.from_clause,
        where_conditions=main_sql.where_conditions + [not_exists_condition],
        joins=main_sql.joins,
        variable_mappings=main_sql.variable_mappings
    )


async def translate_values_pattern(values_pattern, projected_vars: List[Variable] = None, *, sparql_context: SparqlContext = None) -> SQLComponents:
    """Translate VALUES pattern to SQL.
    
    VALUES patterns provide inline data binding for variables.
    Examples:
    - VALUES ?name { "Alice" "Bob" "Charlie" }
    - VALUES (?name ?age) { ("Alice" 25) ("Bob" 30) ("Charlie" 35) }
    
    This generates a subquery with UNION ALL for each data row.
    """
    function_name = "translate_values_pattern"
    
    # Handle backward compatibility - sparql_context might be None
    if sparql_context:
        sparql_context.log_function_entry(function_name, pattern_type=type(values_pattern).__name__)
        table_config = sparql_context.table_config
        alias_gen = sparql_context.alias_generator
        logger = sparql_context.logger
    else:
        # Fallback for functions that don't provide context yet
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"{function_name}: No SparqlContext provided - using fallback logging")
        # These will need to be provided by caller if no context
        table_config = None
        alias_gen = None
    
    try:
        
        logger.debug(f"Translating VALUES pattern: {values_pattern}")
        logger.debug(f"Pattern type: {type(values_pattern)}")
        logger.debug(f"Pattern name: {getattr(values_pattern, 'name', 'NO_NAME')}")
        
        # Get all non-private attributes for debugging
        attrs = [attr for attr in dir(values_pattern) if not attr.startswith('_')]
        logger.debug(f"Pattern attributes: {attrs}")
        
        # Debug each attribute value
        for attr in attrs:
            try:
                value = getattr(values_pattern, attr)
                logger.debug(f"  {attr}: {value} (type: {type(value)})")
                if isinstance(value, (list, tuple)) and len(value) <= 10:
                    for i, item in enumerate(value):
                        logger.debug(f"    [{i}]: {item} (type: {type(item)})")
            except Exception as e:
                logger.debug(f"  {attr}: ERROR - {e}")
        
        # Extract data from ToMultiSet pattern structure
        # ToMultiSet has nested 'p' attribute containing 'values_' pattern with 'res' data
        variables = []
        data_rows = []
        
        # Check for nested values pattern in 'p' attribute
        if hasattr(values_pattern, 'p'):
            nested_p = getattr(values_pattern, 'p')
            logger.debug(f"Nested p pattern: {nested_p} (type: {type(nested_p)})")
            
            if hasattr(nested_p, 'res'):
                res_data = getattr(nested_p, 'res')
                logger.debug(f"Found res data: {res_data} (type: {type(res_data)})")
                
                if res_data and isinstance(res_data, list):
                    # res_data is a list of dictionaries mapping variables to values
                    # Extract variables from first row
                    if res_data:
                        first_row = res_data[0]
                        variables = list(first_row.keys())
                        logger.debug(f"Extracted variables: {variables}")
                        
                        # Convert dictionary rows to tuple rows
                        for row_dict in res_data:
                            row_tuple = tuple(row_dict[var] for var in variables)
                            data_rows.append(row_tuple)
                        
                        logger.debug(f"Converted {len(data_rows)} data rows")
        
        # Handle single variable case (var is not a list)
        if variables and not isinstance(variables, list):
            variables = [variables]
        
        logger.debug(f"FINAL - variables: {variables}")
        logger.debug(f"FINAL - data rows: {len(data_rows) if data_rows else 0} rows")
        if data_rows:
            for i, row in enumerate(data_rows[:3]):  # Show first 3 rows
                logger.debug(f"  Row {i}: {row} (type: {type(row)})")
        
        if not variables or not data_rows:
            logger.warning("Empty VALUES pattern")
            # Use alias generator instead of hardcoded q0
            quad_alias = sparql_context.alias_generator.next_quad_alias()
            result = SQLComponents(
                from_clause=f"FROM {table_config.quad_table} {quad_alias}",
                where_conditions=[],
                joins=[],
                variable_mappings={}
            )
            if sparql_context:
                sparql_context.log_function_exit(function_name, "SQLComponents", variables=0, data_rows=0)
            return result
        
        # Generate alias for VALUES subquery
        if not hasattr(translate_values_pattern, '_values_counter'):
            translate_values_pattern._values_counter = 0
        translate_values_pattern._values_counter += 1
        values_alias = f"values_{translate_values_pattern._values_counter}"
        
        # Build UNION ALL subquery for VALUES data
        union_parts = []
        variable_mappings = {}
        
        for row_idx, row_data in enumerate(data_rows):
            # Handle single value case (not a tuple)
            if not isinstance(row_data, (list, tuple)):
                row_data = [row_data]
            
            # Build SELECT clause for this row
            select_parts = []
            for var_idx, variable in enumerate(variables):
                if var_idx < len(row_data):
                    value = row_data[var_idx]
                    # Convert RDFLib terms to SQL literals
                    sql_value = _convert_rdflib_term_to_sql(value)
                else:
                    # Handle missing values with NULL
                    sql_value = "NULL"
                
                # Create column alias for this variable
                column_alias = f"{variable.n3()[1:]}_val"  # Remove ? from variable name
                select_parts.append(f"{sql_value} AS {column_alias}")
                
                # Store variable mapping (only need to do this once)
                if row_idx == 0:
                    variable_mappings[variable] = f"{values_alias}.{column_alias}"
            
            # Create SELECT statement for this row
            union_parts.append(f"SELECT {', '.join(select_parts)}")
        
        # Combine all rows with UNION ALL
        values_sql = ' UNION ALL '.join(union_parts)
        
        # Create FROM clause with subquery alias
        from_clause = f"FROM ({values_sql}) {values_alias}"
        
        logger.debug(f"Generated VALUES SQL: {from_clause}")
        logger.debug(f"Variable mappings: {variable_mappings}")
        
        result = SQLComponents(
            from_clause=from_clause,
            where_conditions=[],
            joins=[],
            variable_mappings=variable_mappings
        )
        if sparql_context:
            sparql_context.log_function_exit(function_name, "SQLComponents", variables=len(variable_mappings), data_rows=len(data_rows))
        return result
        
    except Exception as e:
        if sparql_context:
            sparql_context.log_function_error(function_name, e)
        else:
            logger.error(f"Error in {function_name}: {e}")
        
        # Re-raise the exception instead of returning fallback SQLComponents
        # This allows proper error handling at the appropriate level
        raise


def _convert_rdflib_term_to_sql(term):
    """Convert RDFLib term to SQL literal value.
    
    CRITICAL FIX: Convert all values to quoted strings for consistency with term table.
    This avoids type mismatch errors when comparing VALUES with BGP patterns.
    """
    from rdflib import URIRef, Literal, BNode
    from rdflib.namespace import XSD
    
    if isinstance(term, URIRef):
        return f"'{str(term)}'"
    elif isinstance(term, Literal):
        # CRITICAL: Convert ALL literals to quoted strings for consistency
        # This prevents type mismatch errors when comparing with term table
        if term.datatype:
            if term.datatype in [XSD.integer, XSD.int, XSD.long]:
                return f"'{str(term.value)}'"  # Quote integers as strings
            elif term.datatype in [XSD.decimal, XSD.double, XSD.float]:
                return f"'{str(term.value)}'"  # Quote numbers as strings
            elif term.datatype == XSD.boolean:
                return f"'{str(term.value).upper()}'"  # Quote booleans as strings
            else:
                # String or other literal types
                return f"'{str(term)}'"
        else:
            # Plain literal (string)
            return f"'{str(term)}'"
    elif isinstance(term, BNode):
        return f"'_:{str(term)}'"
    else:
        # Fallback for other types
        return f"'{str(term)}'"


async def translate_join_pattern(left_sql: SQLComponents, right_sql: SQLComponents, 
                               alias_gen: AliasGenerator, *, sparql_context: SparqlContext = None) -> SQLComponents:
    """
    Translate JOIN pattern by combining left and right operands.
    Uses the exact original implementation logic from postgresql_sparql_impl.py.
    
    Args:
        left_sql: SQL components from left operand
        right_sql: SQL components from right operand
        alias_gen: Alias generator for consistent naming
        sparql_context: Optional SparqlContext for logging and state
        
    Returns:
        SQLComponents with combined JOIN SQL structure
    """
    function_name = "translate_join_pattern"
    
    # Use SparqlContext for logging if available, otherwise fallback
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, 
                                         left_vars=list(left_sql.variable_mappings.keys()),
                                         right_vars=list(right_sql.variable_mappings.keys()))
    else:
        # Import logger for fallback
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f" {function_name}: Starting JOIN pattern translation")
    
    # Find shared variables between left and right patterns
    left_vars = set(left_sql.variable_mappings.keys())
    right_vars = set(right_sql.variable_mappings.keys())
    shared_vars = left_vars & right_vars
    
    logger.debug(f"Left variables: {[str(v) for v in left_vars]}")
    logger.debug(f"Right variables: {[str(v) for v in right_vars]}")
    logger.debug(f"Shared variables: {[str(v) for v in shared_vars]}")
    
    # Combine variable mappings
    combined_vars = {**left_sql.variable_mappings, **right_sql.variable_mappings}
    
    # Combine WHERE conditions
    combined_where = left_sql.where_conditions + right_sql.where_conditions
    
    # CRITICAL FIX: Add equality conditions for shared variables to avoid cartesian products
    # While the original used pure CROSS JOIN, we need explicit equality conditions
    # to connect shared variables across patterns and prevent massive cartesian products.
    
    logger.debug(f"Shared variables found: {[str(v) for v in shared_vars]}")
    
    # Generate equality conditions for shared variables
    shared_var_conditions = []
    if shared_vars:
        logger.debug("Adding equality conditions for shared variables to avoid cartesian product")
        for var in shared_vars:
            left_mapping = left_sql.variable_mappings.get(var)
            right_mapping = right_sql.variable_mappings.get(var)
            
            if left_mapping and right_mapping:
                # Extract table aliases from the mappings (e.g., "subject_term_0.term_text" -> "subject_term_0")
                import re
                left_table_match = re.search(r'(\w+)\.', left_mapping)
                right_table_match = re.search(r'(\w+)\.', right_mapping)
                
                if left_table_match and right_table_match:
                    left_table = left_table_match.group(1)
                    right_table = right_table_match.group(1)
                    
                    # For term tables, connect via term_uuid
                    if 'term' in left_table and 'term' in right_table:
                        condition = f"{left_table}.term_uuid = {right_table}.term_uuid"
                        shared_var_conditions.append(condition)
                        logger.debug(f"🔗 Added shared variable condition for {var}: {condition}")
                    else:
                        # Fallback: connect via the actual column values
                        condition = f"{left_mapping} = {right_mapping}"
                        shared_var_conditions.append(condition)
                        logger.debug(f"🔗 Added shared variable condition for {var}: {condition}")
    else:
        logger.debug("No shared variables - using pure CROSS JOIN")
    
    # Combine JOINs
    combined_joins = left_sql.joins + right_sql.joins
    
    # Combine FROM clauses properly to include both operands
    # Extract table references from both FROM clauses (only remove leading FROM)
    left_tables = left_sql.from_clause[5:].strip() if left_sql.from_clause.startswith("FROM ") else left_sql.from_clause.strip()
    right_tables = right_sql.from_clause[5:].strip() if right_sql.from_clause.startswith("FROM ") else right_sql.from_clause.strip()
    
    # CRITICAL FIX: Check for duplicate table aliases and generate new ones if needed
    import re
    left_alias_match = re.search(r'\b(q\d+)\b', left_tables)
    right_alias_match = re.search(r'\b(q\d+)\b', right_tables)
    
    if (left_alias_match and right_alias_match and 
        left_alias_match.group(1) == right_alias_match.group(1)):
        # Duplicate alias detected - generate new alias for right side
        old_alias = right_alias_match.group(1)
        new_alias = alias_gen.next_quad_alias()
        right_tables = right_tables.replace(old_alias, new_alias)
        
        # Update right side joins to use new alias
        updated_right_joins = []
        for join in right_sql.joins:
            updated_join = join.replace(f"{old_alias}.", f"{new_alias}.")
            updated_right_joins.append(updated_join)
        
        # Update right side WHERE conditions to use new alias
        updated_right_where = []
        for where in right_sql.where_conditions:
            updated_where = where.replace(f"{old_alias}.", f"{new_alias}.")
            updated_right_where.append(updated_where)
        
        # Use updated components
        combined_joins = left_sql.joins + updated_right_joins
        combined_where = left_sql.where_conditions + updated_right_where
        
        logger.debug(f"🔧 JOIN_FIX: Detected duplicate alias '{old_alias}', replaced with '{new_alias}' on right side")
    else:
        # No duplicate aliases - use original logic
        combined_joins = left_sql.joins + right_sql.joins
        combined_where = left_sql.where_conditions + right_sql.where_conditions
    
    # Add shared variable equality conditions to WHERE clause
    combined_where.extend(shared_var_conditions)
    
    # Create combined FROM clause with CROSS JOIN
    combined_from = f"FROM {left_tables} CROSS JOIN {right_tables}"
    

    
    # Log the join operation for debugging
    logger.debug(f"JOIN: Left FROM: {left_sql.from_clause}")
    logger.debug(f"JOIN: Right FROM: {right_sql.from_clause}")
    logger.debug(f"JOIN: Combined FROM: {combined_from}")
    logger.debug(f"JOIN: Left vars: {list(left_sql.variable_mappings.keys())}, Right vars: {list(right_sql.variable_mappings.keys())}")
    
    # For variable mapping conflicts, prefer the left side (first pattern)
    # This is a simple resolution strategy
    for var, alias in right_sql.variable_mappings.items():
        if var not in combined_vars:
            combined_vars[var] = alias
        else:
            logger.debug(f"Variable {var} already mapped, keeping left mapping")
    
    logger.debug(f"✅ JOIN pattern translated with {len(combined_vars)} variables")
    
    result = SQLComponents(
        from_clause=combined_from,
        where_conditions=combined_where,
        joins=combined_joins,
        variable_mappings=combined_vars
    )
    
    # Log function exit
    if sparql_context:
        sparql_context.log_function_exit(function_name, "SQLComponents", 
                                        variable_count=len(combined_vars),
                                        shared_vars=len(shared_vars))
    
    return result


def translate_bind_pattern(nested_sql: SQLComponents, bind_var: Variable, 
                         bind_expr: str, alias_gen: AliasGenerator) -> SQLComponents:
    """
    Translate BIND (Extend) pattern to SQL with computed expressions.
    
    Args:
        nested_sql: SQL components from nested pattern
        bind_var: Variable being bound
        bind_expr: SQL expression to compute
        alias_gen: Alias generator for unique aliases
        
    Returns:
        SQLComponents with BIND expression added
    """
    logger.debug(f"Translating BIND pattern for variable {bind_var}")
    
    # If the nested pattern is complex, wrap it in a subquery to add the BIND expression
    if nested_sql.joins or len(nested_sql.where_conditions) > 1:
        # Build subquery with all existing variables plus the BIND expression
        select_items = []
        for var, col in nested_sql.variable_mappings.items():
            select_items.append(f"{col} AS {str(var).replace('?', '')}")
        
        # Add the BIND expression
        bind_alias = str(bind_var).replace('?', '')
        # If bind_expr is a simple variable reference (like __agg_1__), don't wrap in parentheses
        if bind_expr.strip().startswith('__') and bind_expr.strip().replace('__', '').replace('_', '').isalnum():
            # This is likely a reference to an aggregation variable, use it directly
            select_items.append(f"{bind_expr} AS {bind_alias}")
        elif bind_expr.strip().startswith('ABS(') or bind_expr.strip().startswith('CEIL(') or bind_expr.strip().startswith('FLOOR(') or bind_expr.strip().startswith('ROUND('):
            # Function calls already have proper parentheses, don't wrap again
            select_items.append(f"{bind_expr} AS {bind_alias}")
        else:
            select_items.append(f"({bind_expr}) AS {bind_alias}")
        
        subquery = f"SELECT {', '.join(select_items)}"
        if nested_sql.from_clause:
            # Check if from_clause already starts with FROM
            if nested_sql.from_clause.strip().upper().startswith('FROM'):
                subquery += f" {nested_sql.from_clause}"
            else:
                subquery += f" FROM {nested_sql.from_clause}"
        if nested_sql.joins:
            subquery += f" {' '.join(nested_sql.joins)}"
        if nested_sql.where_conditions:
            subquery += f" WHERE {' AND '.join(nested_sql.where_conditions)}"
        
        bind_subquery_alias = alias_gen.next_subquery_alias()
        from_clause = f"({subquery}) AS {bind_subquery_alias}"
        
        # Update all variable mappings to reference the subquery
        updated_mappings = {}
        for var in nested_sql.variable_mappings:
            updated_mappings[var] = f"{bind_subquery_alias}.{str(var).replace('?', '')}"
        updated_mappings[bind_var] = f"{bind_subquery_alias}.{bind_alias}"
        
        return SQLComponents(
            from_clause=from_clause,
            where_conditions=[],
            joins=[],
            variable_mappings=updated_mappings
        )
    else:
        # Simple case - just add bind variable to mappings
        updated_mappings = nested_sql.variable_mappings.copy()
        updated_mappings[bind_var] = bind_expr
        
        return SQLComponents(
            from_clause=nested_sql.from_clause,
            where_conditions=nested_sql.where_conditions,
            joins=nested_sql.joins,
            variable_mappings=updated_mappings
        )


def translate_filter_pattern(nested_sql: SQLComponents, filter_expr: str) -> SQLComponents:
    """
    Translate FILTER pattern to SQL WHERE conditions.
    
    CRITICAL: Detects HAVING clauses (filters on aggregate expressions) and stores them
    separately from WHERE conditions for proper SQL generation.
    
    Args:
        nested_sql: SQL components from nested pattern
        filter_expr: SQL filter expression
        
    Returns:
        SQLComponents with filter condition added
    """
    logger.debug("Translating FILTER pattern")
    
    # Import the HAVING clause detection function
    from .postgresql_sparql_expressions import is_having_clause
    
    # CRITICAL FIX: Detect if this is a HAVING clause (filter on aggregate expressions)
    # HAVING clauses reference aggregate result variables like __agg_1__, __agg_2__, etc.
    is_having = is_having_clause(filter_expr, nested_sql.variable_mappings)
    
    if is_having:
        # This is a HAVING clause - store it separately for SQL generation after GROUP BY
        variable_mappings = dict(nested_sql.variable_mappings)  # Copy to avoid mutation
        having_conditions = variable_mappings.get('__HAVING_CONDITIONS__', [])
        having_conditions.append(filter_expr)
        variable_mappings['__HAVING_CONDITIONS__'] = having_conditions
        logger.debug(f"Added HAVING condition: {filter_expr}")
        
        return SQLComponents(
            from_clause=nested_sql.from_clause,
            where_conditions=nested_sql.where_conditions,  # Don't add to WHERE
            joins=nested_sql.joins,
            variable_mappings=variable_mappings
        )
    else:
        # Regular WHERE condition
        logger.debug(f"Added WHERE condition: {filter_expr}")
        return SQLComponents(
            from_clause=nested_sql.from_clause,
            where_conditions=nested_sql.where_conditions + [f"({filter_expr})"],
            joins=nested_sql.joins,
            variable_mappings=nested_sql.variable_mappings
        )


async def translate_graph_pattern(nested_sql: SQLComponents, graph_uri: Optional[str],
                          *, sparql_context: SparqlContext = None) -> SQLComponents:
    """
    Translate GRAPH pattern to SQL with graph context constraints - FIXED to use original approach.
    
    The key insight is that context constraints should be applied at the BGP level during
    pattern translation, not after complex SQL structures are built. This avoids scope
    issues with table aliases in UNIONs and subqueries.
    
    Args:
        nested_sql: SQL components from nested pattern
        graph_uri: Graph URI to constrain to (None for variable graphs)
        sparql_context: SparqlContext containing table_config and other state
        
    Returns:
        SQLComponents with graph constraint added
    """
    function_name = "translate_graph_pattern"
    
    # Use SparqlContext for logging and table_config
    if sparql_context:
        logger = sparql_context.logger
        table_config = sparql_context.table_config
        sparql_context.log_function_entry(function_name, graph_uri=graph_uri)
    else:
        # Fallback logging
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"🔗 {function_name}: Translating GRAPH pattern for graph: {graph_uri}")
        # This shouldn't happen in practice since sparql_context should always be provided
        raise ValueError("SparqlContext is required for translate_graph_pattern")
    
    if graph_uri:
        # Named graph - resolve URI to UUID and add context constraint
        logger.debug(f"Processing named graph: {graph_uri}")
        
        # Get term info for the graph URI
        if isinstance(graph_uri, URIRef):
            graph_text, graph_type = str(graph_uri), 'U'
        elif isinstance(graph_uri, str):
            graph_text, graph_type = graph_uri, 'U'
        else:
            graph_text, graph_type = str(graph_uri), 'U'  # Default to URI
        graph_terms = [(graph_text, graph_type)]
        
        # Get UUID for the graph term
        from vitalgraph.db.postgresql.sparql.postgresql_sparql_cache_integration import get_term_uuids_batch
        graph_uuid_mappings = await get_term_uuids_batch(
            graph_terms, table_config, sparql_context.term_cache, sparql_context.space_impl,
            sparql_context=sparql_context
        )
        
        graph_key = (graph_text, graph_type)
        if graph_key in graph_uuid_mappings:
            context_uuid = graph_uuid_mappings[graph_key]
            context_constraint = f"context_uuid = '{context_uuid}'"
            logger.debug(f"Found graph UUID: {context_uuid}")
            
            # FIXED: Context constraints should only be applied at the BGP level during pattern translation
            # Applying them after complex SQL structures are built causes scope issues with table aliases
            # The GRAPH pattern translation now passes context constraints down to BGP via translate_algebra_pattern
            logger.debug(f"Context constraint handled at BGP level during pattern translation")
            
            # Log function exit
            if sparql_context:
                sparql_context.log_function_exit(function_name, "SQLComponents", graph_found=True)
            return nested_sql
        else:
            # Graph not found - return empty result set
            logger.warning(f"Graph not found: {graph_text}")
            # Return empty result by using impossible constraint - context constraints should be handled at BGP level
            result = SQLComponents(
                from_clause=f"FROM {table_config.quad_table} q_empty WHERE 1=0",
                where_conditions=[],
                joins=[],
                variable_mappings={}
            )
            
            # Log function exit
            if sparql_context:
                sparql_context.log_function_exit(function_name, "SQLComponents", graph_found=False)
            return result
    else:
        # Variable graph - no additional constraints needed
        logger.debug(f"Variable graph - no constraints added")
        
        # Log function exit
        if sparql_context:
            sparql_context.log_function_exit(function_name, "SQLComponents", variable_graph=True)
        return nested_sql


def _is_simple_sql_structure(sql_components: SQLComponents) -> bool:
    """
    Check if SQL components represent a simple structure where context constraints can be safely applied.
    
    Args:
        sql_components: SQL components to check
        
    Returns:
        True if structure is simple, False if complex (UNIONs, subqueries, etc.)
    """
    from_clause = sql_components.from_clause or ""
    
    # Check for complex structures that indicate context constraints should be applied at BGP level
    complex_indicators = [
        "(SELECT",  # Subqueries
        "UNION",    # Union operations
        "CROSS JOIN (",  # Cross joins with subqueries
    ]
    
    for indicator in complex_indicators:
        if indicator in from_clause:
            return False
    
    return True


def _apply_context_constraint_to_sql(sql_components: SQLComponents, context_constraint: str, table_config: TableConfig) -> SQLComponents:
    """
    Apply context constraint to SQL components by extracting quad aliases - PORTED from original.
    
    This is the key function from the original implementation that correctly applies
    context constraints to quad table aliases found in the SQL.
    
    CRITICAL: Skip context constraint application for UNION SQL to prevent alias scope errors.
    
    Args:
        sql_components: SQL components to modify
        context_constraint: Context constraint to apply (e.g., "context_uuid = 'uuid'")
        table_config: Table configuration
        
    Returns:
        Modified SQLComponents with context constraint applied
    """
    # CRITICAL FIX: Skip context constraint application for UNION SQL
    # UNION SQL contains aliases that are only in scope within the UNION branches
    # Applying context constraints at the outer level causes "missing FROM-clause entry" errors
    if sql_components.from_clause and 'UNION' in sql_components.from_clause.upper():
        logger.debug(f"Skipping context constraint application for UNION SQL to prevent scope errors")
        return sql_components
    
    # Extract quad aliases from FROM clause and JOINs - EXACT logic from original
    quad_aliases = _extract_quad_aliases_from_sql(sql_components.from_clause, sql_components.joins, table_config)
    
    # Apply context constraint to each quad alias
    additional_where = []
    for quad_alias in quad_aliases:
        constraint = f"{quad_alias}.{context_constraint}"
        additional_where.append(constraint)
    
    logger.debug(f"Applied context constraint '{context_constraint}' to aliases: {quad_aliases}")
    
    return SQLComponents(
        from_clause=sql_components.from_clause,
        where_conditions=sql_components.where_conditions + additional_where,
        joins=sql_components.joins,
        variable_mappings=sql_components.variable_mappings
    )


def _extract_quad_aliases_from_sql(from_clause: str, joins: List[str], table_config: TableConfig) -> List[str]:
    """
    Extract quad table aliases from FROM clause and JOINs - EXACT logic from original implementation.
    
    The original implementation uses simple heuristics that are more robust than complex regex matching.
    CRITICAL: Only extract actual quad table aliases, never term table aliases (e.g., s_term_X, o_term_X).
    CRITICAL: Never extract aliases from within derived tables (content inside parentheses).
    
    Args:
        from_clause: SQL FROM clause
        joins: List of JOIN clauses
        table_config: Table configuration
        
    Returns:
        List of quad table aliases (excludes term table aliases and derived table content)
    """
    import re
    quad_aliases = []
    
    # CRITICAL FIX: If FROM clause contains derived tables (parentheses), only extract from the outer level
    # Do NOT parse content inside parentheses as it contains aliases that are only in scope within the derived table
    if '(' in from_clause and ')' in from_clause:
        # This is a derived table like "FROM (UNION SQL) alias" - only extract the outer alias
        # Pattern: FROM (anything) alias
        derived_match = re.search(r'FROM\s+\([^)]+\)\s+(\w+)', from_clause)
        if derived_match:
            outer_alias = derived_match.group(1)
            # Don't include derived table aliases as they're not quad tables
            pass
        # No quad aliases to extract from derived tables
        return quad_aliases
    
    # Extract alias from FROM clause (e.g., "FROM quad_table q0" -> "q0")
    # EXACT logic from original: use simple pattern matching
    # BUT: Only include if it references a quad table, not a term table
    from_match = re.search(r'FROM\s+(\S+)\s+(\w+)', from_clause)
    if from_match:
        table_name = from_match.group(1)
        alias = from_match.group(2)
        # Only include if it's a quad table (contains 'quad') and alias doesn't look like a term alias
        if 'quad' in table_name.lower() and not re.match(r'[so]_term_\d+', alias):
            quad_aliases.append(alias)
    
    # Extract aliases from JOINs that reference quad tables
    # EXACT logic from original: simple heuristic check
    # BUT: Exclude term table aliases
    for join in joins:
        # Look for quad table JOINs (e.g., "JOIN quad_table q1 ON ...")
        if 'quad' in join.lower():
            join_match = re.search(r'JOIN\s+(\S+)\s+(\w+)\s+ON', join)
            if join_match:
                table_name = join_match.group(1)
                alias = join_match.group(2)
                # Only include if it's a quad table and alias doesn't look like a term alias
                if 'quad' in table_name.lower() and not re.match(r'[so]_term_\d+', alias):
                    if alias not in quad_aliases:
                        quad_aliases.append(alias)
    
    return quad_aliases


def translate_subquery_pattern(subquery_algebra, table_config: TableConfig,
                             alias_gen: AliasGenerator) -> SQLComponents:
    """
    Translate subquery (nested SELECT) pattern to SQL subquery.
    
    Args:
        subquery_algebra: SPARQL algebra for the subquery
        table_config: Table configuration
        alias_gen: Alias generator for unique aliases
        
    Returns:
        SQLComponents with subquery SQL structure
    """
    logger.debug("Translating subquery pattern")
    
    # This is a placeholder implementation - in practice, this would recursively
    # translate the subquery algebra using the main orchestrator
    subquery_alias = alias_gen.next_subquery_alias()
    
    # For now, return a placeholder structure
    # In a complete implementation, this would:
    # 1. Recursively translate the subquery_algebra
    # 2. Build the appropriate SELECT statement
    # 3. Wrap it as a subquery with proper alias
    
    return SQLComponents(
        from_clause=f"(SELECT * FROM {table_config.quad_table} LIMIT 0) AS {subquery_alias}",
        where_conditions=[],
        joins=[],
        variable_mappings={}  # Would be populated from subquery variables
    )


def find_shared_variables(left_mappings: Dict[Variable, str], 
                        right_mappings: Dict[Variable, str]) -> Set[Variable]:
    """
    Find variables that are shared between two variable mapping dictionaries.
    
    Args:
        left_mappings: Variable mappings from left pattern
        right_mappings: Variable mappings from right pattern
        
    Returns:
        Set of shared Variable objects
    """
    left_vars = set(left_mappings.keys())
    right_vars = set(right_mappings.keys())
    return left_vars & right_vars


def extract_variables_from_triples(triples: List[Tuple]) -> Set[Variable]:
    """
    Extract all variables from a list of RDF triples.
    
    Args:
        triples: List of RDF triples (subject, predicate, object)
        
    Returns:
        Set of Variable objects found in the triples
    """
    variables = set()
    
    for triple in triples:
        for term in triple:
            if isinstance(term, Variable):
                variables.add(term)
    
    return variables


def validate_pattern_structure(pattern) -> bool:
    """
    Validate that a SPARQL pattern has the expected structure.
    
    Args:
        pattern: SPARQL algebra pattern
        
    Returns:
        bool: True if pattern structure is valid
    """
    if not hasattr(pattern, 'name'):
        logger.warning(f"Pattern missing 'name' attribute: {type(pattern)}")
        return False
    
    # Basic validation - could be extended with more specific checks
    return True


def optimize_pattern_sql(sql_components: SQLComponents) -> SQLComponents:
    """
    Apply basic optimizations to SQL components from pattern translation.
    
    Args:
        sql_components: SQL components to optimize
        
    Returns:
        Optimized SQLComponents
    """
    # Remove duplicate WHERE conditions
    unique_conditions = []
    seen_conditions = set()
    
    for condition in sql_components.where_conditions:
        if condition not in seen_conditions:
            unique_conditions.append(condition)
            seen_conditions.add(condition)
    
    # Remove duplicate JOINs
    unique_joins = []
    seen_joins = set()
    
    for join in sql_components.joins:
        if join not in seen_joins:
            unique_joins.append(join)
            seen_joins.add(join)
    
    return SQLComponents(
        from_clause=sql_components.from_clause,
        where_conditions=unique_conditions,
        joins=unique_joins,
        variable_mappings=sql_components.variable_mappings
    )


def estimate_pattern_complexity(sql_components: SQLComponents) -> int:
    """
    Estimate the complexity of a pattern based on its SQL components.
    
    Args:
        sql_components: SQL components to analyze
        
    Returns:
        int: Complexity score (higher = more complex)
    """
    complexity = 0
    
    # Base complexity from number of variables
    complexity += len(sql_components.variable_mappings)
    
    # Add complexity for joins
    complexity += len(sql_components.joins) * 2
    
    # Add complexity for WHERE conditions
    complexity += len(sql_components.where_conditions)
    
    # Add complexity for subqueries (detected by parentheses in FROM clause)
    if sql_components.from_clause and '(' in sql_components.from_clause:
        complexity += 5
    
    return complexity


def merge_sql_components(components_list: List[SQLComponents]) -> SQLComponents:
    """
    Merge multiple SQL components into a single component.
    
    Args:
        components_list: List of SQLComponents to merge
        
    Returns:
        Merged SQLComponents
    """
    if not components_list:
        return SQLComponents("", [], [], {})
    
    if len(components_list) == 1:
        return components_list[0]
    
    # Start with the first component
    merged = components_list[0]
    
    # Merge each subsequent component
    for component in components_list[1:]:
        # Combine WHERE conditions
        merged_conditions = merged.where_conditions + component.where_conditions
        
        # Combine JOINs
        merged_joins = merged.joins + component.joins
        
        # Combine variable mappings (later mappings override earlier ones)
        merged_mappings = merged.variable_mappings.copy()
        merged_mappings.update(component.variable_mappings)
        
        # Use the last non-empty FROM clause
        from_clause = component.from_clause if component.from_clause else merged.from_clause
        
        merged = SQLComponents(
            from_clause=from_clause,
            where_conditions=merged_conditions,
            joins=merged_joins,
            variable_mappings=merged_mappings
        )
    
    return merged


async def translate_algebra_pattern_to_components(pattern, context: SparqlContext, projected_vars: List[Variable] = None, context_constraint: str = None) -> SQLComponents:
    """
    Translate a SPARQL algebra pattern to SQL components.
    This is the main entry point for pattern translation in the refactored architecture.
    
    Args:
        pattern: SPARQL pattern from algebra
        context: Translation context with logger, space_impl, etc.
        projected_vars: List of variables that should be projected in the final query
        context_constraint: Optional context constraint for graph-specific queries
        
    Returns:
        SQLComponents object containing SQL components
    """
    # Extract context components first
    logger = context.logger
    table_config = context.table_config
    alias_gen = context.alias_generator
    
    # DEBUG: Log alias generator state for synchronization debugging
    logger.debug(f"🔧 ALIAS_GEN: Starting pattern translation with quad counter: {alias_gen.counters['quad']}")
    
    logger.info(f"🔍 TRANSLATE_PATTERN: Starting translation for pattern type: {type(pattern).__name__}")
    logger.info(f"🔍 TRANSLATE_PATTERN: Pattern name: {getattr(pattern, 'name', 'NO_NAME')}")
    
    logger.debug(f"Translating pattern type: {pattern.name}")
    pattern_name = pattern.name
    
    if pattern_name == "BGP":  # Basic Graph Pattern
        # Use the existing working generate_bgp_sql function with context constraint support
        from .postgresql_sparql_core import generate_bgp_sql
        
        # Extract triples from the BGP pattern
        triples = pattern.triples if hasattr(pattern, 'triples') else []
        
        if not triples:
            # Empty BGP - return minimal structure with context constraint applied directly to FROM clause
            # Context constraints should not be propagated as WHERE conditions to avoid scope errors in UNION
            # Use alias generator instead of hardcoded q0
            quad_alias = context.alias_generator.next_quad_alias()
            if context_constraint:
                from_clause = f"FROM {table_config.quad_table} {quad_alias} WHERE {quad_alias}.{context_constraint}"
            else:
                from_clause = f"FROM {table_config.quad_table} {quad_alias}"
            return SQLComponents(
                from_clause=from_clause,
                where_conditions=[],
                joins=[],
                variable_mappings={}
            )
        
        # Call the cache-enabled BGP function that supports context constraints
        # Use the cache-enabled function that properly handles context constraints
        # CRITICAL: Use alias generator from context to ensure synchronization
        sql_components = await generate_bgp_sql_with_cache(
            triples, table_config, context.alias_generator, projected_vars, 
            context.term_cache, context.space_impl, context_constraint,
            sparql_context=context
        )
        
        return sql_components
    elif pattern_name == "Filter":
        # Translate nested pattern first
        nested_sql = await translate_algebra_pattern_to_components(pattern.p, context, projected_vars, context_constraint)
        
        # Translate the filter expression using the expressions module
        from .postgresql_sparql_expressions import translate_filter_expression
        
        filter_expr = pattern.expr if hasattr(pattern, 'expr') else None
        if filter_expr:
            logger.debug(f"🔍 FILTER: Translating filter expression: {filter_expr}")
            logger.debug(f"🔍 FILTER: Expression type: {type(filter_expr).__name__}")
            logger.debug(f"🔍 FILTER: Expression name: {getattr(filter_expr, 'name', 'NO_NAME')}")
            logger.debug(f"🔍 FILTER: Variable mappings: {nested_sql.variable_mappings}")
            
            filter_sql = await translate_filter_expression(filter_expr, nested_sql.variable_mappings, sparql_context=context)
            logger.debug(f"🔍 FILTER: Generated SQL: {filter_sql}")
            
            if filter_sql and filter_sql != "1=1":  # Only add meaningful filters
                logger.debug(f"🔍 FILTER: Applying filter to nested SQL")
                # Use the HAVING clause detection logic from translate_filter_pattern
                filtered_sql = translate_filter_pattern(nested_sql, filter_sql)
                logger.debug(f"🔍 FILTER: Result WHERE conditions: {filtered_sql.where_conditions}")
                return filtered_sql
            else:
                logger.warning(f"🔍 FILTER: Filter SQL was empty or trivial: '{filter_sql}'")
        
        return nested_sql
    elif pattern_name == "Union":
        # CRITICAL FIX: Match original implementation exactly
        # Original translates UNION branches WITHOUT context constraints, then applies them separately
        # This prevents context constraints from being applied incorrectly and causing missing results
        
        # Translate both operands WITHOUT context constraints (matching original _translate_pattern)
        left_sql = await translate_algebra_pattern_to_components(pattern.p1, context, projected_vars, None)
        right_sql = await translate_algebra_pattern_to_components(pattern.p2, context, projected_vars, None)
        
        # Get the UNION result
        logger.info(f"🔍 UNION: left_sql type: {type(left_sql)}, right_sql type: {type(right_sql)}")
        union_sql = await translate_union_pattern(left_sql, right_sql, alias_gen)
        logger.info(f"🔍 UNION: union_sql type: {type(union_sql)}, has variable_mappings: {hasattr(union_sql, 'variable_mappings')}")
        
        # Apply context constraints AFTER UNION translation (matching original _translate_pattern_with_context)
        if context_constraint:
            logger.debug(f"Applying context constraint to UNION result: {context_constraint}")
            # Extract quad aliases from the UNION SQL to apply context constraint
            import re
            quad_aliases = set()
            
            # Find all quad table aliases in the UNION SQL
            quad_matches = re.findall(r'FROM\s+\S+\s+(\w+)', union_sql.from_clause or '')
            quad_aliases.update(quad_matches)
            
            # Also check joins for quad aliases
            for join in union_sql.joins:
                join_matches = re.findall(r'FROM\s+\S+\s+(\w+)', join)
                quad_aliases.update(join_matches)
            
            # Apply context constraint to all quad aliases
            additional_where_conditions = []
            for quad_alias in quad_aliases:
                if 'quad' in quad_alias.lower():  # Only apply to quad table aliases
                    additional_where_conditions.append(f"{quad_alias}.{context_constraint}")
                    logger.debug(f"Added context constraint: {quad_alias}.{context_constraint}")
            
            # Combine with existing WHERE conditions
            updated_where_conditions = union_sql.where_conditions + additional_where_conditions
            
            return SQLComponents(
                from_clause=union_sql.from_clause,
                where_conditions=updated_where_conditions,
                joins=union_sql.joins,
                variable_mappings=union_sql.variable_mappings
            )
        
        return union_sql
    elif pattern_name == "LeftJoin":  # OPTIONAL
        # Translate both operands
        required_sql = await translate_algebra_pattern_to_components(pattern.p1, context, projected_vars, context_constraint)
        optional_sql = await translate_algebra_pattern_to_components(pattern.p2, context, projected_vars, context_constraint)
        return await translate_optional_pattern(required_sql, optional_sql, alias_gen)
    elif pattern_name == "Minus":  # MINUS
        # Translate both operands
        main_sql = await translate_algebra_pattern_to_components(pattern.p1, context, projected_vars, context_constraint)
        # CRITICAL FIX: For MINUS exclude patterns, use projected_vars=None to ensure ALL variables
        # in the exclude pattern are mapped, including those only used in FILTER expressions
        exclude_sql = await translate_algebra_pattern_to_components(pattern.p2, context, None, context_constraint)
        shared_vars = find_shared_variables(main_sql.variable_mappings, exclude_sql.variable_mappings)
        return translate_minus_pattern(main_sql, exclude_sql, shared_vars)
    elif pattern_name == "Slice":  # LIMIT/OFFSET
        # Slice wraps another pattern - drill down to the nested pattern
        return await translate_algebra_pattern_to_components(pattern.p, context, projected_vars, context_constraint)
    elif pattern_name == "Project":  # SELECT projection
        # Project wraps another pattern - drill down to the nested pattern
        return await translate_algebra_pattern_to_components(pattern.p, context, projected_vars, context_constraint)
    elif pattern_name == "Distinct":  # SELECT DISTINCT
        # Distinct wraps another pattern - drill down to the nested pattern
        return await translate_algebra_pattern_to_components(pattern.p, context, projected_vars, context_constraint)
    elif pattern_name == "OrderBy":  # ORDER BY
        # OrderBy wraps another pattern - translate the nested pattern first
        nested_sql = await translate_algebra_pattern_to_components(pattern.p, context, projected_vars, context_constraint)
        
        # Extract ORDER BY expressions from the pattern
        order_expressions = []
        if hasattr(pattern, 'expr') and pattern.expr:
            # Single ORDER BY expression
            order_expressions = [pattern.expr]
        elif hasattr(pattern, 'expressions') and pattern.expressions:
            # Multiple ORDER BY expressions
            order_expressions = pattern.expressions
        elif hasattr(pattern, 'order') and pattern.order:
            # Alternative attribute name for order expressions
            order_expressions = pattern.order if isinstance(pattern.order, list) else [pattern.order]
        
        # Translate ORDER BY expressions to SQL
        if order_expressions:
            from .postgresql_sparql_expressions import translate_order_by_expressions
            try:
                order_by_clause = await translate_order_by_expressions(order_expressions, nested_sql.variable_mappings, sparql_context=context)
                if order_by_clause:
                    nested_sql.order_by = order_by_clause
                    logger.debug(f"Added ORDER BY clause: {order_by_clause}")
            except Exception as e:
                logger.warning(f"Error translating ORDER BY expressions: {e}")
        
        return nested_sql
    elif pattern_name == "Graph":  # GRAPH pattern
        # Follow the original implementation structure exactly
        graph_term = pattern.term if hasattr(pattern, 'term') else None
        inner_pattern = pattern.p if hasattr(pattern, 'p') else None
        
        logger.debug(f"Graph term: {graph_term} (type: {type(graph_term)})")
        logger.debug(f"Inner pattern: {inner_pattern}")
        
        # Import Variable and URIRef to check types properly
        from rdflib import Variable, URIRef
        
        if isinstance(graph_term, URIRef):
            # Named graph - resolve URI to UUID (following original implementation)
            logger.debug(f"Processing named graph: {graph_term}")
            graph_text, graph_type = str(graph_term), 'U'
            graph_terms = [(graph_text, graph_type)]
            
            # Get UUID for the graph term
            from vitalgraph.db.postgresql.sparql.postgresql_sparql_cache_integration import get_term_uuids_batch
            graph_uuid_mappings = await get_term_uuids_batch(
                graph_terms, table_config, context.term_cache, context.space_impl,
                sparql_context=context
            )
            
            graph_key = (graph_text, graph_type)
            if graph_key in graph_uuid_mappings:
                context_uuid = graph_uuid_mappings[graph_key]
                context_constraint = f"context_uuid = '{context_uuid}'"
                logger.debug(f"Found graph UUID: {context_uuid}")
                return await translate_algebra_pattern_to_components(inner_pattern, context, projected_vars, context_constraint)
            else:
                # Graph not found - return empty result set (following original implementation)
                logger.warning(f"Graph not found: {graph_text}")
                # Use a condition that will never match any real UUID
                context_constraint = f"context_uuid = '00000000-0000-0000-0000-000000000000'"
                return await translate_algebra_pattern_to_components(inner_pattern, context, projected_vars, context_constraint)
        
        elif isinstance(graph_term, Variable):
            # Variable graph - add JOIN to term table (following original implementation)
            logger.debug(f"Processing variable graph: {graph_term}")
            
            # First translate the inner pattern
            nested_sql = await translate_algebra_pattern_to_components(inner_pattern, context, projected_vars, context_constraint)
            
            # Add graph variable to projected variables if needed (following original _translate_variable_graph)
            if projected_vars is None or graph_term in projected_vars:
                # Create JOIN to term table for graph variable
                context_term_alias = context.alias_generator.next_term_alias("context")
                
                # Extract quad aliases to add context JOINs
                from_clause = nested_sql.from_clause
                import re
                quad_alias_match = re.search(r'FROM\s+\S+\s+(\w+)', from_clause)
                
                if quad_alias_match:
                    first_quad_alias = quad_alias_match.group(1)
                    
                    # Add context term JOIN for the first quad table
                    updated_joins = nested_sql.joins.copy()
                    updated_joins.append(f"JOIN {table_config.term_table} {context_term_alias} ON {first_quad_alias}.context_uuid = {context_term_alias}.term_uuid")
                    
                    # Map graph variable to term text
                    updated_mappings = nested_sql.variable_mappings.copy()
                    updated_mappings[graph_term] = f"{context_term_alias}.term_text"
                    logger.debug(f"Mapped graph variable {graph_term} to {context_term_alias}.term_text")
                    
                    return SQLComponents(
                        from_clause=nested_sql.from_clause,
                        where_conditions=nested_sql.where_conditions,
                        joins=updated_joins,
                        variable_mappings=updated_mappings
                    )
                else:
                    logger.warning(f"Could not extract quad alias from FROM clause: {from_clause}")
            else:
                # Graph variable not projected - no additional JOINs needed
                logger.debug(f"Graph variable {graph_term} not projected - no JOINs added")
            
            return nested_sql
        
        else:
            # Unsupported graph term type - fall back to regular pattern translation
            logger.warning(f"Unsupported graph term type: {type(graph_term)}")
            return await translate_algebra_pattern_to_components(inner_pattern, context, projected_vars, context_constraint)
    elif pattern_name == "Extend":  # BIND statements
        # Process the bind expression and extract variables BEFORE translating nested pattern
        bind_var = pattern.var if hasattr(pattern, 'var') else None
        bind_expr = pattern.expr if hasattr(pattern, 'expr') else None
        
        if bind_var and bind_expr:
            logger.debug(f"Processing Extend/BIND: {bind_var} = {bind_expr}")
            
            # CRITICAL FIX: Extract variables from BIND expression and add to projected_vars
            # This ensures all referenced variables get proper mappings from nested patterns
            extended_projected_vars = list(projected_vars) if projected_vars else []
            if bind_var not in extended_projected_vars:
                extended_projected_vars.append(bind_var)
            
            # Extract all variables referenced in the BIND expression
            bind_expr_vars = _extract_variables_from_expression(bind_expr)
            for var in bind_expr_vars:
                if var not in extended_projected_vars:
                    extended_projected_vars.append(var)
                    logger.debug(f"Added BIND expression variable {var} to projected_vars")
            
            # Now translate nested pattern with extended projected variables
            nested_sql = await translate_algebra_pattern_to_components(pattern.p, context, extended_projected_vars, context_constraint)
            
            # For aggregate result variables, the expression is typically just a reference to __agg_N__
            # We need to map the bind variable to the expression in variable_mappings
            updated_mappings = nested_sql.variable_mappings.copy()
            
            # Use the proper BIND expression translation from the expressions module
            try:
                from vitalgraph.db.postgresql.sparql.postgresql_sparql_expressions import translate_bind_expression
                
                # Check if the bind expression is a simple variable reference (like __agg_1__)
                if hasattr(bind_expr, 'n3') and str(bind_expr).startswith('__agg_'):
                    # This is an aggregate result variable - map it directly
                    if bind_expr in updated_mappings:
                        updated_mappings[bind_var] = updated_mappings[bind_expr]
                        logger.debug(f"Mapped aggregate result {bind_var} to {updated_mappings[bind_expr]}")
                    else:
                        logger.warning(f"Aggregate result variable {bind_expr} not found in mappings")
                        updated_mappings[bind_var] = f"'UNMAPPED_AGG_{bind_expr}'"
                else:
                    # Check if this is an OrderCondition expression that should be handled by OrderBy pattern
                    if hasattr(bind_expr, 'name') and bind_expr.name == 'OrderCondition':
                        logger.debug(f"Skipping OrderCondition expression in BIND pattern - should be handled by OrderBy pattern")
                        # Don't process OrderCondition expressions in BIND context
                        updated_mappings[bind_var] = f"'SKIPPED_ORDER_CONDITION_{bind_var}'"
                    else:
                        # Use the comprehensive BIND expression translator
                        sql_expr = translate_bind_expression(bind_expr, updated_mappings, sparql_context=context)
                        updated_mappings[bind_var] = sql_expr
                        logger.debug(f"Translated BIND expression for {bind_var}: {sql_expr}")
                    
            except Exception as expr_error:
                logger.warning(f"Failed to translate BIND expression for {bind_var}: {expr_error}")
                logger.warning(f"Available mappings were: {list(updated_mappings.keys())}")
                # Fall back to simple string approach
                expr_str = str(bind_expr)
                if hasattr(bind_expr, 'datatype') or (hasattr(bind_expr, 'n3') and not expr_str.startswith('?')):
                    sql_expr = f"'{expr_str}'"
                else:
                    sql_expr = f"'BIND_FAILED_{bind_var}'"
                updated_mappings[bind_var] = sql_expr
            
            return SQLComponents(
                from_clause=nested_sql.from_clause,
                where_conditions=nested_sql.where_conditions,
                joins=nested_sql.joins,
                variable_mappings=updated_mappings
            )
        else:
            logger.warning("Extend pattern missing var or expr")
            # Still need to translate the nested pattern even if bind info is missing
            nested_sql = await translate_algebra_pattern_to_components(pattern.p, context, projected_vars, context_constraint)
            return nested_sql
    elif pattern_name == "SelectQuery":  # Sub-SELECT (subquery)
        return translate_subquery_pattern(pattern, table_config, alias_gen)
    elif pattern_name == "Join":  # JOIN patterns
        # Translate both operands using the shared alias generator from context
        left_sql = await translate_algebra_pattern_to_components(pattern.p1, context, projected_vars, context_constraint)
        right_sql = await translate_algebra_pattern_to_components(pattern.p2, context, projected_vars, context_constraint)
        # Use the alias generator from context to ensure synchronization
        return await translate_join_pattern(left_sql, right_sql, context.alias_generator, sparql_context=context)
    elif pattern_name == "Values":  # VALUES clauses
        return await translate_values_pattern(pattern, projected_vars, sparql_context=context)
    elif pattern_name == "ToMultiSet":  # ToMultiSet can contain VALUES or nested patterns
        # Check if this is a VALUES pattern or a nested pattern wrapper
        if hasattr(pattern, 'p') and pattern.p is not None:
            # ToMultiSet wraps another pattern - drill down to the nested pattern
            logger.debug(f"🔍 ToMultiSet contains nested pattern: {pattern.p}")
            return await translate_algebra_pattern_to_components(pattern.p, context, projected_vars, context_constraint)
        else:
            # This is a VALUES pattern
            logger.debug(f"🔍 ToMultiSet is a VALUES pattern")
            return await translate_values_pattern(pattern, projected_vars, sparql_context=context)
    elif pattern_name == "AggregateJoin":  # Aggregate functions
        # Port the exact original implementation logic
        return await translate_aggregate_join_original(pattern, projected_vars, sparql_context=context)
    elif pattern_name == "Group":  # GROUP BY patterns
        # Port the exact original implementation logic
        return await translate_group_original(pattern, projected_vars, sparql_context=context)
    else:
        logger.warning(f"Pattern type {pattern_name} not fully implemented")
        # Return basic SQL components for unsupported patterns
        # Use alias generator instead of hardcoded q0
        quad_alias = context.alias_generator.next_quad_alias()
        return SQLComponents(
            from_clause=f"FROM {table_config.quad_table} {quad_alias}",
            where_conditions=[],
            joins=[],
            variable_mappings={}
        )


async def translate_aggregate_join_original(agg_pattern, projected_vars: List[Variable] = None, *, sparql_context: SparqlContext = None) -> SQLComponents:
    """Translate AggregateJoin pattern (aggregate functions) to SQL - exact port from original implementation.
    
    AggregateJoin patterns have:
    - A: Array of aggregate functions (Aggregate_Count_, Aggregate_Sum_, etc.)
    - p: The nested pattern (usually Group)
    """
    function_name = "translate_aggregate_join_original"
    
    try:
        # Use SparqlContext for logging and table_config
        if sparql_context:
            logger = sparql_context.logger
            table_config = sparql_context.table_config
            sparql_context.log_function_entry(function_name, pattern_type="AggregateJoin")
        else:
            # Fallback logging and error
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"{function_name}: Starting AggregateJoin pattern translation")
            raise ValueError("SparqlContext is required for translate_aggregate_join_original")
        
        # Get the nested pattern (usually Group)
        nested_pattern = agg_pattern.p
        
        # Get the aggregate functions
        aggregates = agg_pattern.A
        if logger:
            logger.debug(f"Found {len(aggregates)} aggregate functions: {[agg.name for agg in aggregates]}")
        
        # CRITICAL FIX: Extract all aggregate input variables and ensure they're included in projected_vars
        # This ensures that variables like ?age, ?price, ?name get proper SQL column mappings from BGP
        aggregate_input_vars = set()
        for agg in aggregates:
            if hasattr(agg, 'vars') and agg.vars:
                aggregate_input_vars.add(agg.vars)
        
        # Also extract result variables to ensure they're projected (important for graph variables)
        aggregate_result_vars = set()
        for agg in aggregates:
            if hasattr(agg, 'res') and agg.res:
                aggregate_result_vars.add(agg.res)
        
        # Combine original projected_vars with aggregate input and result variables
        extended_projected_vars = list(projected_vars) if projected_vars else []
        for var in aggregate_input_vars:
            if var not in extended_projected_vars:
                extended_projected_vars.append(var)
                if logger:
                    logger.debug(f"Added aggregate input variable {var} to projected_vars")
        
        # For SAMPLE aggregates (like graph variables), we need to ensure the input variable is projected
        for var in aggregate_result_vars:
            if var not in extended_projected_vars:
                extended_projected_vars.append(var)
                if logger:
                    logger.debug(f"Added aggregate result variable {var} to projected_vars")
        
        if logger:
            logger.debug(f"Extended projected_vars for aggregates: {extended_projected_vars}")
        
        # Translate the nested pattern with extended projected variables
        nested_result = await translate_algebra_pattern_to_components(
            nested_pattern, sparql_context, extended_projected_vars
        )
        
        # Check if nested pattern translation failed
        if nested_result is None:
            error_msg = "Nested pattern translation returned None in AggregateJoin pattern"
            if sparql_context:
                sparql_context.log_function_error(function_name, error_msg)
            else:
                logger.error(f"{function_name}: {error_msg}")
            raise ValueError(error_msg)
        
        from_clause = nested_result.from_clause
        where_conditions = nested_result.where_conditions
        joins = nested_result.joins
        variable_mappings = nested_result.variable_mappings
        
        if logger:
            logger.debug(f"AggregateJoin variable mappings from nested pattern: {variable_mappings}")
            logger.debug(f"AggregateJoin projected_vars: {projected_vars}")
        
        # Process each aggregate function
        for agg in aggregates:
            agg_name = agg.name
            agg_var = agg.vars  # Input variable (e.g., ?person)
            result_var = agg.res  # Result variable (e.g., __agg_1__)
            
            if logger:
                logger.debug(f"Processing aggregate {agg_name}: {agg_var} -> {result_var}")
            
            # Translate aggregate function to SQL
            # Handle both "Aggregate_Count_" and "Aggregate_Count" formats
            if agg_name in ["Aggregate_Count_", "Aggregate_Count"]:
                if hasattr(agg, 'distinct') and agg.distinct:
                    # COUNT(DISTINCT ?var)
                    if agg_var in variable_mappings:
                        sql_expr = f"COUNT(DISTINCT {variable_mappings[agg_var]})"
                    else:
                        # COUNT(DISTINCT *) is invalid SQL - use a specific column instead
                        sql_expr = "COUNT(*)"
                        if logger:
                            logger.warning(f"COUNT(DISTINCT) without mapped variable - using COUNT(*) as fallback")
                else:
                    # COUNT(?var) or COUNT(*)
                    if agg_var in variable_mappings:
                        sql_expr = f"COUNT({variable_mappings[agg_var]})"
                    else:
                        sql_expr = "COUNT(*)"
                        
            elif agg_name in ["Aggregate_Sum_", "Aggregate_Sum"]:
                if agg_var in variable_mappings:
                    sql_expr = f"SUM(CAST({variable_mappings[agg_var]} AS DECIMAL))"
                else:
                    sql_expr = f"'UNMAPPED_SUM_{agg_var}'"
                    
            elif agg_name in ["Aggregate_Avg_", "Aggregate_Avg"]:
                if agg_var in variable_mappings:
                    sql_expr = f"AVG(CAST({variable_mappings[agg_var]} AS DECIMAL))"
                else:
                    sql_expr = f"'UNMAPPED_AVG_{agg_var}'"
                    
            elif agg_name in ["Aggregate_Min_", "Aggregate_Min"]:
                if agg_var in variable_mappings:
                    sql_expr = f"MIN({variable_mappings[agg_var]})"
                else:
                    sql_expr = f"'UNMAPPED_MIN_{agg_var}'"
                    
            elif agg_name in ["Aggregate_Max_", "Aggregate_Max"]:
                if agg_var in variable_mappings:
                    sql_expr = f"MAX({variable_mappings[agg_var]})"
                else:
                    sql_expr = f"'UNMAPPED_MAX_{agg_var}'"
                    
            elif agg_name in ["Aggregate_Sample_", "Aggregate_Sample"]:
                # Sample is used for GROUP BY non-aggregated variables
                if agg_var in variable_mappings:
                    sql_expr = variable_mappings[agg_var]
                else:
                    sql_expr = f"'UNMAPPED_SAMPLE_{agg_var}'"
            else:
                if logger:
                    logger.warning(f"Unknown aggregate function: {agg_name}")
                sql_expr = f"'UNKNOWN_AGG_{agg_name}'"
            
            # Store the aggregate result in variable mappings
            variable_mappings[result_var] = sql_expr
            if logger:
                logger.debug(f"Mapped aggregate result {result_var} to SQL: {sql_expr}")
        
        # Return SQLComponents with the aggregate mappings
        return SQLComponents(
            from_clause=from_clause,
            where_conditions=where_conditions,
            joins=joins,
            variable_mappings=variable_mappings
        )
        
    except Exception as e:
        if sparql_context:
            sparql_context.log_function_error(function_name, e)
        else:
            logger.error(f"{function_name}: Error translating AggregateJoin pattern: {e}")
        # Re-raise the exception instead of returning fallback SQLComponents
        raise


async def translate_group_original(group_pattern, projected_vars: List[Variable] = None, *, sparql_context: SparqlContext = None) -> SQLComponents:
    """Translate Group pattern (GROUP BY) to SQL - exact port from original implementation.
    
    Group patterns have:
    - p: The nested pattern to translate
    - expr: The grouping expression (list of variables for GROUP BY)
    """
    function_name = "translate_group_original"
    
    try:
        # Use SparqlContext for logging and table_config
        if sparql_context:
            logger = sparql_context.logger
            table_config = sparql_context.table_config
            sparql_context.log_function_entry(function_name, pattern_type="Group")
        else:
            # Fallback logging and error
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"{function_name}: Starting Group pattern translation")
            raise ValueError("SparqlContext is required for translate_group_original")
        
        # Get the nested pattern
        nested_pattern = group_pattern.p
        
        # Get the grouping expression
        group_expr = getattr(group_pattern, 'expr', None)
        if logger:
            if group_expr:
                logger.debug(f"GROUP BY variables: {group_expr}")
            else:
                logger.debug("No GROUP BY variables (aggregate without grouping)")
        
        # Translate the nested pattern
        nested_result = await translate_algebra_pattern_to_components(
            nested_pattern, sparql_context, projected_vars
        )
        
        # Check if nested pattern translation failed
        if nested_result is None:
            error_msg = "Nested pattern translation returned None in Group pattern"
            if sparql_context:
                sparql_context.log_function_error(function_name, error_msg)
            else:
                logger.error(f"{function_name}: {error_msg}")
            raise ValueError(error_msg)
        
        from_clause = nested_result.from_clause
        where_conditions = nested_result.where_conditions
        joins = nested_result.joins
        variable_mappings = nested_result.variable_mappings
        
        # Store GROUP BY information in variable_mappings for later use
        # We'll use this in _build_select_clause to add GROUP BY clause
        if group_expr:
            # Store the GROUP BY variables for later SQL generation
            variable_mappings['__GROUP_BY_VARS__'] = group_expr
            if logger:
                logger.debug(f"Stored GROUP BY variables: {group_expr}")
        
        return SQLComponents(
            from_clause=from_clause,
            where_conditions=where_conditions,
            joins=joins,
            variable_mappings=variable_mappings
        )
        
    except Exception as e:
        if sparql_context:
            sparql_context.log_function_error(function_name, e)
        else:
            logger.error(f"{function_name}: Error translating Group pattern: {e}")
        # Re-raise the exception instead of returning fallback SQLComponents
        raise


# translate_algebra_pattern wrapper function removed - redundant with translate_algebra_pattern_to_components
# All active code paths use translate_algebra_pattern_to_components directly


def get_pattern_complexity(pattern) -> int:
    """
    Calculate the complexity score of a SPARQL pattern.
    
    Args:
        pattern: SPARQL algebra pattern
        
    Returns:
        Complexity score (higher = more complex)
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
        complexity += get_pattern_complexity(pattern.p)
    if hasattr(pattern, 'p1'):
        complexity += get_pattern_complexity(pattern.p1)
    if hasattr(pattern, 'p2'):
        complexity += get_pattern_complexity(pattern.p2)
    
    return complexity


def _extract_variables_from_expression(expr):
    """Extract all variables referenced in a SPARQL expression.
    
    This is critical for BIND+OPTIONAL bug fix - ensures that all variables
    used in BIND expressions are included in projected_vars so they get
    proper mappings from OPTIONAL patterns.
    
    Ported from original PostgreSQLSparqlImpl._extract_variables_from_expression
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
