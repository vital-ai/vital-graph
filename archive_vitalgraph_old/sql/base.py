"""Base classes for the store."""
import logging
import re
from rdflib import Literal
from rdflib.graph import Graph, QuotedGraph
from rdflib.plugins.stores.regexmatching import REGEXTerm
from sqlalchemy.sql import expression
from sqlalchemy.sql import ColumnElement

from .constants import (
    TEXT_SEARCH_OPTIMIZATION_ENABLED,
    TEXT_SEARCH_MIN_TERM_LENGTH,
    TEXT_SEARCH_LITERAL_TABLE_PRIORITY,
)
from .termutils import (
    type_to_term_combination,
    statement_to_term_combination,
)

_logger = logging.getLogger(__name__)


class SQLGeneratorMixin(object):
    """SQL statement generator mixin for the VitalGraphSQLStore store."""

    def regex_op(self, col, pattern):
        """
        Apply a POSIX‐style regex match on `col` using the appropriate operator
        for the current SQL dialect.

        - On PostgreSQL, uses the '~' operator.
        - On MySQL, uses 'REGEXP'.
        """
        _logger.info(f"🚀 SQLGeneratorMixin.regex_op: FUNCTION STARTED with col={col}, pattern={pattern}")
        # PostgreSQL uses '~' for regex; MySQL uses REGEXP
        op_name = "~" if self.engine.name == "postgresql" else "REGEXP"
        return col.op(op_name)(pattern)

    def _build_type_sql_command(self, member, klass, context):
        """Build an insert command for a type table."""
        _logger.info(f"🚀 SQLGeneratorMixin._build_type_sql_command: FUNCTION STARTED with member={member}, klass={klass}, context={context}")
        # columns: member,klass,context
        rt = self.tables["type_statements"].insert()
        return rt, {
            "member": member,
            "klass": klass,
            "context": context.identifier,
            "termComb": int(type_to_term_combination(member, klass, context))
        }

    def _build_literal_triple_sql_command(self, subject, predicate, obj, context):
        """
        Build an insert command for literal triples.

        These triples correspond to RDF statements where the object is a Literal,
        e.g. `rdflib.Literal`.

        """
        _logger.info(f"🚀 SQLGeneratorMixin._build_literal_triple_sql_command: FUNCTION STARTED with subject={subject}, predicate={predicate}, obj={obj}, context={context}")
        triple_pattern = int(
            statement_to_term_combination(subject, predicate, obj, context)
        )

        command = self.tables["literal_statements"].insert()
        values = {
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "context": context.identifier,
            "termComb": triple_pattern,
            "objLanguage": isinstance(obj, Literal) and obj.language or None,
            "objDatatype": isinstance(obj, Literal) and obj.datatype or None,
        }
        return command, values

    def _build_triple_sql_command(self, subject, predicate, obj, context, quoted):
        """
        Build an insert command for regular triple table.

        """
        _logger.info(f"🚀 SQLGeneratorMixin._build_triple_sql_command: FUNCTION STARTED with subject={subject}, predicate={predicate}, obj={obj}, context={context}, quoted={quoted}")
        stmt_table = (
            self.tables["quoted_statements"]
            if quoted
            else self.tables["asserted_statements"]
        )

        triple_pattern = statement_to_term_combination(
            subject,
            predicate,
            obj,
            context,
        )
        command = stmt_table.insert()

        if quoted:
            params = {
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "context": context.identifier,
                "termComb": triple_pattern,
                "objLanguage": isinstance(obj, Literal) and obj.language or None,
                "objDatatype": isinstance(obj, Literal) and obj.datatype or None
            }
        else:
            params = {
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "context": context.identifier,
                "termComb": triple_pattern,
            }
        return command, params

    def build_clause(self, table, subject, predicate, obj, context=None, typeTable=False):
        """Build WHERE clauses for the supplied terms and, context."""
        _logger.info(f"🚀 SQLGeneratorMixin.build_clause: FUNCTION STARTED with table={table.name}, subject={subject}, predicate={predicate}, obj={obj}, context={context}, typeTable={typeTable}")
        
        if typeTable:
            _logger.info("Building type table clauses")
            clauseList = [
                self.build_type_member_clause(subject, table),
                self.build_type_class_clause(obj, table),
                self.build_context_clause(context, table)
            ]
        else:
            _logger.info("Building standard table clauses")
            clauseList = [
                self.build_subject_clause(subject, table),
                self.build_predicate_clause(predicate, table),
                self.build_object_clause(obj, table),
                self.build_context_clause(context, table),
                self.build_literal_datatype_clause(obj, table),
                self.build_literal_language_clause(obj, table)
            ]

        clauseList = [clause for clause in clauseList if clause is not None]
        if clauseList:
            _logger.info(f"Generated {len(clauseList)} clauses")
            return expression.and_(*clauseList)
        else:
            _logger.info("No clauses generated")
            return None

    def build_literal_datatype_clause(self, obj, table):
        """Build Literal and datatype clause."""
        _logger.info(f"🚀 SQLGeneratorMixin.build_literal_datatype_clause: FUNCTION STARTED with obj={obj}, table={table.name}")
        if isinstance(obj, Literal) and obj.datatype is not None:
            return table.c.objDatatype == obj.datatype
        else:
            return None

    def build_literal_language_clause(self, obj, table):
        """Build Literal and language clause."""
        _logger.info(f"🚀 SQLGeneratorMixin.build_literal_language_clause: FUNCTION STARTED with obj={obj}, table={table.name}")
        if isinstance(obj, Literal) and obj.language is not None:
            return table.c.objLanguage == obj.language
        else:
            return None

    # Where Clause  utility Functions
    # The predicate and object clause builders are modified in order
    # to optimize subjects and objects utility functions which can
    # take lists as their last argument (object, predicate - respectively)

    def build_subject_clause(self, subject, table):
        """Build Subject clause."""
        _logger.info(f"🚀 SQLGeneratorMixin.build_subject_clause: FUNCTION STARTED with subject={subject}, table={table.name}")
        if isinstance(subject, REGEXTerm):
            # PostgreSQL regex support using ~ operator (MySQL uses REGEXP)
            return self.regex_op(table.c.subject, subject)

        elif isinstance(subject, list):
            # clauseStrings = [] --- unused
            return expression.or_(
                *[self.build_subject_clause(s, table) for s in subject if s])
        elif isinstance(subject, (QuotedGraph, Graph)):
            return table.c.subject == subject.identifier
        elif subject is not None:
            return table.c.subject == subject
        else:
            return None

    def build_predicate_clause(self, predicate, table):
        """
        Build Predicate clause.

        Capable of taking a list of predicates as well, in which case
        subclauses are joined with 'OR'.

        """
        _logger.info(f"🚀 SQLGeneratorMixin.build_predicate_clause: FUNCTION STARTED with predicate={predicate}, table={table.name}")
        if isinstance(predicate, REGEXTerm):
            # PostgreSQL regex support using ~ operator (MySQL uses REGEXP)
            return self.regex_op(table.c.predicate, predicate)
        elif isinstance(predicate, list):
            return expression.or_(
                *[self.build_predicate_clause(p, table) for p in predicate if p])
        elif predicate is not None:
            return table.c.predicate == predicate
        else:
            return None

    def build_object_clause(self, obj, table):
        """
        Build Object clause.

        Capable of taking a list of objects as well, in which case subclauses
        are joined with 'OR'.

        """
        _logger.info(f"🚀 SQLGeneratorMixin.build_object_clause: FUNCTION STARTED with obj={obj}, table={table.name}")
        if isinstance(obj, REGEXTerm):
            # PostgreSQL regex support using ~ operator (MySQL uses REGEXP)
            return self.regex_op(table.c.object, obj)
        elif isinstance(obj, list):
            return expression.or_(
                *[self.build_object_clause(o, table) for o in obj if o])
        elif isinstance(obj, (QuotedGraph, Graph)):
            return table.c.object == obj.identifier
        elif obj is not None:
            return table.c.object == obj
        else:
            return None

    def build_context_clause(self, context, table):
        """Build Context clause."""
        _logger.info(f"🚀 SQLGeneratorMixin.build_context_clause: FUNCTION STARTED with context={context}, table={table.name}")
        if isinstance(context, REGEXTerm):
            # PostgreSQL regex support using ~ operator (MySQL uses REGEXP)
            return self.regex_op(table.c.context, context)
        elif context is not None:
            # Handle both Graph objects (with .identifier) and URIRef objects (direct use)
            if hasattr(context, 'identifier') and context.identifier is not None:
                return table.c.context == context.identifier
            else:
                # For URIRef objects, use the URIRef directly
                return table.c.context == str(context)
        else:
            return None

    def build_type_member_clause(self, subject, table):
        """Build Type Member clause."""
        _logger.info(f"🚀 SQLGeneratorMixin.build_type_member_clause: FUNCTION STARTED with subject={subject}, table={table.name}")
        if isinstance(subject, REGEXTerm):
            # PostgreSQL regex support using ~ operator (MySQL uses REGEXP)
            return self.regex_op(table.c.member, subject)
        elif isinstance(subject, list):
            return expression.or_(
                *[self.build_type_member_clause(s, table) for s in subject if s])
        elif subject is not None:
            return table.c.member == subject
        else:
            return None

    def build_type_class_clause(self, obj, table):
        """Build Type Class clause."""
        _logger.info(f"🚀 SQLGeneratorMixin.build_type_class_clause: FUNCTION STARTED with obj={obj}, table={table.name}")
        if isinstance(obj, REGEXTerm):
            # PostgreSQL regex support using ~ operator (MySQL uses REGEXP)
            return self.regex_op(table.c.klass, obj)
        elif isinstance(obj, list):
            return expression.or_(
                *[self.build_type_class_clause(o, table) for o in obj if o])
        elif obj is not None:
            return obj and table.c.klass == obj
        else:
            return None

    # Text search optimization methods
    def _detect_text_search_pattern(self, obj):
        """Detect various text search patterns (CONTAINS, REGEX, etc.)"""
        _logger.info(f"🚀 SQLGeneratorMixin._detect_text_search_pattern: FUNCTION STARTED with obj={obj}")
        if not TEXT_SEARCH_OPTIMIZATION_ENABLED:
            return None
            
        # Import URIRef here to avoid circular imports
        from rdflib import URIRef
            
        if isinstance(obj, REGEXTerm):
            # Extract the actual pattern from REGEXTerm
            pattern = str(obj)
            if len(pattern) >= TEXT_SEARCH_MIN_TERM_LENGTH:
                return {'type': 'regex', 'pattern': pattern, 'original': obj}
                
        elif isinstance(obj, Literal):
            # Check for literal text search patterns
            text = str(obj)
            if len(text) >= TEXT_SEARCH_MIN_TERM_LENGTH:
                return {'type': 'literal', 'pattern': text, 'original': obj}
                
        elif obj is not None and not isinstance(obj, URIRef):
            # Check for string patterns that might be text searches
            # Exclude URIRef objects as they are not text search patterns
            text = str(obj)
            if len(text) >= TEXT_SEARCH_MIN_TERM_LENGTH:
                # Simple heuristic: if it contains common words or is long enough
                if len(text) > 10 or any(word in text.lower() for word in ['happy', 'sad', 'good', 'bad']):
                    return {'type': 'string', 'pattern': text, 'original': obj}
                    
        return None

    def _build_trgm_optimized_clause(self, column, pattern, table):
        """Build clauses optimized for pg_trgm indexes"""
        _logger.info(f"🚀 SQLGeneratorMixin._build_trgm_optimized_clause: FUNCTION STARTED with column={column}, pattern={pattern}, table={table.name}")
        if self.engine.name == "postgresql":
            # Use PostgreSQL-specific optimizations
            if len(pattern) >= TEXT_SEARCH_MIN_TERM_LENGTH:
                # Use ILIKE for case-insensitive search with pg_trgm
                return column.ilike(f'%{pattern}%')
            else:
                # Fallback to exact match for short patterns
                return column == pattern
        else:
            # Fallback for other databases
            return column.like(f'%{pattern}%')

    def build_object_clause_optimized(self, obj, table, is_text_search=False):
        """Enhanced object clause with text search optimization"""
        _logger.info(f"🚀 SQLGeneratorMixin.build_object_clause_optimized: FUNCTION STARTED with obj={obj}, table={table.name}, is_text_search={is_text_search}")
        # Check if this is a text search pattern
        text_pattern = self._detect_text_search_pattern(obj)
        
        if text_pattern and is_text_search:
            # Use optimized text search clause
            return self._build_trgm_optimized_clause(
                table.c.object, 
                text_pattern['pattern'], 
                table
            )
        else:
            # Fall back to original implementation
            return self.build_object_clause(obj, table)
