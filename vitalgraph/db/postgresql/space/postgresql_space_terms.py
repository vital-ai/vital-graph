import logging
import uuid
from typing import Optional, Tuple, List, Dict
from datetime import datetime
import psycopg.rows

# RDFLib imports for term handling
from rdflib import URIRef, Literal, BNode
from rdflib.term import Identifier


class PostgreSQLSpaceTerms:
    """
    PostgreSQL term management for RDF spaces.
    
    Handles all term-related operations including adding, retrieving, and deleting terms,
    as well as term UUID generation and datatype processing.
    """
    
    def __init__(self, space_impl):
        """
        Initialize the terms manager with a reference to the space implementation.
        
        Args:
            space_impl: PostgreSQLSpaceImpl instance for accessing other space methods
        """
        self.space_impl = space_impl
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @staticmethod
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
    
    def _resolve_term_info(self, term: Identifier) -> Tuple[str, str, Optional[str], Optional[int]]:
        """
        Resolve an RDF term to its database representation.
        
        Args:
            term: RDFLib term (URIRef, Literal, BNode)
            
        Returns:
            tuple: (term_text, term_type, lang, datatype_id)
        """
        if isinstance(term, URIRef):
            return (str(term), 'U', None, None)
        elif isinstance(term, Literal):
            lang = term.language if term.language else None
            # For now, we'll set datatype_id to None and handle datatypes later
            datatype_id = None            
            return (str(term), 'L', lang, datatype_id)
        elif isinstance(term, BNode):
            return (str(term), 'B', None, None)
        else:
            # Fallback for any other term type
            return (str(term), 'U', None, None)
    
    async def _process_term_with_datatype(self, space_id: str, term_value: str, term_type: str, lang: Optional[str], datatype_uri: Optional[str]) -> Tuple[str, str, Optional[str], Optional[int]]:
        """
        Helper method to process a term and resolve its datatype ID using the space-specific cache.
        
        Args:
            space_id: Space identifier for the datatype cache
            term_value: The term value/text
            term_type: The term type ('U', 'L', 'B', 'G')
            lang: Language tag for literals
            datatype_uri: Datatype URI for literals
            
        Returns:
            Tuple of (term_value, term_type, lang, datatype_id)
        """
        datatype_id = None
        if datatype_uri and term_type == 'L':
            # Use the space_impl's datatype management to resolve the datatype ID
            datatype_id = await self.space_impl.datatypes.get_or_create_datatype_id(space_id, datatype_uri)
            self.logger.debug(f"Resolved datatype '{datatype_uri}' to ID: {datatype_id}")
        
        return (term_value, term_type, lang, datatype_id)
    
    async def add_term(self, space_id: str, term_text: str, term_type: str, 
                      lang: Optional[str] = None, datatype_id: Optional[int] = None) -> Optional[str]:
        """
        Add a term to the terms dictionary for a specific space using UUID-based approach.
        
        Args:
            space_id: Space identifier
            term_text: The term text (URI, literal value, etc.)
            term_type: Term type ('U'=URI, 'L'=Literal, 'B'=BlankNode, 'G'=Graph)
            lang: Language tag for literals
            datatype_id: Datatype ID for literals
            
        Returns:
            str: Term UUID if successful, None otherwise
        """
        try:
            # Import here to avoid circular imports
            # Use the static method from this class
            generate_term_uuid = PostgreSQLSpaceTerms.generate_term_uuid
            
            # Generate deterministic UUID for the term
            term_uuid = generate_term_uuid(term_text, term_type, lang, datatype_id)
            
            # Get table names
            table_names = self.space_impl._get_table_names(space_id)
            
            async with self.space_impl.get_db_connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                cursor = conn.cursor()
                
                # Check if term already exists
                await cursor.execute(
                    f"SELECT term_uuid FROM {table_names['term']} WHERE term_uuid = %s",
                    (str(term_uuid),)
                )
                existing = await cursor.fetchone()
                
                if existing:
                    self.logger.debug(f"Term '{term_text}' already exists in space '{space_id}' with UUID: {term_uuid}")
                    return str(term_uuid)
                
                # Insert new term
                await cursor.execute(
                    f"""
                    INSERT INTO {table_names['term']} 
                    (term_uuid, term_text, term_type, lang, datatype_id, created_time)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (term_uuid, term_text, term_type, lang, datatype_id, datetime.utcnow())
                )
                conn.commit()
                
                self.logger.debug(f"Added term '{term_text}' to space '{space_id}' with UUID: {term_uuid}")
                return str(term_uuid)
                
        except Exception as e:
            self.logger.error(f"Error adding term to space '{space_id}': {e}")
            return None
    
    async def get_term_uuid(self, space_id: str, term_text: str, term_type: str, 
                           lang: Optional[str] = None, datatype_id: Optional[int] = None) -> Optional[str]:
        """
        Get term UUID for existing term in a specific space using datatype-aware approach.
        
        This method is maintained for backward compatibility but now uses the new
        datatype-aware infrastructure internally.
        
        Args:
            space_id: Space identifier
            term_text: The term text
            term_type: Term type ('U'=URI, 'L'=Literal, 'B'=BlankNode, 'G'=Graph)
            lang: Language tag for literals
            datatype_id: Datatype ID for literals
            
        Returns:
            str: Term UUID if found, None otherwise
        """
        try:
            # Import here to avoid circular imports
            # Use the static method from this class
            generate_term_uuid = PostgreSQLSpaceTerms.generate_term_uuid
            term_uuid = generate_term_uuid(term_text, term_type, lang, datatype_id)
            
            # Get table names
            table_names = self.space_impl._get_table_names(space_id)
            
            async with self.space_impl.get_db_connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                cursor = conn.cursor()
                
                # Check if term exists
                cursor.execute(
                    f"SELECT term_uuid FROM {table_names['term']} WHERE term_uuid = %s",
                    (str(term_uuid),)
                )
                result = cursor.fetchone()
                
                return str(term_uuid) if result else None
                
        except Exception as e:
            self.logger.error(f"Error getting term UUID from space '{space_id}': {e}")
            return None
    
    async def get_term_uuid_from_rdf_value(self, space_id: str, rdf_value) -> Optional[str]:
        """
        Get term UUID for existing term from an RDF value using datatype-aware approach.
        
        This method uses the new datatype cache system to properly resolve and match
        datatype IDs for literal terms.
        
        Args:
            space_id: Space identifier
            rdf_value: RDF value (URI, literal, or blank node)
            
        Returns:
            str: Term UUID if found, None otherwise
        """
        try:
            # Resolve term info using the existing method
            term_value, term_type, lang, _ = self._resolve_term_info(rdf_value)
            
            # For literals with datatypes, resolve the datatype ID
            datatype_uri = None
            if isinstance(rdf_value, Literal) and rdf_value.datatype:
                datatype_uri = str(rdf_value.datatype)
            
            # Process term with datatype to get the proper datatype_id
            term_value, term_type, lang, datatype_id = await self._process_term_with_datatype(
                space_id, term_value, term_type, lang, datatype_uri
            )
            
            # Import here to avoid circular imports
            # Use the static method from this class
            generate_term_uuid = PostgreSQLSpaceTerms.generate_term_uuid
            term_uuid = generate_term_uuid(term_value, term_type, lang, datatype_id)
            
            # Get table names
            table_names = self.space_impl._get_table_names(space_id)
            
            async with self.space_impl.get_db_connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                cursor = conn.cursor()
                
                cursor.execute(
                    f"SELECT term_uuid FROM {table_names['term']} WHERE term_uuid = %s",
                    (str(term_uuid),)
                )
                result = cursor.fetchone()
                
                return str(term_uuid) if result else None
                
        except Exception as e:
            self.logger.error(f"Error getting term UUID from RDF value in space '{space_id}': {e}")
            return None
    
    async def delete_term(self, space_id: str, term_text: str, term_type: str, 
                         lang: Optional[str] = None, datatype_id: Optional[int] = None) -> bool:
        """
        Delete a term from a specific space using UUID-based approach.
        
        Note: This will only delete the term if it's not referenced by any quads.
        Use with caution as this could break referential integrity if not checked properly.
        
        Args:
            space_id: Space identifier
            term_text: The term text
            term_type: Term type ('U'=URI, 'L'=Literal, 'B'=BlankNode, 'G'=Graph)
            lang: Language tag for literals
            datatype_id: Datatype ID for literals
            
        Returns:
            bool: True if term was deleted, False otherwise
        """
        try:
            # Import here to avoid circular imports
            # Use the static method from this class
            generate_term_uuid = PostgreSQLSpaceTerms.generate_term_uuid
            term_uuid = generate_term_uuid(term_text, term_type, lang, datatype_id)
            
            # Get table names
            table_names = self.space_impl._get_table_names(space_id)
            
            async with self.space_impl.get_db_connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                cursor = conn.cursor()
                
                # Check if term is referenced by any quads
                await cursor.execute(
                    f"""
                    SELECT COUNT(*) as ref_count FROM {table_names['rdf_quad']} 
                    WHERE subject_uuid = %s OR predicate_uuid = %s OR object_uuid = %s OR context_uuid = %s
                    """,
                    (str(term_uuid), str(term_uuid), str(term_uuid), str(term_uuid))
                )
                ref_result = await cursor.fetchone()
                
                if ref_result and ref_result['ref_count'] > 0:
                    self.logger.warning(f"Cannot delete term '{term_text}' from space '{space_id}': still referenced by {ref_result['ref_count']} quads")
                    return False
                
                # Delete the term
                await cursor.execute(
                    f"DELETE FROM {table_names['term']} WHERE term_uuid = %s",
                    (str(term_uuid),)
                )
                
                deleted_count = cursor.rowcount
                conn.commit()
                
                if deleted_count > 0:
                    self.logger.debug(f"Deleted term '{term_text}' from space '{space_id}' with UUID: {term_uuid}")
                    return True
                else:
                    self.logger.debug(f"No term deleted from space '{space_id}' with UUID: {term_uuid}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error deleting term from space '{space_id}': {e}")
            return False
    
    async def batch_lookup_term_uuids(self, space_id: str, terms: List[str], 
                                     term_cache=None) -> Dict[str, str]:
        """
        Batch lookup term UUIDs using efficient SQL batch query.
        
        Args:
            space_id: Space identifier
            terms: List of term strings to lookup
            term_cache: Optional term cache for performance
            
        Returns:
            Dictionary mapping term strings to UUIDs
        """
        if not terms:
            return {}
        
        # Check cache first if available
        result = {}
        remaining_terms = terms.copy()
        
        if term_cache:
            cached_results = term_cache.get_batch(terms)
            result.update(cached_results)
            remaining_terms = [term for term in terms if term not in cached_results]
        
        if not remaining_terms:
            return result
        
        # Get table names
        table_names = self.space_impl._get_table_names(space_id)
        
        # Batch lookup remaining terms with SQL
        if remaining_terms:
            try:
                async with self.space_impl.get_db_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Use parameterized query with IN clause for batch lookup
                    placeholders = ','.join(['%s'] * len(remaining_terms))
                    sql = f"""
                        SELECT term_uuid, term_text, term_type 
                        FROM {table_names['term']} 
                        WHERE term_text IN ({placeholders})
                    """
                    
                    cursor.execute(sql, remaining_terms)
                    rows = cursor.fetchall()
                    
                    # Process results
                    for row in rows:
                        term_uuid, term_text, term_type = row
                        result[term_text] = str(term_uuid)
                        
                        # Update cache if available
                        if term_cache:
                            term_key = (term_text, term_type)
                            term_cache.put_term_uuid(term_key, str(term_uuid))
                            
            except Exception as e:
                self.logger.warning(f"Batch term lookup failed: {e}")
                # If batch fails, return what we have from cache
        
        return result

    def term_to_db_info(self, term):
        """
        Convert term to database info for query processing.
        
        This method was originally nested in the quads() method but is now
        extracted for better organization.
        
        Args:
            term: RDF term to convert
            
        Returns:
            tuple: (term_text, term_type, lang, datatype_id)
        """
        if hasattr(term, 'term_text'):
            # Already a database term
            return term.term_text, getattr(term, 'term_type', 'U'), getattr(term, 'lang', None), getattr(term, 'datatype_id', None)
        else:
            # Convert RDF term
            return self._resolve_term_info(term)
    
    def db_to_rdflib_term(self, text, term_type, lang=None, datatype_id=None):
        """
        Convert database info to RDFLib term for result processing.
        
        This method was originally nested in the quads() method but is now
        extracted for better organization.
        
        Args:
            text: Term text
            term_type: Term type ('U', 'L', 'B', 'G')
            lang: Language tag for literals
            datatype_id: Datatype ID for literals
            
        Returns:
            RDFLib term (URIRef, Literal, or BNode)
        """
        if term_type == 'U':
            return URIRef(text)
        elif term_type == 'L':
            if lang:
                return Literal(text, lang=lang)
            elif datatype_id:
                # TODO: Resolve datatype_id to datatype URI
                return Literal(text)
            else:
                return Literal(text)
        elif term_type == 'B':
            return BNode(text)
        else:
            # Fallback to URIRef
            return URIRef(text)
