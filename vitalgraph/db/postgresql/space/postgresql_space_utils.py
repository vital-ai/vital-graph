

from typing import Union, Tuple, Optional, Dict
from datetime import datetime

# RDFLib imports for term handling
from rdflib import URIRef, Literal, BNode
from rdflib.term import Identifier
from rdflib.namespace import XSD


class PostgreSQLSpaceUtils:
    """
    Utility class for PostgreSQL RDF space operations.
    
    Contains reusable utility methods for:
    - RDFLib term type detection and value extraction
    - Table naming and validation
    """
    
    @staticmethod
    def validate_space_id(space_id: str) -> None:
        """
        Validate space ID format and PostgreSQL identifier length constraints.
        
        Args:
            space_id: Space identifier to validate
            
        Raises:
            ValueError: If space_id is invalid or would cause PostgreSQL identifier length issues
        """
        if not space_id or not isinstance(space_id, str):
            raise ValueError("Space ID must be a non-empty string")
        if '__' in space_id:
            raise ValueError("Space ID cannot contain double underscores '__'")
        if not space_id.replace('_', '').replace('-', '').isalnum():
            raise ValueError("Space ID must contain only alphanumeric characters, hyphens, and underscores")
        
        # Check PostgreSQL identifier length constraints
        # PostgreSQL has a 63-character limit for identifiers
        # The longest generated identifier is an index name like:
        # idx_{global_prefix}__{space_id}___unlogged_term_text_gist_trgm
        # For global_prefix="vitalgraph1", this becomes:
        # idx_vitalgraph1__{space_id}___unlogged_term_text_gist_trgm
        # = "idx_vitalgraph1__" + space_id + "___unlogged_term_text_gist_trgm"
        # = 17 + len(space_id) + 42 = 59 + len(space_id)
        
        # Calculate actual maximum safe space_id length
        # Using actual measured components:
        # "idx_vitalgraph1__" = 17 chars
        # "___unlogged_term_text_gist_trgm" = 32 chars  
        # Total fixed: 17 + 32 = 49 chars
        # Remaining for space_id: 63 - 49 = 14 chars
        
        fixed_prefix = "idx_vitalgraph1__"  # 17 chars (worst case common prefix)
        fixed_suffix = "___unlogged_term_text_gist_trgm"  # 32 chars (longest suffix)
        max_space_id_len = 63 - len(fixed_prefix) - len(fixed_suffix)
        # 63 - 17 - 32 = 14 characters
        
        if len(space_id) > max_space_id_len:
            raise ValueError(
                f"Space ID '{space_id}' is too long ({len(space_id)} characters). "
                f"Maximum length is {max_space_id_len} characters to avoid PostgreSQL "
                f"identifier length limits (63 chars). Generated index names would be truncated "
                f"and cause conflicts. Use a shorter space ID."
            )
    
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
        PostgreSQLSpaceUtils.validate_space_id(space_id)
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
        return f"{PostgreSQLSpaceUtils.get_table_prefix(global_prefix, space_id)}{base_name}"
    
    @staticmethod
    def determine_term_type(value: Union[Identifier, str, int, float, bool]) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Determine the term type, language, and datatype URI for an RDF value.
        
        Uses RDFLib's native term classes for robust type detection.
        
        Args:
            value: RDF value (RDFLib term, string, or native Python type)
            
        Returns:
            Tuple[str, Optional[str], Optional[str]]: Tuple containing:
                - term_type: 'U' for URI, 'L' for Literal, 'B' for Blank Node
                - language: Language tag for literals (e.g., 'en', 'fr') or None
                - datatype_uri: Datatype URI for typed literals or None
        """
        # Handle RDFLib term objects
        if isinstance(value, URIRef):
            return ('U', None, None)  # URI reference
        elif isinstance(value, BNode):
            return ('B', None, None)  # Blank node
        elif isinstance(value, Literal):
            # Extract language and datatype from RDFLib Literal
            language = str(value.language) if value.language else None
            datatype_uri = str(value.datatype) if value.datatype else None
            return ('L', language, datatype_uri)  # Literal with potential language/datatype
        
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
        prefix = PostgreSQLSpaceUtils.get_table_prefix(global_prefix, space_id)
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


# utility functions used by other functions

