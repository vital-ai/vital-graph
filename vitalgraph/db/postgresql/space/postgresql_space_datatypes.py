import logging
from typing import Dict, List, Optional, Any, Union, Tuple, Set
import psycopg.rows
from .postgresql_space_terms import PostgreSQLSpaceTerms


class PostgreSQLSpaceDatatypes:
    """
    PostgreSQL datatype management for RDF spaces.
    
    Handles datatype caches, standard datatype insertion, and datatype ID resolution
    for PostgreSQL-backed RDF spaces.
    """
    
    def __init__(self, space_impl):
        """
        Initialize datatype management with reference to space implementation.
        
        Args:
            space_impl: Reference to PostgreSQLSpaceImpl instance
        """
        self.space_impl = space_impl
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def get_datatype_cache(self, space_id: str) -> 'PostgreSQLCacheDatatype':
        """
        Get the datatype cache for a specific space, creating it if necessary.
        Each space has its own datatype cache that is initialized when the space is created.
        
        Args:
            space_id: Space identifier
            
        Returns:
            PostgreSQLCacheDatatype: The datatype cache for the specified space
        """
        if space_id not in self.space_impl._datatype_caches:
            from ..postgresql_cache_datatype import PostgreSQLCacheDatatype
            self.space_impl._datatype_caches[space_id] = PostgreSQLCacheDatatype()
        return self.space_impl._datatype_caches[space_id]
    
    def get_standard_datatypes(self) -> List[Tuple[str, str]]:
        """
        Get list of standard XSD and RDF datatype URIs to insert into datatype table.
        
        Returns:
            List of (datatype_uri, datatype_name) tuples
        """
        return [
            # XSD datatypes
            ('http://www.w3.org/2001/XMLSchema#string', 'string'),
            ('http://www.w3.org/2001/XMLSchema#boolean', 'boolean'),
            ('http://www.w3.org/2001/XMLSchema#decimal', 'decimal'),
            ('http://www.w3.org/2001/XMLSchema#integer', 'integer'),
            ('http://www.w3.org/2001/XMLSchema#double', 'double'),
            ('http://www.w3.org/2001/XMLSchema#float', 'float'),
            ('http://www.w3.org/2001/XMLSchema#date', 'date'),
            ('http://www.w3.org/2001/XMLSchema#time', 'time'),
            ('http://www.w3.org/2001/XMLSchema#dateTime', 'dateTime'),
            ('http://www.w3.org/2001/XMLSchema#gYear', 'gYear'),
            ('http://www.w3.org/2001/XMLSchema#gMonth', 'gMonth'),
            ('http://www.w3.org/2001/XMLSchema#gDay', 'gDay'),
            ('http://www.w3.org/2001/XMLSchema#gYearMonth', 'gYearMonth'),
            ('http://www.w3.org/2001/XMLSchema#gMonthDay', 'gMonthDay'),
            ('http://www.w3.org/2001/XMLSchema#duration', 'duration'),
            ('http://www.w3.org/2001/XMLSchema#yearMonthDuration', 'yearMonthDuration'),
            ('http://www.w3.org/2001/XMLSchema#dayTimeDuration', 'dayTimeDuration'),
            ('http://www.w3.org/2001/XMLSchema#byte', 'byte'),
            ('http://www.w3.org/2001/XMLSchema#short', 'short'),
            ('http://www.w3.org/2001/XMLSchema#int', 'int'),
            ('http://www.w3.org/2001/XMLSchema#long', 'long'),
            ('http://www.w3.org/2001/XMLSchema#unsignedByte', 'unsignedByte'),
            ('http://www.w3.org/2001/XMLSchema#unsignedShort', 'unsignedShort'),
            ('http://www.w3.org/2001/XMLSchema#unsignedInt', 'unsignedInt'),
            ('http://www.w3.org/2001/XMLSchema#unsignedLong', 'unsignedLong'),
            ('http://www.w3.org/2001/XMLSchema#positiveInteger', 'positiveInteger'),
            ('http://www.w3.org/2001/XMLSchema#nonNegativeInteger', 'nonNegativeInteger'),
            ('http://www.w3.org/2001/XMLSchema#negativeInteger', 'negativeInteger'),
            ('http://www.w3.org/2001/XMLSchema#nonPositiveInteger', 'nonPositiveInteger'),
            ('http://www.w3.org/2001/XMLSchema#hexBinary', 'hexBinary'),
            ('http://www.w3.org/2001/XMLSchema#base64Binary', 'base64Binary'),
            ('http://www.w3.org/2001/XMLSchema#anyURI', 'anyURI'),
            ('http://www.w3.org/2001/XMLSchema#language', 'language'),
            ('http://www.w3.org/2001/XMLSchema#normalizedString', 'normalizedString'),
            ('http://www.w3.org/2001/XMLSchema#token', 'token'),
            ('http://www.w3.org/2001/XMLSchema#NMTOKEN', 'NMTOKEN'),
            ('http://www.w3.org/2001/XMLSchema#Name', 'Name'),
            ('http://www.w3.org/2001/XMLSchema#NCName', 'NCName'),
            
            # RDF datatypes
            ('http://www.w3.org/1999/02/22-rdf-syntax-ns#XMLLiteral', 'XMLLiteral'),
            ('http://www.w3.org/1999/02/22-rdf-syntax-ns#HTML', 'HTML'),
            ('http://www.w3.org/1999/02/22-rdf-syntax-ns#langString', 'langString'),
            
            # Additional common datatypes
            ('http://www.w3.org/2001/XMLSchema#ENTITY', 'ENTITY'),
            ('http://www.w3.org/2001/XMLSchema#ID', 'ID'),
            ('http://www.w3.org/2001/XMLSchema#IDREF', 'IDREF')
        ]
    
    async def insert_standard_datatypes(self, space_id: str) -> bool:
        """
        Insert standard datatype URIs into the datatype table for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            standard_datatypes = self.get_standard_datatypes()
            table_names = self.space_impl._get_table_names(space_id)
            datatype_table = table_names['datatype']
            term_table = table_names['term']
            
            # Use async context manager with pooled connection
            async with self.space_impl.get_db_connection() as conn:
                try:
                    with conn.cursor() as cursor:
                        for datatype_uri, datatype_name in standard_datatypes:
                            # Generate UUID for the datatype term
                            term_uuid = PostgreSQLSpaceTerms.generate_term_uuid(datatype_uri, 'U')
                            
                            # Insert into term table first
                            cursor.execute(f"""
                                INSERT INTO {term_table} (term_uuid, term_text, term_type)
                                VALUES (%s, %s, %s)
                                ON CONFLICT (term_uuid) DO NOTHING
                            """, (term_uuid, datatype_uri, 'U'))
                            
                            # Insert into datatype table (datatype_id is auto-generated BIGSERIAL)
                            cursor.execute(f"""
                                INSERT INTO {datatype_table} (datatype_uri, datatype_name)
                                VALUES (%s, %s)
                                ON CONFLICT (datatype_uri) DO NOTHING
                            """, (datatype_uri, datatype_name))
                        
                        conn.commit()
                        self.logger.info(f"✅ Inserted {len(standard_datatypes)} standard datatypes for space '{space_id}'")
                        return True
                        # Connection automatically returned to pool when context exits
                        
                except Exception as e:
                    conn.rollback()
                    raise e
                
        except Exception as e:
            self.logger.error(f"❌ Failed to insert standard datatypes for space '{space_id}': {e}")
            return False
    
    async def ensure_datatype_cache_loaded(self, space_id: str) -> None:
        """
        Ensure datatype cache is loaded for a specific space.
        This method loads datatypes from the database into the shared cache if not already loaded.
        
        Args:
            space_id: Space identifier
        """
        # Check if we already have datatypes loaded
        if not self.space_impl._datatype_cache_loaded:
            await self.load_all_datatypes_into_cache()
            self.space_impl._datatype_cache_loaded = True
    
    async def load_all_datatypes_into_cache(self) -> None:
        """
        Load all datatypes from all spaces into the shared datatype cache.
        This is more efficient than loading per-space since datatypes are shared.
        """
        try:
            async with self.space_impl.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Get all datatype tables (they follow the pattern: {prefix}_{space_id}_datatype)
                await cursor.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_name LIKE %s AND table_schema = 'public'
                """, (f"{self.space_impl.global_prefix}_%_datatype",))
                
                datatype_tables = await cursor.fetchall()
                
                # Load datatypes from all tables
                for (table_name,) in datatype_tables:
                    await cursor.execute(f"""
                        SELECT datatype_id, datatype_uri 
                        FROM {table_name}
                        ORDER BY datatype_id
                    """)
                    
                    datatypes = await cursor.fetchall()
                    
                    # Add to cache
                    for datatype_id, datatype_uri in datatypes:
                        self.space_impl._datatype_cache.put(datatype_uri, datatype_id)
                    
                    self.logger.debug(f"Loaded {len(datatypes)} datatypes from table {table_name}")
                
                self.logger.info(f"Loaded datatypes into cache from {len(datatype_tables)} tables")
                
        except Exception as e:
            self.logger.error(f"Error loading datatypes into cache: {e}")
            raise
    
    async def load_datatype_cache(self, space_id: str) -> 'PostgreSQLCacheDatatype':
        """
        Get the datatype cache for a specific space.
        This method ensures the cache is loaded and returns the shared instance.
        
        Args:
            space_id: Space identifier
            
        Returns:
            PostgreSQLCacheDatatype instance populated with datatypes
        """
        await self.ensure_datatype_cache_loaded(space_id)
        return self.space_impl._datatype_cache
    
    async def get_or_create_datatype_id(self, space_id: str, datatype_uri: str) -> int:
        """
        Get or create a datatype ID for the given URI.
        This method first checks the cache, then the database, and creates a new entry if needed.
        
        Args:
            space_id: Space identifier
            datatype_uri: The datatype URI to resolve
            
        Returns:
            The datatype ID (BIGINT)
        """
        
        # Check cache first
        datatype_id = self.space_impl._datatype_cache.get_id_by_uri(datatype_uri)
        if datatype_id is not None:
            return datatype_id
            
        # Not in cache, check database and insert if needed
        table_names = self.space_impl._get_table_names(space_id)
            
        async with self.space_impl.get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Try to insert the datatype (will be ignored if it already exists)
            await cursor.execute(f"""
                INSERT INTO {table_names['datatype']} (datatype_uri, datatype_name)
                VALUES (%s, %s)
                ON CONFLICT (datatype_uri) DO NOTHING
            """, (datatype_uri, datatype_uri.split('#')[-1] if '#' in datatype_uri else datatype_uri.split('/')[-1]))
            
            # Get the datatype_id
            await cursor.execute(f"""
                SELECT datatype_id FROM {table_names['datatype']}
                WHERE datatype_uri = %s
            """, (datatype_uri,))
            
            row = await cursor.fetchone()
            if row:
                datatype_id = row[0]
                # Add to cache for future use
                self.space_impl._datatype_cache.put(datatype_uri, datatype_id)
                return datatype_id
            else:
                raise ValueError(f"Failed to get or create datatype ID for URI: {datatype_uri}")
    
    async def resolve_datatype_ids_batch(self, space_id: str, datatype_uris: set) -> Dict[str, int]:
        """
        Resolve datatype URIs to IDs, inserting unknown datatypes as needed.
        
        Args:
            space_id: Space identifier for the datatype table
            datatype_uris: Set of datatype URIs to resolve
            
        Returns:
            Dictionary mapping datatype URIs to their BIGINT IDs
        """
        if not datatype_uris:
            return {}
            
        # Step 1: Check space-specific cache first
        datatype_cache = self.get_datatype_cache(space_id)
        cache_results = datatype_cache.get_datatype_ids_batch(list(datatype_uris))
        result = {}
        missing_uris = []
        
        for uri, cached_id in cache_results.items():
            if cached_id is not None:
                result[uri] = cached_id
            else:
                missing_uris.append(uri)
        
        # Step 2: Query database for missing datatypes and insert unknown ones
        if missing_uris:
            try:
                # Get table names for this space (already includes unlogged suffix if configured)
                table_names = self.space_impl._get_table_names(space_id)
                datatype_table = table_names['datatype']
                
                # Use async context manager with pooled connection
                async with self.space_impl.get_db_connection() as conn:
                    # Use default tuple rows for better bulk performance (no dict overhead)
                    with conn.cursor() as cursor:
                        
                        # Query for existing datatypes
                        missing_placeholders = ','.join(['%s'] * len(missing_uris))
                        cursor.execute(
                            f"SELECT datatype_uri, datatype_id FROM {datatype_table} WHERE datatype_uri IN ({missing_placeholders})",
                            list(missing_uris)
                        )
                        found_datatypes = cursor.fetchall()
                        still_missing = set(missing_uris)
                        
                        # Add found datatypes to result and cache (using tuple indexing for performance)
                        for row in found_datatypes:
                            uri, datatype_id = row[0], row[1]  # tuple access: [datatype_uri, datatype_id]
                            result[uri] = datatype_id
                            datatype_cache.put(uri, datatype_id)
                            still_missing.discard(uri)
                        
                        # Insert completely unknown datatypes
                        if still_missing:
                            self.logger.info(f"Inserting {len(still_missing)} unknown datatypes: {list(still_missing)}")
                            
                            # Insert new datatypes
                            cursor.executemany(
                                f"INSERT INTO {datatype_table} (datatype_uri, datatype_name) VALUES (%s, %s)",
                                [(uri, None) for uri in still_missing]
                            )
                            
                            # Get the newly inserted datatypes (create placeholders for still_missing)
                            still_missing_placeholders = ','.join(['%s'] * len(still_missing))
                            cursor.execute(
                                f"SELECT datatype_uri, datatype_id FROM {datatype_table} WHERE datatype_uri IN ({still_missing_placeholders})",
                                list(still_missing)
                            )
                            new_datatype_rows = cursor.fetchall()
                            for row in new_datatype_rows:
                                uri, datatype_id = row[0], row[1]  # tuple access: [datatype_uri, datatype_id]
                                result[uri] = datatype_id
                                datatype_cache.put(uri, datatype_id)
                            
                        conn.commit()
                        # Connection automatically returned to pool when context exits
                        
            except Exception as e:
                self.logger.error(f"Error resolving datatype IDs: {e}")
                # Return partial results even if there was an error
                
        return result
    

    async def initialize_space_datatype_cache_sync(self, space_id: str) -> None:
        """
        Initialize the datatype cache for a specific space by loading standard datatypes
        and any existing datatypes from the database (synchronous version).
        
        Args:
            space_id: Space identifier
        """
        try:
            self.logger.debug(f"DEBUG: Starting datatype cache initialization for space '{space_id}'")
            
            # Get the datatype cache for this space
            self.logger.debug("DEBUG: Getting datatype cache")
            datatype_cache = self.get_datatype_cache(space_id)
            self.logger.debug(f"DEBUG: Got datatype cache: {type(datatype_cache)}")
            
            # Get table names for this space (already includes unlogged suffix if configured)
            self.logger.debug("DEBUG: Getting table names")
            table_names = self.space_impl._get_table_names(space_id)
            datatype_table = table_names['datatype']
            self.logger.debug(f"DEBUG: Got datatype table name: {datatype_table}")
            
            # Insert standard datatypes if they don't exist
            self.logger.debug("DEBUG: Getting standard datatypes")
            standard_datatypes = self.get_standard_datatypes()
            self.logger.debug(f"DEBUG: Got {len(standard_datatypes)} standard datatypes")
            
            # Use async context manager with pooled connection
            async with self.space_impl.get_db_connection() as conn:
                # Set row factory to return dict-like rows instead of tuples
                conn.row_factory = psycopg.rows.dict_row
                with conn.cursor() as cursor:
                    
                    # Insert standard datatypes (will be ignored if they already exist)
                    for datatype_uri, datatype_name in standard_datatypes:
                        cursor.execute(
                            f"INSERT INTO {datatype_table} (datatype_uri, datatype_name) VALUES (%s, %s) ON CONFLICT (datatype_uri) DO NOTHING",
                            (datatype_uri, datatype_name)
                        )
                    
                    conn.commit()
                    
                    # Load all datatypes from the database into the cache
                    cursor.execute(f"SELECT datatype_uri, datatype_id FROM {datatype_table}")
                    all_datatypes = cursor.fetchall()
                    
                    # Populate the cache
                    for row in all_datatypes:
                        uri, datatype_id = row['datatype_uri'], row['datatype_id']
                        datatype_cache.put(uri, datatype_id)
                    
                    self.logger.info(f"Initialized datatype cache for space '{space_id}' with {len(all_datatypes)} datatypes")
                    # Connection automatically returned to pool when context exits
                    
        except Exception as e:
            self.logger.error(f"Error initializing datatype cache for space '{space_id}': {e}")
            raise
