"""
PostgreSQL SPARQL Utilities for VitalGraph

This module provides shared utilities, constants, and helper classes
for the PostgreSQL SPARQL implementation refactoring.
"""

import logging
from dataclasses import dataclass
from typing import Tuple
from rdflib import Variable, URIRef, Literal, BNode

# Import PostgreSQL utilities for table name generation
from .postgresql_utils import PostgreSQLUtils


class GraphConstants:
    """Constants for graph URI handling in SPARQL queries."""
    GLOBAL_GRAPH_URI = "urn:___GLOBAL"
    GLOBAL_GRAPH_TYPE = "U"  # URI type
    
    @classmethod
    def get_global_graph_term_info(cls) -> Tuple[str, str]:
        """Get term info tuple for global graph."""
        return (cls.GLOBAL_GRAPH_URI, cls.GLOBAL_GRAPH_TYPE)


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
    def from_space_impl(cls, space_impl, space_id: str, use_unlogged: bool = False) -> 'TableConfig':
        """Create TableConfig from PostgreSQLSpaceImpl and space_id."""
        quad_table = PostgreSQLUtils.get_table_name(space_impl.global_prefix, space_id, "rdf_quad")
        term_table = PostgreSQLUtils.get_table_name(space_impl.global_prefix, space_id, "term")
        
        # Add _unlogged suffix if using unlogged tables
        if use_unlogged:
            quad_table += "_unlogged"
            term_table += "_unlogged"
            
        return cls(quad_table=quad_table, term_table=term_table)


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
            # Escape single quotes in URI
            uri_str = str(term).replace("'", "''")
            return f"'{uri_str}'"
        elif isinstance(term, Literal):
            # Handle different literal types
            value = str(term)
            
            # Check for numeric types
            if term.datatype:
                datatype_str = str(term.datatype)
                if 'integer' in datatype_str.lower():
                    try:
                        return str(int(value))
                    except ValueError:
                        pass
                elif 'decimal' in datatype_str.lower() or 'float' in datatype_str.lower() or 'double' in datatype_str.lower():
                    try:
                        return str(float(value))
                    except ValueError:
                        pass
                elif 'boolean' in datatype_str.lower():
                    return 'TRUE' if value.lower() in ('true', '1') else 'FALSE'
            
            # Default: escape single quotes and wrap in quotes
            escaped_value = value.replace("'", "''")
            return f"'{escaped_value}'"
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
