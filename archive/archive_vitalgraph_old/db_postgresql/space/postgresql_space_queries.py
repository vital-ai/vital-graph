import logging
import re
from typing import Optional, Any
import psycopg
from ..postgresql_log_utils import PostgreSQLLogUtils
from .postgresql_space_utils import PostgreSQLSpaceUtils


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


class PostgreSQLSpaceQueries:
    """
    Handles query operations for PostgreSQL RDF spaces.
    """
    
    def __init__(self, space_impl):
        """
        Initialize the queries handler with a reference to the space implementation.
        
        Args:
            space_impl: The PostgreSQLSpaceImpl instance
        """
        self.space_impl = space_impl
        self.logger = logging.getLogger(__name__)
    
    async def quads(self, space_id: str, quad_pattern: tuple, context: Optional[Any] = None):
        """
        A generator over all the quads matching the pattern. Pattern can include any objects
        for comparing against nodes in the store, including URIRef, Literal, BNode, Variable, 
        and REGEXTerm for regex pattern matching.
        
        This follows the RDFLib triples() pattern but for quads (subject, predicate, object, context).
        Used by SPARQL query implementation for quad pattern matching.
        
        REGEXTerm Support:
        - REGEXTerm instances in any position enable PostgreSQL regex matching (~)
        - Uses PostgreSQL's built-in regex engine for efficient pattern matching
        - Leverages pg_trgm indexes for optimized regex query performance
        - Supports full POSIX regex syntax in pattern strings
        
        Args:
            space_id: Space identifier
            quad_pattern: 4-tuple of (subject, predicate, object, context) patterns
            context: Optional context (not used in current implementation)
            
        Yields:
            tuple: (quad, context_iterator) where quad is (s, p, o, c) and 
                   context_iterator is a function that yields the context
        """
        try:
            self.logger.debug(f"🔍 DEBUG: Starting quads() method for space_id='{space_id}', pattern={quad_pattern}")
            
            PostgreSQLSpaceUtils.validate_space_id(space_id)
            self.logger.debug(f"🔍 DEBUG: Space ID validation passed")
            
            # Extract pattern components
            subject, predicate, obj, graph = quad_pattern
            self.logger.debug(f"🔍 DEBUG: Pattern components - s:{subject}, p:{predicate}, o:{obj}, g:{graph}")
            
            # Get table names (already includes unlogged suffix if configured)
            table_names = self.space_impl._get_table_names(space_id)
            term_table = table_names['term']
            quad_table = table_names['rdf_quad']
            self.logger.debug(f"🔍 DEBUG: Table names - term:{term_table}, quad:{quad_table}")
            
            with self.space_impl.utils.time_operation("quads_query", f"pattern {quad_pattern} in space '{space_id}'"):
                self.logger.debug(f"🔍 DEBUG: Starting time operation and connection")
                # Use async context manager with dict pool for query result compatibility
                async with self.space_impl.core.get_dict_connection() as conn:
                    # Connection already configured with dict_row factory
                    self.logger.debug(f"🔍 DEBUG: Got connection: {type(conn)}")
                    with conn.cursor() as cursor:
                        self.logger.debug(f"🔍 DEBUG: Got cursor: {type(cursor)}")
                        # Use UUID-based schema column names
                        join_columns = {
                            'subject': ('quad.subject_uuid', 's_term.term_uuid'),
                            'predicate': ('quad.predicate_uuid', 'p_term.term_uuid'),
                            'object': ('quad.object_uuid', 'o_term.term_uuid'),
                            'context': ('quad.context_uuid', 'c_term.term_uuid')
                        }
                        
                        # Build the SQL query with appropriate joins
                        base_query = f"""
                        SELECT 
                            s_term.term_text as subject_text,
                            s_term.term_type as subject_type,
                            s_term.lang as subject_lang,
                            s_term.datatype_id as subject_datatype_id,
                            
                            p_term.term_text as predicate_text,
                            p_term.term_type as predicate_type,
                            
                            o_term.term_text as object_text,
                            o_term.term_type as object_type,
                            o_term.lang as object_lang,
                            o_term.datatype_id as object_datatype_id,
                            
                            c_term.term_text as context_text,
                            c_term.term_type as context_type
                        FROM {quad_table} quad
                        JOIN {term_table} s_term ON {join_columns['subject'][0]} = {join_columns['subject'][1]}
                        JOIN {term_table} p_term ON {join_columns['predicate'][0]} = {join_columns['predicate'][1]}
                        JOIN {term_table} o_term ON {join_columns['object'][0]} = {join_columns['object'][1]}
                        JOIN {term_table} c_term ON {join_columns['context'][0]} = {join_columns['context'][1]}
                        """
                    
                        # Build WHERE conditions and parameters
                        where_conditions = []
                        params = []
                        
                        # Helper function to check if a pattern element is a variable/unbound
                        def is_unbound(element):
                            return element is None or (hasattr(element, '__class__') and 
                                                     element.__class__.__name__ == 'Variable')
                        
                        # Helper function to check if a pattern element is a REGEXTerm
                        def is_regex_term(element):
                            return hasattr(element, '__class__') and element.__class__.__name__ == 'REGEXTerm'
                        
                        # Add subject condition
                        if not is_unbound(subject):
                            if is_regex_term(subject):
                                # Use PostgreSQL regex matching for REGEXTerm
                                where_conditions.append("s_term.term_text ~ %s")
                                params.append(subject.pattern)
                                self.logger.debug(f"Added regex condition for subject: {subject.pattern}")
                            else:
                                s_text, s_type, s_lang, s_datatype = self.space_impl.terms.term_to_db_info(subject)
                                where_conditions.append("s_term.term_text = %s AND s_term.term_type = %s")
                                params.extend([s_text, s_type])
                                # Add language condition if present
                                if s_lang:
                                    where_conditions.append("s_term.lang = %s")
                                    params.append(s_lang)
                        
                        # Add predicate condition
                        if not is_unbound(predicate):
                            if is_regex_term(predicate):
                                # Use PostgreSQL regex matching for REGEXTerm
                                where_conditions.append("p_term.term_text ~ %s")
                                params.append(predicate.pattern)
                                self.logger.debug(f"Added regex condition for predicate: {predicate.pattern}")
                            else:
                                p_text, p_type, p_lang, p_datatype = self.space_impl.terms.term_to_db_info(predicate)
                                where_conditions.append("p_term.term_text = %s AND p_term.term_type = %s")
                                params.extend([p_text, p_type])
                        
                        # Add object condition
                        if not is_unbound(obj):
                            if is_regex_term(obj):
                                # Use PostgreSQL regex matching for REGEXTerm
                                where_conditions.append("o_term.term_text ~ %s")
                                params.append(obj.pattern)
                                self.logger.debug(f"Added regex condition for object: {obj.pattern}")
                            else:
                                o_text, o_type, o_lang, o_datatype = self.space_impl.terms.term_to_db_info(obj)
                                where_conditions.append("o_term.term_text = %s AND o_term.term_type = %s")
                                params.extend([o_text, o_type])
                                # Add language condition if present
                                if o_lang:
                                    where_conditions.append("o_term.lang = %s")
                                    params.append(o_lang)
                        
                        # Add context condition
                        if not is_unbound(graph):
                            if is_regex_term(graph):
                                # Use PostgreSQL regex matching for REGEXTerm
                                where_conditions.append("c_term.term_text ~ %s")
                                params.append(graph.pattern)
                                self.logger.debug(f"Added regex condition for context: {graph.pattern}")
                            else:
                                c_text, c_type, c_lang, c_datatype = self.space_impl.terms.term_to_db_info(graph)
                                where_conditions.append("c_term.term_text = %s AND c_term.term_type = %s")
                                params.extend([c_text, c_type])
                        
                        # Build final query
                        if where_conditions:
                            query = base_query + " WHERE " + " AND ".join([f"({cond})" for cond in where_conditions])
                        else:
                            query = base_query
                        
                        # Debug logging with more detail
                        self.logger.info(f"🔍 QUADS QUERY: About to execute query on {len(table_names)} tables")
                        self.logger.info(f"📝 Full query: {query}")
                        self.logger.info(f"📊 Parameters: {params}")
                        self.logger.info(f"🎯 Pattern: {quad_pattern}")
                        
                        # Use server-side cursor for true streaming performance
                        self.logger.info(f"⏰ Starting server-side cursor setup...")
                        import time
                        start_time = time.time()
                        
                        # Generate unique cursor name
                        import uuid
                        cursor_name = f"quads_cursor_{uuid.uuid4().hex[:8]}"
                        
                        try:
                            # Declare server-side cursor
                            declare_sql = f"DECLARE {cursor_name} CURSOR FOR {query}"
                            self.logger.debug(f"🔍 DEBUG: Declaring cursor: {declare_sql}")
                            cursor.execute(declare_sql, params)
                            
                            setup_time = time.time() - start_time
                            self.logger.info(f"✅ Server-side cursor declared in {setup_time:.3f}s")
                            
                            # Convert database terms back to RDFLib terms using terms class method
                            
                            # Use server-side cursor paging for immediate streaming
                            self.logger.debug(f"🔍 DEBUG: Starting server-side cursor paging...")
                            page_size = 1000  # Fetch pages of 1000 rows
                            total_yielded = 0
                            
                            while True:
                                # Fetch next page from server-side cursor
                                fetch_sql = f"FETCH FORWARD {page_size} FROM {cursor_name}"
                                cursor.execute(fetch_sql)
                                page_results = cursor.fetchall()
                                
                                if not page_results:
                                    break  # No more results
                                
                                self.logger.debug(f"🔍 DEBUG: Fetched page of {len(page_results)} rows from cursor")
                                
                                # Process and yield each row immediately
                                for row in page_results:
                                    total_yielded += 1
                                    
                                    # Build the quad (psycopg3 returns named results, access by column name)
                                    s = self.space_impl.terms.db_to_rdflib_term(row['subject_text'], row['subject_type'], row['subject_lang'], row['subject_datatype_id'])
                                    p = self.space_impl.terms.db_to_rdflib_term(row['predicate_text'], row['predicate_type'])
                                    o = self.space_impl.terms.db_to_rdflib_term(row['object_text'], row['object_type'], row['object_lang'], row['object_datatype_id'])
                                    c = self.space_impl.terms.db_to_rdflib_term(row['context_text'], row['context_type'])
                                    
                                    quad = (s, p, o, c)
                                    
                                    # Create context iterator
                                    def context_iter():
                                        yield c
                                    
                                    # Yield immediately for true streaming
                                    yield quad, context_iter
                                    
                                    # Log progress for large result sets
                                    if total_yielded % 50000 == 0:
                                        self.logger.info(f"🔍 DEBUG: Streamed {total_yielded:,} quads so far...")
                            
                            self.logger.info(f"✅ Completed server-side cursor streaming - yielded {total_yielded:,} total quads")
                            
                        except Exception as e:
                            execution_time = time.time() - start_time
                            self.logger.error(f"❌ Server-side cursor failed after {execution_time:.3f}s: {e}")
                            raise
                        finally:
                            # Always close the cursor
                            try:
                                cursor.execute(f"CLOSE {cursor_name}")
                                self.logger.debug(f"🔍 DEBUG: Closed server-side cursor {cursor_name}")
                            except Exception as e:
                                self.logger.warning(f"⚠️ Failed to close cursor {cursor_name}: {e}")
                        
        except Exception as e:
            self.logger.error(f"Error in quads query for space '{space_id}': {e}")
            self.logger.error(f"Exception type: {type(e)}")
            self.logger.error(f"Exception args: {e.args}")
            import traceback
            self.logger.error(f"Full traceback: {traceback.format_exc()}")
            # Return empty results for error case
            return
    
    async def get_quad_count(self, space_id: str, context_uuid: Optional[str] = None) -> int:
        """
        Get count of quads in a specific space using UUID-based approach, optionally filtered by context.
        
        Args:
            space_id: Space identifier
            context_uuid: Optional context UUID to filter by
            
        Returns:
            int: Number of quads
            
        Raises:
            Exception: If the space does not exist
        """
        PostgreSQLSpaceUtils.validate_space_id(space_id)
        
        # Check if space exists first - this will throw if it doesn't
        space_exists = await self.space_impl.space_exists(space_id)
        if not space_exists:
            raise ValueError(f"Space '{space_id}' does not exist")
        
        # Get table names using the same method as insertion operations
        table_names = self.space_impl._get_table_names(space_id)
        quad_table_name = table_names['rdf_quad']
        
        try:
            # Use async context manager with pooled connection
            async with self.space_impl.core.get_dict_connection() as conn:
                # Connection already configured with dict_row factory
                cursor = conn.cursor()
                
                if context_uuid:
                    cursor.execute(
                        f"SELECT COUNT(*) as count FROM {quad_table_name} WHERE context_uuid = %s", 
                        (context_uuid,)
                    )
                else:
                    cursor.execute(f"SELECT COUNT(*) as count FROM {quad_table_name}")
                
                result = cursor.fetchone()
                return result['count'] if result else 0
                # Connection automatically returned to pool when context exits
                    
        except Exception as e:
            self.logger.error(f"Error getting quad count from space '{space_id}': {e}")
            raise  # Re-raise the exception instead of returning 0
    
    async def get_rdf_quad_count(self, space_id: str, graph_uri: Optional[str] = None) -> int:
        """
        Get count of RDF quads in a specific space, optionally filtered by graph URI (context).
        
        This is a high-level RDF API that accepts graph URIs and converts them to UUIDs
        internally for compatibility with the UUID-based get_quad_count method.
        
        Args:
            space_id: Space identifier
            graph_uri: Optional graph URI to filter by (e.g., 'http://vital.ai/graph/test')
            
        Returns:
            int: Number of quads
            
        Raises:
            Exception: If the space does not exist
        """
        try:
            self.logger.debug(f"Getting RDF quad count from space '{space_id}' with graph URI: {graph_uri}")
            
            # If no graph URI specified, get total count
            if graph_uri is None:
                return await self.get_quad_count(space_id)
            
            # Convert graph URI to UUID
            from rdflib import URIRef
            graph_ref = URIRef(graph_uri)
            
            # Determine term type and generate UUID
            g_type, g_lang, g_datatype_id = PostgreSQLSpaceUtils.determine_term_type(graph_ref)
            g_value = PostgreSQLSpaceUtils.extract_literal_value(graph_ref) if g_type == 'L' else graph_ref
            
            # Look up the graph UUID in the term table
            graph_uuid = await self.space_impl.get_term_uuid(space_id, str(g_value), g_type, g_lang, g_datatype_id)
            
            if graph_uuid is None:
                # Graph URI doesn't exist in this space, so count is 0
                self.logger.debug(f"Graph URI '{graph_uri}' not found in space '{space_id}', returning count 0")
                return 0
            
            # Use the UUID-based method
            return await self.get_quad_count(space_id, graph_uuid)
            
        except Exception as e:
            self.logger.error(f"Error getting RDF quad count from space '{space_id}' with graph '{graph_uri}': {e}")
            raise
    
    async def get_rdf_quad(self, space_id: str, s: str, p: str, o: str, g: str) -> bool:
        """
        Check if an RDF quad exists in a specific space using datatype-aware approach.
        
        This method uses the new datatype cache system to properly resolve and match
        datatype IDs for all literal terms in the quad.
        
        Args:
            space_id: Space identifier
            s: Subject value (URI, literal, or blank node)
            p: Predicate value (typically URI)
            o: Object value (URI, literal, or blank node)
            g: Graph/context value (typically URI)
            
        Returns:
            bool: True if the quad exists, False otherwise
        """
        try:
            self.logger.debug(f"Checking RDF quad in space '{space_id}': <{s}> <{p}> <{o}> <{g}>")
            
            # Use new determine_term_type that returns datatype URIs
            s_type, s_lang, s_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(s)
            p_type, p_lang, p_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(p)
            o_type, o_lang, o_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(o)
            g_type, g_lang, g_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(g)
            
            # Extract literal values if needed
            s_value = PostgreSQLSpaceUtils.extract_literal_value(s) if s_type == 'L' else s
            p_value = PostgreSQLSpaceUtils.extract_literal_value(p) if p_type == 'L' else p
            o_value = PostgreSQLSpaceUtils.extract_literal_value(o) if o_type == 'L' else o
            g_value = PostgreSQLSpaceUtils.extract_literal_value(g) if g_type == 'L' else g
            
            self.logger.debug(f"Detected types: s={s_type}, p={p_type}, o={o_type}, g={g_type}")
            
            # Collect datatype URIs that need to be resolved to IDs
            datatype_uris_to_resolve = set()
            if s_datatype_uri:
                datatype_uris_to_resolve.add(s_datatype_uri)
            if p_datatype_uri:
                datatype_uris_to_resolve.add(p_datatype_uri)
            if o_datatype_uri:
                datatype_uris_to_resolve.add(o_datatype_uri)
            if g_datatype_uri:
                datatype_uris_to_resolve.add(g_datatype_uri)
            
            # Resolve datatype URIs to IDs using the cache and database
            if datatype_uris_to_resolve:
                datatype_uri_to_id = await self.space_impl._resolve_datatype_ids_batch(space_id, datatype_uris_to_resolve)
            else:
                datatype_uri_to_id = {}
            
            # Convert to final format with datatype IDs
            s_datatype_id = datatype_uri_to_id.get(s_datatype_uri) if s_datatype_uri else None
            p_datatype_id = datatype_uri_to_id.get(p_datatype_uri) if p_datatype_uri else None
            o_datatype_id = datatype_uri_to_id.get(o_datatype_uri) if o_datatype_uri else None
            g_datatype_id = datatype_uri_to_id.get(g_datatype_uri) if g_datatype_uri else None
            
            # Generate deterministic UUIDs
            from .postgresql_space_terms import PostgreSQLSpaceTerms
            generate_term_uuid = PostgreSQLSpaceTerms.generate_term_uuid
            subject_uuid = generate_term_uuid(s_value, s_type, s_lang, s_datatype_id)
            predicate_uuid = generate_term_uuid(p_value, p_type, p_lang, p_datatype_id)
            object_uuid = generate_term_uuid(o_value, o_type, o_lang, o_datatype_id)
            graph_uuid = generate_term_uuid(g_value, g_type, g_lang, g_datatype_id)
            
            # Get table names
            table_names = PostgreSQLSpaceUtils.get_table_names(self.space_impl.global_prefix, space_id)
            
            # Use async context manager with pooled connection
            async with self.space_impl.core.get_dict_connection() as conn:
                # Connection already configured with dict_row factory
                cursor = conn.cursor()
                
                # Check if quad exists
                cursor.execute(
                    f"""
                    SELECT 1 FROM {table_names['rdf_quad']} 
                    WHERE subject_uuid = %s AND predicate_uuid = %s AND object_uuid = %s AND context_uuid = %s
                    LIMIT 1
                    """,
                    (str(subject_uuid), str(predicate_uuid), str(object_uuid), str(graph_uuid))
                )
                result = cursor.fetchone()
                
                exists = result is not None
                
                if exists:
                    self.logger.debug(f"RDF quad exists in space '{space_id}'")
                else:
                    self.logger.debug(f"RDF quad does not exist in space '{space_id}'")
                
                return exists
                
        except Exception as e:
            self.logger.error(f"Error checking RDF quad in space '{space_id}': {e}")
            return False
