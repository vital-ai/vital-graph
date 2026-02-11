
import logging
from datetime import datetime
from typing import Union, List, Tuple, Optional, Any
import psycopg
from psycopg.rows import dict_row
from rdflib.term import Identifier

# Import PostgreSQL utilities
from ..postgresql_log_utils import PostgreSQLLogUtils
from .postgresql_space_terms import PostgreSQLSpaceTerms
from .postgresql_space_utils import PostgreSQLSpaceUtils


class PostgreSQLSpaceDBOps:
    """
    PostgreSQL database operations for RDF quad CRUD and batch operations.
    
    This class handles all database operations related to RDF quads:
    - Individual quad add/remove operations
    - Batch quad add/remove operations
    - Transaction management
    """
    
    def __init__(self, space_impl):
        """
        Initialize database operations with reference to space implementation.
        
        Args:
            space_impl: PostgreSQLSpaceImpl instance for accessing connections and utilities
        """
        self.space_impl = space_impl
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def add_quad(self, space_id: str, subject_uuid: str, predicate_uuid: str, 
                      object_uuid: str, context_uuid: str, transaction=None, auto_commit: bool = True) -> bool:
        """
        Add an RDF quad to a specific space using UUID-based approach.
        
        Args:
            space_id: Space identifier
            subject_uuid: Subject term UUID
            predicate_uuid: Predicate term UUID
            object_uuid: Object term UUID
            context_uuid: Context (graph) term UUID
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            PostgreSQLSpaceUtils.validate_space_id(space_id)
            
            # Get table names using UUID-based approach
            table_prefix = PostgreSQLSpaceUtils.get_table_prefix(self.space_impl.global_prefix, space_id)
            table_names = self.space_impl._get_table_names(space_id)
            quad_table_name = table_names.get('rdf_quad')
            
            # Use provided transaction or get a pooled connection if None
            if transaction is not None:
                conn = transaction.get_connection()
                if conn is None:
                    raise RuntimeError("Transaction object does not provide a valid connection")
                
                # Use dict pool for RETURNING clause access instead of transaction connection
                async with self.space_impl.core.get_dict_connection() as dict_conn:
                    # Connection already configured with dict_row factory
                    cursor = dict_conn.cursor()
                    
                    # Insert quad (duplicates allowed, quad_uuid auto-generated)
                    cursor.execute(
                        f"""
                        INSERT INTO {quad_table_name} 
                        (subject_uuid, predicate_uuid, object_uuid, context_uuid, created_time) 
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING quad_uuid
                    """,
                    (subject_uuid, predicate_uuid, object_uuid, context_uuid, datetime.utcnow())
                )
                result = cursor.fetchone()
                quad_uuid = result['quad_uuid']
                
                # Update transaction statistics
                transaction.increment_quads_added(1)
                self.logger.debug(f"Prepared quad for space '{space_id}' with UUID: {quad_uuid} (will commit with transaction)")
                
                return True
            else:
                # Use async context manager with dict pool for dictionary results
                async with self.space_impl.core.get_dict_connection() as conn:
                    # Connection already configured with dict_row factory
                    cursor = conn.cursor()
                    
                    # Insert quad (duplicates allowed, quad_uuid auto-generated)
                    cursor.execute(
                        f"""
                        INSERT INTO {quad_table_name} 
                        (subject_uuid, predicate_uuid, object_uuid, context_uuid, created_time) 
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING quad_uuid
                        """,
                        (subject_uuid, predicate_uuid, object_uuid, context_uuid, datetime.utcnow())
                    )
                    result = cursor.fetchone()
                    quad_uuid = result['quad_uuid']
                    
                    # Commit based on auto_commit flag
                    if auto_commit:
                        conn.commit()
                        self.logger.debug(f"Added quad to space '{space_id}' with UUID: {quad_uuid}")
                    else:
                        # If auto_commit is False but no transaction, still commit for consistency
                        conn.commit()
                        self.logger.debug(f"Added quad to space '{space_id}' with UUID: {quad_uuid} (auto_commit=False)")
                    
                    return True
                    # Connection automatically returned to pool when context exits
                    
        except Exception as e:
            self.logger.error(f"Error adding quad to space '{space_id}': {e}")
            return False
    
    async def remove_quad(self, space_id: str, subject_uuid: str, predicate_uuid: str, object_uuid: str, context_uuid: str, transaction=None, auto_commit: bool = True) -> bool:
        """
        Remove a single RDF quad from a specific space using UUID-based approach.
        
        Following RDFLib pattern: removes only one instance of the matching quad,
        not all instances. If multiple identical quads exist, only one is removed.
        
        Args:
            space_id: Space identifier
            subject_uuid: Subject term UUID
            predicate_uuid: Predicate term UUID
            object_uuid: Object term UUID
            context_uuid: Context (graph) term UUID
            
        Returns:
            bool: True if a quad was removed, False if no matching quad found
        """
        try:
            PostgreSQLSpaceUtils.validate_space_id(space_id)
            
            # Get table names using UUID-based approach
            table_prefix = PostgreSQLSpaceUtils.get_table_prefix(self.space_impl.global_prefix, space_id)
            table_names = self.space_impl._get_table_names(space_id)
            quad_table_name = table_names.get('rdf_quad')
            
            # Use provided transaction or get a pooled connection if None
            if transaction is not None:
                conn = transaction.get_connection()
                if conn is None:
                    raise RuntimeError("Transaction object does not provide a valid connection")
                
                # Use dict pool for result access instead of transaction connection
                async with self.space_impl.core.get_dict_connection() as dict_conn:
                    # Connection already configured with dict_row factory
                    cursor = dict_conn.cursor()
                    
                    # Delete exactly one instance using ctid (handles duplicates properly)
                    cursor.execute(
                        f"""
                        DELETE FROM {quad_table_name} 
                        WHERE ctid IN (
                        SELECT ctid FROM {quad_table_name}
                        WHERE subject_uuid = %s AND predicate_uuid = %s 
                              AND object_uuid = %s AND context_uuid = %s
                        LIMIT 1
                    )
                    """,
                    (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                )
                
                removed_count = cursor.rowcount
                
                # Update transaction statistics
                if removed_count > 0:
                    transaction.increment_quads_removed(1)
                
                if removed_count > 0:
                    self.logger.debug(f"Removed one quad instance from space '{space_id}'")
                    return True
                else:
                    self.logger.debug(f"No quad was actually removed from space '{space_id}'")
                    return False
            else:
                # Use async context manager with dict pool for dictionary results
                async with self.space_impl.core.get_dict_connection() as conn:
                    # Connection already configured with dict_row factory
                    cursor = conn.cursor()
                    
                    # Delete exactly one instance using ctid (handles duplicates properly)
                    cursor.execute(
                        f"""
                        DELETE FROM {quad_table_name} 
                        WHERE ctid IN (
                            SELECT ctid FROM {quad_table_name}
                            WHERE subject_uuid = %s AND predicate_uuid = %s 
                                  AND object_uuid = %s AND context_uuid = %s
                            LIMIT 1
                        )
                        """,
                        (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                    )
                    
                    removed_count = cursor.rowcount
                    
                    # Commit based on auto_commit flag
                    if auto_commit:
                        conn.commit()
                    else:
                        # If auto_commit is False but no transaction, still commit for consistency
                        conn.commit()
                    
                    if removed_count > 0:
                        self.logger.debug(f"Removed one quad instance from space '{space_id}'")
                        return True
                    else:
                        self.logger.debug(f"No quad was actually removed from space '{space_id}'")
                        return False
                    # Connection automatically returned to pool when context exits
                
        except Exception as e:
            self.logger.error(f"Error removing quad from space '{space_id}': {e}")
            return False
    
    async def add_rdf_quads_batch(self, space_id: str, quads: List[Tuple[Identifier, Identifier, Identifier, Identifier]], 
                             auto_commit: bool = True, verify_count: bool = False, transaction=None) -> int:
        """
        Datatype-aware batch RDF quad insertion with proper datatype handling.
        
        This method uses the new datatype cache system to properly resolve and store
        datatype IDs for all literal terms in the batch. It also uses the graph cache
        to ensure all graphs are registered before inserting quads.
        
        Args:
            space_id: The space identifier
            quads: List of (subject, predicate, object, context) tuples
            auto_commit: Whether to commit the transaction automatically (default: True)
            verify_count: Whether to verify insertion with COUNT query (default: False, for performance)
            transaction: Optional PostgreSQLSpaceTransaction object for transaction management
            
        Returns:
            Number of quads successfully inserted
        """
        if not quads:
            return 0
            
        self.logger.info(f"🚀 DATATYPE-AWARE BATCH INSERT: Starting processing of {len(quads)} quads...")
        
        # Step 1: Process all terms and resolve datatype information
        unique_terms_with_datatypes = set()
        quad_term_data = []
        datatype_uris_to_resolve = set()
        
        for s, p, o, g in quads:
            try:
                # Use new determine_term_type that returns datatype URIs
                s_type, s_lang, s_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(s)
                p_type, p_lang, p_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(p)
                o_type, o_lang, o_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(o)
                
                # Handle global graph if no graph is specified
                if g is None:
                    from rdflib import URIRef
                    g = URIRef("urn:___GLOBAL")
                
                g_type, g_lang, g_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(g)

                # Extract literal values if needed
                s_value = PostgreSQLSpaceUtils.extract_literal_value(s) if s_type == 'L' else s
                p_value = PostgreSQLSpaceUtils.extract_literal_value(p) if p_type == 'L' else p
                o_value = PostgreSQLSpaceUtils.extract_literal_value(o) if o_type == 'L' else o
                g_value = PostgreSQLSpaceUtils.extract_literal_value(g) if g_type == 'L' else g
                
                # Collect datatype URIs that need to be resolved to IDs
                if s_datatype_uri:
                    datatype_uris_to_resolve.add(s_datatype_uri)
                if p_datatype_uri:
                    datatype_uris_to_resolve.add(p_datatype_uri)
                if o_datatype_uri:
                    datatype_uris_to_resolve.add(o_datatype_uri)
                if g_datatype_uri:
                    datatype_uris_to_resolve.add(g_datatype_uri)
                
                # Store term info with datatype URIs for now
                s_info = (s_value, s_type, s_lang, s_datatype_uri)
                p_info = (p_value, p_type, p_lang, p_datatype_uri)
                o_info = (o_value, o_type, o_lang, o_datatype_uri)
                g_info = (g_value, g_type, g_lang, g_datatype_uri)
                
                quad_term_data.append((s_info, p_info, o_info, g_info))
                unique_terms_with_datatypes.update([s_info, p_info, o_info, g_info])
            except Exception as e:
                self.logger.error(f"❌ Error resolving term info: {e}")
                continue
        
        self.logger.info(f"📊 Generated {len(unique_terms_with_datatypes)} unique terms from {len(quads)} quads")
        
        # Step 2: Resolve datatype URIs to IDs using the cache and database
        if datatype_uris_to_resolve:
            datatype_uri_to_id = await self.space_impl._resolve_datatype_ids_batch(space_id, datatype_uris_to_resolve)
        else:
            datatype_uri_to_id = {}
        
        # Step 3: Convert terms to final format with datatype IDs
        unique_terms_final = set()
        quad_term_data_final = []
        
        for quad_terms in quad_term_data:
            final_quad_terms = []
            for term_value, term_type, lang, datatype_uri in quad_terms:
                datatype_id = datatype_uri_to_id.get(datatype_uri) if datatype_uri else None
                final_term = (term_value, term_type, lang, datatype_id)
                final_quad_terms.append(final_term)
                unique_terms_final.add(final_term)
            quad_term_data_final.append(tuple(final_quad_terms))
        
        # Step 4: Extract unique graph URIs and ensure they exist in the database
        unique_graph_uris = set()
        for quad_terms in quad_term_data_final:
            s_info, p_info, o_info, g_info = quad_terms
            g_value, g_type, g_lang, g_datatype_id = g_info
            if g_type == 'U':  # Only URI graphs need to be registered
                unique_graph_uris.add(str(g_value))
        
        # Use graph cache to check which graphs need to be created
        if unique_graph_uris:
            graph_cache = self.space_impl.get_graph_cache(space_id)
            # Ensure cache is initialized with existing graphs from database
            await graph_cache.ensure_initialized_async(space_id, self.space_impl.graphs)
            missing_graphs = graph_cache.get_missing_graphs(unique_graph_uris)
            
            if missing_graphs:
                self.logger.info(f"📊 Ensuring {len(missing_graphs)} graphs exist in database")
                # Use batch ensure graphs exist to create missing graphs
                await self.space_impl.graphs.batch_ensure_graphs_exist(space_id, missing_graphs)
                # Add newly created graphs to cache
                graph_cache.add_graphs_to_cache_batch(missing_graphs)
            
            self.logger.debug(f"Graph cache stats: {len(unique_graph_uris)} total graphs, {len(missing_graphs)} created")
        
        # Step 5: Generate UUIDs and process batch insertion
        term_to_uuid = {}
        
        for term_info in unique_terms_final:
            term_text, term_type, lang, datatype_id = term_info
            term_uuid = PostgreSQLSpaceTerms.generate_term_uuid(term_text, term_type, lang, datatype_id)
            term_to_uuid[term_info] = term_uuid
        
        # Get table names for this space (already includes unlogged suffix if configured)
        table_names = self.space_impl._get_table_names(space_id)
        
        # Use provided transaction or get a pooled connection if None
        if transaction is not None:
            connection = transaction.get_connection()
            if connection is None:
                raise RuntimeError("Transaction object does not provide a valid connection")
            
            # Use transaction connection with tuple results for batch performance
            cursor = connection.cursor()
            
            # Insert all unique terms first
            if unique_terms_final:
                term_insert_data = []
                for term_info in unique_terms_final:
                    term_text, term_type, lang, datatype_id = term_info
                    term_uuid = term_to_uuid[term_info]
                    term_insert_data.append((str(term_uuid), term_text, term_type, lang, datatype_id, datetime.utcnow()))
                
                # Batch insert terms
                cursor.executemany(
                    f"""
                    INSERT INTO {table_names['term']} 
                    (term_uuid, term_text, term_type, lang, datatype_id, created_time) 
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (term_uuid, dataset) DO NOTHING
                    """,
                    term_insert_data
                )
                
                self.logger.info(f"📝 Inserted/updated {len(term_insert_data)} unique terms")
            
            # Insert all quads
            quad_insert_data = []
            for quad_terms in quad_term_data_final:
                s_info, p_info, o_info, g_info = quad_terms
                s_uuid = str(term_to_uuid[s_info])
                p_uuid = str(term_to_uuid[p_info])
                o_uuid = str(term_to_uuid[o_info])
                g_uuid = str(term_to_uuid[g_info])
                
                quad_insert_data.append((s_uuid, p_uuid, o_uuid, g_uuid, datetime.utcnow()))
            
            # Batch insert quads
            cursor.executemany(
                f"""
                INSERT INTO {table_names['rdf_quad']} 
                (subject_uuid, predicate_uuid, object_uuid, context_uuid, created_time) 
                VALUES (%s, %s, %s, %s, %s)
                """,
                quad_insert_data
            )
            
            inserted_count = cursor.rowcount
            
            # Update transaction statistics
            transaction.increment_quads_added(inserted_count)
            transaction.increment_terms_added(len(unique_terms_final))
            
            self.logger.info(f"✅ Prepared {inserted_count} quads for insertion (will commit with transaction)")
            return inserted_count
        else:
            # Use async context manager with pooled connection (tuple results for batch performance)
            async with self.space_impl.get_db_connection() as connection:
                try:
                    # Use tuple results for batch performance
                    cursor = connection.cursor()
                    
                    # Insert all unique terms first
                    if unique_terms_final:
                        term_insert_data = []
                        for term_info in unique_terms_final:
                            term_text, term_type, lang, datatype_id = term_info
                            term_uuid = term_to_uuid[term_info]
                            term_insert_data.append((str(term_uuid), term_text, term_type, lang, datatype_id, datetime.utcnow()))
                        
                        # Batch insert terms
                        cursor.executemany(
                            f"""
                            INSERT INTO {table_names['term']} 
                            (term_uuid, term_text, term_type, lang, datatype_id, created_time) 
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (term_uuid, dataset) DO NOTHING
                            """,
                            term_insert_data
                        )
                        
                        self.logger.info(f"📝 Inserted/updated {len(term_insert_data)} unique terms")
                    
                    # Insert all quads
                    quad_insert_data = []
                    for quad_terms in quad_term_data_final:
                        s_info, p_info, o_info, g_info = quad_terms
                        s_uuid = str(term_to_uuid[s_info])
                        p_uuid = str(term_to_uuid[p_info])
                        o_uuid = str(term_to_uuid[o_info])
                        g_uuid = str(term_to_uuid[g_info])
                        
                        quad_insert_data.append((s_uuid, p_uuid, o_uuid, g_uuid, datetime.utcnow()))
                    
                    # Batch insert quads
                    cursor.executemany(
                        f"""
                        INSERT INTO {table_names['rdf_quad']} 
                        (subject_uuid, predicate_uuid, object_uuid, context_uuid, created_time) 
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        quad_insert_data
                    )
                    
                    inserted_count = cursor.rowcount
                    
                    # Commit based on auto_commit flag
                    if auto_commit:
                        connection.commit()
                        self.logger.info(f"✅ Successfully inserted {inserted_count} quads")
                    else:
                        self.logger.info(f"✅ Prepared {inserted_count} quads for insertion (not committed)")
                    
                    return inserted_count
                    # Connection automatically returned to pool when context exits
                    
                except Exception as e:
                    error_msg = str(e)
                    # Clean up verbose PostgreSQL error messages for invalid spaces
                    if "does not exist" in error_msg and "relation" in error_msg:
                        if "invalid_space" in error_msg:
                            self.logger.error(f"❌ Error in batch quad insertion: Invalid space '{space_id}' does not exist")
                        else:
                            self.logger.error(f"❌ Error in batch quad insertion: Space '{space_id}' tables not found")
                    else:
                        self.logger.error(f"❌ Error in batch quad insertion: {error_msg}")
                    
                    if auto_commit:
                        connection.rollback()
                    return 0
    
    async def remove_rdf_quads_batch(self, space_id: str, quads: List[tuple], transaction=None) -> int:
        """
        Datatype-aware batch RDF quad removal with proper datatype handling.
        
        This method uses the new datatype cache system to properly resolve and match
        datatype IDs for all literal terms in the batch.
        
        Args:
            space_id: Space identifier
            quads: List of (s, p, o, g) tuples representing RDF quads to remove
            transaction: Optional PostgreSQLSpaceTransaction object for transaction management
            
        Returns:
            int: Number of quads successfully removed
        """
        if not quads:
            return 0
            
        try:
            self.logger.info(f"🗑️ DATATYPE-AWARE BATCH REMOVE: Starting processing of {len(quads)} quads...")
            
            # Step 1: Process all terms and resolve datatype information
            unique_terms_with_datatypes = set()
            quad_term_data = []
            datatype_uris_to_resolve = set()
            
            for s, p, o, g in quads:
                try:
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
                    
                    # Collect datatype URIs that need to be resolved to IDs
                    if s_datatype_uri:
                        datatype_uris_to_resolve.add(s_datatype_uri)
                    if p_datatype_uri:
                        datatype_uris_to_resolve.add(p_datatype_uri)
                    if o_datatype_uri:
                        datatype_uris_to_resolve.add(o_datatype_uri)
                    if g_datatype_uri:
                        datatype_uris_to_resolve.add(g_datatype_uri)
                    
                    # Store term info with datatype URIs for now
                    s_info = (s_value, s_type, s_lang, s_datatype_uri)
                    p_info = (p_value, p_type, p_lang, p_datatype_uri)
                    o_info = (o_value, o_type, o_lang, o_datatype_uri)
                    g_info = (g_value, g_type, g_lang, g_datatype_uri)
                    
                    quad_term_data.append((s_info, p_info, o_info, g_info))
                    unique_terms_with_datatypes.update([s_info, p_info, o_info, g_info])
                except Exception as e:
                    self.logger.error(f"❌ Error resolving term info: {e}")
                    continue
            
            self.logger.info(f"📊 Generated {len(unique_terms_with_datatypes)} unique terms from {len(quads)} quads")
            
            # Step 2: Resolve datatype URIs to IDs using the cache and database
            if datatype_uris_to_resolve:
                datatype_uri_to_id = await self.space_impl.datatypes.resolve_datatype_ids_batch(space_id, datatype_uris_to_resolve)
            else:
                datatype_uri_to_id = {}
            
            # Step 3: Convert terms to final format with datatype IDs and generate UUIDs
            quad_uuids = []
            
            for quad_terms in quad_term_data:
                quad_term_uuids = []
                for term_value, term_type, lang, datatype_uri in quad_terms:
                    datatype_id = datatype_uri_to_id.get(datatype_uri) if datatype_uri else None
                    term_uuid = PostgreSQLSpaceTerms.generate_term_uuid(term_value, term_type, lang, datatype_id)
                    quad_term_uuids.append(str(term_uuid))
                quad_uuids.append(tuple(quad_term_uuids))
            
            # Step 4: Remove quads using UUIDs
            if quad_uuids:
                table_names = PostgreSQLSpaceUtils.get_table_names(self.space_impl.global_prefix, space_id)
                
                # Use provided transaction or get a pooled connection if None
                if transaction is not None:
                    conn = transaction.get_connection()
                    if conn is None:
                        raise RuntimeError("Transaction object does not provide a valid connection")
                    
                    # Use transaction connection directly
                    cursor = conn.cursor()
                    
                    removed_count = 0
                    batch_size = 1000
                    
                    for i in range(0, len(quad_uuids), batch_size):
                        batch_uuids = quad_uuids[i:i + batch_size]
                        
                        # Build parameterized query for batch removal
                        placeholders = []
                        params = []
                        
                        for s_uuid, p_uuid, o_uuid, g_uuid in batch_uuids:
                            placeholders.append("(subject_uuid = %s AND predicate_uuid = %s AND object_uuid = %s AND context_uuid = %s)")
                            params.extend([s_uuid, p_uuid, o_uuid, g_uuid])
                        
                        if placeholders:
                            query = f"DELETE FROM {table_names['rdf_quad']} WHERE {' OR '.join(placeholders)}"
                            
                            cursor.execute(query, params)
                            batch_removed = cursor.rowcount
                            removed_count += batch_removed
                            
                            self.logger.debug(f"🗑️ Batch {i//batch_size + 1}: Removed {batch_removed} quads")
                    
                    # Update transaction statistics
                    transaction.increment_quads_removed(removed_count)
                    
                    if removed_count > 0:
                        self.logger.info(f"✅ Successfully removed {removed_count} quads (will commit with transaction)")
                        return removed_count
                    else:
                        self.logger.info("No matching quads found to remove")
                        return 0
                else:
                    # Use async context manager with pooled connection
                    async with self.space_impl.get_db_connection() as conn:
                        try:
                            cursor = conn.cursor()
                            
                            removed_count = 0
                            batch_size = 1000
                            
                            for i in range(0, len(quad_uuids), batch_size):
                                batch_uuids = quad_uuids[i:i + batch_size]
                                
                                # Build parameterized query for batch removal
                                placeholders = []
                                params = []
                                
                                for s_uuid, p_uuid, o_uuid, g_uuid in batch_uuids:
                                    placeholders.append("(subject_uuid = %s AND predicate_uuid = %s AND object_uuid = %s AND context_uuid = %s)")
                                    params.extend([s_uuid, p_uuid, o_uuid, g_uuid])
                                
                                if placeholders:
                                    query = f"DELETE FROM {table_names['rdf_quad']} WHERE {' OR '.join(placeholders)}"
                                    
                                    cursor.execute(query, params)
                                    batch_removed = cursor.rowcount
                                    removed_count += batch_removed
                                    
                                    self.logger.debug(f"🗑️ Batch {i//batch_size + 1}: Removed {batch_removed} quads")
                            
                            # Commit the transaction
                            conn.commit()
                            
                            if removed_count > 0:
                                self.logger.info(f"✅ Successfully removed {removed_count} quads")
                                return removed_count
                            else:
                                self.logger.info("No matching quads found to remove")
                                return 0
                                # Connection automatically returned to pool when context exits
                                
                        except Exception as e:
                            error_msg = str(e)
                            # Clean up verbose PostgreSQL error messages for invalid spaces
                            if "does not exist" in error_msg and "relation" in error_msg:
                                if "invalid_space" in error_msg:
                                    self.logger.error(f"❌ Error in batch quad removal: Invalid space '{space_id}' does not exist")
                                else:
                                    self.logger.error(f"❌ Error in batch quad removal: Space '{space_id}' tables not found")
                            else:
                                self.logger.error(f"❌ Error in batch quad removal: {error_msg}")
                            
                            conn.rollback()
                            return 0
            else:
                self.logger.info("No quads to remove")
                return 0
                
        except Exception as e:
            self.logger.error(f"❌ Error in batch quad removal: {e}")
            return 0
    
    async def add_rdf_quad(self, space_id: str, quad: Union[tuple, list], transaction=None) -> bool:
        """
        Add an RDF quad to a specific space with proper datatype handling.
        
        This method uses the new datatype cache system to properly resolve and store
        datatype IDs for all literal terms in the quad.
        
        Args:
            space_id: Space identifier
            quad: Tuple of (subject, predicate, object, graph) RDF values
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Unpack the quad tuple
            s, p, o, g = quad
            self.logger.debug(f"Adding RDF quad to space '{space_id}': <{s}> <{p}> <{o}> <{g}>")
            
            # Determine term types and datatype URIs
            from ..postgresql_log_utils import PostgreSQLLogUtils
            s_type, s_lang, s_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(s)
            p_type, p_lang, p_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(p)
            o_type, o_lang, o_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(o)
            g_type, g_lang, g_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(g)
            
            # Process each term with datatype resolution
            s_value, s_type, s_lang, s_datatype_id = await self.space_impl._process_term_with_datatype(
                space_id, s, s_type, s_lang, s_datatype_uri)
            p_value, p_type, p_lang, p_datatype_id = await self.space_impl._process_term_with_datatype(
                space_id, p, p_type, p_lang, p_datatype_uri)
            o_value, o_type, o_lang, o_datatype_id = await self.space_impl._process_term_with_datatype(
                space_id, o, o_type, o_lang, o_datatype_uri)
            g_value, g_type, g_lang, g_datatype_id = await self.space_impl._process_term_with_datatype(
                space_id, g, g_type, g_lang, g_datatype_uri)
            
            self.logger.debug(f"Detected types: s={s_type}, p={p_type}, o={o_type}, g={g_type}")
            self.logger.debug(f"Datatype IDs: s={s_datatype_id}, p={p_datatype_id}, o={o_datatype_id}, g={g_datatype_id}")
            
            # Get table names for operations
            table_names = self.space_impl._get_table_names(space_id)
            
            # Look up existing terms using complete term characteristics
            subject_uuid = await self.space_impl.get_term_uuid(space_id, s_value, s_type, s_lang, s_datatype_id)
            predicate_uuid = await self.space_impl.get_term_uuid(space_id, p_value, p_type, p_lang, p_datatype_id)
            object_uuid = await self.space_impl.get_term_uuid(space_id, o_value, o_type, o_lang, o_datatype_id)
            graph_uuid = await self.space_impl.get_term_uuid(space_id, g_value, g_type, g_lang, g_datatype_id)
            
            # Check if any terms are missing (need to be inserted)
            missing_terms = []
            if not subject_uuid:
                missing_terms.append((s_value, s_type, s_lang, s_datatype_id, 'subject'))
            if not predicate_uuid:
                missing_terms.append((p_value, p_type, p_lang, p_datatype_id, 'predicate'))
            if not object_uuid:
                missing_terms.append((o_value, o_type, o_lang, o_datatype_id, 'object'))
            if not graph_uuid:
                missing_terms.append((g_value, g_type, g_lang, g_datatype_id, 'graph'))
            
            # DEBUG: Print missing terms info
            self.logger.debug(f"🔍 add_rdf_quad: Found {len(missing_terms)} missing terms")
            for term_value, term_type, lang, datatype_id, role in missing_terms:
                self.logger.debug(f"  - {role}: '{term_value}' (type: {term_type}, lang: {lang}, dt_id: {datatype_id})")
            
            # Insert missing terms if any
            if missing_terms:
                self.logger.debug(f"🔧 DEBUG: Inserting {len(missing_terms)} missing terms for quad")
                
                # Generate UUIDs for missing terms
                # Use the static method from PostgreSQLSpaceTerms
                generate_term_uuid = PostgreSQLSpaceTerms.generate_term_uuid
                term_inserts = []
                cache_updates = {}
                
                for term_text, term_type, lang, datatype_id, role in missing_terms:
                    term_uuid = PostgreSQLSpaceTerms.generate_term_uuid(term_text, term_type, lang, datatype_id)
                    term_inserts.append((term_uuid, term_text, term_type, lang, datatype_id, datetime.utcnow()))
                    cache_updates[(term_text, term_type)] = str(term_uuid)
                    self.logger.debug(f"🔧 DEBUG: Generated {role} term: {term_text[:50]} -> {term_uuid}")
                    
                    # Update our local mappings
                    if role == 'subject':
                        subject_uuid = str(term_uuid)
                    elif role == 'predicate':
                        predicate_uuid = str(term_uuid)
                    elif role == 'object':
                        object_uuid = str(term_uuid)
                    elif role == 'graph':
                        graph_uuid = str(term_uuid)
                
                # Insert terms into database using async pooled connection
                try:
                    if transaction is not None:
                        # Use transaction connection if provided
                        conn = transaction.get_connection()
                        if conn is None:
                            raise RuntimeError("Transaction object does not provide a valid connection")
                        
                        # Use transaction connection with tuple results for batch performance
                        cursor = conn.cursor()
                        self.logger.debug(f"🔧 DEBUG: About to insert {len(term_inserts)} terms into {table_names['term']} (using transaction)")
                        
                        # Use executemany for batch insert
                        cursor.executemany(
                            f"""INSERT INTO {table_names['term']} 
                                 (term_uuid, term_text, term_type, lang, datatype_id, created_time) 
                                 VALUES (%s, %s, %s, %s, %s, %s)
                                 ON CONFLICT (term_uuid) DO NOTHING""",
                            term_inserts
                        )
                        
                        rows_affected = cursor.rowcount
                        self.logger.debug(f"🔧 DEBUG: Term insertion rowcount: {rows_affected}")
                        self.logger.debug(f"🔧 DEBUG: Term insertion prepared (will commit with transaction)")
                        
                        # Verify terms were actually inserted (using tuple results for performance)
                        for term_uuid, term_text, term_type, lang, datatype_id, created_time in term_inserts:
                            cursor.execute(f"SELECT COUNT(*) FROM {table_names['term']} WHERE term_uuid = %s", [str(term_uuid)])
                            result = cursor.fetchone()
                            count = result[0] if result else 0
                            self.logger.debug(f"🔧 DEBUG: Term {term_text[:30]} exists after insert: {count > 0}")
                        
                        self.logger.debug(f"✅ Prepared {len(term_inserts)} new terms (will commit with transaction)")
                    else:
                        # Use async context manager with dict pool for dictionary results
                        async with self.space_impl.core.get_dict_connection() as conn:
                            # Connection already configured with dict_row factory
                            cursor = conn.cursor()
                            self.logger.debug(f"🔧 DEBUG: About to insert {len(term_inserts)} terms into {table_names['term']} (using pooled connection)")
                            
                            # Use executemany for batch insert
                            cursor.executemany(
                                f"""INSERT INTO {table_names['term']} 
                                     (term_uuid, term_text, term_type, lang, datatype_id, created_time) 
                                     VALUES (%s, %s, %s, %s, %s, %s)
                                     ON CONFLICT (term_uuid) DO NOTHING""",
                                term_inserts
                            )
                            
                            rows_affected = cursor.rowcount
                            self.logger.debug(f"🔧 DEBUG: Term insertion rowcount: {rows_affected}")
                            
                            # Verify terms were actually inserted
                            for term_uuid, term_text, term_type, lang, datatype_id, created_time in term_inserts:
                                cursor.execute(f"SELECT COUNT(*) as count FROM {table_names['term']} WHERE term_uuid = %s", [str(term_uuid)])
                                result = cursor.fetchone()
                                count = result['count'] if result else 0
                                self.logger.debug(f"🔧 DEBUG: Term {term_text[:30]} exists after insert: {count > 0}")
                            
                            # Commit the transaction
                            conn.commit()
                            self.logger.debug(f"✅ Successfully inserted {len(term_inserts)} new terms")
                            # Connection automatically returned to pool when context exits
                        
                except Exception as term_insert_error:
                    self.logger.error(f"❌ ERROR during term insertion: {term_insert_error}")
                    import traceback
                    self.logger.error(f"📋 Term insertion traceback: {traceback.format_exc()}")
                    return False
            else:
                self.logger.debug(f"🔧 DEBUG: No missing terms to insert")
            
            # Now add the quad using the UUIDs
            success = await self.add_quad(space_id, subject_uuid, predicate_uuid, object_uuid, graph_uuid, transaction)
            
            if success:
                self.logger.debug(f"Successfully added RDF quad to space '{space_id}'")
            else:
                self.logger.error(f"Failed to add RDF quad to space '{space_id}'")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error adding RDF quad to space '{space_id}': {e}")
            import traceback
            self.logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
    
    async def remove_rdf_quad(self, space_id: str, s: str, p: str, o: str, g: str) -> bool:
        """
        Remove an RDF quad from a specific space with proper datatype handling.
        
        This method uses the new datatype cache system to properly resolve datatypes
        when looking up terms for removal.
        
        Args:
            space_id: Space identifier
            s: Subject value (URI, literal, or blank node)
            p: Predicate value (typically URI)
            o: Object value (URI, literal, or blank node)
            g: Graph value (URI, literal, or blank node)
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.logger.debug(f"Removing RDF quad from space '{space_id}': <{s}> <{p}> <{o}> <{g}>")
            
            # Determine term types and datatype URIs
            from ..postgresql_log_utils import PostgreSQLLogUtils
            s_type, s_lang, s_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(s)
            p_type, p_lang, p_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(p)
            o_type, o_lang, o_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(o)
            g_type, g_lang, g_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(g)
            
            # Process each term with datatype resolution
            s_value, s_type, s_lang, s_datatype_id = await self.space_impl._process_term_with_datatype(
                space_id, s, s_type, s_lang, s_datatype_uri)
            p_value, p_type, p_lang, p_datatype_id = await self.space_impl._process_term_with_datatype(
                space_id, p, p_type, p_lang, p_datatype_uri)
            o_value, o_type, o_lang, o_datatype_id = await self.space_impl._process_term_with_datatype(
                space_id, o, o_type, o_lang, o_datatype_uri)
            g_value, g_type, g_lang, g_datatype_id = await self.space_impl._process_term_with_datatype(
                space_id, g, g_type, g_lang, g_datatype_uri)
            
            # Look up term UUIDs with proper datatype matching
            subject_uuid = await self.space_impl.get_term_uuid(space_id, s_value, s_type, s_lang, s_datatype_id)
            predicate_uuid = await self.space_impl.get_term_uuid(space_id, p_value, p_type, p_lang, p_datatype_id)
            object_uuid = await self.space_impl.get_term_uuid(space_id, o_value, o_type, o_lang, o_datatype_id)
            graph_uuid = await self.space_impl.get_term_uuid(space_id, g_value, g_type, g_lang, g_datatype_id)
            
            # Check if all terms exist
            if not all([subject_uuid, predicate_uuid, object_uuid, graph_uuid]):
                self.logger.debug(f"One or more terms not found in space '{space_id}' - cannot remove quad")
                return False
            
            # Remove the quad using term UUIDs
            success = await self.remove_quad(space_id, subject_uuid, predicate_uuid, object_uuid, graph_uuid)
            
            if success:
                self.logger.debug(f"Successfully removed RDF quad from space '{space_id}'")
            else:
                self.logger.debug(f"No matching RDF quad found to remove from space '{space_id}'")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error removing RDF quad from space '{space_id}': {e}")
            return False
    
    async def remove_quads_by_subject_uris(self, space_id: str, subject_uris: List[str], graph_id: str = None, transaction=None) -> int:
        """
        Remove all quads for given subject URIs using text-based matching (like list operation).
        
        This method uses the same text-based approach as get_objects_by_uris_batch() to avoid
        UUID generation/matching issues that can cause incomplete deletions.
        
        Args:
            space_id: Space identifier
            subject_uris: List of subject URIs to delete all quads for
            graph_id: Optional graph identifier to filter by
            transaction: Optional PostgreSQLSpaceTransaction object for transaction management
            
        Returns:
            int: Number of quads successfully removed
        """
        if not subject_uris:
            return 0
            
        try:
            self.logger.info(f"🗑️ TEXT-BASED SUBJECT REMOVAL: Deleting all quads for {len(subject_uris)} subjects...")
            
            # Get table names
            table_names = PostgreSQLSpaceUtils.get_table_names(self.space_impl.global_prefix, space_id)
            quad_table = table_names['rdf_quad']
            term_table = table_names['term']
            
            # Build query using text-based matching (same approach as list operation)
            query_parts = [
                f"DELETE FROM {quad_table}",
                f"WHERE subject_uuid IN (",
                f"    SELECT term_uuid FROM {term_table} WHERE term_text = ANY(%s)",
                f")"
            ]
            
            params = [subject_uris]
            
            # Add graph filter if specified
            if graph_id:
                query_parts.insert(-1, f"AND context_uuid IN (")
                query_parts.insert(-1, f"    SELECT term_uuid FROM {term_table} WHERE term_text = %s")
                query_parts.insert(-1, f")")
                params.append(graph_id)
            
            query = " ".join(query_parts)
            
            # Execute deletion
            if transaction is not None:
                conn = transaction.get_connection()
                if conn is None:
                    raise RuntimeError("Transaction object does not provide a valid connection")
                
                cursor = conn.cursor()
                cursor.execute(query, params)
                removed_count = cursor.rowcount
                
                # Update transaction statistics
                transaction.increment_quads_removed(removed_count)
                
                self.logger.info(f"✅ Successfully removed {removed_count} quads using text-based matching (will commit with transaction)")
                return removed_count
            else:
                # Use async context manager with pooled connection
                async with self.space_impl.get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(query, params)
                    removed_count = cursor.rowcount
                    conn.commit()
                    
                    self.logger.info(f"✅ Successfully removed {removed_count} quads using text-based matching")
                    return removed_count
                    
        except Exception as e:
            self.logger.error(f"❌ Error in text-based subject removal: {e}")
            raise



