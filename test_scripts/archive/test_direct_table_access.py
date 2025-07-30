#!/usr/bin/env python3
"""
Direct table access test to verify edge traversal works when using correct tables
"""

import os
import sys
import time
from sqlalchemy import URL, text, create_engine

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from rdflib import URIRef, Literal

# Database connection parameters
PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

def main():
    print("Direct Table Access Test")
    print("=" * 50)
    
    # Database connection
    db_url = URL.create(
        drivername="postgresql+psycopg",
        username=PG_USER,
        password=PG_PASSWORD or None,
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
    )
    
    engine = create_engine(db_url)
    
    # Use the tables where data actually exists
    literal_table = "kb_bec6803d52_literal_statements"
    asserted_table = "kb_bec6803d52_asserted_statements"
    
    print(f"Using tables:")
    print(f"  Literal: {literal_table}")
    print(f"  Asserted: {asserted_table}")
    
    with engine.connect() as conn:
        # Test 1: Find entities with 'happy' in names (direct SQL)
        print(f"\nTest 1: Direct SQL - Find entities with 'happy' in names")
        
        sql_query = f"""
        SELECT subject, object 
        FROM {literal_table}
        WHERE predicate = 'http://vital.ai/ontology/vital-core#hasName'
          AND object ILIKE '%happy%'
        LIMIT 5
        """
        
        start_time = time.time()
        try:
            result = conn.execute(text(sql_query))
            rows = list(result)
            elapsed = time.time() - start_time
            
            print(f"✓ Found {len(rows)} entities with 'happy' in names:")
            entities_found = []
            for i, row in enumerate(rows):
                entity = row[0]
                name = row[1]
                print(f"  {i+1}: {name}")
                print(f"      URI: {entity}")
                entities_found.append(entity)
            print(f"Query time: {elapsed:.3f} seconds")
            
        except Exception as e:
            print(f"✗ Error in direct SQL text search: {e}")
            return
        
        # Test 2: Find edges for the first entity (direct SQL)
        if entities_found:
            first_entity = entities_found[0]
            print(f"\nTest 2: Direct SQL - Find edges for first entity")
            print(f"Entity: {first_entity}")
            
            edge_sql = f"""
            SELECT s.subject as edge, s.object as source, d.object as destination
            FROM {asserted_table} s
            JOIN {asserted_table} d ON s.subject = d.subject
            WHERE s.predicate = 'http://vital.ai/ontology/vital-core#vital__hasEdgeSource'
              AND d.predicate = 'http://vital.ai/ontology/vital-core#vital__hasEdgeDestination'
              AND s.object = :entity
            LIMIT 10
            """
            
            start_time = time.time()
            try:
                result = conn.execute(text(edge_sql), {"entity": first_entity})
                edge_rows = list(result)
                elapsed = time.time() - start_time
                
                if edge_rows:
                    print(f"✓ Found {len(edge_rows)} edges for this entity:")
                    for i, row in enumerate(edge_rows):
                        edge = row[0]
                        source = row[1]
                        dest = row[2]
                        print(f"  Edge {i+1}: {edge}")
                        print(f"    {source} -> {dest}")
                        
                        # Try to get destination name
                        name_sql = f"""
                        SELECT object FROM {literal_table}
                        WHERE subject = :dest 
                          AND predicate = 'http://vital.ai/ontology/vital-core#hasName'
                        LIMIT 1
                        """
                        
                        try:
                            name_result = conn.execute(text(name_sql), {"dest": dest})
                            name_row = name_result.fetchone()
                            if name_row:
                                print(f"    Dest name: {name_row[0]}")
                        except:
                            pass
                else:
                    print("✗ No edges found for this entity")
                    
                print(f"Query time: {elapsed:.3f} seconds")
                
            except Exception as e:
                print(f"✗ Error in direct SQL edge query: {e}")
        
        # Test 3: General edge verification (direct SQL)
        print(f"\nTest 3: Direct SQL - General edge verification")
        
        general_edge_sql = f"""
        SELECT s.subject as edge, s.object as source, d.object as destination
        FROM {asserted_table} s
        JOIN {asserted_table} d ON s.subject = d.subject
        WHERE s.predicate = 'http://vital.ai/ontology/vital-core#vital__hasEdgeSource'
          AND d.predicate = 'http://vital.ai/ontology/vital-core#vital__hasEdgeDestination'
        LIMIT 5
        """
        
        start_time = time.time()
        try:
            result = conn.execute(text(general_edge_sql))
            general_rows = list(result)
            elapsed = time.time() - start_time
            
            if general_rows:
                print(f"✓ Found {len(general_rows)} edges in database:")
                for i, row in enumerate(general_rows):
                    edge = row[0]
                    source = row[1]
                    dest = row[2]
                    print(f"  Edge {i+1}: {edge}")
                    print(f"    {source} -> {dest}")
            else:
                print("✗ No edges found in database")
                
            print(f"Query time: {elapsed:.3f} seconds")
            
        except Exception as e:
            print(f"✗ Error in general edge SQL: {e}")
    
    print(f"\n" + "=" * 50)
    print("Direct table access test completed!")
    
    if 'edge_rows' in locals() and edge_rows:
        print("✅ SUCCESS: Edge traversal works with direct SQL!")
        print("   The issue is definitely with SPARQL-to-SQL translation")
        print("   when using the wrong graph identifier/table set.")
    elif 'general_rows' in locals() and general_rows:
        print("✅ PARTIAL SUCCESS: Edges exist but specific entity has no edges")
        print("   The SPARQL layer needs to use the correct tables.")
    else:
        print("❌ No edges found - further investigation needed.")

if __name__ == "__main__":
    main()
