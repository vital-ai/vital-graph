"""
PostgreSQL SPARQL Property Paths for VitalGraph

This module provides property path translation functions for SPARQL 1.1 property paths.
Handles transitive paths (+, *), optional paths (?), sequence paths (/), 
alternative paths (|), inverse paths (~), and negated paths (!).

Copied exactly from the original implementation to maintain compatibility.
"""

import logging
from typing import Dict, List, Tuple, Optional, Any
from rdflib import Variable, URIRef, Literal, BNode
from rdflib.plugins.sparql.algebra import Path, MulPath, SequencePath, AlternativePath, InvPath, NegatedPath

from .postgresql_sparql_core import SQLComponents, AliasGenerator, TableConfig, SparqlUtils

logger = logging.getLogger(__name__)

# Import the existing get_term_uuids_batch function
# We need to import it dynamically to avoid circular imports
def get_term_uuids_batch_func():
    """Lazy import to avoid circular dependency"""
    from .postgresql_sparql_cache_integration import get_term_uuids_batch
    return get_term_uuids_batch


async def translate_property_path(subject, path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None, term_cache=None, space_impl=None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
    """Translate SPARQL property paths to PostgreSQL recursive CTEs.
    
    Handles all SPARQL 1.1 property path types:
    - MulPath: + (one or more), * (zero or more), ? (zero or one)
    - SequencePath: / (sequence)
    - AlternativePath: | (alternative)
    - InvPath: ~ (inverse)
    - NegatedPath: ! (negated)
    
    Args:
        subject: Subject term (Variable or bound term)
        path: Property path object from RDFLib
        obj: Object term (Variable or bound term)
        table_config: Table configuration for SQL generation
        alias_gen: Alias generator for SQL identifiers
        projected_vars: Variables to project in SELECT clause
        term_cache: Term cache for efficient lookups
        space_impl: Space implementation for database operations
        
    Returns:
        Tuple of (from_clause, where_conditions, joins, variable_mappings)
    """
    logger.info(f"🛤️ Translating property path: {type(path).__name__} - {path}")
    
    # Dispatch to specific path type handlers
    if isinstance(path, MulPath):
        return await translate_mul_path(subject, path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl)
    elif isinstance(path, SequencePath):
        return await translate_sequence_path(subject, path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl)
    elif isinstance(path, AlternativePath):
        return await translate_alternative_path(subject, path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl)
    elif isinstance(path, InvPath):
        return await translate_inverse_path(subject, path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl)
    elif isinstance(path, NegatedPath):
        return await translate_negated_path(subject, path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl)
    else:
        # Fallback for unknown path types
        logger.error(f"❌ Unsupported property path type: {type(path).__name__}")
        raise NotImplementedError(f"Property path type {type(path).__name__} not yet implemented")


async def translate_mul_path(subject, mul_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None, term_cache=None, space_impl=None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
    """Translate MulPath (*, +, ?) to PostgreSQL recursive CTE.
    
    MulPath represents quantified paths:
    - * : zero or more (includes reflexive)
    - + : one or more (excludes reflexive)
    - ? : zero or one (optional)
    """
    logger.info(f"🔄 Translating MulPath: {mul_path.path} with modifier '{mul_path.mod}'")
    
    # Extract the base path and modifier
    base_path = mul_path.path
    modifier = mul_path.mod  # '*', '+', or '?'
    
    # Generate CTE alias
    cte_alias = alias_gen.next_subquery_alias()
    
    # Get term UUIDs for bound terms
    bound_terms = []
    if not isinstance(subject, Variable):
        term_text, term_type = SparqlUtils.get_term_info(subject)
        bound_terms.append((term_text, term_type))
    if not isinstance(obj, Variable):
        term_text, term_type = SparqlUtils.get_term_info(obj)
        bound_terms.append((term_text, term_type))
    
    # Handle base path (could be URI or nested path)
    if isinstance(base_path, Path):
        # Nested path - recursively translate
        base_from, base_where, base_joins, base_vars = await translate_property_path(
            subject, base_path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl
        )
        # For nested paths, we need to compose the recursive logic
        # This is complex and will be implemented in a later iteration
        raise NotImplementedError("Nested property paths not yet implemented")
    else:
        # Simple URI path - get its UUID
        if bound_terms:
            # Use term cache if available
            if term_cache and space_impl:
                get_term_uuids_batch = get_term_uuids_batch_func()
                term_uuid_mappings = await get_term_uuids_batch(bound_terms, table_config, term_cache, space_impl)
            else:
                # Fallback to space_impl if available
                term_uuid_mappings = {}
                logger.warning("No term cache or space_impl available for property path translation")
        else:
            term_uuid_mappings = {}
        
        # Get predicate UUID
        pred_text, pred_type = SparqlUtils.get_term_info(base_path)
        pred_key = (pred_text, pred_type)
        pred_uuid = None
        
        if pred_key not in term_uuid_mappings:
            # Look up predicate UUID
            if term_cache and space_impl:
                get_term_uuids_batch = get_term_uuids_batch_func()
                pred_mappings = await get_term_uuids_batch([pred_key], table_config, term_cache, space_impl)
                term_uuid_mappings.update(pred_mappings)
        
        if pred_key in term_uuid_mappings:
            pred_uuid = term_uuid_mappings[pred_key]
        else:
            # Predicate not found - return empty result
            logger.warning(f"Predicate not found in database: {pred_text}")
            return "SELECT NULL as start_node, NULL as end_node WHERE 1=0", [], [], {}
    
    # Build recursive CTE based on modifier
    if modifier == '*':
        # Zero or more - includes reflexive relationships
        cte_sql = build_recursive_cte_star(pred_uuid, table_config, cte_alias)
    elif modifier == '+':
        # One or more - excludes reflexive relationships
        cte_sql = build_recursive_cte_plus(pred_uuid, table_config, cte_alias)
    elif modifier == '?':
        # Zero or one - optional relationship
        cte_sql = build_recursive_cte_optional(pred_uuid, table_config, cte_alias)
    else:
        raise NotImplementedError(f"MulPath modifier '{modifier}' not implemented")
    
    # Build variable mappings
    variable_mappings = {}
    where_conditions = []
    joins = []
    
    # Generate a proper subquery alias for the CTE result
    subquery_alias = f"{cte_alias}_result"
    
    # Handle subject and object variables
    if isinstance(subject, Variable) and (projected_vars is None or subject in projected_vars):
        # Join with term table to get subject text
        subj_alias = alias_gen.next_term_alias("subject")
        joins.append(f"JOIN {table_config.term_table} {subj_alias} ON {subquery_alias}.start_node = {subj_alias}.term_uuid")
        variable_mappings[subject] = f"{subj_alias}.term_text"
    elif not isinstance(subject, Variable):
        # Bound subject - add constraint
        subj_text, subj_type = SparqlUtils.get_term_info(subject)
        subj_key = (subj_text, subj_type)
        if subj_key in term_uuid_mappings:
            subj_uuid = term_uuid_mappings[subj_key]
            where_conditions.append(f"{subquery_alias}.start_node = '{subj_uuid}'")
        else:
            # Subject not found
            where_conditions.append("1=0")
    
    if isinstance(obj, Variable) and (projected_vars is None or obj in projected_vars):
        # Join with term table to get object text
        obj_alias = alias_gen.next_term_alias("object")
        joins.append(f"JOIN {table_config.term_table} {obj_alias} ON {subquery_alias}.end_node = {obj_alias}.term_uuid")
        variable_mappings[obj] = f"{obj_alias}.term_text"
    elif not isinstance(obj, Variable):
        # Bound object - add constraint
        obj_text, obj_type = SparqlUtils.get_term_info(obj)
        obj_key = (obj_text, obj_type)
        if obj_key in term_uuid_mappings:
            obj_uuid = term_uuid_mappings[obj_key]
            where_conditions.append(f"{subquery_alias}.end_node = '{obj_uuid}'")
        else:
            # Object not found
            where_conditions.append("1=0")
    
    # Return the CTE as a proper subquery with alias
    return f"{cte_sql} {subquery_alias}", where_conditions, joins, variable_mappings


def build_recursive_cte_star(pred_uuid: str, table_config: TableConfig, cte_alias: str) -> str:
    """Build recursive CTE for * (zero or more) paths with cycle detection."""
    return f"""
    WITH RECURSIVE {cte_alias}(start_node, end_node, path, depth) AS (
        -- Base case: reflexive relationships (zero steps)
        SELECT DISTINCT subject_uuid as start_node, subject_uuid as end_node, 
               ARRAY[subject_uuid] as path, 0 as depth
        FROM {table_config.quad_table}
        WHERE predicate_uuid = '{pred_uuid}'
        
        UNION ALL
        
        -- Recursive case: one or more steps
        SELECT q.subject_uuid as start_node, q.object_uuid as end_node,
               r.path || q.object_uuid as path, r.depth + 1 as depth
        FROM {table_config.quad_table} q
        JOIN {cte_alias} r ON q.subject_uuid = r.end_node
        WHERE q.predicate_uuid = '{pred_uuid}'
          AND r.depth < 10  -- Prevent infinite recursion
          AND NOT (q.object_uuid = ANY(r.path))  -- Cycle detection
    )
    SELECT start_node, end_node FROM {cte_alias}
    """


def build_recursive_cte_plus(pred_uuid: str, table_config: TableConfig, cte_alias: str) -> str:
    """Build recursive CTE for + (one or more) paths with cycle detection."""
    return f"""(
        WITH RECURSIVE path_cte(start_node, end_node, path, depth) AS (
            -- Base case: direct relationships (one step)
            SELECT subject_uuid as start_node, object_uuid as end_node,
                   ARRAY[subject_uuid, object_uuid] as path, 1 as depth
            FROM {table_config.quad_table}
            WHERE predicate_uuid = '{pred_uuid}'
            
            UNION ALL
            
            -- Recursive case: additional steps
            SELECT r.start_node, q.object_uuid as end_node,
                   r.path || q.object_uuid as path, r.depth + 1 as depth
            FROM {table_config.quad_table} q
            JOIN path_cte r ON q.subject_uuid = r.end_node
            WHERE q.predicate_uuid = '{pred_uuid}'
              AND r.depth < 10  -- Prevent infinite recursion
              AND NOT (q.object_uuid = ANY(r.path))  -- Cycle detection
        )
        SELECT start_node, end_node FROM path_cte
    )"""


def build_recursive_cte_optional(pred_uuid: str, table_config: TableConfig, cte_alias: str) -> str:
    """Build CTE for ? (zero or one) paths."""
    return f"""
    WITH {cte_alias}(start_node, end_node) AS (
        -- Zero steps: reflexive relationships
        SELECT DISTINCT subject_uuid as start_node, subject_uuid as end_node
        FROM {table_config.quad_table}
        WHERE predicate_uuid = '{pred_uuid}'
        
        UNION ALL
        
        -- One step: direct relationships
        SELECT subject_uuid as start_node, object_uuid as end_node
        FROM {table_config.quad_table}
        WHERE predicate_uuid = '{pred_uuid}'
    )
    SELECT start_node, end_node FROM {cte_alias}
    """


async def translate_sequence_path(subject, seq_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None, term_cache=None, space_impl=None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
    """Translate SequencePath (/) to nested JOINs or CTEs.
    
    Sequence paths represent path1/path2 where we follow path1 then path2.
    """
    logger.info(f"➡️ Translating SequencePath: {seq_path.args}")
    
    # For now, implement a simple case of two paths
    if len(seq_path.args) != 2:
        raise NotImplementedError("Sequence paths with more than 2 components not yet implemented")
    
    path1, path2 = seq_path.args
    
    # Create intermediate variable for the connection point
    intermediate_var = Variable(f"__seq_intermediate_{alias_gen.counter}")
    alias_gen.counter += 1
    
    # Translate first path: subject -> intermediate
    path1_from, path1_where, path1_joins, path1_vars = await translate_property_path(
        subject, path1, intermediate_var, table_config, alias_gen, projected_vars, term_cache, space_impl
    )
    
    # Translate second path: intermediate -> object
    path2_from, path2_where, path2_joins, path2_vars = await translate_property_path(
        intermediate_var, path2, obj, table_config, alias_gen, projected_vars, term_cache, space_impl
    )
    
    # Combine the two path translations
    # This is a simplified approach - a full implementation would need more sophisticated joining
    combined_cte = f"""
    WITH path1 AS ({path1_from}),
         path2 AS ({path2_from})
    SELECT p1.start_node, p2.end_node
    FROM path1 p1
    JOIN path2 p2 ON p1.end_node = p2.start_node
    """
    
    # Combine conditions and joins
    combined_where = path1_where + path2_where
    combined_joins = path1_joins + path2_joins
    
    # Merge variable mappings (excluding intermediate)
    combined_vars = {}
    for var, mapping in path1_vars.items():
        if var != intermediate_var:
            combined_vars[var] = mapping
    for var, mapping in path2_vars.items():
        if var != intermediate_var:
            combined_vars[var] = mapping
    
    return combined_cte, combined_where, combined_joins, combined_vars


async def translate_alternative_path(subject, alt_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None, term_cache=None, space_impl=None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
    """Translate AlternativePath (|) to UNION of paths.
    
    Alternative paths represent path1|path2 where either path can be taken.
    """
    logger.info(f"🔀 Translating AlternativePath: {alt_path.args}")
    
    # Translate each alternative path
    union_parts = []
    all_where = []
    all_joins = []
    combined_vars = {}
    
    for i, path in enumerate(alt_path.args):
        path_from, path_where, path_joins, path_vars = await translate_property_path(
            subject, path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl
        )
        
        union_parts.append(f"({path_from})")
        all_where.extend(path_where)
        all_joins.extend(path_joins)
        
        # Merge variable mappings
        for var, mapping in path_vars.items():
            if var not in combined_vars:
                combined_vars[var] = mapping
    
    # Combine with UNION
    combined_cte = " UNION ALL ".join(union_parts)
    
    return combined_cte, all_where, all_joins, combined_vars


async def translate_inverse_path(subject, inv_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None, term_cache=None, space_impl=None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
    """Translate InvPath (~) by swapping subject and object.
    
    Inverse paths represent ~path which is equivalent to reversing the direction.
    """
    logger.info(f"🔄 Translating InversePath: ~{inv_path.arg}")
    
    # Translate the inner path with swapped subject and object
    return await translate_property_path(
        obj, inv_path.arg, subject, table_config, alias_gen, projected_vars, term_cache, space_impl
    )


async def translate_negated_path(subject, neg_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None, term_cache=None, space_impl=None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
    """Translate NegatedPath (!) using NOT EXISTS.
    
    Negated paths represent !path which excludes the specified path.
    For example, ?x !foaf:knows ?y finds all pairs where x is NOT connected to y via foaf:knows.
    
    Implementation strategy:
    1. Generate all possible subject-object pairs from the database
    2. Exclude pairs that match the negated path using NOT EXISTS
    """
    logger.info(f"🚫 Translating NegatedPath: !{neg_path.args}")
    
    # Extract the negated paths (NegatedPath can contain multiple alternatives)
    negated_paths = neg_path.args
    
    # Generate aliases
    subquery_alias = alias_gen.next_subquery_alias()
    
    # Get term UUIDs for bound terms
    bound_terms = []
    if not isinstance(subject, Variable):
        term_text, term_type = SparqlUtils.get_term_info(subject)
        bound_terms.append((term_text, term_type))
    if not isinstance(obj, Variable):
        term_text, term_type = SparqlUtils.get_term_info(obj)
        bound_terms.append((term_text, term_type))
    
    if bound_terms:
        if term_cache and space_impl:
            get_term_uuids_batch = get_term_uuids_batch_func()
            term_uuid_mappings = await get_term_uuids_batch(bound_terms, table_config, term_cache, space_impl)
        else:
            term_uuid_mappings = {}
            logger.warning("No term cache or space_impl available for negated path translation")
    else:
        term_uuid_mappings = {}
    
    # Handle the negated paths - build NOT EXISTS clauses for each
    not_exists_clauses = []
    
    for negated_path in negated_paths:
        if isinstance(negated_path, Path):
            # Complex path - recursively translate the negated path
            neg_from, neg_where, neg_joins, neg_vars = await translate_property_path(
                Variable('neg_subj'), negated_path, Variable('neg_obj'), table_config, alias_gen, None, term_cache, space_impl
            )
            
            # Build NOT EXISTS subquery with the complex path
            not_exists_clause = f"""NOT EXISTS (
                SELECT 1 FROM ({neg_from}) neg_path
                {' '.join(neg_joins)}
                WHERE {subquery_alias}.start_node = neg_path.start_node
                  AND {subquery_alias}.end_node = neg_path.end_node
                  {' AND ' + ' AND '.join(neg_where) if neg_where else ''}
            )"""
            not_exists_clauses.append(not_exists_clause)
        else:
            # Simple URI path - get its UUID and build NOT EXISTS
            pred_text, pred_type = SparqlUtils.get_term_info(negated_path)
            pred_key = (pred_text, pred_type)
            
            if pred_key not in term_uuid_mappings:
                if term_cache and space_impl:
                    get_term_uuids_batch = get_term_uuids_batch_func()
                    pred_mappings = await get_term_uuids_batch([pred_key], table_config, term_cache, space_impl)
                    term_uuid_mappings.update(pred_mappings)
            
            if pred_key in term_uuid_mappings:
                pred_uuid = term_uuid_mappings[pred_key]
                not_exists_clause = f"""NOT EXISTS (
                    SELECT 1 FROM {table_config.quad_table} neg_quad
                    WHERE neg_quad.subject_uuid = {subquery_alias}.start_node
                      AND neg_quad.predicate_uuid = '{pred_uuid}'
                      AND neg_quad.object_uuid = {subquery_alias}.end_node
                )"""
                not_exists_clauses.append(not_exists_clause)
            else:
                # Predicate not found - this negated path doesn't constrain anything
                logger.info(f"Negated predicate not found in database: {pred_text} - no constraint")
    
    # Combine all NOT EXISTS clauses with AND (all negated paths must not exist)
    if not_exists_clauses:
        combined_not_exists = " AND ".join(not_exists_clauses)
    else:
        # No valid negated paths found - all pairs are valid
        combined_not_exists = "1=1"
    
    # Build the main query that finds all possible subject-object pairs
    # and excludes those that match the negated path
    if isinstance(subject, Variable) and isinstance(obj, Variable):
        # Both variables - generate all possible pairs from terms, excluding the negated path
        # Fix scoping by replacing subquery_alias references with the actual table aliases
        scoped_not_exists = combined_not_exists.replace(f'{subquery_alias}.start_node', 't1.term_uuid').replace(f'{subquery_alias}.end_node', 't2.term_uuid')
        from_clause = f"""(
            SELECT DISTINCT t1.term_uuid as start_node, t2.term_uuid as end_node
            FROM {table_config.term_table} t1
            CROSS JOIN {table_config.term_table} t2
            WHERE t1.term_uuid != t2.term_uuid  -- Exclude self-loops
              AND {scoped_not_exists}
        ) {subquery_alias}"""
    elif isinstance(subject, Variable):
        # Subject is variable, object is bound
        obj_text, obj_type = SparqlUtils.get_term_info(obj)
        obj_key = (obj_text, obj_type)
        if obj_key in term_uuid_mappings:
            obj_uuid = term_uuid_mappings[obj_key]
            from_clause = f"""(
                SELECT DISTINCT t1.term_uuid as start_node, '{obj_uuid}' as end_node
                FROM {table_config.term_table} t1
                WHERE t1.term_uuid != '{obj_uuid}'  -- Exclude self-loops
                  AND {combined_not_exists.replace(f'{subquery_alias}.end_node', f"'{obj_uuid}'")}
            ) {subquery_alias}"""
        else:
            # Object not found - no results
            from_clause = f"(SELECT NULL as start_node, NULL as end_node WHERE 1=0) {subquery_alias}"
    elif isinstance(obj, Variable):
        # Object is variable, subject is bound
        subj_text, subj_type = SparqlUtils.get_term_info(subject)
        subj_key = (subj_text, subj_type)
        if subj_key in term_uuid_mappings:
            subj_uuid = term_uuid_mappings[subj_key]
            from_clause = f"""(
                SELECT DISTINCT '{subj_uuid}' as start_node, t2.term_uuid as end_node
                FROM {table_config.term_table} t2
                WHERE t2.term_uuid != '{subj_uuid}'  -- Exclude self-loops
                  AND {combined_not_exists.replace(f'{subquery_alias}.start_node', f"'{subj_uuid}'")}
            ) {subquery_alias}"""
        else:
            # Subject not found - no results
            from_clause = f"(SELECT NULL as start_node, NULL as end_node WHERE 1=0) {subquery_alias}"
    else:
        # Both bound - check if the specific pair is NOT connected by the negated path
        subj_text, subj_type = SparqlUtils.get_term_info(subject)
        obj_text, obj_type = SparqlUtils.get_term_info(obj)
        subj_key = (subj_text, subj_type)
        obj_key = (obj_text, obj_type)
        
        if subj_key in term_uuid_mappings and obj_key in term_uuid_mappings:
            subj_uuid = term_uuid_mappings[subj_key]
            obj_uuid = term_uuid_mappings[obj_key]
            
            # Check if the negated path exists between these specific terms
            specific_not_exists = combined_not_exists.replace(
                f'{subquery_alias}.start_node', f"'{subj_uuid}'"
            ).replace(
                f'{subquery_alias}.end_node', f"'{obj_uuid}'"
            )
            
            from_clause = f"""(
                SELECT '{subj_uuid}' as start_node, '{obj_uuid}' as end_node
                WHERE {specific_not_exists}
            ) {subquery_alias}"""
        else:
            # One or both terms not found - no results
            from_clause = f"(SELECT NULL as start_node, NULL as end_node WHERE 1=0) {subquery_alias}"
    
    # Build variable mappings
    variable_mappings = {}
    where_conditions = []
    joins = []
    
    # Handle subject and object variables
    if isinstance(subject, Variable) and (projected_vars is None or subject in projected_vars):
        # Join with term table to get subject text
        subj_alias = alias_gen.next_term_alias("subject")
        joins.append(f"JOIN {table_config.term_table} {subj_alias} ON {subquery_alias}.start_node = {subj_alias}.term_uuid")
        variable_mappings[subject] = f"{subj_alias}.term_text"
    
    if isinstance(obj, Variable) and (projected_vars is None or obj in projected_vars):
        # Join with term table to get object text
        obj_alias = alias_gen.next_term_alias("object")
        joins.append(f"JOIN {table_config.term_table} {obj_alias} ON {subquery_alias}.end_node = {obj_alias}.term_uuid")
        variable_mappings[obj] = f"{obj_alias}.term_text"
    
    return from_clause, where_conditions, joins, variable_mappings
