#!/usr/bin/env python3
"""
Debug script to check what graphs exist in the WordNet space.

This script will:
1. Check what's in the graph table
2. Check what graph URIs exist in the rdf_quad table
3. Create missing graph entries if needed
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.config.config_loader import ConfigLoader
from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_wordnet_graphs():
    """Check what graphs exist for WordNet data."""
    
    # Load configuration
    config_loader = ConfigLoader()
    config = config_loader.load_config()
    
    # Get database configuration
    db_config = config.get('database', {})
    tables_config = config.get('tables', {})
    
    # Create database implementation
    db_impl = PostgreSQLDbImpl(db_config, tables_config)
    
    try:
        # Connect to database
        await db_impl.connect()
        logger.info("✅ Connected to database")
        
        # Get space implementation
        space_impl = db_impl.get_space_impl()
        if not space_impl:
            logger.error("❌ No space implementation available")
            return
        
        # Check WordNet space (assuming it's called 'wordnet_frames')
        space_id = 'wordnet_frames'
        
        logger.info(f"🔍 Checking graphs in space '{space_id}'...")
        
        # 1. Check what's in the graph table
        logger.info("\n📊 Checking graph table...")
        try:
            graphs_from_table = await space_impl.graphs.list_graphs(space_id)
            logger.info(f"Found {len(graphs_from_table)} graphs in graph table:")
            for graph in graphs_from_table:
                logger.info(f"  - {graph['graph_uri']} ({graph['triple_count']} triples)")
        except Exception as e:
            logger.error(f"Error checking graph table: {e}")
            graphs_from_table = []
        
        # 2. Check what graph URIs exist in rdf_quad table
        logger.info("\n📊 Checking distinct graph URIs in rdf_quad table...")
        try:
            table_names = space_impl._get_table_names(space_id)
            quad_table = table_names['rdf_quad']
            term_table = table_names['term']
            
            async with space_impl.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Get distinct graph URIs with counts
                sql = f"""
                    SELECT c_term.term_text as graph_uri, COUNT(*) as triple_count
                    FROM {quad_table} quad
                    JOIN {term_table} c_term ON quad.context_uuid = c_term.term_uuid
                    GROUP BY c_term.term_text
                    ORDER BY triple_count DESC
                """
                
                cursor.execute(sql)
                rows = cursor.fetchall()
                
                logger.info(f"Found {len(rows)} distinct graph URIs in rdf_quad table:")
                graphs_from_quads = []
                for row in rows:
                    graph_uri = row[0]
                    triple_count = row[1]
                    graphs_from_quads.append({'graph_uri': graph_uri, 'triple_count': triple_count})
                    logger.info(f"  - {graph_uri}: {triple_count:,} triples")
                
        except Exception as e:
            logger.error(f"Error checking rdf_quad table: {e}")
            graphs_from_quads = []
        
        # 3. Find missing graphs and create them
        logger.info("\n🔧 Checking for missing graph entries...")
        
        existing_graph_uris = {g['graph_uri'] for g in graphs_from_table}
        quad_graph_uris = {g['graph_uri'] for g in graphs_from_quads}
        
        missing_graphs = quad_graph_uris - existing_graph_uris
        
        if missing_graphs:
            logger.info(f"Found {len(missing_graphs)} missing graph entries:")
            for graph_uri in missing_graphs:
                logger.info(f"  - {graph_uri}")
                
                # Find the triple count for this graph
                quad_info = next((g for g in graphs_from_quads if g['graph_uri'] == graph_uri), None)
                triple_count = quad_info['triple_count'] if quad_info else 0
                
                # Create the graph entry
                try:
                    success = await space_impl.graphs.create_graph(space_id, graph_uri)
                    if success:
                        # Update the triple count
                        await space_impl.graphs.update_graph_triple_count(
                            space_id, graph_uri, absolute_count=triple_count
                        )
                        logger.info(f"  ✅ Created graph entry for {graph_uri} with {triple_count:,} triples")
                    else:
                        logger.error(f"  ❌ Failed to create graph entry for {graph_uri}")
                except Exception as e:
                    logger.error(f"  ❌ Error creating graph entry for {graph_uri}: {e}")
        else:
            logger.info("✅ All graphs from rdf_quad table have corresponding graph table entries")
        
        # 4. Final verification
        logger.info("\n🔍 Final verification - listing graphs again...")
        try:
            final_graphs = await space_impl.graphs.list_graphs(space_id)
            logger.info(f"Final count: {len(final_graphs)} graphs in graph table:")
            for graph in final_graphs:
                logger.info(f"  - {graph['graph_uri']} ({graph['triple_count']:,} triples)")
        except Exception as e:
            logger.error(f"Error in final verification: {e}")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Disconnect from database
        await db_impl.disconnect()
        logger.info("🔌 Disconnected from database")

if __name__ == "__main__":
    asyncio.run(check_wordnet_graphs())
