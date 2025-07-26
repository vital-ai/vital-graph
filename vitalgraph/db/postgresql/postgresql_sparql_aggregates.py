"""
PostgreSQL SPARQL Aggregates Implementation for VitalGraph

This module handles the translation of SPARQL aggregate functions (COUNT, SUM, AVG, MIN, MAX, SAMPLE)
and GROUP BY operations to PostgreSQL SQL.
"""

import logging
from typing import List, Dict, Tuple, Set, Optional, Any
from rdflib import Variable

# Import shared utilities
from .postgresql_sparql_utils import TableConfig, SparqlUtils


class PostgreSQLSparqlAggregates:
    """Handles translation of SPARQL aggregate functions and GROUP BY operations to SQL."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize the aggregates translator.
        
        Args:
            logger: Optional logger instance. If None, creates a new logger.
        """
        self.logger = logger or logging.getLogger(__name__)

    async def translate_aggregate_join(self, agg_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate AggregateJoin pattern (aggregate functions) to SQL.
        
        AggregateJoin patterns have:
        - A: Array of aggregate functions (Aggregate_Count_, Aggregate_Sum_, etc.)
        - p: The nested pattern (usually Group)
        """
        try:
            self.logger.debug(f"Translating AggregateJoin pattern")
            
            # Get the nested pattern (usually Group)
            nested_pattern = agg_pattern.p
            
            # Get the aggregate functions
            aggregates = agg_pattern.A
            self.logger.debug(f"Found {len(aggregates)} aggregate functions: {[agg.name for agg in aggregates]}")
            
            # Validate the aggregate pattern structure
            if not self.validate_aggregate_pattern(agg_pattern):
                self.logger.error("Invalid aggregate pattern structure")
                return f"FROM {table_config.quad_table} q0", [], [], {}
            
            # Extract all aggregate input variables and ensure they're included in projected_vars
            # This ensures that variables like ?age, ?price, ?name get proper SQL column mappings from BGP
            aggregate_input_vars = self.extract_aggregate_input_variables(aggregates)
            
            # Combine original projected_vars with aggregate input variables
            extended_projected_vars = list(projected_vars) if projected_vars else []
            for var in aggregate_input_vars:
                if var not in extended_projected_vars:
                    extended_projected_vars.append(var)
                    self.logger.debug(f"Added aggregate input variable {var} to projected_vars")
            
            self.logger.debug(f"Extended projected_vars for aggregates: {extended_projected_vars}")
            
            # Translate the nested pattern with extended projected variables
            from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern(
                nested_pattern, table_config, extended_projected_vars
            )
            
            self.logger.debug(f"AggregateJoin variable mappings from nested pattern: {variable_mappings}")
            self.logger.debug(f"AggregateJoin projected_vars: {projected_vars}")
            
            # Process each aggregate function using the utility method
            for agg in aggregates:
                agg_name = agg.name
                agg_var = agg.vars  # Input variable (e.g., ?person)
                result_var = agg.res  # Result variable (e.g., __agg_1__)
                has_distinct = hasattr(agg, 'distinct') and agg.distinct
                
                self.logger.debug(f"Processing aggregate {agg_name}: {agg_var} -> {result_var} (distinct: {has_distinct})")
                
                # Use the utility method to translate the aggregate function
                sql_expr = self.translate_aggregate_function(agg_name, agg_var, variable_mappings, has_distinct)
                
                # Map the result variable to the SQL expression
                variable_mappings[result_var] = sql_expr
                self.logger.debug(f"Mapped {result_var} -> {sql_expr}")
            
            return from_clause, where_conditions, joins, variable_mappings
            
        except Exception as e:
            self.logger.error(f"Error translating AggregateJoin pattern: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return f"FROM {table_config.quad_table} q0", [], [], {}
    
    def get_supported_aggregate_functions(self) -> Set[str]:
        """Get the set of supported SPARQL aggregate functions.
        
        Returns:
            Set of supported aggregate function names
        """
        return {
            "Aggregate_Count_", "Aggregate_Count",
            "Aggregate_Sum_", "Aggregate_Sum",
            "Aggregate_Avg_", "Aggregate_Avg",
            "Aggregate_Min_", "Aggregate_Min",
            "Aggregate_Max_", "Aggregate_Max",
            "Aggregate_Sample_", "Aggregate_Sample"
        }
    
    def is_aggregate_function(self, function_name: str) -> bool:
        """Check if a function name is a supported aggregate function.
        
        Args:
            function_name: Name of the function to check
            
        Returns:
            True if the function is a supported aggregate function
        """
        return function_name in self.get_supported_aggregate_functions()
    
    def translate_aggregate_function(self, agg_name: str, agg_var: Variable, 
                                   variable_mappings: Dict[Variable, str], 
                                   has_distinct: bool = False) -> str:
        """Translate a single aggregate function to SQL.
        
        Args:
            agg_name: Name of the aggregate function
            agg_var: Input variable for the aggregate
            variable_mappings: Current variable to SQL column mappings
            has_distinct: Whether the aggregate uses DISTINCT
            
        Returns:
            SQL expression for the aggregate function
        """
        # Normalize function name (remove trailing underscore if present)
        normalized_name = agg_name.rstrip('_')
        
        if normalized_name == "Aggregate_Count":
            if has_distinct:
                if agg_var in variable_mappings:
                    return f"COUNT(DISTINCT {variable_mappings[agg_var]})"
                else:
                    self.logger.warning(f"COUNT(DISTINCT) without mapped variable - using COUNT(*) as fallback")
                    return "COUNT(*)"
            else:
                if agg_var in variable_mappings:
                    return f"COUNT({variable_mappings[agg_var]})"
                else:
                    return "COUNT(*)"
                    
        elif normalized_name == "Aggregate_Sum":
            if agg_var in variable_mappings:
                return f"SUM(CAST({variable_mappings[agg_var]} AS DECIMAL))"
            else:
                return f"'UNMAPPED_SUM_{agg_var}'"
                
        elif normalized_name == "Aggregate_Avg":
            if agg_var in variable_mappings:
                return f"AVG(CAST({variable_mappings[agg_var]} AS DECIMAL))"
            else:
                return f"'UNMAPPED_AVG_{agg_var}'"
                
        elif normalized_name == "Aggregate_Min":
            if agg_var in variable_mappings:
                return f"MIN({variable_mappings[agg_var]})"
            else:
                return f"'UNMAPPED_MIN_{agg_var}'"
                
        elif normalized_name == "Aggregate_Max":
            if agg_var in variable_mappings:
                return f"MAX({variable_mappings[agg_var]})"
            else:
                return f"'UNMAPPED_MAX_{agg_var}'"
                
        elif normalized_name == "Aggregate_Sample":
            # Sample is used for GROUP BY non-aggregated variables
            if agg_var in variable_mappings:
                return variable_mappings[agg_var]
            else:
                return f"'UNMAPPED_SAMPLE_{agg_var}'"
                
        else:
            self.logger.warning(f"Unknown aggregate function: {agg_name}")
            return f"'UNKNOWN_AGG_{agg_name}'"
    
    def extract_aggregate_input_variables(self, aggregates: List[Any]) -> Set[Variable]:
        """Extract all input variables from a list of aggregate functions.
        
        Args:
            aggregates: List of aggregate function objects
            
        Returns:
            Set of variables used as inputs to aggregate functions
        """
        aggregate_input_vars = set()
        for agg in aggregates:
            if hasattr(agg, 'vars') and agg.vars:
                aggregate_input_vars.add(agg.vars)
        return aggregate_input_vars
    
    def build_group_by_clause(self, group_vars: List[Variable], 
                             variable_mappings: Dict[Variable, str]) -> Optional[str]:
        """Build a GROUP BY clause from a list of grouping variables.
        
        Args:
            group_vars: Variables to group by
            variable_mappings: Current variable to SQL column mappings
            
        Returns:
            GROUP BY clause string, or None if no grouping variables
        """
        if not group_vars:
            return None
            
        group_columns = []
        for var in group_vars:
            if var in variable_mappings:
                group_columns.append(variable_mappings[var])
            else:
                self.logger.warning(f"GROUP BY variable {var} not found in mappings")
                
        if group_columns:
            return f"GROUP BY {', '.join(group_columns)}"
        else:
            return None
    
    def validate_aggregate_pattern(self, agg_pattern) -> bool:
        """Validate that an aggregate pattern has the expected structure.
        
        Args:
            agg_pattern: The aggregate pattern to validate
            
        Returns:
            True if the pattern is valid
        """
        try:
            # Check for required attributes
            if not hasattr(agg_pattern, 'A'):
                self.logger.error("AggregateJoin pattern missing 'A' (aggregates) attribute")
                return False
                
            if not hasattr(agg_pattern, 'p'):
                self.logger.error("AggregateJoin pattern missing 'p' (nested pattern) attribute")
                return False
                
            # Check that aggregates is a list
            if not isinstance(agg_pattern.A, (list, tuple)):
                self.logger.error("AggregateJoin 'A' attribute is not a list or tuple")
                return False
                
            # Validate each aggregate function
            for i, agg in enumerate(agg_pattern.A):
                if not hasattr(agg, 'name'):
                    self.logger.error(f"Aggregate function {i} missing 'name' attribute")
                    return False
                    
                if not hasattr(agg, 'res'):
                    self.logger.error(f"Aggregate function {i} missing 'res' (result variable) attribute")
                    return False
                    
                if not self.is_aggregate_function(agg.name):
                    self.logger.warning(f"Unknown aggregate function: {agg.name}")
                    
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating aggregate pattern: {e}")
            return False
    
    async def translate_group_pattern(self, group_pattern, table_config: TableConfig, 
                                    projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate a Group pattern to SQL with GROUP BY clause.
        
        Args:
            group_pattern: The Group pattern to translate
            table_config: Database table configuration
            projected_vars: Variables to project in the query
            
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        try:
            self.logger.debug("Translating Group pattern")
            
            # Get the nested pattern
            nested_pattern = group_pattern.p if hasattr(group_pattern, 'p') else group_pattern
            
            # Get grouping variables
            group_vars = []
            if hasattr(group_pattern, 'expr') and group_pattern.expr:
                # Extract variables from grouping expressions
                for expr in group_pattern.expr:
                    if isinstance(expr, Variable):
                        group_vars.append(expr)
                    elif hasattr(expr, 'var') and isinstance(expr.var, Variable):
                        group_vars.append(expr.var)
            
            self.logger.debug(f"Group variables: {group_vars}")
            
            # Translate the nested pattern
            from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern(
                nested_pattern, table_config, projected_vars
            )
            
            # Build GROUP BY clause if we have grouping variables
            group_by_clause = self.build_group_by_clause(group_vars, variable_mappings)
            if group_by_clause:
                # Add GROUP BY to the from clause (this is a simplification)
                # In practice, this would be handled by the query builder
                self.logger.debug(f"Generated GROUP BY clause: {group_by_clause}")
            
            return from_clause, where_conditions, joins, variable_mappings
            
        except Exception as e:
            self.logger.error(f"Error translating Group pattern: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return f"FROM {table_config.quad_table} q0", [], [], {}
    
    async def translate_group(self, group_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate Group pattern (GROUP BY) to SQL.
        
        Group patterns have:
        - p: The nested pattern to translate
        - expr: The grouping expression (list of variables for GROUP BY)
        """
        try:
            self.logger.debug(f"Translating Group pattern")
            
            # Get the nested pattern
            nested_pattern = group_pattern.p
            
            # Get the grouping expression
            group_expr = getattr(group_pattern, 'expr', None)
            if group_expr:
                self.logger.debug(f"GROUP BY variables: {group_expr}")
            else:
                self.logger.debug("No GROUP BY variables (aggregate without grouping)")
            
            # Translate the nested pattern
            from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern(
                nested_pattern, table_config, projected_vars
            )
            
            # Store GROUP BY information in variable_mappings for later use
            # We'll use this in _build_select_clause to add GROUP BY clause
            if group_expr:
                # Store the GROUP BY variables for later SQL generation
                variable_mappings['__GROUP_BY_VARS__'] = group_expr
                self.logger.debug(f"Stored GROUP BY variables: {group_expr}")
            
            return from_clause, where_conditions, joins, variable_mappings
            
        except Exception as e:
            self.logger.error(f"Error translating UNION pattern: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return f"FROM {table_config.quad_table} q0", [], [], {}


    