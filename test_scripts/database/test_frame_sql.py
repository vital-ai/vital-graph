#!/opt/homebrew/anaconda3/envs/vital-graph/bin/python
"""
Test and benchmark frame SQL query performance in VitalGraph PostgreSQL database.

This script fetches constants first, then executes the optimized frame query
with substituted values, timing the execution and providing performance statistics.
"""

import asyncio
import logging
import os
import sys
import time
import statistics
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

class FrameSQLBenchmark:
    """Test and benchmark frame SQL query performance."""
    
    def __init__(self, config_path: str = None):
        """Initialize with direct database configuration."""
        # Default config path
        if config_path is None:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            config_path = os.path.join(project_root, 'vitalgraphdb_config', 'vitalgraphdb-config.yaml')
        
        self.config_path = config_path
        self.db_config = self._load_config()
        self.connection = None
        self.constants = {}
        
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
                'database': db_config.get('database', 'vitalgraph'),
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
                'database': 'vitalgraph',
                'user': 'postgres',
                'password': '',
                'global_prefix': 'vitalgraph1'
            }
        
    def connect(self):
        """Connect to the database using synchronous psycopg.connect (like existing codebase)."""
        try:
            # Build connection string with debugging options
            conninfo = (
                f"host={self.db_config['host']} "
                f"port={self.db_config['port']} "
                f"dbname={self.db_config['database']} "
                f"user={self.db_config['user']} "
                f"password={self.db_config['password']}"
            )
            
            # Create synchronous connection using psycopg.connect (like existing codebase)
            self.connection = psycopg.connect(conninfo)
            self.connection.autocommit = True
            
            # Enable connection-level debugging
            with self.connection.cursor() as cursor:
                # Enable query logging and debugging
                cursor.execute("SET log_statement = 'all'")
                cursor.execute("SET log_min_duration_statement = 0")
                cursor.execute("SET client_min_messages = 'debug1'")
                cursor.execute("SET log_duration = on")
                cursor.execute("SET log_lock_waits = on")
                cursor.execute("SET deadlock_timeout = '1s'")
                
            logger.info(f"Connected to PostgreSQL database: {self.db_config['database']}")
            logger.info("Connection set to autocommit mode (synchronous like DBeaver)")
            logger.info("✅ Connection debugging enabled: log_statement=all, log_duration=on")
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
    
    def diagnose_database_terms(self, space_id: str = "wordnet_frames"):
        """Diagnose what terms exist in the database."""
        if not self.connection:
            raise RuntimeError("Not connected to database")
        
        global_prefix = self.db_config['global_prefix']
        term_table = f"{global_prefix}__{space_id}__term_unlogged"
        quad_table = f"{global_prefix}__{space_id}__rdf_quad_unlogged"
        
        logger.info("\n" + "="*80)
        logger.info("DATABASE DIAGNOSTIC")
        logger.info("="*80)
        
        # Check table existence
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN (%s, %s)
            """, (term_table, quad_table))
            
            existing_tables = cursor.fetchall()
            logger.info(f"Existing tables: {[row[0] for row in existing_tables]}")
            
            if not existing_tables:
                logger.error(f"❌ No tables found for space '{space_id}'!")
                return False
            
            # Check term table contents
            cursor.execute(f"SELECT COUNT(*) FROM {term_table}")
            term_count = cursor.fetchone()[0]
            logger.info(f"Total terms in {term_table}: {term_count:,}")
            
            # Check quad table contents
            cursor.execute(f"SELECT COUNT(*) FROM {quad_table}")
            quad_count = cursor.fetchone()[0]
            logger.info(f"Total quads in {quad_table}: {quad_count:,}")
            
            # Test the actual constants query from the frame SQL
            logger.info("\n🔍 Testing the constants query from frame SQL:")
            constants_query = f"""
            WITH constants AS (
                SELECT 
                    (SELECT term_uuid FROM {term_table} WHERE term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' LIMIT 1) AS rdf_type_uuid,
                    (SELECT term_uuid FROM {term_table} WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#KGEntity' LIMIT 1) AS kg_entity_uuid,
                    (SELECT term_uuid FROM {term_table} WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription' LIMIT 1) AS has_description_uuid,
                    (SELECT term_uuid FROM {term_table} WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue' LIMIT 1) AS has_entity_slot_value_uuid,
                    (SELECT term_uuid FROM {term_table} WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGSlotType' LIMIT 1) AS has_slot_type_uuid,
                    (SELECT term_uuid FROM {term_table} WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource' LIMIT 1) AS has_edge_source_uuid,
                    (SELECT term_uuid FROM {term_table} WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination' LIMIT 1) AS has_edge_destination_uuid,
                    (SELECT term_uuid FROM {term_table} WHERE term_text = 'http://vital.ai/graph/kgwordnetframes' LIMIT 1) AS graph_uuid,
                    (SELECT term_uuid FROM {term_table} WHERE term_text = 'urn:hasSourceEntity' LIMIT 1) AS has_source_entity_uuid,
                    (SELECT term_uuid FROM {term_table} WHERE term_text = 'urn:hasDestinationEntity' LIMIT 1) AS has_destination_entity_uuid
            )
            SELECT * FROM constants;
            """
            
            cursor.execute(constants_query)
            constants_result = cursor.fetchone()
            
            if constants_result:
                logger.info("Constants query result:")
                field_names = [
                    'rdf_type_uuid', 'kg_entity_uuid', 'has_description_uuid',
                    'has_entity_slot_value_uuid', 'has_slot_type_uuid', 'has_edge_source_uuid',
                    'has_edge_destination_uuid', 'graph_uuid', 'has_source_entity_uuid',
                    'has_destination_entity_uuid'
                ]
                
                null_count = 0
                for i, field_name in enumerate(field_names):
                    value = constants_result[i]
                    if value is None:
                        logger.info(f"  ❌ {field_name}: NULL")
                        null_count += 1
                    else:
                        logger.info(f"  ✅ {field_name}: {value}")
                
                logger.info(f"\nSummary: {null_count}/{len(field_names)} constants are NULL")
                
                if null_count > 0:
                    logger.error("❌ CRITICAL: Some constants are NULL - this will cause the frame query to hang!")
                    
                    # Show what terms actually exist
                    logger.info("\n🔍 Sample terms that DO exist in the database:")
                    cursor.execute(f"SELECT term_text FROM {term_table} WHERE term_text LIKE '%vital.ai%' OR term_text LIKE '%rdf-syntax%' LIMIT 10")
                    sample_terms = cursor.fetchall()
                    if sample_terms:
                        for (term_text,) in sample_terms:
                            logger.info(f"  {term_text}")
                    else:
                        logger.info("  No similar terms found")
                        
                    return False
                else:
                    logger.info("✅ All constants found - query should work!")
                
                    # Now check if there are any "happy" entities
                    logger.info("\n🔍 Checking for 'happy' entities (the actual query target):")
                    happy_entities_query = f"""
                        WITH constants AS (
                            SELECT 
                                (SELECT term_uuid FROM {term_table} WHERE term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' LIMIT 1) AS rdf_type_uuid,
                                (SELECT term_uuid FROM {term_table} WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#KGEntity' LIMIT 1) AS kg_entity_uuid,
                                (SELECT term_uuid FROM {term_table} WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription' LIMIT 1) AS has_description_uuid,
                                (SELECT term_uuid FROM {term_table} WHERE term_text = 'http://vital.ai/graph/kgwordnetframes' LIMIT 1) AS graph_uuid
                        ),
                        happy_entities AS (
                            SELECT q1.subject_uuid as entity_uuid
                            FROM constants
                            JOIN {term_table} obj
                                ON obj.term_text_fts @@ plainto_tsquery('english', 'happy')
                                AND obj.term_type = 'L'
                            JOIN {quad_table} q1 
                                ON q1.object_uuid = obj.term_uuid
                                AND q1.predicate_uuid = constants.has_description_uuid
                                AND q1.context_uuid = constants.graph_uuid
                            JOIN {quad_table} q2
                                ON q2.subject_uuid = q1.subject_uuid
                                AND q2.predicate_uuid = constants.rdf_type_uuid
                                AND q2.object_uuid = constants.kg_entity_uuid
                                AND q2.context_uuid = constants.graph_uuid
                        )
                        SELECT COUNT(*) FROM happy_entities;
                        """
                        
                    cursor.execute(happy_entities_query)
                    happy_count = cursor.fetchone()[0]
                    logger.info(f"  Entities with 'happy' descriptions: {happy_count}")
                    
                    if happy_count == 0:
                        logger.error("❌ CRITICAL: No 'happy' entities found!")
                        logger.error("The frame query will return 0 results and may hang due to empty result set optimization issues.")
                        logger.info("\n🔍 Let's check what description terms actually exist:")
                        
                        # Check what description terms exist
                        cursor.execute(f"""
                            SELECT obj.term_text, COUNT(*) as entity_count
                            FROM {term_table} obj
                            JOIN {quad_table} q1 ON q1.object_uuid = obj.term_uuid
                            WHERE obj.term_type = 'L' 
                            AND obj.term_text LIKE '%happy%'
                            GROUP BY obj.term_text
                            ORDER BY entity_count DESC
                            LIMIT 5
                        """)
                        
                        sample_descriptions = cursor.fetchall()
                        if sample_descriptions:
                            logger.info("  Terms containing 'happy':")
                            for term_text, count in sample_descriptions:
                                logger.info(f"    '{term_text}' - {count} entities")
                        else:
                            logger.info("  No terms containing 'happy' found at all")
                            
                            # Check any sample descriptions
                            cursor.execute(f"""
                                SELECT obj.term_text
                                FROM {term_table} obj
                                JOIN {quad_table} q1 ON q1.object_uuid = obj.term_uuid
                                WHERE obj.term_type = 'L' 
                                LIMIT 10
                            """)
                            any_descriptions = cursor.fetchall()
                            if any_descriptions:
                                logger.info("  Sample description terms in database:")
                                for (term_text,) in any_descriptions:
                                    truncated = term_text[:100] + ('...' if len(term_text) > 100 else '')
                                    logger.info(f"    '{truncated}'")
                        
                        return False
                    else:
                        logger.info(f"✅ Found {happy_count} 'happy' entities - query should return results!")
                        return True
            else:
                logger.error("❌ Constants query returned no results")
                return False
    
    def test_query_with_psql(self, query_sql: str) -> bool:
        """Test query execution using direct psql command-line for performance comparison."""
        import subprocess
        import tempfile
        import os
        import time
        
        temp_sql_file = None
        try:
            # Create a temporary file for the query
            temp_fd, temp_sql_file = tempfile.mkstemp(suffix='.sql', text=True)
            
            # Write the query to the temp file
            with os.fdopen(temp_fd, 'w') as f:
                # Add timing and execution plan commands
                f.write("\\timing on\n")
                f.write("\\echo 'Starting query execution...'\n")
                f.write(query_sql)
                f.write(";\n")
                f.write("\\echo 'Query completed.'\n")
            
            # Verify temp file was created
            if not temp_sql_file or not os.path.exists(temp_sql_file):
                logger.error(f"❌ Temporary SQL file creation failed: {temp_sql_file}")
                return False
                
            logger.info(f"📝 Created temporary SQL file: {temp_sql_file}")
            
            # Debug database configuration
            logger.info(f"🔍 DB Config: host={self.db_config.get('host')}, port={self.db_config.get('port')}, database={self.db_config.get('database')}, user={self.db_config.get('user')}")
            
            # Build psql command with correct path
            psql_cmd = [
                '/opt/homebrew/opt/postgresql@17/bin/psql',
                '-h', str(self.db_config['host']) if self.db_config['host'] else 'localhost',
                '-p', str(self.db_config['port']) if self.db_config['port'] else '5432',
                '-d', str(self.db_config['database']) if self.db_config['database'] else 'postgres',
                '-U', str(self.db_config['user']) if self.db_config['user'] else 'postgres',
                '-f', temp_sql_file,
                '--echo-queries',
                '--quiet'
            ]
            
            # Set password environment variable
            env = os.environ.copy()
            if self.db_config.get('password'):
                env['PGPASSWORD'] = str(self.db_config['password'])
            
            logger.info(f"🚀 Executing query via psql command-line...")
            logger.info(f"🔧 psql command: {' '.join(psql_cmd)}")
            start_time = time.time()
            
            # Execute psql command with timeout
            try:
                result = subprocess.run(
                    psql_cmd,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30  # 30 second timeout for psql
                )
            except Exception as e:
                logger.error(f"❌ subprocess.run failed: {e}")
                logger.error(f"❌ psql_cmd: {psql_cmd}")
                logger.error(f"❌ temp_sql_file: {temp_sql_file}")
                raise
            
            end_time = time.time()
            execution_time = end_time - start_time
            
            # Clean up temp file
            if temp_sql_file and os.path.exists(temp_sql_file):
                os.unlink(temp_sql_file)
            
            if result.returncode == 0:
                logger.info(f"✅ psql execution completed in {execution_time:.3f}s")
                
                # Parse output for timing information
                output_lines = result.stdout.strip().split('\n')
                timing_lines = [line for line in output_lines if 'Time:' in line or 'ms' in line]
                
                if timing_lines:
                    logger.info(f"📊 psql timing details:")
                    for line in timing_lines:
                        logger.info(f"  {line.strip()}")
                
                # Count results
                result_lines = [line for line in output_lines if line.strip() and not line.startswith('Starting') and not line.startswith('Query completed') and not 'Time:' in line]
                if result_lines:
                    # Try to count actual data rows (exclude headers)
                    data_rows = [line for line in result_lines if not line.startswith('-') and '|' in line]
                    logger.info(f"📈 psql returned {len(data_rows)} result rows")
                
                logger.info(f"🎯 COMPARISON: psql={execution_time:.3f}s vs Python client (timing pending)")
                return True
                
            else:
                logger.error(f"❌ psql execution failed (exit code {result.returncode})")
                if result.stderr:
                    logger.error(f"Error output: {result.stderr.strip()}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"❌ psql execution timed out after 30 seconds")
            return False
        except Exception as e:
            logger.error(f"❌ psql execution error: {e}")
            return False
        finally:
            # Ensure temp file is cleaned up
            try:
                if temp_sql_file and os.path.exists(temp_sql_file):
                    os.unlink(temp_sql_file)
            except:
                pass
    
    def fetch_constants(self, space_id: str = "wordnet_frames"):
        """Fetch the constants needed for the frame query."""
        if not self.connection:
            raise RuntimeError("Not connected to database")
        
        # Generate table names
        global_prefix = self.db_config['global_prefix']
        term_table = f"{global_prefix}__{space_id}__term_unlogged"
        
        # Constants SQL query
        constants_sql = f"""
        SELECT term_text, term_uuid
        FROM {term_table}
        WHERE term_text IN (
            'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
            'http://vital.ai/ontology/haley-ai-kg#KGEntity',
            'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription',
            'http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue',
            'http://vital.ai/ontology/haley-ai-kg#hasKGSlotType',
            'http://vital.ai/ontology/vital-core#hasEdgeSource',
            'http://vital.ai/ontology/vital-core#hasEdgeDestination',
            'http://vital.ai/graph/kgwordnetframes',
            'urn:hasSourceEntity',
            'urn:hasDestinationEntity'
        )
        """
        
        logger.info("Loading constants...")
        start_time = time.time()
        
        with self.connection.cursor() as cursor:
            cursor.execute(constants_sql)
            results = cursor.fetchall()
        
        constants_time = time.time() - start_time
        logger.info(f"Constants loaded in {constants_time:.3f}s")
        
        # Build constants dictionary
        constants_map = {}
        for row in results:
            text = row[0]  # term_text
            uuid = row[1]  # term_uuid
            
            if text == 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type':
                constants_map['rdf_type_uuid'] = uuid
            elif text == 'http://vital.ai/ontology/haley-ai-kg#KGEntity':
                constants_map['kg_entity_uuid'] = uuid
            elif text == 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription':
                constants_map['has_description_uuid'] = uuid
            elif text == 'http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue':
                constants_map['has_entity_slot_value_uuid'] = uuid
            elif text == 'http://vital.ai/ontology/haley-ai-kg#hasKGSlotType':
                constants_map['has_slot_type_uuid'] = uuid
            elif text == 'http://vital.ai/ontology/vital-core#hasEdgeSource':
                constants_map['has_edge_source_uuid'] = uuid
            elif text == 'http://vital.ai/ontology/vital-core#hasEdgeDestination':
                constants_map['has_edge_destination_uuid'] = uuid
            elif text == 'http://vital.ai/graph/kgwordnetframes':
                constants_map['graph_uuid'] = uuid
            elif text == 'urn:hasSourceEntity':
                constants_map['has_source_entity_uuid'] = uuid
            elif text == 'urn:hasDestinationEntity':
                constants_map['has_destination_entity_uuid'] = uuid
        
        self.constants = constants_map
        logger.info(f"Found {len(constants_map)} constants")
        return constants_map
    
    def build_frame_query(self, space_id: str = "wordnet_frames"):
        """Build the frame query using the optimized structure with hard-coded constants."""
        if not self.constants:
            raise RuntimeError("Constants not loaded")
            
        # Generate table names
        global_prefix = self.db_config['global_prefix']
        term_table = f"{global_prefix}__{space_id}__term_unlogged"
        quad_table = f"{global_prefix}__{space_id}__rdf_quad_unlogged"
        
        frame_sql_orig = """
        WITH constants AS (
    SELECT 
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' LIMIT 1) AS rdf_type_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#KGEntity' LIMIT 1) AS kg_entity_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription' LIMIT 1) AS has_description_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue' LIMIT 1) AS has_entity_slot_value_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGSlotType' LIMIT 1) AS has_slot_type_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource' LIMIT 1) AS has_edge_source_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination' LIMIT 1) AS has_edge_destination_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'http://vital.ai/graph/kgwordnetframes' LIMIT 1) AS graph_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'urn:hasSourceEntity' LIMIT 1) AS has_source_entity_uuid,
        (SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged WHERE term_text = 'urn:hasDestinationEntity' LIMIT 1) AS has_destination_entity_uuid
),
happy_entities AS (
    SELECT q1.subject_uuid as entity_uuid
    FROM constants
    JOIN vitalgraph1__wordnet_frames__term_unlogged obj
        ON obj.term_text_fts @@ plainto_tsquery('english', 'happy')
        AND obj.term_type = 'L'
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged q1 
        ON q1.object_uuid = obj.term_uuid
        AND q1.predicate_uuid = constants.has_description_uuid
        AND q1.context_uuid = constants.graph_uuid
    JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged q2
        ON q2.subject_uuid = q1.subject_uuid
        AND q2.predicate_uuid = constants.rdf_type_uuid
        AND q2.object_uuid = constants.kg_entity_uuid
        AND q2.context_uuid = constants.graph_uuid
)
-- Source entity is happy
SELECT 
    fc1.entity_uuid as entity,
    fc1.frame_uuid as frame,
    fc1.slot_uuid as sourceSlot,
    fc2.slot_uuid as destinationSlot,
    fc1.entity_uuid as sourceSlotEntity,
    fc2.entity_uuid as destinationSlotEntity
FROM constants
-- Get source slots with happy entities
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ev1
    ON ev1.predicate_uuid = constants.has_entity_slot_value_uuid
    AND ev1.context_uuid = constants.graph_uuid
    AND EXISTS (SELECT 1 FROM happy_entities WHERE entity_uuid = ev1.object_uuid)
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged st1
    ON st1.subject_uuid = ev1.subject_uuid
    AND st1.predicate_uuid = constants.has_slot_type_uuid
    AND st1.object_uuid = constants.has_source_entity_uuid
    AND st1.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ed1
    ON ed1.object_uuid = ev1.subject_uuid
    AND ed1.predicate_uuid = constants.has_edge_destination_uuid
    AND ed1.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged es1
    ON es1.subject_uuid = ed1.subject_uuid
    AND es1.predicate_uuid = constants.has_edge_source_uuid
    AND es1.context_uuid = constants.graph_uuid
-- Get corresponding destination slot for same frame
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ev2
    ON ev2.predicate_uuid = constants.has_entity_slot_value_uuid
    AND ev2.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged st2
    ON st2.subject_uuid = ev2.subject_uuid
    AND st2.predicate_uuid = constants.has_slot_type_uuid
    AND st2.object_uuid = constants.has_destination_entity_uuid
    AND st2.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ed2
    ON ed2.object_uuid = ev2.subject_uuid
    AND ed2.predicate_uuid = constants.has_edge_destination_uuid
    AND ed2.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged es2
    ON es2.subject_uuid = ed2.subject_uuid
    AND es2.predicate_uuid = constants.has_edge_source_uuid
    AND es2.object_uuid = es1.object_uuid  -- Same frame
    AND es2.context_uuid = constants.graph_uuid
-- Create result aliases
CROSS JOIN LATERAL (
    SELECT 
        ev1.subject_uuid as slot_uuid,
        ev1.object_uuid as entity_uuid,
        es1.object_uuid as frame_uuid
) fc1
CROSS JOIN LATERAL (
    SELECT 
        ev2.subject_uuid as slot_uuid,
        ev2.object_uuid as entity_uuid
) fc2

UNION ALL

-- Destination entity is happy
SELECT 
    fc2.entity_uuid as entity,
    fc1.frame_uuid as frame,
    fc1.slot_uuid as sourceSlot,
    fc2.slot_uuid as destinationSlot,
    fc1.entity_uuid as sourceSlotEntity,
    fc2.entity_uuid as destinationSlotEntity
FROM constants
-- Get destination slots with happy entities
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ev2
    ON ev2.predicate_uuid = constants.has_entity_slot_value_uuid
    AND ev2.context_uuid = constants.graph_uuid
    AND EXISTS (SELECT 1 FROM happy_entities WHERE entity_uuid = ev2.object_uuid)
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged st2
    ON st2.subject_uuid = ev2.subject_uuid
    AND st2.predicate_uuid = constants.has_slot_type_uuid
    AND st2.object_uuid = constants.has_destination_entity_uuid
    AND st2.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ed2
    ON ed2.object_uuid = ev2.subject_uuid
    AND ed2.predicate_uuid = constants.has_edge_destination_uuid
    AND ed2.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged es2
    ON es2.subject_uuid = ed2.subject_uuid
    AND es2.predicate_uuid = constants.has_edge_source_uuid
    AND es2.context_uuid = constants.graph_uuid
-- Get corresponding source slot for same frame
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ev1
    ON ev1.predicate_uuid = constants.has_entity_slot_value_uuid
    AND ev1.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged st1
    ON st1.subject_uuid = ev1.subject_uuid
    AND st1.predicate_uuid = constants.has_slot_type_uuid
    AND st1.object_uuid = constants.has_source_entity_uuid
    AND st1.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged ed1
    ON ed1.object_uuid = ev1.subject_uuid
    AND ed1.predicate_uuid = constants.has_edge_destination_uuid
    AND ed1.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged es1
    ON es1.subject_uuid = ed1.subject_uuid
    AND es1.predicate_uuid = constants.has_edge_source_uuid
    AND es1.object_uuid = es2.object_uuid  -- Same frame
    AND es1.context_uuid = constants.graph_uuid
-- Create result aliases
CROSS JOIN LATERAL (
    SELECT 
        ev1.subject_uuid as slot_uuid,
        ev1.object_uuid as entity_uuid,
        es1.object_uuid as frame_uuid
) fc1
CROSS JOIN LATERAL (
    SELECT 
        ev2.subject_uuid as slot_uuid,
        ev2.object_uuid as entity_uuid
) fc2

ORDER BY entity
LIMIT 10 OFFSET 0;
        """


        # Build query using the optimized structure with hard-coded UUIDs
        frame_sql = f"""
WITH happy_entities AS (
    SELECT q1.subject_uuid as entity_uuid
    FROM {term_table} obj
        JOIN {quad_table} q1 
            ON q1.object_uuid = obj.term_uuid
            AND q1.predicate_uuid = '{self.constants['has_description_uuid']}'
            AND q1.context_uuid = '{self.constants['graph_uuid']}'
        JOIN {quad_table} q2
            ON q2.subject_uuid = q1.subject_uuid
            AND q2.predicate_uuid = '{self.constants['rdf_type_uuid']}'
            AND q2.object_uuid = '{self.constants['kg_entity_uuid']}'
            AND q2.context_uuid = '{self.constants['graph_uuid']}'
    WHERE obj.term_text_fts @@ plainto_tsquery('english', 'happy')
        AND obj.term_type = 'L'
)
-- Source entity is happy
SELECT 
    fc1.entity_uuid as entity,
    fc1.frame_uuid as frame,
    fc1.slot_uuid as sourceSlot,
    fc2.slot_uuid as destinationSlot,
    fc1.entity_uuid as sourceSlotEntity,
    fc2.entity_uuid as destinationSlotEntity
FROM 
-- Get source slots with happy entities
{quad_table} ev1
    JOIN {quad_table} st1
        ON st1.subject_uuid = ev1.subject_uuid
        AND st1.predicate_uuid = '{self.constants['has_slot_type_uuid']}'
        AND st1.object_uuid = '{self.constants['has_source_entity_uuid']}'
        AND st1.context_uuid = '{self.constants['graph_uuid']}'
    JOIN {quad_table} ed1
        ON ed1.object_uuid = ev1.subject_uuid
        AND ed1.predicate_uuid = '{self.constants['has_edge_destination_uuid']}'
        AND ed1.context_uuid = '{self.constants['graph_uuid']}'
    JOIN {quad_table} es1
        ON es1.subject_uuid = ed1.subject_uuid
        AND es1.predicate_uuid = '{self.constants['has_edge_source_uuid']}'
        AND es1.context_uuid = '{self.constants['graph_uuid']}'
    -- Get corresponding destination slot for same frame
    JOIN {quad_table} ev2
        ON ev2.predicate_uuid = '{self.constants['has_entity_slot_value_uuid']}'
        AND ev2.context_uuid = '{self.constants['graph_uuid']}'
    JOIN {quad_table} st2
        ON st2.subject_uuid = ev2.subject_uuid
        AND st2.predicate_uuid = '{self.constants['has_slot_type_uuid']}'
        AND st2.object_uuid = '{self.constants['has_destination_entity_uuid']}'
        AND st2.context_uuid = '{self.constants['graph_uuid']}'
    JOIN {quad_table} ed2
        ON ed2.object_uuid = ev2.subject_uuid
        AND ed2.predicate_uuid = '{self.constants['has_edge_destination_uuid']}'
        AND ed2.context_uuid = '{self.constants['graph_uuid']}'
    JOIN {quad_table} es2
        ON es2.subject_uuid = ed2.subject_uuid
        AND es2.predicate_uuid = '{self.constants['has_edge_source_uuid']}'
        AND es2.object_uuid = es1.object_uuid  -- Same frame
        AND es2.context_uuid = '{self.constants['graph_uuid']}'
    -- Create result aliases
    CROSS JOIN LATERAL (
        SELECT 
            ev1.subject_uuid as slot_uuid,
            ev1.object_uuid as entity_uuid,
            es1.object_uuid as frame_uuid
    ) fc1
    CROSS JOIN LATERAL (
        SELECT 
            ev2.subject_uuid as slot_uuid,
            ev2.object_uuid as entity_uuid
    ) fc2
WHERE ev1.predicate_uuid = '{self.constants['has_entity_slot_value_uuid']}'
    AND ev1.context_uuid = '{self.constants['graph_uuid']}'
    AND EXISTS (SELECT 1 FROM happy_entities WHERE entity_uuid = ev1.object_uuid)

UNION ALL

-- Destination entity is happy
SELECT 
    fc2.entity_uuid as entity,
    fc1.frame_uuid as frame,
    fc1.slot_uuid as sourceSlot,
    fc2.slot_uuid as destinationSlot,
    fc1.entity_uuid as sourceSlotEntity,
    fc2.entity_uuid as destinationSlotEntity
FROM 
-- Get destination slots with happy entities
{quad_table} ev2
    JOIN {quad_table} st2
        ON st2.subject_uuid = ev2.subject_uuid
        AND st2.predicate_uuid = '{self.constants['has_slot_type_uuid']}'
        AND st2.object_uuid = '{self.constants['has_destination_entity_uuid']}'
        AND st2.context_uuid = '{self.constants['graph_uuid']}'
    JOIN {quad_table} ed2
        ON ed2.object_uuid = ev2.subject_uuid
        AND ed2.predicate_uuid = '{self.constants['has_edge_destination_uuid']}'
        AND ed2.context_uuid = '{self.constants['graph_uuid']}'
    JOIN {quad_table} es2
        ON es2.subject_uuid = ed2.subject_uuid
        AND es2.predicate_uuid = '{self.constants['has_edge_source_uuid']}'
        AND es2.context_uuid = '{self.constants['graph_uuid']}'
    -- Get corresponding source slot for same frame
    JOIN {quad_table} ev1
        ON ev1.predicate_uuid = '{self.constants['has_entity_slot_value_uuid']}'
        AND ev1.context_uuid = '{self.constants['graph_uuid']}'
    JOIN {quad_table} st1
        ON st1.subject_uuid = ev1.subject_uuid
        AND st1.predicate_uuid = '{self.constants['has_slot_type_uuid']}'
        AND st1.object_uuid = '{self.constants['has_source_entity_uuid']}'
        AND st1.context_uuid = '{self.constants['graph_uuid']}'
    JOIN {quad_table} ed1
        ON ed1.object_uuid = ev1.subject_uuid
        AND ed1.predicate_uuid = '{self.constants['has_edge_destination_uuid']}'
        AND ed1.context_uuid = '{self.constants['graph_uuid']}'
    JOIN {quad_table} es1
        ON es1.subject_uuid = ed1.subject_uuid
        AND es1.predicate_uuid = '{self.constants['has_edge_source_uuid']}'
        AND es1.object_uuid = es2.object_uuid  -- Same frame
        AND es1.context_uuid = '{self.constants['graph_uuid']}'
    -- Create result aliases
    CROSS JOIN LATERAL (
        SELECT 
            ev1.subject_uuid as slot_uuid,
            ev1.object_uuid as entity_uuid,
            es1.object_uuid as frame_uuid
    ) fc1
    CROSS JOIN LATERAL (
        SELECT 
            ev2.subject_uuid as slot_uuid,
            ev2.object_uuid as entity_uuid
    ) fc2
WHERE ev2.predicate_uuid = '{self.constants['has_entity_slot_value_uuid']}'
    AND ev2.context_uuid = '{self.constants['graph_uuid']}'
    AND EXISTS (SELECT 1 FROM happy_entities WHERE entity_uuid = ev2.object_uuid)

ORDER BY entity
LIMIT 10 OFFSET 0
"""
        
        # return frame_sql
        return frame_sql_orig
    

    async def execute_frame_query(self, space_id: str = "wordnet_frames"):
        """Execute the frame query once and return timing and results."""
        frame_sql = self.build_frame_query(space_id)
        
        logger.info("Starting query execution...")
        try:
            async with self.connection.cursor() as cursor:
                start_time = time.time()
                logger.info("Executing SQL query...")
                await cursor.execute(frame_sql)
                logger.info("Query executed, fetching results...")
                results = await cursor.fetchall()
                execution_time = time.time() - start_time
                logger.info(f"Query completed in {execution_time:.3f}s with {len(results)} results")
        except Exception as e:
            logger.error(f"Error during query execution: {e}")
            raise
        
        return {
            'execution_time': execution_time,
            'result_count': len(results),
            'results': results
        }
    
    async def analyze_table_structure(self, conn, space_id: str = "wordnet_frames"):
        """Analyze table structure and indexes for the frame query."""
        # Get table names for the space
        space_impl = self.db_impl.get_space_impl()
        from vitalgraph.db.postgresql.space.postgresql_space_schema import PostgreSQLSpaceSchema
        schema = PostgreSQLSpaceSchema(space_impl.global_prefix, space_id, use_unlogged=True)
        table_names = schema.get_table_names()
        term_table = table_names['term']
        quad_table = table_names['rdf_quad']
        
        cursor = conn.cursor()
        
        # Debug connection info
        cursor.execute("SELECT current_database(), current_schema(), current_user")
        db_info = cursor.fetchone()
        print(f"\n=== Connection Debug Info ===")
        print(f"Raw db_info: {db_info} (type: {type(db_info)})")
        if db_info:
            if isinstance(db_info, (list, tuple)) and len(db_info) >= 3:
                print(f"Database: {db_info[0]}")
                print(f"Schema: {db_info[1]}")
                print(f"User: {db_info[2]}")
            else:
                print(f"Unexpected db_info format: {db_info}")
        
        # Check if tables exist
        cursor.execute(f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = '{term_table}')")
        term_result = cursor.fetchone()
        term_exists = term_result[0] if isinstance(term_result, (list, tuple)) and len(term_result) > 0 else term_result
        cursor.execute(f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = '{quad_table}')")
        quad_result = cursor.fetchone()
        quad_exists = quad_result[0] if isinstance(quad_result, (list, tuple)) and len(quad_result) > 0 else quad_result
        print(f"Term table exists: {term_exists}")
        print(f"Quad table exists: {quad_exists}")
        
        # Analyze term table structure and indexes
        print(f"\n=== {term_table} Table Analysis ===")
        cursor.execute(f"""
            SELECT indexname
            FROM pg_indexes 
            WHERE tablename = '{term_table}'
            ORDER BY indexname
        """)
        term_indexes = cursor.fetchall()
        print(f"Found {len(term_indexes)} indexes on {term_table}:")
        term_index_names = []
        for idx_row in term_indexes:
            # Debug: print the raw row structure
            print(f"  DEBUG: Raw row: {idx_row} (type: {type(idx_row)})")
            if isinstance(idx_row, (list, tuple)) and len(idx_row) > 0:
                idx_name = idx_row[0]
            elif hasattr(idx_row, '__getitem__'):
                try:
                    idx_name = idx_row[0]
                except (KeyError, IndexError):
                    idx_name = str(idx_row)
            else:
                idx_name = str(idx_row)
            print(f"  - {idx_name}")
            term_index_names.append(idx_name)
            
        # Check for critical term table custom indexes
        critical_term_indexes = [
            'idx_vitalgraph1__wordnet_frames__term_text_lower',
            'idx_vitalgraph1__wordnet_frames__term_text_literals_gin',
            'idx_vitalgraph1__wordnet_frames__term_text_fts'
        ]
        
        print(f"\n=== Critical Term Index Check ===")
        for critical_idx in critical_term_indexes:
            if critical_idx in term_index_names:
                print(f"  ✅ {critical_idx} - EXISTS")
            else:
                print(f"  ❌ {critical_idx} - MISSING")
            
        # Analyze quad table structure and indexes  
        print(f"\n=== {quad_table} Table Analysis ===")
        cursor.execute(f"""
            SELECT indexname
            FROM pg_indexes 
            WHERE tablename = '{quad_table}'
            ORDER BY indexname
        """)
        quad_indexes = cursor.fetchall()
        print(f"Found {len(quad_indexes)} indexes on {quad_table}:")
        quad_index_names = []
        for idx_row in quad_indexes:
            if isinstance(idx_row, (list, tuple)) and len(idx_row) > 0:
                idx_name = idx_row[0]
            else:
                idx_name = str(idx_row)
            print(f"  - {idx_name}")
            quad_index_names.append(idx_name)
            
        # Check for specific custom indexes that are critical for performance
        critical_indexes = [
            'idx_vitalgraph1__wordnet_frames__quad_poc',
            'idx_vitalgraph1__wordnet_frames__quad_opc', 
            'idx_vitalgraph1__wordnet_frames__quad_cpso',
            'idx_vitalgraph1__wordnet_frames__quad_pco',
            'idx_quad_predicate_object_context_subject',
            'idx_quad_subject_predicate_context_object'
        ]
        
        print(f"\n=== Critical Custom Index Check ===")
        for critical_idx in critical_indexes:
            if critical_idx in quad_index_names:
                print(f"  ✅ {critical_idx} - EXISTS")
            else:
                print(f"  ❌ {critical_idx} - MISSING")
            
        # Get table sizes
        cursor.execute(f"""
            SELECT 
                schemaname,
                tablename,
                attname,
                n_distinct,
                correlation
            FROM pg_stats 
            WHERE tablename IN ('{term_table}', '{quad_table}')
            AND attname IN ('term_uuid', 'subject_uuid', 'predicate_uuid', 'object_uuid', 'context_uuid', 'term_text_fts')
            ORDER BY tablename, attname
        """)
        stats = cursor.fetchall()
        print(f"\n=== Table Statistics ===")
        for schema, table, column, n_distinct, correlation in stats:
            print(f"  {table}.{column}: n_distinct={n_distinct}, correlation={correlation}")
            
        return {
            'term_table': term_table,
            'quad_table': quad_table,
            'term_indexes': term_indexes,
            'quad_indexes': quad_indexes,
            'stats': stats
        }

    async def analyze_frame_query(self, conn, space_id: str = "wordnet_frames"):
        """Analyze the frame query execution plan."""
        frame_sql = self.build_frame_query(space_id)
        explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {frame_sql}"
        
        cursor = conn.cursor()
        start_time = time.time()
        cursor.execute(explain_sql)
        result = cursor.fetchone()
        analysis_time = time.time() - start_time
        
        # Extract the JSON plan - result is a tuple with JSON data
        if result:
            plan_data = result[0] if isinstance(result, (list, tuple)) and len(result) > 0 else result
        else:
            plan_data = None
        
        return {
            'analysis_time': analysis_time,
            'plan': plan_data
        }
    
    def print_execution_plan(self, explain_plan):
        """Print execution plan in a readable format."""
        if not explain_plan:
            print("No execution plan available")
            return
        
        print("\n" + "="*60)
        print("EXECUTION PLAN ANALYSIS")
        print("="*60)
        
        # Parse the JSON structure: explain_plan is a dict with 'QUERY PLAN' key
        if isinstance(explain_plan, dict) and 'QUERY PLAN' in explain_plan:
            query_plans = explain_plan['QUERY PLAN']
            if isinstance(query_plans, list) and len(query_plans) > 0:
                main_plan = query_plans[0]['Plan']
                
                # Extract key performance metrics
                total_time = main_plan.get('Actual Total Time', 0)
                total_cost = main_plan.get('Total Cost', 0)
                startup_time = main_plan.get('Actual Startup Time', 0)
                actual_rows = main_plan.get('Actual Rows', 0)
                
                # Extract buffer statistics
                shared_hit = main_plan.get('Shared Hit Blocks', 0)
                shared_read = main_plan.get('Shared Read Blocks', 0)
                temp_read = main_plan.get('Temp Read Blocks', 0)
                temp_written = main_plan.get('Temp Written Blocks', 0)
                
                print(f"🔍 PERFORMANCE SUMMARY:")
                print(f"   Total Execution Time: {total_time:.1f} ms ({total_time/1000:.2f} seconds)")
                print(f"   Startup Time: {startup_time:.1f} ms")
                print(f"   Total Cost: {total_cost:,.0f}")
                print(f"   Rows Returned: {actual_rows}")
                print(f"")
                print(f"📊 BUFFER USAGE:")
                print(f"   Shared Blocks Hit: {shared_hit:,} (cache hits)")
                print(f"   Shared Blocks Read: {shared_read:,} (disk reads)")
                print(f"   Temp Blocks Read: {temp_read:,}")
                print(f"   Temp Blocks Written: {temp_written:,}")
                
                # Calculate cache hit ratio
                if shared_hit + shared_read > 0:
                    hit_ratio = shared_hit / (shared_hit + shared_read) * 100
                    print(f"   Cache Hit Ratio: {hit_ratio:.1f}%")
                
                print(f"")
                print(f"⚠️  KEY INSIGHTS:")
                if shared_read > 1000000:  # More than 1M disk reads
                    print(f"   • HIGH DISK I/O: {shared_read:,} disk reads indicate poor index usage")
                if temp_read > 0 or temp_written > 0:
                    print(f"   • TEMP FILES: Query is using temporary storage (sorts/joins too large for memory)")
                if total_cost > 1000000:
                    print(f"   • HIGH COST: Query cost of {total_cost:,.0f} suggests inefficient execution plan")
                    
                self._print_plan_tree(main_plan, 0)
            else:
                print("No valid plan data found")
        else:
            print(f"Unexpected explain plan format: {type(explain_plan)}")
        
        print("="*60)
    
    def _print_plan_tree(self, node, indent=0):
        """Recursively print the execution plan tree."""
        prefix = "  " * indent
        node_type = node.get('Node Type', 'Unknown')
        actual_time = node.get('Actual Total Time', 0)
        actual_rows = node.get('Actual Rows', 0)
        cost = node.get('Total Cost', 0)
        
        print(f"\n{prefix}📋 {node_type}")
        print(f"{prefix}   Time: {actual_time:.1f}ms | Rows: {actual_rows} | Cost: {cost:,.0f}")
        
        # Print additional details for certain node types
        if 'Index Name' in node:
            print(f"{prefix}   🔍 Index: {node['Index Name']}")
        if 'Relation Name' in node:
            print(f"{prefix}   📊 Table: {node['Relation Name']}")
        if 'Filter' in node:
            print(f"{prefix}   🔍 Filter: {node['Filter']}")
        if 'Join Type' in node:
            print(f"{prefix}   🔗 Join: {node['Join Type']}")
        
        # Recursively print child plans
        for plan in node.get('Plans', []):
            self._print_plan_tree(plan, indent + 1)
    
    async def analyze_execution_plan(self, connection, query):
        """Analyze the execution plan for the query."""
        # Use EXPLAIN without ANALYZE first to avoid actually executing the query
        explain_query = f"EXPLAIN (FORMAT JSON) {query}"
        
        try:
            # Add timeout to prevent hanging
            async with asyncio.timeout(30):  # 30 second timeout
                async with connection.cursor() as cursor:
                    await cursor.execute(explain_query)
                    plan_result = await cursor.fetchone()
                    plan_json = plan_result[0][0]  # Extract JSON from result
                    
            return plan_json
        except asyncio.TimeoutError:
            logger.warning("Execution plan analysis timed out after 30 seconds")
            return None
        except Exception as e:
            logger.error(f"Error during execution plan analysis: {e}")
            return None

    def print_execution_plan_summary(self, plan_json):
        """Print a summary of the execution plan."""
        logger.info("\n" + "="*60)
        logger.info("EXECUTION PLAN ANALYSIS")
        logger.info("="*60)
        
        def extract_plan_info(node, depth=0):
            indent = "  " * depth
            node_type = node.get('Node Type', 'Unknown')
            
            # Extract key metrics
            actual_time = node.get('Actual Total Time', 0)
            actual_rows = node.get('Actual Rows', 0)
            actual_loops = node.get('Actual Loops', 1)
            
            # Buffer usage
            shared_hit = node.get('Shared Hit Blocks', 0)
            shared_read = node.get('Shared Read Blocks', 0)
            shared_written = node.get('Shared Written Blocks', 0)
            temp_read = node.get('Temp Read Blocks', 0)
            temp_written = node.get('Temp Written Blocks', 0)
            
            logger.info(f"{indent}{node_type}: {actual_time:.2f}ms, {actual_rows} rows, {actual_loops} loops")
            
            # Show buffer usage if significant
            if shared_hit > 1000 or shared_read > 100 or temp_read > 0:
                buffer_info = []
                if shared_hit > 0:
                    buffer_info.append(f"hit={shared_hit}")
                if shared_read > 0:
                    buffer_info.append(f"read={shared_read}")
                if shared_written > 0:
                    buffer_info.append(f"written={shared_written}")
                if temp_read > 0:
                    buffer_info.append(f"temp_read={temp_read}")
                if temp_written > 0:
                    buffer_info.append(f"temp_written={temp_written}")
                logger.info(f"{indent}  Buffers: {', '.join(buffer_info)}")
            
            # Show relation name if available
            if 'Relation Name' in node:
                logger.info(f"{indent}  Table: {node['Relation Name']}")
            
            # Show index name if available
            if 'Index Name' in node:
                logger.info(f"{indent}  Index: {node['Index Name']}")
            
            # Show join type if available
            if 'Join Type' in node:
                logger.info(f"{indent}  Join Type: {node['Join Type']}")
            
            # Recursively process child plans
            if 'Plans' in node:
                for child in node['Plans']:
                    extract_plan_info(child, depth + 1)
        
        # Extract overall execution stats
        plan = plan_json['Plan']
        total_time = plan.get('Actual Total Time', 0)
        total_rows = plan.get('Actual Rows', 0)
        
        logger.info(f"Total Execution Time: {total_time:.2f}ms")
        logger.info(f"Total Rows Returned: {total_rows}")
        logger.info("")
        
        # Extract detailed plan
        extract_plan_info(plan)
        
        logger.info("="*60)

    async def check_session_settings(self):
        """Check PostgreSQL session settings that might affect performance."""
        settings_to_check = [
            'work_mem',
            'shared_buffers', 
            'effective_cache_size',
            'random_page_cost',
            'seq_page_cost',
            'cpu_tuple_cost',
            'cpu_index_tuple_cost',
            'cpu_operator_cost',
            'enable_hashjoin',
            'enable_mergejoin',
            'enable_nestloop',
            'enable_seqscan',
            'enable_indexscan',
            'enable_indexonlyscan'
        ]
        
        logger.info("\n" + "="*60)
        logger.info("POSTGRESQL SESSION SETTINGS")
        logger.info("="*60)
        
        async with self.connection.cursor() as cursor:
            for setting in settings_to_check:
                await cursor.execute(f"SHOW {setting}")
                result = await cursor.fetchone()
                logger.info(f"{setting}: {result[0]}")
        
        logger.info("="*60)

    async def benchmark_frame_query(self, space_id: str = "wordnet_frames", iterations: int = 10):
        """Benchmark the frame query with multiple iterations."""
        logger.info(f"Benchmarking frame query with {iterations} iterations...")
        
        times = []
        sample_results = None
        
        # Check session settings first
        await self.check_session_settings()
        
        # Output the exact query for comparison with DBeaver
        frame_sql = self.build_frame_query(space_id)
        logger.info("\n" + "="*60)
        logger.info("EXACT QUERY BEING EXECUTED")
        logger.info("="*60)
        logger.info("Copy this query to DBeaver for comparison:")
        logger.info("\n" + frame_sql)
        logger.info("="*60)
        
        # Analyze the execution plan
        logger.info("\nAnalyzing execution plan...")
        try:
            plan_json = await self.analyze_execution_plan(self.connection, frame_sql)
            if plan_json:
                self.print_execution_plan_summary(plan_json)
            else:
                logger.warning("Execution plan analysis failed or timed out")
        except Exception as e:
            logger.error(f"Failed to analyze execution plan: {e}")
        
        logger.info(f"\nBenchmarking frame query with {iterations} iterations...")
        
        for i in range(iterations):
            logger.info(f"Iteration {i+1}/{iterations}")
            result = await self.execute_frame_query(space_id)
            times.append(result['execution_time'])
            
            # Store sample results from first iteration
            if i == 0:
                sample_results = result['results']
                logger.info(f"Sample results (first 3):")
                for j, row in enumerate(sample_results[:3], 1):
                    # Convert tuple result to dict-like access
                    entity = row[0]  # entity
                    frame = row[1]   # frame
                    logger.info(f"  {j}: entity={entity}, frame={frame}")
        
        # Calculate statistics
        best_time = min(times)
        worst_time = max(times)
        avg_time = sum(times) / len(times)
        median_time = sorted(times)[len(times) // 2]
        
        # Calculate standard deviation
        variance = sum((t - avg_time) ** 2 for t in times) / len(times)
        std_dev = variance ** 0.5
        
        return {
            'iterations': iterations,
            'result_count': len(sample_results) if sample_results else 0,
            'best_time': best_time,
            'worst_time': worst_time,
            'avg_time': avg_time,
            'median_time': median_time,
            'std_dev': std_dev,
            'total_time': sum(times),
            'times': times,
            'sample_results': sample_results
        }

def main():
    """Main function to run the frame SQL benchmark."""
    benchmark = FrameSQLBenchmark()
    
    try:
        # Connect to database
        if not benchmark.connect():
            logger.error("Failed to connect to database")
            return
        
        # First, diagnose the database to check for required terms
        logger.info("Running database diagnostic...")
        terms_ok = benchmark.diagnose_database_terms()
        
        if not terms_ok:
            logger.error("❌ Database diagnostic failed - required terms are missing!")
            logger.error("Cannot proceed with frame query benchmark.")
            return
        
        logger.info("✅ Database diagnostic passed - proceeding with benchmark...")
        
        # Load constants for the query
        benchmark.fetch_constants()
        
        # Just get execution plan without running the query
        logger.info("\n" + "="*60)
        logger.info("GETTING FRESH EXECUTION PLAN")
        logger.info("="*60)
        
        frame_sql = benchmark.build_frame_query()
        logger.info("\nAnalyzing execution plan...")
        try:
            plan_json = benchmark.analyze_execution_plan(benchmark.connection, frame_sql)
            if plan_json:
                benchmark.print_execution_plan_summary(plan_json)
            else:
                logger.warning("Execution plan analysis failed or timed out")
        except Exception as e:
            logger.error(f"Failed to analyze execution plan: {e}")
        
        logger.info("\n✅ Execution plan analysis complete")
        
        # Skip sync test since it also hangs - go straight to full-text search diagnostic
        
        # Test full-text search directly to isolate the issue
        logger.info("\n" + "="*60)
        logger.info("FULL-TEXT SEARCH DIAGNOSTIC")
        logger.info("="*60)
        
        logger.info("\n🔍 Testing full-text search directly...")
        
        # Use the benchmark connection and create a new cursor for diagnostics
        with benchmark.connection.cursor() as diag_cursor:
            # Define table name for diagnostics
            term_table = "vitalgraph1__wordnet_frames__term_unlogged"
            
            # Check session settings that might affect query planning
            logger.info("\n1. Session Settings (Query Planner Focus):")
            settings_to_check = [
                # Text search settings
                'default_text_search_config',
                'client_encoding',
                'search_path',
                
                # Query planner settings that could affect execution
                'work_mem',
                'shared_buffers', 
                'effective_cache_size',
                'random_page_cost',
                'seq_page_cost',
                
                # Planner enable/disable settings
                'enable_nestloop',
                'enable_hashjoin',
                'enable_mergejoin',
                'enable_indexscan',
                'enable_indexonlyscan',
                'enable_bitmapscan',
                'enable_seqscan',
                
                # Other important settings
                'default_transaction_isolation',
                'statement_timeout',
                'lock_timeout',
                'application_name'
            ]
            
            for setting in settings_to_check:
                try:
                    diag_cursor.execute(f"SHOW {setting}")
                    value = diag_cursor.fetchone()[0]
                    logger.info(f"  {setting}: {value}")
                except Exception as e:
                    logger.info(f"  {setting}: ERROR - {e}")
            
            # Test the full-text search that's failing
            logger.info("\n2. Full-text Search Tests:")
            
            # Test basic literal count
            diag_cursor.execute(f"SELECT COUNT(*) FROM {term_table} WHERE term_type = 'L'")
            literal_count = diag_cursor.fetchone()[0]
            logger.info(f"  Total literals: {literal_count:,}")
            
            # Test FTS column population
            diag_cursor.execute(f"SELECT COUNT(*) FROM {term_table} WHERE term_text_fts IS NOT NULL AND term_type = 'L'")
            fts_populated = diag_cursor.fetchone()[0]
            logger.info(f"  FTS column populated: {fts_populated:,}")
            
            # Test the exact search that's failing
            diag_cursor.execute(f"""
                SELECT COUNT(*) FROM {term_table} 
                WHERE term_text_fts @@ plainto_tsquery('english', 'happy')
                AND term_type = 'L'
            """)
            happy_fts_count = diag_cursor.fetchone()[0]
            logger.info(f"  FTS 'happy' matches: {happy_fts_count}")
            
            # Test alternative search methods
            diag_cursor.execute(f"SELECT COUNT(*) FROM {term_table} WHERE term_text ILIKE '%happy%' AND term_type = 'L'")
            happy_ilike_count = diag_cursor.fetchone()[0]
            logger.info(f"  ILIKE '%happy%' matches: {happy_ilike_count}")
            
            # If FTS returns 0 but ILIKE returns results, we found the issue
            if happy_fts_count == 0 and happy_ilike_count > 0:
                logger.error("\n❌ ISSUE FOUND: Full-text search returns 0 but ILIKE finds matches!")
                logger.error("This explains why the query hangs in Python but works in DBeaver.")
                logger.error("DBeaver might be using different text search configuration.")
                
                # Show some sample matches
                diag_cursor.execute(f"SELECT term_text FROM {term_table} WHERE term_text ILIKE '%happy%' AND term_type = 'L' LIMIT 3")
                samples = diag_cursor.fetchall()
                logger.info("\nSample terms containing 'happy':")
                for (text,) in samples:
                    logger.info(f"  '{text[:100]}{'...' if len(text) > 100 else ''}'")
                    
            elif happy_fts_count > 0:
                logger.info(f"\n✅ Full-text search working: Found {happy_fts_count} matches")
            else:
                logger.info("\n⚠️ No 'happy' matches found with either method")
        
        logger.info("\n✅ Full-text search diagnostic complete - exiting")
        
        
        # Find actual search terms that exist in the database
        logger.info("\n" + "="*60)
        logger.info("FINDING REAL SEARCH TERMS")
        logger.info("="*60)
        
        with benchmark.connection.cursor() as cursor:
            global_prefix = benchmark.db_config['global_prefix']
            term_table = f"{global_prefix}__wordnet_frames__term_unlogged"
            quad_table = f"{global_prefix}__wordnet_frames__rdf_quad_unlogged"
            
            # Find common English words in descriptions
            logger.info("\n🔍 Searching for common English words in descriptions...")
            search_words = ['happy','good', 'bad', 'big', 'small', 'new', 'old', 'first', 'last', 'long', 'short', 'high', 'low', 'right', 'left', 'young', 'great', 'little', 'own', 'other', 'new', 'old', 'right', 'good', 'high', 'small', 'large', 'next', 'early', 'important', 'few', 'public', 'bad', 'same', 'able']
            
            found_words = []
            for word in search_words[:10]:  # Test first 10 words
                cursor.execute(f"""
                    SELECT COUNT(DISTINCT q1.subject_uuid) as entity_count
                    FROM {term_table} obj
                    JOIN {quad_table} q1 ON q1.object_uuid = obj.term_uuid
                    WHERE obj.term_text_fts @@ plainto_tsquery('english', %s)
                    AND obj.term_type = 'L'
                """, (word,))
                
                count = cursor.fetchone()[0]
                if count > 0:
                    found_words.append((word, count))
                    logger.info(f"  ✅ '{word}' - {count} entities")
                else:
                    logger.info(f"  ❌ '{word}' - 0 entities")
            
            if found_words:
                # Use the word with the most entities
                # Force use of 'happy' as requested by user
                best_word = 'happy'
                happy_info = next((word, count) for word, count in found_words if word == 'happy')
                best_count = happy_info[1] if happy_info else 0
                logger.info(f"\n🎆 USING: '{best_word}' as requested ({best_count} entities)")
                
                # Test the REAL frame query with happy
                logger.info(f"\n🗺 Testing REAL frame query with '{best_word}'...")
                
                # Create the actual frame query with the different search term
                space_id = "wordnet_frames"  # Define space_id for the query
                frame_sql = benchmark.build_frame_query(space_id)
                original_search_term = 'happy'  # The original term in the query
                modified_frame_sql = frame_sql.replace(f"plainto_tsquery('english', '{original_search_term}')", f"plainto_tsquery('english', '{best_word}')")
                
                # First, test with direct psql command-line for comparison
                logger.info(f"\n🔧 Testing with direct psql command-line first...")
                psql_success = benchmark.test_query_with_psql(modified_frame_sql)
                
                if psql_success:
                    logger.info(f"✅ Direct psql execution successful - now testing Python client...")
                else:
                    logger.error(f"❌ Direct psql execution failed - query may have issues")
                
                # Log the query being executed
                logger.info(f"\n📝 Query to execute (first 500 chars):")
                logger.info(f"{modified_frame_sql[:500]}...")
                
                import time
                start_time = time.time()
                
                try:
                    # Execute with manual timeout handling (synchronous)
                    import signal
                    
                    def timeout_handler(signum, frame):
                        raise TimeoutError("Query execution timed out")
                    
                    # Set up timeout
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(10)  # 10 second timeout
                    
                    # Test both direct execution and prepared statement (like DBeaver)
                    logger.info(f"🔧 Testing prepared statement execution (like DBeaver)...")
                    
                    try:
                        # First try prepared statement approach (like DBeaver uses)
                        cursor.execute("PREPARE frame_query AS " + modified_frame_sql)
                        logger.info(f"✅ Query prepared successfully")
                        
                        cursor.execute("EXECUTE frame_query")
                        logger.info(f"✅ Prepared statement executed successfully, fetching results...")
                        results = cursor.fetchall()
                        logger.info(f"✅ Results fetched successfully from prepared statement")
                        
                        # Clean up prepared statement
                        cursor.execute("DEALLOCATE frame_query")
                        
                    except Exception as prep_error:
                        logger.warning(f"⚠️ Prepared statement failed: {prep_error}")
                        logger.info(f"🔧 Falling back to direct execution...")
                        
                        # Fallback to direct execution
                        cursor.execute(modified_frame_sql)
                        logger.info(f"✅ Direct query executed successfully, fetching results...")
                        results = cursor.fetchall()
                        logger.info(f"✅ Results fetched successfully from direct execution")
                    
                    # Cancel timeout
                    signal.alarm(0)
                    end_time = time.time()
                    
                    logger.info(f"  ✅ Query completed in {end_time - start_time:.3f}s")
                    logger.info(f"  ✅ Found {len(results)} entities with '{best_word}' descriptions")
                    
                    if len(results) > 0:
                        logger.info(f"\n🎉 SUCCESS: The REAL frame query works with '{best_word}'!")
                        logger.info(f"\nFirst few results:")
                        for i, row in enumerate(results[:3], 1):
                            logger.info(f"  {i}: entity={row[0]}, frame={row[1]}")
                    else:
                        logger.info(f"\n⚠️ Query completed but returned no results for '{best_word}'")
                        
                except TimeoutError:
                    end_time = time.time()
                    logger.error(f"\n❌ TIMEOUT: Query with '{best_word}' also hangs after {end_time - start_time:.1f}s!")
                    logger.error(f"This means the issue is NOT term-specific but with the query structure itself.")
                    # Cancel timeout in case of exception
                    signal.alarm(0)
                    
                except Exception as e:
                    end_time = time.time()
                    logger.error(f"\n❌ ERROR: Query with '{best_word}' failed: {e}")
                    # Cancel timeout in case of exception
                    signal.alarm(0)
            else:
                logger.error("❌ No common English words found in descriptions")
                logger.info("The database may not contain English text descriptions")
        
        return
        
        # Print results
        logger.info("\n" + "="*60)
        logger.info("FRAME SQL BENCHMARK RESULTS")
        logger.info("="*60)
        logger.info(f"Iterations: {stats['iterations']}")
        logger.info(f"Result Count: {stats['result_count']}")
        logger.info(f"Best Time: {stats['best_time']:.3f}s")
        logger.info(f"Worst Time: {stats['worst_time']:.3f}s")
        logger.info(f"Average Time: {stats['avg_time']:.3f}s")
        logger.info(f"Median Time: {stats['median_time']:.3f}s")
        logger.info(f"Std Deviation: {stats['std_dev']:.3f}s")
        logger.info(f"Total Time: {stats['total_time']:.3f}s")
        
        # Check against target performance
        target_time = 1.1  # Target from memories
        if stats['avg_time'] <= target_time:
            logger.info(f"\n🎯 TARGET ACHIEVED! Average time {stats['avg_time']:.3f}s <= {target_time}s")
        else:
            gap = stats['avg_time'] - target_time
            logger.info(f"\n⏱️  Still {gap:.3f}s away from {target_time}s target")
            logger.info(f"   Current performance is {stats['avg_time']/target_time:.1f}x slower than target")
        
        logger.info("\nAll Times (seconds):")
        for i, t in enumerate(stats['times'], 1):
            logger.info(f"  {i:2d}: {t:.3f}s")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"Error during benchmark: {e}")
        raise
    finally:
        benchmark.disconnect()
        logger.info("Disconnected from database")

if __name__ == "__main__":
    main()
