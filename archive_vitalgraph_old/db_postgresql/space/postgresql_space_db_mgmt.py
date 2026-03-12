import logging
import time
from typing import Dict, List, Optional, Any
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from ..postgresql_log_utils import PostgreSQLLogUtils
from .postgresql_space_schema import PostgreSQLSpaceSchema


class PostgreSQLSpaceDbMgmt:
    """
    PostgreSQL Space Database Management.
    
    Handles table creation, deletion, and index management for RDF spaces.
    This class is responsible for all database schema operations but does not
    handle data queries or modifications.
    """
    
    def __init__(self, space_impl):
        """
        Initialize database management with space implementation reference.
        
        Args:
            space_impl: PostgreSQLSpaceImpl instance to access core, schema, and configuration
        """
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.space_impl = space_impl
        self.utils = PostgreSQLLogUtils()
    
    async def create_space_tables(self, space_id: str) -> bool:
        """
        Create UUID-based RDF tables optimized for deterministic batch loading.
        
        This creates tables that use UUIDs as primary keys 
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if tables created successfully, False otherwise
        """
        start_time = time.time()
        self.logger.info(f"🔨 Creating space tables for '{space_id}'...")
        
        try:
            # Get table creation SQL from the space implementation
            table_sqls = self.space_impl._get_create_table_sql(space_id)
            
            # Use async context manager with pooled connection
            async with self.space_impl.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Create tables in dependency order
                    table_order = ['datatype', 'term', 'rdf_quad', 'namespace', 'graph']
                    
                    for table_base in table_order:
                        if table_base in table_sqls:
                            table_sql = table_sqls[table_base]
                            self.logger.debug(f"Creating table {table_base}: {table_sql[:100]}...")
                            cursor.execute(table_sql)
                            self.logger.info(f"✅ Created table {table_base}")
                    
                    # Commit the transaction
                    conn.commit()
                    
                    execution_time = time.time() - start_time
                    self.logger.info(f"✅ Successfully created space tables for '{space_id}' in {execution_time:.3f}s")
                    return True
                    # Connection automatically returned to pool when context exits
                
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.error(f"❌ Failed to create space tables for '{space_id}' after {execution_time:.3f}s: {e}")
            return False
    
    async def drop_indexes_for_bulk_load(self, space_id: str) -> bool:
        """
        Drop all indexes before bulk loading for maximum performance.
        Keeps only primary keys and constraints.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if indexes dropped successfully, False otherwise
        """
        start_time = time.time()
        self.logger.info(f"🗑️ Dropping indexes for bulk load in space '{space_id}'...")
        
        try:
            # Get drop index SQL from the space implementation
            schema = self.space_impl._get_schema(space_id)
            drop_statements = schema.get_drop_indexes_sql()
            
            # Use async context manager with pooled connection
            async with self.space_impl.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    dropped_count = 0
                    for drop_sql in drop_statements:
                        try:
                            self.logger.debug(f"Executing: {drop_sql}")
                            cursor.execute(drop_sql)
                            dropped_count += 1
                        except Exception as e:
                            self.logger.debug(f"Index drop failed (may not exist): {e}")
                    
                    conn.commit()
                    self.logger.info(f"Dropped {dropped_count} indexes for bulk loading")
                    # Connection automatically returned to pool when context exits
            
            execution_time = time.time() - start_time
            self.logger.info(f"✅ Successfully dropped indexes for '{space_id}' in {execution_time:.3f}s")
            return True
            
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.error(f"❌ Failed to drop indexes for '{space_id}' after {execution_time:.3f}s: {e}")
            return False
    
    async def recreate_indexes_after_bulk_load(self, space_id: str, concurrent: bool = True) -> bool:
        """
        Recreate all indexes after bulk loading is complete.
        
        Args:
            space_id: Space identifier
            concurrent: If True, use CONCURRENTLY to avoid blocking queries
            
        Returns:
            bool: True if indexes recreated successfully, False otherwise
        """
        start_time = time.time()
        self.logger.info(f"🔨 Recreating indexes after bulk load in space '{space_id}'...")
        
        try:
            # Get recreate index SQL from the space implementation
            schema = self.space_impl._get_schema(space_id)
            create_statements = schema.get_recreate_indexes_sql(concurrent=concurrent)
            
            # Use async context manager with pooled connection
            async with self.space_impl.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    created_count = 0
                    for create_sql in create_statements:
                        try:
                            self.logger.debug(f"Executing: {create_sql}")
                            cursor.execute(create_sql)
                            created_count += 1
                            
                            # Commit each index if using CONCURRENTLY
                            if concurrent:
                                conn.commit()
                                
                        except Exception as e:
                            self.logger.warning(f"Failed to create index: {e}")
                            if concurrent:
                                conn.rollback()
                    
                    # Final commit if not using CONCURRENTLY
                    if not concurrent:
                        conn.commit()
                    
                    # Optional: Cluster tables for better performance (only for large datasets)
                    if created_count > 0:
                        try:
                            self.logger.info("Disabled: Clustering tables for optimal performance...")
                            # self.logger.info("Clustering tables for optimal performance...")
                            # cluster_statements = schema.get_cluster_sql()
                            # for cluster_sql in cluster_statements:
                            #     cursor.execute(cluster_sql)
                            # conn.commit()
                            # self.logger.info("Table clustering completed")
                        except Exception as e:
                            self.logger.warning(f"Table clustering failed (non-critical): {e}")
                    
                    self.logger.info(f"Successfully recreated {created_count} indexes after bulk loading")
                    # Connection automatically returned to pool when context exits
            
            execution_time = time.time() - start_time
            self.logger.info(f"✅ Successfully recreated indexes for '{space_id}' in {execution_time:.3f}s")
            return True
            
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.error(f"❌ Failed to recreate indexes for '{space_id}' after {execution_time:.3f}s: {e}")
            return False
    
    async def delete_space_tables(self, space_id: str) -> bool:
        """
        Delete all RDF tables for a specific space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if tables deleted successfully, False otherwise
        """
        start_time = time.time()
        self.logger.info(f"🗑️ Deleting space tables for '{space_id}'...")
        
        try:
            # Get table names from the space implementation
            table_names = self.space_impl._get_table_names(space_id)
            
            # Use async context manager with pooled connection
            async with self.space_impl.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Drop tables in reverse dependency order to avoid foreign key issues
                    table_order = ['graph', 'namespace', 'rdf_quad', 'term', 'datatype']
                    
                    for table_base in table_order:
                        if table_base in table_names:
                            table_name = table_names[table_base]
                            try:
                                cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
                                self.logger.info(f"✅ Dropped table {table_name}")
                            except Exception as e:
                                self.logger.warning(f"⚠️ Failed to drop table {table_name}: {e}")
                    
                    # Commit the transaction
                    conn.commit()
                    
                    execution_time = time.time() - start_time
                    self.logger.info(f"✅ Successfully deleted space tables for '{space_id}' in {execution_time:.3f}s")
                    return True
                    # Connection automatically returned to pool when context exits
                
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.error(f"❌ Failed to delete space tables for '{space_id}' after {execution_time:.3f}s: {e}")
            return False
    

