#!/usr/bin/env python3
"""
Inspect the database directly to find where edge triples are stored
"""

import os
import sys
from sqlalchemy import URL, create_engine, text

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.store.store import VitalGraphSQLStore

# Database connection parameters
PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

def main():
    # Build database connection
    db_url = URL.create(
        drivername="postgresql+psycopg",
        username=PG_USER,
        password=PG_PASSWORD or None,
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
    )
    
    engine = create_engine(db_url)
    
    print("Inspecting WordNet database for edge triples...")
    print("=" * 60)
    
    with engine.connect() as conn:
        # First, list all tables in the database
        print("\nAll tables in database:")
        try:
            result = conn.execute(text("""
                SELECT tablename 
                FROM pg_tables 
                WHERE schemaname = 'public' 
                ORDER BY tablename
            """))
            
            all_tables = [row[0] for row in result]
            for table in all_tables:
                print(f"  {table}")
                
            # Find tables that might contain wordnet data
            wordnet_tables = [t for t in all_tables if 'wordnet' in t.lower()]
            print(f"\nWordNet-related tables: {wordnet_tables}")
            
            if not wordnet_tables:
                print("No WordNet tables found! Checking all tables for edge predicates...")
                wordnet_tables = all_tables
                
        except Exception as e:
            print(f"Error listing tables: {e}")
            return
            
        # Check wordnet tables for edge predicates
        edge_predicates = [
            'http://vital.ai/ontology/vital-core#vital__hasEdgeSource',
            'http://vital.ai/ontology/vital-core#vital__hasEdgeDestination'
        ]
        
        # Focus on the actual RDF tables with predicate columns
        rdf_tables = [
            'kb_5e9e5feadf_asserted_statements',
            'kb_5e9e5feadf_literal_statements', 
            'kb_5e9e5feadf_type_statements',
            'kb_bec6803d52_asserted_statements',
            'kb_bec6803d52_literal_statements',
            'kb_bec6803d52_type_statements'
        ]
        
        for table in rdf_tables:
            print(f"\nChecking table: {table}")
            
            try:
                # Check if table has the expected columns
                result = conn.execute(text(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = :table_name
                    ORDER BY ordinal_position
                """), {"table_name": table})
                
                columns = [row[0] for row in result]
                print(f"  Columns: {columns}")
                
                if 'predicate' in columns:
                    # Get row count
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    total_count = result.scalar()
                    print(f"  Total rows: {total_count:,}")
                    
                    # Check for edge predicates
                    for predicate in edge_predicates:
                        try:
                            result = conn.execute(text(f"""
                                SELECT COUNT(*) FROM {table} 
                                WHERE predicate = :pred
                            """), {"pred": predicate})
                            edge_count = result.scalar()
                            if edge_count > 0:
                                print(f"  ✓ {predicate}: {edge_count} rows")
                                
                                # Show sample rows
                                result = conn.execute(text(f"""
                                    SELECT subject, predicate, object 
                                    FROM {table} 
                                    WHERE predicate = :pred 
                                    LIMIT 3
                                """), {"pred": predicate})
                                print(f"    Sample rows:")
                                for row in result:
                                    print(f"      {row.subject} -> {row.object}")
                            
                        except Exception as e:
                            print(f"    Error checking {predicate}: {e}")
                    
                    # Check for any edge-related predicates
                    try:
                        result = conn.execute(text(f"""
                            SELECT DISTINCT predicate, COUNT(*) as count
                            FROM {table} 
                            WHERE predicate LIKE '%Edge%' OR predicate LIKE '%hasEdge%'
                            GROUP BY predicate
                            ORDER BY count DESC
                        """))
                        
                        edge_predicates_found = list(result)
                        if edge_predicates_found:
                            print(f"  Edge-related predicates in {table}:")
                            for pred, count in edge_predicates_found:
                                print(f"    {pred}: {count} rows")
                                
                    except Exception as e:
                        print(f"  Error searching for edge predicates: {e}")
                        
                else:
                    print(f"  No 'predicate' column found")
                    
            except Exception as e:
                print(f"  Error accessing table {table}: {e}")

if __name__ == "__main__":
    main()
