import logging
from typing import Optional, List, Dict, Set
from datetime import datetime

# RDFLib imports for graph handling
from rdflib import URIRef


class PostgreSQLSpaceGraphs:
    """
    PostgreSQL graph management for RDF spaces.
    
    Handles all graph-related operations including creating, retrieving, updating, and deleting graphs,
    as well as managing graph metadata like triple counts.
    """
    
    def __init__(self, space_impl):
        """
        Initialize the graphs manager with a reference to the space implementation.
        
        Args:
            space_impl: PostgreSQLSpaceImpl instance for accessing other space methods
        """
        self.space_impl = space_impl
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def create_graph(self, space_id: str, graph_uri: str, graph_name: Optional[str] = None) -> bool:
        """
        Create a new graph in the graph table.
        
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
            
            table_names = self.space_impl._get_table_names(space_id)
            
            async with self.space_impl.get_db_connection() as conn:
                cursor = conn.cursor()
                sql = f"""
                    INSERT INTO {table_names['graph']} (graph_uri, graph_name, triple_count, created_time, updated_time)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (graph_uri) DO NOTHING
                """
                
                now = datetime.now()
                cursor.execute(sql, (graph_uri, graph_name, 0, now, now))
                
            self.logger.debug(f"Created graph: {graph_uri} in space {space_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating graph {graph_uri} in space {space_id}: {e}")
            return False
    
    async def get_graph(self, space_id: str, graph_uri: str) -> Optional[Dict]:
        """
        Get graph information by URI.
        
        Args:
            space_id: Space identifier
            graph_uri: URI of the graph to retrieve
            
        Returns:
            Dict with graph info if found, None otherwise
        """
        try:
            table_names = self.space_impl._get_table_names(space_id)
            
            async with self.space_impl.get_db_connection() as conn:
                cursor = conn.cursor()
                sql = f"""
                    SELECT graph_id, graph_uri, graph_name, created_time, updated_time, triple_count
                    FROM {table_names['graph']}
                    WHERE graph_uri = %s
                """
                
                cursor.execute(sql, (graph_uri,))
                row = cursor.fetchone()
                
                if row:
                    return {
                        'graph_id': row[0],
                        'graph_uri': row[1],
                        'graph_name': row[2],
                        'created_time': row[3],
                        'updated_time': row[4],
                        'triple_count': row[5]
                    }
                    
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting graph {graph_uri} in space {space_id}: {e}")
            return None
    
    async def list_graphs(self, space_id: str) -> List[Dict]:
        """
        Get all graphs in a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            List of graph dictionaries
        """
        try:
            table_names = self.space_impl._get_table_names(space_id)
            
            async with self.space_impl.get_db_connection() as conn:
                cursor = conn.cursor()
                sql = f"""
                    SELECT graph_id, graph_uri, graph_name, created_time, updated_time, triple_count
                    FROM {table_names['graph']}
                    ORDER BY created_time DESC
                """
                
                cursor.execute(sql)
                rows = cursor.fetchall()
                
                return [
                    {
                        'graph_id': row[0],
                        'graph_uri': row[1],
                        'graph_name': row[2],
                        'created_time': row[3],
                        'updated_time': row[4],
                        'triple_count': row[5]
                    }
                    for row in rows
                ]
                    
        except Exception as e:
            self.logger.error(f"Error listing graphs in space {space_id}: {e}")
            return []
    
    async def update_graph_triple_count(self, space_id: str, graph_uri: str, count_delta: int = 0, absolute_count: Optional[int] = None) -> bool:
        """
        Update the triple count for a graph.
        
        Args:
            space_id: Space identifier
            graph_uri: URI of the graph to update
            count_delta: Change in triple count (ignored if absolute_count is provided)
            absolute_count: Absolute triple count to set (overrides count_delta)
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            table_names = self.space_impl._get_table_names(space_id)
            
            async with self.space_impl.get_db_connection() as conn:
                cursor = conn.cursor()
                if absolute_count is not None:
                    # Set absolute count
                    sql = f"""
                        UPDATE {table_names['graph']}
                        SET triple_count = %s, updated_time = %s
                        WHERE graph_uri = %s
                    """
                    now = datetime.now()
                    cursor.execute(sql, (absolute_count, now, graph_uri))
                else:
                    # Update by delta
                    sql = f"""
                        UPDATE {table_names['graph']}
                        SET triple_count = triple_count + %s, updated_time = %s
                        WHERE graph_uri = %s
                    """
                    now = datetime.now()
                    cursor.execute(sql, (count_delta, now, graph_uri))
                    return cursor.rowcount > 0
                    
        except Exception as e:
            self.logger.error(f"Error updating triple count for graph {graph_uri} in space {space_id}: {e}")
            return False
    
    async def clear_graph(self, space_id: str, graph_uri: str) -> bool:
        """
        Clear all triples from a graph following SPARQL CLEAR GRAPH semantics.
        
        SPARQL Semantics:
        - Removes all triples (quads) from the specified graph
        - Keeps the graph in the registry (graph table entry remains)
        - Graph still exists but is empty
        
        Args:
            space_id: Space identifier
            graph_uri: URI of the graph to clear
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            table_names = self.space_impl._get_table_names(space_id)
            
            async with self.space_impl.get_db_connection() as conn:
                cursor = conn.cursor()
                # Remove all triples from the graph but keep the graph entry
                sql = f"""
                    DELETE FROM {table_names['rdf_quad']}
                    WHERE context_uuid = (
                        SELECT term_uuid FROM {table_names['term']}
                        WHERE term_text = %s
                    )
                """
                
                cursor.execute(sql, (graph_uri,))
                deleted_count = cursor.rowcount
                
                # Update graph triple count to 0 in the same connection
                update_sql = f"""
                    UPDATE {table_names['graph']}
                    SET triple_count = 0, updated_time = %s
                    WHERE graph_uri = %s
                """
                now = datetime.now()
                cursor.execute(update_sql, (now, graph_uri))
                        
            self.logger.info(f"Cleared {deleted_count} triples from graph {graph_uri} in space {space_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error clearing graph {graph_uri} in space {space_id}: {e}")
            return False
    
    async def drop_graph(self, space_id: str, graph_uri: str) -> bool:
        """
        Drop a graph completely following SPARQL DROP GRAPH semantics.
        
        SPARQL Semantics:
        - Removes all triples (quads) from the specified graph
        - Removes the graph from the registry (deletes graph table entry)
        - Graph no longer exists in the system
        
        Args:
            space_id: Space identifier
            graph_uri: URI of the graph to drop
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            table_names = self.space_impl._get_table_names(space_id)
            
            async with self.space_impl.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # First, remove all triples from the graph
                delete_triples_sql = f"""
                    DELETE FROM {table_names['rdf_quad']}
                    WHERE context_uuid = (
                        SELECT term_uuid FROM {table_names['term']}
                        WHERE term_text = %s
                    )
                """
                cursor.execute(delete_triples_sql, (graph_uri,))
                deleted_count = cursor.rowcount
                
                # Then remove the graph entry itself
                delete_graph_sql = f"""
                    DELETE FROM {table_names['graph']}
                    WHERE graph_uri = %s
                """
                cursor.execute(delete_graph_sql, (graph_uri,))
                    
            self.logger.info(f"Dropped graph {graph_uri} from space {space_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error dropping graph {graph_uri} in space {space_id}: {e}")
            return False
    
    async def ensure_graph_exists(self, space_id: str, graph_uri: str) -> bool:
        """
        Ensure a graph exists, creating it if necessary.
        
        Args:
            space_id: Space identifier
            graph_uri: URI of the graph to ensure exists
            
        Returns:
            bool: True if graph exists or was created, False on error
        """
        # Check if graph already exists
        existing_graph = await self.get_graph(space_id, graph_uri)
        if existing_graph:
            return True
        
        # Create the graph
        return await self.create_graph(space_id, graph_uri)
    
    async def batch_ensure_graphs_exist(self, space_id: str, graph_uris: Set[str]) -> bool:
        """
        Ensure multiple graphs exist, creating them if necessary (batch operation).
        
        Args:
            space_id: Space identifier
            graph_uris: Set of graph URIs to ensure exist
            
        Returns:
            bool: True if all graphs exist or were created, False on error
        """
        if not graph_uris:
            return True
        
        try:
            table_names = self.space_impl._get_table_names(space_id)
            
            # Prepare batch insert data
            insert_data = []
            now = datetime.now()
            
            for graph_uri in graph_uris:
                # Extract a simple name from the URI for the graph_name field
                graph_name = graph_uri.split('/')[-1] if '/' in graph_uri else graph_uri
                insert_data.append((graph_uri, graph_name, 0, now, now))
            
            async with self.space_impl.get_db_connection() as conn:
                cursor = conn.cursor()
                # Use batch insert with ON CONFLICT DO NOTHING
                placeholders = ','.join(['(%s, %s, %s, %s, %s)'] * len(insert_data))
                sql = f"""
                    INSERT INTO {table_names['graph']} (graph_uri, graph_name, triple_count, created_time, updated_time)
                    VALUES {placeholders}
                    ON CONFLICT (graph_uri) DO NOTHING
                """
                
                # Flatten the insert data for the query
                flattened_data = [item for sublist in insert_data for item in sublist]
                cursor.execute(sql, flattened_data)
                    
            self.logger.debug(f"Batch ensured {len(graph_uris)} graphs exist in space {space_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error batch ensuring graphs exist in space {space_id}: {e}")
            return False
