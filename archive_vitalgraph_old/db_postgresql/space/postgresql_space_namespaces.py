from typing import Optional, List, Dict, Any
import traceback
import psycopg
from vitalgraph.db.postgresql.postgresql_log_utils import PostgreSQLLogUtils
from vitalgraph.db.postgresql.space.postgresql_space_utils import PostgreSQLSpaceUtils


class PostgreSQLSpaceNamespaces:
    """
    Handles namespace-specific operations for PostgreSQL spaces.
    
    This class manages namespace prefix mappings within RDF spaces,
    providing functionality to add, retrieve, and list namespace definitions.
    """
    
    def __init__(self, space_impl):
        """
        Initialize the namespace handler with a reference to the space implementation.
        
        Args:
            space_impl: The PostgreSQLSpaceImpl instance for database operations
        """
        self.space_impl = space_impl
        self.logger = space_impl.logger
    
    async def add_namespace(self, space_id: str, prefix: str, namespace_uri: str) -> Optional[int]:
        """
        Add a namespace prefix mapping to a specific space.
        
        Args:
            space_id: Space identifier
            prefix: Namespace prefix (e.g., 'foaf', 'rdf')
            namespace_uri: Full namespace URI (e.g., 'http://xmlns.com/foaf/0.1/')
            
        Returns:
            int: Namespace ID if successful, None otherwise
        """
        try:
            PostgreSQLSpaceUtils.validate_space_id(space_id)
            
            # Get table names using current structure
            table_names = self.space_impl._get_table_names(space_id)
            namespace_table_name = table_names['namespace']
            
            self.logger.debug(f"Adding namespace '{prefix}' -> '{namespace_uri}' to space '{space_id}'")
            
            # Use async context manager with pooled connection
            async with self.space_impl.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Check if prefix already exists
                cursor.execute(
                    f"SELECT namespace_id, namespace_uri FROM {namespace_table_name} WHERE prefix = %s",
                    (prefix,)
                )
                result = cursor.fetchone()
                
                if result:
                    namespace_id, existing_uri = result
                    # Update existing namespace URI if different
                    if existing_uri != namespace_uri:
                        cursor.execute(
                            f"UPDATE {namespace_table_name} SET namespace_uri = %s WHERE namespace_id = %s",
                            (namespace_uri, namespace_id)
                        )
                        conn.commit()
                        self.logger.info(f"Updated namespace '{prefix}' in space '{space_id}' to URI: {namespace_uri}")
                    else:
                        self.logger.debug(f"Namespace '{prefix}' already exists in space '{space_id}' with same URI")
                    return namespace_id
                
                # Insert new namespace
                cursor.execute(
                    f"INSERT INTO {namespace_table_name} (prefix, namespace_uri) VALUES (%s, %s) RETURNING namespace_id",
                    (prefix, namespace_uri)
                )
                result = cursor.fetchone()
                namespace_id = result[0] if result else None
                
                conn.commit()
                
                self.logger.info(f"Added namespace '{prefix}' -> '{namespace_uri}' to space '{space_id}' with ID: {namespace_id}")
                return namespace_id
                # Connection automatically returned to pool when context exits
                
        except Exception as e:
            self.logger.error(f"Error adding namespace to space '{space_id}': {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    async def get_namespace_uri(self, space_id: str, prefix: str) -> Optional[str]:
        """
        Get namespace URI for a given prefix in a specific space.
        
        Args:
            space_id: Space identifier
            prefix: Namespace prefix to look up
            
        Returns:
            str: Namespace URI if found, None otherwise
        """
        try:
            PostgreSQLSpaceUtils.validate_space_id(space_id)
            
            # Get table names using current structure
            table_names = self.space_impl._get_table_names(space_id)
            namespace_table_name = table_names['namespace']
            
            self.logger.debug(f"Looking up namespace URI for prefix '{prefix}' in space '{space_id}'")
            
            # Use async context manager with pooled connection
            async with self.space_impl.get_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute(
                    f"SELECT namespace_uri FROM {namespace_table_name} WHERE prefix = %s",
                    (prefix,)
                )
                result = cursor.fetchone()
                
                if result:
                    namespace_uri = result[0]
                    self.logger.debug(f"Found namespace URI for '{prefix}' in space '{space_id}': {namespace_uri}")
                    return namespace_uri
                else:
                    self.logger.debug(f"No namespace found for prefix '{prefix}' in space '{space_id}'")
                    return None
                # Connection automatically returned to pool when context exits
                    
        except Exception as e:
            self.logger.error(f"Error getting namespace URI from space '{space_id}': {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    async def list_namespaces(self, space_id: str) -> List[Dict[str, Any]]:
        """
        Get all namespace prefix mappings for a specific space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            list: List of namespace dictionaries with id, prefix, namespace_uri, created_time
        """
        try:
            PostgreSQLSpaceUtils.validate_space_id(space_id)
            
            # Get table names using current structure
            table_names = self.space_impl._get_table_names(space_id)
            namespace_table_name = table_names['namespace']
            
            self.logger.debug(f"Listing all namespaces for space '{space_id}'")
            
            # Use async context manager with dict pool for query result compatibility
            async with self.space_impl.core.get_dict_connection() as conn:
                # Connection already configured with dict_row factory
                cursor = conn.cursor()
                
                cursor.execute(
                    f"SELECT namespace_id, prefix, namespace_uri, created_time FROM {namespace_table_name} ORDER BY prefix"
                )
                results = cursor.fetchall()
                
                namespaces = []
                for row in results:
                    namespace_id, prefix, namespace_uri, created_time = row
                    namespaces.append({
                        'namespace_id': namespace_id,
                        'prefix': prefix,
                        'namespace_uri': namespace_uri,
                        'created_time': created_time.isoformat() if created_time else None
                    })
                
                self.logger.debug(f"Retrieved {len(namespaces)} namespaces from space '{space_id}'")
                return namespaces
                # Connection automatically returned to pool when context exits
                
        except Exception as e:
            self.logger.error(f"Error listing namespaces from space '{space_id}': {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return []
