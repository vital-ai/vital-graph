"""
PostgreSQL SPARQL Expressions Functions for VitalGraph

This module provides pure functions for translating SPARQL expressions and filters
to SQL expressions. No inter-dependencies with other SPARQL modules - only imports utilities.
"""

import logging
import re
from typing import Dict, List, Tuple, Set, Optional, Any, Union
from rdflib import Variable, URIRef, Literal, BNode
from rdflib.namespace import XSD
from rdflib.plugins.sparql.parserutils import CompValue

# Configure logging
logger = logging.getLogger(__name__)


async def translate_filter_expression(expr, variable_mappings: Dict[Variable, str], context=None) -> str:
    """Translate a SPARQL filter expression to SQL."""
    # Handle case where expr is a list (multiple filter expressions)
    if isinstance(expr, list):
        if len(expr) == 1:
            return await translate_filter_expression(expr[0], variable_mappings, context)
        else:
            # Multiple expressions - combine with AND
            conditions = []
            for sub_expr in expr:
                condition = await translate_filter_expression(sub_expr, variable_mappings, context)
                conditions.append(condition)
            return f"({' AND '.join(conditions)})"
    
    # Handle case where expr doesn't have a name attribute
    if not hasattr(expr, 'name'):
        logger.warning(f"Filter expression has no name attribute: {type(expr)}")
        return "1=1"  # No-op condition
    
    expr_name = expr.name
    logger.debug(f"Processing filter expression: {expr_name}")
    
    if expr_name == "RelationalExpression":
        return await _translate_relational_expression(expr, variable_mappings, context)
    elif expr_name == "ConditionalAndExpression":
        return await _translate_and_expression(expr, variable_mappings, context)
    elif expr_name == "ConditionalOrExpression":
        return await _translate_or_expression(expr, variable_mappings, context)
    elif expr_name == "Builtin_REGEX":
        return _translate_regex_expression(expr, variable_mappings)
    elif expr_name == "Builtin_CONTAINS":
        return _translate_contains_expression(expr, variable_mappings)
    elif expr_name == "Builtin_STRSTARTS":
        return _translate_strstarts_expression(expr, variable_mappings)
    elif expr_name == "Builtin_STRENDS":
        return _translate_strends_expression(expr, variable_mappings)
    elif expr_name == "Builtin_EXISTS":
        return await _translate_exists_expression(expr, variable_mappings, is_not_exists=False)
    elif expr_name == "Builtin_NOTEXISTS":
        return await _translate_exists_expression(expr, variable_mappings, is_not_exists=True)
    elif expr_name == "Builtin_LANG":
        return _translate_lang_filter_expression(expr, variable_mappings)
    elif expr_name == "Builtin_DATATYPE":
        return _translate_datatype_filter_expression(expr, variable_mappings, context)
    elif expr_name in ["Builtin_URI", "Builtin_IRI"]:
        return _translate_uri_filter_expression(expr, variable_mappings)
    elif expr_name == "Builtin_BNODE":
        return _translate_bnode_filter_expression(expr, variable_mappings)
    elif expr_name == "Builtin_isURI":
        return _translate_isuri_filter_expression(expr, variable_mappings)
    elif expr_name == "Builtin_isIRI":
        return _translate_isuri_filter_expression(expr, variable_mappings)  # isIRI is alias for isURI
    elif expr_name == "Builtin_isLITERAL":
        return _translate_isliteral_filter_expression(expr, variable_mappings)
    elif expr_name == "Builtin_isNUMERIC":
        return _translate_isnumeric_filter_expression(expr, variable_mappings)
    elif expr_name == "Builtin_isBLANK":
        return _translate_isblank_filter_expression(expr, variable_mappings)
    elif expr_name == "Builtin_BOUND":
        return _translate_bound_filter_expression(expr, variable_mappings)
    elif expr_name == "Builtin_sameTerm":
        return _translate_sameterm_filter_expression(expr, variable_mappings)
    # NOTE: IN() is handled as RelationalExpression with op='IN', not as a builtin function
    else:
        logger.warning(f"Filter expression {expr_name} not implemented")
        return "1=1"  # No-op condition


async def _translate_relational_expression(expr, variable_mappings: Dict[Variable, str], context=None) -> str:
    """Translate relational expression (=, !=, <, >, etc.)."""
    operator = expr['op']
    left = expr['expr']
    right = expr['other']
    
    # Handle IN operator specially
    if operator == 'IN':
        left_sql = await _translate_expression_operand(left, variable_mappings, context=context)
        if isinstance(right, list):
            # Multiple values for IN
            values = []
            for value in right:
                value_sql = await _translate_expression_operand(value, variable_mappings, context=context)
                values.append(value_sql)
            if values:
                return f"({left_sql} IN ({', '.join(values)}))"
            else:
                return "FALSE"  # Empty IN list is always false
        else:
            # Single value case (shouldn't happen with IN but handle gracefully)
            right_sql = await _translate_expression_operand(right, variable_mappings, context=context)
            return f"({left_sql} = {right_sql})"
    
    # Determine if this is a numeric comparison
    numeric_operators = {'<', '<=', '>', '>='}
    is_numeric = operator in numeric_operators
    
    try:
        left_sql = await _translate_expression_operand(left, variable_mappings, cast_numeric=is_numeric, context=context)
        right_sql = await _translate_expression_operand(right, variable_mappings, cast_numeric=is_numeric, context=context)
        
        # Ensure we got string SQL representations, not dict objects
        if not isinstance(left_sql, str):
            logger.warning(f"Left operand translation returned non-string: {type(left_sql)}, value: {left_sql}")
            left_sql = str(left_sql)
        if not isinstance(right_sql, str):
            logger.warning(f"Right operand translation returned non-string: {type(right_sql)}, value: {right_sql}")
            right_sql = str(right_sql)
        
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
        
    except Exception as e:
        logger.error(f"Error translating relational expression {operator}: {e}")
        logger.error(f"Left operand: {left}, Right operand: {right}")
        # Return a safe fallback condition
        return "1=1"


async def _translate_and_expression(expr, variable_mappings: Dict[Variable, str], context=None) -> str:
    """Translate AND expression."""
    left = await translate_filter_expression(expr['expr'], variable_mappings, context)
    right = await translate_filter_expression(expr['other'], variable_mappings, context)
    return f"({left} AND {right})"


async def _translate_or_expression(expr, variable_mappings: Dict[Variable, str], context=None) -> str:
    """Translate OR expression."""
    left = await translate_filter_expression(expr['expr'], variable_mappings, context)
    right = await translate_filter_expression(expr['other'], variable_mappings, context)
    return f"({left} OR {right})"


async def _translate_expression_operand(operand, variable_mappings: Dict[Variable, str], cast_numeric: bool = False, context=None) -> str:
    """Translate an expression operand (variable or literal)."""
    logger.debug(f"Translating operand: {operand}, type: {type(operand)}, is Variable: {isinstance(operand, Variable)}")
    if isinstance(operand, Variable):
        logger.debug(f"Variable {operand} in mappings: {operand in variable_mappings}")
        if operand in variable_mappings:
            term_column = variable_mappings[operand]
            logger.debug(f"Variable {operand} mapped to: {term_column}")
            # Only cast to numeric types when explicitly requested for numeric operations
            if cast_numeric:
                return f"CAST({term_column} AS DECIMAL)"
            else:
                return term_column
        else:
            logger.debug(f"Variable {operand} not found in mappings: {list(variable_mappings.keys())}")
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
        return await _translate_function_expression(operand, variable_mappings, context)
    
    # Direct value fallback
    if operand is None:
        return "NULL"
    elif isinstance(operand, str):
        return f"'{operand}'"
    else:
        return str(operand)


async def _translate_function_expression(func_expr, variable_mappings: Dict[Variable, str], context=None) -> str:
    """Translate function expressions in FILTER operands."""
    func_name = func_expr.name
    
    # Handle STRLEN function (can be 'STRLEN' or 'Builtin_STRLEN')
    if func_name == 'STRLEN' or func_name == 'Builtin_STRLEN':
        # Try 'arg' first (most common for STRLEN), then 'expr'
        if hasattr(func_expr, 'arg') and func_expr.arg:
            logger.debug(f"STRLEN arg: {func_expr.arg}, type: {type(func_expr.arg)}")
            arg_sql = await _translate_expression_operand(func_expr.arg, variable_mappings, context=context)
            logger.debug(f"STRLEN translated to: LENGTH({arg_sql})")
            return f"LENGTH({arg_sql})"
        elif hasattr(func_expr, 'expr') and func_expr.expr:
            logger.debug(f"STRLEN expr: {func_expr.expr}, type: {type(func_expr.expr)}")
            arg_sql = await _translate_expression_operand(func_expr.expr, variable_mappings, context=context)
            logger.debug(f"STRLEN translated to: LENGTH({arg_sql})")
            return f"LENGTH({arg_sql})"
        else:
            logger.warning(f"STRLEN function missing argument")
            return "NULL"
    
    # Handle other common SPARQL functions
    elif func_name == 'UCASE':
        if hasattr(func_expr, 'expr') and func_expr.expr:
            arg_sql = await _translate_expression_operand(func_expr.expr, variable_mappings, context=context)
            return f"UPPER({arg_sql})"
        else:
            return "NULL"
    
    elif func_name == 'LCASE':
        if hasattr(func_expr, 'expr') and func_expr.expr:
            arg_sql = await _translate_expression_operand(func_expr.expr, variable_mappings, context=context)
            return f"LOWER({arg_sql})"
        else:
            return "NULL"
    
    elif func_name == 'SUBSTR':
        if hasattr(func_expr, 'expr') and hasattr(func_expr, 'start'):
            str_sql = await _translate_expression_operand(func_expr.expr, variable_mappings, context=context)
            start_sql = await _translate_expression_operand(func_expr.start, variable_mappings, context=context)
            if hasattr(func_expr, 'length') and func_expr.length:
                length_sql = await _translate_expression_operand(func_expr.length, variable_mappings, context=context)
                return f"SUBSTRING({str_sql} FROM {start_sql} FOR {length_sql})"
            else:
                return f"SUBSTRING({str_sql} FROM {start_sql})"
        else:
            return "NULL"
    
    # DATATYPE and LANG functions - Previously missing
    elif func_name == 'Builtin_DATATYPE':
        if hasattr(func_expr, 'arg'):
            arg_sql = await _translate_expression_operand(func_expr.arg, variable_mappings, context=context)
            # Use the same logic as _translate_datatype_filter_expression
            if '.term_text' in arg_sql:
                # Extract the table alias from the arg_sql
                table_alias = arg_sql.split('.')[0]
                
                # Get the datatype table name from context
                datatype_table = None
                if context and context.space_impl and context.space_id:
                    table_names = context.space_impl._get_table_names(context.space_id)
                    datatype_table = table_names.get('datatype')
                
                if datatype_table:
                    # Use the datatype table to resolve datatype URIs
                    return f"""(
                        CASE 
                            WHEN {table_alias}.datatype_id IS NOT NULL THEN (
                                SELECT dt.datatype_uri 
                                FROM {datatype_table} dt 
                                WHERE dt.datatype_id = {table_alias}.datatype_id
                            )
                            WHEN {table_alias}.term_type = 'L' THEN 'http://www.w3.org/2001/XMLSchema#string'
                            WHEN {table_alias}.term_type = 'U' THEN NULL
                            WHEN {table_alias}.term_type = 'B' THEN NULL
                            ELSE 'http://www.w3.org/2001/XMLSchema#string'
                        END
                    )"""
                else:
                    # Fallback to regex-based datatype inference
                    return f"""(
                        CASE 
                            WHEN {table_alias}.term_type = 'L' AND {table_alias}.term_text ~ '^[+-]?[0-9]+$' THEN 'http://www.w3.org/2001/XMLSchema#integer'
                            WHEN {table_alias}.term_type = 'L' AND {table_alias}.term_text ~ '^[+-]?[0-9]*\\.[0-9]+$' THEN 'http://www.w3.org/2001/XMLSchema#decimal'
                            WHEN {table_alias}.term_type = 'L' AND {table_alias}.term_text ~ '^[+-]?[0-9]*\\.?[0-9]+([eE][+-]?[0-9]+)?$' THEN 'http://www.w3.org/2001/XMLSchema#double'
                            WHEN {table_alias}.term_type = 'L' AND LOWER({table_alias}.term_text) IN ('true', 'false') THEN 'http://www.w3.org/2001/XMLSchema#boolean'
                            WHEN {table_alias}.term_type = 'L' THEN 'http://www.w3.org/2001/XMLSchema#string'
                            WHEN {table_alias}.term_type = 'U' THEN NULL
                            WHEN {table_alias}.term_type = 'B' THEN NULL
                            ELSE 'http://www.w3.org/2001/XMLSchema#string'
                        END
                    )"""
            else:
                # For literal values in the query, return xsd:string as default
                return "'http://www.w3.org/2001/XMLSchema#string'"
        return "NULL"
    
    elif func_name == 'Builtin_LANG':
        if hasattr(func_expr, 'arg'):
            arg_sql = await _translate_expression_operand(func_expr.arg, variable_mappings, context=context)
            # For variables, we need to look up the language from the term table
            if '.term_text' in arg_sql:
                # Replace term_text with lang column
                lang_sql = arg_sql.replace('.term_text', '.lang')
                return f"COALESCE({lang_sql}, '')"
            else:
                # For non-variable values, return empty string
                return "''"
        return "''"
    
    # URI and IRI functions
    elif func_name in ['Builtin_URI', 'Builtin_IRI']:
        if hasattr(func_expr, 'arg'):
            arg_sql = await _translate_expression_operand(func_expr.arg, variable_mappings, context=context)
            # URI/IRI just returns the string value for SQL purposes
            return arg_sql
        return "NULL"
    
    # Type checking functions
    elif func_name == 'Builtin_isURI':
        if hasattr(func_expr, 'arg'):
            arg_sql = await _translate_expression_operand(func_expr.arg, variable_mappings, context=context)
            # Check if the value looks like a URI using regex pattern matching
            uri_pattern = "'^(https?|ftp|file|mailto|urn|ldap|news|gopher|telnet):[^\\s]*$'"
            return f"({arg_sql} ~ {uri_pattern})"
        return "FALSE"
    
    elif func_name == 'Builtin_isLITERAL':
        if hasattr(func_expr, 'arg'):
            arg_sql = await _translate_expression_operand(func_expr.arg, variable_mappings, context=context)
            # Check if the value is NOT a URI (inverse of isURI check)
            uri_pattern = "'^(https?|ftp|file|mailto|urn|ldap|news|gopher|telnet):[^\\s]*$'"
            return f"NOT ({arg_sql} ~ {uri_pattern})"
        return "FALSE"
    
    elif func_name == 'Builtin_isNUMERIC':
        if hasattr(func_expr, 'arg'):
            arg_sql = await _translate_expression_operand(func_expr.arg, variable_mappings, context=context)
            # Use PostgreSQL's improved numeric pattern matching
            numeric_pattern = "'^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$'"
            return f"({arg_sql} ~ {numeric_pattern})"
        return "FALSE"
    
    elif func_name == 'Builtin_isBLANK':
        if hasattr(func_expr, 'arg'):
            arg_sql = await _translate_expression_operand(func_expr.arg, variable_mappings, context=context)
            # For variables, check the term_type in the database
            if '.term_text' in arg_sql:
                # Replace term_text with term_type and check for 'B' (Blank Node)
                term_type_sql = arg_sql.replace('.term_text', '.term_type')
                return f"({term_type_sql} = 'B')"
            else:
                # For non-variable values, check if they start with '_:'
                return f"({arg_sql}::text LIKE '_:%')"
        return "FALSE"
    
    elif func_name == 'Builtin_BNODE':
        return _translate_builtin_bnode(func_expr, variable_mappings)
    
    elif func_name == 'Builtin_UUID':
        return _translate_builtin_uuid(func_expr, variable_mappings)
    
    # For unimplemented functions, try using translate_bind_expression
    # This handles cases where builtin functions are used in filter expressions
    try:
        logger.debug(f"Attempting to translate function {func_name} using translate_bind_expression")
        result = translate_bind_expression(func_expr, variable_mappings, context)
        if result and result != "1=1" and not result.startswith("'MISSING") and not result.startswith("'PARSE_ERROR"):
            return result
    except Exception as e:
        logger.debug(f"translate_bind_expression failed for {func_name}: {e}")
    
    # Final fallback - log warning and return NULL
    logger.warning(f"Function expression {func_name} not implemented in operand translation")
    return "NULL"


def _translate_expression_operand_sync(operand, variable_mappings: Dict[Variable, str], cast_numeric: bool = False) -> str:
    """Synchronous version of _translate_expression_operand for simple cases."""
    logger.debug(f"Translating operand: {operand}, type: {type(operand)}, is Variable: {isinstance(operand, Variable)}")
    
    # Handle nested builtin functions (e.g., LCASE(?name) inside CONTAINS)
    if hasattr(operand, 'name') and operand.name and operand.name.startswith('Builtin_'):
        logger.debug(f"Found nested builtin function: {operand.name}")
        try:
            # Use translate_bind_expression to handle the nested builtin
            return translate_bind_expression(operand, variable_mappings)
        except Exception as e:
            logger.warning(f"Error translating nested builtin {operand.name}: {e}")
            return f"'ERROR_NESTED_BUILTIN_{operand.name}'"
    
    if isinstance(operand, Variable):
        logger.debug(f"Variable {operand} in mappings: {operand in variable_mappings}")
        if operand in variable_mappings:
            term_column = variable_mappings[operand]
            logger.debug(f"Variable {operand} mapped to: {term_column}")
            # Only cast to numeric types when explicitly requested for numeric operations
            if cast_numeric:
                return f"CAST({term_column} AS DECIMAL)"
            else:
                return term_column
        else:
            logger.debug(f"Variable {operand} not found in mappings: {list(variable_mappings.keys())}")
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

    # Direct value fallback
    if operand is None:
        return "NULL"
    elif isinstance(operand, str):
        return f"'{operand}'"
    else:
        return str(operand)


def translate_bind_arg(arg, variable_mappings: Dict) -> str:
    """Translate a single argument in a BIND expression.
    Uses exact original implementation from postgresql_sparql_impl.py.
    
    Args:
        arg: Argument (Variable, Literal, URIRef, or nested expression)
        variable_mappings: Current variable mappings
        
    Returns:
        SQL representation of the argument
    """
    from rdflib import Variable, Literal, URIRef
    from rdflib.plugins.sparql.parserutils import CompValue
    
    if isinstance(arg, Variable):
        # Variable reference - look up in mappings
        var_name = str(arg)
        if arg in variable_mappings:
            # Get the SQL column reference for this variable
            mapping = variable_mappings[arg]
            
            # CRITICAL FIX: Aggregate result variables (like __agg_1__) contain complete SQL expressions
            # that should NOT be split on ' AS ' since they may contain CAST(...AS...) expressions
            if var_name.startswith('__agg_'):
                # This is an aggregate result variable - return the complete SQL expression
                logger.debug(f"Returning aggregate expression for {var_name}: {mapping}")
                return mapping
            else:
                # Regular variable - extract just the column reference (remove AS clause if present)
                # BUT: Don't split CAST expressions like "CAST(col AS DECIMAL)"
                if ' AS ' in mapping and not mapping.strip().startswith('CAST(') and not 'CAST(' in mapping:
                    return mapping.split(' AS ')[0]
                return mapping
        else:
            logger.warning(f"Variable {var_name} not found in mappings")
            # CRITICAL DEBUG: Show available mappings to help debug variable mapping issues
            logger.warning(f"Available variable mappings: {list(variable_mappings.keys())}")
            return f"'UNMAPPED_{var_name}'"
            
    elif isinstance(arg, Literal):
        # Literal value - escape for SQL
        escaped_value = str(arg).replace("'", "''")
        return f"'{escaped_value}'"
        
    elif isinstance(arg, URIRef):
        # URI reference - treat as string literal
        escaped_value = str(arg).replace("'", "''")
        return f"'{escaped_value}'"
        
    elif isinstance(arg, CompValue):
        # Nested expression - recursively translate
        return translate_bind_expression(arg, variable_mappings)
        
    elif isinstance(arg, (int, float)):
        # Numeric literal
        return str(arg)
        
    elif isinstance(arg, str):
        # String literal - check if it's numeric
        try:
            # Try to parse as number first
            if '.' in arg:
                float(arg)
                return arg  # Return as numeric literal
            else:
                int(arg)
                return arg  # Return as numeric literal
        except ValueError:
            # It's a string literal, escape it
            escaped_value = arg.replace("'", "''")
            return f"'{escaped_value}'"
            
    elif isinstance(arg, list):
        # Handle list arguments (can occur in complex expressions)
        logger.debug(f"List argument in BIND: {arg} (length: {len(arg)})")
        if len(arg) == 1:
            # Single element list - unwrap and translate
            return translate_bind_arg(arg[0], variable_mappings)
        elif len(arg) > 1:
            # Multiple elements - check if this is a built-in function call
            first_elem = arg[0]
            if isinstance(first_elem, str) and first_elem.startswith('Builtin_'):
                # This is a built-in function call wrapped in a list
                # Create a CompValue-like structure to handle it
                logger.debug(f"Detected built-in function in list: {first_elem}")
                try:
                    # Create a mock CompValue structure
                    class MockCompValue:
                        def __init__(self, name, args):
                            self.name = name
                            # For BOUND function, the argument is typically the second element
                            if name == 'Builtin_BOUND' and len(args) > 1:
                                self.arg = args[1]  # Variable argument for BOUND
                            else:
                                self.args = args[1:] if len(args) > 1 else []
                    
                    mock_comp = MockCompValue(first_elem, arg)
                    return translate_bind_expression(mock_comp, variable_mappings)
                except Exception as e:
                    logger.error(f"Error handling built-in function in list: {e}")
                    return "NULL"
            else:
                # Multiple elements, not a function - translate first element
                return translate_bind_arg(arg[0], variable_mappings)
        else:
            return "NULL"  # Empty list becomes NULL
            
    elif arg is None:
        # Handle None values explicitly
        logger.warning("None argument in BIND expression")
        return "NULL"
        
    else:
        logger.warning(f"Unknown argument type in BIND: {type(arg)} with value: {arg}")
        return "NULL"  # Return NULL instead of string that might cause SQL errors


def translate_bind_expression(bind_expr, variable_mappings: Dict, context=None) -> str:
    """Translate a SPARQL BIND expression to PostgreSQL SQL.
    Uses exact original implementation from postgresql_sparql_impl.py.
    
    Args:
        bind_expr: RDFLib expression object from BIND statement
        variable_mappings: Current variable to SQL column mappings
        
    Returns:
        SQL expression string
    """
    from rdflib.plugins.sparql.parserutils import CompValue
    from rdflib import Variable, Literal, URIRef
    
    # RDFLib BIND expressions are parsed as Expr objects with dict-like access
    
    logger.debug(f"Translating BIND expression: {bind_expr} (type: {type(bind_expr)})")
    
    # Handle different expression types
    if isinstance(bind_expr, CompValue):
        # CompValue represents function calls and operations
        expr_name = bind_expr.name
        logger.debug(f"CompValue expression name: {expr_name}")
        
        if expr_name == 'Builtin_CONCAT':
            # CONCAT(arg1, arg2, ...) -> CONCAT(arg1, arg2, ...)
            args = [translate_bind_arg(arg, variable_mappings) for arg in bind_expr.arg]
            return f"CONCAT({', '.join(args)})"
            
        elif expr_name == 'Builtin_STR':
            # STR(?var) -> CAST(var AS TEXT)
            arg = translate_bind_arg(bind_expr.arg, variable_mappings)
            return f"CAST({arg} AS TEXT)"
            
        elif expr_name == 'Builtin_IF':
            # IF(condition, true_val, false_val) -> CASE WHEN condition THEN true_val ELSE false_val END
            # RDFLib stores IF args as dict keys: 'arg1', 'arg2', 'arg3'
            try:
                # Extract arguments from dictionary keys
                if 'arg1' in bind_expr and 'arg2' in bind_expr and 'arg3' in bind_expr:
                    condition = translate_bind_arg(bind_expr['arg1'], variable_mappings)
                    true_val = translate_bind_arg(bind_expr['arg2'], variable_mappings)
                    false_val = translate_bind_arg(bind_expr['arg3'], variable_mappings)
                    return f"CASE WHEN {condition} THEN {true_val} ELSE {false_val} END"
                else:
                    logger.warning(f"IF missing required keys 'arg1', 'arg2', or 'arg3' in {bind_expr.keys()}")
                    return "'IF_MISSING_KEYS'"
            except Exception as e:
                logger.warning(f"Error parsing IF expression: {e}")
                return "'IF_PARSE_ERROR'"
                
        elif expr_name == 'MultiplicativeExpression':
            # Handle multiplication and division expressions like ?age * 12 or ?x / ?y
            # CRITICAL FIX: This was missing from refactored implementation
            try:
                if hasattr(bind_expr, 'expr') and hasattr(bind_expr, 'other') and hasattr(bind_expr, 'op'):
                    left = translate_bind_expression(bind_expr.expr, variable_mappings, context)
                    right = translate_bind_expression(bind_expr.other, variable_mappings, context)
                    
                    # Handle operator - it might be a list or a string
                    op_raw = bind_expr.op
                    if isinstance(op_raw, list) and len(op_raw) > 0:
                        op = str(op_raw[0])  # Take first element if it's a list
                    else:
                        op = str(op_raw)
                    
                    logger.debug(f"MultiplicativeExpression operator: {op_raw} -> {op}")
                    
                    # Map SPARQL operators to SQL operators
                    if op == '*':
                        # Add type casting for arithmetic operations
                        return f"(CAST({left} AS DECIMAL) * CAST({right} AS DECIMAL))"
                    elif op == '/':
                        # Use NULLIF to avoid division by zero and add type casting
                        return f"(CAST({left} AS DECIMAL) / NULLIF(CAST({right} AS DECIMAL), 0))"
                    else:
                        logger.warning(f"Unknown multiplicative operator: {op}")
                        return "NULL"
                else:
                    logger.warning(f"MultiplicativeExpression missing required attributes: {bind_expr}")
                    return "NULL"
            except Exception as e:
                logger.error(f"Error translating MultiplicativeExpression: {e}")
                return "NULL"
                
        elif expr_name == 'RelationalExpression':
            # Handle comparison operations like ?age < 30
            # CRITICAL FIX: This was missing from refactored implementation
            try:
                if hasattr(bind_expr, 'op'):
                    op = bind_expr.op
                    logger.debug(f"Comparison operator: {op}")
                    
                    # Get left and right operands
                    left_expr = getattr(bind_expr, 'expr', None)
                    right_expr = getattr(bind_expr, 'other', None)
                    
                    if left_expr is None or right_expr is None:
                        logger.warning(f"Missing operands in comparison: left={left_expr}, right={right_expr}")
                        return "FALSE"
                    
                    left = translate_bind_arg(left_expr, variable_mappings)
                    right = translate_bind_arg(right_expr, variable_mappings)
                    
                    # Ensure we don't have None values
                    if left is None:
                        left = "NULL"
                    if right is None:
                        right = "NULL"
                    
                    # Map SPARQL operators to SQL
                    op_mapping = {
                        '=': '=',
                        '!=': '!=', 
                        '<': '<',
                        '<=': '<=',
                        '>': '>',
                        '>=': '>=',
                        '&&': 'AND',
                        '||': 'OR'
                    }
                    
                    sql_op = op_mapping.get(op, op)
                    result = f"({left} {sql_op} {right})"
                    logger.debug(f"Translated comparison to: {result}")
                    return result
                else:
                    logger.warning(f"Unsupported comparison expression (no op): {bind_expr}")
                    return "FALSE"
            except Exception as e:
                logger.error(f"Error translating RelationalExpression: {e}")
                return "FALSE"
                
        elif expr_name == 'AdditiveExpression':
            # Handle addition and subtraction expressions like ?x + ?y or ?x - ?y
            # CRITICAL FIX: This was missing from refactored implementation
            try:
                if hasattr(bind_expr, 'expr') and hasattr(bind_expr, 'other') and hasattr(bind_expr, 'op'):
                    left = translate_bind_expression(bind_expr.expr, variable_mappings, context)
                    right = translate_bind_expression(bind_expr.other, variable_mappings, context)
                    
                    # Handle operator - it might be a list or a string
                    op_raw = bind_expr.op
                    if isinstance(op_raw, list) and len(op_raw) > 0:
                        op = str(op_raw[0])  # Take first element if it's a list
                    else:
                        op = str(op_raw)
                    
                    logger.debug(f"AdditiveExpression operator: {op_raw} -> {op}")
                    
                    # Map SPARQL operators to SQL operators
                    if op == '+':
                        # Add type casting for arithmetic operations
                        return f"(CAST({left} AS DECIMAL) + CAST({right} AS DECIMAL))"
                    elif op == '-':
                        # Add type casting for arithmetic operations
                        return f"(CAST({left} AS DECIMAL) - CAST({right} AS DECIMAL))"
                    else:
                        logger.warning(f"Unknown additive operator: {op}")
                        return "NULL"
                else:
                    logger.warning(f"AdditiveExpression missing required attributes: {bind_expr}")
                    return "NULL"
            except Exception as e:
                logger.error(f"Error translating AdditiveExpression: {e}")
                return "NULL"
        
        # CRITICAL BUILTIN FUNCTIONS - Connect existing implementations
        elif expr_name == 'Builtin_BOUND':
            return _translate_builtin_bound(bind_expr, variable_mappings)
        elif expr_name == 'Builtin_COALESCE':
            # COALESCE(arg1, arg2, ...) -> COALESCE(arg1, arg2, ...)
            if hasattr(bind_expr, 'arg') and isinstance(bind_expr.arg, list):
                args = [translate_bind_arg(arg, variable_mappings) for arg in bind_expr.arg]
                return f"COALESCE({', '.join(args)})"
            else:
                logger.warning(f"COALESCE missing arg list: {bind_expr}")
                return "NULL"
        elif expr_name in ['Builtin_URI', 'Builtin_IRI']:
            # URI(string) -> string (assuming it's already a valid URI)
            arg = translate_bind_arg(bind_expr.arg, variable_mappings)
            return arg
        elif expr_name == 'Builtin_ENCODE_FOR_URI':
            # ENCODE_FOR_URI(string) -> URL encode the string
            arg = translate_bind_arg(bind_expr.arg, variable_mappings)
            # PostgreSQL doesn't have built-in URL encoding, use REPLACE for basic cases
            return f"REPLACE(REPLACE(REPLACE({arg}, ' ', '%20'), '@', '%40'), '#', '%23')"
            
        # STRING FUNCTIONS - Connect existing implementations
        elif expr_name == 'Builtin_SUBSTR':
            # SUBSTR(string, start, length?) -> SUBSTRING(string FROM start FOR length)
            # RDFLib stores SUBSTR args as dict keys: 'arg', 'start', 'length'
            try:
                # Extract arguments from dictionary keys
                if 'arg' in bind_expr and 'start' in bind_expr:
                    string_arg = translate_bind_arg(bind_expr['arg'], variable_mappings)
                    
                    # For numeric literals, extract the raw value without quotes
                    start_val = bind_expr['start']
                    if hasattr(start_val, 'toPython'):
                        start_arg = str(start_val.toPython())
                    else:
                        start_arg = translate_bind_arg(start_val, variable_mappings)
                    
                    if 'length' in bind_expr:
                        length_val = bind_expr['length']
                        if hasattr(length_val, 'toPython'):
                            length_arg = str(length_val.toPython())
                        else:
                            length_arg = translate_bind_arg(length_val, variable_mappings)
                        return f"SUBSTRING({string_arg} FROM {start_arg} FOR {length_arg})"
                    else:
                        return f"SUBSTRING({string_arg} FROM {start_arg})"
                else:
                    logger.warning(f"SUBSTR missing required keys 'arg' or 'start' in {bind_expr.keys()}")
                    return "'SUBSTR_MISSING_KEYS'"
            except Exception as e:
                logger.warning(f"Error parsing SUBSTR expression: {e}")
                return "'SUBSTR_PARSE_ERROR'"
        elif expr_name == 'Builtin_STRLEN':
            # STRLEN(string) -> LENGTH(string)
            arg = translate_bind_arg(bind_expr.arg, variable_mappings)
            return f"LENGTH({arg})"
        elif expr_name == 'Builtin_UCASE':
            # UCASE(string) -> UPPER(string)
            arg = translate_bind_arg(bind_expr.arg, variable_mappings)
            return f"UPPER({arg})"
        elif expr_name == 'Builtin_LCASE':
            # LCASE(string) -> LOWER(string)
            arg = translate_bind_arg(bind_expr.arg, variable_mappings)
            return f"LOWER({arg})"
        elif expr_name == 'Builtin_CONTAINS':
            # CONTAINS(string, substring) -> string LIKE '%substring%'
            if hasattr(bind_expr, 'arg1') and hasattr(bind_expr, 'arg2'):
                string_arg = translate_bind_arg(bind_expr.arg1, variable_mappings)
                substring_arg = translate_bind_arg(bind_expr.arg2, variable_mappings)
                return f"({string_arg} LIKE CONCAT('%', {substring_arg}, '%'))"
            else:
                logger.warning(f"CONTAINS missing arg1/arg2: {bind_expr}")
                return "FALSE"
        elif expr_name == 'Builtin_STRSTARTS':
            # STRSTARTS(string, prefix) -> string LIKE 'prefix%'
            if hasattr(bind_expr, 'arg1') and hasattr(bind_expr, 'arg2'):
                string_arg = translate_bind_arg(bind_expr.arg1, variable_mappings)
                prefix_arg = translate_bind_arg(bind_expr.arg2, variable_mappings)
                return f"({string_arg} LIKE CONCAT({prefix_arg}, '%'))"
            else:
                logger.warning(f"STRSTARTS missing arg1/arg2: {bind_expr}")
                return "FALSE"
        elif expr_name == 'Builtin_STRENDS':
            # STRENDS(string, suffix) -> string LIKE '%suffix'
            if hasattr(bind_expr, 'arg1') and hasattr(bind_expr, 'arg2'):
                string_arg = translate_bind_arg(bind_expr.arg1, variable_mappings)
                suffix_arg = translate_bind_arg(bind_expr.arg2, variable_mappings)
                return f"({string_arg} LIKE CONCAT('%', {suffix_arg}))"
            else:
                logger.warning(f"STRENDS missing arg1/arg2: {bind_expr}")
                return "FALSE"
        elif expr_name == 'Builtin_REPLACE':
            # REPLACE(string, pattern, replacement) -> REPLACE(string, pattern, replacement)
            try:
                if hasattr(bind_expr, 'arg') and isinstance(bind_expr.arg, list) and len(bind_expr.arg) >= 3:
                    string_arg = translate_bind_arg(bind_expr.arg[0], variable_mappings)
                    pattern_arg = translate_bind_arg(bind_expr.arg[1], variable_mappings)
                    replacement_arg = translate_bind_arg(bind_expr.arg[2], variable_mappings)
                    return f"REPLACE({string_arg}, {pattern_arg}, {replacement_arg})"
                else:
                    logger.warning(f"REPLACE: Missing required arguments or incorrect structure")
                    return "''"
            except Exception as e:
                logger.error(f"Error translating REPLACE: {e}")
                return "''"
        elif expr_name == 'Builtin_STRBEFORE':
            # STRBEFORE(string, delimiter) -> SUBSTRING(string, 1, POSITION(delimiter IN string) - 1)
            if hasattr(bind_expr, 'arg1') and hasattr(bind_expr, 'arg2'):
                string_arg = translate_bind_arg(bind_expr.arg1, variable_mappings)
                delimiter_arg = translate_bind_arg(bind_expr.arg2, variable_mappings)
                return f"CASE WHEN POSITION({delimiter_arg} IN {string_arg}) > 0 THEN SUBSTRING({string_arg}, 1, POSITION({delimiter_arg} IN {string_arg}) - 1) ELSE '' END"
            else:
                logger.warning(f"STRBEFORE missing arg1/arg2: {bind_expr}")
                return "''"
        elif expr_name == 'Builtin_STRAFTER':
            # STRAFTER(string, delimiter) -> SUBSTRING(string FROM POSITION(delimiter IN string) + LENGTH(delimiter))
            if hasattr(bind_expr, 'arg1') and hasattr(bind_expr, 'arg2'):
                string_arg = translate_bind_arg(bind_expr.arg1, variable_mappings)
                delimiter_arg = translate_bind_arg(bind_expr.arg2, variable_mappings)
                return f"CASE WHEN POSITION({delimiter_arg} IN {string_arg}) > 0 THEN SUBSTRING({string_arg} FROM POSITION({delimiter_arg} IN {string_arg}) + LENGTH({delimiter_arg})) ELSE '' END"
            else:
                logger.warning(f"STRAFTER missing arg1/arg2: {bind_expr}")
                return "''"
                
        # NUMERIC FUNCTIONS - Connect existing implementations
        elif expr_name == 'Builtin_ABS':
            return _translate_builtin_abs(bind_expr, variable_mappings)
        elif expr_name == 'Builtin_CEIL':
            return _translate_builtin_ceil(bind_expr, variable_mappings)
        elif expr_name == 'Builtin_FLOOR':
            return _translate_builtin_floor(bind_expr, variable_mappings)
        elif expr_name == 'Builtin_ROUND':
            return _translate_builtin_round(bind_expr, variable_mappings)
        elif expr_name == 'Builtin_RAND':
            return _translate_builtin_rand(bind_expr, variable_mappings)
            
        # TYPE CHECKING FUNCTIONS - Connect existing implementations
        elif expr_name == 'Builtin_isURI':
            return _translate_builtin_isuri(bind_expr, variable_mappings)
        elif expr_name == 'Builtin_isLITERAL':
            return _translate_builtin_isliteral(bind_expr, variable_mappings)
        elif expr_name == 'Builtin_isNUMERIC':
            return _translate_builtin_isnumeric(bind_expr, variable_mappings)
        elif expr_name == 'Builtin_isBLANK':
            return _translate_builtin_isblank(bind_expr, variable_mappings)
        elif expr_name == 'Builtin_isIRI':
            return _translate_builtin_isuri(bind_expr, variable_mappings)  # isIRI is alias for isURI
            
        # DATATYPE AND LANG FUNCTIONS - Previously missing
        elif expr_name == 'Builtin_DATATYPE':
            # DATATYPE(?var) -> get datatype URI for the variable
            # Use the proper _translate_builtin_datatype function instead of placeholder
            return _translate_builtin_datatype(bind_expr, variable_mappings, context)
        elif expr_name == 'Builtin_LANG':
            # LANG(?var) -> get language tag for the variable
            if hasattr(bind_expr, 'arg'):
                arg_sql = translate_bind_arg(bind_expr.arg, variable_mappings)
                # For variables, we need to look up the language from the term table
                if '.term_text' in arg_sql:
                    # Replace term_text with lang column
                    lang_sql = arg_sql.replace('.term_text', '.lang')
                    return f"COALESCE({lang_sql}, '')"
                else:
                    # For non-variable values, return empty string
                    return "''"
            return "''"
        elif expr_name == 'Builtin_CONTAINS':
            # CONTAINS(string, substring) -> string LIKE '%substring%'
            if hasattr(bind_expr, 'arg1') and hasattr(bind_expr, 'arg2'):
                string_arg = translate_bind_arg(bind_expr.arg1, variable_mappings)
                substring_arg = translate_bind_arg(bind_expr.arg2, variable_mappings)
                # Remove quotes from literal substring for LIKE pattern
                if substring_arg.startswith("'") and substring_arg.endswith("'"):
                    substring_val = substring_arg[1:-1]
                    return f"({string_arg} LIKE '%{substring_val}%')"
                else:
                    return f"({string_arg} LIKE CONCAT('%', {substring_arg}, '%'))"
            else:
                logger.warning(f"CONTAINS missing arg1/arg2: {bind_expr}")
                return "FALSE"
        elif expr_name == 'Builtin_STRSTARTS':
            # STRSTARTS(string, prefix) -> string LIKE 'prefix%'
            if hasattr(bind_expr, 'arg1') and hasattr(bind_expr, 'arg2'):
                string_arg = translate_bind_arg(bind_expr.arg1, variable_mappings)
                prefix_arg = translate_bind_arg(bind_expr.arg2, variable_mappings)
                # Remove quotes from literal prefix for LIKE pattern
                if prefix_arg.startswith("'") and prefix_arg.endswith("'"):
                    prefix_val = prefix_arg[1:-1]
                    return f"({string_arg} LIKE '{prefix_val}%')"
                else:
                    return f"({string_arg} LIKE CONCAT({prefix_arg}, '%'))"
            else:
                logger.warning(f"STRSTARTS missing arg1/arg2: {bind_expr}")
                return "FALSE"
        elif expr_name == 'Builtin_STRENDS':
            # STRENDS(string, suffix) -> string LIKE '%suffix'
            if hasattr(bind_expr, 'arg1') and hasattr(bind_expr, 'arg2'):
                string_arg = translate_bind_arg(bind_expr.arg1, variable_mappings)
                suffix_arg = translate_bind_arg(bind_expr.arg2, variable_mappings)
                # Remove quotes from literal suffix for LIKE pattern
                if suffix_arg.startswith("'") and suffix_arg.endswith("'"):
                    suffix_val = suffix_arg[1:-1]
                    return f"({string_arg} LIKE '%{suffix_val}')"
                else:
                    return f"({string_arg} LIKE CONCAT('%', {suffix_arg}))"
            else:
                logger.warning(f"STRENDS missing arg1/arg2: {bind_expr}")
                return "FALSE"
        elif expr_name == 'Builtin_STRBEFORE':
            # STRBEFORE(string, delimiter) -> SUBSTRING(string, 1, POSITION(delimiter IN string) - 1)
            if hasattr(bind_expr, 'arg1') and hasattr(bind_expr, 'arg2'):
                string_arg = translate_bind_arg(bind_expr.arg1, variable_mappings)
                delimiter_arg = translate_bind_arg(bind_expr.arg2, variable_mappings)
                return f"CASE WHEN POSITION({delimiter_arg} IN {string_arg}) > 0 THEN SUBSTRING({string_arg}, 1, POSITION({delimiter_arg} IN {string_arg}) - 1) ELSE '' END"
            else:
                logger.warning(f"STRBEFORE missing arg1/arg2: {bind_expr}")
                return "''"
        elif expr_name == 'Builtin_STRAFTER':
            # STRAFTER(string, delimiter) -> SUBSTRING(string FROM POSITION(delimiter IN string) + LENGTH(delimiter))
            if hasattr(bind_expr, 'arg1') and hasattr(bind_expr, 'arg2'):
                string_arg = translate_bind_arg(bind_expr.arg1, variable_mappings)
                delimiter_arg = translate_bind_arg(bind_expr.arg2, variable_mappings)
                return f"CASE WHEN POSITION({delimiter_arg} IN {string_arg}) > 0 THEN SUBSTRING({string_arg} FROM POSITION({delimiter_arg} IN {string_arg}) + LENGTH({delimiter_arg})) ELSE '' END"
            else:
                logger.warning(f"STRAFTER missing arg1/arg2: {bind_expr}")
                return "''"
        elif expr_name == 'Builtin_BNODE':
            # BNODE() -> Generate blank node identifier with proper SPARQL semantics
            # Per SPARQL spec: BNODE() without args should return the same blank node
            # for all calls within a single solution, but distinct across solutions
            # BNODE(expr) should return same blank node for same expr within solution
            if hasattr(bind_expr, 'arg') and bind_expr.arg is not None:
                # BNODE with argument - use argument + solution context for consistency
                arg_sql = translate_bind_arg(bind_expr.arg, variable_mappings)
                # Create solution-scoped blank node using row context
                # Use a combination of the argument and a solution identifier
                return f"('_:' || MD5(CONCAT({arg_sql}::text, COALESCE(ROW_NUMBER() OVER (), 1)::text)))"
            else:
                # BNODE without argument - same blank node per solution, unique across solutions
                # Use ROW_NUMBER() to create a unique identifier per solution/row
                return "('_:' || MD5(CONCAT('__BNODE_NO_ARG__', COALESCE(ROW_NUMBER() OVER (), 1)::text)))"
        elif expr_name == 'Builtin_UUID':
            # UUID() -> Generate unique UUID (always different)
            return "gen_random_uuid()::text"
                
        # LANG/DATATYPE FUNCTIONS - Handle language and datatype functions
        elif expr_name == 'Builtin_LANG':
            # LANG(literal) -> Extract language tag from literal
            return _translate_builtin_lang(bind_expr, variable_mappings)
            
        elif expr_name == 'Builtin_DATATYPE':
            # DATATYPE(literal) -> Return datatype URI
            return _translate_builtin_datatype(bind_expr, variable_mappings, context)
            
        # UNARY EXPRESSIONS - Handle unary operators
        elif expr_name == 'UnaryMinus':
            # Handle unary minus like -?age
            if hasattr(bind_expr, 'expr'):
                operand = translate_bind_expression(bind_expr.expr, variable_mappings, context)
                # Cast to numeric for unary operations - use proper unary minus syntax
                return f"(-CAST({operand} AS DECIMAL))"
            else:
                logger.warning(f"UnaryMinus missing expr: {bind_expr}")
                return "0"
        elif expr_name == 'UnaryPlus':
            # Handle unary plus like +?age
            if hasattr(bind_expr, 'expr'):
                operand = translate_bind_expression(bind_expr.expr, variable_mappings, context)
                # Cast to numeric for unary operations
                return f"(+CAST({operand} AS DECIMAL))"
            else:
                logger.warning(f"UnaryPlus missing expr: {bind_expr}")
                return "0"
                
        # CONDITIONAL EXPRESSIONS - Handle complex logic
        elif expr_name == 'ConditionalOrExpression':
            # Handle OR expressions like BOUND(?email) || BOUND(?phone)
            if hasattr(bind_expr, 'expr') and hasattr(bind_expr, 'other'):
                left = translate_bind_expression(bind_expr.expr, variable_mappings)
                right_exprs = bind_expr.other if isinstance(bind_expr.other, list) else [bind_expr.other]
                conditions = [left]
                for right_expr in right_exprs:
                    conditions.append(translate_bind_expression(right_expr, variable_mappings))
                return f"({' OR '.join(conditions)})"
            else:
                logger.warning(f"ConditionalOrExpression missing expr/other: {bind_expr}")
                return "FALSE"
        elif expr_name == 'ConditionalAndExpression':
            # Handle AND expressions like ISLITERAL(?x) && ISNUMERIC(?x)
            if hasattr(bind_expr, 'expr') and hasattr(bind_expr, 'other'):
                left = translate_bind_expression(bind_expr.expr, variable_mappings)
                right_exprs = bind_expr.other if isinstance(bind_expr.other, list) else [bind_expr.other]
                conditions = [left]
                for right_expr in right_exprs:
                    conditions.append(translate_bind_expression(right_expr, variable_mappings))
                return f"({' AND '.join(conditions)})"
            else:
                logger.warning(f"ConditionalAndExpression missing expr/other: {bind_expr}")
                return "FALSE"
        
        # Handle simple literal expressions
        elif isinstance(bind_expr, str):
            # String literal
            escaped_value = bind_expr.replace("'", "''")
            return f"'{escaped_value}'"
        else:
            # Comprehensive fallback for any missing builtin functions
            # This ensures all builtin functions are handled by the refactored implementation
            if expr_name.startswith('Builtin_'):
                logger.debug(f"Attempting to handle missing builtin function: {expr_name}")
                
                # Try to handle common builtin patterns
                if expr_name in ['Builtin_CONTAINS', 'Builtin_STRSTARTS', 'Builtin_STRENDS', 'Builtin_REPLACE', 
                                'Builtin_STRBEFORE', 'Builtin_STRAFTER', 'Builtin_isIRI', 'Builtin_isBLANK']:
                    # These should have been handled above, but if we reach here, provide a basic implementation
                    logger.warning(f"Builtin function {expr_name} reached fallback - this should not happen")
                    if hasattr(bind_expr, 'arg1') and hasattr(bind_expr, 'arg2'):
                        arg1 = translate_bind_arg(bind_expr.arg1, variable_mappings)
                        arg2 = translate_bind_arg(bind_expr.arg2, variable_mappings)
                        if expr_name == 'Builtin_CONTAINS':
                            return f"({arg1} LIKE CONCAT('%', {arg2}, '%'))"
                        elif expr_name == 'Builtin_STRSTARTS':
                            return f"({arg1} LIKE CONCAT({arg2}, '%'))"
                        elif expr_name == 'Builtin_STRENDS':
                            return f"({arg1} LIKE CONCAT('%', {arg2}))"
                    return "TRUE"  # Safe fallback for boolean functions
                else:
                    # For other builtin functions, try to extract basic argument and return a safe value
                    if hasattr(bind_expr, 'arg'):
                        arg = translate_bind_arg(bind_expr.arg, variable_mappings)
                        return f"'{expr_name}({arg})'"
                    else:
                        return f"'{expr_name}()'"
            else:
                # Fallback for other expression types
                logger.warning(f"Unhandled BIND expression type: {expr_name}")
                logger.warning(f"Expression attributes: {getattr(bind_expr, '__dict__', 'no __dict__')}")
                return "'UNHANDLED_BIND'"
    
    # Handle direct values
    elif isinstance(bind_expr, Literal):
        escaped_value = str(bind_expr).replace("'", "''")
        return f"'{escaped_value}'"
    elif isinstance(bind_expr, URIRef):
        escaped_value = str(bind_expr).replace("'", "''")
        return f"'{escaped_value}'"
    elif isinstance(bind_expr, Variable):
        return translate_bind_arg(bind_expr, variable_mappings)
    elif isinstance(bind_expr, str):
        escaped_value = bind_expr.replace("'", "''")
        return f"'{escaped_value}'"
    elif isinstance(bind_expr, list):
        # CRITICAL FIX: Handle list arguments that can occur in BIND expressions
        # This was the root cause of the BIND arithmetic failure
        logger.debug(f"List in translate_bind_expression: {bind_expr} (length: {len(bind_expr)})")
        if len(bind_expr) == 1:
            # Single element list - unwrap and translate using translate_bind_arg
            return translate_bind_arg(bind_expr[0], variable_mappings)
        elif len(bind_expr) > 1:
            # Multiple elements - translate first element
            return translate_bind_arg(bind_expr[0], variable_mappings)
        else:
            return "NULL"  # Empty list becomes NULL
    else:
        logger.warning(f"Unknown BIND expression type: {type(bind_expr)}")
        logger.warning(f"Expression value: {bind_expr}")
        logger.warning(f"Expression hasattr name: {hasattr(bind_expr, 'name')}")
        if hasattr(bind_expr, 'name'):
            logger.warning(f"Expression name: {bind_expr.name}")
        return "'UNKNOWN_BIND'"


def translate_aggregate_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """
    Translate SPARQL aggregate expression to SQL aggregate function.
    
    Args:
        expr: SPARQL aggregate expression from RDFLib algebra
        variable_mappings: Variable to SQL column mappings
        
    Returns:
        SQL aggregate expression string
    """
    logger.debug(f"Translating aggregate expression: {type(expr).__name__}")
    
    # Handle different aggregate types
    if hasattr(expr, 'name'):
        agg_name = expr.name
        if agg_name == "Aggregate_Count":
            return _translate_count_aggregate(expr, variable_mappings)
        elif agg_name == "Aggregate_Sum":
            return _translate_sum_aggregate(expr, variable_mappings)
        elif agg_name == "Aggregate_Avg":
            return _translate_avg_aggregate(expr, variable_mappings)
        elif agg_name == "Aggregate_Min":
            return _translate_min_aggregate(expr, variable_mappings)
        elif agg_name == "Aggregate_Max":
            return _translate_max_aggregate(expr, variable_mappings)
        elif agg_name == "Aggregate_Sample":
            return _translate_sample_aggregate(expr, variable_mappings)
    
    # Fallback for unknown aggregates
    logger.warning(f"Unknown aggregate expression: {expr}")
    return "COUNT(*)"


def extract_variables_from_expression(expr) -> Set[Variable]:
    """
    Extract all variables used in a SPARQL expression.
    
    Args:
        expr: SPARQL expression from RDFLib algebra
        
    Returns:
        Set of Variable objects found in the expression
    """
    variables = set()
    
    if isinstance(expr, Variable):
        variables.add(expr)
    elif isinstance(expr, list):
        for item in expr:
            variables.update(extract_variables_from_expression(item))
    elif hasattr(expr, 'expr'):
        variables.update(extract_variables_from_expression(expr.expr))
    elif hasattr(expr, 'left') and hasattr(expr, 'right'):
        variables.update(extract_variables_from_expression(expr.left))
        variables.update(extract_variables_from_expression(expr.right))
    
    if hasattr(expr, 'args'):
        for arg in expr.args:
            variables.update(extract_variables_from_expression(arg))
    
    return variables


# Helper functions for simple built-in expressions
def _translate_regex_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate REGEX() function to PostgreSQL regex operator with error handling."""
    text_expr = expr['text']
    pattern_expr = expr['pattern']
    
    text_sql = _translate_expression_operand_sync(text_expr, variable_mappings)
    pattern_sql = _translate_expression_operand_sync(pattern_expr, variable_mappings)
    
    # Check if pattern is a literal string that we can validate
    if hasattr(pattern_expr, 'toPython') and hasattr(pattern_expr, 'datatype'):
        try:
            # Extract literal pattern value
            pattern_value = str(pattern_expr.toPython())
            if not _validate_regex_pattern(pattern_value):
                logger.warning(f"Invalid regex pattern detected: {pattern_value}")
                return "FALSE"  # Return FALSE for invalid patterns
        except Exception as e:
            logger.debug(f"Could not validate regex pattern: {e}")
    
    # For valid patterns or variable patterns, use a safer approach
    # Use PostgreSQL's position() function as fallback for problematic patterns
    return f"""(
        CASE 
            WHEN {pattern_sql} IS NULL OR {pattern_sql} = '' THEN FALSE
            WHEN {text_sql} IS NULL THEN FALSE
            ELSE (
                COALESCE(
                    (SELECT {text_sql} ~ {pattern_sql}),
                    FALSE
                )
            )
        END
    )"""


def _validate_regex_pattern(pattern: str) -> bool:
    """Validate a regex pattern to prevent SQL errors."""
    import re
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False


def _translate_contains_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate CONTAINS() function to SQL LIKE."""
    text_expr = expr['arg1']
    search_expr = expr['arg2']
    
    text_sql = _translate_expression_operand_sync(text_expr, variable_mappings)
    search_sql = _translate_expression_operand_sync(search_expr, variable_mappings)
    
    # Remove quotes from search term and wrap with %
    search_term = search_sql.strip("'")
    return f"{text_sql} LIKE '%{search_term}%'"


def _translate_strstarts_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate STRSTARTS() function to SQL LIKE."""
    text_expr = expr['arg1']
    prefix_expr = expr['arg2']
    
    text_sql = _translate_expression_operand_sync(text_expr, variable_mappings)
    prefix_sql = _translate_expression_operand_sync(prefix_expr, variable_mappings)
    
    # Use LIKE with % wildcard for prefix matching - leverages text indexes
    return f"({text_sql} LIKE {prefix_sql} || '%')"


def _translate_strends_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate STRENDS() function to SQL LIKE."""
    text_expr = expr['arg1']
    suffix_expr = expr['arg2']
    
    text_sql = _translate_expression_operand_sync(text_expr, variable_mappings)
    suffix_sql = _translate_expression_operand_sync(suffix_expr, variable_mappings)
    
    # Use LIKE with % wildcard for suffix matching - leverages text indexes
    return f"({text_sql} LIKE '%' || {suffix_sql})"


# EXISTS/NOT EXISTS expression translators
async def _translate_exists_expression(expr, variable_mappings: Dict[Variable, str], is_not_exists: bool = False) -> str:
    """Translate EXISTS() or NOT EXISTS() function expressions."""
    logger.debug(f"Translating {'NOT EXISTS' if is_not_exists else 'EXISTS'} expression")
    # TODO: Implement EXISTS/NOT EXISTS translation
    return "1=1" if not is_not_exists else "1=0"


# LANG/DATATYPE filter expression translators
def _translate_lang_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate LANG() filter expression."""
    logger.debug("Translating LANG filter expression")
    if hasattr(expr, 'arg'):
        arg_sql = _translate_expression_operand_sync(expr.arg, variable_mappings)
        
        # For variables, we need to get the language tag from the term table
        # The arg_sql should reference a term table column like 'o_term_1.term_text'
        # We need to convert this to get the lang column
        if '.term_text' in arg_sql:
            # Replace term_text with lang to get the language tag
            lang_sql = arg_sql.replace('.term_text', '.lang')
            # Return COALESCE to convert NULL to empty string for SPARQL compliance
            return f"COALESCE({lang_sql}, '')"
        else:
            # For literal values in the query, we can't determine language at SQL level
            # Return empty string as literals in SPARQL queries don't have language info
            return "''"
    return "''"


def _translate_datatype_filter_expression(expr, variable_mappings: Dict[Variable, str], context=None) -> str:
    """Translate DATATYPE() filter expression using the datatype table."""
    logger.debug("Translating DATATYPE filter expression")
    if hasattr(expr, 'arg'):
        arg_sql = _translate_expression_operand_sync(expr.arg, variable_mappings)
        logger.debug(f"DATATYPE filter arg_sql: {arg_sql}")
        
        # For variables, get the datatype URI from the datatype table
        if '.term_text' in arg_sql:
            # Extract the table alias from the arg_sql (e.g., 'o_term_1' from 'o_term_1.term_text')
            table_alias = arg_sql.split('.')[0]
            logger.debug(f"DATATYPE filter table_alias: {table_alias}")
            
            # Get the datatype table name from context
            datatype_table = None
            if context and context.space_impl and context.space_id:
                # Get all table names using the proper method with the actual space_id
                table_names = context.space_impl._get_table_names(context.space_id)
                datatype_table = table_names.get('datatype')
                logger.debug(f"DATATYPE filter using space_id: {context.space_id}, datatype_table: {datatype_table}")
            
            if datatype_table:
                # Use the datatype table to resolve datatype URIs
                datatype_sql = f"""(
                    CASE 
                        WHEN {table_alias}.datatype_id IS NOT NULL THEN (
                            SELECT dt.datatype_uri 
                            FROM {datatype_table} dt 
                            WHERE dt.datatype_id = {table_alias}.datatype_id
                        )
                        WHEN {table_alias}.term_type = 'L' THEN 'http://www.w3.org/2001/XMLSchema#string'
                        WHEN {table_alias}.term_type = 'U' THEN NULL
                        WHEN {table_alias}.term_type = 'B' THEN NULL
                        ELSE 'http://www.w3.org/2001/XMLSchema#string'
                    END
                )"""
            else:
                # Fallback to regex-based datatype inference
                logger.debug("DATATYPE filter: falling back to regex-based datatype inference")
                datatype_sql = f"""(
                    CASE 
                        WHEN {table_alias}.term_type = 'L' AND {table_alias}.term_text ~ '^[+-]?[0-9]+$' THEN 'http://www.w3.org/2001/XMLSchema#integer'
                        WHEN {table_alias}.term_type = 'L' AND {table_alias}.term_text ~ '^[+-]?[0-9]*\\.[0-9]+$' THEN 'http://www.w3.org/2001/XMLSchema#decimal'
                        WHEN {table_alias}.term_type = 'L' AND {table_alias}.term_text ~ '^[+-]?[0-9]*\\.?[0-9]+([eE][+-]?[0-9]+)?$' THEN 'http://www.w3.org/2001/XMLSchema#double'
                        WHEN {table_alias}.term_type = 'L' AND LOWER({table_alias}.term_text) IN ('true', 'false') THEN 'http://www.w3.org/2001/XMLSchema#boolean'
                        WHEN {table_alias}.term_type = 'L' THEN 'http://www.w3.org/2001/XMLSchema#string'
                        WHEN {table_alias}.term_type = 'U' THEN NULL
                        WHEN {table_alias}.term_type = 'B' THEN NULL
                        ELSE 'http://www.w3.org/2001/XMLSchema#string'
                    END
                )"""
            
            logger.debug(f"DATATYPE filter generated SQL: {datatype_sql}")
            return datatype_sql
        else:
            # For literal values in the query, return xsd:string as default
            logger.debug("DATATYPE filter: returning default xsd:string for literal")
            return "'http://www.w3.org/2001/XMLSchema#string'"
    logger.debug("DATATYPE filter: returning default xsd:string (no arg)")
    return "'http://www.w3.org/2001/XMLSchema#string'"


# URI/BNODE filter expression translators
def _translate_uri_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate URI()/IRI() filter expression."""
    logger.debug("Translating URI/IRI filter expression")
    return "1=1"  # Placeholder


def _translate_bnode_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate BNODE() filter expression."""
    logger.debug("Translating BNODE filter expression")
    return "1=1"  # Placeholder


# Type checking filter expression translators
def _translate_isuri_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate isURI() filter expression."""
    logger.debug("Translating isURI filter expression")
    if hasattr(expr, 'arg'):
        # Get the variable being tested
        arg = expr.arg
        if isinstance(arg, Variable) and arg in variable_mappings:
            # Get the term column for this variable
            term_column = variable_mappings[arg]
            # Check if the value looks like a URI using regex pattern matching
            # This matches common URI schemes without database lookups
            uri_pattern = "'^(https?|ftp|file|mailto|urn|ldap|news|gopher|telnet):[^\\s]*$'"
            return f"({term_column} ~ {uri_pattern})"
        else:
            logger.warning(f"isURI argument not found in variable mappings: {arg}")
            return "FALSE"
    return "FALSE"


def _translate_isliteral_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate isLITERAL() filter expression."""
    logger.debug("Translating isLITERAL filter expression")
    if hasattr(expr, 'arg'):
        # Get the variable being tested
        arg = expr.arg
        if isinstance(arg, Variable) and arg in variable_mappings:
            # Get the term column for this variable
            term_column = variable_mappings[arg]
            # Check if the value is NOT a URI (inverse of isURI check)
            # A literal is anything that doesn't match URI patterns
            uri_pattern = "'^(https?|ftp|file|mailto|urn|ldap|news|gopher|telnet):[^\\s]*$'"
            return f"NOT ({term_column} ~ {uri_pattern})"
        else:
            logger.warning(f"isLITERAL argument not found in variable mappings: {arg}")
            return "FALSE"
    return "FALSE"


def _translate_isblank_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate isBLANK() filter expression."""
    logger.debug("Translating isBLANK filter expression")
    if hasattr(expr, 'arg'):
        arg_sql = _translate_expression_operand_sync(expr.arg, variable_mappings)
        # Check if the term looks like a blank node (starts with _:)
        return f"({arg_sql} LIKE '_:%')"
    return "FALSE"


def _translate_isnumeric_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate isNUMERIC() filter expression."""
    logger.debug("Translating isNUMERIC filter expression")
    if hasattr(expr, 'arg'):
        # Get the variable being tested
        arg = expr.arg
        if isinstance(arg, Variable) and arg in variable_mappings:
            # Get the term column for this variable
            term_column = variable_mappings[arg]
            # Check if the value is numeric using PostgreSQL's improved regex pattern
            # This pattern matches integers, decimals, and scientific notation
            numeric_pattern = "'^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$'"
            return f"({term_column} ~ {numeric_pattern})"
        else:
            logger.warning(f"isNUMERIC argument not found in variable mappings: {arg}")
            return "FALSE"
    return "FALSE"


def _translate_bound_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate BOUND() filter expression."""
    logger.debug("Translating BOUND filter expression")
    if hasattr(expr, 'arg') and isinstance(expr.arg, Variable):
        var_sql = _get_variable_sql_column(expr.arg, variable_mappings)
        return f"({var_sql} IS NOT NULL)"
    return "1=0"


def _translate_sameterm_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate sameTerm() filter expression."""
    logger.debug("Translating sameTerm filter expression")
    if hasattr(expr, 'arg1') and hasattr(expr, 'arg2'):
        arg1_sql = _translate_expression_operand_sync(expr.arg1, variable_mappings)
        arg2_sql = _translate_expression_operand_sync(expr.arg2, variable_mappings)
        return f"({arg1_sql} = {arg2_sql})"
    return "1=0"


# Math built-in function translators
def _translate_builtin_ceil(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate CEIL() built-in to SQL CEIL()."""
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    arg = None
    if hasattr(expr, 'arg') and expr.arg is not None:
        arg = expr.arg
    elif hasattr(expr, 'args') and len(expr.args) >= 1:
        arg = expr.args[0]
    
    if arg is not None:
        value_sql = translate_bind_arg(arg, variable_mappings)
        return f"CEIL({value_sql})"
    return "0"


def _translate_builtin_floor(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate FLOOR() built-in to SQL FLOOR()."""
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    arg = None
    if hasattr(expr, 'arg') and expr.arg is not None:
        arg = expr.arg
    elif hasattr(expr, 'args') and len(expr.args) >= 1:
        arg = expr.args[0]
    
    if arg is not None:
        value_sql = translate_bind_arg(arg, variable_mappings)
        return f"FLOOR({value_sql})"
    return "0"


def _translate_builtin_replace(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate REPLACE() built-in to string replacement."""
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    args = []
    if hasattr(expr, 'arg') and expr.arg is not None:
        args = [expr.arg]
    elif hasattr(expr, 'args') and expr.args:
        args = expr.args
    
    if len(args) >= 3:
        string_sql = translate_bind_arg(args[0], variable_mappings)
        pattern_sql = translate_bind_arg(args[1], variable_mappings)
        replacement_sql = translate_bind_arg(args[2], variable_mappings)
        return f"REPLACE({string_sql}, {pattern_sql}, {replacement_sql})"
    else:
        logger.warning("REPLACE: Missing required arguments")
        return "''"


def _translate_builtin_contains(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate CONTAINS() built-in to string containment check."""
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    args = []
    if hasattr(expr, 'arg') and expr.arg is not None:
        args = [expr.arg]
    elif hasattr(expr, 'args') and expr.args:
        args = expr.args
    
    if len(args) >= 2:
        string_sql = translate_bind_arg(args[0], variable_mappings)
        substring_sql = translate_bind_arg(args[1], variable_mappings)
        return f"({string_sql} LIKE '%' || {substring_sql} || '%')"
    return "FALSE"


def _translate_builtin_strstarts(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate STRSTARTS() built-in to string prefix check."""
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    args = []
    if hasattr(expr, 'arg') and expr.arg is not None:
        args = [expr.arg]
    elif hasattr(expr, 'args') and expr.args:
        args = expr.args
    
    if len(args) >= 2:
        string_sql = translate_bind_arg(args[0], variable_mappings)
        prefix_sql = translate_bind_arg(args[1], variable_mappings)
        return f"({string_sql} LIKE {prefix_sql} || '%')"
    return "FALSE"


def _translate_builtin_strends(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate STRENDS() built-in to string suffix check."""
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    args = []
    if hasattr(expr, 'arg') and expr.arg is not None:
        args = [expr.arg]
    elif hasattr(expr, 'args') and expr.args:
        args = expr.args
    
    if len(args) >= 2:
        string_sql = translate_bind_arg(args[0], variable_mappings)
        suffix_sql = translate_bind_arg(args[1], variable_mappings)
        return f"({string_sql} LIKE '%' || {suffix_sql})"
    return "FALSE"


def _translate_builtin_strbefore(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate STRBEFORE() built-in to substring before delimiter."""
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    args = []
    if hasattr(expr, 'arg') and expr.arg is not None:
        args = [expr.arg]
    elif hasattr(expr, 'args') and expr.args:
        args = expr.args
    
    if len(args) >= 2:
        string_sql = translate_bind_arg(args[0], variable_mappings)
        delimiter_sql = translate_bind_arg(args[1], variable_mappings)
        return f"SUBSTRING({string_sql} FROM 1 FOR POSITION({delimiter_sql} IN {string_sql}) - 1)"
    return "''"


def _translate_builtin_strafter(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate STRAFTER() built-in to substring after delimiter."""
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    args = []
    if hasattr(expr, 'arg') and expr.arg is not None:
        args = [expr.arg]
    elif hasattr(expr, 'args') and expr.args:
        args = expr.args
    
    if len(args) >= 2:
        string_sql = translate_bind_arg(args[0], variable_mappings)
        delimiter_sql = translate_bind_arg(args[1], variable_mappings)
        return f"SUBSTRING({string_sql} FROM POSITION({delimiter_sql} IN {string_sql}) + LENGTH({delimiter_sql}))"
    return "''"


# Date/Time built-in function translators
def _translate_builtin_now(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate NOW() built-in to SQL NOW()."""
    return "NOW()"


def _translate_builtin_year(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate YEAR() built-in to SQL EXTRACT(YEAR FROM ...)."""
    if hasattr(expr, 'args') and len(expr.args) >= 1:
        date_sql = _translate_expression_operand_sync(expr.args[0], variable_mappings)
        return f"EXTRACT(YEAR FROM {date_sql})"
    return "0"


def _translate_builtin_month(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate MONTH() built-in to SQL EXTRACT(MONTH FROM ...)."""
    if hasattr(expr, 'args') and len(expr.args) >= 1:
        date_sql = _translate_expression_operand_sync(expr.args[0], variable_mappings)
        return f"EXTRACT(MONTH FROM {date_sql})"
    return "0"


def _translate_builtin_day(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate DAY() built-in to SQL EXTRACT(DAY FROM ...)."""
    if hasattr(expr, 'args') and len(expr.args) >= 1:
        date_sql = _translate_expression_operand_sync(expr.args[0], variable_mappings)
        return f"EXTRACT(DAY FROM {date_sql})"
    return "0"


def _translate_builtin_hours(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate HOURS() built-in to SQL EXTRACT(HOUR FROM ...)."""
    if hasattr(expr, 'args') and len(expr.args) >= 1:
        time_sql = _translate_expression_operand_sync(expr.args[0], variable_mappings)
        return f"EXTRACT(HOUR FROM {time_sql})"
    return "0"


def _translate_builtin_minutes(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate MINUTES() built-in to SQL EXTRACT(MINUTE FROM ...)."""
    if hasattr(expr, 'args') and len(expr.args) >= 1:
        time_sql = _translate_expression_operand_sync(expr.args[0], variable_mappings)
        return f"EXTRACT(MINUTE FROM {time_sql})"
    return "0"


def _translate_builtin_seconds(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate SECONDS() built-in to SQL EXTRACT(SECOND FROM ...)."""
    if hasattr(expr, 'args') and len(expr.args) >= 1:
        time_sql = _translate_expression_operand_sync(expr.args[0], variable_mappings)
        return f"EXTRACT(SECOND FROM {time_sql})"
    return "0"


# Type/Casting built-in function translators
def _translate_builtin_datatype(expr, variable_mappings: Dict[Variable, str], context=None) -> str:
    """Translate DATATYPE() built-in function using the datatype table."""
    logger.debug("Translating DATATYPE builtin function")
    if hasattr(expr, 'arg'):
        arg_sql = _translate_expression_operand_sync(expr.arg, variable_mappings)
        logger.debug(f"DATATYPE builtin arg_sql: {arg_sql}")
        
        # For variables, get the datatype URI from the datatype table
        if '.term_text' in arg_sql:
            # Extract the table alias from the arg_sql (e.g., 'o_term_1' from 'o_term_1.term_text')
            table_alias = arg_sql.split('.')[0]
            logger.debug(f"DATATYPE builtin table_alias: {table_alias}")
            
            # Get the datatype table name from context
            datatype_table = None
            if context and context.space_impl and context.space_id:
                # Get all table names using the proper method with the actual space_id
                table_names = context.space_impl._get_table_names(context.space_id)
                datatype_table = table_names.get('datatype')
                logger.debug(f"DATATYPE builtin using space_id: {context.space_id}, datatype_table: {datatype_table}")
            
            if datatype_table:
                # Use the datatype table to resolve datatype URIs
                datatype_sql = f"""(
                    CASE 
                        WHEN {table_alias}.datatype_id IS NOT NULL THEN (
                            SELECT dt.datatype_uri 
                            FROM {datatype_table} dt 
                            WHERE dt.datatype_id = {table_alias}.datatype_id
                        )
                        WHEN {table_alias}.term_type = 'L' THEN 'http://www.w3.org/2001/XMLSchema#string'
                        WHEN {table_alias}.term_type = 'U' THEN NULL
                        WHEN {table_alias}.term_type = 'B' THEN NULL
                        ELSE 'http://www.w3.org/2001/XMLSchema#string'
                    END
                )"""
            else:
                # Fallback to regex-based datatype inference
                logger.debug("DATATYPE builtin: falling back to regex-based datatype inference")
                datatype_sql = f"""(
                    CASE 
                        WHEN {table_alias}.term_type = 'L' AND {table_alias}.term_text ~ '^[+-]?[0-9]+$' THEN 'http://www.w3.org/2001/XMLSchema#integer'
                        WHEN {table_alias}.term_type = 'L' AND {table_alias}.term_text ~ '^[+-]?[0-9]*\\.[0-9]+$' THEN 'http://www.w3.org/2001/XMLSchema#decimal'
                        WHEN {table_alias}.term_type = 'L' AND {table_alias}.term_text ~ '^[+-]?[0-9]*\\.?[0-9]+([eE][+-]?[0-9]+)?$' THEN 'http://www.w3.org/2001/XMLSchema#double'
                        WHEN {table_alias}.term_type = 'L' AND LOWER({table_alias}.term_text) IN ('true', 'false') THEN 'http://www.w3.org/2001/XMLSchema#boolean'
                        WHEN {table_alias}.term_type = 'L' THEN 'http://www.w3.org/2001/XMLSchema#string'
                        WHEN {table_alias}.term_type = 'U' THEN NULL
                        WHEN {table_alias}.term_type = 'B' THEN NULL
                        ELSE 'http://www.w3.org/2001/XMLSchema#string'
                    END
                )"""
            
            logger.debug(f"DATATYPE builtin generated SQL: {datatype_sql}")
            return datatype_sql
        else:
            # For literal values in the query, return xsd:string as default
            logger.debug("DATATYPE builtin: returning default xsd:string for literal")
            return "'http://www.w3.org/2001/XMLSchema#string'"
    logger.debug("DATATYPE builtin: returning default xsd:string (no arg)")
    return "'http://www.w3.org/2001/XMLSchema#string'"


def _translate_builtin_lang(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate LANG() built-in - returns language tag of literal."""
    if hasattr(expr, 'arg'):
        # Handle both single argument and list of arguments
        if isinstance(expr.arg, list) and len(expr.arg) >= 1:
            arg_sql = translate_bind_arg(expr.arg[0], variable_mappings)
        else:
            # Single argument (most common case)
            arg_sql = translate_bind_arg(expr.arg, variable_mappings)
        
        # For variables, get the language tag from the term table
        if '.term_text' in arg_sql:
            # Replace term_text with lang to get the language tag
            lang_sql = arg_sql.replace('.term_text', '.lang')
            # Return COALESCE to convert NULL to empty string for SPARQL compliance
            return f"COALESCE({lang_sql}, '')"
        else:
            # For literal values, return empty string
            return "''"
    elif hasattr(expr, 'args') and len(expr.args) >= 1:
        # Fallback for args format
        arg_sql = translate_bind_arg(expr.args[0], variable_mappings)
        if '.term_text' in arg_sql:
            lang_sql = arg_sql.replace('.term_text', '.lang')
            return f"COALESCE({lang_sql}, '')"
        else:
            return "''"
    return "''"


def _translate_builtin_str(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate STR() built-in to string conversion."""
    if hasattr(expr, 'args') and len(expr.args) >= 1:
        value_sql = _translate_expression_operand_sync(expr.args[0], variable_mappings)
        return f"CAST({value_sql} AS TEXT)"
    return "''"


def _translate_builtin_langmatches(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate LANGMATCHES() built-in for language tag matching."""
    if hasattr(expr, 'args') and len(expr.args) >= 2:
        lang_sql = _translate_expression_operand_sync(expr.args[0], variable_mappings)
        pattern_sql = _translate_expression_operand_sync(expr.args[1], variable_mappings)
        # Simplified language matching
        return f"({lang_sql} LIKE {pattern_sql})"
    return "1=0"


def _translate_builtin_bound(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate BOUND() built-in to check if variable is bound."""
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    arg = None
    if hasattr(expr, 'arg') and expr.arg is not None:
        arg = expr.arg
    elif hasattr(expr, 'args') and len(expr.args) >= 1:
        arg = expr.args[0]
    
    if arg is not None and isinstance(arg, Variable):
        var_sql = _get_variable_sql_column(arg, variable_mappings)
        return f"({var_sql} IS NOT NULL)"
    return "FALSE"


def _translate_builtin_isuri(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate isURI() built-in to check if term is a URI."""
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    arg = None
    if hasattr(expr, 'arg') and expr.arg is not None:
        arg = expr.arg
    elif hasattr(expr, 'args') and len(expr.args) >= 1:
        arg = expr.args[0]
    
    if arg is not None:
        arg_sql = translate_bind_arg(arg, variable_mappings)
        # Check if the value looks like a URI using SQL pattern matching
        return f"CASE WHEN ({arg_sql} ~ '^(https?|ftp|urn):') THEN TRUE ELSE FALSE END"
    return "FALSE"


def _translate_builtin_isliteral(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate isLITERAL() built-in to check if term is a literal."""
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    arg = None
    if hasattr(expr, 'arg') and expr.arg is not None:
        arg = expr.arg
    elif hasattr(expr, 'args') and len(expr.args) >= 1:
        arg = expr.args[0]
    
    if arg is not None:
        arg_sql = translate_bind_arg(arg, variable_mappings)
        # Check if the value is NOT a URI (inverse of isURI check)
        return f"CASE WHEN NOT ({arg_sql} ~ '^(https?|ftp|urn):') THEN TRUE ELSE FALSE END"
    return "FALSE"


def _translate_builtin_isblank(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate isBLANK() built-in to check if term is a blank node."""
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    arg = None
    if hasattr(expr, 'arg') and expr.arg is not None:
        arg = expr.arg
    elif hasattr(expr, 'args') and len(expr.args) >= 1:
        arg = expr.args[0]
    
    if arg is not None:
        arg_sql = translate_bind_arg(arg, variable_mappings)
        # Check if the term looks like a blank node (starts with _:)
        return f"({arg_sql} LIKE '_:%')"
    return "FALSE"


def _translate_builtin_bnode(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate BNODE() built-in to generate blank node identifiers with proper SPARQL semantics.
    
    Per SPARQL spec:
    - BNODE() without args: same blank node for all calls within a single solution
    - BNODE(expr) with args: same blank node for same expr within solution, different across solutions
    """
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    arg = None
    if hasattr(expr, 'arg') and expr.arg is not None:
        arg = expr.arg
    elif hasattr(expr, 'args') and len(expr.args) >= 1:
        arg = expr.args[0]
    
    if arg is not None:
        # BNODE with argument - use argument + solution context for consistency
        arg_sql = translate_bind_arg(arg, variable_mappings)
        # Create solution-scoped blank node using row context
        return f"('_:' || MD5(CONCAT({arg_sql}::text, COALESCE(ROW_NUMBER() OVER (), 1)::text)))"
    else:
        # BNODE without argument - same blank node per solution, unique across solutions
        return "('_:' || MD5(CONCAT('__BNODE_NO_ARG__', COALESCE(ROW_NUMBER() OVER (), 1)::text)))"


def _translate_builtin_uuid(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate UUID() built-in to generate unique UUID."""
    return "gen_random_uuid()::text"


# String manipulation function translators
def _translate_concat_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate CONCAT() function expressions."""
    logger.debug("Translating CONCAT expression")
    if hasattr(expr, 'args'):
        arg_sqls = []
        for arg in expr.args:
            arg_sql = _translate_expression_operand_sync(arg, variable_mappings)
            arg_sqls.append(arg_sql)
        return f"CONCAT({', '.join(arg_sqls)})"
    return "''"


def _translate_str_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate STR() function expressions."""
    logger.debug("Translating STR expression")
    if hasattr(expr, 'arg'):
        arg_sql = _translate_expression_operand_sync(expr.arg, variable_mappings)
        return f"CAST({arg_sql} AS TEXT)"
    return "''"


def _translate_ucase_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate UCASE() function expressions."""
    logger.debug("Translating UCASE expression")
    if hasattr(expr, 'arg'):
        arg_sql = _translate_expression_operand_sync(expr.arg, variable_mappings)
        return f"UPPER({arg_sql})"
    return "''"


def _translate_lcase_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate LCASE() function expressions."""
    logger.debug("Translating LCASE expression")
    if hasattr(expr, 'arg'):
        arg_sql = _translate_expression_operand_sync(expr.arg, variable_mappings)
        return f"LOWER({arg_sql})"
    return "''"


def _translate_lang_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate LANG() function expressions."""
    logger.debug("Translating LANG expression")
    if hasattr(expr, 'arg'):
        # LANG() returns the language tag of a literal
        arg_sql = _translate_expression_operand_sync(expr.arg, variable_mappings)
        # Replace .term_text with .lang to get language tag
        lang_sql = arg_sql.replace('.term_text', '.lang')
        return f"COALESCE({lang_sql}, '')"
    return "''"


def _translate_datatype_expression(expr, variable_mappings: Dict[Variable, str], context=None) -> str:
    """Translate DATATYPE() function expressions."""
    logger.debug("Translating DATATYPE expression")
    if hasattr(expr, 'arg'):
        # DATATYPE() returns the datatype URI of a literal
        # Need to resolve datatype_id to actual datatype URI
        if context and context.table_config:
            term_table = context.table_config.term_table
        else:
            # Fallback - this shouldn't happen but provides safety
            term_table = 'term_table'
        return f"CASE WHEN datatype_id IS NOT NULL THEN (SELECT term_text FROM {term_table} WHERE term_uuid = datatype_id) ELSE '{XSD.string}' END"
    return f"'{XSD.string}'"


# Helper functions for aggregate expressions
def _translate_count_aggregate(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate COUNT aggregate expressions."""
    logger.debug("Translating COUNT aggregate")
    
    if hasattr(expr, 'vars') and expr.vars:
        # COUNT(?var)
        var = expr.vars[0]
        if var in variable_mappings:
            var_sql = variable_mappings[var]
            if hasattr(expr, 'distinct') and expr.distinct:
                return f"COUNT(DISTINCT {var_sql})"
            else:
                return f"COUNT({var_sql})"
    
    # COUNT(*)
    return "COUNT(*)"


def _translate_sum_aggregate(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate SUM aggregate expressions."""
    logger.debug("Translating SUM aggregate")
    
    if hasattr(expr, 'vars') and expr.vars:
        var = expr.vars[0]
        if var in variable_mappings:
            var_sql = variable_mappings[var]
            return f"SUM(CAST({var_sql} AS DECIMAL))"
    
    return "SUM(0)"


def _translate_avg_aggregate(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate AVG aggregate expressions."""
    logger.debug("Translating AVG aggregate")
    
    if hasattr(expr, 'vars') and expr.vars:
        var = expr.vars[0]
        if var in variable_mappings:
            var_sql = variable_mappings[var]
            return f"AVG(CAST({var_sql} AS DECIMAL))"
    
    return "AVG(0)"


def _translate_min_aggregate(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate MIN aggregate expressions."""
    logger.debug("Translating MIN aggregate")
    
    if hasattr(expr, 'vars') and expr.vars:
        var = expr.vars[0]
        if var in variable_mappings:
            var_sql = variable_mappings[var]
            return f"MIN({var_sql})"
    
    return "MIN('')"


def _translate_max_aggregate(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate MAX aggregate expressions."""
    logger.debug("Translating MAX aggregate")
    
    if hasattr(expr, 'vars') and expr.vars:
        var = expr.vars[0]
        if var in variable_mappings:
            var_sql = variable_mappings[var]
            return f"MAX({var_sql})"
    
    return "MAX('')"


def _translate_sample_aggregate(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate SAMPLE aggregate expressions."""
    logger.debug("Translating SAMPLE aggregate")
    
    if hasattr(expr, 'vars') and expr.vars:
        var = expr.vars[0]
        if var in variable_mappings:
            var_sql = variable_mappings[var]
            # Use PostgreSQL's FIRST_VALUE or MIN as approximation
            return f"MIN({var_sql})"
    
    return "MIN('')"


# Additional aggregate function translators from broken version
def _translate_aggregate_count(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate COUNT aggregate to SQL COUNT()."""
    if hasattr(expr, 'vars') and expr.vars:
        # COUNT(?var)
        var_sql = _get_variable_sql_column(expr.vars[0], variable_mappings)
        return f"COUNT({var_sql})"
    else:
        # COUNT(*)
        return "COUNT(*)"


def _translate_aggregate_sum(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate SUM aggregate to SQL SUM()."""
    if hasattr(expr, 'vars') and expr.vars:
        var_sql = _get_variable_sql_column(expr.vars[0], variable_mappings)
        return f"SUM({var_sql})"
    return "SUM(1)"


def _translate_aggregate_avg(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate AVG aggregate to SQL AVG()."""
    if hasattr(expr, 'vars') and expr.vars:
        var_sql = _get_variable_sql_column(expr.vars[0], variable_mappings)
        return f"AVG({var_sql})"
    return "AVG(1)"


def _translate_aggregate_min(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate MIN aggregate to SQL MIN()."""
    if hasattr(expr, 'vars') and expr.vars:
        var_sql = _get_variable_sql_column(expr.vars[0], variable_mappings)
        return f"MIN({var_sql})"
    return "MIN(1)"


def _translate_aggregate_max(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate MAX aggregate to SQL MAX()."""
    if hasattr(expr, 'vars') and expr.vars:
        var_sql = _get_variable_sql_column(expr.vars[0], variable_mappings)
        return f"MAX({var_sql})"
    return "MAX(1)"


def _translate_aggregate_group_concat(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate GROUP_CONCAT aggregate to SQL STRING_AGG()."""
    if hasattr(expr, 'vars') and expr.vars:
        var_sql = _get_variable_sql_column(expr.vars[0], variable_mappings)
        separator = "', '"  # Default separator
        
        # Check for custom separator
        if hasattr(expr, 'separator'):
            separator = f"'{expr.separator}'"
        
        return f"STRING_AGG({var_sql}, {separator})"
    return "STRING_AGG('', ', ')"


def _translate_aggregate_sample(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate SAMPLE aggregate to SQL - returns any value."""
    if hasattr(expr, 'vars') and expr.vars:
        var_sql = _get_variable_sql_column(expr.vars[0], variable_mappings)
        # Use PostgreSQL's ANY_VALUE equivalent or MIN as fallback
        return f"MIN({var_sql})"
    return "MIN(1)"


# Private helper functions
def _get_variable_sql_column(variable: Variable, variable_mappings: Dict[Variable, str]) -> str:
    """
    Get SQL column reference for a variable.
    
    Args:
        variable: RDFLib Variable
        variable_mappings: Variable to SQL column mappings
        
    Returns:
        SQL column reference
    """
    if variable in variable_mappings:
        return variable_mappings[variable]
    else:
        logger.warning(f"Variable {variable} not found in mappings")
        return f"'{str(variable)}'"  # Fallback to literal


def is_having_clause(filter_sql: str, variable_mappings: Dict) -> bool:
    """Detect if a filter condition should be a HAVING clause instead of WHERE.
    
    HAVING clauses contain aggregate functions or reference aggregate result variables.
    Aggregate result variables are internal variables like __agg_1__, __agg_2__, etc.
    
    Args:
        filter_sql: SQL filter expression
        variable_mappings: Variable to SQL column mappings
        
    Returns:
        True if this should be a HAVING clause, False for WHERE clause
    """
    # Check if the filter SQL contains aggregate functions directly
    aggregate_functions = ['COUNT(', 'SUM(', 'AVG(', 'MIN(', 'MAX(']
    if any(func in filter_sql for func in aggregate_functions):
        logger.debug(f"Filter contains aggregate function: {filter_sql}")
        return True
    
    # Check if the filter references aggregate result variables (__agg_1__, __agg_2__, etc.)
    # These variables are mapped to aggregate SQL expressions in variable_mappings
    for var, mapping in variable_mappings.items():
        if isinstance(var, Variable) and str(var).startswith('__agg_'):
            # This is an aggregate result variable - check if it's referenced in the filter
            if mapping in filter_sql:
                logger.debug(f"Filter references aggregate variable {var}: {filter_sql}")
                return True
    
    return False


def _translate_builtin_abs(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate ABS() function to SQL ABS()."""
    if hasattr(expr, 'arg'):
        arg = translate_bind_arg(expr.arg, variable_mappings)
        return f"ABS({arg})"
    else:
        logger.warning(f"ABS missing arg: {expr}")
        return "0"


def _translate_builtin_isnumeric(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate ISNUMERIC() function to SQL numeric check."""
    if hasattr(expr, 'arg'):
        arg_sql = translate_bind_arg(expr.arg, variable_mappings)
        # Check if value can be cast to numeric using SQL pattern matching
        return f"CASE WHEN ({arg_sql} ~ '^[+-]?([0-9]*[.])?[0-9]+([eE][+-]?[0-9]+)?$') THEN TRUE ELSE FALSE END"
    else:
        logger.warning(f"ISNUMERIC missing arg: {expr}")
        return "FALSE"


def _translate_builtin_round(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate ROUND() function to SQL ROUND()."""
    if hasattr(expr, 'arg'):
        arg = translate_bind_arg(expr.arg, variable_mappings)
        return f"ROUND(CAST({arg} AS DECIMAL))"
    else:
        logger.warning(f"ROUND missing arg: {expr}")
        return "0"


def _translate_builtin_isiri(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate isIRI() function - alias for isURI()."""
    return _translate_builtin_isuri(expr, variable_mappings)


def _translate_builtin_contains(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate CONTAINS() function to SQL LIKE with wildcards."""
    # Handle both expr.arg (from translate_bind_expression) and expr.args (from filter expressions)
    if hasattr(expr, 'arg') and expr.arg is not None:
        # BIND expression format: single arg
        arg = translate_bind_arg(expr.arg, variable_mappings)
        # For BIND, we need to extract the arguments differently
        if hasattr(expr, '_vars') and len(expr._vars) > 0:
            # This is a complex case - let's handle it properly
            logger.warning(f"Complex CONTAINS BIND expression: {expr}")
            return "TRUE"  # Fallback
        return f"({arg} LIKE '%' || ? || '%')"  # Placeholder for now
    elif hasattr(expr, 'args') and len(expr.args) >= 2:
        # Filter expression format: multiple args
        text_arg = translate_bind_arg(expr.args[0], variable_mappings)
        search_arg = translate_bind_arg(expr.args[1], variable_mappings)
        return f"({text_arg} LIKE '%' || {search_arg} || '%')"
    else:
        logger.warning(f"CONTAINS missing args: {expr}")
        return "FALSE"


def _translate_builtin_rand(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate RAND() function to SQL RANDOM()."""
    # RAND() takes no arguments and returns a random number between 0 and 1
    return "RANDOM()"


def _translate_builtin_bound(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate BOUND() function to SQL IS NOT NULL check."""
    if hasattr(expr, 'arg'):
        arg_sql = translate_bind_arg(expr.arg, variable_mappings)
        return f"({arg_sql} IS NOT NULL)"
    return "FALSE"


def _translate_builtin_ceil(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate CEIL() function to SQL CEIL()."""
    if hasattr(expr, 'arg'):
        arg = translate_bind_arg(expr.arg, variable_mappings)
        return f"CEIL(CAST({arg} AS DECIMAL))"
    else:
        logger.warning(f"CEIL missing arg: {expr}")
        return "0"


def _translate_builtin_floor(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate FLOOR() function to SQL FLOOR()."""
    if hasattr(expr, 'arg'):
        arg = translate_bind_arg(expr.arg, variable_mappings)
        return f"FLOOR(CAST({arg} AS DECIMAL))"
    else:
        logger.warning(f"FLOOR missing arg: {expr}")
        return "0"


def _translate_builtin_isuri(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate isURI() function to SQL term_type check."""
    if hasattr(expr, 'arg'):
        arg_sql = translate_bind_arg(expr.arg, variable_mappings)
        # For variables, check the term_type in the database
        if '.term_text' in arg_sql:
            # Replace term_text with term_type and check for 'U' (URI)
            term_type_sql = arg_sql.replace('.term_text', '.term_type')
            return f"({term_type_sql} = 'U')"
        else:
            # For literal values, they are not URIs
            return "FALSE"
    return "FALSE"


def _translate_builtin_isliteral(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate isLITERAL() function to SQL term_type check."""
    if hasattr(expr, 'arg'):
        arg_sql = translate_bind_arg(expr.arg, variable_mappings)
        # For variables, check the term_type in the database
        if '.term_text' in arg_sql:
            # Replace term_text with term_type and check for 'L' (Literal)
            term_type_sql = arg_sql.replace('.term_text', '.term_type')
            return f"({term_type_sql} = 'L')"
        else:
            # For literal values, they are always literals
            return "TRUE"
    return "FALSE"


def _translate_builtin_isblank(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate isBLANK() function to SQL term_type check."""
    if hasattr(expr, 'arg'):
        arg_sql = translate_bind_arg(expr.arg, variable_mappings)
        # For variables, check the term_type in the database
        if '.term_text' in arg_sql:
            # Replace term_text with term_type and check for 'B' (Blank Node)
            term_type_sql = arg_sql.replace('.term_text', '.term_type')
            return f"({term_type_sql} = 'B')"
        else:
            # For non-variable values, check if they start with '_:'
            return f"({arg_sql}::text LIKE '_:%')"
    return "FALSE"


# Missing filter expression functions that were disconnected during refactoring

def _translate_uri_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate URI()/IRI() function in filter expressions."""
    # Extract the argument (should be a string expression)
    if hasattr(expr, 'arg'):
        arg_sql = _translate_expression_operand_sync(expr.arg, variable_mappings)
        # URI/IRI just returns the string value for SQL purposes
        return arg_sql
    return "NULL"


def _translate_bnode_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate BNODE() function in filter expressions.
    
    Note: When BNODE() is used in a filter context, it should check if a value is a blank node,
    not generate new blank nodes. For blank node generation, use BNODE() in BIND expressions.
    """
    # Check if the value is a blank node (term_type = 'B')
    if hasattr(expr, 'arg') and expr.arg:
        arg_sql = _translate_expression_operand_sync(expr.arg, variable_mappings)
        
        # For variables, check the term_type in the database
        if '.term_text' in arg_sql:
            # Replace term_text with term_type and check for 'B' (Blank Node)
            term_type_sql = arg_sql.replace('.term_text', '.term_type')
            return f"({term_type_sql} = 'B')"
        else:
            # For non-variable values, check if they start with '_:'
            return f"({arg_sql}::text LIKE '_:%')"
    else:
        # BNODE without argument in filter context - this is unusual but handle gracefully
        # Return FALSE since we can't check a blank node without specifying what to check
        return "FALSE"





def _translate_isblank_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate isBLANK() function in filter expressions."""
    # Check if the value is a blank node (term_type = 'B')
    if hasattr(expr, 'arg'):
        arg_sql = _translate_expression_operand_sync(expr.arg, variable_mappings)
        
        # For variables, check the term_type in the database
        if '.term_text' in arg_sql:
            # Replace term_text with term_type and check for 'B' (Blank Node)
            term_type_sql = arg_sql.replace('.term_text', '.term_type')
            return f"({term_type_sql} = 'B')"
        else:
            # For non-variable values, check if they start with '_:'
            return f"({arg_sql}::text LIKE '_:%')"
    return "FALSE"


def _translate_bound_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate BOUND() function in filter expressions."""
    # Check if variable is bound (not NULL)
    if hasattr(expr, 'arg'):
        arg_sql = _translate_expression_operand_sync(expr.arg, variable_mappings)
        return f"({arg_sql} IS NOT NULL)"
    return "FALSE"


def _translate_sameterm_filter_expression(expr, variable_mappings: Dict[Variable, str]) -> str:
    """Translate sameTerm() function in filter expressions."""
    # Test if two RDF terms are identical
    if hasattr(expr, 'arg1') and hasattr(expr, 'arg2'):
        arg1_sql = _translate_expression_operand_sync(expr.arg1, variable_mappings)
        arg2_sql = _translate_expression_operand_sync(expr.arg2, variable_mappings)
        return f"({arg1_sql} = {arg2_sql})"
    elif hasattr(expr, 'args') and len(expr.args) >= 2:
        arg1_sql = _translate_expression_operand_sync(expr.args[0], variable_mappings)
        arg2_sql = _translate_expression_operand_sync(expr.args[1], variable_mappings)
        return f"({arg1_sql} = {arg2_sql})"
    return "FALSE"


# End of expressions module
