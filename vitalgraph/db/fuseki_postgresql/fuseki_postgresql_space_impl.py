"""
Main hybrid space implementation for FUSEKI_POSTGRESQL backend.
Orchestrates Fuseki datasets, PostgreSQL primary data storage, and dual-write operations.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List, Union
import json

from ..backend_config import SpaceBackendInterface
from .fuseki_dataset_manager import FusekiDatasetManager
from .postgresql_db_impl import FusekiPostgreSQLDbImpl
from .postgresql_signal_manager import PostgreSQLSignalManager
from .dual_write_coordinator import DualWriteCoordinator
from .sparql_update_parser import SPARQLUpdateParser
from .fuseki_postgresql_space_graphs import FusekiPostgreSQLSpaceGraphs
from .entity_lock_manager import EntityLockManager

logger = logging.getLogger(__name__)


class FusekiPostgreSQLSpaceImpl(SpaceBackendInterface):
    """
    Hybrid implementation combining Fuseki datasets with PostgreSQL primary data storage.
    
    Architecture:
    - Index/Cache operations: Fuseki datasets (fast graph queries)
    - Metadata operations: PostgreSQL tables (structured data)
    - Primary data operations: PostgreSQL quad tables (authoritative storage)
    - Signal operations: PostgreSQL-based notifications
    
    This implementation provides the best of both worlds:
    - Fuseki's high-performance graph operations
    - PostgreSQL's reliability and data persistence capabilities
    - Real-time notifications via PostgreSQL signals
    """
    
    def __init__(self, fuseki_config: dict, postgresql_config: dict):
        """
        Initialize hybrid space implementation.
        
        Args:
            fuseki_config: Fuseki server configuration
            postgresql_config: PostgreSQL database configuration
        """
        self.fuseki_config = fuseki_config
        self.postgresql_config = postgresql_config
        
        # Initialize component managers
        self.fuseki_manager = FusekiDatasetManager(fuseki_config)
        self.postgresql_impl = FusekiPostgreSQLDbImpl(postgresql_config)
        
        # Initialize graph management
        self.graphs = FusekiPostgreSQLSpaceGraphs(self)
        self.signal_manager = PostgreSQLSignalManager(postgresql_config)
        self.entity_lock_manager = EntityLockManager(postgresql_config)
        
        # Initialize dual-write coordinator (graph manager set after initialization)
        self.dual_write_coordinator = DualWriteCoordinator(
            self.fuseki_manager, 
            self.postgresql_impl
        )
        # Set graph manager for auto-registration
        self.dual_write_coordinator.graph_manager = self.graphs
        
        # Initialize SPARQL UPDATE parser
        self.sparql_parser = SPARQLUpdateParser(self.fuseki_manager)
        
        # Initialize database abstraction layers
        from .fuseki_postgresql_db_objects import FusekiPostgreSQLDbObjects
        from .fuseki_postgresql_db_ops import FusekiPostgreSQLDbOps
        
        self.db_objects = FusekiPostgreSQLDbObjects(self)
        self.db_ops = FusekiPostgreSQLDbOps(self)
        
        # Initialize core management (for compatibility with PostgreSQL patterns)
        self.core = self.postgresql_impl
        
        # Connection state
        self.connected = False
        
        logger.info("FusekiPostgreSQLSpaceImpl initialized")
    
    async def connect(self) -> bool:
        """Connect to both Fuseki and PostgreSQL systems."""
        try:
            logger.info("Connecting FUSEKI_POSTGRESQL hybrid backend...")
            
            # Connect to PostgreSQL
            pg_success = await self.postgresql_impl.connect()
            if not pg_success:
                logger.error("Failed to connect to PostgreSQL")
                return False
            
            # Connect to Fuseki
            fuseki_success = await self.fuseki_manager.connect()
            if not fuseki_success:
                logger.error("Failed to connect to Fuseki")
                await self.postgresql_impl.disconnect()
                return False
            
            # Connect signal manager
            signal_success = await self.signal_manager.connect()
            if not signal_success:
                logger.warning("Failed to connect signal manager (non-critical)")
            
            # Connect entity lock manager
            try:
                await self.entity_lock_manager.connect()
            except Exception as e:
                logger.warning(f"Failed to connect entity lock manager (non-critical): {e}")
            
            # Initialize PostgreSQL schema if needed
            schema_success = await self.postgresql_impl.initialize_schema()
            if not schema_success:
                logger.error("Failed to initialize PostgreSQL schema")
                await self.disconnect()
                return False
            
            self.connected = True
            logger.info("FUSEKI_POSTGRESQL hybrid backend connected successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error connecting FUSEKI_POSTGRESQL backend: {e}")
            await self.disconnect()
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from both Fuseki and PostgreSQL systems."""
        try:
            logger.info("Disconnecting FUSEKI_POSTGRESQL hybrid backend...")
            
            success = True
            
            # Disconnect entity lock manager
            if hasattr(self, 'entity_lock_manager'):
                try:
                    await self.entity_lock_manager.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting entity lock manager: {e}")
            
            # Disconnect signal manager
            if hasattr(self, 'signal_manager'):
                signal_success = await self.signal_manager.disconnect()
                if not signal_success:
                    success = False
            
            # Disconnect Fuseki
            if hasattr(self, 'fuseki_manager'):
                fuseki_success = await self.fuseki_manager.disconnect()
                if not fuseki_success:
                    success = False
            
            # Disconnect PostgreSQL
            if hasattr(self, 'postgresql_impl'):
                pg_success = await self.postgresql_impl.disconnect()
                if not pg_success:
                    success = False
            
            self.connected = False
            logger.info("FUSEKI_POSTGRESQL hybrid backend disconnected")
            return success
            
        except Exception as e:
            logger.error(f"Error disconnecting FUSEKI_POSTGRESQL backend: {e}")
            return False
    
    async def is_connected(self) -> bool:
        """Check if hybrid backend is connected."""
        if not self.connected:
            return False
        
        # Check both PostgreSQL and Fuseki connections
        pg_connected = await self.postgresql_impl.is_connected()
        # Note: FusekiDatasetManager doesn't have is_connected method yet
        # fuseki_connected = await self.fuseki_manager.is_connected()
        
        return pg_connected  # and fuseki_connected
    
    # Required abstract methods from SpaceBackendInterface
    
    async def space_exists(self, space_id: str) -> bool:
        """Check if space exists in both systems."""
        fuseki_exists = await self.fuseki_manager.dataset_exists(space_id)
        pg_exists = await self.postgresql_impl.space_data_tables_exist(space_id)
        return fuseki_exists and pg_exists
    
    async def add_namespace(self, space_id: str, prefix: str, uri: str) -> bool:
        """Add namespace - delegate to PostgreSQL."""
        # Namespaces are metadata, store in PostgreSQL
        # For now, return True as namespaces are handled at the endpoint level
        return True
    
    async def get_namespace_uri(self, space_id: str, prefix: str) -> Optional[str]:
        """Get namespace URI - delegate to PostgreSQL."""
        # Namespaces are handled at endpoint level for now
        return None
    
    async def list_namespaces(self, space_id: str) -> Dict[str, str]:
        """List namespaces - delegate to PostgreSQL."""
        # Namespaces are handled at endpoint level for now
        return {}
    
    async def add_term(self, space_id: str, term_text: str, term_type: str, 
                      language: Optional[str] = None, datatype: Optional[str] = None) -> str:
        """Add term - delegate to PostgreSQL primary data storage."""
        # Terms are handled automatically during RDF operations
        return ""
    
    async def get_term_uuid(self, space_id: str, term_text: str, term_type: str,
                           language: Optional[str] = None, datatype: Optional[str] = None) -> Optional[str]:
        """Get term UUID - delegate to PostgreSQL."""
        # Terms are handled automatically during RDF operations
        return None
    
    async def delete_term(self, space_id: str, term_uuid: str) -> bool:
        """Delete term - delegate to PostgreSQL."""
        # Terms are handled automatically during RDF operations
        return True
    
    async def add_rdf_quads(self, space_id: str, quads: List[tuple]) -> bool:
        """Add RDF quads using dual-write coordinator."""
        if not quads:
            return True
        
        # Use dual-write coordinator directly with RDFLib quads
        return await self.dual_write_coordinator.add_quads(space_id, quads)
    
    async def add_rdf_quad(self, space_id: str, subject: str, predicate: str, 
                          obj: str, graph: str) -> bool:
        """Add single RDF quad using dual-write coordinator."""
        # Convert to quad tuple and use batch method
        quad = (subject, predicate, obj, graph)
        return await self.add_rdf_quads(space_id, [quad])
    
    async def remove_rdf_quad(self, space_id: str, subject: str, predicate: str,
                             obj: str, graph: str) -> bool:
        """Remove RDF quad using dual-write coordinator."""
        # Convert to SPARQL DELETE and use dual-write
        delete_sparql = f"""
        DELETE DATA {{
            GRAPH <{graph}> {{
                <{subject}> <{predicate}> <{obj}> .
            }}
        }}
        """
        return await self.dual_write_coordinator.execute_sparql_update(space_id, delete_sparql)
    
    async def get_rdf_quad(self, space_id: str, subject: Optional[str] = None,
                          predicate: Optional[str] = None, obj: Optional[str] = None,
                          graph: Optional[str] = None) -> List[tuple]:
        """Get RDF quads - query Fuseki (primary system)."""
        # Build SPARQL query based on parameters
        where_clauses = []
        if subject:
            where_clauses.append(f"?s = <{subject}>")
        if predicate:
            where_clauses.append(f"?p = <{predicate}>")
        if obj:
            where_clauses.append(f"?o = <{obj}>")
        
        where_filter = f"FILTER ({' && '.join(where_clauses)})" if where_clauses else ""
        graph_clause = f"GRAPH <{graph}>" if graph else "GRAPH ?g"
        
        query = f"""
        SELECT ?s ?p ?o ?g WHERE {{
            {graph_clause} {{
                ?s ?p ?o .
            }}
            {where_filter}
        }}
        """
        
        bindings = await self.fuseki_manager.query_dataset(space_id, query)
        return [{'subject': b['s']['value'], 'predicate': b['p']['value'], 
                'object': b['o']['value'], 'graph': b.get('g', {}).get('value', graph or '')} 
                for b in bindings]
    
    async def get_rdf_quad_count(self, space_id: str, graph: Optional[str] = None) -> int:
        """Get RDF quad count - query Fuseki."""
        graph_clause = f"GRAPH <{graph}>" if graph else "GRAPH ?g"
        query = f"""
        SELECT (COUNT(*) AS ?count) WHERE {{
            {graph_clause} {{
                ?s ?p ?o .
            }}
        }}
        """
        bindings = await self.fuseki_manager.query_dataset(space_id, query)
        return int(bindings[0]['count']['value']) if bindings else 0
    
    async def add_rdf_quads_batch(self, space_id: str, quads: List[tuple]) -> bool:
        """Add RDF quads in batch using dual-write coordinator via db_ops layer."""
        if not quads:
            return True
        
        # Use the db_ops layer which has proper dual-write handling
        added_count = await self.db_ops.add_rdf_quads_batch(space_id, quads)
        
        # Return True if any quads were added successfully
        return added_count > 0
    
    async def remove_rdf_quads_batch(self, space_id: str, quads: List[tuple]) -> bool:
        """Remove RDF quads in batch using dual-write coordinator."""
        if not quads:
            return True
        
        # Use the db_ops layer which has proper dual-write handling
        removed_count = await self.db_ops.remove_rdf_quads_batch(space_id, quads)
        
        # Return True if any quads were removed successfully
        return removed_count > 0
    
    def _format_sparql_term(self, term: str) -> str:
        """Format an RDF term for SPARQL based on its type."""
        if not term:
            return '""'
        
        # Check if it's a URI (starts with http:// or https:// or urn:)
        if str(term).startswith(('http://', 'https://', 'urn:')):
            return f'<{term}>'
        
        # Check if it's already a properly formatted URI in angle brackets
        if str(term).startswith('<') and str(term).endswith('>'):
            return term
        
        # Check if it's a blank node
        if str(term).startswith('_:'):
            return term
        
        # Check if it's a number (integer or decimal)
        try:
            if '.' in term:
                float(term)
                return term  # Decimal literal
            else:
                int(term)
                return term  # Integer literal
        except ValueError:
            pass
        
        # Check if it's already a quoted string literal
        if (term.startswith('"') and term.endswith('"')) or (term.startswith("'") and term.endswith("'")):
            return term
        
        # Default: treat as string literal and escape quotes
        escaped_term = term.replace('"', '\\"')
        return f'"{escaped_term}"'
    
    async def quads(self, space_id: str, quad_pattern: tuple, context: Optional[Any] = None):
        """Generator for quad pattern matching - delegate to Fuseki."""
        # This would implement RDFLib-style quad pattern matching
        # For now, return empty generator
        return
        yield  # Make this a generator
    
    async def get_sparql_impl(self, space_id: str):
        """Get SPARQL implementation - return self as we handle SPARQL via dual-write."""
        return self
    
    async def get_db_connection(self, space_id: str):
        """Get database connection - return PostgreSQL connection."""
        return await self.postgresql_impl.get_db_connection()
    
    async def close(self) -> bool:
        """Close connections - same as disconnect."""
        return await self.disconnect()
    
    async def get_manager_info(self) -> Dict[str, Any]:
        """Get manager information."""
        return {
            'backend_type': 'fuseki_postgresql',
            'fuseki_info': self.fuseki_manager.get_connection_info() if hasattr(self.fuseki_manager, 'get_connection_info') else {},
            'postgresql_info': self.postgresql_impl.get_connection_info(),
            'connected': self.connected
        }
    
    # Space lifecycle operations
    
    async def create_space_storage(self, space_id: str) -> bool:
        """Create storage for a new space in both Fuseki and PostgreSQL."""
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        logger.info(f"Creating hybrid storage for space: {space_id}")
        
        try:
            # Use dual-write coordinator to create storage
            success = await self.dual_write_coordinator.create_space_storage(space_id)
            
            if success:
                # Send space created notification
                await self.signal_manager.notify_space_created(space_id)
                logger.info(f"Hybrid storage created successfully for space: {space_id}")
            else:
                logger.error(f"Failed to create hybrid storage for space: {space_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error creating space storage for {space_id}: {e}")
            return False
    
    async def delete_space_storage(self, space_id: str) -> bool:
        """Delete storage for a space from both Fuseki and PostgreSQL."""
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        logger.info(f"Deleting hybrid storage for space: {space_id}")
        
        try:
            # Use dual-write coordinator to delete storage
            success = await self.dual_write_coordinator.delete_space_storage(space_id)
            
            if success:
                # Also delete space metadata from PostgreSQL admin tables
                metadata_success = await self.delete_space_metadata(space_id)
                if not metadata_success:
                    logger.warning(f"Failed to delete space metadata for {space_id}, but storage deletion succeeded")
                
                # Send space deleted notification
                await self.signal_manager.notify_space_deleted(space_id)
                logger.info(f"Hybrid storage deleted successfully for space: {space_id}")
            else:
                logger.error(f"Failed to delete hybrid storage for space: {space_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error deleting space storage for {space_id}: {e}")
            return False
    
    async def space_storage_exists(self, space_id: str) -> bool:
        """Check if storage exists for a space."""
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        try:
            # Check if Fuseki dataset exists (primary indicator)
            return await self.fuseki_manager.dataset_exists(space_id)
            
        except Exception as e:
            logger.error(f"Error checking space storage existence for {space_id}: {e}")
            return False
    
    # Graph data operations (index/cache: Fuseki, primary data: PostgreSQL)
    
    async def execute_sparql_update(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute SPARQL UPDATE with dual-write to both Fuseki and PostgreSQL.
        
        This is the main entry point for graph updates in the hybrid backend.
        Parses the SPARQL UPDATE to determine affected triples, then coordinates
        the dual-write operation.
        
        Args:
            space_id: Target space identifier
            sparql_update: SPARQL UPDATE query string
            
        Returns:
            True if both operations succeeded, False otherwise
        """
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        logger.debug(f"Executing SPARQL UPDATE on space {space_id}")
        
        try:
            # Use dual-write coordinator for SPARQL UPDATE execution
            success = await self.dual_write_coordinator.execute_sparql_update(space_id, sparql_update)
            
            if success:
                # Send graph updated notification
                await self.signal_manager.notify_graph_updated(space_id, "default")
                logger.debug(f"SPARQL UPDATE successful on space {space_id}")
            else:
                logger.error(f"SPARQL UPDATE failed on space {space_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error executing SPARQL UPDATE on space {space_id}: {e}")
            return False
    
    async def add_quads(self, space_id: str, quads: List[tuple]) -> bool:
        """Add RDF quads using dual-write to both Fuseki and PostgreSQL."""
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        if not quads:
            return True
        
        logger.debug(f"Adding {len(quads)} quads to space {space_id}")
        
        try:
            # Use dual-write coordinator for consistency
            success = await self.dual_write_coordinator.add_quads(space_id, quads)
            
            if success:
                # Send graph updated notification
                await self.signal_manager.notify_graph_updated(space_id, "default")
                logger.debug(f"Successfully added {len(quads)} quads to space {space_id}")
            else:
                logger.error(f"Failed to add quads to space {space_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error adding quads to space {space_id}: {e}")
            return False
    
    async def remove_quads(self, space_id: str, quads: List[tuple]) -> bool:
        """Remove RDF quads using dual-write from both Fuseki and PostgreSQL."""
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        if not quads:
            return True
        
        logger.debug(f"Removing {len(quads)} quads from space {space_id}")
        
        try:
            # Use dual-write coordinator for consistency
            success = await self.dual_write_coordinator.remove_quads(space_id, quads)
            
            if success:
                # Send graph updated notification
                await self.signal_manager.notify_graph_updated(space_id, "default")
                logger.debug(f"Successfully removed {len(quads)} quads from space {space_id}")
            else:
                logger.error(f"Failed to remove quads from space {space_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error removing quads from space {space_id}: {e}")
            return False
    
    async def query_quads(self, space_id: str, sparql_query: str) -> List[tuple]:
        """Query RDF quads from Fuseki dataset (primary read path)."""
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        logger.debug(f"Executing SPARQL query on space {space_id}")
        
        try:
            # Query Fuseki dataset directly for optimal performance
            results = await self.fuseki_manager.query_dataset(space_id, sparql_query)
            
            logger.debug(f"SPARQL query returned {len(results)} results for space {space_id}")
            return results
            
        except Exception as e:
            logger.error(f"Error querying space {space_id}: {e}")
            return []
    
    async def count_quads(self, space_id: str) -> int:
        """Count RDF quads in a space using Fuseki dataset."""
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        try:
            # Get dataset info from Fuseki
            dataset_info = await self.fuseki_manager.get_dataset_info(space_id)
            
            if dataset_info:
                return dataset_info.get('triple_count', 0)
            else:
                return 0
                
        except Exception as e:
            logger.error(f"Error counting quads in space {space_id}: {e}")
            return 0
    
    # Metadata operations (PostgreSQL admin tables)
    
    async def create_space_metadata(self, space_id: str, metadata: Dict[str, Any]) -> bool:
        """Create space metadata in PostgreSQL admin tables."""
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        try:
            # Insert space metadata into PostgreSQL
            query = """
                INSERT INTO space (space_id, space_name, space_description, tenant, update_time)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (space_id) DO UPDATE SET
                    space_name = EXCLUDED.space_name,
                    space_description = EXCLUDED.space_description,
                    tenant = EXCLUDED.tenant,
                    update_time = NOW()
            """
            
            params = [
                space_id,
                metadata.get('space_name', space_id),
                metadata.get('space_description', ''),
                metadata.get('tenant', 'default')
            ]
            
            await self.postgresql_impl.execute_query(query, params)
            logger.info(f"Space metadata created for: {space_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating space metadata for {space_id}: {e}")
            return False
    
    async def delete_space_metadata(self, space_id: str) -> bool:
        """Delete space metadata from PostgreSQL admin tables."""
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        try:
            # Delete space metadata from PostgreSQL
            query = "DELETE FROM space WHERE space_id = $1"
            params = [space_id]
            
            await self.postgresql_impl.execute_query(query, params)
            logger.info(f"Space metadata deleted for: {space_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting space metadata for {space_id}: {e}")
            return False
    
    async def get_space_metadata(self, space_id: str) -> Optional[Dict[str, Any]]:
        """Get space metadata from PostgreSQL admin tables."""
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        try:
            # Query PostgreSQL space table
            query = "SELECT * FROM space WHERE space_id = $1"
            params = {'space_id': space_id}
            
            results = await self.postgresql_impl.execute_query(query, params)
            
            if results:
                return results[0]
            else:
                return None
                
        except Exception as e:
            logger.error(f"Error getting space metadata for {space_id}: {e}")
            return None
    
    async def list_spaces(self) -> List[Dict[str, Any]]:
        """List all spaces from PostgreSQL admin tables."""
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        try:
            # Query PostgreSQL space table
            query = "SELECT * FROM space ORDER BY space_id"
            
            results = await self.postgresql_impl.execute_query(query)
            return results
            
        except Exception as e:
            logger.error(f"Error listing spaces: {e}")
            return []
    
    # Utility and diagnostic operations
    
    async def get_space_info(self, space_id: str) -> Dict[str, Any]:
        """Get comprehensive information about a space."""
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        try:
            # Get metadata from PostgreSQL
            metadata = await self.get_space_metadata(space_id)
            
            # Get dataset info from Fuseki
            dataset_info = await self.fuseki_manager.get_dataset_info(space_id)
            
            # Get consistency check
            consistency = await self.dual_write_coordinator.verify_consistency(space_id)
            
            info = {
                'space_id': space_id,
                'metadata': metadata,
                'fuseki_info': dataset_info,
                'consistency_check': consistency,
                'backend_type': 'fuseki_postgresql'
            }
            
            # Get and log space statistics from PostgreSQL
            pg_impl = self.dual_write_coordinator.postgresql_impl
            space_stats = await pg_impl.get_space_stats(space_id)
            
            # Log space statistics
            logger.info(f"📊 SPACE STATISTICS for {space_id}:")
            logger.info(f"  Total quads: {space_stats.get('total_quad_count', 0)}")
            logger.info(f"  Number of graphs: {len(space_stats.get('graph_uris', []))}")
            
            for graph_uri in space_stats.get('graph_uris', []):
                graph_stats = space_stats.get('graphs', {}).get(graph_uri, {})
                logger.info(f"  Graph: {graph_uri}")
                logger.info(f"    - Quads: {graph_stats.get('quad_count', 0)}")
                logger.info(f"    - Unique subjects: {graph_stats.get('unique_subjects', 0)}")
                logger.info(f"    - Unique predicates: {graph_stats.get('unique_predicates', 0)}")
            
            info['space_stats'] = space_stats
            
            # Add quad logging if enabled in postgresql config
            logger.info(f"🔧 DEBUG: PostgreSQL config keys: {list(self.postgresql_config.keys())}")
            enable_quad_logging = self.postgresql_config.get('enable_quad_logging', False)
            logger.info(f"🔧 DEBUG: enable_quad_logging value: {enable_quad_logging}")
            if enable_quad_logging:
                logger.info(f"🔍 QUAD LOGGING ENABLED for space {space_id}")
                quad_info = await self._log_all_quads(space_id)
                info['quad_logging'] = quad_info
            else:
                logger.info(f"🔧 DEBUG: Quad logging not enabled in config")
            
            return info
            
        except Exception as e:
            logger.error(f"Error getting space info for {space_id}: {e}")
            return {
                'space_id': space_id,
                'error': str(e),
                'backend_type': 'fuseki_postgresql'
            }
    
    async def _log_all_quads(self, space_id: str, page_size: int = 100) -> Dict[str, Any]:
        """
        Log all quads in a space for debugging and validation using pagination.
        
        Args:
            space_id: Space identifier
            page_size: Number of quads to fetch per page (default 100)
        
        Returns dict with quad counts and grouped quads by graph.
        """
        try:
            # Get PostgreSQL implementation from dual write coordinator
            pg_impl = self.dual_write_coordinator.postgresql_impl
            
            # Get total quad count from PostgreSQL
            total_count = await pg_impl.count_quads(space_id)
            
            if total_count == 0:
                logger.info(f"No quads found in PostgreSQL for space {space_id}")
                return {'total_quad_count': 0, 'graph_count': 0, 'quads_by_graph': {}}
            
            logger.info(f"📊 Starting quad logging for space {space_id} - Total quads: {total_count}")
            
            # Process quads in pages from PostgreSQL
            quads_by_graph = {}
            total_quads = 0
            offset = 0
            page_num = 1
            
            while offset < total_count:
                # Get page of quads from PostgreSQL using new method
                result = await pg_impl.get_data_quads(space_id, limit=page_size, offset=offset)
                
                if result['status'] != 'success' or not result['quads']:
                    if result['status'] == 'error':
                        logger.error(f"Error getting quads: {result.get('error')}")
                    break
                
                quads = result['quads']
                logger.info(f"📄 Processing page {page_num} (offset {result['start_index']}, size {len(quads)})")
                
                # Process this page of quads (each quad is a tuple: (graph, subject, predicate, object))
                for quad in quads:
                    graph, subject, predicate, obj = quad
                    
                    if graph not in quads_by_graph:
                        quads_by_graph[graph] = []
                    
                    quads_by_graph[graph].append({
                        'subject': subject,
                        'predicate': predicate,
                        'object': obj
                    })
                    total_quads += 1
                    
                    # Log each quad on a separate line with truncated URIs
                    g_short = graph.split('/')[-1] if '/' in graph else graph
                    s_short = subject.split('/')[-1] if '/' in subject else subject
                    p_short = predicate.split('#')[-1] if '#' in predicate else predicate.split('/')[-1] if '/' in predicate else predicate
                    o_short = obj.split('/')[-1] if '/' in obj else obj[:80]
                    
                    logger.info(f"QUAD: G=<{g_short}> S=<{s_short}> P=<{p_short}> O=<{o_short}>")
                
                offset += page_size
                page_num += 1
            
            # Log summary by graph
            logger.info(f"📊 QUAD SUMMARY for space {space_id}:")
            logger.info(f"  Total quads: {total_quads}")
            for graph, quads in quads_by_graph.items():
                logger.info(f"  Graph <{graph}>: {len(quads)} quads")
            
            return {
                'total_quad_count': total_quads,
                'graph_count': len(quads_by_graph),
                'quads_by_graph': {g: len(q) for g, q in quads_by_graph.items()}
            }
            
        except Exception as e:
            logger.error(f"Error logging quads for space {space_id}: {e}", exc_info=True)
            return {'error': str(e), 'quad_count': 0}
    
    async def verify_space_consistency(self, space_id: str) -> Dict[str, Any]:
        """Verify consistency between Fuseki and PostgreSQL for a space."""
        if not self.connected:
            raise RuntimeError("Backend not connected")
        
        return await self.dual_write_coordinator.verify_consistency(space_id)
    
    def get_signal_manager(self):
        """Get the signal manager instance."""
        return self.signal_manager
    
    def get_connection_info(self) -> Dict[str, Any]:
        """Get connection information for both systems."""
        return {
            'backend_type': 'fuseki_postgresql',
            'connected': self.connected,
            'fuseki': {
                'server_url': self.fuseki_config.get('server_url'),
                'username': self.fuseki_config.get('username')
            },
            'postgresql': self.postgresql_impl.get_connection_info() if self.postgresql_impl else None
        }
    
    async def execute_sparql_query(self, space_id: str, query: str) -> Dict[str, Any]:
        """Execute SPARQL query - delegate to existing db_ops implementation."""
        try:
            bindings = await self.db_ops.execute_sparql_query(space_id, query)
            return {
                'success': True,
                'results': {
                    'bindings': bindings
                }
            }
        except Exception as e:
            logger.error(f"Error executing SPARQL query: {e}")
            return {
                'success': False,
                'error': str(e),
                'results': {'bindings': []}
            }
