import logging
import time
from contextlib import contextmanager
from typing import Union, Tuple, Optional, Dict
from datetime import datetime
import uuid
import hashlib

# RDFLib imports for term handling
from rdflib import URIRef, Literal, BNode
from rdflib.term import Identifier
from rdflib.namespace import XSD


def generate_term_uuid(term_text: str, term_type: str, lang: Optional[str] = None, datatype_id: Optional[int] = None) -> uuid.UUID:
    """
    Generate a deterministic UUID for an RDF term based on its components.
    
    This function creates a UUID v5 (namespace-based) using a consistent namespace
    and the term's text, type, language, and datatype ID. This ensures that
    identical terms always get the same UUID.
    
    Args:
        term_text: The term's text value
        term_type: The term type ('U' for URI, 'L' for literal, 'B' for blank node)
        lang: Language tag for literals (optional)
        datatype_id: Datatype ID for typed literals (optional)
        
    Returns:
        uuid.UUID: Deterministic UUID for the term
    """
    # Use a consistent namespace UUID for VitalGraph terms
    VITALGRAPH_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
    
    # Create a consistent string representation of the term
    components = [term_text, term_type]
    
    if lang is not None:
        components.append(f"lang:{lang}")
    
    if datatype_id is not None:
        components.append(f"datatype:{datatype_id}")
    
    # Join components with a separator that won't appear in normal term text
    term_string = "\x00".join(components)
    
    # Generate UUID v5 using the namespace and term string
    return uuid.uuid5(VITALGRAPH_NAMESPACE, term_string)


class REGEXTerm(str):
    """
    REGEXTerm can be used in any term slot and is interpreted as a request to
    perform a REGEX match (not a string comparison) using the value
    (pre-compiled) for checking matches against database terms.
    
    Inspired by RDFLib's REGEXMatching store plugin.
    """
    
    def __init__(self, expr):
        self.compiledExpr = re.compile(expr)
        self.pattern = expr
    
    def __reduce__(self):
        return (REGEXTerm, (self.pattern,))
    
    def match(self, text):
        """Check if the given text matches this regex pattern."""
        return self.compiledExpr.match(str(text)) is not None
    
    def __str__(self):
        return f"REGEXTerm({self.pattern})"


class PostgreSQLUtils:
    """
    Utility class for PostgreSQL RDF operations.
    
    Contains reusable utility methods for:
    - RDFLib term type detection and value extraction
    - Table naming and validation
    - Performance timing and logging
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize PostgreSQL utilities.
        
        Args:
            logger: Optional logger instance. If None, creates a new logger.
        """
        self.logger = logger or logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @contextmanager
    def time_operation(self, operation_name: str, details: str = ""):
        """
        Context manager for timing operations and logging performance metrics.
        
        Args:
            operation_name: Name of the operation being timed
            details: Additional details to include in the log message
        """
        start_time = time.time()
        detail_str = f" ({details})" if details else ""
        self.logger.debug(f"Starting {operation_name}{detail_str}")
        
        try:
            yield
        finally:
            end_time = time.time()
            duration = end_time - start_time
            duration_ms = duration * 1000
            
            if duration < 0.001:  # Less than 1ms
                duration_str = f"{duration_ms:.3f}ms"
            elif duration < 1.0:  # Less than 1 second
                duration_str = f"{duration_ms:.1f}ms"
            else:  # 1 second or more
                duration_str = f"{duration:.2f}s"
            
            self.logger.info(f"Completed {operation_name}{detail_str} in {duration_str}")
    
    @staticmethod
    def validate_space_id(space_id: str) -> None:
        """
        Validate space ID format.
        
        Args:
            space_id: Space identifier to validate
            
        Raises:
            ValueError: If space_id is invalid
        """
        if not space_id or not isinstance(space_id, str):
            raise ValueError("Space ID must be a non-empty string")
        if '__' in space_id:
            raise ValueError("Space ID cannot contain double underscores '__'")
        if not space_id.replace('_', '').replace('-', '').isalnum():
            raise ValueError("Space ID must contain only alphanumeric characters, hyphens, and underscores")
    
    @staticmethod
    def get_table_prefix(global_prefix: str, space_id: str) -> str:
        """
        Get table prefix for a specific space.
        
        Args:
            global_prefix: Global table prefix
            space_id: Space identifier
            
        Returns:
            str: Table prefix in format {global_prefix}__{space_id}__
        """
        PostgreSQLUtils.validate_space_id(space_id)
        return f"{global_prefix}__{space_id}__"
    
    @staticmethod
    def get_table_name(global_prefix: str, space_id: str, base_name: str) -> str:
        """
        Get full table name with space prefix.
        
        Args:
            global_prefix: Global table prefix
            space_id: Space identifier
            base_name: Base table name (e.g., 'term', 'rdf_quad')
            
        Returns:
            str: Full table name with prefix
        """
        return f"{PostgreSQLUtils.get_table_prefix(global_prefix, space_id)}{base_name}"
    
    @staticmethod
    def determine_term_type(value: Union[Identifier, str, int, float, bool]) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Determine the term type, language, and datatype URI for an RDF value.
        
        Uses RDFLib's native term classes for robust type detection.
        
        Args:
            value: RDF value (RDFLib term, string, or native Python type)
            
        Returns:
            tuple: (term_type, language, datatype_uri) where:
                - term_type: 'U' for URI, 'L' for Literal, 'B' for Blank Node
                - language: Language tag for literals (e.g., 'en', 'fr') or None
                - datatype_uri: Datatype URI for typed literals or None
        """
        from rdflib import XSD
        
        # Handle RDFLib term objects
        if isinstance(value, URIRef):
            return ('U', None, None)
        elif isinstance(value, BNode):
            return ('B', None, None)
        elif isinstance(value, Literal):
            # Extract language and datatype from RDFLib Literal
            language = str(value.language) if value.language else None
            
            # Extract datatype URI
            datatype_uri = None
            if value.datatype:
                datatype_uri = str(value.datatype)
            elif language:
                # Language-tagged literals have rdf:langString datatype
                datatype_uri = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#langString'
            else:
                # Plain literals default to xsd:string
                datatype_uri = str(XSD.string)
                
            return ('L', language, datatype_uri)
        
        # Handle native Python types - convert to appropriate RDFLib terms
        elif isinstance(value, str):
            # Assume string literals unless they look like URIs
            if value.startswith(('http://', 'https://', 'ftp://', 'urn:', 'mailto:')) or '://' in value:
                return ('U', None, None)  # Treat as URI
            else:
                return ('L', None, str(XSD.string))  # String literal with xsd:string datatype
        elif isinstance(value, bool):
            # Boolean literals
            return ('L', None, str(XSD.boolean))
        elif isinstance(value, int):
            # Integer literals
            return ('L', None, str(XSD.integer))
        elif isinstance(value, float):
            # Float literals
            return ('L', None, str(XSD.double))
        elif isinstance(value, datetime):
            # DateTime literals
            return ('L', None, str(XSD.dateTime))
        elif isinstance(value, bytes):
            # Base64 binary literals
            return ('L', None, str(XSD.base64Binary))
        else:
            # Default to string literal for unknown types
            return ('L', None, str(XSD.string))
    
    @staticmethod
    def extract_literal_value(value: Union[Identifier, str, int, float, bool]) -> str:
        """
        Extract the literal value from a potentially language-tagged or typed literal.
        
        Uses RDFLib's native term classes for robust value extraction.
        
        Args:
            value: RDF value (RDFLib term, string, or native Python type)
            
        Returns:
            str: The literal value as a string for storage
        """
        # Handle RDFLib term objects
        if isinstance(value, (URIRef, BNode)):
            return str(value)
        elif isinstance(value, Literal):
            # Extract the literal value from RDFLib Literal
            return str(value)
        
        # Handle native Python types
        elif isinstance(value, str):
            return value
        elif isinstance(value, bool):
            # Convert boolean to lowercase string (RDF standard)
            return str(value).lower()
        elif isinstance(value, (int, float)):
            # Convert numbers to string
            return str(value)
        elif isinstance(value, datetime):
            # Convert datetime to ISO format
            return value.isoformat()
        elif isinstance(value, bytes):
            # Convert bytes to base64 string
            import base64
            return base64.b64encode(value).decode('utf-8')
        else:
            # Default to string conversion for unknown types
            return str(value)
    
    @staticmethod
    def get_table_names(global_prefix: str, space_id: str) -> Dict[str, str]:
        """
        Get all table names for a specific space.
        
        Args:
            global_prefix: Global table prefix
            space_id: Space identifier
            
        Returns:
            Dict[str, str]: Dictionary mapping table types to full table names
        """
        prefix = PostgreSQLUtils.get_table_prefix(global_prefix, space_id)
        return {
            'term': f"{prefix}term",
            'rdf_quad': f"{prefix}rdf_quad",
            'namespace': f"{prefix}namespace",
            'datatype': f"{prefix}datatype"
        }
    
    @staticmethod
    def validate_global_prefix(global_prefix: str) -> None:
        """
        Validate global prefix format.
        
        Args:
            global_prefix: Global prefix to validate
            
        Raises:
            ValueError: If global_prefix is invalid
        """
        if not global_prefix or not isinstance(global_prefix, str):
            raise ValueError("Global prefix must be a non-empty string")
        if '__' in global_prefix:
            raise ValueError("Global prefix cannot contain double underscores '__'")
        if not global_prefix.replace('_', '').replace('-', '').isalnum():
            raise ValueError("Global prefix must contain only alphanumeric characters, hyphens, and underscores")


