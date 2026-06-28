"""
PostgreSQL SPARQL Core Functions for VitalGraph

This module provides pure functions for core SQL generation operations.
No inter-dependencies with other SPARQL modules - only imports utilities.
"""

import logging
from typing import Dict, List, Tuple, Set, Optional, Any
from dataclasses import dataclass
from rdflib import Variable, URIRef, Literal, BNode

# Import shared utilities only
from ..postgresql_space_impl import PostgreSQLSpaceImpl
from ..postgresql_log_utils import PostgreSQLLogUtils
from ..space.postgresql_space_utils import PostgreSQLSpaceUtils


class GraphConstants:
    """Constants for graph URI handling in SPARQL queries."""
    GLOBAL_GRAPH_URI = "urn:___GLOBAL"
    GLOBAL_GRAPH_TYPE = "U"  # URI type
    
    @classmethod
    def get_global_graph_term_info(cls) -> Tuple[str, str]:
        """Get term info tuple for global graph."""
        return (cls.GLOBAL_GRAPH_URI, cls.GLOBAL_GRAPH_TYPE)


class SparqlUtils:
    """Utility functions for SPARQL-to-SQL translation."""
    
    @staticmethod
    def get_term_info(term) -> Tuple[str, str]:
        """Extract term text and type from RDFLib term.
        
        Args:
            term: RDFLib term (URIRef, Literal, BNode)
            
        Returns:
            Tuple of (term_text, term_type) where term_type is 'U', 'L', or 'B'
        """
        if isinstance(term, URIRef):
            return (str(term), 'U')
        elif isinstance(term, Literal):
            return (str(term), 'L')
        elif isinstance(term, BNode):
            return (str(term), 'B')
        else:
            # Fallback for unknown term types
            return (str(term), 'U')
    
    @staticmethod
    def convert_rdflib_term_to_sql(term) -> str:
        """Convert RDFLib term to SQL literal value.
        
        Args:
            term: RDFLib term to convert
            
        Returns:
            SQL-safe literal string
        """
        if isinstance(term, URIRef):
            # URI references as strings with escaped quotes
            uri_str = str(term).replace("'", "''")
            return f"'{uri_str}'"
        elif isinstance(term, Literal):
            # Literals as strings with escaped quotes
            literal_str = str(term).replace("'", "''")
            return f"'{literal_str}'"
        elif isinstance(term, Variable):
            # Variables should not be converted to literals
            raise ValueError(f"Cannot convert Variable {term} to SQL literal")
        elif isinstance(term, BNode):
            # Blank nodes as strings
            bnode_str = str(term).replace("'", "''")
            return f"'{bnode_str}'"
        else:
            # Fallback for unknown types
            fallback_str = str(term).replace("'", "''")
            return f"'{fallback_str}'"
    
    @staticmethod
    def find_shared_variables_between_triples(triple1, triple2):
        """Find variables that appear in both triples.
        
        Args:
            triple1: First triple (subject, predicate, object)
            triple2: Second triple (subject, predicate, object)
            
        Returns:
            Set of shared Variable objects
        """
        vars1 = set()
        vars2 = set()
        
        # Extract variables from first triple
        for term in triple1:
            if isinstance(term, Variable):
                vars1.add(term)
        
        # Extract variables from second triple
        for term in triple2:
            if isinstance(term, Variable):
                vars2.add(term)
        
        return vars1 & vars2
    
    @staticmethod
    def get_variable_position_in_triple(triple, variable):
        """Get the position of a variable in a triple.
        
        Args:
            triple: Triple (subject, predicate, object)
            variable: Variable to find
            
        Returns:
            Position string ('subject', 'predicate', 'object') or None
        """
        subject, predicate, obj = triple
        
        if subject == variable:
            return 'subject'
        elif predicate == variable:
            return 'predicate'
        elif obj == variable:
            return 'object'
        else:
            return None
    
    @staticmethod
    def extract_variables_from_pattern(pattern):
        """Extract all variables from a SPARQL pattern.
        
        Args:
            pattern: SPARQL algebra pattern
            
        Returns:
            List of Variable objects found in the pattern
        """
        variables = []
        
        # Try to get variables from pattern's _vars attribute
        if hasattr(pattern, '_vars'):
            variables.extend(list(pattern._vars))
        
        # Try to get variables from pattern's get method
        try:
            pattern_vars = pattern.get('_vars', set())
            variables.extend(list(pattern_vars))
        except (AttributeError, TypeError):
            pass
        
        # For BGP patterns, extract from triples
        if hasattr(pattern, 'triples'):
            for triple in pattern.triples:
                for term in triple:
                    if isinstance(term, Variable) and term not in variables:
                        variables.append(term)
        
        return variables


class REGEXTerm(str):
    """A string subclass that represents a regex pattern for term matching.
    
    This is used in quad pattern matching to enable regex-based searches
    on term text using PostgreSQL's regex operators.
    """
    
    def __new__(cls, pattern):
        obj = str.__new__(cls, pattern)
        obj.pattern = pattern
        obj.compiledExpr = None  # Could add compiled regex if needed
        return obj
    
    def match(self, text):
        """Check if the pattern matches the given text.
        
        Args:
            text: Text to match against
            
        Returns:
            bool: True if pattern matches
        """
        import re
        if self.compiledExpr is None:
            self.compiledExpr = re.compile(self.pattern)
        return self.compiledExpr.match(str(text)) is not None
    
    def __reduce__(self):
        """Support for pickling."""
        return (self.__class__, (self.pattern,))
    
    def __repr__(self):
        return f"REGEXTerm('{self.pattern}')"


def is_regex_term(term) -> bool:
    """Check if a term is a REGEXTerm instance.
    
    Args:
        term: Term to check
        
    Returns:
        bool: True if term is a REGEXTerm
    """
    return isinstance(term, REGEXTerm)


@dataclass
class SQLComponents:
    """Container for SQL query components."""
    from_clause: str
    where_conditions: List[str]
    joins: List[str]
    variable_mappings: Dict[Variable, str]
    order_by: str = ""
    
    def __post_init__(self):
        """Ensure all fields are properly initialized."""
        if self.where_conditions is None:
            self.where_conditions = []
        if self.joins is None:
            self.joins = []
        if self.variable_mappings is None:
            self.variable_mappings = {}
        if self.order_by is None:
            self.order_by = ""


class AliasGenerator:
    """Independent alias generator for SQL table and column aliases."""
    
    def __init__(self, prefix: str = ""):
        """Initialize alias generator with optional prefix."""
        import logging
        self.logger = logging.getLogger(__name__)
        self.prefix = prefix
        self.counters = {
            'quad': 0,
            'term': 0,
            'subquery': 0,
            'join': 0,
            'union': 0,
            'values': 0
        }
        self.instance_id = id(self)  # Unique instance identifier
        self.logger.debug(f"🏗️ ALIAS_GEN_INIT: Created new AliasGenerator instance {self.instance_id} with prefix '{prefix}'")
    
    def next_quad_alias(self) -> str:
        """Generate next quad table alias."""
        old_counter = self.counters['quad']
        alias = f"{self.prefix}q{old_counter}"
        self.counters['quad'] += 1
        self.logger.debug(f"🔧 ALIAS_GEN_QUAD: Instance {self.instance_id} generated '{alias}' (counter: {old_counter} → {self.counters['quad']})")
        return alias
    
    def next_term_alias(self, position: str) -> str:
        """Generate next term table alias for given position."""
        old_counter = self.counters['term']
        alias = f"{self.prefix}{position}_term_{old_counter}"
        self.counters['term'] += 1
        self.logger.debug(f"🔧 ALIAS_GEN_TERM: Instance {self.instance_id} generated '{alias}' (counter: {old_counter} → {self.counters['term']})")
        return alias
    
    def next_subquery_alias(self) -> str:
        """Generate next subquery alias."""
        old_counter = self.counters['subquery']
        alias = f"{self.prefix}subquery_{old_counter}"
        self.counters['subquery'] += 1
        self.logger.debug(f"🔧 ALIAS_GEN_SUBQUERY: Instance {self.instance_id} generated '{alias}' (counter: {old_counter} → {self.counters['subquery']})")
        return alias
    
    def next_join_alias(self) -> str:
        """Generate next join alias."""
        alias = f"{self.prefix}join_{self.counters['join']}"
        self.counters['join'] += 1
        return alias
    
    def next_union_alias(self) -> str:
        """Generate next union alias."""
        alias = f"{self.prefix}union_{self.counters['union']}"
        self.counters['union'] += 1
        return alias
    
    def next_values_alias(self) -> str:
        """Generate next VALUES alias."""
        alias = f"{self.prefix}values_{self.counters['values']}"
        self.counters['values'] += 1
        return alias
    
    def create_child_generator(self, child_prefix: str) -> 'AliasGenerator':
        """Create a child generator with a different prefix to avoid conflicts."""
        child_gen = AliasGenerator(f"{self.prefix}{child_prefix}_")
        self.logger.debug(f"👶 ALIAS_GEN_CHILD: Instance {self.instance_id} created child {child_gen.instance_id} with prefix '{child_prefix}'")
        return child_gen
    
    def reset_counters(self):
        """Reset all counters to 0 - for debugging purposes."""
        old_counters = self.counters.copy()
        self.counters = {
            'quad': 0,
            'term': 0,
            'subquery': 0,
            'join': 0,
            'union': 0,
            'values': 0
        }
        self.logger.warning(f"🔄 ALIAS_GEN_RESET: Instance {self.instance_id} counters reset from {old_counters} to {self.counters}")
    
    def get_state(self) -> dict:
        """Get current state for debugging."""
        state = {
            'instance_id': self.instance_id,
            'prefix': self.prefix,
            'counters': self.counters.copy()
        }
        self.logger.debug(f"📊 ALIAS_GEN_STATE: Instance {self.instance_id} state: {state}")
        return state


@dataclass
class TableConfig:
    """Configuration for quad, term, and graph table names."""
    quad_table: str
    term_table: str
    graph_table: str
    
    @classmethod
    def from_space_impl(cls, space_impl, space_id: str) -> 'TableConfig':
        """Create TableConfig from PostgreSQLSpaceImpl and space_id."""
        quad_table = PostgreSQLSpaceUtils.get_table_name(space_impl.global_prefix, space_id, "rdf_quad")
        term_table = PostgreSQLSpaceUtils.get_table_name(space_impl.global_prefix, space_id, "term")
        graph_table = PostgreSQLSpaceUtils.get_table_name(space_impl.global_prefix, space_id, "graph")
            
        return cls(quad_table=quad_table, term_table=term_table, graph_table=graph_table)


class SparqlContext:
    """
    Stateful context object that maintains shared state across all SPARQL processing.
    
    This replaces the original class-based approach where self.alias_generator and other
    state was automatically shared across all method calls. By passing this context object
    to all SPARQL generation functions, we ensure perfect alias consistency and prevent
    "missing FROM-clause entry" errors where context constraints reference aliases that
    don't exist in the final FROM clause.
    
    This context can be used by any SPARQL-related function for logging, state management,
    and maintaining consistency across the translation pipeline.
    """
    
    def __init__(self, alias_generator: AliasGenerator, term_cache=None,
                 space_impl=None, table_config: TableConfig = None, datatype_cache=None, space_id=None, logger=None):
        self.alias_generator = alias_generator
        self.term_cache = term_cache
        self.space_impl = space_impl
        self.table_config = table_config
        self.datatype_cache = datatype_cache
        self.space_id = space_id
        
        # Logger for consistent function-name logging
        import logging
        self.logger = logger or logging.getLogger(__name__)
        
        # Additional state that might be needed
        self.graph_cache = {}
        self.variable_counter = 0
        self.join_counter = 0
        

    
    def log_function_entry(self, function_name: str, **kwargs):
        """Log function entry with consistent format including function name."""
        args_str = ", ".join(f"{k}={v}" for k, v in kwargs.items())
        self.logger.info(f"🔍 {function_name}: Starting translation - {args_str}")
    
    def log_function_exit(self, function_name: str, result_type: str = None, **kwargs):
        """Log function exit with consistent format including function name."""
        result_str = f"result_type={result_type}" if result_type else ""
        args_str = ", ".join(f"{k}={v}" for k, v in kwargs.items())
        log_parts = [part for part in [result_str, args_str] if part]
        self.logger.info(f"✅ {function_name}: Completed translation - {', '.join(log_parts)}")
    
    def log_function_error(self, function_name: str, error: Exception):
        """Log function error with consistent format including function name."""
        self.logger.error(f"❌ {function_name}: Error during translation - {error}")


# Backward compatibility alias
TranslationContext = SparqlContext


# Core SQL generation functions

def _find_shared_variables_between_triples(triple1, triple2):
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


def _get_variable_position_in_triple(triple, variable):
    """Get the position (subject, predicate, object) of a variable in a triple."""
    subject, predicate, obj = triple
    
    if subject == variable:
        return "subject"
    elif predicate == variable:
        return "predicate"
    elif obj == variable:
        return "object"
    
    return None


async def generate_bgp_sql(triples: List[Tuple], table_config: TableConfig, alias_gen: AliasGenerator, projected_vars: Optional[List[Variable]] = None, *, sparql_context: SparqlContext = None) -> SQLComponents:
    """
    Generate SQL components for Basic Graph Pattern (BGP) with optimization for shared variables.
    
    OPTIMIZATION: This version reuses table aliases when variables are shared across triples,
    dramatically reducing the number of table joins. Instead of creating separate aliases
    for each triple, we track variable usage and reuse aliases where possible.
    
    Args:
        triples: List of RDF triples (subject, predicate, object)
        table_config: Table configuration for SQL generation
        alias_gen: Alias generator for unique table aliases
        projected_vars: Variables to project (for optimization)
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        SQLComponents with FROM clause, WHERE conditions, JOINs, and variable mappings
    """
    function_name = "generate_bgp_sql"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, 
                                         num_triples=len(triples) if triples else 0,
                                         has_projected_vars=projected_vars is not None)
    else:
        logger = logging.getLogger(__name__)
    logger = logging.getLogger(__name__)
    
    # Handle None triples
    if triples is None:
        triples = []
    
    logger.debug(f"Generating BGP SQL for {len(triples)} triples")
    
    if not triples:
        return SQLComponents(
            from_clause="",
            where_conditions=[],
            joins=[],
            variable_mappings={}
        )
    
    # GLOBAL OPTIMIZATION: Check if we have global optimization state in SparqlContext

    
    # OPTIMIZATION: Track variable-to-alias mappings to reuse aliases for shared variables
    all_joins = []
    quad_joins = []  # JOINs for additional quad tables
    all_where_conditions = []
    variable_mappings = {}
    quad_aliases = []
    
    # OPTIMIZATION: Comprehensive variable usage analysis for maximum alias reuse
    variable_positions = {}  # var -> [(triple_idx, position), ...]
    quad_alias_for_variable = {}  # var -> quad_alias (for reuse)
    variable_connectivity = {}  # var -> set of connected variables
    
    # First pass: analyze variable usage patterns and connectivity
    for triple_idx, triple in enumerate(triples):
        subject, predicate, obj = triple
        triple_vars = []
        
        # Track variable positions for optimization
        if isinstance(subject, Variable):
            if subject not in variable_positions:
                variable_positions[subject] = []
            variable_positions[subject].append((triple_idx, 'subject'))
            triple_vars.append(subject)
            
        if isinstance(predicate, Variable):
            if predicate not in variable_positions:
                variable_positions[predicate] = []
            variable_positions[predicate].append((triple_idx, 'predicate'))
            triple_vars.append(predicate)
            
        if isinstance(obj, Variable):
            if obj not in variable_positions:
                variable_positions[obj] = []
            variable_positions[obj].append((triple_idx, 'object'))
            triple_vars.append(obj)
        
        # Build connectivity graph: variables in the same triple are connected
        for var1 in triple_vars:
            if var1 not in variable_connectivity:
                variable_connectivity[var1] = set()
            for var2 in triple_vars:
                if var1 != var2:
                    variable_connectivity[var1].add(var2)
    
    logger.warning(f"🔧 BGP OPTIMIZATION: Processing {len(triples)} triples with {len(variable_positions)} unique variables")
    logger.debug(f"Variable usage analysis: {len(variable_positions)} unique variables across {len(triples)} triples")
    logger.debug(f"Variable connectivity: {[(str(k), [str(v) for v in vs]) for k, vs in variable_connectivity.items()]}")
    
    # OPTIMIZATION: Direct variable-based alias reuse (simplified approach)
    # For each variable, assign it to the first quad alias that uses it
    # This ensures that all triples sharing a variable use the same alias
    
    # Build a mapping of which variables appear in which triples
    variable_to_triples = {}  # var -> [triple_indices]
    for triple_idx, triple in enumerate(triples):
        subject, predicate, obj = triple
        for var in [subject, predicate, obj]:
            if isinstance(var, Variable):
                if var not in variable_to_triples:
                    variable_to_triples[var] = []
                variable_to_triples[var].append(triple_idx)
    
    # Find the most connected variable (appears in most triples) to start with
    most_connected_vars = sorted(variable_to_triples.items(), key=lambda x: len(x[1]), reverse=True)
    logger.debug(f"🔍 Most connected variables: {[(str(var), len(triples)) for var, triples in most_connected_vars[:5]]}")
    
    # Assign aliases based on variable usage
    triple_to_alias = {}  # triple_idx -> quad_alias
    alias_usage_count = {}  # alias -> count of triples using it
    
    for var, triple_indices in most_connected_vars:
        # Check if any of these triples already have an alias assigned
        existing_alias = None
        for triple_idx in triple_indices:
            if triple_idx in triple_to_alias:
                existing_alias = triple_to_alias[triple_idx]
                break
        
        if existing_alias:
            # Reuse existing alias for all triples with this variable
            alias_to_use = existing_alias
            logger.debug(f"🔄 Reusing alias {alias_to_use} for variable {var} across {len(triple_indices)} triples")
        else:
            # Create new alias for this variable
            alias_to_use = alias_gen.next_quad_alias()
            logger.debug(f"🆕 Created new alias {alias_to_use} for variable {var} across {len(triple_indices)} triples")
        
        # Assign this alias to all triples that use this variable
        for triple_idx in triple_indices:
            if triple_idx not in triple_to_alias:
                triple_to_alias[triple_idx] = alias_to_use
                alias_usage_count[alias_to_use] = alias_usage_count.get(alias_to_use, 0) + 1
        
        # Track this alias for the variable
        quad_alias_for_variable[var] = alias_to_use
    
    # Handle any remaining triples without aliases (shouldn't happen)
    for triple_idx in range(len(triples)):
        if triple_idx not in triple_to_alias:
            fallback_alias = alias_gen.next_quad_alias()
            triple_to_alias[triple_idx] = fallback_alias
            logger.warning(f"⚠️ Created fallback alias {fallback_alias} for triple {triple_idx}")
    
    unique_aliases = len(set(triple_to_alias.values()))
    logger.warning(f"🎯 BGP OPTIMIZATION RESULT: Reduced {len(triples)} triples to {unique_aliases} unique aliases")
    logger.warning(f"📊 Alias usage: {[(alias, count) for alias, count in sorted(alias_usage_count.items())]}")
    
    # Second pass: generate SQL with pre-computed alias assignments
    for triple_idx, triple in enumerate(triples):
        subject, predicate, obj = triple
        
        # Use the pre-computed alias for this triple
        quad_alias = triple_to_alias.get(triple_idx)
        reused_alias = quad_alias in alias_usage_count and alias_usage_count[quad_alias] > 1
        
        # Safety fallback (shouldn't happen)
        if quad_alias is None:
            quad_alias = alias_gen.next_quad_alias()
            logger.error(f"❌ CRITICAL: No alias found for triple {triple_idx} - this should not happen!")
        
        quad_aliases.append(quad_alias)
        logger.debug(f"Processing triple #{triple_idx}: ({subject}, {predicate}, {obj}) -> {quad_alias} (reused: {reused_alias})")
        
        # Handle subject - exact logic from original
        if isinstance(subject, Variable):
            if subject not in variable_mappings and (projected_vars is None or subject in projected_vars):
                term_alias = alias_gen.next_term_alias("subject")
                all_joins.append(f"JOIN {table_config.term_table} {term_alias} ON {quad_alias}.subject_uuid = {term_alias}.term_uuid")
                variable_mappings[subject] = f"{term_alias}.term_text"
        else:
            # Bound term - use SQL subquery (fallback when no cache)
            term_text, term_type = SparqlUtils.get_term_info(subject)
            escaped_text = term_text.replace("'", "''")
            all_where_conditions.append(
                f"{quad_alias}.subject_uuid = (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{escaped_text}' AND term_type = '{term_type}')"
            )
        
        # Handle predicate - exact logic from original
        if isinstance(predicate, Variable):
            if predicate not in variable_mappings and (projected_vars is None or predicate in projected_vars):
                term_alias = alias_gen.next_term_alias("predicate")
                all_joins.append(f"JOIN {table_config.term_table} {term_alias} ON {quad_alias}.predicate_uuid = {term_alias}.term_uuid")
                variable_mappings[predicate] = f"{term_alias}.term_text"
        else:
            # Bound term - use SQL subquery (fallback when no cache)
            term_text, term_type = SparqlUtils.get_term_info(predicate)
            escaped_text = term_text.replace("'", "''")
            all_where_conditions.append(
                f"{quad_alias}.predicate_uuid = (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{escaped_text}' AND term_type = '{term_type}')"
            )
        
        # Handle object - exact logic from original
        if isinstance(obj, Variable):
            if obj not in variable_mappings and (projected_vars is None or obj in projected_vars):
                term_alias = alias_gen.next_term_alias("object")
                all_joins.append(f"JOIN {table_config.term_table} {term_alias} ON {quad_alias}.object_uuid = {term_alias}.term_uuid")
                variable_mappings[obj] = f"{term_alias}.term_text"
        else:
            # Bound term - use SQL subquery (fallback when no cache)
            term_text, term_type = SparqlUtils.get_term_info(obj)
            escaped_text = term_text.replace("'", "''")
            all_where_conditions.append(
                f"{quad_alias}.object_uuid = (SELECT term_uuid FROM {table_config.term_table} WHERE term_text = '{escaped_text}' AND term_type = '{term_type}')"
            )
        


    
    # OPTIMIZATION: Build FROM clause with unique quad aliases only
    # Remove duplicate aliases that were reused for shared variables
    unique_quad_aliases = []
    seen_aliases = set()
    for alias in quad_aliases:
        if alias not in seen_aliases:
            unique_quad_aliases.append(alias)
            seen_aliases.add(alias)
    
    logger.debug(f"Reduced {len(quad_aliases)} total aliases to {len(unique_quad_aliases)} unique aliases")
    
    if not unique_quad_aliases:
        # No quad tables needed - this shouldn't happen but handle gracefully
        from_clause = ""
    else:
        # Build FROM clause with first unique quad table
        from_clause = f"FROM {table_config.quad_table} {unique_quad_aliases[0]}"
        
        # Add additional unique quad tables as JOINs if multiple unique aliases
        if len(unique_quad_aliases) > 1:
            # OPTIMIZATION: Only create JOINs for truly unique aliases
            # Build a mapping from unique aliases back to their original triples for JOIN logic
            alias_to_triple_indices = {}
            for idx, alias in enumerate(quad_aliases):
                if alias not in alias_to_triple_indices:
                    alias_to_triple_indices[alias] = []
                alias_to_triple_indices[alias].append(idx)
            
            for i in range(1, len(unique_quad_aliases)):
                current_alias = unique_quad_aliases[i]
                # Get the first triple index that uses this alias
                current_triple_indices = alias_to_triple_indices[current_alias]
                current_triple_idx = current_triple_indices[0]
                current_triple = triples[current_triple_idx]
                current_vars = {var for var in current_triple if isinstance(var, Variable)}
                
                best_join_conditions = []
                best_reference_alias = None
                
                # Check against all previous unique aliases to find the best join
                for j in range(i):
                    ref_alias = unique_quad_aliases[j]
                    ref_triple_indices = alias_to_triple_indices[ref_alias]
                    
                    # Check all triples that use this reference alias
                    for ref_triple_idx in ref_triple_indices:
                        ref_triple = triples[ref_triple_idx]
                        ref_vars = {var for var in ref_triple if isinstance(var, Variable)}
                        shared_vars = current_vars & ref_vars
                        
                        if shared_vars:
                            join_conditions = []
                            for var in shared_vars:
                                # Find the position of this variable in both triples
                                current_position = None
                                ref_position = None
                                
                                # Find variable position in current triple
                                if current_triple[0] == var:
                                    current_position = "subject_uuid"
                                elif current_triple[1] == var:
                                    current_position = "predicate_uuid"
                                elif current_triple[2] == var:
                                    current_position = "object_uuid"
                                
                                # Find variable position in reference triple
                                if ref_triple[0] == var:
                                    ref_position = "subject_uuid"
                                elif ref_triple[1] == var:
                                    ref_position = "predicate_uuid"
                                elif ref_triple[2] == var:
                                    ref_position = "object_uuid"
                                
                                # Create JOIN condition based on positions
                                if current_position and ref_position:
                                    join_conditions.append(f"{current_alias}.{current_position} = {ref_alias}.{ref_position}")
                            
                            if len(join_conditions) > len(best_join_conditions):
                                best_join_conditions = join_conditions
                                best_reference_alias = ref_alias
                
                if best_join_conditions:
                    quad_joins.append(f"JOIN {table_config.quad_table} {current_alias} ON {' AND '.join(best_join_conditions)}")
                    logger.debug(f"Added optimized JOIN: {current_alias} -> {best_reference_alias} on {len(best_join_conditions)} conditions")
                else:
                    # No shared variables - use CROSS JOIN
                    quad_joins.append(f"CROSS JOIN {table_config.quad_table} {current_alias}")
                    logger.debug(f"Added CROSS JOIN for {current_alias} (no shared variables)")
    
    # Combine quad JOINs first, then term JOINs - exact logic from original
    combined_joins = quad_joins + all_joins
    
    return SQLComponents(
        from_clause=from_clause,
        where_conditions=where_conditions,
        joins=all_joins,
        variable_mappings=variable_mappings
    )


async def _get_single_term_uuid(term, term_cache, space_impl, table_config):
    """Get UUID for a single term using the batch lookup function with error handling"""
    if not term_cache or not space_impl:
        return None
    
    try:
        # Import the batch function
        from .postgresql_sparql_cache_integration import get_term_uuids_batch
        
        # Get term info
        term_text, term_type = SparqlUtils.get_term_info(term)
        
        # Use batch lookup for single term
        result = await get_term_uuids_batch([(term_text, term_type)], table_config, term_cache, space_impl)
        
        return result.get((term_text, term_type))
    except Exception as e:
        # Handle missing tables, connection errors, etc. gracefully
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"⚠️ Term UUID lookup failed for {term}: {e}")
        return None





def generate_term_lookup_sql(terms: List[Tuple[str, str]], table_config: TableConfig, *, sparql_context: SparqlContext = None) -> str:
    """
    Generate SQL for term lookup operations.
    
    Args:
        terms: List of (term_text, term_type) tuples to look up
        table_config: Table configuration
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        SQL query string for term lookup
    """
    function_name = "generate_term_lookup_sql"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, num_terms=len(terms) if terms else 0)
    else:
        logger = logging.getLogger(__name__)
    logger = logging.getLogger(__name__)
    logger.debug(f"Generating term lookup SQL for {len(terms)} terms")
    
    if not terms:
        return f"SELECT term_uuid, term_text, term_type FROM {table_config.term_table} WHERE 1=0"
    
    # Build WHERE conditions for each term
    conditions = []
    for term_text, term_type in terms:
        escaped_text = term_text.replace("'", "''")
        conditions.append(f"(term_text = '{escaped_text}' AND term_type = '{term_type}')")
    
    where_clause = " OR ".join(conditions)
    
    return f"""
        SELECT term_uuid, term_text, term_type 
        FROM {table_config.term_table} 
        WHERE {where_clause}
    """


def build_join_conditions(shared_vars: Set[Variable], left_mappings: Dict[Variable, str], 
                         right_mappings: Dict[Variable, str]) -> List[str]:
    """
    Build JOIN conditions for shared variables between two patterns.
    
    Args:
        shared_vars: Set of variables shared between patterns
        left_mappings: Variable mappings from left pattern
        right_mappings: Variable mappings from right pattern
        
    Returns:
        List of JOIN condition strings
    """
    join_conditions = []
    
    for var in shared_vars:
        if var in left_mappings and var in right_mappings:
            left_col = left_mappings[var]
            right_col = right_mappings[var]
            join_conditions.append(f"{left_col} = {right_col}")
    
    return join_conditions


def extract_term_info(term) -> Tuple[str, str]:
    """
    Extract term text and type from RDFLib term.
    
    Args:
        term: RDFLib term (URIRef, Literal, BNode, Variable)
        
    Returns:
        Tuple of (term_text, term_type) where term_type is 'U', 'L', or 'B'
    """
    return SparqlUtils.get_term_info(term)


def convert_rdflib_term_to_sql(term) -> str:
    """
    Convert RDFLib term to SQL literal value.
    
    Args:
        term: RDFLib term to convert
        
    Returns:
        SQL-safe literal string
    """
    return SparqlUtils.convert_rdflib_term_to_sql(term)


def optimize_sql_components(sql_components: SQLComponents, *, sparql_context: SparqlContext = None) -> SQLComponents:
    """
    Apply optimizations to SQL components.
    
    Args:
        sql_components: SQL components to optimize
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        Optimized SQL components
    """
    function_name = "optimize_sql_components"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, 
                                         num_joins=len(sql_components.joins),
                                         num_where_conditions=len(sql_components.where_conditions))
    else:
        logger = logging.getLogger(__name__)
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


def merge_variable_mappings(left_mappings: Dict[Variable, str], 
                           right_mappings: Dict[Variable, str]) -> Dict[Variable, str]:
    """
    Merge variable mappings from two patterns, preferring left mappings for conflicts.
    
    Args:
        left_mappings: Variable mappings from left pattern
        right_mappings: Variable mappings from right pattern
        
    Returns:
        Merged variable mappings
    """
    merged = left_mappings.copy()
    
    for var, mapping in right_mappings.items():
        if var not in merged:
            merged[var] = mapping
    
    return merged


def build_term_insertion_sql(terms: List[Tuple[str, str]], table_config: TableConfig, *, sparql_context: SparqlContext = None) -> str:
    """
    Build SQL for inserting terms into the term table.
    
    Args:
        terms: List of (term_text, term_type) tuples to insert
        table_config: Table configuration
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        SQL INSERT statement
    """
    function_name = "build_term_insertion_sql"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, num_terms=len(terms) if terms else 0)
    else:
        logger = logging.getLogger(__name__)
    if not terms:
        return ""
    
    # Build VALUES clause
    value_tuples = []
    for term_text, term_type in terms:
        escaped_text = term_text.replace("'", "''")
        value_tuples.append(f"('{escaped_text}', '{term_type}')")
    
    values_clause = ", ".join(value_tuples)
    
    return f"""
        INSERT INTO {table_config.term_table} (term_text, term_type)
        VALUES {values_clause}
        ON CONFLICT (term_text, term_type) DO NOTHING
    """


def validate_sql_components(sql_components: SQLComponents, *, sparql_context: SparqlContext = None) -> bool:
    """
    Validate that SQL components are well-formed.
    
    Args:
        sql_components: SQLComponents to validate
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        True if components are valid
    """
    function_name = "validate_sql_components"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name)
    else:
        logger = logging.getLogger(__name__)
    logger = logging.getLogger(__name__)
    
    # Check for required FROM clause if there are WHERE conditions or JOINs
    if (sql_components.where_conditions or sql_components.joins) and not sql_components.from_clause:
        logger.warning("SQL components have WHERE/JOIN conditions but no FROM clause")
        return False
    
    # Check that variable mappings reference valid column expressions
    for var, mapping in sql_components.variable_mappings.items():
        if not mapping or not isinstance(mapping, str):
            logger.warning(f"Invalid variable mapping for {var}: {mapping}")
            return False
    
    return True


def estimate_sql_complexity(sql_components: SQLComponents, *, sparql_context: SparqlContext = None) -> int:
    """
    Estimate the complexity of SQL components.
    
    Args:
        sql_components: SQL components to analyze
        sparql_context: SparqlContext for logging and configuration (optional)
        
    Returns:
        Complexity score (higher = more complex)
    """
    function_name = "estimate_sql_complexity"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name)
    else:
        logger = logging.getLogger(__name__)
    complexity = 1
    
    # Add complexity for variables
    complexity += len(sql_components.variable_mappings)
    
    # Add complexity for JOINs
    complexity += len(sql_components.joins) * 2
    
    # Add complexity for WHERE conditions
    complexity += len(sql_components.where_conditions)
    
    # Add complexity for subqueries (detected by SELECT in FROM clause)
    if sql_components.from_clause and 'SELECT' in sql_components.from_clause.upper():
        complexity += 5
    
    return complexity


def create_empty_sql_components() -> SQLComponents:
    """
    Create empty SQL components for initialization.
    
    Returns:
        Empty SQLComponents instance
    """
    return SQLComponents(
        from_clause="",
        where_conditions=[],
        joins=[],
        variable_mappings={}
    )
    
    # Remove duplicate conditions and joins
    unique_where = list(dict.fromkeys(components.where_conditions))
    unique_joins = list(dict.fromkeys(components.joins))
    
    return SQLComponents(
        from_clause=components.from_clause.strip(),
        where_conditions=unique_where,
        joins=unique_joins,
        variable_mappings=components.variable_mappings
    )


def extract_term_info(term) -> Tuple[str, str]:
    """
    Extract term text and type from RDFLib term.
    
    Args:
        term: RDFLib term (URIRef, Literal, BNode, Variable)
        
    Returns:
        Tuple of (term_text, term_type) where term_type is 'U', 'L', or 'B'
    """
    if isinstance(term, URIRef):
        return (str(term), 'U')
    elif isinstance(term, Literal):
        return (str(term), 'L')
    elif isinstance(term, BNode):
        return (str(term), 'B')
    elif isinstance(term, Variable):
        return (str(term), 'V')  # Variable marker
    else:
        # Fallback for unknown term types
        return (str(term), 'U')


def convert_rdflib_term_to_sql(term) -> str:
    """
    Convert RDFLib term to SQL literal value.
    
    Args:
        term: RDFLib term to convert
        
    Returns:
        SQL-safe literal string
    """
    if isinstance(term, URIRef):
        # URIs as strings with proper escaping
        uri_str = str(term).replace("'", "''")
        return f"'{uri_str}'"
    elif isinstance(term, Literal):
        # Literals as strings with proper escaping
        literal_str = str(term).replace("'", "''")
        return f"'{literal_str}'"
    elif isinstance(term, BNode):
        # Blank nodes as strings
        bnode_str = str(term).replace("'", "''")
        return f"'{bnode_str}'"
    else:
        # Fallback for unknown types
        fallback_str = str(term).replace("'", "''")
        return f"'{fallback_str}'"


def validate_sql_components(components: SQLComponents) -> bool:
    """
    Validate that SQL components are well-formed.
    
    Args:
        components: SQLComponents to validate
        
    Returns:
        True if components are valid
    """
    # TODO: Implement comprehensive SQL component validation
    logger = logging.getLogger(__name__)
    
    try:
        # Basic validation checks
        if not isinstance(components.from_clause, str):
            logger.error("FROM clause must be a string")
            return False
        
        if not isinstance(components.where_conditions, list):
            logger.error("WHERE conditions must be a list")
            return False
        
        if not isinstance(components.joins, list):
            logger.error("JOINs must be a list")
            return False
        
        if not isinstance(components.variable_mappings, dict):
            logger.error("Variable mappings must be a dictionary")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"Error validating SQL components: {e}")
        return False
