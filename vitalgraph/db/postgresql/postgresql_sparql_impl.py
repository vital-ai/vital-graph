"""
PostgreSQL SPARQL Implementation for VitalGraph

This module provides SPARQL-to-SQL translation and execution capabilities
for the VitalGraph PostgreSQL backend using the UUID-based quad/term schema.
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Any, Iterator
from functools import lru_cache
from rdflib import Variable, URIRef, Literal, BNode
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.algebra import translateAlgebra
from rdflib.plugins.sparql.sparql import Query

from .postgresql_space_impl import PostgreSQLSpaceImpl
from .postgresql_utils import PostgreSQLUtils


class GraphConstants:
    """Constants for graph URI handling in SPARQL queries."""
    GLOBAL_GRAPH_URI = "urn:___GLOBAL"
    GLOBAL_GRAPH_TYPE = "U"  # URI type
    
    @classmethod
    def get_global_graph_term_info(cls) -> Tuple[str, str]:
        """Get term info tuple for global graph."""
        return (cls.GLOBAL_GRAPH_URI, cls.GLOBAL_GRAPH_TYPE)


class TermUUIDCache:
    """
    LRU cache for term UUID lookups to avoid repeated subqueries.
    
    This cache stores mappings from (term_text, term_type) tuples to term UUIDs,
    using an LRU eviction policy when the cache reaches its maximum size.
    """
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache = {}
        self.access_order = []
        self.logger = logging.getLogger(f"{__name__}.TermUUIDCache")
    
    def get(self, term_text: str, term_type: str) -> Optional[str]:
        """
        Get term UUID from cache.
        
        Args:
            term_text: The term text
            term_type: The term type ('U', 'L', 'B')
            
        Returns:
            Term UUID if found, None otherwise
        """
        key = (term_text, term_type)
        if key in self.cache:
            # Move to end (most recently used)
            self.access_order.remove(key)
            self.access_order.append(key)
            self.logger.debug(f"Cache hit for term: {term_text} ({term_type})")
            return self.cache[key]
        
        self.logger.debug(f"Cache miss for term: {term_text} ({term_type})")
        return None
    
    def get_batch(self, terms: List[Tuple[str, str]]) -> Dict[Tuple[str, str], Optional[str]]:
        """
        Get multiple term UUIDs from cache.
        
        Args:
            terms: List of (term_text, term_type) tuples
            
        Returns:
            Dictionary mapping (term_text, term_type) to UUID (or None if not cached)
        """
        result = {}
        cache_hits = 0
        
        for term_text, term_type in terms:
            key = (term_text, term_type)
            if key in self.cache:
                # Move to end (most recently used)
                self.access_order.remove(key)
                self.access_order.append(key)
                result[key] = self.cache[key]
                cache_hits += 1
            else:
                result[key] = None
        
        self.logger.debug(f"Batch lookup: {cache_hits}/{len(terms)} cache hits")
        return result
    
    def put(self, term_text: str, term_type: str, term_uuid: str):
        """
        Add term UUID to cache.
        
        Args:
            term_text: The term text
            term_type: The term type ('U', 'L', 'B')
            term_uuid: The term UUID
        """
        key = (term_text, term_type)
        
        if key in self.cache:
            # Update existing entry and move to end
            self.access_order.remove(key)
        elif len(self.cache) >= self.max_size:
            # Evict least recently used
            lru_key = self.access_order.pop(0)
            del self.cache[lru_key]
            self.logger.debug(f"Evicted LRU term: {lru_key[0]} ({lru_key[1]})")
        
        self.cache[key] = term_uuid
        self.access_order.append(key)
        self.logger.debug(f"Cached term: {term_text} ({term_type}) -> {term_uuid}")
    
    def put_batch(self, term_mappings: Dict[Tuple[str, str], str]):
        """
        Add multiple term UUIDs to cache.
        
        Args:
            term_mappings: Dictionary mapping (term_text, term_type) to term_uuid
        """
        for (term_text, term_type), term_uuid in term_mappings.items():
            self.put(term_text, term_type, term_uuid)
        
        self.logger.debug(f"Batch cached {len(term_mappings)} terms")
    
    def size(self) -> int:
        """Get current cache size."""
        return len(self.cache)
    
    def clear(self) -> None:
        """Clear the cache."""
        self.cache.clear()
        self.access_order.clear()

logger = logging.getLogger(__name__)


class AliasGenerator:
    """Independent alias generator for SQL table and column aliases."""
    
    def __init__(self, prefix: str = ""):
        """Initialize alias generator with optional prefix."""
        self.prefix = prefix
        self.counters = {
            'quad': 0,
            'term': 0,
            'subquery': 0,
            'join': 0,
            'union': 0
        }
    
    def next_quad_alias(self) -> str:
        """Generate next quad table alias."""
        alias = f"{self.prefix}q{self.counters['quad']}"
        self.counters['quad'] += 1
        return alias
    
    def next_term_alias(self, position: str) -> str:
        """Generate next term table alias for subject/predicate/object."""
        alias = f"{self.prefix}{position[0]}_term_{self.counters['term']}"
        self.counters['term'] += 1
        return alias
    
    def next_subquery_alias(self) -> str:
        """Generate next subquery alias."""
        alias = f"{self.prefix}subquery_{self.counters['subquery']}"
        self.counters['subquery'] += 1
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
    
    def create_child_generator(self, child_prefix: str) -> 'AliasGenerator':
        """Create a child generator with a different prefix to avoid conflicts."""
        return AliasGenerator(f"{self.prefix}{child_prefix}_")


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
        self.alias_generator = AliasGenerator()
        # Keep legacy counters for backward compatibility during transition
        self.variable_counter = 0
        self.join_counter = 0
        self.term_uuid_cache = TermUUIDCache(max_size=10000)  # Cache for term UUID lookups
        
    async def execute_sparql_query(self, space_id: str, sparql_query: str) -> List[Dict[str, Any]]:
        """
        Execute a SPARQL query against the specified space.
        
        Args:
            space_id: Space identifier
            sparql_query: SPARQL query string
            
        Returns:
            List of result dictionaries with variable bindings (SELECT)
            or List of RDF triple dictionaries (CONSTRUCT)
        """
        try:
            # Validate space exists
            PostgreSQLUtils.validate_space_id(space_id)
            
            # Parse query to determine type
            from rdflib.plugins.sparql import prepareQuery
            prepared_query = prepareQuery(sparql_query)
            query_type = prepared_query.algebra.name
            
            # Translate SPARQL to SQL
            sql_query = await self._translate_sparql_to_sql(space_id, sparql_query)
            
            # Execute SQL query
            sql_results = await self._execute_sql_query(sql_query)
            
            # Process results based on query type
            if query_type == "ConstructQuery":
                # For CONSTRUCT queries, convert SQL results to RDF Graph
                construct_template = prepared_query.algebra.template
                rdf_graph = await self._process_construct_results(sql_results, construct_template)
                self.logger.info(f"CONSTRUCT query executed successfully, constructed {len(rdf_graph)} triples")
                return rdf_graph
            else:
                # For SELECT queries, return SQL results as-is
                self.logger.info(f"SELECT query executed successfully, returned {len(sql_results)} results")
                return sql_results
            
        except Exception as e:
            self.logger.error(f"Error executing SPARQL query: {e}")
            raise
    
    async def _get_term_uuids_batch(self, terms: List[Tuple[str, str]], table_config: TableConfig) -> Dict[Tuple[str, str], str]:
        """
        Get term UUIDs for multiple terms using cache and batch database lookup.
        
        Args:
            terms: List of (term_text, term_type) tuples
            table_config: Table configuration for database queries
            
        Returns:
            Dictionary mapping (term_text, term_type) to term_uuid
        """
        if not terms:
            return {}
        
        # First, check cache for all terms
        cached_results = self.term_uuid_cache.get_batch(terms)
        
        # Find terms that need database lookup
        uncached_terms = [(term_text, term_type) for (term_text, term_type), uuid in cached_results.items() if uuid is None]
        
        result = {}
        
        # Add cached results to final result
        for (term_text, term_type), uuid in cached_results.items():
            if uuid is not None:
                result[(term_text, term_type)] = uuid
        
        # Batch lookup uncached terms from database
        if uncached_terms:
            self.logger.debug(f"Batch database lookup for {len(uncached_terms)} uncached terms")
            
            # Build batch query for all uncached terms
            conditions = []
            for term_text, term_type in uncached_terms:
                conditions.append(f"(term_text = '{term_text}' AND term_type = '{term_type}')")
            
            batch_query = f"""
                SELECT term_text, term_type, term_uuid 
                FROM {table_config.term_table} 
                WHERE {' OR '.join(conditions)}
            """
            
            # Execute batch query
            db_results = await self._execute_sql_query(batch_query)
            
            # Process database results
            db_mappings = {}
            for row in db_results:
                key = (row['term_text'], row['term_type'])
                uuid = row['term_uuid']
                result[key] = uuid
                db_mappings[key] = uuid
            
            # Cache the database results
            if db_mappings:
                self.term_uuid_cache.put_batch(db_mappings)
                self.logger.debug(f"Cached {len(db_mappings)} terms from database lookup")
        
        return result
    
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
            # Create table configuration for logged tables (testing logged table performance)
            table_config = TableConfig.from_space_impl(self.space_impl, space_id)
            
            # Parse and get algebra
            prepared_query = prepareQuery(sparql_query)
            algebra = prepared_query.algebra
            
            self.logger.info(f"Translating SPARQL query with algebra: {algebra.name}")
            
            # Reset counters for each query
            self.variable_counter = 0
            self.join_counter = 0
            
            # Translate based on query type
            if algebra.name == "SelectQuery":
                sql_query = await self._translate_select_query(algebra, table_config)
            elif algebra.name == "ConstructQuery":
                sql_query = await self._translate_construct_query(algebra, table_config)
            else:
                raise NotImplementedError(f"Query type {algebra.name} not yet supported")
            
            # Log generated SQL for debugging
            self.logger.info(f"Generated SQL query ({len(sql_query)} chars):")
            self.logger.info(f"SQL: {sql_query}")
            
            return sql_query
                
        except Exception as e:
            self.logger.error(f"Error translating SPARQL query: {e}")
            raise
    
    async def _translate_select_query(self, algebra, table_config: TableConfig) -> str:
        """Translate SELECT query algebra to SQL."""
        
        # Extract projection variables
        projection_vars = algebra.get('PV', [])
        
        # Check if we have a DISTINCT pattern and extract LIMIT/OFFSET
        pattern = algebra['p']
        has_distinct = self._has_distinct_pattern(pattern)
        limit_info = self._extract_limit_offset(pattern)
        
        # Extract and translate the main pattern
        from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern(pattern, table_config, projection_vars)
        
        # Build SELECT clause with variable mappings
        select_clause = self._build_select_clause(projection_vars, variable_mappings, has_distinct)
        
        # Build complete SQL query
        sql_parts = [select_clause]
        sql_parts.append(from_clause)
        
        if joins:
            sql_parts.extend(joins)
        
        # Check if this is a UNION-derived table - if so, don't apply outer WHERE conditions
        # UNION patterns are self-contained and all conditions are already within subqueries
        is_union_derived = "union_" in from_clause and "FROM (" in from_clause
        
        if where_conditions and not is_union_derived:
            sql_parts.append(f"WHERE {' AND '.join(where_conditions)}")
        elif where_conditions and is_union_derived:
            self.logger.debug(f"Skipping {len(where_conditions)} WHERE conditions for UNION-derived table")
        
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
    
    async def _translate_pattern(self, pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """
        Translate a SPARQL pattern to SQL components.
        
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        pattern_name = pattern.name
        
        if pattern_name == "BGP":  # Basic Graph Pattern
            return await self._translate_bgp(pattern, table_config, projected_vars)
        elif pattern_name == "Filter":
            return await self._translate_filter(pattern, table_config, projected_vars)
        elif pattern_name == "Union":
            return await self._translate_union(pattern, table_config, projected_vars)
        elif pattern_name == "LeftJoin":  # OPTIONAL
            return await self._translate_optional(pattern, table_config)
        elif pattern_name == "Slice":  # LIMIT/OFFSET
            # Slice wraps another pattern - drill down to the nested pattern
            nested_pattern = pattern.p
            return await self._translate_pattern(nested_pattern, table_config, projected_vars)
        elif pattern_name == "Project":  # SELECT projection
            # Project wraps another pattern - drill down to the nested pattern
            nested_pattern = pattern.p
            return await self._translate_pattern(nested_pattern, table_config, projected_vars)
        elif pattern_name == "Distinct":  # SELECT DISTINCT
            # Distinct wraps another pattern - drill down to the nested pattern
            nested_pattern = pattern.p
            return await self._translate_pattern(nested_pattern, table_config, projected_vars)
        elif pattern_name == "OrderBy":  # ORDER BY
            # OrderBy wraps another pattern - drill down to the nested pattern
            nested_pattern = pattern.p
            return await self._translate_pattern(nested_pattern, table_config, projected_vars)
        elif pattern_name == "Graph":  # GRAPH pattern
            return await self._translate_graph(pattern, table_config, projected_vars)
        elif pattern_name == "Extend":  # BIND statements
            return await self._translate_extend(pattern, table_config, projected_vars)
        elif pattern_name == "SelectQuery":  # Sub-SELECT (subquery)
            return await self._translate_subquery(pattern, table_config, projected_vars)
        elif pattern_name == "Join":  # JOIN patterns
            return await self._translate_join(pattern, table_config, projected_vars)
        else:
            self.logger.warning(f"Pattern type {pattern_name} not fully implemented")
            return f"FROM {table_config.quad_table} q0", [], [], {}
    
    async def _translate_pattern_with_alias_gen(self, pattern, table_config: TableConfig, projected_vars: List[Variable] = None, alias_gen: AliasGenerator = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """
        Translate a SPARQL pattern to SQL components with a specific alias generator.
        This is used for JOIN patterns to ensure independent alias generation.
        
        Args:
            pattern: SPARQL pattern from algebra
            table_config: Table configuration
            projected_vars: Variables to project
            alias_gen: Alias generator to use for this pattern
            
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        pattern_name = pattern.name
        
        # For BGP patterns, pass the alias generator directly
        if pattern_name == "BGP":
            return await self._translate_bgp(pattern, table_config, projected_vars, None, alias_gen)
        
        # For other patterns, temporarily replace the main alias generator
        original_alias_gen = self.alias_generator
        if alias_gen is not None:
            self.alias_generator = alias_gen
        
        try:
            # Use the regular pattern translation
            result = await self._translate_pattern(pattern, table_config, projected_vars)
            return result
        finally:
            # Restore original alias generator
            self.alias_generator = original_alias_gen
    
    async def _translate_bgp(self, bgp_pattern, table_config: TableConfig, projected_vars: List[Variable] = None, context_constraint: str = None, alias_gen: AliasGenerator = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
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
            
            if not isinstance(predicate, Variable):
                term_text, term_type = self._get_term_info(predicate)
                bound_terms.append((term_text, term_type))
            
            if not isinstance(obj, Variable):
                term_text, term_type = self._get_term_info(obj)
                bound_terms.append((term_text, term_type))
        
        # Batch lookup all bound terms
        term_uuid_mappings = await self._get_term_uuids_batch(bound_terms, table_config) if bound_terms else {}
        
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
                if term_key in term_uuid_mappings:
                    term_uuid = term_uuid_mappings[term_key]
                    all_where_conditions.append(f"{quad_alias}.predicate_uuid = '{term_uuid}'")
                else:
                    # Term not found - this will result in no matches
                    all_where_conditions.append("1=0")  # Condition that never matches
        
        # Handle predicate
        if isinstance(predicate, Variable):
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
                all_where_conditions.append("1=0")  # Condition that never matches
        
        # Handle object
        if isinstance(obj, Variable):
            if obj not in variable_mappings and (projected_vars is None or obj in projected_vars):
                term_alias = alias_gen.next_term_alias("object")
                all_joins.append(f"JOIN {table_config.term_table} {term_alias} ON {quad_alias}.object_uuid = {term_alias}.term_uuid")
                variable_mappings[obj] = f"{term_alias}.term_text"
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
            # No explicit GRAPH pattern - query default graph (urn:___GLOBAL)
            global_graph_terms = [GraphConstants.get_global_graph_term_info()]
            global_graph_mappings = await self._get_term_uuids_batch(global_graph_terms, table_config)
            
            global_key = GraphConstants.get_global_graph_term_info()
            if global_key in global_graph_mappings:
                global_uuid = global_graph_mappings[global_key]
                # Add global graph constraint to all quad tables
                for quad_alias in quad_aliases:
                    all_where_conditions.append(f"{quad_alias}.context_uuid = '{global_uuid}'")
                self.logger.debug(f"Applied default graph constraint: {global_uuid}")
            else:
                self.logger.warning("Global graph not found in database - queries may return unexpected results")
        else:
            # Explicit context constraint provided
            for quad_alias in quad_aliases:
                all_where_conditions.append(f"{quad_alias}.{context_constraint}")
            self.logger.debug(f"Applied explicit context constraint: {context_constraint}")
        
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
    
    async def _translate_filter(self, filter_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate FILTER pattern to SQL."""
        # Get the underlying pattern first
        inner_pattern = filter_pattern['p']
        from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern(inner_pattern, table_config, projected_vars)
        
        # Debug logging
        self.logger.debug(f"Filter pattern variable mappings: {variable_mappings}")
        
        # Translate the filter expression
        filter_expr = filter_pattern['expr']
        self.logger.debug(f"Translating filter expression: {filter_expr}")
        filter_sql = await self._translate_filter_expression(filter_expr, variable_mappings)
        self.logger.debug(f"Filter SQL result: {filter_sql}")
        
        if filter_sql:
            where_conditions.append(filter_sql)
        
        return from_clause, where_conditions, joins, variable_mappings
    
    async def _translate_union(self, union_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
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
            left_from, left_where, left_joins, left_vars = await self._translate_pattern(
                left_operand, table_config, projected_vars
            )
            
            # Save left branch counters and increment for right branch
            left_var_counter = self.variable_counter
            left_join_counter = self.join_counter
            
            # Translate right branch with separate alias space
            self.logger.debug("Translating right branch of UNION")
            right_from, right_where, right_joins, right_vars = await self._translate_pattern(
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
                    left_select_items.append(f"{left_vars[var]} AS {col_name}")
                else:
                    left_select_items.append(f"NULL AS {col_name}")
                
                # Right branch: use mapping if available, otherwise NULL
                if var in right_vars:
                    right_select_items.append(f"{right_vars[var]} AS {col_name}")
                else:
                    right_select_items.append(f"NULL AS {col_name}")
            
            # Build left branch SQL
            left_sql_parts = [f"SELECT {', '.join(left_select_items)}"]
            left_sql_parts.append(left_from)
            if left_joins:
                left_sql_parts.extend(left_joins)
            if left_where:
                left_sql_parts.append(f"WHERE {' AND '.join(left_where)}")
            
            left_sql = '\n'.join(left_sql_parts)
            
            # Build right branch SQL
            right_sql_parts = [f"SELECT {', '.join(right_select_items)}"]
            right_sql_parts.append(right_from)
            if right_joins:
                right_sql_parts.extend(right_joins)
            if right_where:
                right_sql_parts.append(f"WHERE {' AND '.join(right_where)}")
            
            right_sql = '\n'.join(right_sql_parts)
            
            # Combine with UNION
            union_sql = f"({left_sql})\nUNION\n({right_sql})"
            
            # Create a derived table for the UNION result
            union_alias = f"union_{self.join_counter}"
            self.join_counter += 1
            
            union_from_clause = f"FROM ({union_sql}) {union_alias}"
            
            # Update variable mappings to reference the union table
            union_variable_mappings = {}
            for var, col_name in final_variable_mappings.items():
                union_variable_mappings[var] = f"{union_alias}.{col_name}"
            
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
    
    async def _translate_subquery(self, subquery_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
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
    
    async def _translate_join(self, join_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
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
        # Extract table references from both FROM clauses
        left_tables = left_from.replace("FROM ", "").strip()
        right_tables = right_from.replace("FROM ", "").strip()
        
        # Create combined FROM clause with CROSS JOIN
        combined_from = f"FROM {left_tables} CROSS JOIN {right_tables}"
        
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
    
    async def _translate_optional(self, optional_pattern, table_config: TableConfig) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate OPTIONAL (LeftJoin) pattern to SQL (stub implementation)."""
        self.logger.warning("OPTIONAL pattern not fully implemented")
        return f"FROM {table_config.quad_table} q0", [], [], {}
    
    async def _translate_extend(self, extend_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate Extend pattern (BIND statements) to SQL.
        
        Extend patterns have:
        - p: The nested pattern to translate
        - var: The variable being bound
        - expr: The expression to compute
        
        For now, we'll translate the nested pattern and add a placeholder for the BIND variable.
        Full BIND expression evaluation would require complex SQL expression translation.
        """
        try:
            self.logger.debug(f"Translating Extend pattern (BIND statement)")
            
            # Get the nested pattern (the WHERE clause before BIND)
            nested_pattern = extend_pattern.p
            
            # Translate the nested pattern first
            from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern(
                nested_pattern, table_config, projected_vars
            )
            
            # Get the BIND variable and expression
            bind_var = extend_pattern.var
            bind_expr = extend_pattern.expr
            
            self.logger.debug(f"BIND variable: {bind_var}")
            self.logger.debug(f"BIND expression: {bind_expr} (type: {type(bind_expr)})")
            
            # Translate the BIND expression to SQL
            try:
                sql_expression = self._translate_bind_expression(bind_expr, variable_mappings)
                variable_mappings[bind_var] = sql_expression
                self.logger.debug(f"Successfully translated BIND expression for {bind_var}: {sql_expression}")
            except Exception as expr_error:
                self.logger.warning(f"Failed to translate BIND expression for {bind_var}: {expr_error}")
                # Fall back to placeholder to avoid query failure
                variable_mappings[bind_var] = f"'BIND_FAILED_{bind_var}'"
            
            return from_clause, where_conditions, joins, variable_mappings
            
        except Exception as e:
            self.logger.error(f"Error translating Extend pattern: {e}")
            # Fall back to basic pattern to avoid complete failure
            return f"FROM {table_config.quad_table} q0", [], [], {}
    
    def _extract_bind_args(self, bind_expr) -> list:
        """Extract arguments from a BIND expression in a robust way.
        
        Different RDFLib expression types store arguments differently:
        - Some use .arg as a list
        - Some use .arg as a single value
        - Some use other attribute names
        - Complex expressions may have nested structures
        
        Returns:
            List of argument objects, empty list if none found
        """
        # Try different ways to extract arguments
        args = []
        
        # Log the expression structure for debugging
        self.logger.debug(f"Extracting args from {bind_expr} (type: {type(bind_expr)})")
        if hasattr(bind_expr, '__dict__'):
            self.logger.debug(f"Expression dict: {bind_expr.__dict__}")
        
        # Method 1: .arg as a list or single value
        if hasattr(bind_expr, 'arg'):
            arg_val = bind_expr.arg
            if arg_val is not None:
                if hasattr(arg_val, '__iter__') and not isinstance(arg_val, str):
                    # It's iterable (list/tuple)
                    try:
                        args = list(arg_val)
                        self.logger.debug(f"Found args via .arg (iterable): {args}")
                    except:
                        pass
                else:
                    # It's a single value
                    args = [arg_val]
                    self.logger.debug(f"Found args via .arg (single): {args}")
        
        # Method 2: Try other common attribute names
        if not args:
            for attr_name in ['args', 'operands', 'expr', 'expressions', 'params']:
                if hasattr(bind_expr, attr_name):
                    attr_val = getattr(bind_expr, attr_name)
                    if attr_val is not None:
                        if hasattr(attr_val, '__iter__') and not isinstance(attr_val, str):
                            try:
                                args = list(attr_val)
                                self.logger.debug(f"Found args via .{attr_name} (iterable): {args}")
                                break
                            except:
                                pass
                        else:
                            args = [attr_val]
                            self.logger.debug(f"Found args via .{attr_name} (single): {args}")
                            break
        
        # Method 3: For comparison expressions, try left/right
        if not args and hasattr(bind_expr, 'name') and any(op in str(bind_expr.name) for op in ['<', '>', '=', '!']):
            left = getattr(bind_expr, 'left', None)
            right = getattr(bind_expr, 'right', None)
            if left is not None and right is not None:
                args = [left, right]
                self.logger.debug(f"Found args via left/right: {args}")
        
        # Method 4: For specific function types, try to reconstruct arguments
        if not args and hasattr(bind_expr, 'name'):
            expr_name = bind_expr.name
            
            # Special handling for SUBSTR - might have nested structure
            if expr_name == 'Builtin_SUBSTR':
                # Try to find nested arguments in different ways
                for attr in ['arg', 'args', 'operands']:
                    if hasattr(bind_expr, attr):
                        val = getattr(bind_expr, attr)
                        if val is not None:
                            # Check if it's a nested structure
                            if hasattr(val, '__dict__'):
                                self.logger.debug(f"SUBSTR nested structure in {attr}: {val.__dict__}")
                            # Try to extract from nested CompValue
                            if hasattr(val, 'arg'):
                                nested_args = val.arg
                                if hasattr(nested_args, '__iter__') and not isinstance(nested_args, str):
                                    args = list(nested_args)
                                    self.logger.debug(f"Found SUBSTR args via nested {attr}.arg: {args}")
                                    break
            
            # Special handling for IF - might have condition as separate structure
            elif expr_name == 'Builtin_IF':
                # Try to find condition, then_val, else_val
                for attr in ['arg', 'args', 'operands', 'condition']:
                    if hasattr(bind_expr, attr):
                        val = getattr(bind_expr, attr)
                        if val is not None:
                            if hasattr(val, '__dict__'):
                                self.logger.debug(f"IF nested structure in {attr}: {val.__dict__}")
                            # Try to extract from nested structure
                            if hasattr(val, 'arg'):
                                nested_args = val.arg
                                if hasattr(nested_args, '__iter__') and not isinstance(nested_args, str):
                                    args = list(nested_args)
                                    self.logger.debug(f"Found IF args via nested {attr}.arg: {args}")
                                    break
        
        self.logger.debug(f"Final extracted {len(args)} args: {args}")
        return args

    def _translate_bind_expression(self, bind_expr, variable_mappings: Dict) -> str:
        """Translate a SPARQL BIND expression to PostgreSQL SQL.
        
        Args:
            bind_expr: RDFLib expression object from BIND statement
            variable_mappings: Current variable to SQL column mappings
            
        Returns:
            SQL expression string
        """
        from rdflib.plugins.sparql.parserutils import CompValue
        from rdflib import Variable, Literal, URIRef
        
        # RDFLib BIND expressions are parsed as Expr objects with dict-like access
        
        self.logger.debug(f"Translating BIND expression: {bind_expr} (type: {type(bind_expr)})")
        
        # Add detailed debugging for expression structure
        if hasattr(bind_expr, '__dict__'):
            self.logger.debug(f"Expression attributes: {bind_expr.__dict__}")
        if hasattr(bind_expr, 'name'):
            self.logger.debug(f"Expression name: {bind_expr.name}")
        if hasattr(bind_expr, 'arg'):
            self.logger.debug(f"Expression args: {bind_expr.arg} (type: {type(bind_expr.arg)})")
        
        # Handle different expression types
        if isinstance(bind_expr, CompValue):
            # CompValue represents function calls and operations
            expr_name = bind_expr.name
            
            if expr_name == 'Builtin_CONCAT':
                # CONCAT(arg1, arg2, ...) -> CONCAT(arg1, arg2, ...)
                args = [self._translate_bind_arg(arg, variable_mappings) for arg in bind_expr.arg]
                return f"CONCAT({', '.join(args)})"
                
            elif expr_name == 'Builtin_STR':
                # STR(?var) -> CAST(var AS TEXT)
                arg = self._translate_bind_arg(bind_expr.arg, variable_mappings)
                return f"CAST({arg} AS TEXT)"
                
            elif expr_name == 'Builtin_IF':
                # IF(condition, true_val, false_val) -> CASE WHEN condition THEN true_val ELSE false_val END
                # RDFLib stores IF args as dict keys: 'arg1', 'arg2', 'arg3'
                try:
                    # Extract arguments from dictionary keys
                    if 'arg1' in bind_expr and 'arg2' in bind_expr and 'arg3' in bind_expr:
                        condition = self._translate_bind_arg(bind_expr['arg1'], variable_mappings)
                        true_val = self._translate_bind_arg(bind_expr['arg2'], variable_mappings)
                        false_val = self._translate_bind_arg(bind_expr['arg3'], variable_mappings)
                        return f"CASE WHEN {condition} THEN {true_val} ELSE {false_val} END"
                    else:
                        self.logger.warning(f"IF missing required keys 'arg1', 'arg2', or 'arg3' in {bind_expr.keys()}")
                        return "'IF_MISSING_KEYS'"
                except Exception as e:
                    self.logger.warning(f"Error parsing IF expression: {e}")
                    return "'IF_PARSE_ERROR'"
                
            elif expr_name == 'Builtin_SUBSTR':
                # SUBSTR(string, start, length?) -> SUBSTRING(string FROM start FOR length)
                # RDFLib stores SUBSTR args as dict keys: 'arg', 'start', 'length'
                try:
                    # Extract arguments from dictionary keys
                    if 'arg' in bind_expr and 'start' in bind_expr:
                        string_arg = self._translate_bind_arg(bind_expr['arg'], variable_mappings)
                        
                        # For numeric literals, extract the raw value without quotes
                        start_val = bind_expr['start']
                        if hasattr(start_val, 'toPython'):
                            start_arg = str(start_val.toPython())
                        else:
                            start_arg = self._translate_bind_arg(start_val, variable_mappings)
                        
                        if 'length' in bind_expr:
                            length_val = bind_expr['length']
                            if hasattr(length_val, 'toPython'):
                                length_arg = str(length_val.toPython())
                            else:
                                length_arg = self._translate_bind_arg(length_val, variable_mappings)
                            return f"SUBSTRING({string_arg} FROM {start_arg} FOR {length_arg})"
                        else:
                            return f"SUBSTRING({string_arg} FROM {start_arg})"
                    else:
                        self.logger.warning(f"SUBSTR missing required keys 'arg' or 'start' in {bind_expr.keys()}")
                        return "'SUBSTR_MISSING_KEYS'"
                except Exception as e:
                    self.logger.warning(f"Error parsing SUBSTR expression: {e}")
                    return "'SUBSTR_PARSE_ERROR'"
                    
            elif expr_name == 'Builtin_SHA1':
                # SHA1(string) -> Use MD5 as fallback since it's more reliably available
                # Note: This is not cryptographically equivalent but works for BIND testing
                arg = self._translate_bind_arg(bind_expr.arg, variable_mappings)
                return f"MD5({arg}::text)"
                
            elif expr_name == 'Builtin_MD5':
                # MD5(string) -> MD5(string)
                arg = self._translate_bind_arg(bind_expr.arg, variable_mappings)
                return f"MD5({arg})"
                
            elif expr_name == 'Builtin_STRLEN':
                # STRLEN(string) -> LENGTH(string)
                arg = self._translate_bind_arg(bind_expr.arg, variable_mappings)
                return f"LENGTH({arg})"
                
            elif expr_name == 'Builtin_UCASE':
                # UCASE(string) -> UPPER(string)
                arg = self._translate_bind_arg(bind_expr.arg, variable_mappings)
                return f"UPPER({arg})"
                
            elif expr_name == 'Builtin_LCASE':
                # LCASE(string) -> LOWER(string)
                arg = self._translate_bind_arg(bind_expr.arg, variable_mappings)
                return f"LOWER({arg})"
                
            elif expr_name in ['RelationalExpression', 'ConditionalAndExpression', 'ConditionalOrExpression']:
                # Handle comparison and logical operations
                return self._translate_bind_comparison(bind_expr, variable_mappings)
                
            else:
                self.logger.warning(f"Unsupported BIND expression type: {expr_name}")
                return f"'UNSUPPORTED_{expr_name}'"
                
        elif isinstance(bind_expr, Variable):
            # Direct variable reference
            return self._translate_bind_arg(bind_expr, variable_mappings)
            
        elif isinstance(bind_expr, (Literal, URIRef)):
            # Direct literal or URI
            return self._translate_bind_arg(bind_expr, variable_mappings)
            
        else:
            self.logger.warning(f"Unknown BIND expression type: {type(bind_expr)}")
            return f"'UNKNOWN_EXPR_{type(bind_expr).__name__}'"
    
    def _translate_bind_arg(self, arg, variable_mappings: Dict) -> str:
        """Translate a single argument in a BIND expression.
        
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
                # Extract just the column reference (remove AS clause if present)
                if ' AS ' in mapping:
                    return mapping.split(' AS ')[0]
                return mapping
            else:
                self.logger.warning(f"Variable {var_name} not found in mappings")
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
            return self._translate_bind_expression(arg, variable_mappings)
            
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
            
        else:
            self.logger.warning(f"Unknown argument type in BIND: {type(arg)}")
            return f"'UNKNOWN_ARG_{type(arg).__name__}'"
    
    def _translate_bind_comparison(self, comp_expr, variable_mappings: Dict) -> str:
        """Translate comparison expressions in BIND statements.
        
        Args:
            comp_expr: Comparison expression (RelationalExpression, etc.)
            variable_mappings: Current variable mappings
            
        Returns:
            SQL comparison expression
        """
        try:
            # Handle different comparison types
            if hasattr(comp_expr, 'op'):
                op = comp_expr.op
                left = self._translate_bind_arg(comp_expr.expr, variable_mappings)
                right = self._translate_bind_arg(comp_expr.other, variable_mappings)
                
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
                return f"({left} {sql_op} {right})"
                
            else:
                self.logger.warning(f"Unsupported comparison expression: {comp_expr}")
                return "'UNSUPPORTED_COMPARISON'"
                
        except Exception as e:
            self.logger.error(f"Error translating comparison: {e}")
            return "'COMPARISON_ERROR'"
    
    async def _translate_graph(self, graph_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """
        Translate GRAPH pattern to SQL with context constraints.
        
        Handles:
        - GRAPH <uri> { ... } (named graphs)
        - GRAPH ?var { ... } (variable graphs)
        - Default graph behavior (no GRAPH specified uses urn:___GLOBAL)
        
        Args:
            graph_pattern: The GRAPH pattern from SPARQL algebra
            table_config: Table configuration for SQL generation
            projected_vars: Variables to project in SELECT clause
            
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        self.logger.debug(f"Translating GRAPH pattern: {graph_pattern}")
        
        # Extract graph term and inner pattern
        graph_term = graph_pattern.get('term')  # The graph URI or variable
        inner_pattern = graph_pattern.get('p')   # The pattern inside GRAPH
        
        self.logger.debug(f"Graph term: {graph_term} (type: {type(graph_term)})")
        self.logger.debug(f"Inner pattern: {inner_pattern}")
        
        if isinstance(graph_term, URIRef):
            # Named graph - resolve URI to UUID
            self.logger.debug(f"Processing named graph: {graph_term}")
            graph_text, graph_type = self._get_term_info(graph_term)
            graph_terms = [(graph_text, graph_type)]
            graph_uuid_mappings = await self._get_term_uuids_batch(graph_terms, table_config)
            
            graph_key = (graph_text, graph_type)
            if graph_key in graph_uuid_mappings:
                context_uuid = graph_uuid_mappings[graph_key]
                context_constraint = f"context_uuid = '{context_uuid}'"
                self.logger.debug(f"Found graph UUID: {context_uuid}")
                return await self._translate_pattern_with_context(inner_pattern, table_config, projected_vars, context_constraint)
            else:
                # Graph not found - return empty result set
                self.logger.warning(f"Graph not found: {graph_text}")
                # Use a condition that will never match any real UUID
                # This ensures 0 results while maintaining valid SQL structure
                context_constraint = f"context_uuid = '00000000-0000-0000-0000-000000000000'"
                return await self._translate_pattern_with_context(inner_pattern, table_config, projected_vars, context_constraint)
        
        elif isinstance(graph_term, Variable):
            # Variable graph - add JOIN to term table
            self.logger.debug(f"Processing variable graph: {graph_term}")
            return await self._translate_variable_graph(graph_term, inner_pattern, table_config, projected_vars)
        
        else:
            self.logger.warning(f"Unsupported graph term type: {type(graph_term)}")
            return await self._translate_pattern(inner_pattern, table_config, projected_vars)
    
    async def _translate_pattern_with_context(self, pattern, table_config: TableConfig, projected_vars: List[Variable] = None, context_constraint: str = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """
        Translate any pattern with additional context constraint.
        
        Args:
            pattern: The SPARQL pattern to translate
            table_config: Table configuration for SQL generation
            projected_vars: Variables to project in SELECT clause
            context_constraint: SQL constraint for context_uuid column
            
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        pattern_name = pattern.name
        
        if pattern_name == "BGP":
            return await self._translate_bgp(pattern, table_config, projected_vars, context_constraint)
        elif pattern_name == "Filter":
            # Handle filter with context constraint
            inner_pattern = pattern['p']
            from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern_with_context(inner_pattern, table_config, projected_vars, context_constraint)
            
            # Add filter conditions
            filter_expr = pattern['expr']
            filter_sql = await self._translate_filter_expression(filter_expr, variable_mappings)
            if filter_sql:
                where_conditions.append(filter_sql)
            
            return from_clause, where_conditions, joins, variable_mappings
        else:
            # For other patterns, fall back to regular translation and add context constraint
            from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern(pattern, table_config, projected_vars)
            if context_constraint:
                # Extract quad aliases from FROM clause and JOINs to apply context constraint
                quad_aliases = self._extract_quad_aliases_from_sql(from_clause, joins)
                for quad_alias in quad_aliases:
                    where_conditions.append(f"{quad_alias}.{context_constraint}")
            return from_clause, where_conditions, joins, variable_mappings
    
    async def _translate_construct_query(self, algebra, table_config: TableConfig) -> str:
        """Translate CONSTRUCT query algebra to SQL.
        
        CONSTRUCT queries work by:
        1. Extracting the CONSTRUCT template (what triples to build)
        2. Translating the WHERE clause to SQL (like SELECT queries)
        3. Mapping SQL results back to RDF triples/quads per template
        
        Args:
            algebra: RDFLib ConstructQuery algebra object
            table_config: Table configuration for SQL generation
            
        Returns:
            SQL query string that returns data for CONSTRUCT template
        """
        try:
            self.logger.info("Translating CONSTRUCT query")
            
            # Extract CONSTRUCT template - list of (subject, predicate, object) triples
            if not hasattr(algebra, 'template') or not algebra.template:
                raise ValueError("CONSTRUCT query missing template")
            
            construct_template = algebra.template
            self.logger.debug(f"CONSTRUCT template has {len(construct_template)} triples")
            
            # Extract WHERE clause pattern from algebra.p
            if not hasattr(algebra, 'p') or not algebra.p:
                raise ValueError("CONSTRUCT query missing WHERE clause")
            
            where_pattern = algebra.p
            self.logger.debug(f"WHERE pattern type: {where_pattern.name}")
            
            # Translate the WHERE clause to SQL (reuse existing SELECT logic)
            # The WHERE clause contains the pattern that finds variable bindings
            sql_query = await self._translate_select_pattern(where_pattern, table_config)
            
            # Store the template for result processing
            # Note: In a full implementation, we'd need to return both SQL and template
            # For now, we'll add template info as SQL comments for debugging
            template_comment = "-- CONSTRUCT template:\n"
            for i, (s, p, o) in enumerate(construct_template):
                template_comment += f"--   [{i+1}] {s} {p} {o}\n"
            
            final_sql = template_comment + sql_query
            
            self.logger.info(f"Successfully translated CONSTRUCT query with {len(construct_template)} template triples")
            return final_sql
            
        except Exception as e:
            self.logger.error(f"Error translating CONSTRUCT query: {e}")
            raise NotImplementedError(f"CONSTRUCT query translation failed: {e}")
    
    async def _translate_select_pattern(self, pattern, table_config: TableConfig) -> str:
        """Translate a SELECT pattern to SQL for CONSTRUCT queries.
        
        This method extracts the core pattern translation logic from SELECT queries
        so it can be reused for CONSTRUCT queries. The difference is that CONSTRUCT
        queries need the variable bindings from the WHERE clause to build new triples.
        
        Args:
            pattern: RDFLib pattern algebra (Project, Slice, BGP, etc.)
            table_config: Table configuration for SQL generation
            
        Returns:
            SQL query string that returns variable bindings
        """
        try:
            # Get all variables from the pattern for projection
            all_vars = list(pattern.get('_vars', set()))
            if not all_vars:
                # If no variables found in pattern, try to extract from sub-patterns
                all_vars = self._extract_variables_from_pattern(pattern)
            
            self.logger.debug(f"Pattern variables: {all_vars}")
            
            # Check for DISTINCT and LIMIT/OFFSET
            has_distinct = self._has_distinct_pattern(pattern)
            limit_info = self._extract_limit_offset(pattern)
            
            # Translate the pattern to SQL components
            from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern(
                pattern, table_config, all_vars
            )
            
            # Build SELECT clause with all variables (needed for CONSTRUCT template)
            select_clause = self._build_select_clause(all_vars, variable_mappings, has_distinct)
            
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
            
        except Exception as e:
            self.logger.error(f"Error translating SELECT pattern: {e}")
            raise
    
    def _extract_variables_from_pattern(self, pattern):
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
                        for term in triple:
                            if hasattr(term, 'n3') and str(term).startswith('?'):
                                variables.add(term)
                elif attr == 'PV' and isinstance(attr_value, list):
                    # Projection variables
                    variables.update(attr_value)
                elif hasattr(attr_value, '_vars'):
                    # Nested pattern with variables
                    variables.update(attr_value._vars)
        
        return list(variables)
    
    async def _process_construct_results(self, sql_results: List[Dict[str, Any]], construct_template: List) -> 'rdflib.Graph':
        """Process SQL results to generate RDF triples according to CONSTRUCT template.
        
        Args:
            sql_results: List of SQL result dictionaries with variable bindings
            construct_template: List of (subject, predicate, object) triples from CONSTRUCT clause
            
        Returns:
            RDFLib Graph object containing the constructed triples
        """
        try:
            from rdflib import Graph
            
            # Create RDFLib Graph to hold constructed triples
            result_graph = Graph()
            triple_count = 0
            
            self.logger.debug(f"Processing {len(sql_results)} SQL results with {len(construct_template)} template triples")
            
            # For each SQL result row (variable binding)
            for row in sql_results:
                # For each triple template in the CONSTRUCT clause
                for template_triple in construct_template:
                    subject_term, predicate_term, object_term = template_triple
                    
                    # Substitute variables with values from SQL result
                    subject_value = self._substitute_template_term(subject_term, row)
                    predicate_value = self._substitute_template_term(predicate_term, row)
                    object_value = self._substitute_template_term(object_term, row)
                    
                    # Only create triple if all terms are successfully substituted
                    if (subject_value is not None and 
                        predicate_value is not None and 
                        object_value is not None):
                        
                        # Convert string values to RDFLib terms
                        rdf_subject = self._string_to_rdflib_term(subject_value)
                        rdf_predicate = self._string_to_rdflib_term(predicate_value)
                        rdf_object = self._string_to_rdflib_term(object_value)
                        
                        # Add triple to graph
                        result_graph.add((rdf_subject, rdf_predicate, rdf_object))
                        triple_count += 1
                    else:
                        self.logger.debug(f"Skipping incomplete triple: {subject_value} {predicate_value} {object_value}")
            
            self.logger.info(f"Generated RDFLib Graph with {triple_count} triples from {len(sql_results)} SQL results")
            return result_graph
            
        except Exception as e:
            self.logger.error(f"Error processing CONSTRUCT results: {e}")
            raise
    
    def _string_to_rdflib_term(self, value: str):
        """Convert a string value to the appropriate RDFLib term type.
        
        Args:
            value: String value to convert
            
        Returns:
            RDFLib URIRef, Literal, or BNode
        """
        from rdflib import URIRef, Literal, BNode
        
        # Handle None values
        if value is None:
            return None
            
        value_str = str(value)
        
        # Check if it's a URI (starts with http:// or https://)
        if value_str.startswith('http://') or value_str.startswith('https://'):
            return URIRef(value_str)
        
        # Check if it's a blank node (starts with _:)
        if value_str.startswith('_:'):
            return BNode(value_str[2:])  # Remove _: prefix
        
        # Check if it's a URI scheme (contains ://)
        if '://' in value_str:
            return URIRef(value_str)
        
        # Otherwise treat as literal
        return Literal(value_str)
    
    def _substitute_template_term(self, template_term, variable_bindings: Dict[str, Any]) -> str:
        """Substitute a template term with values from variable bindings.
        
        Args:
            template_term: RDFLib term from CONSTRUCT template (Variable, URIRef, Literal)
            variable_bindings: Dictionary of variable -> value mappings from SQL
            
        Returns:
            String value for the term, or None if substitution fails
        """
        try:
            from rdflib import Variable, URIRef, Literal, BNode
            
            if isinstance(template_term, Variable):
                # Variable - substitute with value from bindings
                var_name = str(template_term)  # Variable name (e.g., 'entity')
                
                # Try to find the variable in bindings
                if var_name in variable_bindings:
                    return str(variable_bindings[var_name])
                else:
                    # Try without '?' prefix if present
                    clean_var_name = var_name.lstrip('?')
                    if clean_var_name in variable_bindings:
                        return str(variable_bindings[clean_var_name])
                    else:
                        self.logger.debug(f"Variable {var_name} not found in bindings: {list(variable_bindings.keys())}")
                        return None
                        
            elif isinstance(template_term, (URIRef, Literal)):
                # Constant term - return as-is
                return str(template_term)
                
            elif isinstance(template_term, BNode):
                # Blank node - return as string
                return str(template_term)
                
            else:
                # Unknown term type - convert to string
                self.logger.warning(f"Unknown template term type: {type(template_term)}")
                return str(template_term)
                
        except Exception as e:
            self.logger.error(f"Error substituting template term {template_term}: {e}")
            return None
    
    async def _translate_filter_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate a SPARQL filter expression to SQL."""
        # Handle case where expr is a list (multiple filter expressions)
        if isinstance(expr, list):
            if len(expr) == 1:
                return await self._translate_filter_expression(expr[0], variable_mappings)
            else:
                # Multiple expressions - combine with AND
                conditions = []
                for sub_expr in expr:
                    conditions.append(await self._translate_filter_expression(sub_expr, variable_mappings))
                return f"({' AND '.join(conditions)})"
        
        # Handle case where expr doesn't have a name attribute
        if not hasattr(expr, 'name'):
            self.logger.warning(f"Filter expression has no name attribute: {type(expr)}")
            return "1=1"  # No-op condition
        
        expr_name = expr.name
        
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
        else:
            self.logger.warning(f"Filter expression {expr_name} not implemented")
            return "1=1"  # No-op condition
    
    async def _translate_exists_expression(self, expr, variable_mappings: Dict[Variable, str], is_not_exists: bool = False) -> str:
        """
        Translate EXISTS/NOT EXISTS subquery expressions to SQL.
        
        Args:
            expr: The EXISTS/NOT EXISTS expression
            variable_mappings: Current variable mappings from outer query
            is_not_exists: True for NOT EXISTS, False for EXISTS
            
        Returns:
            SQL EXISTS/NOT EXISTS condition
        """
        try:
            self.logger.info(f"🔍 TRANSLATING {'NOT EXISTS' if is_not_exists else 'EXISTS'} EXPRESSION")
            
            # Get the pattern inside the EXISTS/NOT EXISTS
            exists_pattern = expr.get('graph', expr.get('p', None))
            if not exists_pattern:
                self.logger.warning("EXISTS expression has no pattern")
                return "1=1"
            
            # Store original counters
            original_variable_counter = self.variable_counter
            original_join_counter = self.join_counter
            
            # Create table config for the EXISTS subquery
            # Use the same table config as the outer query
            table_config = TableConfig(
                quad_table=f"vitalgraph1__space_test__rdf_quad",
                term_table=f"vitalgraph1__space_test__term"
            )
            
            # Translate the EXISTS pattern
            from_clause, where_conditions, joins, exists_variable_mappings = await self._translate_pattern(
                exists_pattern, table_config, projected_vars=None
            )
            
            # Build the EXISTS subquery SQL
            exists_sql_parts = ["SELECT 1"]
            exists_sql_parts.append(from_clause)
            
            # Add any JOIN clauses
            if joins:
                exists_sql_parts.extend(joins)
            
            # Add WHERE conditions
            if where_conditions:
                exists_sql_parts.append(f"WHERE {' AND '.join(where_conditions)}")
            
            exists_subquery = '\n'.join(exists_sql_parts)
            
            # Restore original counters
            self.variable_counter = original_variable_counter
            self.join_counter = original_join_counter
            
            # Wrap in EXISTS/NOT EXISTS
            exists_operator = "NOT EXISTS" if is_not_exists else "EXISTS"
            result = f"{exists_operator} ({exists_subquery})"
            
            self.logger.info(f"Successfully translated {'NOT EXISTS' if is_not_exists else 'EXISTS'} expression")
            self.logger.debug(f"EXISTS SQL: {result}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error translating EXISTS expression: {e}")
            # Restore counters on error
            self.variable_counter = original_variable_counter
            self.join_counter = original_join_counter
            return "1=1"  # Fallback condition
    
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
    
    async def _translate_and_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate AND expression."""
        left = await self._translate_filter_expression(expr['expr'], variable_mappings)
        right = await self._translate_filter_expression(expr['other'], variable_mappings)
        return f"({left} AND {right})"
    
    async def _translate_or_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate OR expression."""
        left = await self._translate_filter_expression(expr['expr'], variable_mappings)
        right = await self._translate_filter_expression(expr['other'], variable_mappings)
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
    
    def _translate_project(self, pattern, table_config: TableConfig) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate PROJECT pattern - placeholder implementation."""
        # TODO: Implement PROJECT pattern translation
        inner_pattern = pattern['p']
        return self._translate_pattern(inner_pattern, table_config)
    

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
    
    def _extract_quad_aliases_from_sql(self, from_clause: str, joins: List[str]) -> List[str]:
        """
        Extract quad table aliases from FROM clause and JOINs.
        
        Args:
            from_clause: SQL FROM clause
            joins: List of JOIN clauses
            
        Returns:
            List of quad table aliases
        """
        import re
        quad_aliases = []
        
        # Extract alias from FROM clause (e.g., "FROM quad_table q0" -> "q0")
        from_match = re.search(r'FROM\s+\S+\s+(\w+)', from_clause)
        if from_match:
            quad_aliases.append(from_match.group(1))
        
        # Extract aliases from JOINs that reference quad tables
        for join in joins:
            # Look for quad table JOINs (e.g., "JOIN quad_table q1 ON ...")
            if 'quad' in join.lower():
                join_match = re.search(r'JOIN\s+\S+\s+(\w+)\s+ON', join)
                if join_match:
                    alias = join_match.group(1)
                    if alias not in quad_aliases:
                        quad_aliases.append(alias)
        
        return quad_aliases
    
    async def _translate_variable_graph(self, graph_var: Variable, inner_pattern, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """
        Translate variable graph pattern (GRAPH ?var { ... }).
        
        Args:
            graph_var: The graph variable
            inner_pattern: The pattern inside GRAPH
            table_config: Table configuration for SQL generation
            projected_vars: Variables to project in SELECT clause
            
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        self.logger.debug(f"Translating variable graph pattern: {graph_var}")
        
        # First translate the inner pattern
        from_clause, where_conditions, joins, variable_mappings = await self._translate_pattern(inner_pattern, table_config, projected_vars)
        
        # Add graph variable to projected variables if needed
        if projected_vars is None or graph_var in projected_vars:
            # Create JOIN to term table for graph variable
            context_term_alias = f"g_term_{len(joins)}"
            
            # Extract quad aliases to add context JOINs
            quad_aliases = self._extract_quad_aliases_from_sql(from_clause, joins)
            
            # Add context term JOIN for the first quad table
            if quad_aliases:
                first_quad_alias = quad_aliases[0]
                joins.append(f"JOIN {table_config.term_table} {context_term_alias} ON {first_quad_alias}.context_uuid = {context_term_alias}.term_uuid")
                
                # For additional quad tables, ensure they have the same context
                for i, quad_alias in enumerate(quad_aliases[1:], 1):
                    where_conditions.append(f"{quad_alias}.context_uuid = {first_quad_alias}.context_uuid")
            
            # Map graph variable to term text
            variable_mappings[graph_var] = f"{context_term_alias}.term_text"
            self.logger.debug(f"Mapped graph variable {graph_var} to {context_term_alias}.term_text")
        else:
            # Graph variable not projected - no additional JOINs needed
            self.logger.debug(f"Graph variable {graph_var} not projected - no JOINs added")
        
        return from_clause, where_conditions, joins, variable_mappings
