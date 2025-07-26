"""
PostgreSQL SPARQL Property Paths Implementation for VitalGraph

This module handles the translation of SPARQL 1.1 property paths to PostgreSQL
recursive CTEs and SQL queries. Supports all property path types including
MulPath (*, +, ?), SequencePath (/), AlternativePath (|), InvPath (~), and NegatedPath (!).
"""

import logging
from typing import List, Dict, Tuple, Set, Optional, Any, Union
from rdflib import Variable, URIRef, Literal, BNode
from rdflib.paths import Path, MulPath, SequencePath, AlternativePath, InvPath, NegatedPath

# Import shared utilities
from .postgresql_sparql_utils import TableConfig, AliasGenerator, SparqlUtils


class PostgreSQLSparqlPropertyPaths:
    """Handles translation of SPARQL property paths to PostgreSQL recursive CTEs."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize the property paths translator.
        
        Args:
            logger: Optional logger instance. If None, creates a new logger.
        """
        self.logger = logger or logging.getLogger(__name__)

    async def translate_property_path(self, subject, path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
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
            
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        self.logger.info(f"🛤️ Translating property path: {type(path).__name__} - {path}")
        
        # Dispatch to specific path type handlers
        if isinstance(path, MulPath):
            return await self.translate_mul_path(subject, path, obj, table_config, alias_gen, projected_vars)
        elif isinstance(path, SequencePath):
            return await self.translate_sequence_path(subject, path, obj, table_config, alias_gen, projected_vars)
        elif isinstance(path, AlternativePath):
            return await self.translate_alternative_path(subject, path, obj, table_config, alias_gen, projected_vars)
        elif isinstance(path, InvPath):
            return await self.translate_inverse_path(subject, path, obj, table_config, alias_gen, projected_vars)
        elif isinstance(path, NegatedPath):
            return await self.translate_negated_path(subject, path, obj, table_config, alias_gen, projected_vars)
        else:
            # Fallback for unknown path types
            self.logger.error(f"❌ Unsupported property path type: {type(path).__name__}")
            raise NotImplementedError(f"Property path type {type(path).__name__} not yet implemented")



    async def translate_mul_path(self, subject, mul_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate MulPath (*, +, ?) to PostgreSQL recursive CTE.
        
        MulPath represents quantified paths:
        - * : zero or more (includes reflexive)
        - + : one or more (excludes reflexive)
        - ? : zero or one (optional)
        """
        self.logger.info(f"🔄 Translating MulPath: {mul_path.path} with modifier '{mul_path.mod}'")
        
        # Extract the base path and modifier
        base_path = mul_path.path
        modifier = mul_path.mod  # '*', '+', or '?'
        
        # Generate CTE alias
        cte_alias = alias_gen.next_subquery_alias()
        
        # Get term UUIDs for bound terms
        bound_terms = []
        if not isinstance(subject, Variable):
            term_text, term_type = self._get_term_info(subject)
            bound_terms.append((term_text, term_type))
        if not isinstance(obj, Variable):
            term_text, term_type = self._get_term_info(obj)
            bound_terms.append((term_text, term_type))
        
        # Handle base path (could be URI or nested path)
        if isinstance(base_path, Path):
            # Nested path - recursively translate
            base_from, base_where, base_joins, base_vars = await self.translate_property_path(
                subject, base_path, obj, table_config, alias_gen, projected_vars
            )
            # For nested paths, we need to compose the recursive logic
            # This is complex and will be implemented in a later iteration
            raise NotImplementedError("Nested property paths not yet implemented")
        else:
            # Simple URI path - get its UUID
            if bound_terms:
                term_uuid_mappings = await self._get_term_uuids_batch(bound_terms, table_config)
            else:
                term_uuid_mappings = {}
            
            # Get predicate UUID
            pred_text, pred_type = self._get_term_info(base_path)
            pred_key = (pred_text, pred_type)
            pred_uuid = None
            
            if pred_key not in term_uuid_mappings:
                # Look up predicate UUID
                pred_mappings = await self._get_term_uuids_batch([pred_key], table_config)
                term_uuid_mappings.update(pred_mappings)
            
            if pred_key in term_uuid_mappings:
                pred_uuid = term_uuid_mappings[pred_key]
            else:
                # Predicate not found - return empty result
                self.logger.warning(f"Predicate not found in database: {pred_text}")
                return "SELECT NULL as start_node, NULL as end_node WHERE 1=0", [], [], {}
        
        # Build recursive CTE based on modifier
        if modifier == '*':
            # Zero or more - includes reflexive relationships
            cte_sql = self._build_recursive_cte_star(pred_uuid, table_config, cte_alias)
        elif modifier == '+':
            # One or more - excludes reflexive relationships
            cte_sql = self._build_recursive_cte_plus(pred_uuid, table_config, cte_alias)
        elif modifier == '?':
            # Zero or one - optional relationship
            cte_sql = self._build_recursive_cte_optional(pred_uuid, table_config, cte_alias)
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
            subj_text, subj_type = self._get_term_info(subject)
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
            obj_text, obj_type = self._get_term_info(obj)
            obj_key = (obj_text, obj_type)
            if obj_key in term_uuid_mappings:
                obj_uuid = term_uuid_mappings[obj_key]
                where_conditions.append(f"{subquery_alias}.end_node = '{obj_uuid}'")
            else:
                # Object not found
                where_conditions.append("1=0")
        
        # Return the CTE as a proper subquery with alias
        return f"{cte_sql} {subquery_alias}", where_conditions, joins, variable_mappings


    async def translate_sequence_path(self, subject, seq_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate SequencePath (/) to nested JOINs or CTEs.
        
        Sequence paths represent path1/path2 where we follow path1 then path2.
        """
        self.logger.info(f"➡️ Translating SequencePath: {seq_path.args}")
        
        # For now, implement a simple case of two paths
        if len(seq_path.args) != 2:
            raise NotImplementedError("Sequence paths with more than 2 components not yet implemented")
        
        path1, path2 = seq_path.args
        
        # Create intermediate variable for the connection point
        intermediate_var = Variable(f"__seq_intermediate_{alias_gen.counter}")
        alias_gen.counter += 1
        
        # Translate first path: subject -> intermediate
        path1_from, path1_where, path1_joins, path1_vars = await self.translate_property_path(
            subject, path1, intermediate_var, table_config, alias_gen, projected_vars
        )
        
        # Translate second path: intermediate -> object
        path2_from, path2_where, path2_joins, path2_vars = await self.translate_property_path(
            intermediate_var, path2, obj, table_config, alias_gen, projected_vars
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

    async def translate_sequence_path(self, subject, seq_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate SequencePath (/) to nested JOINs or CTEs.
        
        Sequence paths represent path1/path2 where we follow path1 then path2.
        """
        self.logger.info(f"➡️ Translating SequencePath: {seq_path.args}")
        
        # For now, implement a simple case of two paths
        if len(seq_path.args) != 2:
            raise NotImplementedError("Sequence paths with more than 2 components not yet implemented")
        
        path1, path2 = seq_path.args
        
        # Create intermediate variable for the connection point
        intermediate_var = Variable(f"__seq_intermediate_{alias_gen.counter}")
        alias_gen.counter += 1
        
        # Translate first path: subject -> intermediate
        path1_from, path1_where, path1_joins, path1_vars = await self.translate_property_path(
            subject, path1, intermediate_var, table_config, alias_gen, projected_vars
        )
        
        # Translate second path: intermediate -> object
        path2_from, path2_where, path2_joins, path2_vars = await self.translate_property_path(
            intermediate_var, path2, obj, table_config, alias_gen, projected_vars
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

    async def translate_alternative_path(self, subject, alt_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate AlternativePath (|) to UNION of paths.
        
        Alternative paths represent path1|path2 where either path can be taken.
        """
        self.logger.info(f"🔀 Translating AlternativePath: {alt_path.args}")
        
        # Translate each alternative path
        union_parts = []
        all_where = []
        all_joins = []
        combined_vars = {}
        
        for i, path in enumerate(alt_path.args):
            path_from, path_where, path_joins, path_vars = await self._translate_property_path(
                subject, path, obj, table_config, alias_gen, projected_vars
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

    
    async def translate_inverse_path(self, subject, inv_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate InvPath (~) by swapping subject and object.
        
        Inverse paths represent ~path which is equivalent to reversing the direction.
        """
        self.logger.info(f"🔄 Translating InversePath: ~{inv_path.arg}")
        
        # Translate the inner path with swapped subject and object
        return await self.translate_property_path(
            obj, inv_path.arg, subject, table_config, alias_gen, projected_vars
        )

    async def translate_negated_path(self, subject, neg_path, obj, table_config: TableConfig, alias_gen, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate NegatedPath (!) using NOT EXISTS.
        
        Negated paths represent !path which excludes the specified path.
        For example, ?x !foaf:knows ?y finds all pairs where x is NOT connected to y via foaf:knows.
        
        Implementation strategy:
        1. Generate all possible subject-object pairs from the database
        2. Exclude pairs that match the negated path using NOT EXISTS
        """
        self.logger.info(f"🚫 Translating NegatedPath: !{neg_path.args}")
        
        # Extract the negated paths (NegatedPath can contain multiple alternatives)
        negated_paths = neg_path.args
        
        # Generate aliases
        subquery_alias = alias_gen.next_subquery_alias()
        
        # Get term UUIDs for bound terms
        bound_terms = []
        if not isinstance(subject, Variable):
            term_text, term_type = self._get_term_info(subject)
            bound_terms.append((term_text, term_type))
        if not isinstance(obj, Variable):
            term_text, term_type = self._get_term_info(obj)
            bound_terms.append((term_text, term_type))
        
        if bound_terms:
            term_uuid_mappings = await self._get_term_uuids_batch(bound_terms, table_config)
        else:
            term_uuid_mappings = {}
        
        # Handle the negated paths - build NOT EXISTS clauses for each
        not_exists_clauses = []
        
        for negated_path in negated_paths:
            if isinstance(negated_path, Path):
                # Complex path - recursively translate the negated path
                neg_from, neg_where, neg_joins, neg_vars = await self.translate_property_path(
                    Variable('neg_subj'), negated_path, Variable('neg_obj'), table_config, alias_gen
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
                pred_text, pred_type = self._get_term_info(negated_path)
                pred_key = (pred_text, pred_type)
                
                if pred_key not in term_uuid_mappings:
                    pred_mappings = await self._get_term_uuids_batch([pred_key], table_config)
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
                    self.logger.info(f"Negated predicate not found in database: {pred_text} - no constraint")
        
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
            obj_text, obj_type = self._get_term_info(obj)
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
            subj_text, subj_type = self._get_term_info(subject)
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
            subj_text, subj_type = self._get_term_info(subject)
            obj_text, obj_type = self._get_term_info(obj)
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
    
    def get_supported_path_types(self) -> Set[str]:
        """Get the set of supported SPARQL property path types.
        
        Returns:
            Set of supported property path type names
        """
        return {
            "MulPath", "SequencePath", "AlternativePath", "InvPath", "NegatedPath"
        }
    
    def is_supported_path_type(self, path_type: str) -> bool:
        """Check if a property path type is supported.
        
        Args:
            path_type: Name of the path type to check
            
        Returns:
            True if the path type is supported
        """
        return path_type in self.get_supported_path_types()
    
    def get_term_info(self, term) -> Tuple[str, str]:
        """Extract term text and type from RDFLib term.
        
        Args:
            term: RDFLib term (URIRef, Literal, BNode, Variable)
            
        Returns:
            Tuple of (term_text, term_type) where term_type is 'U', 'L', 'B', or 'V'
        """
        return SparqlUtils.get_term_info(term)
    
    def validate_path_structure(self, path) -> bool:
        """Validate that a property path has the expected structure.
        
        Args:
            path: Property path to validate
            
        Returns:
            True if the path is valid
        """
        try:
            # Check basic path structure
            if not hasattr(path, '__class__'):
                self.logger.error("Path object missing class information")
                return False
            
            path_type = type(path).__name__
            
            # Validate path-specific structure
            if path_type == "MulPath":
                if not (hasattr(path, 'path') and hasattr(path, 'mod')):
                    self.logger.error("MulPath missing 'path' or 'mod' attributes")
                    return False
                if path.mod not in ['*', '+', '?']:
                    self.logger.error(f"Invalid MulPath modifier: {path.mod}")
                    return False
            elif path_type == "SequencePath":
                if not hasattr(path, 'args'):
                    self.logger.error("SequencePath missing 'args' attribute")
                    return False
                if not isinstance(path.args, (list, tuple)) or len(path.args) < 2:
                    self.logger.error("SequencePath must have at least 2 path components")
                    return False
            elif path_type == "AlternativePath":
                if not hasattr(path, 'args'):
                    self.logger.error("AlternativePath missing 'args' attribute")
                    return False
                if not isinstance(path.args, (list, tuple)) or len(path.args) < 2:
                    self.logger.error("AlternativePath must have at least 2 path alternatives")
                    return False
            elif path_type == "InvPath":
                if not hasattr(path, 'arg'):
                    self.logger.error("InvPath missing 'arg' attribute")
                    return False
            elif path_type == "NegatedPath":
                if not hasattr(path, 'args'):
                    self.logger.error("NegatedPath missing 'args' attribute")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating path structure: {e}")
            return False
    
    def build_recursive_cte(self, base_query: str, recursive_query: str, 
                           cte_name: str, columns: List[str]) -> str:
        """Build a PostgreSQL recursive CTE.
        
        Args:
            base_query: Base case query (non-recursive part)
            recursive_query: Recursive case query
            cte_name: Name for the CTE
            columns: Column names for the CTE
            
        Returns:
            Complete recursive CTE SQL
        """
        column_list = ', '.join(columns)
        return f"""
        WITH RECURSIVE {cte_name}({column_list}) AS (
            {base_query}
            UNION ALL
            {recursive_query}
        )
        SELECT * FROM {cte_name}
        """.strip()
    
    def build_union_query(self, queries: List[str], alias: str) -> str:
        """Build a UNION query from multiple subqueries.
        
        Args:
            queries: List of SQL queries to union
            alias: Alias for the resulting union
            
        Returns:
            UNION query SQL
        """
        if not queries:
            return f"(SELECT NULL as start_node, NULL as end_node WHERE 1=0) {alias}"
        
        union_sql = ' UNION ALL '.join(f"({query})" for query in queries)
        return f"({union_sql}) {alias}"
    
    def extract_path_variables(self, subject, obj, projected_vars: Optional[List[Variable]] = None) -> Set[Variable]:
        """Extract variables from subject and object that need to be projected.
        
        Args:
            subject: Subject term (Variable or bound term)
            obj: Object term (Variable or bound term)
            projected_vars: Optional list of variables to project
            
        Returns:
            Set of variables that need projection
        """
        variables = set()
        
        if isinstance(subject, Variable):
            if projected_vars is None or subject in projected_vars:
                variables.add(subject)
        
        if isinstance(obj, Variable):
            if projected_vars is None or obj in projected_vars:
                variables.add(obj)
        
        return variables
    
    def build_term_joins(self, variables: Set[Variable], subquery_alias: str, 
                        table_config: TableConfig, alias_gen: AliasGenerator) -> Tuple[List[str], Dict[Variable, str]]:
        """Build JOIN clauses to resolve term UUIDs to text values.
        
        Args:
            variables: Variables that need term resolution
            subquery_alias: Alias of the subquery containing term UUIDs
            table_config: Database table configuration
            alias_gen: Alias generator for unique names
            
        Returns:
            Tuple of (join_clauses, variable_mappings)
        """
        joins = []
        variable_mappings = {}
        
        for var in variables:
            if var.toPython().lower().endswith('subject') or 'subj' in var.toPython().lower():
                # This is likely a subject variable
                term_alias = alias_gen.next_term_alias("subject")
                joins.append(f"JOIN {table_config.term_table} {term_alias} ON {subquery_alias}.start_node = {term_alias}.term_uuid")
                variable_mappings[var] = f"{term_alias}.term_text"
            elif var.toPython().lower().endswith('object') or 'obj' in var.toPython().lower():
                # This is likely an object variable
                term_alias = alias_gen.next_term_alias("object")
                joins.append(f"JOIN {table_config.term_table} {term_alias} ON {subquery_alias}.end_node = {term_alias}.term_uuid")
                variable_mappings[var] = f"{term_alias}.term_text"
            else:
                # Generic variable - assume it could be either subject or object
                # We'll need context to determine which column to join on
                term_alias = alias_gen.next_term_alias("term")
                # Default to start_node (subject) - this may need refinement
                joins.append(f"JOIN {table_config.term_table} {term_alias} ON {subquery_alias}.start_node = {term_alias}.term_uuid")
                variable_mappings[var] = f"{term_alias}.term_text"
        
        return joins, variable_mappings
    
    def generate_intermediate_variable(self, base_name: str, counter: int) -> Variable:
        """Generate a unique intermediate variable for path sequences.
        
        Args:
            base_name: Base name for the variable
            counter: Counter for uniqueness
            
        Returns:
            Unique Variable instance
        """
        return Variable(f"__{base_name}_intermediate_{counter}__")
    
    def merge_path_results(self, results: List[Tuple[str, List[str], List[str], Dict[Variable, str]]], 
                          operation: str = "UNION") -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Merge multiple path translation results.
        
        Args:
            results: List of (from_clause, where_conditions, joins, variable_mappings) tuples
            operation: How to combine the results ("UNION" or "JOIN")
            
        Returns:
            Merged result tuple
        """
        if not results:
            return "(SELECT NULL as start_node, NULL as end_node WHERE 1=0) empty", [], [], {}
        
        if len(results) == 1:
            return results[0]
        
        # Extract components
        from_clauses = [result[0] for result in results]
        all_where = []
        all_joins = []
        combined_vars = {}
        
        for result in results:
            all_where.extend(result[1])
            all_joins.extend(result[2])
            combined_vars.update(result[3])
        
        # Combine FROM clauses based on operation
        if operation == "UNION":
            combined_from = self.build_union_query(from_clauses, "combined_paths")
        else:
            # For JOIN operations, this would need more sophisticated logic
            combined_from = from_clauses[0]  # Simplified
        
        return combined_from, all_where, all_joins, combined_vars
    
    def optimize_path_query(self, from_clause: str, where_conditions: List[str], 
                           joins: List[str]) -> Tuple[str, List[str], List[str]]:
        """Apply optimizations to property path queries.
        
        Args:
            from_clause: FROM clause SQL
            where_conditions: WHERE conditions
            joins: JOIN clauses
            
        Returns:
            Optimized query components
        """
        # Remove duplicate conditions
        unique_where = list(dict.fromkeys(where_conditions))
        unique_joins = list(dict.fromkeys(joins))
        
        # TODO: Add more sophisticated optimizations like:
        # - Predicate pushdown
        # - Join reordering
        # - Index hints
        
        return from_clause, unique_where, unique_joins
    
    def estimate_path_complexity(self, path) -> int:
        """Estimate the computational complexity of a property path.
        
        Args:
            path: Property path to analyze
            
        Returns:
            Complexity score (higher = more complex)
        """
        if not hasattr(path, '__class__'):
            return 1
        
        path_type = type(path).__name__
        
        if path_type == "MulPath":
            # Recursive paths are most expensive
            base_complexity = self.estimate_path_complexity(path.path) if hasattr(path, 'path') and isinstance(path.path, Path) else 1
            if path.mod == '*':
                return base_complexity * 10  # Zero or more is most expensive
            elif path.mod == '+':
                return base_complexity * 8   # One or more is expensive
            else:  # '?'
                return base_complexity * 2   # Zero or one is moderate
        elif path_type == "SequencePath":
            # Sequence complexity is sum of components
            if hasattr(path, 'args'):
                return sum(self.estimate_path_complexity(arg) for arg in path.args if isinstance(arg, Path))
            return 3
        elif path_type == "AlternativePath":
            # Alternative complexity is max of components
            if hasattr(path, 'args'):
                return max(self.estimate_path_complexity(arg) for arg in path.args if isinstance(arg, Path))
            return 2
        elif path_type == "InvPath":
            # Inverse adds minimal overhead
            base_complexity = self.estimate_path_complexity(path.arg) if hasattr(path, 'arg') and isinstance(path.arg, Path) else 1
            return base_complexity + 1
        elif path_type == "NegatedPath":
            # Negation is expensive due to NOT EXISTS
            if hasattr(path, 'args'):
                base_complexity = sum(self.estimate_path_complexity(arg) for arg in path.args if isinstance(arg, Path))
            else:
                base_complexity = 1
            return base_complexity * 5
        else:
            return 1  # Simple URI path

        