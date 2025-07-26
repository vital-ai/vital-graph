"""
PostgreSQL SPARQL Filters Implementation for VitalGraph

This module handles the translation of SPARQL FILTER expressions and built-in functions
to PostgreSQL SQL WHERE and HAVING clauses.
"""

import logging
import re
from typing import List, Dict, Tuple, Set, Optional, Any, Union
from rdflib import Variable, URIRef, Literal, BNode

# Import shared utilities
from .postgresql_sparql_utils import TableConfig, SparqlUtils


class PostgreSQLSparqlFilters:
    """Handles translation of SPARQL FILTER expressions and built-in functions to SQL."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize the filters translator.
        
        Args:
            logger: Optional logger instance. If None, creates a new logger.
        """
        self.logger = logger or logging.getLogger(__name__)
    
    async def translate_filter(self, filter_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate FILTER pattern to SQL.
        
        CRITICAL: Detects HAVING clauses (filters on aggregate expressions) and stores them
        separately from WHERE conditions for proper SQL generation.
        """
        # Get the underlying pattern first
        inner_pattern = filter_pattern['p']
        from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern(inner_pattern, table_config, projected_vars)
        
        # Debug logging
        self.logger.debug(f"Filter pattern variable mappings: {variable_mappings}")
        
        # Translate the filter expression
        filter_expr = filter_pattern['expr']
        self.logger.debug(f"Translating filter expression: {filter_expr}")
        filter_sql = await self.translate_filter_expression(filter_expr, variable_mappings)
        self.logger.debug(f"Filter SQL result: {filter_sql}")
        
        if filter_sql:
            # CRITICAL FIX: Detect if this is a HAVING clause (filter on aggregate expressions)
            # HAVING clauses reference aggregate result variables like __agg_1__, __agg_2__, etc.
            is_having_clause = self._is_having_clause(filter_sql, variable_mappings)
            
            if is_having_clause:
                # This is a HAVING clause - store it separately for SQL generation after GROUP BY
                having_conditions = variable_mappings.get('__HAVING_CONDITIONS__', [])
                having_conditions.append(filter_sql)
                variable_mappings['__HAVING_CONDITIONS__'] = having_conditions
                self.logger.debug(f"Added HAVING condition: {filter_sql}")
            else:
                # Regular WHERE condition
                where_conditions.append(filter_sql)
                self.logger.debug(f"Added WHERE condition: {filter_sql}")
        
        return from_clause, where_conditions, joins, variable_mappings
    

    async def translate_filter_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate a SPARQL filter expression to SQL."""
        # Handle case where expr is a list (multiple filter expressions)
        if isinstance(expr, list):
            if len(expr) == 1:
                return await self.translate_filter_expression(expr[0], variable_mappings)
            else:
                # Multiple expressions - combine with AND
                conditions = []
                for sub_expr in expr:
                    conditions.append(await self.translate_filter_expression(sub_expr, variable_mappings))
                return f"({' AND '.join(conditions)})"
        
        # Handle case where expr doesn't have a name attribute
        if not hasattr(expr, 'name'):
            self.logger.warning(f"Filter expression has no name attribute: {type(expr)}")
            return "1=1"  # No-op condition
        
        expr_name = expr.name
        self.logger.debug(f"Processing filter expression: {expr_name}")
        
        if expr_name == "RelationalExpression":
            return self._translate_relational_expression(expr, variable_mappings)
        elif expr_name == "ConditionalAndExpression":
            return await self._translate_and_expression(expr, variable_mappings)
        elif expr_name == "ConditionalOrExpression":
            return await self._translate_or_expression(expr, variable_mappings)
        elif expr_name == "Builtin_REGEX":
            return self._translate_regex_expression(expr, variable_mappings)
        elif expr_name == "Builtin_CONTAINS":
            return self._translate_contains_expression(expr, variable_mappings)
        elif expr_name == "Builtin_STRSTARTS":
            return self._translate_strstarts_expression(expr, variable_mappings)
        elif expr_name == "Builtin_STRENDS":
            return self._translate_strends_expression(expr, variable_mappings)
        elif expr_name == "Builtin_EXISTS":
            return await self._translate_exists_expression(expr, variable_mappings, is_not_exists=False)
        elif expr_name == "Builtin_NOTEXISTS":
            return await self._translate_exists_expression(expr, variable_mappings, is_not_exists=True)
        elif expr_name == "Builtin_LANG":
            return self._translate_lang_filter_expression(expr, variable_mappings)
        elif expr_name == "Builtin_DATATYPE":
            return self._translate_datatype_filter_expression(expr, variable_mappings)
        elif expr_name in ["Builtin_URI", "Builtin_IRI"]:
            return self._translate_uri_filter_expression(expr, variable_mappings)
        elif expr_name == "Builtin_BNODE":
            return self._translate_bnode_filter_expression(expr, variable_mappings)
        elif expr_name == "Builtin_isURI":
            return self._translate_isuri_filter_expression(expr, variable_mappings)
        elif expr_name == "Builtin_isLITERAL":
            return self._translate_isliteral_filter_expression(expr, variable_mappings)
        elif expr_name == "Builtin_isNUMERIC":
            return self._translate_isnumeric_filter_expression(expr, variable_mappings)
        elif expr_name == "Builtin_BOUND":
            return self._translate_bound_filter_expression(expr, variable_mappings)
        elif expr_name == "Builtin_sameTerm":
            return self._translate_sameterm_filter_expression(expr, variable_mappings)
        # NOTE: IN() is handled as RelationalExpression with op='IN', not as a builtin function
        else:
            self.logger.warning(f"Filter expression {expr_name} not implemented")
            return "1=1"  # No-op condition
    
    def get_supported_builtin_functions(self) -> Set[str]:
        """Get the set of supported SPARQL built-in filter functions.
        
        Returns:
            Set of supported built-in function names
        """
        return {
            "RelationalExpression",
            "ConditionalAndExpression", "ConditionalOrExpression",
            "Builtin_REGEX", "Builtin_CONTAINS", "Builtin_STRSTARTS", "Builtin_STRENDS",
            "Builtin_EXISTS", "Builtin_NOTEXISTS",
            "Builtin_LANG", "Builtin_DATATYPE", "Builtin_URI", "Builtin_IRI", "Builtin_BNODE",
            "Builtin_isURI", "Builtin_isLITERAL", "Builtin_isNUMERIC", "Builtin_BOUND", "Builtin_sameTerm"
        }
    
    def is_supported_builtin(self, function_name: str) -> bool:
        """Check if a function name is a supported built-in filter function.
        
        Args:
            function_name: Name of the function to check
            
        Returns:
            True if the function is supported
        """
        return function_name in self.get_supported_builtin_functions()
    
    def is_having_clause(self, filter_sql: str, variable_mappings: Dict[Variable, str]) -> bool:
        """Detect if a filter SQL should be a HAVING clause (filters on aggregate expressions).
        
        Args:
            filter_sql: The generated SQL filter condition
            variable_mappings: Current variable to SQL column mappings
            
        Returns:
            True if this should be a HAVING clause
        """
        # Check if the filter references aggregate result variables like __agg_1__, __agg_2__, etc.
        import re
        agg_pattern = r'__agg_\d+__'
        return bool(re.search(agg_pattern, filter_sql))
    
    def extract_filter_variables(self, expr) -> Set[Variable]:
        """Extract all variables referenced in a filter expression.
        
        Args:
            expr: Filter expression to analyze
            
        Returns:
            Set of variables found in the expression
        """
        variables = set()
        
        # Handle list of expressions
        if isinstance(expr, list):
            for sub_expr in expr:
                variables.update(self.extract_filter_variables(sub_expr))
            return variables
        
        # Handle expressions with arguments
        if hasattr(expr, 'arg') and isinstance(expr.arg, Variable):
            variables.add(expr.arg)
        elif hasattr(expr, 'args'):
            for arg in expr.args:
                if isinstance(arg, Variable):
                    variables.add(arg)
                elif hasattr(arg, 'arg') and isinstance(arg.arg, Variable):
                    variables.add(arg.arg)
        
        # Handle relational expressions with left/right operands
        if hasattr(expr, 'left') and isinstance(expr.left, Variable):
            variables.add(expr.left)
        if hasattr(expr, 'right') and isinstance(expr.right, Variable):
            variables.add(expr.right)
        
        return variables
    
    def escape_sql_string(self, value: str) -> str:
        """Escape a string value for safe inclusion in SQL.
        
        Args:
            value: String value to escape
            
        Returns:
            SQL-safe escaped string
        """
        # Escape single quotes by doubling them
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    
    def convert_sparql_operator_to_sql(self, sparql_op: str) -> str:
        """Convert SPARQL comparison operators to SQL equivalents.
        
        Args:
            sparql_op: SPARQL operator (=, !=, <, <=, >, >=, etc.)
            
        Returns:
            SQL operator equivalent
        """
        operator_map = {
            '=': '=',
            '!=': '!=', 
            '<>': '!=',
            '<': '<',
            '<=': '<=',
            '>': '>',
            '>=': '>=',
            'IN': 'IN',
            'NOT IN': 'NOT IN'
        }
        return operator_map.get(sparql_op, sparql_op)
    
    def build_regex_condition(self, text_expr: str, pattern: str, flags: Optional[str] = None) -> str:
        """Build a PostgreSQL regex condition.
        
        Args:
            text_expr: SQL expression for the text to match
            pattern: Regex pattern
            flags: Optional regex flags (i for case-insensitive)
            
        Returns:
            PostgreSQL regex condition
        """
        # Escape single quotes in pattern
        escaped_pattern = pattern.replace("'", "''")
        
        if flags and 'i' in flags.lower():
            # Case-insensitive regex
            return f"{text_expr} ~* '{escaped_pattern}'"
        else:
            # Case-sensitive regex
            return f"{text_expr} ~ '{escaped_pattern}'"
    
    def build_string_contains_condition(self, text_expr: str, substring: str, case_sensitive: bool = True) -> str:
        """Build a string contains condition using PostgreSQL LIKE or ILIKE.
        
        Args:
            text_expr: SQL expression for the text to search in
            substring: Substring to search for
            case_sensitive: Whether the search should be case-sensitive
            
        Returns:
            PostgreSQL string contains condition
        """
        # Escape LIKE special characters and single quotes
        escaped = substring.replace("'", "''").replace('%', '\\%').replace('_', '\\_')
        pattern = f"'%{escaped}%'"
        
        if case_sensitive:
            return f"{text_expr} LIKE {pattern}"
        else:
            return f"{text_expr} ILIKE {pattern}"
    
    def build_string_starts_condition(self, text_expr: str, prefix: str, case_sensitive: bool = True) -> str:
        """Build a string starts-with condition.
        
        Args:
            text_expr: SQL expression for the text to check
            prefix: Prefix to check for
            case_sensitive: Whether the check should be case-sensitive
            
        Returns:
            PostgreSQL string starts-with condition
        """
        # Escape LIKE special characters and single quotes
        escaped = prefix.replace("'", "''").replace('%', '\\%').replace('_', '\\_')
        pattern = f"'{escaped}%'"
        
        if case_sensitive:
            return f"{text_expr} LIKE {pattern}"
        else:
            return f"{text_expr} ILIKE {pattern}"
    
    def build_string_ends_condition(self, text_expr: str, suffix: str, case_sensitive: bool = True) -> str:
        """Build a string ends-with condition.
        
        Args:
            text_expr: SQL expression for the text to check
            suffix: Suffix to check for
            case_sensitive: Whether the check should be case-sensitive
            
        Returns:
            PostgreSQL string ends-with condition
        """
        # Escape LIKE special characters and single quotes
        escaped = suffix.replace("'", "''").replace('%', '\\%').replace('_', '\\_')
        pattern = f"'%{escaped}'"
        
        if case_sensitive:
            return f"{text_expr} LIKE {pattern}"
        else:
            return f"{text_expr} ILIKE {pattern}"
    
    def validate_filter_pattern(self, filter_pattern) -> bool:
        """Validate that a filter pattern has the expected structure.
        
        Args:
            filter_pattern: The filter pattern to validate
            
        Returns:
            True if the pattern is valid
        """
        try:
            # Check for required keys
            if not isinstance(filter_pattern, dict):
                self.logger.error("Filter pattern is not a dictionary")
                return False
                
            if 'p' not in filter_pattern:
                self.logger.error("Filter pattern missing 'p' (nested pattern) key")
                return False
                
            if 'expr' not in filter_pattern:
                self.logger.error("Filter pattern missing 'expr' (filter expression) key")
                return False
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating filter pattern: {e}")
            return False
    
    def get_term_type_check_sql(self, variable_expr: str, term_type: str) -> str:
        """Generate SQL to check the type of a term (URI, Literal, BNode).
        
        Args:
            variable_expr: SQL expression for the variable
            term_type: Type to check for ('U' for URI, 'L' for Literal, 'B' for BNode)
            
        Returns:
            SQL condition to check term type
        """
        # Assuming term type is stored in a separate column or can be determined
        # This would need to be adapted based on the actual table schema
        return f"{variable_expr}_type = '{term_type}'"
    
    def build_bound_condition(self, variable: Variable, variable_mappings: Dict[Variable, str]) -> str:
        """Build a BOUND() condition to check if a variable is bound.
        
        Args:
            variable: Variable to check
            variable_mappings: Current variable mappings
            
        Returns:
            SQL condition to check if variable is bound (not NULL)
        """
        if variable in variable_mappings:
            return f"{variable_mappings[variable]} IS NOT NULL"
        else:
            self.logger.warning(f"BOUND() check for unmapped variable {variable}")
            return "FALSE"  # Unmapped variables are considered unbound

    