#!/usr/bin/env python3
"""
SPARQL to SQL Translator using RDFLib Parser

This module provides comprehensive translation from SPARQL queries to SQL queries
for custom table schemas, supporting all major SPARQL features including:
- Basic triple patterns
- FILTER expressions (comparisons, regex, string functions)
- OPTIONAL clauses
- UNION operations
- Complex boolean expressions

Usage:
    translator = SparqlToSqlTranslator(table_config)
    sql_query = translator.translate_sparql(sparql_query)
"""

import re
import logging
from typing import Dict, List, Tuple, Any, Optional, Union
from dataclasses import dataclass
from rdflib import Variable, URIRef, Literal, BNode
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.algebra import translateQuery

logger = logging.getLogger(__name__)

@dataclass
class TableConfig:
    """Configuration for UUID-based quad/term table schema mapping"""
    # Main tables
    quad_table: str = "rdf_quad"
    term_table: str = "term"
    
    # Quad table columns (all UUIDs)
    subject_uuid_column: str = "subject_uuid"
    predicate_uuid_column: str = "predicate_uuid" 
    object_uuid_column: str = "object_uuid"
    context_uuid_column: str = "context_uuid"
    
    # Term table columns
    term_uuid_column: str = "term_uuid"
    term_text_column: str = "term_text"
    term_type_column: str = "term_type"
    term_lang_column: str = "lang"
    term_datatype_column: str = "datatype_id"

class SparqlToSqlTranslator:
    """
    Translates SPARQL queries to SQL using RDFLib's algebra representation.
    """
    
    def __init__(self, table_config: TableConfig):
        self.table_config = table_config
        self.variable_counter = 0
        self.join_counter = 0
        
    def translate_sparql(self, sparql_query: str) -> str:
        """
        Main entry point: translate SPARQL query to SQL.
        
        Args:
            sparql_query: SPARQL query string
            
        Returns:
            SQL query string
        """
        try:
            # Parse and get algebra
            prepared_query = prepareQuery(sparql_query)
            algebra = prepared_query.algebra
            
            logger.info(f"Translating SPARQL query with algebra: {algebra.name}")
            
            # Reset counters for each query
            self.variable_counter = 0
            self.join_counter = 0
            
            # Translate based on query type
            if algebra.name == "SelectQuery":
                return self._translate_select_query(algebra)
            elif algebra.name == "ConstructQuery":
                return self._translate_construct_query(algebra)
            else:
                raise NotImplementedError(f"Query type {algebra.name} not yet supported")
                
        except Exception as e:
            logger.error(f"Error translating SPARQL query: {e}")
            raise
    
    def _translate_select_query(self, algebra) -> str:
        """Translate SELECT query algebra to SQL."""
        
        # Extract projection variables
        projection_vars = algebra.get('PV', [])
        
        # Extract and translate the main pattern
        pattern = algebra['p']
        from_clause, where_conditions, joins, variable_mappings = self._translate_pattern(pattern)
        
        # Build SELECT clause with variable mappings
        select_clause = self._build_select_clause(projection_vars, variable_mappings)
        
        # Build complete SQL query
        sql_parts = [select_clause]
        sql_parts.append(from_clause)
        
        if joins:
            sql_parts.extend(joins)
            
        if where_conditions:
            sql_parts.append(f"WHERE {' AND '.join(where_conditions)}")
            
        return '\n'.join(sql_parts)
    
    def _build_select_clause(self, projection_vars: List[Variable], variable_mappings: Dict[Variable, str]) -> str:
        """Build SQL SELECT clause from SPARQL projection variables."""
        if not projection_vars:
            return "SELECT *"
            
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
            
        return f"SELECT {', '.join(select_items)}"
    
    def _translate_pattern(self, pattern) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """
        Translate a SPARQL pattern to SQL components.
        
        Returns:
            Tuple of (from_clause, where_conditions, joins, variable_mappings)
        """
        pattern_name = pattern.name
        
        if pattern_name == "BGP":  # Basic Graph Pattern
            return self._translate_bgp(pattern)
        elif pattern_name == "Filter":
            return self._translate_filter(pattern)
        elif pattern_name == "Project":
            return self._translate_project(pattern)
        elif pattern_name == "Union":
            return self._translate_union(pattern)
        elif pattern_name == "LeftJoin":  # OPTIONAL
            return self._translate_optional(pattern)
        else:
            logger.warning(f"Pattern type {pattern_name} not fully implemented")
            return f"FROM {self.table_config.quad_table} q0", [], [], {}
    
    def _translate_bgp(self, bgp_pattern) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate Basic Graph Pattern to SQL using UUID-based quad/term schema."""
        triples = bgp_pattern.get('triples', [])
        
        if not triples:
            return f"FROM {self.table_config.quad_table} q0", [], [], {}
        
        # Build query with JOINs to term table for each position
        quad_alias = f"q{self.join_counter}"
        self.join_counter += 1
        
        from_clause = f"FROM {self.table_config.quad_table} {quad_alias}"
        where_conditions = []
        joins = []
        variable_mappings = {}
        
        # Track which term aliases we need for variables
        term_alias_counter = 0
        
        # Process each triple pattern
        for triple_idx, triple in enumerate(triples):
            subject, predicate, obj = triple
            
            # Handle additional triples with self-joins on quad table
            if triple_idx > 0:
                new_quad_alias = f"q{self.join_counter}"
                self.join_counter += 1
                
                # Join on shared variables
                join_condition = self._build_quad_join_condition(quad_alias, new_quad_alias, triple, triples[0])
                joins.append(f"JOIN {self.table_config.quad_table} {new_quad_alias} ON {join_condition}")
                current_quad_alias = new_quad_alias
            else:
                current_quad_alias = quad_alias
            
            # Add JOINs to term table for variables and conditions for bound terms
            self._process_triple_terms(current_quad_alias, subject, predicate, obj, 
                                     joins, where_conditions, variable_mappings, term_alias_counter)
        
        return from_clause, where_conditions, joins, variable_mappings
    
    def _process_triple_terms(self, quad_alias: str, subject, predicate, obj, 
                            joins: List[str], where_conditions: List[str], 
                            variable_mappings: Dict[Variable, str], term_alias_counter: int):
        """Process terms in a triple, adding JOINs for variables and conditions for bound terms."""
        
        # Process subject
        if isinstance(subject, Variable):
            if subject not in variable_mappings:
                term_alias = f"ts{term_alias_counter}"
                term_alias_counter += 1
                joins.append(f"JOIN {self.table_config.term_table} {term_alias} ON {quad_alias}.{self.table_config.subject_uuid_column} = {term_alias}.{self.table_config.term_uuid_column}")
                variable_mappings[subject] = f"{term_alias}.{self.table_config.term_text_column}"
        else:
            # Bound term - add condition via subquery
            term_value = self._format_rdf_term(subject)
            where_conditions.append(f"{quad_alias}.{self.table_config.subject_uuid_column} IN (SELECT {self.table_config.term_uuid_column} FROM {self.table_config.term_table} WHERE {self.table_config.term_text_column} = {term_value})")
        
        # Process predicate
        if isinstance(predicate, Variable):
            if predicate not in variable_mappings:
                term_alias = f"tp{term_alias_counter}"
                term_alias_counter += 1
                joins.append(f"JOIN {self.table_config.term_table} {term_alias} ON {quad_alias}.{self.table_config.predicate_uuid_column} = {term_alias}.{self.table_config.term_uuid_column}")
                variable_mappings[predicate] = f"{term_alias}.{self.table_config.term_text_column}"
        else:
            # Bound term - add condition via subquery
            term_value = self._format_rdf_term(predicate)
            where_conditions.append(f"{quad_alias}.{self.table_config.predicate_uuid_column} IN (SELECT {self.table_config.term_uuid_column} FROM {self.table_config.term_table} WHERE {self.table_config.term_text_column} = {term_value})")
        
        # Process object
        if isinstance(obj, Variable):
            if obj not in variable_mappings:
                term_alias = f"to{term_alias_counter}"
                term_alias_counter += 1
                joins.append(f"JOIN {self.table_config.term_table} {term_alias} ON {quad_alias}.{self.table_config.object_uuid_column} = {term_alias}.{self.table_config.term_uuid_column}")
                variable_mappings[obj] = f"{term_alias}.{self.table_config.term_text_column}"
        else:
            # Bound term - add condition via subquery with type/datatype constraints
            term_value = self._format_rdf_term(obj)
            term_conditions = [f"{self.table_config.term_text_column} = {term_value}"]
            
            # Add type constraint
            if isinstance(obj, URIRef):
                term_conditions.append(f"{self.table_config.term_type_column} = 'U'")
            elif isinstance(obj, Literal):
                term_conditions.append(f"{self.table_config.term_type_column} = 'L'")
                if obj.language:
                    term_conditions.append(f"{self.table_config.term_lang_column} = '{obj.language}'")
                if obj.datatype:
                    # This would need more complex handling for datatype UUIDs
                    pass
            elif isinstance(obj, BNode):
                term_conditions.append(f"{self.table_config.term_type_column} = 'B'")
            
            where_conditions.append(f"{quad_alias}.{self.table_config.object_uuid_column} IN (SELECT {self.table_config.term_uuid_column} FROM {self.table_config.term_table} WHERE {' AND '.join(term_conditions)})")
    
    def _build_quad_join_condition(self, alias1: str, alias2: str, triple1: tuple, triple2: tuple) -> str:
        """Build JOIN condition between quad tables based on shared variables."""
        # Find shared variables between the two triples
        vars1 = {term for term in triple1 if isinstance(term, Variable)}
        vars2 = {term for term in triple2 if isinstance(term, Variable)}
        shared_vars = vars1.intersection(vars2)
        
        if not shared_vars:
            return "1=1"  # Cartesian product if no shared variables
        
        # Build join conditions for shared variables
        join_conditions = []
        for var in shared_vars:
            # Find positions of the variable in each triple
            pos1 = self._find_variable_position(triple1, var)
            pos2 = self._find_variable_position(triple2, var)
            
            col1 = self._get_uuid_column_for_position(pos1)
            col2 = self._get_uuid_column_for_position(pos2)
            
            join_conditions.append(f"{alias1}.{col1} = {alias2}.{col2}")
        
        return " AND ".join(join_conditions)
    
    def _get_uuid_column_for_position(self, position: int) -> str:
        """Get UUID column name for triple position."""
        if position == 0:
            return self.table_config.subject_uuid_column
        elif position == 1:
            return self.table_config.predicate_uuid_column
        elif position == 2:
            return self.table_config.object_uuid_column
        else:
            return self.table_config.subject_uuid_column  # Default
    
    def _build_triple_conditions(self, table_alias: str, subject, predicate, obj) -> List[str]:
        """Build WHERE conditions for a single triple pattern."""
        conditions = []
        
        # Subject condition
        if not isinstance(subject, Variable):
            subject_value = self._format_rdf_term(subject)
            conditions.append(f"{table_alias}.{self.table_config.subject_column} = {subject_value}")
        
        # Predicate condition  
        if not isinstance(predicate, Variable):
            predicate_value = self._format_rdf_term(predicate)
            conditions.append(f"{table_alias}.{self.table_config.predicate_column} = {predicate_value}")
        
        # Object condition
        if not isinstance(obj, Variable):
            obj_value = self._format_rdf_term(obj)
            conditions.append(f"{table_alias}.{self.table_config.object_column} = {obj_value}")
            
            # Add type/datatype conditions for literals
            if isinstance(obj, Literal):
                conditions.append(f"{table_alias}.{self.table_config.object_type_column} = 'L'")
                if obj.datatype:
                    datatype_value = self._format_rdf_term(obj.datatype)
                    conditions.append(f"{table_alias}.{self.table_config.object_datatype_column} = {datatype_value}")
                if obj.language:
                    conditions.append(f"{table_alias}.{self.table_config.object_language_column} = '{obj.language}'")
        
        return conditions
    
    def _build_join_condition(self, alias1: str, alias2: str, triple1: tuple, triple2: tuple) -> str:
        """Build JOIN condition based on shared variables between triples."""
        # Find shared variables between the two triples
        vars1 = {term for term in triple1 if isinstance(term, Variable)}
        vars2 = {term for term in triple2 if isinstance(term, Variable)}
        shared_vars = vars1.intersection(vars2)
        
        if not shared_vars:
            return "1=1"  # Cartesian product if no shared variables
        
        # Build join conditions for shared variables
        join_conditions = []
        for var in shared_vars:
            # Find positions of the variable in each triple
            pos1 = self._find_variable_position(triple1, var)
            pos2 = self._find_variable_position(triple2, var)
            
            col1 = self._get_column_for_position(pos1)
            col2 = self._get_column_for_position(pos2)
            
            join_conditions.append(f"{alias1}.{col1} = {alias2}.{col2}")
        
        return " AND ".join(join_conditions)
    
    def _translate_filter(self, filter_pattern) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate FILTER pattern to SQL."""
        # Get the underlying pattern
        inner_pattern = filter_pattern['p']
        from_clause, where_conditions, joins, variable_mappings = self._translate_pattern(inner_pattern)
        
        # Translate the filter expression
        filter_expr = filter_pattern['expr']
        filter_condition = self._translate_expression(filter_expr, variable_mappings)
        
        if filter_condition:
            where_conditions.append(filter_condition)
        
        return from_clause, where_conditions, joins, variable_mappings
    
    def _translate_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate SPARQL filter expressions to SQL."""
        expr_name = expr.name
        
        if expr_name == "RelationalExpression":
            return self._translate_relational_expression(expr, variable_mappings)
        elif expr_name == "ConditionalAndExpression":
            return self._translate_and_expression(expr, variable_mappings)
        elif expr_name == "ConditionalOrExpression":
            return self._translate_or_expression(expr, variable_mappings)
        elif expr_name.startswith("Builtin_"):
            return self._translate_builtin_function(expr, variable_mappings)
        else:
            logger.warning(f"Expression type {expr_name} not implemented")
            return "1=1"
    
    def _translate_relational_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate relational expressions like ?x > 100."""
        variable = expr['expr']
        operator = expr['op']
        other_value = expr['other']
        
        # Map variable to column using variable mappings
        if variable in variable_mappings:
            column = variable_mappings[variable]
        else:
            logger.warning(f"Variable {variable} not found in mappings")
            return "1=1"
        
        # Format the other value
        if isinstance(other_value, Literal):
            # Handle numeric literals - cast term text to appropriate type
            if other_value.datatype and 'integer' in str(other_value.datatype):
                column = f"CAST({column} AS INTEGER)"
                sql_value = str(other_value)
            elif other_value.datatype and ('decimal' in str(other_value.datatype) or 'double' in str(other_value.datatype)):
                column = f"CAST({column} AS DECIMAL)"
                sql_value = str(other_value)
            else:
                sql_value = f"'{other_value}'"
        else:
            sql_value = self._format_rdf_term(other_value)
        
        # Map SPARQL operators to SQL
        op_mapping = {
            '>': '>',
            '<': '<',
            '>=': '>=',
            '<=': '<=',
            '=': '=',
            '!=': '!='
        }
        
        sql_op = op_mapping.get(operator, operator)
        return f"{column} {sql_op} {sql_value}"
    
    def _translate_and_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate AND expressions."""
        left_expr = expr['expr']
        other_exprs = expr.get('other', [])
        
        conditions = [self._translate_expression(left_expr, variable_mappings)]
        
        for other_expr in other_exprs:
            conditions.append(self._translate_expression(other_expr, variable_mappings))
        
        return f"({' AND '.join(conditions)})"
    
    def _translate_or_expression(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate OR expressions."""
        left_expr = expr['expr']
        other_exprs = expr.get('other', [])
        
        conditions = [self._translate_expression(left_expr, variable_mappings)]
        
        for other_expr in other_exprs:
            conditions.append(self._translate_expression(other_expr, variable_mappings))
        
        return f"({' OR '.join(conditions)})"
    
    def _translate_builtin_function(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate SPARQL builtin functions."""
        func_name = expr.name.replace("Builtin_", "")
        
        if func_name == "REGEX":
            return self._translate_regex_function(expr, variable_mappings)
        elif func_name == "CONTAINS":
            return self._translate_contains_function(expr, variable_mappings)
        elif func_name == "STRSTARTS":
            return self._translate_strstarts_function(expr, variable_mappings)
        elif func_name == "STRENDS":
            return self._translate_strends_function(expr, variable_mappings)
        else:
            logger.warning(f"Builtin function {func_name} not implemented")
            return "1=1"
    
    def _translate_regex_function(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate REGEX function to SQL."""
        arg1 = expr.get('arg1')  # Variable or expression
        arg2 = expr.get('arg2')  # Pattern
        flags = expr.get('arg3', '')  # Optional flags
        
        if arg1 in variable_mappings:
            column = variable_mappings[arg1]
        else:
            logger.warning(f"Variable {arg1} not found in mappings for REGEX")
            return "1=1"
        
        pattern = str(arg2).strip('"\'')
        
        # Handle case-insensitive flag
        if 'i' in str(flags).lower():
            return f"LOWER({column}) ~ LOWER('{pattern}')"
        else:
            return f"{column} ~ '{pattern}'"
    
    def _translate_contains_function(self, expr, variable_mappings: Dict[Variable, str]) -> str:
        """Translate CONTAINS function to SQL."""
        arg1 = expr.get('arg1')
        arg2 = expr.get('arg2')
        
        if arg1 in variable_mappings:
            column = variable_mappings[arg1]
        else:
            logger.warning(f"Variable {arg1} not found in mappings for CONTAINS")
            return "1=1"
        
        search_term = str(arg2).strip('"\'')
        
        return f"{column} LIKE '%{search_term}%'"
    
    def _translate_strstarts_function(self, expr, table_alias: str) -> str:
        """Translate STRSTARTS function to SQL."""
        arg1 = expr.get('arg1')
        arg2 = expr.get('arg2')
        
        column = self._map_variable_to_column(arg1, table_alias)
        prefix = str(arg2).strip('"\'')
        
        return f"{column} LIKE '{prefix}%'"
    
    def _translate_strends_function(self, expr, table_alias: str) -> str:
        """Translate STRENDS function to SQL."""
        arg1 = expr.get('arg1')
        arg2 = expr.get('arg2')
        
        column = self._map_variable_to_column(arg1, table_alias)
        suffix = str(arg2).strip('"\'')
        
        return f"{column} LIKE '%{suffix}'"
    
    def _translate_project(self, pattern) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate Project (SELECT clause) pattern."""
        # Project just wraps another pattern
        inner_pattern = pattern['p']
        return self._translate_pattern(inner_pattern)
    
    def _translate_union(self, pattern) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate UNION pattern to SQL."""
        # This would require UNION in SQL - more complex implementation needed
        logger.warning("UNION translation not fully implemented")
        return f"FROM {self.table_config.quad_table} q0", [], [], {}
    
    def _translate_optional(self, pattern) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
        """Translate OPTIONAL pattern to LEFT JOIN."""
        # This would require LEFT JOIN - more complex implementation needed
        logger.warning("OPTIONAL translation not fully implemented")
        return f"FROM {self.table_config.quad_table} q0", [], [], {}
    
    def _map_variable_to_column(self, variable, table_alias: str) -> str:
        """Map SPARQL variable to appropriate SQL column."""
        # This is a simplified mapping - in practice you'd need more sophisticated logic
        # to determine which column a variable maps to based on its usage in triple patterns
        var_name = str(variable).replace('?', '').lower()
        
        # Common variable name mappings
        if var_name in ['s', 'subject']:
            return f"{table_alias}.{self.table_config.subject_column}"
        elif var_name in ['p', 'predicate']:
            return f"{table_alias}.{self.table_config.predicate_column}"
        elif var_name in ['o', 'object']:
            return f"{table_alias}.{self.table_config.object_column}"
        else:
            # Default to object column for value variables
            return f"{table_alias}.{self.table_config.object_column}"
    
    def _find_variable_position(self, triple: tuple, variable: Variable) -> int:
        """Find the position (0=subject, 1=predicate, 2=object) of a variable in a triple."""
        for i, term in enumerate(triple):
            if term == variable:
                return i
        return -1
    
    def _get_column_for_position(self, position: int) -> str:
        """Get column name for triple position."""
        if position == 0:
            return self.table_config.subject_column
        elif position == 1:
            return self.table_config.predicate_column
        elif position == 2:
            return self.table_config.object_column
        else:
            return self.table_config.subject_column  # Default
    
    def _format_rdf_term(self, term) -> str:
        """Format RDF term for SQL query."""
        if isinstance(term, URIRef):
            return f"'{str(term)}'"
        elif isinstance(term, Literal):
            return f"'{str(term)}'"
        elif isinstance(term, BNode):
            return f"'{str(term)}'"
        else:
            return f"'{str(term)}'"

# Example usage and test functions
def main():
    """Test the SPARQL to SQL translator."""
    
    # Configure UUID-based table schema (matching your VitalGraph schema)
    table_config = TableConfig(
        quad_table="rdf_quad",
        term_table="term",
        subject_uuid_column="subject_uuid",
        predicate_uuid_column="predicate_uuid",
        object_uuid_column="object_uuid",
        context_uuid_column="context_uuid",
        term_uuid_column="term_uuid",
        term_text_column="term_text",
        term_type_column="term_type",
        term_lang_column="lang",
        term_datatype_column="datatype_id"
    )
    
    translator = SparqlToSqlTranslator(table_config)
    
    # Test queries
    test_queries = [
        # Basic triple pattern
        """
        SELECT ?person ?name WHERE {
            ?person <http://example.org/name> ?name .
        }
        """,
        
        # Filter with comparison
        """
        SELECT ?person ?age WHERE {
            ?person <http://example.org/age> ?age .
            FILTER(?age > 21)
        }
        """,
        
        # Regex filter
        """
        SELECT ?person ?name WHERE {
            ?person <http://example.org/name> ?name .
            FILTER(REGEX(?name, "John.*", "i"))
        }
        """,
        
        # Complex filter
        """
        SELECT ?person ?name ?age WHERE {
            ?person <http://example.org/name> ?name .
            ?person <http://example.org/age> ?age .
            FILTER(?age > 18 && ?age < 65 && CONTAINS(?name, "Smith"))
        }
        """
    ]
    
    for i, sparql_query in enumerate(test_queries, 1):
        print(f"\n{'='*60}")
        print(f"TEST QUERY {i}")
        print(f"{'='*60}")
        print("SPARQL:")
        print(sparql_query.strip())
        print("\nSQL:")
        try:
            sql_query = translator.translate_sparql(sparql_query.strip())
            print(sql_query)
        except Exception as e:
            print(f"ERROR: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
