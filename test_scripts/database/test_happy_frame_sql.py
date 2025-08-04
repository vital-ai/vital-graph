#!/opt/homebrew/anaconda3/envs/vital-graph/bin/python
"""
Test and benchmark happy frame SQL query performance in VitalGraph PostgreSQL database.

This script executes the happy_frame_query_4.sql file directly and provides timing
and pretty-printed results for the text search query.
"""

import logging
import os
import sys
import time
import yaml
from typing import List, Dict, Any, Optional
from datetime import datetime
import psycopg
import psycopg.sql

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class HappyFrameSQLTest:
    """Test and benchmark happy frame SQL query performance."""
    
    def __init__(self, config_path: str = None):
        """Initialize with direct database configuration."""
        # Default config path
        if config_path is None:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            config_path = os.path.join(project_root, 'vitalgraphdb_config', 'vitalgraphdb-config.yaml')
        
        self.config_path = config_path
        self.db_config = self._load_config()
        self.connection = None
        
        # Path to the SQL file
        self.sql_file_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'sql_scripts', 'happy_frame_query_4.sql'
        )
        
    def _load_config(self):
        """Load database configuration from YAML file."""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            # Extract database configuration
            db_config = config.get('database', {})
            return {
                'host': db_config.get('host', 'localhost'),
                'port': db_config.get('port', 5432),
                'database': db_config.get('database', 'vitalgraphdb'),
                'user': db_config.get('user', 'postgres'),
                'password': db_config.get('password', ''),
                'global_prefix': config.get('tables', {}).get('global_prefix', 'vitalgraph1')
            }
        except Exception as e:
            logger.error(f"Failed to load config from {self.config_path}: {e}")
            # Fallback to default configuration
            return {
                'host': 'localhost',
                'port': 5432,
                'database': 'vitalgraphdb',
                'user': 'postgres',
                'password': '',
                'global_prefix': 'vitalgraph1'
            }
        
    def connect(self):
        """Connect to the database using synchronous psycopg.connect."""
        try:
            # Build connection string
            conninfo = (
                f"host={self.db_config['host']} "
                f"port={self.db_config['port']} "
                f"dbname={self.db_config['database']} "
                f"user={self.db_config['user']} "
                f"password={self.db_config['password']}"
            )
            
            # Create synchronous connection
            self.connection = psycopg.connect(conninfo)
            self.connection.autocommit = True
            
            logger.info(f"Connected to PostgreSQL database: {self.db_config['database']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from the database."""
        if self.connection:
            self.connection.close()
            self.connection = None
            logger.info("Disconnected from database")
    
    def load_sql_query(self):
        """Load the SQL query from the file."""
        try:
            with open(self.sql_file_path, 'r') as f:
                sql_content = f.read()
            
            # Remove comments and empty lines for cleaner execution
            lines = sql_content.split('\n')
            sql_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith('--'):
                    sql_lines.append(line)
            
            sql_query = '\n'.join(sql_lines)
            logger.info(f"Loaded SQL query from: {self.sql_file_path}")
            return sql_query
            
        except Exception as e:
            logger.error(f"Failed to load SQL file {self.sql_file_path}: {e}")
            return None
    
    def execute_happy_frame_query(self):
        """Execute the happy frame query and return timing and results."""
        try:
            sql_query = self.load_sql_query()
            if not sql_query:
                return None
            
            logger.info("Executing happy frame query...")
            
            with self.connection.cursor() as cursor:
                # Execute query with timing
                start_time = time.time()
                cursor.execute(sql_query)
                results = cursor.fetchall()
                end_time = time.time()
                
                execution_time = end_time - start_time
                result_count = len(results)
                
                logger.info(f"Query executed in {execution_time:.3f} seconds")
                logger.info(f"Found {result_count} entities with 'happy' in descriptions")
                
                return {
                    'execution_time': execution_time,
                    'result_count': result_count,
                    'results': results
                }
                
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            return None
    
    def pretty_print_results(self, query_result):
        """Pretty print the query results."""
        if not query_result:
            logger.error("No query results to display")
            return
        
        results = query_result['results']
        execution_time = query_result['execution_time']
        result_count = query_result['result_count']
        
        print("\n" + "="*80)
        print("HAPPY FRAME SQL QUERY RESULTS")
        print("="*80)
        print(f"Execution Time: {execution_time:.3f} seconds")
        print(f"Result Count: {result_count}")
        print("="*80)
        
        if result_count == 0:
            print("No results found.")
            return
        
        # Print header
        print(f"{'#':<4} {'Entity URI':<60} {'Description'}")
        print("-" * 80)
        
        # Print results with numbering
        for i, (entity_uri, description) in enumerate(results, 1):
            # Truncate long descriptions for display
            display_desc = description[:50] + "..." if len(description) > 50 else description
            print(f"{i:<4} {entity_uri:<60} {display_desc}")
        
        print("="*80)
        
        # Show some statistics
        if result_count > 0:
            avg_uri_length = sum(len(row[0]) for row in results) / result_count
            avg_desc_length = sum(len(row[1]) for row in results) / result_count
            
            print(f"\nStatistics:")
            print(f"  Average URI length: {avg_uri_length:.1f} characters")
            print(f"  Average description length: {avg_desc_length:.1f} characters")
            
            # Show first few full descriptions as examples
            print(f"\nFirst 3 full descriptions:")
            for i, (entity_uri, description) in enumerate(results[:3], 1):
                print(f"  {i}. {description}")
        
        print("\n" + "="*80)

def main():
    """Main function to run the happy frame SQL test."""
    logger.info("Starting Happy Frame SQL Test")
    logger.info("="*50)
    
    test = HappyFrameSQLTest()
    
    try:
        # Connect to database
        if not test.connect():
            logger.error("Failed to connect to database")
            return 1
        
        # Execute the query
        logger.info("Executing happy frame query...")
        query_result = test.execute_happy_frame_query()
        
        if query_result:
            # Pretty print results
            test.pretty_print_results(query_result)
            
            # Performance summary
            execution_time = query_result['execution_time']
            result_count = query_result['result_count']
            
            logger.info(f"\n🎯 PERFORMANCE SUMMARY:")
            logger.info(f"   Execution Time: {execution_time:.3f}s")
            logger.info(f"   Results Found: {result_count}")
            logger.info(f"   Rate: {result_count/execution_time:.1f} results/second")
            
            if execution_time < 0.1:
                logger.info(f"   ⚡ EXCELLENT: Very fast query execution")
            elif execution_time < 1.0:
                logger.info(f"   ✅ GOOD: Fast query execution")
            elif execution_time < 5.0:
                logger.info(f"   ⚠️  MODERATE: Acceptable query execution")
            else:
                logger.info(f"   🐌 SLOW: Query execution could be optimized")
        else:
            logger.error("Query execution failed")
            return 1
            
    except Exception as e:
        logger.error(f"Error during test execution: {e}")
        return 1
    finally:
        test.disconnect()
        logger.info("Happy Frame SQL Test completed")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
