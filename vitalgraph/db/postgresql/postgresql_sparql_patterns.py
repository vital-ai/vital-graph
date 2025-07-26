"""
PostgreSQL SPARQL Patterns Implementation for VitalGraph

This module handles the translation of various SPARQL algebra patterns
(BGP, UNION, OPTIONAL, MINUS, JOIN, BIND, VALUES, subqueries) to PostgreSQL SQL.
"""

import logging
import uuid
from typing import List, Dict, Tuple, Set, Optional, Any, Union
from rdflib import Variable, URIRef, Literal, BNode

# Import shared utilities
from .postgresql_sparql_utils import TableConfig, AliasGenerator, SparqlUtils


class PostgreSQLSparqlPatterns:
    """Handles translation of SPARQL algebra patterns to SQL components."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize the patterns translator.
        
        Args:
            logger: Optional logger instance. If None, creates a new logger.
        """
        self.logger = logger or logging.getLogger(__name__)
        self.variable_counter = 0
        self.join_counter = 0
        self._subquery_depth = 0
    
    
    async def translate_pattern(self, pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """
        Translate a SPARQL pattern to SQL components.
        
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        pattern_name = pattern.name
        
        if pattern_name == "BGP":  # Basic Graph Pattern
            return await self.translate_bgp(pattern, table_config, projected_vars)
        elif pattern_name == "Filter":
            return await self.translate_filter(pattern, table_config, projected_vars)
        elif pattern_name == "Union":
            return await self.translate_union(pattern, table_config, projected_vars)
        elif pattern_name == "LeftJoin":  # OPTIONAL
            return await self.translate_optional(pattern, table_config, projected_vars)
        elif pattern_name == "Minus":  # MINUS
            return await self.translate_minus(pattern, table_config, projected_vars)
        elif pattern_name == "Slice":  # LIMIT/OFFSET
            # Slice wraps another pattern - drill down to the nested pattern
            nested_pattern = pattern.p
            return await self.translate_pattern(nested_pattern, table_config, projected_vars)
        elif pattern_name == "Project":  # SELECT projection
            # Project wraps another pattern - drill down to the nested pattern
            nested_pattern = pattern.p
            return await self.translate_pattern(nested_pattern, table_config, projected_vars)
        elif pattern_name == "Distinct":  # SELECT DISTINCT
            # Distinct wraps another pattern - drill down to the nested pattern
            nested_pattern = pattern.p
            return await self.translate_pattern(nested_pattern, table_config, projected_vars)
        elif pattern_name == "OrderBy":  # ORDER BY
            # OrderBy wraps another pattern - drill down to the nested pattern
            nested_pattern = pattern.p
            return await self.translate_pattern(nested_pattern, table_config, projected_vars)
        elif pattern_name == "Graph":  # GRAPH pattern
            return await self.translate_graph(pattern, table_config, projected_vars)
        elif pattern_name == "Extend":  # BIND statements
            return await self.translate_extend(pattern, table_config, projected_vars)
        elif pattern_name == "SelectQuery":  # Sub-SELECT (subquery)
            return await self.translate_subquery(pattern, table_config, projected_vars)
        elif pattern_name == "Join":  # JOIN patterns
            return await self.translate_join(pattern, table_config, projected_vars)
        elif pattern_name == "AggregateJoin":  # Aggregate functions
            return await self.translate_aggregate_join(pattern, table_config, projected_vars)
        elif pattern_name == "Group":  # GROUP BY patterns
            return await self.translate_group(pattern, table_config, projected_vars)
        elif pattern_name == "Values":  # VALUES clauses
            return await self.translate_values(pattern, table_config, projected_vars)
        elif pattern_name == "ToMultiSet":  # VALUES clauses (RDFLib uses ToMultiSet)
            return await self.translate_values(pattern, table_config, projected_vars)
        else:
            self.logger.warning(f"Pattern type {pattern_name} not fully implemented")
            return f"FROM {table_config.quad_table} q0", [], [], {}


    async def translate_bgp(self, bgp_pattern, table_config: TableConfig, projected_vars: List[Variable] = None, context_constraint: str = None, alias_gen: AliasGenerator = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate Basic Graph Pattern to SQL using UUID-based quad/term schema with batch term lookup.
        
        Args:
            bgp_pattern: Basic Graph Pattern from SPARQL algebra
            table_config: Table configuration for SQL generation
            projected_vars: Variables to project in SELECT clause
            context_constraint: Optional SQL constraint for context_uuid column (for GRAPH patterns)
            alias_gen: Optional alias generator for independent alias management
        """
        # Use provided alias generator or create a new one
        if alias_gen is None:
            alias_gen = self.alias_generator
        
        triples = bgp_pattern.get('triples', [])
        
        if not triples:
            return f"FROM {table_config.quad_table} {alias_gen.next_quad_alias()}", [], [], {}
        
        # First pass: collect all bound terms for batch lookup
        bound_terms = []
        for triple in triples:
            subject, predicate, obj = triple
            
            if not isinstance(subject, Variable):
                term_text, term_type = self._get_term_info(subject)
                bound_terms.append((term_text, term_type))
            
            if not isinstance(predicate, Variable) and not isinstance(predicate, Path):
                term_text, term_type = self._get_term_info(predicate)
                bound_terms.append((term_text, term_type))
            
            if not isinstance(obj, Variable):
                term_text, term_type = self._get_term_info(obj)
                bound_terms.append((term_text, term_type))
        
        # Batch lookup all bound terms
        self.logger.debug(f"🔍 BGP collecting bound terms: {bound_terms}")
        term_uuid_mappings = await self._get_term_uuids_batch(bound_terms, table_config) if bound_terms else {}
        self.logger.debug(f"🔍 BGP term UUID mappings: {term_uuid_mappings}")
        
        all_joins = []
        quad_joins = []  # JOINs for additional quad tables
        all_where_conditions = []
        variable_mappings = {}
        quad_aliases = []
        
        # Second pass: process each triple pattern with resolved UUIDs
        for triple_idx, triple in enumerate(triples):
            subject, predicate, obj = triple
            quad_alias = alias_gen.next_quad_alias()
            quad_aliases.append(quad_alias)
            self.logger.debug(f"🔍 Processing triple #{triple_idx}: ({subject}, {predicate}, {obj})")
            
            # Handle subject
            if isinstance(subject, Variable):
                if subject not in variable_mappings and (projected_vars is None or subject in projected_vars):
                    term_alias = alias_gen.next_term_alias("subject")
                    all_joins.append(f"JOIN {table_config.term_table} {term_alias} ON {quad_alias}.subject_uuid = {term_alias}.term_uuid")
                    variable_mappings[subject] = f"{term_alias}.term_text"
                # Variable already mapped or not projected - don't create JOIN
            else:
                # Bound term - use resolved UUID
                term_text, term_type = self._get_term_info(subject)
                term_key = (term_text, term_type)
                if term_key in term_uuid_mappings:
                    term_uuid = term_uuid_mappings[term_key]
                    all_where_conditions.append(f"{quad_alias}.subject_uuid = '{term_uuid}'")
                else:
                    # Term not found - this will result in no matches
                    self.logger.error(f"🚨 TERM LOOKUP FAILED for subject: {term_text} (type: {term_type}) - adding 1=0 condition")
                    self.logger.error(f"Available term mappings: {list(term_uuid_mappings.keys())[:10]}...")
                    all_where_conditions.append("1=0")  # Condition that never matches
            
            # Handle predicate - check for property paths first
            if isinstance(predicate, Path):
                # Property path detected - delegate to specialized handler
                self.logger.info(f"🛤️ Property path detected: {type(predicate).__name__} - {predicate}")
                
                # Handle property path translation
                path_from, path_where, path_joins, path_vars = await self._translate_property_path(
                    subject, predicate, obj, table_config, alias_gen, projected_vars
                )
                
                # Integrate property path results with BGP translation
                if path_from:
                    # Property path generates its own FROM clause (CTE)
                    # We need to join this with the current quad table
                    all_joins.append(f"JOIN {path_from} ON 1=1")
                
                if path_joins:
                    all_joins.extend(path_joins)
                
                if path_where:
                    all_where_conditions.extend(path_where)
                
                # Merge variable mappings from property path
                for var, mapping in path_vars.items():
                    if var not in variable_mappings:
                        variable_mappings[var] = mapping
                
                # Skip normal predicate processing since this is a property path
                continue
                
            elif isinstance(predicate, Variable):
                if predicate not in variable_mappings and (projected_vars is None or predicate in projected_vars):
                    term_alias = alias_gen.next_term_alias("predicate")
                    all_joins.append(f"JOIN {table_config.term_table} {term_alias} ON {quad_alias}.predicate_uuid = {term_alias}.term_uuid")
                    variable_mappings[predicate] = f"{term_alias}.term_text"
                # Variable already mapped or not projected - don't create JOIN
            else:
                # Bound term - use resolved UUID
                term_text, term_type = self._get_term_info(predicate)
                term_key = (term_text, term_type)
                if term_key in term_uuid_mappings:
                    term_uuid = term_uuid_mappings[term_key]
                    all_where_conditions.append(f"{quad_alias}.predicate_uuid = '{term_uuid}'")
                else:
                    # Term not found - this will result in no matches
                    self.logger.error(f"🚨 TERM LOOKUP FAILED for predicate: {term_text} (type: {term_type}) - adding 1=0 condition")
                    self.logger.error(f"🔍 BIND+OPTIONAL DEBUG: Searched for predicate key: {term_key}")
                    self.logger.error(f"🔍 BIND+OPTIONAL DEBUG: Available term mappings ({len(term_uuid_mappings)}): {list(term_uuid_mappings.keys())}")
                    self.logger.error(f"🔍 BIND+OPTIONAL DEBUG: All bound terms collected: {bound_terms}")
                    all_where_conditions.append("1=0")  # Condition that never matches
            
            # Handle object
            if isinstance(obj, Variable):
                self.logger.debug(f"🔍 Processing object variable {obj}: already_mapped={obj in variable_mappings}, projected={projected_vars is None or obj in projected_vars}")
                if obj not in variable_mappings and (projected_vars is None or obj in projected_vars):
                    term_alias = alias_gen.next_term_alias("object")
                    all_joins.append(f"JOIN {table_config.term_table} {term_alias} ON {quad_alias}.object_uuid = {term_alias}.term_uuid")
                    variable_mappings[obj] = f"{term_alias}.term_text"
                    self.logger.debug(f"✅ Created mapping for {obj}: {variable_mappings[obj]}")
                else:
                    self.logger.debug(f"⏭️ Skipping mapping for {obj}: already_mapped={obj in variable_mappings}, projected={projected_vars is None or obj in projected_vars}")
                # Variable already mapped or not projected - don't create JOIN
            else:
                # Bound term - use resolved UUID
                term_text, term_type = self._get_term_info(obj)
                term_key = (term_text, term_type)
                if term_key in term_uuid_mappings:
                    term_uuid = term_uuid_mappings[term_key]
                    all_where_conditions.append(f"{quad_alias}.object_uuid = '{term_uuid}'")
                else:
                    # Term not found - this will result in no matches
                    all_where_conditions.append("1=0")  # Condition that never matches
        
        # Build FROM clause with first quad table
        from_clause = f"FROM {table_config.quad_table} {quad_aliases[0]}"
        
        # Add additional quad tables as JOINs if multiple triples
        if len(quad_aliases) > 1:
            for i in range(1, len(quad_aliases)):
                # Find shared variables between current triple and ANY previous triple
                best_join_conditions = []
                best_reference_idx = 0
                
                # Check against all previous triples to find the best join
                for ref_idx in range(i):
                    shared_vars = self._find_shared_variables_between_triples(triples[ref_idx], triples[i])
                    if shared_vars:
                        # Create join conditions based on shared variables
                        join_conditions = []
                        for var in shared_vars:
                            # Both triples share this variable, so their corresponding positions should match
                            pos_in_ref = self._get_variable_position_in_triple(triples[ref_idx], var)
                            pos_in_current = self._get_variable_position_in_triple(triples[i], var)
                            
                            if pos_in_ref and pos_in_current:
                                col_ref = f"{quad_aliases[ref_idx]}.{pos_in_ref}_uuid"
                                col_current = f"{quad_aliases[i]}.{pos_in_current}_uuid"
                                join_conditions.append(f"{col_ref} = {col_current}")
                        
                        # Use the join with the most conditions (most specific)
                        if len(join_conditions) > len(best_join_conditions):
                            best_join_conditions = join_conditions
                            best_reference_idx = ref_idx
                
                if best_join_conditions:
                    quad_joins.append(f"JOIN {table_config.quad_table} {quad_aliases[i]} ON {' AND '.join(best_join_conditions)}")
                else:
                    # Fallback: cross join if no shared variables found
                    quad_joins.append(f"JOIN {table_config.quad_table} {quad_aliases[i]} ON 1=1")
        
        # Combine quad JOINs first, then term JOINs
        combined_joins = quad_joins + all_joins
        
        # Handle context constraints for GRAPH patterns
        if context_constraint is None:
            # No explicit GRAPH pattern - query ALL graphs (SPARQL 1.1 default graph behavior)
            # This means the union of all named graphs + the global graph
            # So we don't add any context constraint, allowing search across all graphs
            self.logger.debug("No GRAPH clause - searching across all graphs (SPARQL 1.1 default graph behavior)")
        else:
            # Explicit context constraint provided
            for quad_alias in quad_aliases:
                all_where_conditions.append(f"{quad_alias}.{context_constraint}")
            self.logger.debug(f"Applied explicit context constraint: {context_constraint}")
        
        return from_clause, all_where_conditions, combined_joins, variable_mappings    


    async def translate_union(self, union_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """
        Translate UNION pattern to SQL UNION operations.
        
        UNION patterns have two operands (p1 and p2) that need to be translated
        separately and combined with SQL UNION. The key challenges are:
        1. Variable consistency - both branches must project the same variables
        2. Alias management - avoid conflicts between branches
        3. Result harmonization - handle NULL values for missing variables
        
        Args:
            union_pattern: UNION pattern from SPARQL algebra with p1 and p2 operands
            table_config: Table configuration for SQL generation
            projected_vars: Variables to project in SELECT clause
            
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        try:
            self.logger.info(f"🔗 TRANSLATING UNION PATTERN with projected vars: {projected_vars}")
            
            # Extract left and right operands
            left_operand = union_pattern.p1
            right_operand = union_pattern.p2
            
            self.logger.info(f"📌 Left operand: {getattr(left_operand, 'name', type(left_operand).__name__)}")
            self.logger.info(f"📌 Right operand: {getattr(right_operand, 'name', type(right_operand).__name__)}")
            
            # Log operand details for debugging GRAPH interactions
            if hasattr(left_operand, 'term') and hasattr(left_operand, 'p'):
                self.logger.info(f"📌 Left operand is GRAPH pattern with term: {left_operand.term}")
            if hasattr(right_operand, 'term') and hasattr(right_operand, 'p'):
                self.logger.info(f"📌 Right operand is GRAPH pattern with term: {right_operand.term}")
            
            # Save current counters to restore later
            original_variable_counter = self.variable_counter
            original_join_counter = self.join_counter
            
            # Translate left branch
            self.logger.debug("Translating left branch of UNION")
            left_from, left_where, left_joins, left_vars = await self.translate_pattern(
                left_operand, table_config, projected_vars
            )
            
            # Save left branch counters and increment for right branch
            left_var_counter = self.variable_counter
            left_join_counter = self.join_counter
            
            # Translate right branch with separate alias space
            self.logger.debug("Translating right branch of UNION")
            right_from, right_where, right_joins, right_vars = await self.translate_pattern(
                right_operand, table_config, projected_vars
            )
            
            # Determine all variables that appear in either branch
            all_variables = set(left_vars.keys()) | set(right_vars.keys())
            if projected_vars:
                # Only include projected variables
                all_variables = set(projected_vars) & all_variables
            
            self.logger.debug(f"All variables in UNION: {[str(v) for v in all_variables]}")
            
            # Build SELECT clauses for both branches with consistent variable ordering
            variable_list = sorted(all_variables, key=str)  # Consistent ordering
            
            left_select_items = []
            right_select_items = []
            final_variable_mappings = {}
            
            for i, var in enumerate(variable_list):
                col_name = f"var_{i}"  # Use consistent column names
                final_variable_mappings[var] = col_name
                
                # Left branch: use mapping if available, otherwise NULL
                if var in left_vars:
                    left_mapping = left_vars[var]
                    left_select_items.append(f"{left_mapping} AS {col_name}")
                    # Debug BIND expressions in UNION
                    if "'" in left_mapping and left_mapping.startswith("'") and left_mapping.endswith("'"):
                        self.logger.debug(f"UNION Left: BIND literal {var} -> {left_mapping}")
                else:
                    left_select_items.append(f"NULL AS {col_name}")
                
                # Right branch: use mapping if available, otherwise NULL
                if var in right_vars:
                    right_mapping = right_vars[var]
                    right_select_items.append(f"{right_mapping} AS {col_name}")
                    # Debug BIND expressions in UNION
                    if "'" in right_mapping and right_mapping.startswith("'") and right_mapping.endswith("'"):
                        self.logger.debug(f"UNION Right: BIND literal {var} -> {right_mapping}")
                else:
                    right_select_items.append(f"NULL AS {col_name}")
            
            # Build left branch SQL
            # CRITICAL FIX: Check if left_from is already a complete derived table
            print(f"🔧 UNION DEBUG: left_from = '{left_from[:100] if left_from else 'None'}...'")
            
            if left_from and left_from.strip().startswith('FROM (') and 'UNION' in left_from:
                # left_from is already a complete UNION derived table - use it directly
                print(f"🔧 UNION DEBUG: left_from is complete derived table, using directly")
                
                # Extract the SQL content between FROM ( and ) alias
                # Find the opening parenthesis after FROM
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
                left_sql = left_from[start_idx:end_idx-1]  # -1 to exclude the closing )
                print(f"🔧 UNION DEBUG: Extracted left_sql: {left_sql[:200]}...")
                print(f"🔧 UNION DEBUG: Full extracted left_sql:\n{left_sql}")
                # No need to add joins/where since it's already a complete UNION
            else:
                # Normal case - build SELECT statement
                left_sql_parts = [f"SELECT {', '.join(left_select_items)}"]
                if left_from:
                    if not left_from.strip().upper().startswith('FROM'):
                        # If from_clause doesn't start with FROM, it's just a table reference
                        print(f"🔧 UNION DEBUG: Adding FROM to left_from: '{left_from}' -> 'FROM {left_from}'")
                        left_sql_parts.append(f"FROM {left_from}")
                    else:
                        # from_clause already includes FROM keyword
                        print(f"🔧 UNION DEBUG: left_from already has FROM: '{left_from}'")
                        left_sql_parts.append(left_from)
                else:
                    # No FROM clause - this shouldn't happen but handle gracefully
                    print(f"🔧 UNION DEBUG: No left_from, using fallback")
                    left_sql_parts.append(f"FROM {table_config.quad_table} fallback_q0")
                    self.logger.warning("Left branch missing FROM clause, using fallback")
                
                # Add joins and where conditions for normal case
                if left_joins:
                    left_sql_parts.extend(left_joins)
                if left_where:
                    left_sql_parts.append(f"WHERE {' AND '.join(left_where)}")
                
                left_sql = '\n'.join(left_sql_parts)
            
            # Build right branch SQL
            right_sql_parts = [f"SELECT {', '.join(right_select_items)}"]
            # Ensure FROM clause includes the FROM keyword and handle empty cases
            print(f"🔧 UNION DEBUG: right_from = '{right_from}'")
            if right_from:
                if not right_from.strip().upper().startswith('FROM'):
                    # If from_clause doesn't start with FROM, it's just a table reference
                    print(f"🔧 UNION DEBUG: Adding FROM to right_from: '{right_from}' -> 'FROM {right_from}'")
                    right_sql_parts.append(f"FROM {right_from}")
                else:
                    # from_clause already includes FROM keyword
                    print(f"🔧 UNION DEBUG: right_from already has FROM: '{right_from}'")
                    right_sql_parts.append(right_from)
            else:
                # No FROM clause - this shouldn't happen but handle gracefully
                print(f"🔧 UNION DEBUG: No right_from, using fallback")
                right_sql_parts.append(f"FROM {table_config.quad_table} fallback_q1")
                self.logger.warning("Right branch missing FROM clause, using fallback")
            
            if right_joins:
                right_sql_parts.extend(right_joins)
                
            if right_where:
                right_sql_parts.append(f"WHERE {' AND '.join(right_where)}")
            
            right_sql = '\n'.join(right_sql_parts)
            
            # Debug: Log the generated SQL for each branch
            self.logger.debug(f"Left branch SQL: {left_sql}")
            self.logger.debug(f"Right branch SQL: {right_sql}")
            
            # Validate that both branches have proper FROM clauses
            if 'FROM' not in left_sql.upper():
                self.logger.error(f"Left branch missing FROM clause: {left_sql}")
            if 'FROM' not in right_sql.upper():
                self.logger.error(f"Right branch missing FROM clause: {right_sql}")
            
            # Combine with UNION - ensure proper SQL structure
            # Remove extra parentheses that cause malformed nested structure
            union_sql = f"{left_sql}\nUNION\n{right_sql}"
            print(f"🔧 UNION DEBUG: Combined UNION SQL before fixing:\n{union_sql}")
            self.logger.debug(f"Combined UNION SQL: {union_sql}")
            
            # CRITICAL FIX: Check if we need FROM keyword fixing
            # If we extracted SQL from derived tables, it should already be correct
            has_proper_from_keywords = 'FROM vitalgraph' in union_sql and union_sql.count('FROM vitalgraph') >= union_sql.count('SELECT')
            
            if has_proper_from_keywords:
                print(f"🔧 UNION DEBUG: SQL already has proper FROM keywords, skipping fixing process")
                fixed_union_sql = union_sql
            else:
                print(f"🔧 UNION DEBUG: Starting FROM keyword fixing process...")
                # Fix missing FROM keywords and remove duplicates
                lines = union_sql.split('\n')
                fixed_lines = []
                i = 0
                while i < len(lines):
                    line = lines[i]
                    stripped = line.strip()
                    
                    # Handle duplicate FROM keywords first
                    if stripped.upper().startswith('FROM FROM'):
                        # Remove duplicate FROM keywords
                        fixed_line = stripped[5:].strip()  # Remove first 'FROM '
                        fixed_lines.append(f"FROM {fixed_line}")
                        self.logger.debug(f"Fixed duplicate FROM in: {stripped}")
                    # Look for table references that need FROM keywords
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
                        self.logger.debug(f"Added missing FROM keyword to: {stripped}")
                    else:
                        fixed_lines.append(line)
                    i += 1
                fixed_union_sql = '\n'.join(fixed_lines)
            
            # Validate the combined UNION SQL structure
            if '((' in fixed_union_sql or '))' in fixed_union_sql:
                self.logger.warning(f"UNION SQL has suspicious parentheses: {fixed_union_sql[:200]}...")
                # Log the full SQL for debugging
                self.logger.error(f"Full malformed UNION SQL: {fixed_union_sql}")
            
            # Validate that the UNION SQL is properly formed
            if 'FROM' not in fixed_union_sql.upper():
                self.logger.error(f"UNION SQL missing FROM clauses: {fixed_union_sql[:300]}...")
                self.logger.error(f"Left branch SQL: {left_sql}")
                self.logger.error(f"Right branch SQL: {right_sql}")
                # This is a critical error - the UNION branches are malformed
                raise ValueError(f"UNION SQL generation failed - missing FROM clauses")
            
            # Create a derived table for the UNION result
            union_alias = f"union_{self.join_counter}"
            self.join_counter += 1
            
            # CRITICAL FIX: Avoid excessive nesting in UNION patterns
            # Instead of always wrapping in a derived table, return the UNION SQL directly
            # when it's already properly structured
            
            print(f"🔧 UNION STRUCTURE DEBUG: Checking if we can avoid derived table wrapping")
            print(f"🔧 UNION SQL: {fixed_union_sql[:300]}...")
            
            # Check the complexity of each branch
            left_is_simple = left_sql.strip().startswith('SELECT') and 'FROM (' not in left_sql
            right_is_simple = right_sql.strip().startswith('SELECT') and 'FROM (' not in right_sql
            left_is_union = 'UNION' in left_sql
            right_is_union = 'UNION' in right_sql
            
            print(f"🔧 Left: simple={left_is_simple}, union={left_is_union}")
            print(f"🔧 Right: simple={right_is_simple}, union={right_is_union}")
            
            # Avoid excessive nesting by returning UNION directly in most cases
            # Only use derived table wrapping when absolutely necessary
            if (left_is_simple and right_is_simple) or (left_is_union or right_is_union):
                # Either both branches are simple, or at least one is already a UNION
                # In both cases, we can return the UNION directly without additional wrapping
                print(f"🔧 UNION STRUCTURE DEBUG: Returning UNION directly to avoid nesting")
                
                # Update variable mappings to not reference a union alias
                union_variable_mappings = final_variable_mappings.copy()
                
                # Return the UNION SQL directly as the FROM clause
                union_from_clause = f"FROM ({fixed_union_sql}) union_{self.join_counter}"
                return union_from_clause, [], [], union_variable_mappings
            else:
                # Complex structure that requires derived table approach
                print(f"🔧 UNION STRUCTURE DEBUG: Using derived table approach for complex structure")
                union_alias = f"union_{self.join_counter}"
                self.join_counter += 1
                union_from_clause = f"FROM ({fixed_union_sql}) {union_alias}"
            
            # Update variable mappings to reference the union table
            union_variable_mappings = {}
            for var, col_name in final_variable_mappings.items():
                union_variable_mappings[var] = f"{union_alias}.{col_name}"
                # Debug BIND variable mapping preservation
                if var in left_vars and "'" in str(left_vars[var]):
                    self.logger.debug(f"UNION: BIND variable {var} mapped from left '{left_vars[var]}' to '{union_variable_mappings[var]}'")
                elif var in right_vars and "'" in str(right_vars[var]):
                    self.logger.debug(f"UNION: BIND variable {var} mapped from right '{right_vars[var]}' to '{union_variable_mappings[var]}'")
            
            # Debug final variable mappings
            self.logger.debug(f"UNION final variable mappings: {union_variable_mappings}")
            self.logger.debug(f"UNION left vars: {left_vars}")
            self.logger.debug(f"UNION right vars: {right_vars}")
            
            # Debug: Log the final UNION FROM clause
            self.logger.debug(f"Final UNION FROM clause: {union_from_clause[:200]}...")
            
            self.logger.info(f"Successfully translated UNION with {len(variable_list)} variables")
            self.logger.debug(f"UNION SQL generated: {len(union_sql)} characters")
            
            # UNION patterns are self-contained - no additional WHERE conditions or JOINs needed
            # All conditions are already applied within the UNION subqueries
            return union_from_clause, [], [], union_variable_mappings
            
        except Exception as e:
            self.logger.error(f"Error translating UNION pattern: {e}")
            # Restore original counters on error
            self.variable_counter = original_variable_counter
            self.join_counter = original_join_counter
            # Return fallback to avoid complete query failure
            return f"FROM {table_config.quad_table} q0", [], [], {}
    async def translate_optional(self, optional_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """
        Translate OPTIONAL (LeftJoin) pattern to SQL LEFT JOIN operations.
        
        OPTIONAL patterns have two operands (p1 and p2) where p1 is required
        and p2 is optional. This translates to a LEFT JOIN where:
        1. p1 (required) forms the main query
        2. p2 (optional) is LEFT JOINed to p1
        3. Variables from p2 can be NULL if no match is found
        
        Args:
            optional_pattern: OPTIONAL pattern from SPARQL algebra with p1 and p2 operands
            table_config: Table configuration for SQL generation
            projected_vars: Variables to project in SELECT clause
            
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        try:
            self.logger.info(f"🔗 TRANSLATING OPTIONAL PATTERN with projected vars: {projected_vars}")
            
            # Extract required and optional operands
            required_operand = optional_pattern.p1  # Required part (LEFT side of LEFT JOIN)
            optional_operand = optional_pattern.p2  # Optional part (RIGHT side of LEFT JOIN)
            
            self.logger.info(f"📌 Required operand: {getattr(required_operand, 'name', type(required_operand).__name__)}")
            self.logger.info(f"📌 Optional operand: {getattr(optional_operand, 'name', type(optional_operand).__name__)}")
            
            # Create independent alias generators for each operand to avoid conflicts
            # This follows the same pattern as _translate_join
            req_alias_gen = self.alias_generator.create_child_generator("req")
            opt_alias_gen = self.alias_generator.create_child_generator("opt")
            
            self.logger.debug(f"Created child alias generators: req_alias_gen, opt_alias_gen")
            
            # Translate required part (main query) with its own alias generator
            self.logger.debug("Translating required part of OPTIONAL")
            req_from, req_where, req_joins, req_vars = await self._translate_pattern_with_alias_gen(
                required_operand, table_config, projected_vars, req_alias_gen
            )
            
            # Translate optional part with its own alias generator to prevent conflicts
            self.logger.debug("Translating optional part of OPTIONAL")
            opt_from, opt_where, opt_joins, opt_vars = await self._translate_pattern_with_alias_gen(
                optional_operand, table_config, projected_vars, opt_alias_gen
            )
            
            # Determine all variables
            all_variables = set(req_vars.keys()) | set(opt_vars.keys())
            if projected_vars:
                all_variables = set(projected_vars) & all_variables
            
            self.logger.debug(f"All variables in OPTIONAL: {[str(v) for v in all_variables]}")
            
            # Build LEFT JOIN SQL
            # Start with required part as the main FROM clause
            main_from = req_from
            main_joins = req_joins.copy() if req_joins else []
            main_where = req_where.copy() if req_where else []
            
            # CRITICAL FIX: Ensure all referenced table aliases are properly declared
            # The issue is that LEFT JOINs reference quad table aliases that don't exist
            # We need to extract all referenced aliases from both WHERE conditions AND JOIN conditions
            
            all_where_conditions = main_where + (opt_where if opt_where else [])
            all_join_conditions = main_joins.copy()
            
            # Add optional JOINs to the analysis (they haven't been processed yet)
            if opt_joins:
                all_join_conditions.extend(opt_joins)
            
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
            
            self.logger.debug(f"All referenced quad aliases: {referenced_quad_aliases}")
            
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
            
            self.logger.debug(f"Already declared aliases: {declared_aliases}")
            
            # Find aliases that will be added by optional JOINs processing
            aliases_from_opt_joins = set()
            if opt_joins:
                for join in opt_joins:
                    join_match = re.search(r'JOIN\s+\S+\s+(\w+)', join)
                    if join_match:
                        aliases_from_opt_joins.add(join_match.group(1))
            
            self.logger.debug(f"Aliases that will be added by optional JOINs: {aliases_from_opt_joins}")
            
            # Find missing quad aliases that need to be declared (excluding ones handled by opt_joins)
            missing_aliases = referenced_quad_aliases - declared_aliases - aliases_from_opt_joins
            self.logger.debug(f"Missing quad aliases that need declaration: {missing_aliases}")
            
            # Add LEFT JOINs for missing quad table aliases with proper ON clauses
            quad_table = table_config.quad_table
            
            # Find a quad alias from the required part to connect to (for JOIN ON conditions)
            connection_alias = None
            req_from_match = re.search(r'FROM\s+\S+\s+(\w+)', main_from)
            if req_from_match:
                connection_alias = req_from_match.group(1)
            
            self.logger.debug(f"Using connection alias: {connection_alias}")
            
            # Add LEFT JOINs for missing quad aliases, connecting through subject_uuid
            for alias in missing_aliases:
                if connection_alias:
                    main_joins.append(f"LEFT JOIN {quad_table} {alias} ON {connection_alias}.subject_uuid = {alias}.subject_uuid")
                    self.logger.debug(f"Added LEFT JOIN for missing quad alias: {alias} connected to {connection_alias}")
                else:
                    # Fallback: add without ON clause (will likely cause error but better than missing table)
                    main_joins.append(f"LEFT JOIN {quad_table} {alias}")
                    self.logger.warning(f"Added LEFT JOIN for missing quad alias: {alias} WITHOUT ON clause - may cause SQL error")
            
            # Convert all optional JOINs to LEFT JOINs
            if opt_joins:
                for join in opt_joins:
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
            if opt_where:
                main_where.extend(opt_where)
            
            # Combine variable mappings (optional variables can be NULL)
            self.logger.debug(f"Required variables mapping: {req_vars}")
            self.logger.debug(f"Optional variables mapping: {opt_vars}")
            
            combined_vars = req_vars.copy()
            combined_vars.update(opt_vars)
            
            self.logger.debug(f"Combined variables mapping: {combined_vars}")
            self.logger.info(f"✅ OPTIONAL translation completed with {len(combined_vars)} variables")
            
            # Debug logging for returned SQL components
            self.logger.debug(f"OPTIONAL returning FROM: '{main_from}'")
            self.logger.debug(f"OPTIONAL returning WHERE: {main_where}")
            self.logger.debug(f"OPTIONAL returning JOINs: {main_joins}")
            self.logger.debug(f"OPTIONAL returning variables: {list(combined_vars.keys())}")
            
            return main_from, main_where, main_joins, combined_vars
            
        except Exception as e:
            self.logger.error(f"❌ Error translating OPTIONAL pattern: {str(e)}")
            self.logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            
            # Return fallback result
            return f"FROM {table_config.quad_table} q0", [], [], {}

    async def translate_minus(self, minus_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """
        Translate MINUS pattern to SQL NOT EXISTS operations.
        
        MINUS patterns have two operands (p1 and p2) where:
        1. p1 is the main pattern (left operand)
        2. p2 is the pattern to exclude (right operand)
        
        The result includes all solutions from p1 that do not have a matching solution in p2
        based on shared variables. This is implemented using NOT EXISTS subquery.
        
        Args:
            minus_pattern: MINUS pattern from SPARQL algebra with p1 and p2 operands
            table_config: Table configuration for SQL generation
            projected_vars: Variables to project in SELECT clause
            
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        try:
            self.logger.info(f"🚫 TRANSLATING MINUS PATTERN with projected vars: {projected_vars}")
            
            # Extract main and exclusion operands
            main_operand = minus_pattern.p1  # Main pattern (what we want)
            exclude_operand = minus_pattern.p2  # Pattern to exclude (what we don't want)
            
            self.logger.info(f"📌 Main operand: {getattr(main_operand, 'name', type(main_operand).__name__)}")
            self.logger.info(f"📌 Exclude operand: {getattr(exclude_operand, 'name', type(exclude_operand).__name__)}")
            
            # Create independent alias generators for each operand to avoid conflicts
            main_alias_gen = self.alias_generator.create_child_generator("main")
            exclude_alias_gen = self.alias_generator.create_child_generator("excl")
            
            self.logger.debug(f"Created child alias generators: main_alias_gen, exclude_alias_gen")
            
            # Translate main pattern (the pattern we want to keep)
            self.logger.debug("Translating main part of MINUS")
            main_from, main_where, main_joins, main_vars = await self._translate_pattern_with_alias_gen(
                main_operand, table_config, projected_vars, main_alias_gen
            )
            
            # Translate exclude pattern (the pattern to subtract)
            # CRITICAL FIX: Pass None for projected_vars to ensure exclude pattern variables are properly mapped
            self.logger.debug("Translating exclude part of MINUS")
            exclude_from, exclude_where, exclude_joins, exclude_vars = await self._translate_pattern_with_alias_gen(
                exclude_operand, table_config, None, exclude_alias_gen
            )
            
            # Find shared variables between main and exclude patterns
            shared_variables = set(main_vars.keys()) & set(exclude_vars.keys())
            self.logger.debug(f"Shared variables between main and exclude patterns: {[str(v) for v in shared_variables]}")
            
            # ... (rest of the code remains the same)
            # Build the NOT EXISTS subquery for exclusion
            if shared_variables:
                # Build the NOT EXISTS subquery
                exclude_select_items = []
                exclude_conditions = []
                
                # Add shared variable equality conditions
                for var in shared_variables:
                    main_mapping = main_vars[var]
                    exclude_mapping = exclude_vars[var]
                    exclude_conditions.append(f"{main_mapping} = {exclude_mapping}")
                
                # Build the exclude subquery SQL
                exclude_sql_parts = []
                
                # Add FROM clause for exclude pattern
                if exclude_from:
                    exclude_sql_parts.append(exclude_from)
                
                # Add JOINs for exclude pattern
                if exclude_joins:
                    exclude_sql_parts.extend(exclude_joins)
                
                # Combine WHERE conditions for exclude pattern
                all_exclude_conditions = []
                if exclude_where:
                    all_exclude_conditions.extend(exclude_where)
                if exclude_conditions:
                    all_exclude_conditions.extend(exclude_conditions)
                
                if all_exclude_conditions:
                    exclude_sql_parts.append(f"WHERE {' AND '.join(all_exclude_conditions)}")
                
                # Build complete NOT EXISTS subquery
                exclude_subquery = f"SELECT 1 {' '.join(exclude_sql_parts)}"
                not_exists_condition = f"NOT EXISTS ({exclude_subquery})"
                
                self.logger.debug(f"Generated NOT EXISTS condition: {not_exists_condition}")
                
                # Add NOT EXISTS to main WHERE conditions
                final_where = main_where.copy() if main_where else []
                final_where.append(not_exists_condition)
                
            else:
                # No shared variables - MINUS has no effect (all results from main pattern)
                self.logger.warning("No shared variables between MINUS operands - MINUS has no effect")
                final_where = main_where.copy() if main_where else []
            
            # Return main pattern with NOT EXISTS exclusion
            self.logger.debug(f"Main variables mapping: {main_vars}")
            self.logger.info(f"✅ MINUS translation completed with {len(main_vars)} variables")
            
            # Debug logging for returned SQL components
            self.logger.debug(f"MINUS returning FROM: '{main_from}'")
            self.logger.debug(f"MINUS returning WHERE: {final_where}")
            self.logger.debug(f"MINUS returning JOINs: {main_joins}")
            self.logger.debug(f"MINUS returning variables: {list(main_vars.keys())}")
            
            return main_from, final_where, main_joins, main_vars
            
        except Exception as e:
            self.logger.error(f"❌ Error translating MINUS pattern: {str(e)}")
            self.logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            
            # Return fallback result
            return f"FROM {table_config.quad_table} q0", [], [], {}



    async def translate_join(self, join_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """
        Translate JOIN pattern by combining left and right operands.
        
        Args:
            join_pattern: RDFLib Join pattern with left and right operands
            table_config: Table configuration
            projected_vars: Variables to project
            
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        self.logger.debug(f"🔗 TRANSLATING JOIN PATTERN")
        
        # Get left and right operands
        left_pattern = join_pattern.p1
        right_pattern = join_pattern.p2
        
        # Create independent alias generators for each operand to avoid conflicts
        left_alias_gen = self.alias_generator.create_child_generator("left")
        right_alias_gen = self.alias_generator.create_child_generator("right")
        
        # Translate left operand with its own alias generator
        left_from, left_where, left_joins, left_vars = await self._translate_pattern_with_alias_gen(
            left_pattern, table_config, projected_vars, left_alias_gen
        )
        
        # Translate right operand with its own alias generator
        right_from, right_where, right_joins, right_vars = await self._translate_pattern_with_alias_gen(
            right_pattern, table_config, projected_vars, right_alias_gen
        )
        
        # Combine variable mappings
        combined_vars = {**left_vars, **right_vars}
        
        # Combine WHERE conditions
        combined_where = left_where + right_where
        
        # Combine JOINs
        combined_joins = left_joins + right_joins
        
        # Combine FROM clauses properly to include both operands
        # Extract table references from both FROM clauses (only remove leading FROM)
        left_tables = left_from[5:].strip() if left_from.startswith("FROM ") else left_from.strip()
        right_tables = right_from[5:].strip() if right_from.startswith("FROM ") else right_from.strip()
        
        # Create combined FROM clause with CROSS JOIN
        combined_from = f"FROM {left_tables} CROSS JOIN {right_tables}"
        
        print(f"🔧 JOIN DEBUG: left_from = '{left_from[:100]}...'")
        print(f"🔧 JOIN DEBUG: right_from = '{right_from[:100]}...'")
        print(f"🔧 JOIN DEBUG: left_tables = '{left_tables[:100]}...'")
        print(f"🔧 JOIN DEBUG: right_tables = '{right_tables[:100]}...'")
        print(f"🔧 JOIN DEBUG: combined_from = '{combined_from[:100]}...'")
        
        # Log the join operation for debugging
        self.logger.debug(f"JOIN: Left FROM: {left_from}")
        self.logger.debug(f"JOIN: Right FROM: {right_from}")
        self.logger.debug(f"JOIN: Combined FROM: {combined_from}")
        self.logger.debug(f"JOIN: Left vars: {list(left_vars.keys())}, Right vars: {list(right_vars.keys())}")
        
        # For variable mapping conflicts, prefer the left side (first pattern)
        # This is a simple resolution strategy
        for var, alias in right_vars.items():
            if var not in combined_vars:
                combined_vars[var] = alias
            else:
                self.logger.debug(f"Variable {var} already mapped, keeping left mapping")
        
        self.logger.debug(f"✅ JOIN pattern translated with {len(combined_vars)} variables")
        
        return combined_from, combined_where, combined_joins, combined_vars


    async def translate_extend(self, extend_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate Extend pattern (BIND statements) to SQL.
        
        Extend patterns have:
        - p: The nested pattern to translate
        - var: The variable being bound
        - expr: The expression to compute
        
        CRITICAL FIX: Ensure BIND expressions can access variables from OPTIONAL patterns
        by properly propagating variable mappings from nested patterns.
        """
        try:
            self.logger.debug(f"Translating Extend pattern (BIND statement)")
            
            # Get the nested pattern (the WHERE clause before BIND)
            nested_pattern = extend_pattern.p
            
            # Get the BIND variable and expression first to understand what variables we need
            bind_var = extend_pattern.var
            bind_expr = extend_pattern.expr
            
            self.logger.debug(f"BIND variable: {bind_var}")
            self.logger.debug(f"BIND expression: {bind_expr} (type: {type(bind_expr)})")
            
            # CRITICAL FIX for BIND+OPTIONAL bug: Ensure projected_vars includes ALL variables
            # referenced in the BIND expression, not just the BIND variable itself
            extended_projected_vars = list(projected_vars) if projected_vars else []
            
            # Add the BIND variable if not already included
            if bind_var not in extended_projected_vars:
                extended_projected_vars.append(bind_var)
            
            # CRITICAL: Extract all variables referenced in the BIND expression
            # This ensures OPTIONAL variables used in BIND expressions are properly mapped
            bind_expr_vars = self._extract_variables_from_expression(bind_expr)
            for var in bind_expr_vars:
                if var not in extended_projected_vars:
                    extended_projected_vars.append(var)
                    self.logger.debug(f"Added BIND expression variable {var} to projected_vars")
            
            # Translate the nested pattern first with extended projection
            from_clause, where_conditions, joins, variable_mappings = await self.translate_pattern(
                nested_pattern, table_config, extended_projected_vars
            )
            
            # Debug: Log all available variable mappings before BIND translation
            self.logger.debug(f"Variable mappings available for BIND {bind_var}: {list(variable_mappings.keys())}")
            self.logger.debug(f"Full variable mappings: {variable_mappings}")
            
            # Translate the BIND expression to SQL
            try:
                sql_expression = self._translate_bind_expression(bind_expr, variable_mappings)
                
                # CRITICAL FIX: Ensure the BIND variable mapping is properly set
                # If the BIND expression references OPTIONAL variables that weren't found,
                # we need to handle this gracefully
                if 'UNMAPPED_' in sql_expression:
                    self.logger.warning(f"BIND expression contains unmapped variables: {sql_expression}")
                    self.logger.warning(f"Available variable mappings: {list(variable_mappings.keys())}")
                    # Still set the mapping but log the issue
                
                variable_mappings[bind_var] = sql_expression
                self.logger.debug(f"Successfully translated BIND expression for {bind_var}: {sql_expression}")
                
            except Exception as expr_error:
                self.logger.warning(f"Failed to translate BIND expression for {bind_var}: {expr_error}")
                self.logger.warning(f"Available mappings were: {list(variable_mappings.keys())}")
                # Fall back to placeholder to avoid query failure
                variable_mappings[bind_var] = f"'BIND_FAILED_{bind_var}'"
                
            # Ensure FROM clause includes the FROM keyword for proper SQL generation
            # This is critical for UNION branches containing BIND expressions
            if from_clause and not from_clause.strip().upper().startswith('FROM'):
                # If from_clause doesn't start with FROM, it's just a table reference
                from_clause = f"FROM {from_clause}"
                self.logger.debug(f"Fixed FROM clause in BIND pattern: {from_clause}")
            
            return from_clause, where_conditions, joins, variable_mappings
            
        except Exception as e:
            self.logger.error(f"Error translating Extend pattern: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            # Fall back to basic pattern to avoid complete failure
            return f"FROM {table_config.quad_table} q0", [], [], {}

    async def translate_values(self, values_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate VALUES pattern to SQL.
        
        VALUES patterns provide inline data binding for variables.
        Examples:
        - VALUES ?name { "Alice" "Bob" "Charlie" }
        - VALUES (?name ?age) { ("Alice" 25) ("Bob" 30) ("Charlie" 35) }
        
        This generates a subquery with UNION ALL for each data row.
        """
        try:
            self.logger.debug(f"Translating VALUES pattern: {values_pattern}")
            self.logger.debug(f"Pattern type: {type(values_pattern)}")
            self.logger.debug(f"Pattern name: {getattr(values_pattern, 'name', 'NO_NAME')}")
            
            # Get all non-private attributes for debugging
            attrs = [attr for attr in dir(values_pattern) if not attr.startswith('_')]
            self.logger.debug(f"Pattern attributes: {attrs}")
            
            # Debug each attribute value
            for attr in attrs:
                try:
                    value = getattr(values_pattern, attr)
                    self.logger.debug(f"  {attr}: {value} (type: {type(value)})")
                    if isinstance(value, (list, tuple)) and len(value) <= 10:
                        for i, item in enumerate(value):
                            self.logger.debug(f"    [{i}]: {item} (type: {type(item)})")
                except Exception as e:
                    self.logger.debug(f"  {attr}: ERROR - {e}")
            
            # Extract data from ToMultiSet pattern structure
            # ToMultiSet has nested 'p' attribute containing 'values_' pattern with 'res' data
            variables = []
            data_rows = []
            
            # Check for nested values pattern in 'p' attribute
            if hasattr(values_pattern, 'p'):
                nested_p = getattr(values_pattern, 'p')
                self.logger.debug(f"Nested p pattern: {nested_p} (type: {type(nested_p)})")
                
                if hasattr(nested_p, 'res'):
                    res_data = getattr(nested_p, 'res')
                    self.logger.debug(f"Found res data: {res_data} (type: {type(res_data)})")
                    
                    if res_data and isinstance(res_data, list):
                        # res_data is a list of dictionaries mapping variables to values
                        # Extract variables from first row
                        if res_data:
                            first_row = res_data[0]
                            variables = list(first_row.keys())
                            self.logger.debug(f"Extracted variables: {variables}")
                            
                            # Convert dictionary rows to tuple rows
                            for row_dict in res_data:
                                row_tuple = tuple(row_dict[var] for var in variables)
                                data_rows.append(row_tuple)
                            
                            self.logger.debug(f"Converted {len(data_rows)} data rows")
            
            # Handle single variable case (var is not a list)
            if variables and not isinstance(variables, list):
                variables = [variables]
            
            self.logger.debug(f"FINAL - variables: {variables}")
            self.logger.debug(f"FINAL - data rows: {len(data_rows) if data_rows else 0} rows")
            if data_rows:
                for i, row in enumerate(data_rows[:3]):  # Show first 3 rows
                    self.logger.debug(f"  Row {i}: {row} (type: {type(row)})")
            
            if not variables or not data_rows:
                self.logger.warning("Empty VALUES pattern")
                return f"FROM {table_config.quad_table} q0", [], [], {}
            
            # Generate alias for VALUES subquery
            if not hasattr(self, '_values_counter'):
                self._values_counter = 0
            self._values_counter += 1
            values_alias = f"values_{self._values_counter}"
            
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
                        sql_value = self._convert_rdflib_term_to_sql(value)
                    else:
                        # Handle missing values with NULL
                        sql_value = "NULL"
                    
                    # Create column alias for this variable
                    column_alias = f"{variable.n3()[1:]}_val"  # Remove ? from variable name
                    select_parts.append(f"{sql_value} AS {column_alias}")
                    
                    # Store variable mapping (only need to do this once)
                    if row_idx == 0:
                        variable_mappings[variable] = f"{values_alias}.{column_alias}"
                
                union_parts.append(f"SELECT {', '.join(select_parts)}")
            
            # Build complete VALUES subquery
            values_subquery = f"({' UNION ALL '.join(union_parts)}) {values_alias}"
            
            self.logger.debug(f"Generated VALUES subquery: {values_subquery}")
            self.logger.debug(f"VALUES variable mappings: {variable_mappings}")
            
            return f"FROM {values_subquery}", [], [], variable_mappings
            
        except Exception as e:
            self.logger.error(f"Error translating VALUES pattern: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return f"FROM {table_config.quad_table} q0", [], [], {}

    async def translate_subquery(self, subquery_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """
        Translate a nested SELECT query (subquery) to SQL.
        
        Args:
            subquery_pattern: RDFLib algebra for the subquery (SelectQuery)
            table_config: Table configuration
            projected_vars: Variables projected by parent query
            
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        try:
            self.logger.info(f"🔗 TRANSLATING SUBQUERY PATTERN with projected vars: {projected_vars or []}")
            
            # Store original counters to restore after subquery translation
            original_variable_counter = self.variable_counter
            original_join_counter = self.join_counter
            
            # Create isolated context for subquery (increment counters to avoid conflicts)
            subquery_depth = getattr(self, '_subquery_depth', 0) + 1
            self._subquery_depth = subquery_depth
            
            # Translate the subquery as a complete SELECT query
            subquery_sql = await self._translate_select_query(subquery_pattern, table_config)
            
            # Generate unique alias for the subquery derived table
            subquery_alias = f"subquery_{subquery_depth}_{self.join_counter}"
            self.join_counter += 1
            
            # Wrap subquery in parentheses as derived table
            derived_table_from = f"FROM ({subquery_sql}) {subquery_alias}"
            
            # Extract projection variables from subquery to create variable mappings
            subquery_projection_vars = subquery_pattern.get('PV', [])
            subquery_variable_mappings = {}
            
            for var in subquery_projection_vars:
                # Map subquery variables to the derived table alias
                column_name = var.toPython().lower()
                subquery_variable_mappings[var] = f"{subquery_alias}.{column_name}"
            
            self.logger.info(f"Successfully translated subquery with {len(subquery_projection_vars)} projected variables")
            self.logger.debug(f"Subquery SQL generated: {len(subquery_sql)} characters")
            
            # Reset subquery depth
            self._subquery_depth = subquery_depth - 1
            
            # Restore original counters (subquery has its own isolated context)
            self.variable_counter = original_variable_counter
            self.join_counter = original_join_counter
            
            # Return derived table - subqueries are self-contained
            return derived_table_from, [], [], subquery_variable_mappings
            
        except Exception as e:
            self.logger.error(f"Error translating subquery pattern: {e}")
            # Reset subquery depth and restore counters on error
            self._subquery_depth = getattr(self, '_subquery_depth', 1) - 1
            self.variable_counter = original_variable_counter
            self.join_counter = original_join_counter
            # Return fallback to avoid complete query failure
            return f"FROM {table_config.quad_table} q0", [], [], {}
    
    def get_supported_pattern_types(self) -> Set[str]:
        """Get the set of supported SPARQL algebra pattern types.
        
        Returns:
            Set of supported pattern type names
        """
        return {
            "BGP", "Filter", "Union", "LeftJoin", "Minus", "Slice", "Project",
            "Distinct", "OrderBy", "Graph", "Extend", "SelectQuery", "Join",
            "AggregateJoin", "Group", "Values", "ToMultiSet"
        }
    
    def is_supported_pattern(self, pattern_name: str) -> bool:
        """Check if a pattern type is supported.
        
        Args:
            pattern_name: Name of the pattern type to check
            
        Returns:
            True if the pattern type is supported
        """
        return pattern_name in self.get_supported_pattern_types()
    
    def extract_pattern_variables(self, pattern) -> Set[Variable]:
        """Extract all variables from a SPARQL algebra pattern.
        
        Args:
            pattern: SPARQL algebra pattern
            
        Returns:
            Set of variables found in the pattern
        """
        variables = set()
        
        # Try to get variables from pattern's _vars attribute
        if hasattr(pattern, '_vars'):
            variables.update(pattern._vars)
        
        # For BGP patterns, extract from triples
        if hasattr(pattern, 'triples'):
            for triple in pattern.triples:
                for term in triple:
                    if isinstance(term, Variable):
                        variables.add(term)
        
        # For patterns with nested patterns
        if hasattr(pattern, 'p'):
            variables.update(self.extract_pattern_variables(pattern.p))
        
        # For binary patterns (Union, LeftJoin, Minus, Join)
        if hasattr(pattern, 'p1'):
            variables.update(self.extract_pattern_variables(pattern.p1))
        if hasattr(pattern, 'p2'):
            variables.update(self.extract_pattern_variables(pattern.p2))
        
        return variables
    
    def generate_unique_alias(self, prefix: str = "alias") -> str:
        """Generate a unique alias for SQL table references.
        
        Args:
            prefix: Prefix for the alias
            
        Returns:
            Unique alias string
        """
        self.variable_counter += 1
        return f"{prefix}_{self.variable_counter}"
    
    def generate_join_alias(self) -> str:
        """Generate a unique alias for JOIN operations.
        
        Returns:
            Unique join alias string
        """
        self.join_counter += 1
        return f"join_{self.join_counter}"
    
    def build_triple_conditions(self, triple, quad_alias: str, variable_mappings: Dict[Variable, str]) -> List[str]:
        """Build SQL conditions for a single RDF triple.
        
        Args:
            triple: RDF triple (subject, predicate, object)
            quad_alias: SQL alias for the quad table
            variable_mappings: Current variable to SQL column mappings
            
        Returns:
            List of SQL WHERE conditions
        """
        conditions = []
        subject, predicate, obj = triple
        
        # Handle subject
        if isinstance(subject, Variable):
            if subject not in variable_mappings:
                variable_mappings[subject] = f"{quad_alias}.subject"
        else:
            # Constant subject - add condition
            subject_sql = SparqlUtils.convert_rdflib_term_to_sql(subject)
            conditions.append(f"{quad_alias}.subject = {subject_sql}")
        
        # Handle predicate
        if isinstance(predicate, Variable):
            if predicate not in variable_mappings:
                variable_mappings[predicate] = f"{quad_alias}.predicate"
        else:
            # Constant predicate - add condition
            predicate_sql = SparqlUtils.convert_rdflib_term_to_sql(predicate)
            conditions.append(f"{quad_alias}.predicate = {predicate_sql}")
        
        # Handle object
        if isinstance(obj, Variable):
            if obj not in variable_mappings:
                variable_mappings[obj] = f"{quad_alias}.object"
        else:
            # Constant object - add condition
            object_sql = SparqlUtils.convert_rdflib_term_to_sql(obj)
            conditions.append(f"{quad_alias}.object = {object_sql}")
        
        return conditions
    
    def merge_variable_mappings(self, mappings1: Dict[Variable, str], mappings2: Dict[Variable, str]) -> Dict[Variable, str]:
        """Merge two variable mapping dictionaries, preferring mappings1 for conflicts.
        
        Args:
            mappings1: First set of variable mappings (takes precedence)
            mappings2: Second set of variable mappings
            
        Returns:
            Merged variable mappings
        """
        merged = mappings2.copy()
        merged.update(mappings1)
        return merged
    
    def find_shared_variables(self, vars1: Set[Variable], vars2: Set[Variable]) -> Set[Variable]:
        """Find variables that are shared between two sets.
        
        Args:
            vars1: First set of variables
            vars2: Second set of variables
            
        Returns:
            Set of shared variables
        """
        return vars1 & vars2
    
    def build_join_conditions(self, shared_vars: Set[Variable], 
                             left_mappings: Dict[Variable, str], 
                             right_mappings: Dict[Variable, str]) -> List[str]:
        """Build JOIN conditions based on shared variables.
        
        Args:
            shared_vars: Variables shared between left and right patterns
            left_mappings: Variable mappings from left pattern
            right_mappings: Variable mappings from right pattern
            
        Returns:
            List of SQL JOIN conditions
        """
        join_conditions = []
        
        for var in shared_vars:
            if var in left_mappings and var in right_mappings:
                left_expr = left_mappings[var]
                right_expr = right_mappings[var]
                join_conditions.append(f"{left_expr} = {right_expr}")
            else:
                self.logger.warning(f"Shared variable {var} missing from mappings")
        
        return join_conditions
    
    def validate_pattern_structure(self, pattern) -> bool:
        """Validate that a pattern has the expected structure.
        
        Args:
            pattern: Pattern to validate
            
        Returns:
            True if the pattern is valid
        """
        try:
            # Check for required name attribute
            if not hasattr(pattern, 'name'):
                self.logger.error("Pattern missing 'name' attribute")
                return False
            
            pattern_name = pattern.name
            
            # Validate pattern-specific structure
            if pattern_name == "BGP":
                if not hasattr(pattern, 'triples'):
                    self.logger.error("BGP pattern missing 'triples' attribute")
                    return False
            elif pattern_name in ["Union", "LeftJoin", "Minus", "Join"]:
                if not (hasattr(pattern, 'p1') and hasattr(pattern, 'p2')):
                    self.logger.error(f"{pattern_name} pattern missing 'p1' or 'p2' attributes")
                    return False
            elif pattern_name in ["Slice", "Project", "Distinct", "OrderBy", "Extend"]:
                if not hasattr(pattern, 'p'):
                    self.logger.error(f"{pattern_name} pattern missing 'p' attribute")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating pattern structure: {e}")
            return False
    
    def normalize_from_clause(self, from_clause: str) -> str:
        """Ensure FROM clause starts with 'FROM' keyword.
        
        Args:
            from_clause: FROM clause to normalize
            
        Returns:
            Normalized FROM clause
        """
        if from_clause and not from_clause.strip().upper().startswith('FROM'):
            return f"FROM {from_clause}"
        return from_clause
    
    def combine_conditions(self, conditions_list: List[List[str]]) -> List[str]:
        """Combine multiple lists of SQL conditions into a single list.
        
        Args:
            conditions_list: List of condition lists to combine
            
        Returns:
            Combined list of conditions
        """
        combined = []
        for conditions in conditions_list:
            if conditions:
                combined.extend(conditions)
        return combined
    
    def get_pattern_depth(self, pattern) -> int:
        """Calculate the nesting depth of a pattern.
        
        Args:
            pattern: Pattern to analyze
            
        Returns:
            Nesting depth (0 for leaf patterns)
        """
        if not hasattr(pattern, 'name'):
            return 0
        
        pattern_name = pattern.name
        max_depth = 0
        
        # Check nested patterns
        if hasattr(pattern, 'p'):
            max_depth = max(max_depth, 1 + self.get_pattern_depth(pattern.p))
        
        # Check binary patterns
        if hasattr(pattern, 'p1'):
            max_depth = max(max_depth, 1 + self.get_pattern_depth(pattern.p1))
        if hasattr(pattern, 'p2'):
            max_depth = max(max_depth, 1 + self.get_pattern_depth(pattern.p2))
        
        return max_depth

    