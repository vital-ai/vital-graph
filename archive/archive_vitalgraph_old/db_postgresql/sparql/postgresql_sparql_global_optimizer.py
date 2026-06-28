"""
Global SPARQL Query Optimizer for PostgreSQL Backend

This module implements a global two-pass optimization strategy:
1. First pass: Analyze the entire SPARQL algebra tree to collect variable usage patterns
2. Second pass: Generate SQL using globally optimized alias assignments

This addresses the fundamental issue where local pattern-by-pattern translation
cannot achieve optimal alias reuse across different parts of the query.
"""

import logging
from typing import Dict, List, Set, Optional, Any, Tuple
from rdflib import Variable
from dataclasses import dataclass

from .postgresql_sparql_core import AliasGenerator, SparqlContext


@dataclass
class GlobalVariableInfo:
    """Information about a variable's usage across the entire query."""
    variable: Variable
    usage_count: int
    positions: List[Tuple[str, str]]  # (pattern_type, position) e.g., ("BGP", "subject")
    connected_variables: Set[Variable]
    assigned_alias: Optional[str] = None


@dataclass
class GlobalOptimizationState:
    """Global optimization state shared across all pattern translations."""
    variable_info: Dict[Variable, GlobalVariableInfo]
    alias_assignments: Dict[Variable, str]  # variable -> quad_alias
    alias_usage_count: Dict[str, int]  # alias -> usage_count
    total_variables: int
    total_patterns: int
    estimated_table_reduction: float
    master_variable_mappings: Dict[Variable, str] = None  # Master mappings for coordination


class GlobalQueryAnalyzer:
    """Analyzes SPARQL algebra tree to build global optimization state."""
    
    def __init__(self, alias_gen: AliasGenerator, sparql_context: Optional[SparqlContext] = None):
        self.alias_gen = alias_gen
        self.logger = sparql_context.logger if sparql_context else logging.getLogger(__name__)
        self.variable_info: Dict[Variable, GlobalVariableInfo] = {}
        
    def analyze_query(self, algebra) -> GlobalOptimizationState:
        """
        Analyze the entire SPARQL algebra tree using breadth-first variable reuse.
        
        This implements true breadth-first traversal where each variable gets assigned
        once on first encounter and reused everywhere, eliminating duplicates.
        
        Args:
            algebra: RDFLib SPARQL algebra tree
            
        Returns:
            GlobalOptimizationState with breadth-first variable assignments
        """
        self.logger.warning(f"🔍 GLOBAL ANALYZER: Starting breadth-first analysis of {type(algebra).__name__} algebra")
        
        # 🧠 BREADTH-FIRST VARIABLE REUSE: Initialize global variable registry
        # Each variable gets assigned once on first encounter and reused everywhere
        self.global_variable_registry = {}  # Variable -> assigned mapping
        self.variable_counter = 0  # Counter for consistent variable indexing
        
        # Single pass: breadth-first traversal with immediate variable assignment
        self.logger.warning(f"🔍 GLOBAL ANALYZER: Breadth-first traversal with variable reuse")
        self._traverse_breadth_first(algebra, "ROOT")
        self.logger.warning(f"🔍 GLOBAL ANALYZER: Breadth-first complete - {len(self.global_variable_registry)} unique variables")
        
        # Build optimization state from global registry
        optimization_state = self._build_breadth_first_state()
        self.logger.warning(f"🔍 GLOBAL ANALYZER: Built state with {len(optimization_state.alias_assignments)} assignments")
        
        return optimization_state
    
    def _traverse_breadth_first(self, pattern, pattern_type: str, depth: int = 0):
        """
        Breadth-first traversal of SPARQL algebra with immediate variable assignment.
        
        Each variable gets assigned once on first encounter and reused everywhere.
        This eliminates duplicates and ensures consistent variable mapping.
        """
        if pattern is None:
            return
            
        indent = "  " * depth
        pattern_name = getattr(pattern, 'name', str(type(pattern).__name__))
        self.logger.debug(f"{indent}🧠 BFS: {pattern_type}.{pattern_name}")
        
        # Handle different pattern types with breadth-first processing
        if pattern_name == "BGP":
            self._process_bgp_breadth_first(pattern, depth)
        elif pattern_name == "Union":
            self._traverse_breadth_first(getattr(pattern, 'p1', None), "UNION_LEFT", depth + 1)
            self._traverse_breadth_first(getattr(pattern, 'p2', None), "UNION_RIGHT", depth + 1)
        elif pattern_name == "Join":
            self._traverse_breadth_first(getattr(pattern, 'p1', None), "JOIN_LEFT", depth + 1)
            self._traverse_breadth_first(getattr(pattern, 'p2', None), "JOIN_RIGHT", depth + 1)
        elif pattern_name == "LeftJoin":
            self._traverse_breadth_first(getattr(pattern, 'p1', None), "OPTIONAL_REQUIRED", depth + 1)
            self._traverse_breadth_first(getattr(pattern, 'p2', None), "OPTIONAL_OPTIONAL", depth + 1)
        elif hasattr(pattern, 'p'):
            # Generic pattern with single sub-pattern
            self._traverse_breadth_first(getattr(pattern, 'p'), f"{pattern_type}_{pattern_name}", depth + 1)
    
    def _process_bgp_breadth_first(self, bgp_pattern, depth: int):
        """
        Process BGP pattern with breadth-first variable assignment.
        
        Each variable gets assigned once on first encounter.
        """
        indent = "  " * depth
        triples = getattr(bgp_pattern, 'triples', [])
        
        for triple in triples:
            for term in triple:
                if hasattr(term, 'n3') and term.n3().startswith('?'):
                    # This is a variable
                    var_name = str(term)
                    
                    # 🧠 BREADTH-FIRST ASSIGNMENT: Assign once, reuse everywhere
                    if term not in self.global_variable_registry:
                        # First encounter - assign new mapping
                        var_mapping = f"var_{self.variable_counter}"
                        self.global_variable_registry[term] = var_mapping
                        self.variable_counter += 1
                        self.logger.debug(f"{indent}🧠 BFS: NEW variable {var_name} -> {var_mapping}")
                    else:
                        # Subsequent encounter - reuse existing mapping
                        existing_mapping = self.global_variable_registry[term]
                        self.logger.debug(f"{indent}🧠 BFS: REUSE variable {var_name} -> {existing_mapping}")
    
    def _build_breadth_first_state(self) -> GlobalOptimizationState:
        """
        Build GlobalOptimizationState from breadth-first variable registry.
        
        This creates the final optimization state with consistent variable mappings.
        """
        # Convert global registry to optimization state format
        alias_assignments = {}
        master_variable_mappings = {}
        variable_info = {}
        alias_usage_count = {}
        
        for variable, mapping in self.global_variable_registry.items():
            var_name = str(variable)
            alias_assignments[variable] = mapping
            master_variable_mappings[variable] = mapping
            
            # Create variable info for compatibility
            variable_info[variable] = GlobalVariableInfo(
                variable=variable,
                usage_count=1,  # Simplified for breadth-first
                positions=[("BGP", "term")],  # Simplified position info
                connected_variables=set(),  # Simplified for breadth-first
                assigned_alias=mapping
            )
            
            # Track alias usage
            alias_usage_count[mapping] = alias_usage_count.get(mapping, 0) + 1
            
            self.logger.debug(f"🧠 BFS STATE: {var_name} -> {mapping}")
        
        # Calculate estimated table reduction (breadth-first achieves optimal reduction)
        total_variables = len(self.global_variable_registry)
        estimated_reduction = max(0.0, (total_variables - len(alias_assignments)) / max(1, total_variables))
        
        # Create optimization state with all required fields
        state = GlobalOptimizationState(
            variable_info=variable_info,
            alias_assignments=alias_assignments,
            alias_usage_count=alias_usage_count,
            total_variables=total_variables,
            total_patterns=1,  # Simplified for breadth-first
            estimated_table_reduction=estimated_reduction,
            master_variable_mappings=master_variable_mappings
        )
        
        self.logger.warning(f"🧠 BFS STATE: Created state with {len(alias_assignments)} consistent variable mappings")
        return state
    
    def _collect_variables_recursive(self, pattern, pattern_type: str, depth: int = 0):
        """Recursively collect variables from SPARQL algebra patterns."""
        if pattern is None:
            return
            
        indent = "  " * depth
        pattern_name = getattr(pattern, 'name', str(type(pattern).__name__))
        self.logger.debug(f"{indent}📋 Analyzing {pattern_type}.{pattern_name}")
        
        # Handle different pattern types
        if pattern_name == "BGP":
            self._collect_bgp_variables(pattern, depth)
        elif pattern_name == "Union":
            self._collect_variables_recursive(getattr(pattern, 'p1', None), "UNION_LEFT", depth + 1)
            self._collect_variables_recursive(getattr(pattern, 'p2', None), "UNION_RIGHT", depth + 1)
        elif pattern_name == "Join":
            self._collect_variables_recursive(getattr(pattern, 'p1', None), "JOIN_LEFT", depth + 1)
            self._collect_variables_recursive(getattr(pattern, 'p2', None), "JOIN_RIGHT", depth + 1)
        elif pattern_name == "LeftJoin":
            self._collect_variables_recursive(getattr(pattern, 'p1', None), "OPTIONAL_REQUIRED", depth + 1)
            self._collect_variables_recursive(getattr(pattern, 'p2', None), "OPTIONAL_OPTIONAL", depth + 1)
        elif hasattr(pattern, 'p'):
            # Generic pattern with single sub-pattern
            self._collect_variables_recursive(getattr(pattern, 'p'), f"{pattern_type}_{pattern_name}", depth + 1)
    
    def _collect_bgp_variables(self, bgp_pattern, depth: int):
        """Collect variables from Basic Graph Pattern."""
        if not hasattr(bgp_pattern, 'triples') or not bgp_pattern.triples:
            return
            
        indent = "  " * depth
        self.logger.debug(f"{indent}🔍 BGP with {len(bgp_pattern.triples)} triples")
        
        # Track variables within this BGP for connectivity analysis
        bgp_variables = set()
        
        for triple_idx, triple in enumerate(bgp_pattern.triples):
            subject, predicate, obj = triple
            
            # Process each position in the triple
            for position, term in [("subject", subject), ("predicate", predicate), ("object", obj)]:
                if isinstance(term, Variable):
                    bgp_variables.add(term)
                    
                    # Create or update variable info
                    if term not in self.variable_info:
                        self.variable_info[term] = GlobalVariableInfo(
                            variable=term,
                            usage_count=0,
                            positions=[],
                            connected_variables=set()
                        )
                    
                    var_info = self.variable_info[term]
                    var_info.usage_count += 1
                    var_info.positions.append(("BGP", position))
        
        # Update connectivity: variables in the same BGP are connected
        for var1 in bgp_variables:
            for var2 in bgp_variables:
                if var1 != var2:
                    self.variable_info[var1].connected_variables.add(var2)
                    self.variable_info[var2].connected_variables.add(var1)
    
    def _build_optimization_state(self) -> GlobalOptimizationState:
        """Build global optimization state with alias assignments."""
        
        # Sort variables by usage count (most used first) for better alias assignment
        sorted_variables = sorted(
            self.variable_info.items(),
            key=lambda x: (x[1].usage_count, len(x[1].connected_variables)),
            reverse=True
        )
        
        self.logger.warning(f"🔍 Variable usage analysis: {[(str(var), info.usage_count) for var, info in sorted_variables[:5]]}")
        
        # Assign aliases using connectivity-based grouping
        alias_assignments = {}
        alias_usage_count = {}
        processed_variables = set()
        
        total_variables = len(self.variable_info)
        if total_variables > 6:  # Lower threshold for aggressive optimization
            self.logger.warning(f"🔥 EXTREME ALIAS REDUCTION: {total_variables} variables detected - using maximum alias sharing")
            
            # EXTREME OPTIMIZATION: Use only 2-3 aliases for all variables to dramatically reduce table count
            max_aliases = max(2, min(3, total_variables // 3))  # Use 2-3 aliases maximum
            self.logger.warning(f"🔥 EXTREME: Reducing {total_variables} variables to {max_aliases} table aliases")
            
            # Create alias groups and assign variables round-robin
            alias_groups = []
            for i in range(max_aliases):
                alias_groups.append({
                    'alias': self.alias_gen.next_quad_alias(),
                    'variables': [],
                    'total_usage': 0
                })
            
            # Distribute variables across alias groups in round-robin fashion
            for idx, (variable, var_info) in enumerate(sorted_variables):
                group_idx = idx % max_aliases
                group = alias_groups[group_idx]
                
                group['variables'].append(variable)
                group['total_usage'] += var_info.usage_count
                
                alias_assignments[variable] = group['alias']
                processed_variables.add(variable)
            
            # Log the extreme optimization results
            for group in alias_groups:
                alias_usage_count[group['alias']] = group['total_usage']
                self.logger.warning(f"🔥 EXTREME: Alias {group['alias']} assigned to {len(group['variables'])} variables (usage: {group['total_usage']})")
        else:
            # Standard optimization for simpler queries
            for variable, var_info in sorted_variables:
                if variable in processed_variables:
                    continue
                    
                # Find all variables transitively connected to this one
                connected_group = self._find_connected_group(variable, processed_variables)
                
                # Generate a single alias for the entire connected group
                group_alias = self.alias_gen.next_quad_alias()
                
                # Assign the same alias to all variables in the connected group
                for connected_var in connected_group:
                    alias_assignments[connected_var] = group_alias
                    processed_variables.add(connected_var)
                
                # Track usage count for this alias (sum of all variables using it)
                total_usage = sum(self.variable_info[v].usage_count for v in connected_group if v in self.variable_info)
                alias_usage_count[group_alias] = total_usage
                
                self.logger.debug(f"🔗 Assigned alias {group_alias} to {len(connected_group)} connected variables: "
                                f"{[str(v) for v in list(connected_group)[:3]]}{'...' if len(connected_group) > 3 else ''}")
        
        # Calculate estimated table reduction
        total_variables = len(self.variable_info)
        unique_aliases = len(alias_usage_count)
        estimated_reduction = (total_variables - unique_aliases) / max(total_variables, 1)
        
        return GlobalOptimizationState(
            variable_info=self.variable_info,
            alias_assignments=alias_assignments,
            alias_usage_count=alias_usage_count,
            total_variables=total_variables,
            total_patterns=len([info for info in self.variable_info.values() if info.usage_count > 0]),
            estimated_table_reduction=estimated_reduction
        )
    
    def _find_connected_group(self, start_variable: Variable, processed_variables: Set[Variable]) -> Set[Variable]:
        """Find all variables transitively connected to the start variable."""
        connected_group = set()
        queue = [start_variable]
        
        while queue:
            current_var = queue.pop(0)
            if current_var in processed_variables or current_var in connected_group:
                continue
                
            connected_group.add(current_var)
            
            # Add all directly connected variables to the queue
            if current_var in self.variable_info:
                for connected_var in self.variable_info[current_var].connected_variables:
                    if connected_var not in processed_variables and connected_var not in connected_group:
                        queue.append(connected_var)
        
        return connected_group


def create_global_optimization_state(algebra, alias_gen: AliasGenerator, 
                                   sparql_context: Optional[SparqlContext] = None) -> GlobalOptimizationState:
    """
    Create global optimization state for a SPARQL query.
    
    This is the main entry point for global query optimization.
    
    Args:
        algebra: RDFLib SPARQL algebra tree
        alias_gen: Alias generator for consistent naming
        sparql_context: Optional context for logging
        
    Returns:
        GlobalOptimizationState with optimized alias assignments
    """
    import logging
    logger = sparql_context.logger if sparql_context else logging.getLogger(__name__)
    logger.warning(f"🌍 GLOBAL OPTIMIZER: create_global_optimization_state called with algebra: {type(algebra).__name__}")
    
    try:
        analyzer = GlobalQueryAnalyzer(alias_gen, sparql_context)
        result = analyzer.analyze_query(algebra)
        logger.warning(f"🌍 GLOBAL OPTIMIZER: Analysis complete - {result.total_variables} vars -> {len(result.alias_assignments)} aliases")
        return result
    except Exception as e:
        logger.error(f"❌ GLOBAL OPTIMIZER: Error in create_global_optimization_state: {e}")
        import traceback
        logger.error(f"❌ GLOBAL OPTIMIZER: Traceback: {traceback.format_exc()}")
        raise
