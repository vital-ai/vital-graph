#!/usr/bin/env python3
"""
Create missing graph entries for imported RDF data.

This script finds all distinct graph URIs in the rdf_quad table and creates
corresponding entries in the graph table so they show up in the frontend.
Skips magic URIs like urn:___GLOBAL.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.config.config_loader import get_config
from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def create_missing_graph_entries():
    """Find and create missing graph entries for all spaces."""
    
    # Initialize VitalGraph
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    
    try:
        # Connect to database
        await impl.db_impl.connect()
        logger.info("✅ Connected to database")
        
        # Get space manager and initialize from database
        space_manager = impl.get_space_manager()
        await space_manager.initialize_from_database()
        logger.info(f"✅ Initialized space manager with {len(space_manager)} spaces")
        
        # Get space implementation
        space_impl = impl.db_impl.space_impl
        if not space_impl:
            logger.error("❌ No space implementation available")
            return
        
        # Process each space
        for space_id in space_manager.list_spaces():
            logger.info(f"\n🔍 Processing space: {space_id}")
            
            try:
                # Check what graphs exist in the graph table
                existing_graphs = await space_impl.graphs.list_graphs(space_id)
                existing_graph_uris = {g['graph_uri'] for g in existing_graphs}
                logger.info(f"  📊 Found {len(existing_graphs)} existing graph entries")
                
                # Check what graph URIs exist in rdf_quad table
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
                    
                    logger.info(f"  📊 Found {len(rows)} distinct graph URIs in rdf_quad table")
                    
                    # Find missing graphs and create them
                    missing_count = 0
                    for row in rows:
                        graph_uri = row[0]
                        triple_count = row[1]
                        
                        # Skip magic URIs like the global graph
                        if graph_uri == "urn:___GLOBAL":
                            logger.info(f"  🔮 Skipping magic URI (global graph): {graph_uri} ({triple_count:,} triples)")
                            continue
                            
                        if graph_uri not in existing_graph_uris:
                            logger.info(f"  🔧 Creating missing graph: {graph_uri} ({triple_count:,} triples)")
                            
                            # Create the graph entry
                            success = await space_impl.graphs.create_graph(space_id, graph_uri)
                            if success:
                                # Update the triple count
                                await space_impl.graphs.update_graph_triple_count(
                                    space_id, graph_uri, absolute_count=triple_count
                                )
                                logger.info(f"    ✅ Created graph entry with {triple_count:,} triples")
                                missing_count += 1
                            else:
                                logger.error(f"    ❌ Failed to create graph entry")
                        else:
                            logger.info(f"  ✅ Graph already exists: {graph_uri} ({triple_count:,} triples)")
                    
                    if missing_count > 0:
                        logger.info(f"  🎉 Created {missing_count} graph entries for space {space_id}")
                    else:
                        logger.info(f"  ✅ No missing graph entries for space {space_id}")
                        
            except Exception as e:
                logger.error(f"  ❌ Error processing space {space_id}: {e}")
                continue
        
        logger.info(f"\n🎉 Finished processing all spaces!")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Disconnect from database
        await impl.db_impl.disconnect()
        logger.info("🔌 Disconnected from database")

if __name__ == "__main__":
    asyncio.run(create_missing_graph_entries())
