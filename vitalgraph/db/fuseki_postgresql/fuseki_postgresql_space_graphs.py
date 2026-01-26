"""
Graph management operations for Fuseki+PostgreSQL hybrid backend.
Provides PostgreSQL graph table operations with dual-write coordination.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class FusekiPostgreSQLSpaceGraphs:
    """
    Graph management for Fuseki+PostgreSQL hybrid backend.
    
    Handles PostgreSQL graph table operations:
    - create_graph: Insert record into graph table
    - drop_graph: Remove record from graph table + SPARQL DROP
    - clear_graph: SPARQL CLEAR operation (keeps graph record)
    - list_graphs: Query graph table records
    - get_graph: Get specific graph record
    """
    
    def __init__(self, space_impl):
        """
        Initialize graph management.
        
        Args:
            space_impl: FusekiPostgreSQLSpaceImpl instance
        """
        self.space_impl = space_impl
        self.logger = logging.getLogger(f"{__name__}.FusekiPostgreSQLSpaceGraphs")
    
    async def create_graph(self, space_id: str, graph_uri: str, graph_name: Optional[str] = None) -> bool:
        """
        Create a new graph record in PostgreSQL graph table.
        
        Args:
            space_id: Space identifier
            graph_uri: URI of the graph to create
            graph_name: Optional human-readable name for the graph
            
        Returns:
            bool: True if graph was created or already exists, False on error
        """
        try:
            # Extract a simple name from the URI if not provided
            if graph_name is None:
                graph_name = graph_uri.split('/')[-1] if '/' in graph_uri else graph_uri
            
            # Use PostgreSQL implementation to insert graph record in global graph table
            query = """
                INSERT INTO graph (space_id, graph_uri, graph_name, created_time)
                VALUES ($1, $2, $3, $4)
            """
            
            now = datetime.now()
            params = [space_id, graph_uri, graph_name, now]
            
            await self.space_impl.postgresql_impl.execute_query(query, params)
            
            self.logger.debug(f"Created graph record: {graph_uri} in space {space_id}")
            
            # Send notification for graph creation
            try:
                signal_manager = self.space_impl.get_signal_manager()
                if signal_manager:
                    # Import signal constants
                    from vitalgraph.signal.signal_manager import SIGNAL_TYPE_CREATED
                    
                    # Notify graph changes (async task to avoid blocking)
                    import asyncio
                    asyncio.create_task(signal_manager.notify_graphs_changed(SIGNAL_TYPE_CREATED))
                    asyncio.create_task(signal_manager.notify_graph_changed(graph_uri, SIGNAL_TYPE_CREATED))
                    self.logger.debug(f"Sent notifications for graph creation: {graph_uri}")
                else:
                    self.logger.warning("No SignalManager available for notifications")
            except Exception as e:
                # Log but don't fail the operation if notification fails
                self.logger.warning(f"Failed to send graph creation notifications: {e}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating graph {graph_uri} in space {space_id}: {e}")
            return False
    
    async def drop_graph(self, space_id: str, graph_uri: str) -> bool:
        """
        Drop a graph - remove from PostgreSQL table and execute SPARQL DROP.
        
        Args:
            space_id: Space identifier
            graph_uri: URI of the graph to drop
            
        Returns:
            bool: True if graph was dropped successfully, False on error
        """
        try:
            # First execute SPARQL DROP to remove triples
            sparql_drop = f"DROP SILENT GRAPH <{graph_uri}>"
            sparql_success = await self.space_impl.execute_sparql_update(space_id, sparql_drop)
            
            if not sparql_success:
                self.logger.warning(f"SPARQL DROP failed for graph {graph_uri}, continuing with table cleanup")
            
            # Remove graph record from global graph table
            query = "DELETE FROM graph WHERE space_id = $1 AND graph_uri = $2"
            params = [space_id, graph_uri]
            
            await self.space_impl.postgresql_impl.execute_query(query, params)
            
            self.logger.debug(f"Dropped graph: {graph_uri} from space {space_id}")
            
            # Send notification for graph deletion
            try:
                signal_manager = self.space_impl.get_signal_manager()
                if signal_manager:
                    # Import signal constants
                    from vitalgraph.signal.signal_manager import SIGNAL_TYPE_DELETED
                    
                    # Notify graph changes (async task to avoid blocking)
                    import asyncio
                    asyncio.create_task(signal_manager.notify_graphs_changed(SIGNAL_TYPE_DELETED))
                    asyncio.create_task(signal_manager.notify_graph_changed(graph_uri, SIGNAL_TYPE_DELETED))
                    self.logger.debug(f"Sent notifications for graph deletion: {graph_uri}")
                else:
                    self.logger.warning("No SignalManager available for notifications")
            except Exception as e:
                # Log but don't fail the operation if notification fails
                self.logger.warning(f"Failed to send graph deletion notifications: {e}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error dropping graph {graph_uri} from space {space_id}: {e}")
            return False
    
    async def clear_graph(self, space_id: str, graph_uri: str) -> bool:
        """
        Clear a graph - execute SPARQL CLEAR but keep graph record.
        
        Args:
            space_id: Space identifier
            graph_uri: URI of the graph to clear
            
        Returns:
            bool: True if graph was cleared successfully, False on error
        """
        try:
            # Execute SPARQL CLEAR to remove triples but keep graph
            sparql_clear = f"CLEAR SILENT GRAPH <{graph_uri}>"
            success = await self.space_impl.execute_sparql_update(space_id, sparql_clear)
            
            if success:
                # Graph record exists, no need to update since schema doesn't have triple_count
                # The SPARQL CLEAR operation already cleared the triples
                self.logger.debug(f"Cleared graph: {graph_uri} in space {space_id}")
                
                # Send notification for graph update
                try:
                    signal_manager = self.space_impl.get_signal_manager()
                    if signal_manager:
                        # Import signal constants
                        from vitalgraph.signal.signal_manager import SIGNAL_TYPE_UPDATED
                        
                        # Notify graph changes (async task to avoid blocking)
                        import asyncio
                        asyncio.create_task(signal_manager.notify_graphs_changed(SIGNAL_TYPE_UPDATED))
                        asyncio.create_task(signal_manager.notify_graph_changed(graph_uri, SIGNAL_TYPE_UPDATED))
                        self.logger.debug(f"Sent notifications for graph clear: {graph_uri}")
                    else:
                        self.logger.warning("No SignalManager available for notifications")
                except Exception as e:
                    # Log but don't fail the operation if notification fails
                    self.logger.warning(f"Failed to send graph clear notifications: {e}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error clearing graph {graph_uri} in space {space_id}: {e}")
            return False
    
    async def list_graphs(self, space_id: str) -> List[Dict[str, Any]]:
        """
        List all graphs in the space from PostgreSQL graph table.
        
        Args:
            space_id: Space identifier
            
        Returns:
            List[tuple]: List of graph records
        """
        try:
            query = """
                SELECT graph_uri, graph_name, created_time
                FROM graph
                WHERE space_id = $1
                ORDER BY created_time DESC
            """
            
            results = await self.space_impl.postgresql_impl.execute_query(query, [space_id])
            
            # Convert to list of dictionaries
            graphs = []
            for result in results:
                graph_data = {
                    'graph_uri': result.get('graph_uri'),
                    'graph_name': result.get('graph_name'),
                    'triple_count': 0,  # Not stored in table, default to 0
                    'created_time': result.get('created_time'),
                    'updated_time': None  # Not stored in table
                }
                graphs.append(graph_data)
            
            self.logger.debug(f"Listed {len(graphs)} graphs in space {space_id}")
            return graphs
            
        except Exception as e:
            self.logger.error(f"Error listing graphs in space {space_id}: {e}")
            return []
    
    async def get_graph(self, space_id: str, graph_uri: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific graph from PostgreSQL graph table.
        
        Args:
            space_id: Space identifier
            graph_uri: URI of the graph to get
            
        Returns:
            Optional[Dict]: Graph record or None if not found
        """
        try:
            query = """
                SELECT graph_uri, graph_name, created_time
                FROM graph
                WHERE space_id = $1 AND graph_uri = $2
            """
            params = [space_id, graph_uri]
            
            results = await self.space_impl.postgresql_impl.execute_query(query, params)
            
            if results:
                result = results[0]
                graph_data = {
                    'graph_uri': result.get('graph_uri'),
                    'graph_name': result.get('graph_name'),
                    'triple_count': 0,  # Not stored in table, default to 0
                    'created_time': result.get('created_time'),
                    'updated_time': None  # Not stored in table
                }
                
                self.logger.debug(f"Retrieved graph info: {graph_uri} in space {space_id}")
                return graph_data
            else:
                self.logger.debug(f"Graph not found: {graph_uri} in space {space_id}")
                return None
            
        except Exception as e:
            self.logger.error(f"Error getting graph {graph_uri} in space {space_id}: {e}")
            return None
