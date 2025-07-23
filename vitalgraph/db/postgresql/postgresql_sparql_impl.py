"""
PostgreSQL SPARQL Implementation for VitalGraph

This module provides SPARQL-to-SQL translation and execution capabilities
for the VitalGraph PostgreSQL backend using the UUID-based quad/term schema.
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Any, Iterator

from rdflib import Variable, URIRef, Literal, BNode
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.algebra import translateAlgebra
from rdflib.plugins.sparql.sparql import Query

from .postgresql_space_impl import PostgreSQLSpaceImpl
from .postgresql_utils import PostgreSQLUtils

logger = logging.getLogger(__name__)


@dataclass
class TableConfig:
    """Configuration for quad and term table names."""
    quad_table: str
    term_table: str
    
    @classmethod
    def from_space_impl(cls, space_impl: PostgreSQLSpaceImpl, space_id: str, use_unlogged: bool = False) -> 'TableConfig':
        """Create TableConfig from PostgreSQLSpaceImpl and space_id."""
        quad_table = PostgreSQLUtils.get_table_name(space_impl.global_prefix, space_id, "rdf_quad")
        term_table = PostgreSQLUtils.get_table_name(space_impl.global_prefix, space_id, "term")
        
        # Add _unlogged suffix if using unlogged tables
        if use_unlogged:
            quad_table += "_unlogged"
            term_table += "_unlogged"
            
        return cls(quad_table=quad_table, term_table=term_table)


class PostgreSQLSparqlImpl:
    """
    PostgreSQL SPARQL implementation providing SPARQL-to-SQL translation
    and query execution for VitalGraph's UUID-based quad/term schema.
    """
    
    def __init__(self, space_impl: PostgreSQLSpaceImpl):
        """
        Initialize PostgreSQL SPARQL implementation.
        
        Args:
            space_impl: PostgreSQLSpaceImpl instance for database operations
        """
        self.space_impl = space_impl
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.variable_counter = 0
        self.join_counter = 0
        
    async def execute_sparql_query(self, space_id: str, sparql_query: str) -> List[Dict[str, Any]]:
        """
        Execute a SPARQL query against the specified space.
        
        Args:
            space_id: Space identifier
            sparql_query: SPARQL query string
            
        Returns:
            List of result dictionaries with variable bindings
        """
        try:
            # Validate space exists
            PostgreSQLUtils.validate_space_id(space_id)
            
            # Translate SPARQL to SQL
            sql_query = await self._translate_sparql_to_sql(space_id, sparql_query)
            
            # Execute SQL query
            results = await self._execute_sql_query(sql_query)
            
            self.logger.info(f"SPARQL query executed successfully, returned {len(results)} results")
            return results
            
        except Exception as e:
            self.logger.error(f"Error executing SPARQL query: {e}")
            raise
    
    async def _translate_sparql_to_sql(self, space_id: str, sparql_query: str) -> str:
        """
        Translate SPARQL query to SQL using RDFLib's algebra representation.
        
        Args:
            space_id: Space identifier for table name resolution
            sparql_query: SPARQL query string
            
        Returns:
            SQL query string
        """
        try:
            # Create table configuration for unlogged tables (WordNet data was loaded into unlogged tables)
            table_config = TableConfig.from_space_impl(self.space_impl, space_id, use_unlogged=True)
            
            # Parse and get algebra
            prepared_query = prepareQuery(sparql_query)
            algebra = prepared_query.algebra
            
            self.logger.info(f"Translating SPARQL query with algebra: {algebra.name}")
            
            # Reset counters for each query
            self.variable_counter = 0
            self.join_counter = 0
            
            # Translate based on query type
            if algebra.name == "SelectQuery":
                return self._translate_select_query(algebra, table_config)
            elif algebra.name == "ConstructQuery":
                return self._translate_construct_query(algebra, table_config)
            else:
                raise NotImplementedError(f"Query type {algebra.name} not yet supported")
                
        except Exception as e:
            self.logger.error(f"Error translating SPARQL query: {e}")
            raise
    
    def _translate_select_query(self, algebra, table_config: TableConfig) -> str:
        """Translate SELECT query algebra to SQL."""
        
        # Extract projection variables
        projection_vars = algebra.get('PV', [])
        
        # Check if we have a DISTINCT pattern and extract LIMIT/OFFSET
        pattern = algebra['p']
        has_distinct = self._has_distinct_pattern(pattern)
        limit_info = self._extract_limit_offset(pattern)
        
        # Extract and translate the main pattern
        from_clause, where_conditions, joins, variable_mappings = self._translate_pattern(pattern, table_config, projection_vars)
        
        # Build SELECT clause with variable mappings
        select_clause = self._build_select_clause(projection_vars, variable_mappings, has_distinct)
        
        # Build complete SQL query
        sql_parts = [select_clause]
        sql_parts.append(from_clause)
        
        if joins:
            sql_parts.extend(joins)
            
        if where_conditions:
            sql_parts.append(f"WHERE {' AND '.join(where_conditions)}")
        
        # Add LIMIT and OFFSET if present
        if limit_info['offset'] is not None:
            sql_parts.append(f"OFFSET {limit_info['offset']}")
        if limit_info['limit'] is not None:
            sql_parts.append(f"LIMIT {limit_info['limit']}")
            
        return '\n'.join(sql_parts)
    
    def _has_distinct_pattern(self, pattern) -> bool:
        """Recursively check if the pattern contains a DISTINCT."""
        if hasattr(pattern, 'name'):
            if pattern.name == "Distinct":
                return True
            # Check nested patterns
            if hasattr(pattern, 'p'):
                return self._has_distinct_pattern(pattern.p)
        return False
    
    def _extract_limit_offset(self, pattern) -> dict:
        """Recursively extract LIMIT and OFFSET from Slice patterns."""
        result = {'limit': None, 'offset': None}
        
        if hasattr(pattern, 'name') and pattern.name == "Slice":
            # Slice pattern has start (offset) and length (limit)
            if hasattr(pattern, 'start') and pattern.start is not None:
                result['offset'] = pattern.start
            if hasattr(pattern, 'length') and pattern.length is not None:
                result['limit'] = pattern.length
        
        # Check nested patterns
        if hasattr(pattern, 'p'):
            nested_result = self._extract_limit_offset(pattern.p)
            # Use nested values if current pattern doesn't have them
            if result['limit'] is None:
                result['limit'] = nested_result['limit']
            if result['offset'] is None:
                result['offset'] = nested_result['offset']
        
        return result
    
    def _build_select_clause(self, projection_vars: List[Variable], variable_mappings: Dict[Variable, str], has_distinct: bool = False) -> str:
        """Build SQL SELECT clause from SPARQL projection variables."""
        if not projection_vars:
            distinct_keyword = "DISTINCT " if has_distinct else ""
            return f"SELECT {distinct_keyword}*"
        
        select_items = []
        for var in projection_vars:
            var_name = str(var).replace('?', '')
            # Get the term text for this variable using the mapping
            if var in variable_mappings:
                term_column = variable_mappings[var]
                select_items.append(f"{term_column} AS {var_name}")
            else:
                # Fallback - shouldn't happen with proper mapping
                select_items.append(f"'UNMAPPED_VAR_{var_name}' AS {var_name}")
            
        distinct_keyword = "DISTINCT " if has_distinct else ""
        return f"SELECT {distinct_keyword}{', '.join(select_items)}"
    
    def _translate_pattern(self, pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """
        Translate a SPARQL pattern to SQL components.
        
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        pattern_name = pattern.name
        
        if pattern_name == "BGP":  # Basic Graph Pattern
            return self._translate_bgp(pattern, table_config, projected_vars)
        elif pattern_name == "Filter":
            return self._translate_filter(pattern, table_config, projected_vars)
        elif pattern_name == "Union":
            return self._translate_union(pattern, table_config)
        elif pattern_name == "LeftJoin":  # OPTIONAL
            return self._translate_optional(pattern, table_config)
        elif pattern_name == "Slice":  # LIMIT/OFFSET
            # Slice wraps another pattern - drill down to the nested pattern
            nested_pattern = pattern.p
            return self._translate_pattern(nested_pattern, table_config, projected_vars)
        elif pattern_name == "Project":  # SELECT projection
            # Project wraps another pattern - drill down to the nested pattern
            nested_pattern = pattern.p
            return self._translate_pattern(nested_pattern, table_config, projected_vars)
        elif pattern_name == "Distinct":  # SELECT DISTINCT
            # Distinct wraps another pattern - drill down to the nested pattern
            nested_pattern = pattern.p
            return self._translate_pattern(nested_pattern, table_config, projected_vars)
        elif pattern_name == "OrderBy":  # ORDER BY
            # OrderBy wraps another pattern - drill down to the nested pattern
            nested_pattern = pattern.p
            return self._translate_pattern(nested_pattern, table_config, projected_vars)
        else:
            self.logger.warning(f"Pattern type {pattern_name} not fully implemented")
            return f"FROM {table_config.quad_table} q0", [], [], {}
    
    def _translate_bgp(self, bgp_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate Basic Graph Pattern to SQL using UUID-based quad/term schema."""
        triples = bgp_pattern.get('triples', [])
        
        if not triples:
            return f"FROM {table_config.quad_table} q0", [], [], {}
        
        all_joins = []
        quad_joins = []  # JOINs for additional quad tables
        all_where_conditions = []
        variable_mappings = {}
        term_alias_counter = 0
        quad_aliases = []
        
        # Process each triple pattern separately with its own quad table alias
        for triple_idx, triple in enumerate(triples):
            subject, predicate, obj = triple
            quad_alias = f"q{self.join_counter}"
            self.join_counter += 1
            quad_aliases.append(quad_alias)
            
            # Handle subject
            if isinstance(subject, Variable):
                if subject not in variable_mappings and (projected_vars is None or subject in projected_vars):
                    term_alias = f"s_term_{term_alias_counter}"
                    term_alias_counter += 1
                    all_joins.append(f"JOIN {table_config.term_table} {term_alias} ON {quad_alias}.subject_uuid = {term_alias}.term_uuid")
                    variable_mappings[subject] = f"{term_alias}.term_text"
                # Variable already mapped or not projected - don't create JOIN
            else:
                # Bound term - use subquery
                term_text, term_type = self._get_term_info(subject)
                subquery = f"(SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{term_text}' AND term_type = '{term_type}')"
                all_where_conditions.append(f"{quad_alias}.subject_uuid = {subquery}")
            
            # Handle predicate
            if isinstance(predicate, Variable):
                if predicate not in variable_mappings and (projected_vars is None or predicate in projected_vars):
                    term_alias = f"p_term_{term_alias_counter}"
                    term_alias_counter += 1
                    all_joins.append(f"JOIN {table_config.term_table} {term_alias} ON {quad_alias}.predicate_uuid = {term_alias}.term_uuid")
                    variable_mappings[predicate] = f"{term_alias}.term_text"
                # Variable already mapped or not projected - don't create JOIN
            else:
                # Bound term - use subquery
                term_text, term_type = self._get_term_info(predicate)
                subquery = f"(SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{term_text}' AND term_type = '{term_type}')"
                all_where_conditions.append(f"{quad_alias}.predicate_uuid = {subquery}")
            
            # Handle object
            if isinstance(obj, Variable):
                if obj not in variable_mappings and (projected_vars is None or obj in projected_vars):
                    term_alias = f"o_term_{term_alias_counter}"
                    term_alias_counter += 1
                    all_joins.append(f"JOIN {table_config.term_table} {term_alias} ON {quad_alias}.object_uuid = {term_alias}.term_uuid")
                    variable_mappings[obj] = f"{term_alias}.term_text"
                # Variable already mapped or not projected - don't create JOIN
            else:
                # Bound term - use subquery
                term_text, term_type = self._get_term_info(obj)
                subquery = f"(SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{term_text}' AND term_type = '{term_type}')"
                all_where_conditions.append(f"{quad_alias}.object_uuid = {subquery}")
        
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
        
        return from_clause, all_where_conditions, combined_joins, variable_mappings
    
    def _find_shared_variables_between_triples(self, triple1, triple2):
        """Find variables that are shared between two triples."""
        vars1 = set()
        vars2 = set()
        
        # Extract variables from first triple
        for item in triple1:
            if isinstance(item, Variable):
                vars1.add(item)
        
        # Extract variables from second triple
        for item in triple2:
            if isinstance(item, Variable):
                vars2.add(item)
        
        return vars1.intersection(vars2)
    
    def _get_variable_position_in_triple(self, triple, variable):
        """Get the position (subject, predicate, object) of a variable in a triple."""
        subject, predicate, obj = triple
        
        if subject == variable:
            return "subject"
        elif predicate == variable:
            return "predicate"
        elif obj == variable:
            return "object"
        
        return None
    
    def _translate_filter(self, filter_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate FILTER pattern to SQL."""
        # Get the underlying pattern first
        inner_pattern = filter_pattern['p']
        from_clause, where_conditions, joins, variable_mappings = self._translate_pattern(inner_pattern, table_config, projected_vars)
        
        # Debug logging
        self.logger.debug(f"Filter pattern variable mappings: {variable_mappings}")
        
        # Translate the filter expression
        filter_expr = filter_pattern['expr']
        self.logger.debug(f"Translating filter expression: {filter_expr}")
        filter_sql = self._translate_filter_expression(filter_expr, variable_mappings)
        self.logger.debug(f"Filter SQL result: {filter_sql}")
        
        if filter_sql:
            where_conditions.append(filter_sql)
        
        return from_clause, where_conditions, joins, variable_mappings
    
    def _translate_filter_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate a SPARQL filter expression to SQL."""
        # Handle case where expr is a list (multiple filter expressions)
        if isinstance(expr, list):
            if len(expr) == 1:
                return self._translate_filter_expression(expr[0], variable_mappings)
            else:
                # Multiple expressions - combine with AND
                conditions = []
                for sub_expr in expr:
                    conditions.append(self._translate_filter_expression(sub_expr, variable_mappings))
                return f"({' AND '.join(conditions)})"
        
        # Handle case where expr doesn't have a name attribute
        if not hasattr(expr, 'name'):
            self.logger.warning(f"Filter expression has no name attribute: {type(expr)}")
            return "1=1"  # No-op condition
        
        expr_name = expr.name
        
        if expr_name == "RelationalExpression":
            return self._translate_relational_expression(expr, variable_mappings)
        elif expr_name == "ConditionalAndExpression":
            return self._translate_and_expression(expr, variable_mappings)
        elif expr_name == "ConditionalOrExpression":
            return self._translate_or_expression(expr, variable_mappings)
        elif expr_name == "Builtin_REGEX":
            return self._translate_regex_expression(expr, variable_mappings)
        elif expr_name == "Builtin_CONTAINS":
            return self._translate_contains_expression(expr, variable_mappings)
        elif expr_name == "Builtin_STRSTARTS":
            return self._translate_strstarts_expression(expr, variable_mappings)
        elif expr_name == "Builtin_STRENDS":
            return self._translate_strends_expression(expr, variable_mappings)
        else:
            self.logger.warning(f"Filter expression {expr_name} not implemented")
            return "1=1"  # No-op condition
    
    def _translate_relational_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate relational expressions like ?x > 100."""
        operator = expr['op']
        left = expr['expr']
        right = expr['other']
        
        # Determine if this is a numeric comparison
        numeric_operators = {'<', '<=', '>', '>='}
        is_numeric = operator in numeric_operators
        
        left_sql = self._translate_expression_operand(left, variable_mappings, cast_numeric=is_numeric)
        right_sql = self._translate_expression_operand(right, variable_mappings, cast_numeric=is_numeric)
        
        # Map SPARQL operators to SQL
        op_mapping = {
            '=': '=',
            '!=': '!=',
            '<': '<',
            '<=': '<=',
            '>': '>',
            '>=': '>='
        }
        
        sql_op = op_mapping.get(operator, operator)
        return f"{left_sql} {sql_op} {right_sql}"
    
    def _translate_expression_operand(self, operand, variable_mappings: Dict[Variable, str], cast_numeric: bool = False) -> str:
        """Translate an expression operand (variable or literal)."""
        self.logger.debug(f"Translating operand: {operand}, type: {type(operand)}, is Variable: {isinstance(operand, Variable)}")
        if isinstance(operand, Variable):
            self.logger.debug(f"Variable {operand} in mappings: {operand in variable_mappings}")
            if operand in variable_mappings:
                term_column = variable_mappings[operand]
                self.logger.debug(f"Variable {operand} mapped to: {term_column}")
                # Only cast to numeric types when explicitly requested for numeric operations
                if cast_numeric:
                    return f"CAST({term_column} AS DECIMAL)"
                else:
                    return term_column
            else:
                self.logger.debug(f"Variable {operand} not found in mappings: {list(variable_mappings.keys())}")
                return f"'UNMAPPED_{operand}'"
        elif hasattr(operand, 'toPython') and operand.toPython is not None:
            # RDFLib literal with Python value
            try:
                value = operand.toPython()
                if value is not None:
                    if isinstance(value, str):
                        return f"'{value}'"
                    else:
                        return str(value)
            except (AttributeError, TypeError):
                pass
    
        # Handle function expressions or other complex operands
        if hasattr(operand, 'name'):
            # This might be a function call like STRLEN
            return self._translate_function_expression(operand, variable_mappings)
        
        # Direct value fallback
        if operand is None:
            return "NULL"
        elif isinstance(operand, str):
            return f"'{operand}'"
        else:
            return str(operand)
    
    def _translate_function_expression(self, func_expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate SPARQL function expressions to SQL."""
        if not hasattr(func_expr, 'name'):
            return "NULL"
        
        func_name = func_expr.name
        self.logger.debug(f"Translating function: {func_name}, available mappings: {list(variable_mappings.keys())}")
        
        # Handle different SPARQL functions
        if func_name == 'STRLEN' or func_name == 'Builtin_STRLEN':
            # STRLEN(?var) -> LENGTH(term_text)
            # Try 'arg' first (most common for STRLEN), then 'expr'
            if hasattr(func_expr, 'arg') and func_expr.arg is not None:
                self.logger.debug(f"STRLEN arg: {func_expr.arg}, type: {type(func_expr.arg)}")
                arg_sql = self._translate_expression_operand(func_expr.arg, variable_mappings)
                self.logger.debug(f"STRLEN translated to: LENGTH({arg_sql})")
                return f"LENGTH({arg_sql})"
            elif hasattr(func_expr, 'expr') and func_expr.expr is not None:
                self.logger.debug(f"STRLEN expr: {func_expr.expr}, type: {type(func_expr.expr)}")
                arg_sql = self._translate_expression_operand(func_expr.expr, variable_mappings)
                self.logger.debug(f"STRLEN translated to: LENGTH({arg_sql})")
                return f"LENGTH({arg_sql})"
        elif func_name == 'UCASE':
            # UCASE(?var) -> UPPER(term_text)
            if hasattr(func_expr, 'expr'):
                arg_sql = self._translate_expression_operand(func_expr.expr, variable_mappings)
                return f"UPPER({arg_sql})"
        elif func_name == 'LCASE' or func_name == 'Builtin_LCASE':
            # LCASE(?var) -> LOWER(term_text)
            if hasattr(func_expr, 'expr'):
                arg_sql = self._translate_expression_operand(func_expr.expr, variable_mappings)
                return f"LOWER({arg_sql})"
            elif hasattr(func_expr, 'arg'):
                arg_sql = self._translate_expression_operand(func_expr.arg, variable_mappings)
                return f"LOWER({arg_sql})"
        elif func_name == 'SUBSTR':
            # SUBSTR(?var, start, length) -> SUBSTRING(term_text FROM start FOR length)
            if hasattr(func_expr, 'expr') and hasattr(func_expr, 'start'):
                arg_sql = self._translate_expression_operand(func_expr.expr, variable_mappings)
                start_sql = self._translate_expression_operand(func_expr.start, variable_mappings)
                if hasattr(func_expr, 'length'):
                    length_sql = self._translate_expression_operand(func_expr.length, variable_mappings)
                    return f"SUBSTRING({arg_sql} FROM {start_sql} FOR {length_sql})"
                else:
                    return f"SUBSTRING({arg_sql} FROM {start_sql})"
        
        # Fallback for unknown functions
        self.logger.warning(f"Unknown SPARQL function: {func_name}")
        return "NULL"
    
    def _translate_regex_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate REGEX() function to PostgreSQL regex operator."""
        text_expr = expr['text']
        pattern_expr = expr['pattern']
        
        text_sql = self._translate_expression_operand(text_expr, variable_mappings)
        pattern_sql = self._translate_expression_operand(pattern_expr, variable_mappings)
        
        # Use PostgreSQL regex operator
        return f"{text_sql} ~ {pattern_sql}"
    
    def _translate_contains_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate CONTAINS() function to SQL LIKE."""
        text_expr = expr['arg1']
        search_expr = expr['arg2']
        
        text_sql = self._translate_expression_operand(text_expr, variable_mappings)
        search_sql = self._translate_expression_operand(search_expr, variable_mappings)
        
        # Remove quotes from search term and wrap with %
        search_term = search_sql.strip("'")
        return f"{text_sql} LIKE '%{search_term}%'"
    
    def _translate_strstarts_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate STRSTARTS() function to SQL LIKE."""
        text_expr = expr['arg1']
        prefix_expr = expr['arg2']
        
        text_sql = self._translate_expression_operand(text_expr, variable_mappings)
        prefix_sql = self._translate_expression_operand(prefix_expr, variable_mappings)
        
        # Remove quotes from prefix and add %
        prefix_term = prefix_sql.strip("'")
        return f"{text_sql} LIKE '{prefix_term}%'"
    
    def _translate_strends_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate STRENDS() function to SQL LIKE."""
        text_expr = expr['arg1']
        suffix_expr = expr['arg2']
        
        text_sql = self._translate_expression_operand(text_expr, variable_mappings)
        suffix_sql = self._translate_expression_operand(suffix_expr, variable_mappings)
        
        # Remove quotes from suffix and add %
        suffix_term = suffix_sql.strip("'")
        return f"{text_sql} LIKE '%{suffix_term}'"
    
    def _translate_and_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate AND expression."""
        left = self._translate_filter_expression(expr['expr'], variable_mappings)
        right = self._translate_filter_expression(expr['other'], variable_mappings)
        return f"({left} AND {right})"
    
    def _translate_or_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate OR expression."""
        left = self._translate_filter_expression(expr['expr'], variable_mappings)
        right = self._translate_filter_expression(expr['other'], variable_mappings)
        return f"({left} OR {right})"
    
    def _get_term_info(self, term) -> Tuple[str, str]:
        """Get term text and type for database lookup."""
        if isinstance(term, URIRef):
            return str(term), 'U'
        elif isinstance(term, Literal):
            return str(term), 'L'
        elif isinstance(term, BNode):
            return str(term), 'B'
        else:
            return str(term), 'U'  # Default to URI
    
    def _find_shared_variables(self, triple1, triple2, alias1: str, alias2: str) -> List[str]:
        """Find shared variables between two triples for join conditions."""
        conditions = []
        
        # Check each position for shared variables
        positions = [('subject', 'subject_uuid'), ('predicate', 'predicate_uuid'), ('object', 'object_uuid')]
        
        for i, (pos_name, uuid_col) in enumerate(positions):
            term1 = triple1[i]
            term2 = triple2[i]
            
            if isinstance(term1, Variable) and isinstance(term2, Variable) and term1 == term2:
                conditions.append(f"{alias1}.{uuid_col} = {alias2}.{uuid_col}")
        
        return conditions if conditions else ["1=1"]  # Default condition if no shared variables
    
    def _translate_construct_query(self, algebra, table_config: TableConfig) -> str:
        """Translate CONSTRUCT query - placeholder implementation."""
        # TODO: Implement CONSTRUCT query translation
        raise NotImplementedError("CONSTRUCT queries not yet implemented")
    
    def _translate_project(self, pattern, table_config: TableConfig) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate PROJECT pattern - placeholder implementation."""
        # TODO: Implement PROJECT pattern translation
        inner_pattern = pattern['p']
        return self._translate_pattern(inner_pattern, table_config)
    
    def _translate_union(self, pattern, table_config: TableConfig) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate UNION pattern - placeholder implementation."""
        # TODO: Implement UNION pattern translation
        self.logger.warning("UNION pattern not yet implemented")
        return f"FROM {table_config.quad_table} q0", [], [], {}
    
    def _translate_optional(self, pattern, table_config: TableConfig) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate OPTIONAL (LeftJoin) pattern - placeholder implementation."""
        # TODO: Implement OPTIONAL pattern translation
        self.logger.warning("OPTIONAL pattern not yet implemented")
        return f"FROM {table_config.quad_table} q0", [], [], {}
    
    async def _execute_sql_query(self, sql_query: str) -> List[Dict[str, Any]]:
        """Execute SQL query and return results."""
        try:
            # Use the space_impl's get_connection method to get a database connection
            with self.space_impl.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql_query)
                    
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
                
        except Exception as e:
            self.logger.error(f"Error executing SQL query: {e}")
            self.logger.error(f"SQL query was: {sql_query}")
            raise
