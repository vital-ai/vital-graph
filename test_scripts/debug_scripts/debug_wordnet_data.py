#!/usr/bin/env python3

"""
Debug script to check what's actually in the WordNet data
"""

import asyncio
import logging
from vitalgraph.space.space_manager import SpaceManager
from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl

async def debug_wordnet_data():
    """Check what data exists in the WordNet graph."""
    
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # Initialize database
    db_impl = PostgreSQLDbImpl()
    await db_impl.initialize()
    
    # Initialize space manager
    space_manager = SpaceManager(db_impl)
    await space_manager.initialize_from_database()
    
    # Get space
    space_record = space_manager.get_space("test_4847")
    if not space_record:
        logger.error("Space test_4847 not found")
        return
    
    space_impl = space_record.space_impl
    db_space_impl = space_impl.get_db_space_impl()
    
    # Get graph UUID for WordNet graph
    graph_id = "urn:kgframe-wordnet-002"
    table_prefix = "vitalgraph2__test_4847__"
    
    async with db_space_impl.core.get_dict_connection() as conn:
        # 1. Check if graph exists
        with conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT term_uuid FROM {table_prefix}term 
                WHERE term_text = %s AND term_type = 'U'
            """, [graph_id])
            graph_result = cursor.fetchone()
            
        if not graph_result:
            logger.error(f"Graph {graph_id} not found in term table")
            return
            
        graph_uuid = str(graph_result['term_uuid'])
        logger.info(f"Found graph UUID: {graph_uuid}")
        
        # 2. Check total triples in this graph
        with conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT COUNT(*) as total_triples
                FROM {table_prefix}rdf_quad 
                WHERE context_uuid = %s
            """, [graph_uuid])
            total_result = cursor.fetchone()
            
        logger.info(f"Total triples in graph: {total_result['total_triples']}")
        
        # 3. Check what predicates exist
        with conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT p_term.term_text, COUNT(*) as count
                FROM {table_prefix}rdf_quad q
                JOIN {table_prefix}term p_term ON q.predicate_uuid = p_term.term_uuid
                WHERE q.context_uuid = %s
                GROUP BY p_term.term_text
                ORDER BY count DESC
                LIMIT 20
            """, [graph_uuid])
            predicate_results = cursor.fetchall()
            
        logger.info("Top 20 predicates:")
        for row in predicate_results:
            logger.info(f"  {row['term_text']}: {row['count']} triples")
        
        # 4. Check for vitaltype-like predicates
        vitaltype_candidates = [
            "http://vital.ai/ontology/vital-core#vitaltype",
            "http://vital.ai/ontology/vital-core#type", 
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            "type",
            "vitaltype"
        ]
        
        for candidate in vitaltype_candidates:
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT COUNT(*) as count
                    FROM {table_prefix}rdf_quad q
                    JOIN {table_prefix}term p_term ON q.predicate_uuid = p_term.term_uuid
                    WHERE q.context_uuid = %s AND p_term.term_text = %s
                """, [graph_uuid, candidate])
                result = cursor.fetchone()
                
            if result['count'] > 0:
                logger.info(f"Found {result['count']} triples with predicate: {candidate}")
        
        # 5. Sample some subjects to see what they look like
        with conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT DISTINCT s_term.term_text
                FROM {table_prefix}rdf_quad q
                JOIN {table_prefix}term s_term ON q.subject_uuid = s_term.term_uuid
                WHERE q.context_uuid = %s
                LIMIT 10
            """, [graph_uuid])
            subject_results = cursor.fetchall()
            
        logger.info("Sample subjects:")
        for row in subject_results:
            logger.info(f"  {row['term_text']}")

if __name__ == "__main__":
    asyncio.run(debug_wordnet_data())
