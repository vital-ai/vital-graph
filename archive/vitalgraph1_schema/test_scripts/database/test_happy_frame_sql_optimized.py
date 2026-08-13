#!/opt/homebrew/anaconda3/envs/vital-graph/bin/python
"""
Test and benchmark optimized happy frame SQL query performance in VitalGraph PostgreSQL database.

This script executes the optimized query with cache-based constant resolution and batch UUID-to-URI
conversion, demonstrating production-ready performance patterns.
"""

import logging
import os
import sys
import time
import yaml
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import psycopg
import psycopg.sql

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class HappyFrameSQLOptimizedTest:
    """Test and benchmark optimized happy frame SQL query performance."""
    
    def __init__(self, config_path: str = None):
        """Initialize with direct database configuration."""
        # Default config path
        if config_path is None:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            config_path = os.path.join(project_root, 'vitalgraphdb_config', 'vitalgraphdb-config.yaml')
        
        self.config_path = config_path
        self.db_config = self._load_config()
        self.connection = None
        self.constants_cache = {}
        
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
    
    def load_constants(self) -> Dict[str, str]:
        """Load constants from database (simulating cache lookup)."""
        constants_query = """
        SELECT 
            'rdf_type_uuid' as constant_name,
            t1.term_uuid as uuid_value
        FROM vitalgraph1__wordnet_frames__term_unlogged t1
        WHERE t1.term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
        
        UNION ALL
        
        SELECT 
            'kg_entity_uuid' as constant_name,
            t2.term_uuid as uuid_value
        FROM vitalgraph1__wordnet_frames__term_unlogged t2
        WHERE t2.term_text = 'http://vital.ai/ontology/haley-ai-kg#KGEntity'
        
        UNION ALL
        
        SELECT 
            'has_description_uuid' as constant_name,
            t3.term_uuid as uuid_value
        FROM vitalgraph1__wordnet_frames__term_unlogged t3
        WHERE t3.term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription'
        
        UNION ALL
        
        SELECT 
            'has_entity_slot_value_uuid' as constant_name,
            t4.term_uuid as uuid_value
        FROM vitalgraph1__wordnet_frames__term_unlogged t4
        WHERE t4.term_text = 'http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue'
        
        UNION ALL
        
        SELECT 
            'has_slot_type_uuid' as constant_name,
            t5.term_uuid as uuid_value
        FROM vitalgraph1__wordnet_frames__term_unlogged t5
        WHERE t5.term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGSlotType'
        
        UNION ALL
        
        SELECT 
            'has_source_entity_uuid' as constant_name,
            t9.term_uuid as uuid_value
        FROM vitalgraph1__wordnet_frames__term_unlogged t9
        WHERE t9.term_text = 'urn:hasSourceEntity'
        
        UNION ALL
        
        SELECT 
            'has_destination_entity_uuid' as constant_name,
            t10.term_uuid as uuid_value
        FROM vitalgraph1__wordnet_frames__term_unlogged t10
        WHERE t10.term_text = 'urn:hasDestinationEntity'
        
        ORDER BY constant_name;
        """
        
        try:
            with self.connection.cursor() as cursor:
                start_time = time.time()
                cursor.execute(constants_query)
                results = cursor.fetchall()
                constants_time = time.time() - start_time
                
                # Build constants dictionary
                constants = {}
                for constant_name, uuid_value in results:
                    constants[constant_name] = str(uuid_value)
                
                logger.info(f"Loaded {len(constants)} constants in {constants_time:.3f}s")
                return constants, constants_time
                
        except Exception as e:
            logger.error(f"Error loading constants: {e}")
            return {}, 0.0
    
    def execute_optimized_frame_query(self, constants: Dict[str, str]) -> Tuple[List, float]:
        """Execute the optimized frame query using hardcoded constants."""
        
        # Optimized Query 17 with early filtering and proper UNION semantics
        optimized_query = f"""
        WITH
        -- Happy entities with "happy" in description
        happy_entities AS (
            SELECT DISTINCT q1.subject_uuid as entity_uuid
            FROM vitalgraph1__wordnet_frames__rdf_quad_unlogged q1
            WHERE q1.predicate_uuid = '{constants['has_description_uuid']}'::uuid
              AND q1.object_uuid IN (
                  SELECT t.term_uuid 
                  FROM vitalgraph1__wordnet_frames__term_unlogged t
                  WHERE plainto_tsquery('happy') @@ t.term_text_fts
              )
        ),
        -- Optimized slot data - only include slots with matching "happy" entities (early filtering)
        slot_data AS (
            SELECT 
                q1.subject_uuid as slot_uuid,
                q1.object_uuid as entity_uuid,
                CASE WHEN q2.object_uuid = '{constants['has_source_entity_uuid']}'::uuid THEN 'source'
                     WHEN q2.object_uuid = '{constants['has_destination_entity_uuid']}'::uuid THEN 'dest'
                     ELSE NULL END as slot_type,
                -- All entities match by definition (due to INNER JOIN)
                1 as is_matching_entity
            FROM vitalgraph1__wordnet_frames__rdf_quad_unlogged q1
            JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged q2 ON q2.subject_uuid = q1.subject_uuid
            JOIN happy_entities he ON he.entity_uuid = q1.object_uuid  -- INNER JOIN = early filter!
            WHERE q1.predicate_uuid = '{constants['has_entity_slot_value_uuid']}'::uuid
              AND q2.predicate_uuid = '{constants['has_slot_type_uuid']}'::uuid
              AND q2.object_uuid IN ('{constants['has_source_entity_uuid']}'::uuid, '{constants['has_destination_entity_uuid']}'::uuid)
        ),
        edge_structure AS (
            SELECT 
                source_node_uuid as frame_uuid,
                dest_node_uuid as slot_uuid
            FROM vitalgraph1__wordnet_frames__edge_relationships_mv
        ),
        -- Efficient aggregation like query 16
        frame_aggregated AS (
            SELECT 
                es.frame_uuid,
                (array_agg(sd.slot_uuid) FILTER (WHERE sd.slot_type = 'source'))[1] as source_slot_uuid,
                (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'source'))[1] as source_entity_uuid,
                (array_agg(sd.slot_uuid) FILTER (WHERE sd.slot_type = 'dest'))[1] as dest_slot_uuid,
                (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'dest'))[1] as dest_entity_uuid,
                -- Simple flags for matching entities
                MAX(CASE WHEN sd.slot_type = 'source' AND sd.is_matching_entity = 1 THEN 1 ELSE 0 END) as source_matches_happy,
                MAX(CASE WHEN sd.slot_type = 'dest' AND sd.is_matching_entity = 1 THEN 1 ELSE 0 END) as dest_matches_happy
            FROM edge_structure es
            JOIN slot_data sd ON sd.slot_uuid = es.slot_uuid
            GROUP BY es.frame_uuid
            HAVING (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'source'))[1] IS NOT NULL
               AND (array_agg(sd.entity_uuid) FILTER (WHERE sd.slot_type = 'dest'))[1] IS NOT NULL
        )
        -- UNION: Mirror the SPARQL UNION structure exactly
        -- Solution 1: Bind ?entity to SOURCE entity when it matches "happy"
        SELECT 
            fa.source_entity_uuid as entity_uuid,
            fa.frame_uuid,
            fa.source_slot_uuid,
            fa.dest_slot_uuid,
            fa.source_entity_uuid,
            fa.dest_entity_uuid
        FROM frame_aggregated fa
        WHERE fa.source_matches_happy = 1
        UNION ALL
        -- Solution 2: Bind ?entity to DESTINATION entity when it matches "happy"
        SELECT 
            fa.dest_entity_uuid as entity_uuid,
            fa.frame_uuid,
            fa.source_slot_uuid,
            fa.dest_slot_uuid,
            fa.source_entity_uuid,
            fa.dest_entity_uuid
        FROM frame_aggregated fa
        WHERE fa.dest_matches_happy = 1
        ORDER BY entity_uuid
        LIMIT 500 OFFSET 0;
        """
        
        try:
            with self.connection.cursor() as cursor:
                start_time = time.time()
                cursor.execute(optimized_query)
                results = cursor.fetchall()
                query_time = time.time() - start_time
                
                logger.info(f"Executed optimized query in {query_time:.3f}s, got {len(results)} results")
                return results, query_time
                
        except Exception as e:
            logger.error(f"Error executing optimized query: {e}")
            return [], 0.0
    
    def batch_resolve_uuids(self, query_results: List) -> Tuple[Dict[str, str], float]:
        """Batch resolve all UUIDs to URIs."""
        if not query_results:
            return {}, 0.0
        
        # Collect all unique UUIDs from results
        all_uuids = set()
        for row in query_results:
            for uuid_val in row:
                if uuid_val:  # Skip None values
                    all_uuids.add(str(uuid_val))
        
        if not all_uuids:
            return {}, 0.0
        
        # Build batch lookup query
        uuid_list = "', '".join(all_uuids)
        batch_query = f"""
        SELECT term_uuid::text, term_text
        FROM vitalgraph1__wordnet_frames__term_unlogged
        WHERE term_uuid::text IN ('{uuid_list}')
        """
        
        try:
            with self.connection.cursor() as cursor:
                start_time = time.time()
                cursor.execute(batch_query)
                uuid_results = cursor.fetchall()
                lookup_time = time.time() - start_time
                
                # Build UUID -> URI mapping
                uuid_to_uri = {}
                for uuid_str, uri in uuid_results:
                    uuid_to_uri[uuid_str] = uri
                
                logger.info(f"Batch resolved {len(uuid_to_uri)} UUIDs in {lookup_time:.3f}s")
                return uuid_to_uri, lookup_time
                
        except Exception as e:
            logger.error(f"Error in batch UUID resolution: {e}")
            return {}, 0.0
    
    def format_construct_results(self, query_results: List, uuid_to_uri: Dict[str, str]) -> List[Dict]:
        """Format results to match SPARQL CONSTRUCT output format."""
        construct_results = []
        
        for i, row in enumerate(query_results):
            entity_uuid, frame_uuid, source_slot_uuid, dest_slot_uuid, source_entity_uuid, dest_entity_uuid = row
            
            # Create a result entry matching SPARQL CONSTRUCT format
            result_entry = {
                'entity': uuid_to_uri.get(str(entity_uuid), f"<UUID:{entity_uuid}>"),
                'frame': uuid_to_uri.get(str(frame_uuid), f"<UUID:{frame_uuid}>"),
                'sourceSlot': uuid_to_uri.get(str(source_slot_uuid), f"<UUID:{source_slot_uuid}>"),
                'destinationSlot': uuid_to_uri.get(str(dest_slot_uuid), f"<UUID:{dest_slot_uuid}>"),
                'sourceSlotEntity': uuid_to_uri.get(str(source_entity_uuid), f"<UUID:{source_entity_uuid}>"),
                'destinationSlotEntity': uuid_to_uri.get(str(dest_entity_uuid), f"<UUID:{dest_entity_uuid}>")
            }
            construct_results.append(result_entry)
        
        return construct_results
    
    def execute_full_optimized_test(self):
        """Execute the complete optimized test with timing breakdown."""
        logger.info("Starting optimized happy frame query test...")
        
        total_start_time = time.time()
        
        # Phase 1: Load constants (cache simulation)
        logger.info("Phase 1: Loading constants...")
        constants, constants_time = self.load_constants()
        if not constants:
            logger.error("Failed to load constants")
            return None
        
        # Phase 2: Execute optimized graph query
        logger.info("Phase 2: Executing optimized graph query...")
        query_results, query_time = self.execute_optimized_frame_query(constants)
        if not query_results:
            logger.warning("No query results returned")
            return None
        
        # Phase 3: Batch UUID resolution
        logger.info("Phase 3: Batch UUID resolution...")
        uuid_to_uri, lookup_time = self.batch_resolve_uuids(query_results)
        
        # Phase 4: Format results
        logger.info("Phase 4: Formatting results...")
        format_start = time.time()
        construct_results = self.format_construct_results(query_results, uuid_to_uri)
        format_time = time.time() - format_start
        
        total_time = time.time() - total_start_time
        
        return {
            'results': construct_results,
            'timing': {
                'constants_time': constants_time,
                'query_time': query_time,
                'lookup_time': lookup_time,
                'format_time': format_time,
                'total_time': total_time
            },
            'result_count': len(construct_results)
        }
    
    def pretty_print_results(self, test_result):
        """Pretty print the optimized test results."""
        if not test_result:
            logger.error("No test results to display")
            return
        
        results = test_result['results']
        timing = test_result['timing']
        result_count = test_result['result_count']
        
        print("\n" + "="*100)
        print("OPTIMIZED HAPPY FRAME SQL QUERY RESULTS")
        print("="*100)
        print(f"Total Execution Time: {timing['total_time']:.3f} seconds")
        print(f"Result Count: {result_count}")
        print("\nTiming Breakdown:")
        print(f"  Constants Loading: {timing['constants_time']:.3f}s ({timing['constants_time']/timing['total_time']*100:.1f}%)")
        print(f"  Graph Query:       {timing['query_time']:.3f}s ({timing['query_time']/timing['total_time']*100:.1f}%)")
        print(f"  Batch UUID Lookup: {timing['lookup_time']:.3f}s ({timing['lookup_time']/timing['total_time']*100:.1f}%)")
        print(f"  Result Formatting: {timing['format_time']:.3f}s ({timing['format_time']/timing['total_time']*100:.1f}%)")
        print("="*100)
        
        if result_count == 0:
            print("No results found.")
            return
        
        # Print header
        print(f"{'#':<3} {'Entity':<50} {'Frame':<50}")
        print("-" * 100)
        
        # Print first 10 results with numbering
        for i, result in enumerate(results[:10], 1):
            entity = result['entity'][:47] + "..." if len(result['entity']) > 50 else result['entity']
            frame = result['frame'][:47] + "..." if len(result['frame']) > 50 else result['frame']
            print(f"{i:<3} {entity:<50} {frame:<50}")
        
        if result_count > 10:
            print(f"... and {result_count - 10} more results")
        
        print("="*100)
        
        # Show detailed first result as example
        if results:
            print(f"\nDetailed first result (CONSTRUCT format):")
            first_result = results[0]
            print(f"  Entity: {first_result['entity']}")
            print(f"  Frame: {first_result['frame']}")
            print(f"  Source Slot: {first_result['sourceSlot']}")
            print(f"  Destination Slot: {first_result['destinationSlot']}")
            print(f"  Source Slot Entity: {first_result['sourceSlotEntity']}")
            print(f"  Destination Slot Entity: {first_result['destinationSlotEntity']}")
        
        print("\n" + "="*100)
    
    def print_sparql_rdf_output(self, results: List[Dict]):
        """Print results in N-Triples RDF format matching the CONSTRUCT query."""
        print("\n" + "="*100)
        print("SPARQL RDF OUTPUT (N-Triples Format)")
        print("="*100)
        print("# This matches the output format of the original SPARQL CONSTRUCT query:")
        print("# CONSTRUCT {")
        print("#   _:bnode1 <urn:hasEntity> ?entity .")
        print("#   _:bnode1 <urn:hasFrame> ?frame .")
        print("#   _:bnode1 <urn:hasSourceSlot> ?sourceSlot .")
        print("#   _:bnode1 <urn:hasDestinationSlot> ?destinationSlot .")
        print("#   _:bnode1 <urn:hasSourceSlotEntity> ?sourceSlotEntity .")
        print("#   _:bnode1 <urn:hasDestinationSlotEntity> ?destinationSlotEntity .")
        print("# }")
        print("")
        
        print("")
        print("="*100)
        print(f"Total RDF Triples: {len(results) * 6}")
        print(f"Total Result Blocks: {len(results)}")
        print("="*100)

        # Output all results in N-Triples format
        for i, result in enumerate(results):
            bnode = f"_:result{i+1}"
            print(f"{bnode} <urn:hasEntity> <{result['entity']}> .")
            print(f"{bnode} <urn:hasFrame> <{result['frame']}> .")
            print(f"{bnode} <urn:hasSourceSlot> <{result['sourceSlot']}> .")
            print(f"{bnode} <urn:hasDestinationSlot> <{result['destinationSlot']}> .")
            print(f"{bnode} <urn:hasSourceSlotEntity> <{result['sourceSlotEntity']}> .")
            print(f"{bnode} <urn:hasDestinationSlotEntity> <{result['destinationSlotEntity']}> .")
        


def main():
    """Main function to run the optimized happy frame SQL test."""
    logger.info("Starting Optimized Happy Frame SQL Test")
    logger.info("="*60)
    
    test = HappyFrameSQLOptimizedTest()
    
    try:
        # Connect to database
        if not test.connect():
            logger.error("Failed to connect to database")
            return 1
        
        # Execute the optimized test
        logger.info("Executing optimized happy frame query test...")
        test_result = test.execute_full_optimized_test()
        
        if test_result:
            # Pretty print results
            test.pretty_print_results(test_result)
            
            # Performance summary
            timing = test_result['timing']
            result_count = test_result['result_count']
            
            logger.info(f"\n🚀 OPTIMIZED PERFORMANCE SUMMARY:")
            logger.info(f"   Total Time: {timing['total_time']:.3f}s")
            logger.info(f"   Core Query: {timing['query_time']:.3f}s")
            logger.info(f"   Results Found: {result_count}")
            logger.info(f"   Rate: {result_count/timing['total_time']:.1f} results/second")
            
            if timing['total_time'] < 0.1:
                logger.info(f"   ⚡ BLAZING FAST: Ultra-optimized performance")
            elif timing['total_time'] < 0.5:
                logger.info(f"   🚀 EXCELLENT: Very fast optimized execution")
            elif timing['total_time'] < 1.0:
                logger.info(f"   ✅ GOOD: Fast optimized execution")
            else:
                logger.info(f"   ⚠️  MODERATE: Room for further optimization")
                
            # Compare with theoretical baseline
            baseline_time = 2.9  # Original query time
            improvement = (baseline_time - timing['total_time']) / baseline_time * 100
            logger.info(f"   📈 Improvement vs baseline: {improvement:.1f}% faster")
            

        else:
            logger.error("Optimized test execution failed")
            return 1
            
    except Exception as e:
        logger.error(f"Error during test execution: {e}")
        return 1
    finally:
        test.disconnect()
        logger.info("Optimized Happy Frame SQL Test completed")
        
        # Output N-Triples RDF format as the absolute last thing
        # if test_result and test_result.get('results'):
        #    test.print_sparql_rdf_output(test_result['results'])
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
