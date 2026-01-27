"""
PostgreSQL database implementation for FUSEKI_POSTGRESQL hybrid backend.
Direct PostgreSQL connections without SQLAlchemy for optimal performance.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Union, Any
import asyncpg
from datetime import datetime

from ..db_inf import DbImplInterface
from .postgresql_schema import FusekiPostgreSQLSchema
from ...utils.resource_manager import track_pool


logger = logging.getLogger(__name__)


class FusekiPostgreSQLTransaction:
    """Transaction wrapper for FusekiPostgreSQLDbImpl with async context manager support."""
    
    def __init__(self, connection, transaction, pool):
        self.connection = connection
        self.transaction = transaction
        self.pool = pool
        self._committed = False
        self._rolled_back = False
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None and not self._committed and not self._rolled_back:
            # Success case - commit transaction
            await self.commit()
        elif not self._rolled_back:
            # Exception case - rollback transaction
            await self.rollback()
        
        # Always release connection back to pool
        await self.pool.release(self.connection)
    
    async def commit(self):
        """Commit the transaction."""
        if not self._committed and not self._rolled_back:
            await self.transaction.commit()
            self._committed = True
    
    async def rollback(self):
        """Rollback the transaction."""
        if not self._committed and not self._rolled_back:
            await self.transaction.rollback()
            self._rolled_back = True
    
    def get_connection(self):
        """Get the underlying connection for direct database operations."""
        return self.connection


class FusekiPostgreSQLDbImpl(DbImplInterface):
    """
    PostgreSQL database implementation for FUSEKI_POSTGRESQL hybrid backend.
    Direct PostgreSQL connections without SQLAlchemy for optimal performance.
    
    This implementation provides the PostgreSQL component of the hybrid backend,
    handling metadata storage and primary data operations while Fuseki provides index/cache layer.
    """
    
    def __init__(self, postgresql_config: dict):
        """
        Initialize PostgreSQL database implementation.
        
        Args:
            postgresql_config: PostgreSQL connection configuration
        """
        self.config = postgresql_config
        self.connection_pool = None
        self.schema = FusekiPostgreSQLSchema()
        self.connected = False
        
        logger.info("FusekiPostgreSQLDbImpl initialized")
    
    async def connect(self) -> bool:
        """Establish PostgreSQL connection pool."""
        try:
            logger.info("Connecting to PostgreSQL for FUSEKI_POSTGRESQL backend...")
            
            # Create connection pool using asyncpg
            self.connection_pool = await asyncpg.create_pool(
                host=self.config.get('host', 'localhost'),
                port=self.config.get('port', 5432),
                database=self.config.get('database', 'vitalgraph'),
                user=self.config.get('username', 'vitalgraph_user'),
                password=self.config.get('password', 'vitalgraph_pass'),
                min_size=1,
                max_size=10,
                command_timeout=60
            )
            
            # Track the pool for proper cleanup
            track_pool(self.connection_pool)
            
            # Test connection
            async with self.connection_pool.acquire() as conn:
                result = await conn.fetchval('SELECT 1')
                if result == 1:
                    self.connected = True
                    logger.info("PostgreSQL connection pool established successfully")
                    return True
                else:
                    logger.error("PostgreSQL connection test failed")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            self.connected = False
            return False
    
    async def disconnect(self) -> bool:
        """Close PostgreSQL connection pool with optimized cleanup."""
        try:
            if self.connection_pool:
                logger.info("Closing PostgreSQL connection pool...")
                
                # First try graceful close with shorter timeout
                import asyncio
                try:
                    await asyncio.wait_for(self.connection_pool.close(), timeout=3.0)
                    logger.info("PostgreSQL connection pool closed gracefully")
                except asyncio.TimeoutError:
                    logger.warning("Pool close timed out, forcing immediate termination...")
                    # Force terminate all connections immediately (synchronous)
                    self.connection_pool.terminate()
                    logger.info("PostgreSQL connection pool terminated")
                
                # Wait for all connections to be properly closed
                try:
                    await asyncio.wait_for(self.connection_pool.wait_closed(), timeout=2.0)
                    logger.debug("PostgreSQL connection pool wait_closed completed")
                except asyncio.TimeoutError:
                    logger.warning("Pool wait_closed timed out")
                except Exception as e:
                    logger.debug(f"Pool wait_closed error (non-critical): {e}")
                
                self.connection_pool = None
            
            self.connected = False
            return True
            
        except Exception as e:
            logger.error(f"Error closing PostgreSQL connection pool: {e}")
            return False
    
    async def is_connected(self) -> bool:
        """Check if PostgreSQL connection is active."""
        if not self.connected or not self.connection_pool:
            return False
        
        try:
            # Test connection with a simple query
            async with self.connection_pool.acquire() as conn:
                await conn.fetchval('SELECT 1')
            return True
        except Exception:
            self.connected = False
            return False
    
    async def execute_query(self, query: str, params: Optional[Union[Dict, List]] = None) -> List[Dict[str, Any]]:
        """Execute PostgreSQL query and return results."""
        if not self.connected:
            raise RuntimeError("Not connected to PostgreSQL")
        
        try:
            async with self.connection_pool.acquire() as conn:
                if params:
                    # Handle both dict and list params
                    if isinstance(params, dict):
                        param_values = list(params.values())
                    else:
                        param_values = params
                    rows = await conn.fetch(query, *param_values)
                else:
                    rows = await conn.fetch(query)
                
                # Convert asyncpg Records to dictionaries
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            raise
    
    async def execute_update(self, query: str, params: Optional[Union[Dict, List]] = None) -> bool:
        """Execute PostgreSQL update/insert/delete operation."""
        if not self.connected:
            raise RuntimeError("Not connected to PostgreSQL")
        
        try:
            async with self.connection_pool.acquire() as conn:
                if params:
                    # Handle both dict and list params
                    if isinstance(params, dict):
                        param_values = list(params.values())
                    else:
                        param_values = params
                    result = await conn.execute(query, *param_values)
                else:
                    result = await conn.execute(query)
                
                # Return True if operation affected rows
                return result != 'SELECT 0'
                
        except Exception as e:
            logger.error(f"Error executing update: {e}")
            return False
    
    async def create_transaction(self, space_impl=None) -> FusekiPostgreSQLTransaction:
        """Create a PostgreSQL transaction with async context manager support."""
        return await self.begin_transaction()
    
    async def begin_transaction(self) -> FusekiPostgreSQLTransaction:
        """Begin a PostgreSQL transaction."""
        if not self.connected:
            raise RuntimeError("Not connected to PostgreSQL")
        
        try:
            connection = await self.connection_pool.acquire()
            # Track the acquired connection for proper cleanup
            from ...utils.resource_manager import track_connection
            track_connection(connection)
            
            transaction = connection.transaction()
            await transaction.start()
            
            return FusekiPostgreSQLTransaction(connection, transaction, self.connection_pool)
        except Exception as e:
            logger.error(f"Error beginning transaction: {e}")
            # Release connection on error
            if 'connection' in locals():
                await self.connection_pool.release(connection)
            raise
    
    async def commit_transaction(self, transaction: FusekiPostgreSQLTransaction) -> bool:
        """Commit a PostgreSQL transaction and release connection."""
        try:
            await transaction.commit()
            # Release connection back to pool
            await transaction.pool.release(transaction.connection)
            return True
            
        except Exception as e:
            logger.error(f"Error committing transaction: {e}")
            # Release connection on error
            try:
                await transaction.pool.release(transaction.connection)
            except:
                pass
            return False
    
    async def rollback_transaction(self, transaction: FusekiPostgreSQLTransaction) -> bool:
        """Rollback a PostgreSQL transaction and release connection."""
        try:
            await transaction.rollback()
            # Release connection back to pool
            await transaction.pool.release(transaction.connection)
            return True
            
        except Exception as e:
            logger.error(f"Error rolling back transaction: {e}")
            # Release connection on error
            try:
                await transaction.pool.release(transaction.connection)
            except:
                pass
            return False
    
    def get_connection_info(self) -> Dict[str, Any]:
        """Get PostgreSQL connection information."""
        return {
            'type': 'postgresql',
            'backend': 'fuseki_postgresql',
            'host': self.config.get('host', 'localhost'),
            'port': self.config.get('port', 5432),
            'database': self.config.get('database', 'vitalgraph'),
            'connected': self.connected,
            'pool_size': self.connection_pool.get_size() if self.connection_pool else 0,
            'pool_max_size': self.connection_pool.get_max_size() if self.connection_pool else 0
        }
    
    def set_signal_manager(self, signal_manager):
        """Set the signal manager for this database implementation."""
        self.signal_manager = signal_manager
        logger.info("Signal manager set on FusekiPostgreSQLDbImpl")
    
    def get_signal_manager(self):
        """Get the signal manager for this database implementation."""
        return getattr(self, 'signal_manager', None)
    
    
    async def initialize_schema(self) -> bool:
        """Verify PostgreSQL admin tables exist - they should be created during service initialization."""
        try:
            # Verify admin tables exist (they should be created during service setup)
            if not await self._verify_admin_tables_exist():
                logger.error("PostgreSQL admin tables do not exist - run service initialization first")
                return False
            
            logger.debug("PostgreSQL admin tables verified successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying PostgreSQL schema: {e}")
            return False
    
    async def _verify_admin_tables_exist(self) -> bool:
        """Verify that admin tables exist (should be created during service initialization)."""
        try:
            # Check if the core admin tables exist
            check_query = """
            SELECT COUNT(*) as table_count
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('install', 'space', 'graph', 'user')
            """
            
            result = await self.execute_query(check_query)
            table_count = result[0]['table_count'] if result else 0
            
            # All 4 admin tables should exist
            return table_count == 4
            
        except Exception as e:
            logger.error(f"Error verifying admin tables existence: {e}")
            return False
    
    async def space_data_tables_exist(self, space_id: str) -> bool:
        """Check if primary data tables exist for a space."""
        try:
            prefix = f"{space_id}_"
            
            # Check if both term and rdf_quad tables exist
            check_query = """
            SELECT COUNT(*) as table_count
            FROM information_schema.tables 
            WHERE table_name IN ($1, $2)
            AND table_schema = 'public'
            """
            
            results = await self.execute_query(
                check_query, 
                [f'{prefix}term', f'{prefix}rdf_quad']
            )
            
            if results and len(results) > 0:
                return results[0]['table_count'] == 2
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking data tables for space {space_id}: {e}")
            return False
    
    async def get_graph_uris(self, space_id: str) -> List[str]:
        """
        Get list of all graph URIs in a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            List of graph URIs
        """
        try:
            prefix = f"{space_id}_"
            
            query = f"""
            SELECT DISTINCT c_term.term_text as graph_uri
            FROM {prefix}rdf_quad q
            JOIN {prefix}term c_term ON q.context_uuid = c_term.term_uuid
            ORDER BY c_term.term_text
            """
            
            results = await self.execute_query(query)
            if results:
                return [row['graph_uri'] for row in results]
            return []
            
        except Exception as e:
            logger.error(f"Error getting graph URIs for space {space_id}: {e}")
            return []
    
    async def get_unique_subjects(self, space_id: str, graph_uri: str, 
                                 limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """
        Get paginated list of unique subjects in a graph with sorting.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to query (required)
            limit: Maximum number of subjects to return
            offset: Offset for pagination
            
        Returns:
            Dictionary with:
                - start_index: Starting index of this page
                - end_index: Ending index of this page
                - status: 'success' or 'error'
                - subjects: List of unique subject URIs (sorted)
                - total_count: Total number of unique subjects in the graph
                - error: Error message if status is 'error'
        """
        try:
            prefix = f"{space_id}_"
            
            # Get total count of unique subjects in this graph
            count_query = f"""
            SELECT COUNT(DISTINCT q.subject_uuid) as count
            FROM {prefix}rdf_quad q
            JOIN {prefix}term c_term ON q.context_uuid = c_term.term_uuid
            WHERE c_term.term_text = $1
            """
            
            count_results = await self.execute_query(count_query, [graph_uri])
            total_count = count_results[0]['count'] if count_results else 0
            
            # Get paginated unique subjects
            query = f"""
            SELECT DISTINCT s_term.term_text as subject
            FROM {prefix}rdf_quad q
            JOIN {prefix}term s_term ON q.subject_uuid = s_term.term_uuid
            JOIN {prefix}term c_term ON q.context_uuid = c_term.term_uuid
            WHERE c_term.term_text = $1
            ORDER BY s_term.term_text
            LIMIT $2
            OFFSET $3
            """
            
            results = await self.execute_query(query, [graph_uri, limit, offset])
            
            subjects = []
            if results:
                subjects = [row['subject'] for row in results]
            
            return {
                'start_index': offset,
                'end_index': offset + len(subjects),
                'status': 'success',
                'subjects': subjects,
                'total_count': total_count
            }
            
        except Exception as e:
            logger.error(f"Error getting unique subjects for space {space_id}, graph {graph_uri}: {e}")
            return {
                'start_index': offset,
                'end_index': offset,
                'status': 'error',
                'subjects': [],
                'total_count': 0,
                'error': str(e)
            }
    
    async def get_unique_predicates(self, space_id: str, graph_uri: str, 
                                   limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """
        Get paginated list of unique predicates (property URIs) in a graph with sorting.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to query (required)
            limit: Maximum number of predicates to return
            offset: Offset for pagination
            
        Returns:
            Dictionary with:
                - start_index: Starting index of this page
                - end_index: Ending index of this page
                - status: 'success' or 'error'
                - predicates: List of unique predicate URIs (sorted)
                - total_count: Total number of unique predicates in the graph
                - error: Error message if status is 'error'
        """
        try:
            prefix = f"{space_id}_"
            
            # Get total count of unique predicates in this graph
            count_query = f"""
            SELECT COUNT(DISTINCT q.predicate_uuid) as count
            FROM {prefix}rdf_quad q
            JOIN {prefix}term c_term ON q.context_uuid = c_term.term_uuid
            WHERE c_term.term_text = $1
            """
            
            count_results = await self.execute_query(count_query, [graph_uri])
            total_count = count_results[0]['count'] if count_results else 0
            
            # Get paginated unique predicates
            query = f"""
            SELECT DISTINCT p_term.term_text as predicate
            FROM {prefix}rdf_quad q
            JOIN {prefix}term p_term ON q.predicate_uuid = p_term.term_uuid
            JOIN {prefix}term c_term ON q.context_uuid = c_term.term_uuid
            WHERE c_term.term_text = $1
            ORDER BY p_term.term_text
            LIMIT $2
            OFFSET $3
            """
            
            results = await self.execute_query(query, [graph_uri, limit, offset])
            
            predicates = []
            if results:
                predicates = [row['predicate'] for row in results]
            
            return {
                'start_index': offset,
                'end_index': offset + len(predicates),
                'status': 'success',
                'predicates': predicates,
                'total_count': total_count
            }
            
        except Exception as e:
            logger.error(f"Error getting unique predicates for space {space_id}, graph {graph_uri}: {e}")
            return {
                'start_index': offset,
                'end_index': offset,
                'status': 'error',
                'predicates': [],
                'total_count': 0,
                'error': str(e)
            }
    
    async def get_space_stats(self, space_id: str) -> Dict[str, Any]:
        """
        Get comprehensive statistics for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            Dictionary with:
                - total_quad_count: Total number of quads in the space
                - graph_uris: List of all graph URIs
                - graphs: Dict mapping graph URI to stats:
                    - quad_count: Number of quads in this graph
                    - unique_subjects: Number of unique subjects in this graph
                    - unique_predicates: Number of unique predicates in this graph
        """
        try:
            prefix = f"{space_id}_"
            
            # Get total quad count
            total_count = await self.count_quads(space_id)
            
            # Get per-graph statistics in a single query
            query = f"""
            SELECT 
                c_term.term_text as graph_uri,
                COUNT(*) as quad_count,
                COUNT(DISTINCT q.subject_uuid) as unique_subjects,
                COUNT(DISTINCT q.predicate_uuid) as unique_predicates
            FROM {prefix}rdf_quad q
            JOIN {prefix}term c_term ON q.context_uuid = c_term.term_uuid
            GROUP BY c_term.term_text
            ORDER BY c_term.term_text
            """
            
            results = await self.execute_query(query)
            
            graph_uris = []
            graphs = {}
            
            if results:
                for row in results:
                    graph_uri = row['graph_uri']
                    graph_uris.append(graph_uri)
                    graphs[graph_uri] = {
                        'quad_count': row['quad_count'],
                        'unique_subjects': row['unique_subjects'],
                        'unique_predicates': row['unique_predicates']
                    }
            
            return {
                'total_quad_count': total_count,
                'graph_uris': graph_uris,
                'graphs': graphs
            }
            
        except Exception as e:
            logger.error(f"Error getting space stats for space {space_id}: {e}")
            return {
                'total_quad_count': 0,
                'graph_uris': [],
                'graphs': {},
                'error': str(e)
            }
    
    async def count_quads(self, space_id: str, graph_uri: Optional[str] = None) -> int:
        """
        Count total number of quads in a space, optionally filtered by graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Optional graph URI to filter by
            
        Returns:
            Total count of quads in the space (or graph if specified)
        """
        try:
            prefix = f"{space_id}_"
            
            if graph_uri:
                # Count quads in a specific graph
                query = f"""
                SELECT COUNT(*) as count 
                FROM {prefix}rdf_quad q
                JOIN {prefix}term c_term ON q.context_uuid = c_term.term_uuid
                WHERE c_term.term_text = $1
                """
                results = await self.execute_query(query, [graph_uri])
            else:
                # Count all quads
                query = f"SELECT COUNT(*) as count FROM {prefix}rdf_quad"
                results = await self.execute_query(query)
            
            if results and len(results) > 0:
                return results[0]['count']
            return 0
            
        except Exception as e:
            logger.error(f"Error counting quads for space {space_id}: {e}")
            return 0
    
    async def get_data_quads(self, space_id: str, limit: int = 100, offset: int = 0, 
                            graph_uri: Optional[str] = None) -> Dict[str, Any]:
        """
        Get quads from PostgreSQL primary data tables with pagination.
        
        Args:
            space_id: Space identifier
            limit: Maximum number of quads to return
            offset: Offset for pagination
            graph_uri: Optional graph URI to filter by
            
        Returns:
            Dictionary with:
                - start_index: Starting index of this page
                - end_index: Ending index of this page
                - status: 'success' or 'error'
                - quads: List of tuples (graph, subject, predicate, object)
                - error: Error message if status is 'error'
        """
        try:
            prefix = f"{space_id}_"
            
            # Query to get quads from primary data tables with JOINs to resolve UUIDs
            if graph_uri:
                query = f"""
                SELECT 
                    c_term.term_text as graph,
                    s_term.term_text as subject,
                    p_term.term_text as predicate,
                    o_term.term_text as object
                FROM {prefix}rdf_quad q
                JOIN {prefix}term s_term ON q.subject_uuid = s_term.term_uuid
                JOIN {prefix}term p_term ON q.predicate_uuid = p_term.term_uuid  
                JOIN {prefix}term o_term ON q.object_uuid = o_term.term_uuid
                JOIN {prefix}term c_term ON q.context_uuid = c_term.term_uuid
                WHERE c_term.term_text = $1
                ORDER BY c_term.term_text, s_term.term_text, p_term.term_text, o_term.term_text
                LIMIT $2
                OFFSET $3
                """
                results = await self.execute_query(query, [graph_uri, limit, offset])
            else:
                query = f"""
                SELECT 
                    c_term.term_text as graph,
                    s_term.term_text as subject,
                    p_term.term_text as predicate,
                    o_term.term_text as object
                FROM {prefix}rdf_quad q
                JOIN {prefix}term s_term ON q.subject_uuid = s_term.term_uuid
                JOIN {prefix}term p_term ON q.predicate_uuid = p_term.term_uuid  
                JOIN {prefix}term o_term ON q.object_uuid = o_term.term_uuid
                JOIN {prefix}term c_term ON q.context_uuid = c_term.term_uuid
                ORDER BY c_term.term_text, s_term.term_text, p_term.term_text, o_term.term_text
                LIMIT $1
                OFFSET $2
                """
                results = await self.execute_query(query, [limit, offset])
            
            # Convert results to list of tuples
            quads = []
            if results:
                for row in results:
                    quads.append((row['graph'], row['subject'], row['predicate'], row['object']))
            
            return {
                'start_index': offset,
                'end_index': offset + len(quads),
                'status': 'success',
                'quads': quads
            }
            
        except Exception as e:
            logger.error(f"Error getting data quads for space {space_id}: {e}")
            return {
                'start_index': offset,
                'end_index': offset,
                'status': 'error',
                'quads': [],
                'error': str(e)
            }
    
    async def create_space_data_tables(self, space_id: str) -> bool:
        """Create primary data tables for a specific space."""
        try:
            logger.info(f"Creating primary data tables for space: {space_id}")
            
            space_table_statements = self.schema.create_space_tables_sql(space_id)
            for statement in space_table_statements:
                await self.execute_update(statement)
            
            logger.info(f"Primary data tables created for space: {space_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating data tables for space {space_id}: {e}")
            return False
    
    async def drop_space_data_tables(self, space_id: str) -> bool:
        """Drop primary data tables for a specific space."""
        try:
            logger.info(f"Dropping primary data tables for space: {space_id}")
            
            drop_statements = self.schema.drop_space_tables_sql(space_id)
            for statement in drop_statements:
                await self.execute_update(statement)
            
            logger.info(f"Primary data tables dropped for space: {space_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error dropping data tables for space {space_id}: {e}")
            return False
    
    def _extract_term_info(self, rdf_term) -> tuple:
        """
        Extract term information from RDFLib term object or formatted string.
        
        Args:
            rdf_term: RDFLib term (URIRef, Literal, BNode) or formatted string
        
        Returns:
            Tuple of (unwrapped_value, term_type, lang, datatype_uri)
        """
        from rdflib import URIRef, Literal, BNode, Graph
        
        if isinstance(rdf_term, URIRef):
            return (str(rdf_term), 'U', None, None)
        
        elif isinstance(rdf_term, Literal):
            # Extract unwrapped value and metadata from RDFLib Literal
            value = str(rdf_term)  # Unwrapped value
            lang = str(rdf_term.language) if rdf_term.language else None
            datatype_uri = str(rdf_term.datatype) if rdf_term.datatype else None
            return (value, 'L', lang, datatype_uri)
        
        elif isinstance(rdf_term, BNode):
            return (str(rdf_term), 'B', None, None)
        
        else:
            # Handle formatted string literals from SPARQL parser using RDFLib
            term_str = str(rdf_term)
            
            # Quick check: if no RDF syntax markers, return as-is
            if not any(marker in term_str for marker in ['"', '^^', '@', '<', '_:']):
                return (term_str, 'L', None, None)
            
            try:
                # For typed literals, extract the value directly from the string to preserve precision
                # Format: "value"^^<datatype> or "value"@lang
                if '^^' in term_str:
                    # Typed literal: "value"^^<datatype>
                    # Extract the value between quotes to preserve original precision
                    if term_str.startswith('"'):
                        end_quote = term_str.find('"', 1)
                        if end_quote > 0:
                            value = term_str[1:end_quote]
                            return (value, 'L', None, None)
                elif '@' in term_str and term_str.startswith('"'):
                    # Language-tagged literal: "value"@lang
                    end_quote = term_str.find('"', 1)
                    if end_quote > 0:
                        value = term_str[1:end_quote]
                        return (value, 'L', None, None)
                
                # Fallback: Parse as N-Triples object using dummy triple
                # Format: <s> <p> <object> .
                dummy_triple = f'<urn:s> <urn:p> {term_str} .'
                
                graph = Graph()
                graph.parse(data=dummy_triple, format='nt')
                
                # Extract the object (third element of the triple)
                for s, p, o in graph:
                    if isinstance(o, Literal):
                        value = str(o)
                        return (value, 'L', None, None)
                    elif isinstance(o, URIRef):
                        return (str(o), 'U', None, None)
                    elif isinstance(o, BNode):
                        return (str(o), 'B', None, None)
                
                # Fallback if parsing didn't produce expected result
                return (term_str, 'L', None, None)
                
            except Exception:
                # If RDFLib parsing fails, treat as plain literal
                # Strip quotes if present for plain literals
                if term_str.startswith('"') and term_str.endswith('"') and len(term_str) > 1:
                    return (term_str[1:-1], 'L', None, None)
                return (term_str, 'L', None, None)
    
    async def store_quads_to_postgresql(self, space_id: str, quads: List[tuple], 
                                       transaction: 'FusekiPostgreSQLTransaction' = None) -> bool:
        """
        Store RDF quads to PostgreSQL primary data tables.
        This is part of the dual-write system.
        
        Args:
            space_id: Space identifier
            quads: List of quad tuples with RDFLib objects (s, p, o, g)
                   where s, p, o, g can be URIRef, Literal, BNode, or string
            transaction: Optional transaction object. If provided, uses transaction connection.
                        If None, acquires connection from pool.
        
        Uses the FusekiPostgreSQLSpaceTerms class for proper term management.
        """
        try:
            if not quads:
                return True
                
            logger.debug(f"Storing {len(quads)} quads for space {space_id}")
            
            # Import the adapted terms class
            from .fuseki_postgresql_space_terms import FusekiPostgreSQLSpaceTerms
            from datetime import datetime
            
            # Create a terms manager instance (simplified for this context)
            terms_manager = FusekiPostgreSQLSpaceTerms(self)
            
            # Use proper table naming convention
            prefix = f"{space_id}_"
            term_table = f"{prefix}term"
            quad_table = f"{prefix}rdf_quad"
            
            # Step 1: Collect unique RDFLib term objects (not strings)
            term_uuid_map = {}
            unique_terms = {}  # Map: str(term) -> rdf_term object
            
            for i, quad in enumerate(quads):
                try:
                    # Debug logging for problematic quads
                    # logger.debug(f"Processing quad {i}: {type(quad)} = {quad}")
                    
                    # Validate quad is a proper tuple/list
                    if not isinstance(quad, (tuple, list)):
                        logger.error(f"Invalid quad type at index {i}: {type(quad)} = {quad}")
                        continue
                    
                    # Handle tuple format: (subject, predicate, object, graph)
                    if len(quad) >= 4:
                        subject, predicate, obj, graph = quad[:4]
                    else:
                        subject, predicate, obj = quad[:3]
                        graph = 'default'
                    
                    # Store RDFLib objects, keyed by their string representation
                    for term in [subject, predicate, obj, graph]:
                        term_key = str(term)
                        if term_key and term_key not in unique_terms:
                            unique_terms[term_key] = term
                            
                except Exception as quad_error:
                    logger.error(f"Error processing quad {i}: {quad_error} - quad: {quad}")
                    continue
            
            # Step 2: Batch process terms - extract info from RDFLib objects
            terms_to_insert = []
            for term_key, rdf_term in unique_terms.items():
                # Extract info directly from RDFLib object
                unwrapped_value, term_type, lang, datatype_uri = self._extract_term_info(rdf_term)
                
                # TODO: Resolve datatype_id if datatype present
                # For now, set to None since FusekiPostgreSQLDbImpl doesn't have space_impl
                # This maintains the original behavior while fixing the UUID mismatch
                datatype_id = None
                # if datatype_uri:
                #     datatype_id = await self.space_impl.datatypes.get_or_create_datatype_id(
                #         space_id, datatype_uri
                #     )
                
                # Generate UUID from UNWRAPPED value for consistency across paths
                term_uuid = FusekiPostgreSQLSpaceTerms.generate_term_uuid(
                    unwrapped_value, term_type, lang, datatype_id
                )
                
                # Map string representation to UUID for quad insertion
                term_uuid_map[term_key] = str(term_uuid)
                
                # Store unwrapped value in PostgreSQL
                terms_to_insert.append((str(term_uuid), unwrapped_value, term_type, lang, datatype_id))
            
            # Batch check which terms already exist
            # Must check with dataset='primary' to match the default value used in INSERT
            if terms_to_insert:
                term_uuids = [t[0] for t in terms_to_insert]
                placeholders = ','.join([f'${i+1}' for i in range(len(term_uuids))])
                # Check with dataset='primary' since INSERT doesn't specify dataset (uses schema default)
                check_query = f"SELECT term_uuid FROM {term_table} WHERE term_uuid IN ({placeholders}) AND dataset = 'primary'"
                logger.info(f"Checking for {len(term_uuids)} existing terms with dataset='primary'")
                existing_terms = await self.execute_query(check_query, term_uuids)
                # Ensure UUIDs are strings to match terms_to_insert format
                existing_uuids = {str(row['term_uuid']) for row in existing_terms}
                logger.info(f"Found {len(existing_uuids)} existing terms out of {len(term_uuids)} checked")
                
                # Filter out existing terms
                new_terms = [t for t in terms_to_insert if t[0] not in existing_uuids]
                logger.info(f"Will insert {len(new_terms)} new terms (filtered out {len(terms_to_insert) - len(new_terms)} existing)")
                
                # Batch insert new terms using INSERT ... ON CONFLICT DO NOTHING for safety
                if new_terms:
                    logger.info(f"Batch inserting {len(new_terms)} new terms (out of {len(terms_to_insert)} total)")
                    now = datetime.utcnow()
                    
                    # Use executemany for batch insert
                    insert_query = f"""
                        INSERT INTO {term_table} 
                        (term_uuid, term_text, term_type, lang, datatype_id, created_time)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """
                    
                    # Use transaction connection if provided, else acquire from pool
                    if transaction:
                        conn = transaction.get_connection()
                        await conn.executemany(insert_query, [
                            (uuid, text, ttype, lang, dtype_id, now) 
                            for uuid, text, ttype, lang, dtype_id in new_terms
                        ])
                    else:
                        async with self.connection_pool.acquire() as conn:
                            await conn.executemany(insert_query, [
                                (uuid, text, ttype, lang, dtype_id, now) 
                                for uuid, text, ttype, lang, dtype_id in new_terms
                            ])
                    
                    logger.debug(f"Successfully inserted {len(new_terms)} new terms")
                else:
                    logger.debug(f"All {len(terms_to_insert)} terms already exist, skipping insert")
            
            # Step 3: Batch insert quad relationships
            quads_to_insert = []
            for i, quad in enumerate(quads):
                try:
                    # Validate quad is a proper tuple/list
                    if not isinstance(quad, (tuple, list)):
                        logger.error(f"Invalid quad type at index {i} during insertion: {type(quad)} = {quad}")
                        continue
                    
                    # Handle tuple format: (subject, predicate, object, graph)
                    if len(quad) >= 4:
                        subject, predicate, obj, graph = quad[:4]
                    else:
                        subject, predicate, obj = quad[:3]
                        graph = 'default'
                    
                    subject_uuid = term_uuid_map.get(str(subject))
                    predicate_uuid = term_uuid_map.get(str(predicate))
                    object_uuid = term_uuid_map.get(str(obj))
                    context_uuid = term_uuid_map.get(str(graph))
                    
                    if all([subject_uuid, predicate_uuid, object_uuid, context_uuid]):
                        quads_to_insert.append((subject_uuid, predicate_uuid, object_uuid, context_uuid))
                    
                except Exception as quad_error:
                    logger.error(f"Error processing quad {i} during insertion: {quad_error} - quad: {quad}")
                    continue
            
            # Batch insert all quads
            if quads_to_insert:
                logger.debug(f"Batch inserting {len(quads_to_insert)} quads")
                now = datetime.utcnow()
                
                quad_insert_query = f"""
                    INSERT INTO {quad_table} (subject_uuid, predicate_uuid, object_uuid, context_uuid, created_time)
                    VALUES ($1, $2, $3, $4, $5)
                """
                
                # Use transaction connection if provided, else acquire from pool
                if transaction:
                    conn = transaction.get_connection()
                    await conn.executemany(quad_insert_query, [
                        (s, p, o, c, now) for s, p, o, c in quads_to_insert
                    ])
                else:
                    async with self.connection_pool.acquire() as conn:
                        await conn.executemany(quad_insert_query, [
                            (s, p, o, c, now) for s, p, o, c in quads_to_insert
                        ])
                
                logger.debug(f"Successfully inserted {len(quads_to_insert)} quads")
            
            logger.debug(f"Successfully stored {len(quads)} quads and {len(unique_terms)} terms for space {space_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error storing quads for space {space_id}: {e}")
            return False
    
    async def remove_quads_from_postgresql(self, space_id: str, quads: List[tuple],
                                          transaction: 'FusekiPostgreSQLTransaction' = None) -> bool:
        """
        Remove RDF quads from PostgreSQL primary data tables.
        This is part of the dual-write system.
        
        Args:
            space_id: Space identifier
            quads: List of quad tuples to remove
            transaction: Optional transaction object. If provided, uses transaction connection.
                        If None, uses execute_update/execute_query methods.
        
        Uses the FusekiPostgreSQLSpaceTerms class for proper term management.
        """
        try:
            if not quads:
                return True
                
            logger.debug(f"Batch removing {len(quads)} quads for space {space_id}")
            
            # Step 1: Collect all unique terms from quads and unwrap literals
            # Need to map: formatted_string -> unwrapped_value for UUID lookup
            term_unwrap_map = {}  # Maps formatted string to unwrapped value
            
            for quad in quads:
                if len(quad) >= 4:
                    subject, predicate, obj, graph = quad[:4]
                else:
                    subject, predicate, obj = quad[:3]
                    graph = 'default'
                
                # For each term, extract unwrapped value for UUID lookup
                for term in [subject, predicate, obj, graph]:
                    formatted_str = str(term)
                    if formatted_str not in term_unwrap_map:
                        # Extract unwrapped value (handles both RDFLib objects and formatted strings)
                        unwrapped_value, _, _, _ = self._extract_term_info(term)
                        term_unwrap_map[formatted_str] = unwrapped_value
            
            unique_terms = set(term_unwrap_map.values())  # Use unwrapped values for lookup
            logger.debug(f"Collected {len(unique_terms)} unique unwrapped terms from {len(quads)} quads")
            
            # Step 2: Batch UUID lookup - single query for all terms
            term_table = f"{space_id}_term"
            term_list = list(unique_terms)
            placeholders = ','.join([f'${i+1}' for i in range(len(term_list))])
            batch_lookup_query = f"""
                SELECT term_text, term_uuid 
                FROM {term_table} 
                WHERE term_text IN ({placeholders}) 
                  AND dataset = ${len(term_list) + 1}
            """
            
            # Execute batch lookup using transaction connection or execute_query
            if transaction:
                conn = transaction.get_connection()
                rows = await conn.fetch(batch_lookup_query, *term_list, 'primary')
            else:
                rows = await self.execute_query(batch_lookup_query, term_list + ['primary'])
            
            # Build term_text -> UUID map
            term_uuid_map = {row['term_text']: row['term_uuid'] for row in rows}
            logger.debug(f"Batch lookup found {len(term_uuid_map)} UUIDs out of {len(unique_terms)} terms")
            
            # Step 3: Validate all terms found (data integrity check) with float precision matching
            missing_terms = unique_terms - set(term_uuid_map.keys())
            if missing_terms:
                logger.debug(f"Initial lookup: {len(missing_terms)} terms not found, attempting prefix match for float precision")
                
                # For missing terms that look like floats, try prefix matching
                # This handles Fuseki's float truncation (e.g., '32785.68' should match '32785.67923076924')
                for missing_term in list(missing_terms):
                    try:
                        missing_float = float(missing_term)
                        # It's a number - try prefix matching by dropping the last digit
                        if '.' in missing_term:
                            prefix = missing_term[:-1]  # '32785.68' → '32785.6'
                            pattern = f"{prefix}%"
                            
                            fuzzy_query = f"""
                                SELECT term_text, term_uuid 
                                FROM {term_table} 
                                WHERE term_text LIKE $1 AND dataset = $2
                            """
                            
                            if transaction:
                                conn = transaction.get_connection()
                                rows = await conn.fetch(fuzzy_query, pattern, 'primary')
                            else:
                                rows = await self.execute_query(fuzzy_query, [pattern, 'primary'])
                            
                            # Find the closest numeric match
                            for row in rows:
                                try:
                                    db_float = float(row['term_text'])
                                    # Check if values are close (within 1% tolerance for float rounding)
                                    if abs(db_float - missing_float) / max(abs(db_float), abs(missing_float), 1) < 0.01:
                                        term_uuid_map[missing_term] = row['term_uuid']
                                        logger.info(f"🔍 Float precision fix: '{missing_term}' → '{row['term_text']}'")
                                        break
                                except (ValueError, TypeError):
                                    continue
                    except (ValueError, TypeError):
                        # Not a numeric value, skip fuzzy matching
                        pass
                
                # Re-check for still-missing terms after prefix matching
                still_missing = unique_terms - set(term_uuid_map.keys())
                if still_missing:
                    logger.error(f"DELETE failed - missing UUIDs for {len(still_missing)} terms after prefix matching")
                    logger.error(f"Missing terms (first 5): {list(still_missing)[:5]}")
                    return False
            
            # Step 4: Build list of quad UUID tuples for batch delete
            quad_table = f"{space_id}_rdf_quad"
            quad_uuids = []
            
            for quad in quads:
                if len(quad) >= 4:
                    subject, predicate, obj, graph = quad[:4]
                else:
                    subject, predicate, obj = quad[:3]
                    graph = 'default'
                
                # Look up UUIDs using unwrapped values
                subject_unwrapped = term_unwrap_map.get(str(subject))
                predicate_unwrapped = term_unwrap_map.get(str(predicate))
                object_unwrapped = term_unwrap_map.get(str(obj))
                graph_unwrapped = term_unwrap_map.get(str(graph))
                
                subject_uuid = term_uuid_map.get(subject_unwrapped)
                predicate_uuid = term_uuid_map.get(predicate_unwrapped)
                object_uuid = term_uuid_map.get(object_unwrapped)
                context_uuid = term_uuid_map.get(graph_unwrapped)
                
                if all([subject_uuid, predicate_uuid, object_uuid, context_uuid]):
                    quad_uuids.append((subject_uuid, predicate_uuid, object_uuid, context_uuid, 'primary'))
                else:
                    logger.warning(f"Skipping quad due to missing UUID: {subject} {predicate} {obj} (graph: {graph})")
            
            logger.debug(f"Prepared {len(quad_uuids)} quad UUIDs for batch deletion")
            
            if not quad_uuids:
                logger.warning(f"No valid quads to delete after UUID mapping")
                return True
            
            # Step 5: Batch DELETE using executemany
            delete_query = f"""
                DELETE FROM {quad_table} 
                WHERE subject_uuid = $1 
                  AND predicate_uuid = $2 
                  AND object_uuid = $3 
                  AND context_uuid = $4
                  AND dataset = $5
            """
            
            # Execute batch delete using transaction connection or connection pool
            if transaction:
                conn = transaction.get_connection()
                await conn.executemany(delete_query, quad_uuids)
            else:
                async with self.connection_pool.acquire() as conn:
                    await conn.executemany(delete_query, quad_uuids)
            
            logger.debug(f"Batch deleted {len(quad_uuids)} quads for space {space_id}")
            
            # Step 3: Clean up orphaned terms (terms not referenced by any quads)
            # This follows the existing PostgreSQL implementation pattern
            term_table = f"{space_id}_term"
            for term_uuid in term_uuid_map.values():
                orphan_check_query = f"""
                    SELECT COUNT(*) as count FROM {quad_table} 
                    WHERE subject_uuid = $1 OR predicate_uuid = $1 OR object_uuid = $1 OR context_uuid = $1
                """
                
                # Use transaction connection if provided, else execute_query
                if transaction:
                    conn = transaction.get_connection()
                    result = await conn.fetch(orphan_check_query, term_uuid)
                else:
                    result = await self.execute_query(orphan_check_query, [term_uuid])
                
                if result and result[0]['count'] == 0:
                    # Term is orphaned, remove it
                    if transaction:
                        conn = transaction.get_connection()
                        await conn.execute(f"DELETE FROM {term_table} WHERE term_uuid = $1", term_uuid)
                    else:
                        await self.execute_update(f"DELETE FROM {term_table} WHERE term_uuid = $1", [term_uuid])
            
            logger.debug(f"Successfully removed {len(quads)} quads for space {space_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error removing quads for space {space_id}: {e}")
            return False
