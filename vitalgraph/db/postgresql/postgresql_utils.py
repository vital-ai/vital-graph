import logging
import time
from contextlib import contextmanager
from typing import Union, Tuple, Optional
from datetime import datetime

# RDFLib imports for term handling
from rdflib import URIRef, Literal, BNode
from rdflib.term import Identifier


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
    def determine_term_type(value: Union[Identifier, str, int, float, bool]) -> Tuple[str, Optional[str], Optional[int]]:
        """
        Determine the term type, language, and datatype for an RDF value.
        
        Uses RDFLib's native term classes for robust type detection.
        
        Args:
            value: RDF value (RDFLib term, string, or native Python type)
            
        Returns:
            tuple: (term_type, language, datatype_id) where:
                - term_type: 'U' for URI, 'L' for Literal, 'B' for Blank Node
                - language: Language tag for literals (e.g., 'en', 'fr') or None
                - datatype_id: Datatype term ID for typed literals or None
        """

            
        # Handle RDFLib term objects
        if isinstance(value, URIRef):
            return ('U', None, None)
        elif isinstance(value, BNode):
            return ('B', None, None)
        elif isinstance(value, Literal):
            # Extract language and datatype from RDFLib Literal
            # Check if it's actually a proper Literal with language attribute
            if hasattr(value, 'language'):
                language = str(value.language) if value.language else None
                datatype_id = None  # TODO: Handle datatype term ID lookup
                
                # DEBUG: Log language tag extraction for debugging
                if str(value) in ['John Smith', 'Jean Dupont', 'Juan García', 'Johann Schmidt']:
                    print(f"DEBUG: Processing literal '{value}' - has language attr: {hasattr(value, 'language')}, language: {repr(value.language)}, extracted: {repr(language)}")
                
                return ('L', language, datatype_id)
            else:
                # Fallback for objects that pass isinstance but don't have language attribute
                if str(value) in ['John Smith', 'Jean Dupont', 'Juan García', 'Johann Schmidt']:
                    print(f"DEBUG: Processing literal '{value}' - NO language attribute")
                return ('L', None, None)
        
        # Handle native Python types - convert to appropriate RDFLib terms
        elif isinstance(value, str):
            # Assume string literals unless they look like URIs
            if value.startswith(('http://', 'https://', 'ftp://', 'urn:', 'mailto:')) or '://' in value:
                return ('U', None, None)  # Treat as URI
            else:
                return ('L', None, None)  # Treat as string literal
        elif isinstance(value, bool):
            # Boolean literals
            return ('L', None, None)  # TODO: Add XSD boolean datatype
        elif isinstance(value, int):
            # Integer literals
            return ('L', None, None)  # TODO: Add XSD integer datatype
        elif isinstance(value, float):
            # Float literals
            return ('L', None, None)  # TODO: Add XSD double datatype
        elif isinstance(value, datetime):
            # DateTime literals
            return ('L', None, None)  # TODO: Add XSD dateTime datatype
        elif isinstance(value, bytes):
            # Base64 binary literals
            return ('L', None, None)  # TODO: Add XSD base64Binary datatype
        else:
            # Default to string literal for unknown types
            return ('L', None, None)
    
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
