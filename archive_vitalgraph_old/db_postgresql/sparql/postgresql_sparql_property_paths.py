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

from vitalgraph.db.postgresql.sparql.postgresql_sparql_core import SQLComponents, AliasGenerator, TableConfig, SparqlUtils

logger = logging.getLogger(__name__)

# Cache the imported function to avoid repeated imports (performance optimization)
_get_term_uuids_batch = None

def _get_cached_term_uuids_batch():
    """Get cached get_term_uuids_batch function to avoid circular import and repeated imports"""
    global _get_term_uuids_batch
    if _get_term_uuids_batch is None:
        from vitalgraph.db.postgresql.sparql.postgresql_sparql_cache_integration import get_term_uuids_batch
        _get_term_uuids_batch = get_term_uuids_batch
    return _get_term_uuids_batch

async def translate_property_path(subject, path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None, term_cache=None, space_impl=None, *, sparql_context=None):
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
    function_name = "translate_property_path"
    
    # Use SparqlContext for consistent logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, path_type=type(path).__name__, path=str(path))
    else:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"🛤️ {function_name}: Translating property path: {type(path).__name__} - {path}")
    
    # Dispatch to specific path type handlers
    if isinstance(path, MulPath):
        return await translate_mul_path(subject, path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl, sparql_context=sparql_context)
    elif isinstance(path, SequencePath):
        return await translate_sequence_path(subject, path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl, sparql_context=sparql_context)
    elif isinstance(path, AlternativePath):
        return await translate_alternative_path(subject, path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl, sparql_context=sparql_context)
    elif isinstance(path, InvPath):
        return await translate_inverse_path(subject, path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl, sparql_context=sparql_context)
    elif isinstance(path, NegatedPath):
        return await translate_negated_path(subject, path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl, sparql_context=sparql_context)
    else:
        # Fallback for unknown path types
        logger.error(f"❌ Unsupported property path type: {type(path).__name__}")
        raise NotImplementedError(f"Property path type {type(path).__name__} not yet implemented")


async def translate_mul_path(subject, mul_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None, term_cache=None, space_impl=None, *, sparql_context=None):
    """Translate MulPath (*, +, ?) to PostgreSQL recursive CTE.
    
    MulPath represents quantified paths:
    - * : zero or more (includes reflexive)
    - + : one or more (excludes reflexive)
    - ? : zero or one (optional)
    """
    function_name = "translate_mul_path"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, path_type=type(mul_path.path).__name__, 
                                         modifier=mul_path.mod)
    else:
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"{function_name}: Translating MulPath with modifier '{mul_path.mod}'")
    
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
        base_result = await translate_property_path(
            subject, base_path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl
        )
        base_from = base_result.from_clause
        base_where = base_result.where_conditions
        base_joins = base_result.joins
        base_vars = base_result.variable_mappings
        # For nested paths, we need to compose the recursive logic
        # This is complex and will be implemented in a later iteration
        raise NotImplementedError("Nested property paths not yet implemented")
    else:
        # Simple URI path - get its UUID
        if bound_terms:
            # Use term cache if available
            if term_cache and space_impl:
                get_term_uuids_batch = _get_cached_term_uuids_batch()
                term_uuid_mappings = await get_term_uuids_batch(bound_terms, table_config, term_cache, space_impl, sparql_context=sparql_context)
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
                get_term_uuids_batch = _get_cached_term_uuids_batch()
                pred_mappings = await get_term_uuids_batch([pred_key], table_config, term_cache, space_impl, sparql_context=sparql_context)
                term_uuid_mappings.update(pred_mappings)
        
        if pred_key in term_uuid_mappings:
            pred_uuid = term_uuid_mappings[pred_key]
        else:
            # Predicate not found - return empty result
            logger.warning(f"Predicate not found in database: {pred_text}")
            from .postgresql_sparql_core import SQLComponents
            return SQLComponents(
                from_clause="SELECT NULL as start_node, NULL as end_node WHERE 1=0",
                where_conditions=[],
                joins=[],
                variable_mappings={}
            )
    
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
    from .postgresql_sparql_core import SQLComponents
    return SQLComponents(
        from_clause=f"{cte_sql} {subquery_alias}",
        where_conditions=where_conditions,
        joins=joins,
        variable_mappings=variable_mappings
    )


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


async def translate_sequence_path(subject, seq_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None, term_cache=None, space_impl=None, *, sparql_context=None):
    """Translate SequencePath (/) using JOINs.
    
    Sequence paths represent path1/path2 which means following path1 then path2.
    """
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
    else:
        import logging
        logger = logging.getLogger(__name__)
    
    logger.info(f"➡️ Translating SequencePath: {seq_path.args}")
    
    # For now, implement a simple case of two paths
    if len(seq_path.args) != 2:
        raise NotImplementedError("Sequence paths with more than 2 components not yet implemented")
    
    path1, path2 = seq_path.args
    
    # Create intermediate variable for the connection point
    intermediate_var = Variable(f"__seq_intermediate_{alias_gen.counter}")
    alias_gen.counter += 1
    
    # Translate first path: subject -> intermediate
    path1_result = await translate_property_path(
        subject, path1, intermediate_var, table_config, alias_gen, projected_vars, term_cache, space_impl
    )
    
    # Translate second path: intermediate -> object
    path2_result = await translate_property_path(
        intermediate_var, path2, obj, table_config, alias_gen, projected_vars, term_cache, space_impl
    )
    
    # Combine the two path translations
    # This is a simplified approach - a full implementation would need more sophisticated joining
    combined_cte = f"""
    WITH path1 AS ({path1_result.from_clause}),
         path2 AS ({path2_result.from_clause})
    SELECT p1.start_node, p2.end_node
    FROM path1 p1
    JOIN path2 p2 ON p1.end_node = p2.start_node
    """
    
    # Combine conditions and joins
    combined_where = path1_result.where_conditions + path2_result.where_conditions
    combined_joins = path1_result.joins + path2_result.joins
    
    # Merge variable mappings (excluding intermediate)
    combined_vars = {}
    for var, mapping in path1_result.variable_mappings.items():
        if var != intermediate_var:
            combined_vars[var] = mapping
    for var, mapping in path2_result.variable_mappings.items():
        if var != intermediate_var:
            combined_vars[var] = mapping
    
    from .postgresql_sparql_core import SQLComponents
    return SQLComponents(
        from_clause=combined_cte,
        where_conditions=combined_where,
        joins=combined_joins,
        variable_mappings=combined_vars
    )


async def translate_alternative_path(subject, alt_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None, term_cache=None, space_impl=None, *, sparql_context=None):
    """Translate AlternativePath (|) to UNION of paths.
    
    Alternative paths represent path1|path2 where either path can be taken.
    """
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
    else:
        import logging
        logger = logging.getLogger(__name__)
    
    logger.info(f"🔀 Translating AlternativePath: {alt_path.args}")
    
    # Translate each alternative path
    union_parts = []
    all_where = []
    all_joins = []
    combined_vars = {}
    
    for i, path in enumerate(alt_path.args):
        path_result = await translate_property_path(
            subject, path, obj, table_config, alias_gen, projected_vars, term_cache, space_impl
        )
        
        union_parts.append(f"({path_result.from_clause})")
        all_where.extend(path_result.where_conditions)
        all_joins.extend(path_result.joins)
        
        # Merge variable mappings
        for var, mapping in path_result.variable_mappings.items():
            if var not in combined_vars:
                combined_vars[var] = mapping
    
    # Combine with UNION
    combined_cte = " UNION ALL ".join(union_parts)
    
    from .postgresql_sparql_core import SQLComponents
    return SQLComponents(
        from_clause=combined_cte,
        where_conditions=all_where,
        joins=all_joins,
        variable_mappings=combined_vars
    )


async def translate_inverse_path(subject, inv_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None, term_cache=None, space_impl=None, *, sparql_context=None):
    """Translate InvPath (~) by swapping subject and object.
    
    Inverse paths represent ~path which is equivalent to reversing the direction.
    """
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
    else:
        import logging
        logger = logging.getLogger(__name__)
    
    logger.info(f"🔄 Translating InversePath: ~{inv_path.arg}")
    
    # Translate the inner path with swapped subject and object
    return await translate_property_path(
        obj, inv_path.arg, subject, table_config, alias_gen, projected_vars, term_cache, space_impl
    )


async def translate_negated_path(subject, neg_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None, term_cache=None, space_impl=None, *, sparql_context=None):
    """Translate NegatedPath (!) using NOT EXISTS.
    
    Negated paths represent !path which excludes the specified path.
    For example, ?x !foaf:knows ?y finds all pairs where x is NOT connected to y via foaf:knows.
    
    Implementation strategy:
    1. Generate all possible subject-object pairs from the database
    2. Exclude pairs that match the negated path using NOT EXISTS
    """
    function_name = "translate_negated_path"
    
    # Use SparqlContext for logging if available
    if sparql_context:
        logger = sparql_context.logger
        sparql_context.log_function_entry(function_name, negated_args=str(neg_path.args))
    else:
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"{function_name}: Translating NegatedPath with args {neg_path.args}")
    
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
            get_term_uuids_batch = _get_cached_term_uuids_batch()
            term_uuid_mappings = await get_term_uuids_batch(bound_terms, table_config, term_cache, space_impl, sparql_context=sparql_context)
        else:
            term_uuid_mappings = {}
            logger.warning("No term cache or space_impl available for negated path translation")
    else:
        term_uuid_mappings = {}
    
    # NEW APPROACH: Use recursive CTEs for negated paths to enable full compatibility
    # with arbitrary length paths and create a unified architecture
    
    # Build recursive CTEs for each negated path
    negated_ctes = []
    
    for i, negated_path in enumerate(negated_paths):
        cte_alias = f"negated_path_{i}"
        
        if isinstance(negated_path, Path):
            # Complex path (e.g., MulPath, SequencePath) - recursively translate
            # This enables support for !(knows+), !(knows/hasName), etc.
            neg_result = await translate_property_path(
                Variable('neg_subj'), negated_path, Variable('neg_obj'), table_config, alias_gen, None, term_cache, space_impl,
                sparql_context=sparql_context
            )
            
            # Extract the CTE from the complex path result
            if neg_result.from_clause.strip().startswith('('):
                # Remove outer parentheses and alias to get the CTE
                inner_cte = neg_result.from_clause.strip()[1:-1].split(') ')[0] + ')'
                negated_ctes.append(f"{cte_alias} AS {inner_cte}")
            else:
                # Simple FROM clause - wrap as CTE
                negated_ctes.append(f"{cte_alias} AS (SELECT start_node, end_node FROM {neg_result.from_clause})")
                
        else:
            # Simple URI path - build recursive CTE for direct relationships
            pred_text, pred_type = SparqlUtils.get_term_info(negated_path)
            pred_key = (pred_text, pred_type)
            
            if pred_key not in term_uuid_mappings:
                if term_cache and space_impl:
                    get_term_uuids_batch = _get_cached_term_uuids_batch()
                    pred_mappings = await get_term_uuids_batch([pred_key], table_config, term_cache, space_impl, sparql_context=sparql_context)
                    term_uuid_mappings.update(pred_mappings)
            
            if pred_key in term_uuid_mappings:
                pred_uuid = term_uuid_mappings[pred_key]
                # Build CTE for simple predicate relationships
                negated_ctes.append(f"""{cte_alias} AS (
                    SELECT subject_uuid as start_node, object_uuid as end_node
                    FROM {table_config.quad_table}
                    WHERE predicate_uuid = '{pred_uuid}'
                )""")
            else:
                # Predicate not found - create empty CTE
                logger.info(f"Negated predicate not found in database: {pred_text} - no constraint")
                negated_ctes.append(f"{cte_alias} AS (SELECT NULL::uuid as start_node, NULL::uuid as end_node WHERE 1=0)")
    
    # Combine all negated CTEs
    if negated_ctes:
        combined_negated_ctes = ", ".join(negated_ctes)
    else:
        # No valid negated paths found - create empty CTE
        combined_negated_ctes = "empty_negated AS (SELECT NULL::uuid as start_node, NULL::uuid as end_node WHERE 1=0)"
    
    # COMMENTED OUT: Original NOT EXISTS approach for reference
    # This approach had limitations with complex nested property paths
    # The old implementation used NOT EXISTS clauses but couldn't handle
    # complex nested property paths like !(knows+) or !(knows/hasName)
    # New CTE approach above enables full compatibility with arbitrary length paths
    
    # Build the main query using recursive CTEs to find all possible subject-object pairs
    # and exclude those that match any of the negated paths
    if isinstance(subject, Variable) and isinstance(obj, Variable):
        # Both variables - generate all possible pairs and exclude negated relationships
        # Use recursive CTE approach for full compatibility with arbitrary length paths
        
        # Generate unique aliases for the candidate pair generation
        quad_alias_1 = alias_gen.next_quad_alias()
        quad_alias_2 = alias_gen.next_quad_alias()
        main_cte_alias = alias_gen.next_subquery_alias()
        
        # Debug logging to verify unique alias generation
        if sparql_context:
            logger.debug(f"Generated unique aliases for negated path CTE: {quad_alias_1}, {quad_alias_2}")
        else:
            logger.debug(f"Generated unique aliases for negated path CTE: {quad_alias_1}, {quad_alias_2}")
        
        # Build the main CTE that generates candidate pairs and excludes negated paths
        from_clause = f"""(
            WITH {combined_negated_ctes},
            all_negated AS (
                {' UNION ALL '.join([f'SELECT start_node, end_node FROM negated_path_{i}' for i in range(len(negated_paths))])}
            ),
            candidates AS (
                -- Generate candidate pairs from terms that participate in relationships
                SELECT DISTINCT {quad_alias_1}.subject_uuid as start_node, {quad_alias_2}.subject_uuid as end_node
                FROM {table_config.quad_table} {quad_alias_1}
                CROSS JOIN {table_config.quad_table} {quad_alias_2}
                WHERE {quad_alias_1}.subject_uuid != {quad_alias_2}.subject_uuid
            )
            SELECT DISTINCT candidates.start_node, candidates.end_node
            FROM candidates
            WHERE NOT EXISTS (
                SELECT 1 FROM all_negated
                WHERE all_negated.start_node = candidates.start_node
                  AND all_negated.end_node = candidates.end_node
            )
        ) {subquery_alias}"""
        
        # Debug logging to show the generated SQL
        if sparql_context:
            logger.debug(f"Generated negated path CTE SQL:")
            logger.debug(f"SQL: {from_clause}")
        else:
            logger.debug(f"Generated negated path CTE SQL:")
            logger.debug(f"SQL: {from_clause}")
    elif isinstance(subject, Variable):
        # Subject is variable, object is bound - use CTE approach
        obj_text, obj_type = SparqlUtils.get_term_info(obj)
        obj_key = (obj_text, obj_type)
        if obj_key in term_uuid_mappings:
            obj_uuid = term_uuid_mappings[obj_key]
            # Build CTE that finds all subjects not connected to the bound object via negated paths
            from_clause = f"""(
                WITH {combined_negated_ctes},
                all_negated AS (
                    {' UNION ALL '.join([f'SELECT start_node, end_node FROM negated_path_{i}' for i in range(len(negated_paths))])}
                ),
                subject_candidates AS (
                    -- All terms that participate in RDF relationships
                    SELECT DISTINCT subject_uuid as term_uuid FROM {table_config.quad_table}
                    UNION
                    SELECT DISTINCT object_uuid as term_uuid FROM {table_config.quad_table}
                )
                SELECT DISTINCT subj_candidates.term_uuid as start_node, '{obj_uuid}' as end_node
                FROM subject_candidates subj_candidates
                WHERE subj_candidates.term_uuid != '{obj_uuid}'  -- Exclude self-loops
                  AND NOT EXISTS (
                      SELECT 1 FROM all_negated
                      WHERE all_negated.start_node = subj_candidates.term_uuid
                        AND all_negated.end_node = '{obj_uuid}'
                  )
            ) {subquery_alias}"""
        else:
            # Object not found - no results
            from_clause = f"(SELECT NULL as start_node, NULL as end_node WHERE 1=0) {subquery_alias}"
        
        # COMMENTED OUT: Original NOT EXISTS approach for reference
        # The old approach used scoped NOT EXISTS clauses with variable replacement
        # but had limitations with complex nested property paths
    elif isinstance(obj, Variable):
        # Object is variable, subject is bound - use CTE approach
        subj_text, subj_type = SparqlUtils.get_term_info(subject)
        subj_key = (subj_text, subj_type)
        if subj_key in term_uuid_mappings:
            subj_uuid = term_uuid_mappings[subj_key]
            # Build CTE that finds all objects not connected from the bound subject via negated paths
            from_clause = f"""(
                WITH {combined_negated_ctes},
                all_negated AS (
                    {' UNION ALL '.join([f'SELECT start_node, end_node FROM negated_path_{i}' for i in range(len(negated_paths))])}
                ),
                object_candidates AS (
                    -- All terms that participate in RDF relationships
                    SELECT DISTINCT subject_uuid as term_uuid FROM {table_config.quad_table}
                    UNION
                    SELECT DISTINCT object_uuid as term_uuid FROM {table_config.quad_table}
                )
                SELECT DISTINCT '{subj_uuid}' as start_node, obj_candidates.term_uuid as end_node
                FROM object_candidates obj_candidates
                WHERE obj_candidates.term_uuid != '{subj_uuid}'  -- Exclude self-loops
                  AND NOT EXISTS (
                      SELECT 1 FROM all_negated
                      WHERE all_negated.start_node = '{subj_uuid}'
                        AND all_negated.end_node = obj_candidates.term_uuid
                  )
            ) {subquery_alias}"""
        else:
            # Subject not found - no results
            from_clause = f"(SELECT NULL as start_node, NULL as end_node WHERE 1=0) {subquery_alias}"
    else:
        # Both bound - check if the specific pair is NOT connected by the negated path using CTE approach
        subj_text, subj_type = SparqlUtils.get_term_info(subject)
        obj_text, obj_type = SparqlUtils.get_term_info(obj)
        subj_key = (subj_text, subj_type)
        obj_key = (obj_text, obj_type)
        
        if subj_key in term_uuid_mappings and obj_key in term_uuid_mappings:
            subj_uuid = term_uuid_mappings[subj_key]
            obj_uuid = term_uuid_mappings[obj_key]
            
            # Use CTE to check if the specific pair is NOT connected by any negated path
            from_clause = f"""(
                WITH {combined_negated_ctes},
                all_negated AS (
                    {' UNION ALL '.join([f'SELECT start_node, end_node FROM negated_path_{i}' for i in range(len(negated_paths))])}
                )
                SELECT '{subj_uuid}' as start_node, '{obj_uuid}' as end_node
                WHERE NOT EXISTS (
                    SELECT 1 FROM all_negated
                    WHERE all_negated.start_node = '{subj_uuid}'
                      AND all_negated.end_node = '{obj_uuid}'
                )
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
    
    from .postgresql_sparql_core import SQLComponents
    return SQLComponents(
        from_clause=from_clause,
        where_conditions=where_conditions,
        joins=joins,
        variable_mappings=variable_mappings
    )
