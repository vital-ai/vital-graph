"""
PostgreSQL SPARQL Cache Integration for VitalGraph

This module provides cache-integrated versions of SPARQL translation functions
that use the PostgreSQLCacheTerm for optimal performance.
"""

import logging
from typing import Dict, List, Tuple, Optional, Any
from rdflib import Variable, URIRef, Literal, BNode

from .postgresql_sparql_core import SQLComponents, AliasGenerator, TableConfig, SparqlUtils
from ..postgresql_cache_term import PostgreSQLCacheTerm

logger = logging.getLogger(__name__)


async def generate_bgp_sql_with_cache(triples: List[Tuple], table_config: TableConfig, 
                                    alias_gen: AliasGenerator, projected_vars: Optional[List[Variable]] = None,
                                    term_cache: PostgreSQLCacheTerm = None, space_impl = None, 
                                    context_constraint: str = None) -> SQLComponents:
    """
    Generate SQL components for Basic Graph Pattern (BGP) using exact logic from original implementation.
    This function ports the complete _translate_bgp method from PostgreSQLSparqlImpl.
    
    Args:
        triples: List of RDF triples (subject, predicate, object)
        table_config: Table configuration for SQL generation
        alias_gen: Alias generator for unique table aliases
        projected_vars: Variables to project (for optimization)
        term_cache: Term cache for efficient term UUID lookups
        space_impl: Space implementation for database operations
        context_constraint: Optional SQL constraint for context_uuid column (for GRAPH patterns)
        
    Returns:
        SQLComponents with FROM clause, WHERE conditions, JOINs, and variable mappings
    """
    logger.debug(f"🔍 BGP: Generating SQL with cache for {len(triples)} triples")
    
    if not triples:
        return SQLComponents(
            from_clause=f"FROM {table_config.quad_table} {alias_gen.next_quad_alias()}",
            where_conditions=[],
            joins=[],
            variable_mappings={}
        )
    
    # First pass: collect all bound terms for batch lookup - exact logic from original
    bound_terms = []
    for triple in triples:
        subject, predicate, obj = triple
        
        if not isinstance(subject, Variable):
            term_text, term_type = SparqlUtils.get_term_info(subject)
            bound_terms.append((term_text, term_type))
        
        if not isinstance(predicate, Variable):
            term_text, term_type = SparqlUtils.get_term_info(predicate)
            bound_terms.append((term_text, term_type))
        
        if not isinstance(obj, Variable):
            term_text, term_type = SparqlUtils.get_term_info(obj)
            bound_terms.append((term_text, term_type))
    
    # Batch lookup all bound terms - exact logic from original
    logger.debug(f"🔍 BGP collecting bound terms: {bound_terms}")
    term_uuid_mappings = {}
    if bound_terms and term_cache:
        logger.debug(f"Looking up {len(bound_terms)} bound terms using cache")
        
        # Check cache first
        cached_results = term_cache.get_batch(bound_terms)
        missing_terms = []
        
        for term_key in bound_terms:
            if term_key in cached_results:
                term_uuid_mappings[term_key] = cached_results[term_key]
            else:
                missing_terms.append(term_key)
        
        # Lookup missing terms from database - exact logic from original implementation
        if missing_terms:
            logger.debug(f"Cache miss for {len(missing_terms)} terms, looking up in database")
            
            # Build optimized batch query using exact logic from original _get_term_uuids_batch
            if len(missing_terms) == 1:
                # Single term - use simple equality for better readability
                term_text, term_type = missing_terms[0]
                escaped_text = term_text.replace("'", "''")
                batch_query = f"""
                    SELECT term_text, term_type, term_uuid 
                    FROM {table_config.term_table} 
                    WHERE term_text = '{escaped_text}' AND term_type = '{term_type}'
                """
            else:
                # Multiple terms - use IN clause with VALUES for better performance
                values_list = []
                for term_text, term_type in missing_terms:
                    escaped_text = term_text.replace("'", "''")
                    values_list.append(f"('{escaped_text}', '{term_type}')")
                
                batch_query = f"""
                    SELECT t.term_text, t.term_type, t.term_uuid 
                    FROM {table_config.term_table} t
                    INNER JOIN (VALUES {', '.join(values_list)}) AS v(term_text, term_type)
                        ON t.term_text = v.term_text AND t.term_type = v.term_type
                """
            
            # Execute batch query using space_impl connection - exact logic from original _execute_sql_query
            try:
                # Use the space_impl's get_connection method exactly like the original
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
                        missing_results = {}
                        for row in db_results:
                            key = (row['term_text'], row['term_type'])
                            uuid = row['term_uuid']
                            missing_results[key] = uuid
                        
                        # Update cache with newly found terms - exact logic from original
                        if missing_results:
                            term_cache.put_batch(missing_results)
                            term_uuid_mappings.update(missing_results)
                            logger.debug(f"Cached {len(missing_results)} terms from database lookup")
                    
            except Exception as e:
                logger.error(f"Error in batch database lookup: {e}")
        
        logger.debug(f"Term cache lookup complete: {len(term_uuid_mappings)} terms resolved")
    elif bound_terms and space_impl:
        # Fallback: direct database lookup without cache
        logger.debug(f"No cache available, looking up {len(bound_terms)} terms directly from database")
        
        # Use the same batch lookup logic as the original implementation
        if len(bound_terms) == 1:
            term_text, term_type = bound_terms[0]
            escaped_text = term_text.replace("'", "''")
            query = f"""
                SELECT term_uuid 
                FROM {table_config.term_table} 
                WHERE term_text = '{escaped_text}' AND term_type = '{term_type}'
            """
            
            result = await space_impl.execute_query(query)
            if result:
                term_uuid_mappings[bound_terms[0]] = result[0]['term_uuid']
        else:
            # Batch query for multiple terms
            term_conditions = []
            for term_text, term_type in bound_terms:
                escaped_text = term_text.replace("'", "''")
                term_conditions.append(f"(term_text = '{escaped_text}' AND term_type = '{term_type}')")
            
            query = f"""
                SELECT term_text, term_type, term_uuid 
                FROM {table_config.term_table} 
                WHERE {' OR '.join(term_conditions)}
            """
            
            results = await space_impl.execute_query(query)
            for row in results:
                term_key = (row['term_text'], row['term_type'])
                term_uuid_mappings[term_key] = row['term_uuid']
    
    logger.debug(f"🔍 BGP term UUID mappings: {term_uuid_mappings}")
    
    # Second pass: process each triple pattern with resolved UUIDs - exact logic from original
    all_joins = []
    quad_joins = []  # JOINs for additional quad tables
    all_where_conditions = []
    variable_mappings = {}
    quad_aliases = []
    
    for triple_idx, triple in enumerate(triples):
        subject, predicate, obj = triple
        quad_alias = alias_gen.next_quad_alias()
        quad_aliases.append(quad_alias)
        logger.debug(f"🔍 Processing triple #{triple_idx}: ({subject}, {predicate}, {obj})")
        
        # Handle subject - exact logic from original
        if isinstance(subject, Variable):
            if subject not in variable_mappings and (projected_vars is None or subject in projected_vars):
                term_alias = alias_gen.next_term_alias("subject")
                all_joins.append(f"JOIN {table_config.term_table} {term_alias} ON {quad_alias}.subject_uuid = {term_alias}.term_uuid")
                variable_mappings[subject] = f"{term_alias}.term_text"
            # Variable already mapped or not projected - don't create JOIN
        else:
            # Bound term - use resolved UUID
            term_text, term_type = SparqlUtils.get_term_info(subject)
            term_key = (term_text, term_type)
            if term_key in term_uuid_mappings:
                term_uuid = term_uuid_mappings[term_key]
                all_where_conditions.append(f"{quad_alias}.subject_uuid = '{term_uuid}'")
            else:
                # Term not found - this will result in no matches
                logger.error(f"🚨 TERM LOOKUP FAILED for subject: {term_text} (type: {term_type}) - adding 1=0 condition")
                logger.error(f"Available term mappings: {list(term_uuid_mappings.keys())[:10]}...")
                all_where_conditions.append("1=0")  # Condition that never matches
        
        # Handle predicate - exact logic from original
        if isinstance(predicate, Variable):
            if predicate not in variable_mappings and (projected_vars is None or predicate in projected_vars):
                term_alias = alias_gen.next_term_alias("predicate")
                all_joins.append(f"JOIN {table_config.term_table} {term_alias} ON {quad_alias}.predicate_uuid = {term_alias}.term_uuid")
                variable_mappings[predicate] = f"{term_alias}.term_text"
            # Variable already mapped or not projected - don't create JOIN
        else:
            # Bound term - use resolved UUID
            term_text, term_type = SparqlUtils.get_term_info(predicate)
            term_key = (term_text, term_type)
            if term_key in term_uuid_mappings:
                term_uuid = term_uuid_mappings[term_key]
                all_where_conditions.append(f"{quad_alias}.predicate_uuid = '{term_uuid}'")
            else:
                # Term not found - this will result in no matches
                logger.error(f"🚨 TERM LOOKUP FAILED for predicate: {term_text} (type: {term_type}) - adding 1=0 condition")
                all_where_conditions.append("1=0")  # Condition that never matches
        
        # Handle object - exact logic from original
        if isinstance(obj, Variable):
            logger.debug(f"🔍 Processing object variable {obj}: already_mapped={obj in variable_mappings}, projected={projected_vars is None or obj in projected_vars}")
            if obj not in variable_mappings and (projected_vars is None or obj in projected_vars):
                term_alias = alias_gen.next_term_alias("object")
                all_joins.append(f"JOIN {table_config.term_table} {term_alias} ON {quad_alias}.object_uuid = {term_alias}.term_uuid")
                variable_mappings[obj] = f"{term_alias}.term_text"
                logger.debug(f"✅ Created mapping for {obj}: {variable_mappings[obj]}")
            else:
                logger.debug(f"⏭️ Skipping mapping for {obj}: already_mapped={obj in variable_mappings}, projected={projected_vars is None or obj in projected_vars}")
            # Variable already mapped or not projected - don't create JOIN
        else:
            # Bound term - use resolved UUID
            term_text, term_type = SparqlUtils.get_term_info(obj)
            term_key = (term_text, term_type)
            if term_key in term_uuid_mappings:
                term_uuid = term_uuid_mappings[term_key]
                all_where_conditions.append(f"{quad_alias}.object_uuid = '{term_uuid}'")
            else:
                # Term not found - this will result in no matches
                all_where_conditions.append("1=0")  # Condition that never matches
    
    # Build FROM clause with first quad table - exact logic from original
    from_clause = f"FROM {table_config.quad_table} {quad_aliases[0]}"
    
    # Add additional quad tables as JOINs if multiple triples - exact logic from original
    if len(quad_aliases) > 1:
        for i in range(1, len(quad_aliases)):
            # Find shared variables between current triple and ANY previous triple
            best_join_conditions = []
            best_reference_idx = 0
            
            # Check against all previous triples to find the best join
            for ref_idx in range(i):
                shared_vars = _find_shared_variables_between_triples(triples[ref_idx], triples[i])
                if shared_vars:
                    # Create join conditions based on shared variables
                    join_conditions = []
                    for var in shared_vars:
                        # Both triples share this variable, so their corresponding positions should match
                        pos_in_ref = _get_variable_position_in_triple(triples[ref_idx], var)
                        pos_in_current = _get_variable_position_in_triple(triples[i], var)
                        
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
    
    # Combine quad JOINs first, then term JOINs - exact logic from original
    combined_joins = quad_joins + all_joins
    
    # Handle context constraints for GRAPH patterns - exact logic from original
    if context_constraint is None:
        # No explicit GRAPH pattern - query ALL graphs (SPARQL 1.1 default graph behavior)
        # This means the union of all named graphs + the global graph
        # So we don't add any context constraint, allowing search across all graphs
        logger.debug("No GRAPH clause - searching across all graphs (SPARQL 1.1 default graph behavior)")
    else:
        # Explicit context constraint provided
        for quad_alias in quad_aliases:
            constraint = f"{quad_alias}.{context_constraint}"
            all_where_conditions.append(constraint)
        logger.debug(f"Applied explicit context constraint: {context_constraint}")
    
    return SQLComponents(
        from_clause=from_clause,
        where_conditions=all_where_conditions,
        joins=combined_joins,
        variable_mappings=variable_mappings
    )


def _find_shared_variables_between_triples(triple1, triple2):
    """Find shared variables between two triples - exact logic from original."""
    vars1 = {var for var in triple1 if isinstance(var, Variable)}
    vars2 = {var for var in triple2 if isinstance(var, Variable)}
    return vars1 & vars2


def _get_variable_position_in_triple(triple, variable):
    """Get the position of a variable in a triple (subject, predicate, object) - exact logic from original."""
    subject, predicate, obj = triple
    if subject == variable:
        return "subject"
    elif predicate == variable:
        return "predicate"
    elif obj == variable:
        return "object"
    return None


async def get_term_uuids_batch(terms: List[Tuple[str, str]], table_config: TableConfig, 
                               term_cache: PostgreSQLCacheTerm, space_impl) -> Dict[Tuple[str, str], str]:
    """
    Get term UUIDs for multiple terms using cache and batch database lookup.
    Ported from original PostgreSQLSparqlImpl._get_term_uuids_batch method.
    
    Args:
        terms: List of (term_text, term_type) tuples
        table_config: Table configuration for database queries
        term_cache: Term cache for efficient lookups
        space_impl: Space implementation for database operations
        
    Returns:
        Dictionary mapping (term_text, term_type) to term_uuid
    """
    if not terms:
        return {}
    
    # First, check cache for all terms
    logger.debug(f"🔍 CACHE CHECK: Looking up {len(terms)} terms in cache")
    cached_results = term_cache.get_batch(terms)
    
    # Find terms that need database lookup (terms not found in cache)
    cached_keys = set(cached_results.keys())
    uncached_terms = [term for term in terms if term not in cached_keys]
    cached_count = len(cached_results)
    logger.debug(f"🎯 CACHE RESULT: {cached_count}/{len(terms)} cache hits, {len(uncached_terms)} need DB lookup")
    
    # Start with cached results
    result = cached_results.copy()
    
    # Batch lookup uncached terms from database
    if uncached_terms:
        logger.debug(f"Batch database lookup for {len(uncached_terms)} uncached terms")
        
        # Build optimized batch query using IN clause for better performance
        # This leverages the composite (term_text, term_type) index more efficiently than OR clauses
        if len(uncached_terms) == 1:
            # Single term - use simple equality for better readability
            term_text, term_type = uncached_terms[0]
            escaped_text = term_text.replace("'", "''")
            batch_query = f"""
                SELECT term_text, term_type, term_uuid 
                FROM {table_config.term_table} 
                WHERE term_text = '{escaped_text}' AND term_type = '{term_type}'
            """
        else:
            # Multiple terms - use IN clause with VALUES for better performance
            # This approach is more reliable than string concatenation
            values_list = []
            for term_text, term_type in uncached_terms:
                escaped_text = term_text.replace("'", "''")
                values_list.append(f"('{escaped_text}', '{term_type}')")
            
            batch_query = f"""
                SELECT t.term_text, t.term_type, t.term_uuid 
                FROM {table_config.term_table} t
                INNER JOIN (VALUES {', '.join(values_list)}) AS v(term_text, term_type)
                    ON t.term_text = v.term_text AND t.term_type = v.term_type
            """
        
        # Execute batch query using space_impl
        # Use the space_impl's connection method to execute SQL
        with space_impl.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(batch_query)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                rows = cursor.fetchall()
                db_results = []
                for row in rows:
                    if isinstance(row, dict):
                        db_results.append(row)
                    else:
                        result_dict = {}
                        for i, value in enumerate(row):
                            if i < len(columns):
                                result_dict[columns[i]] = value
                        db_results.append(result_dict)
        
        # Process database results
        db_mappings = {}
        for row in db_results:
            key = (row['term_text'], row['term_type'])
            uuid = row['term_uuid']
            result[key] = uuid
            db_mappings[key] = uuid
        
        # Cache the database results
        if db_mappings:
            term_cache.put_batch(db_mappings)
            logger.debug(f"Cached {len(db_mappings)} terms from database lookup")
    
    return result
