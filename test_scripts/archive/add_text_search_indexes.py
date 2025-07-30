#!/usr/bin/env python3
"""
Add PostgreSQL text search indexes (GIN/pg_trgm) for optimal regex and text search performance
"""

import sys
import os
import psycopg
from sqlalchemy import create_engine, text

# Database connection parameters
PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_USER = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

# Table prefix for WordNet data
TABLE_PREFIX = "kb_bec6803d52"

def add_text_search_indexes():
    """Add GIN/pg_trgm indexes for text search optimization"""
    print("=== ADDING POSTGRESQL TEXT SEARCH INDEXES ===")
    print(f"Database: {PG_DATABASE}")
    print(f"Table prefix: {TABLE_PREFIX}")
    
    # Connect to PostgreSQL
    if PG_PASSWORD:
        db_uri = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    else:
        db_uri = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    
    try:
        engine = create_engine(db_uri)
        
        with engine.connect() as conn:
            # Verify pg_trgm extension is available
            print("\n--- Checking pg_trgm extension ---")
            result = conn.execute(text("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'"))
            if result.fetchone():
                print("✅ pg_trgm extension is installed")
            else:
                print("❌ pg_trgm extension not found - installing...")
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                conn.commit()
                print("✅ pg_trgm extension installed")
            
            # Define indexes to create
            indexes_to_create = [
                # Literal statements - object column (most important for text search)
                {
                    "table": f"{TABLE_PREFIX}_literal_statements",
                    "column": "object",
                    "index_name": f"idx_{TABLE_PREFIX}_literal_object_gin_trgm",
                    "index_type": "GIN",
                    "operator_class": "gin_trgm_ops"
                },
                
                # Asserted statements - object column (for URI text search)
                {
                    "table": f"{TABLE_PREFIX}_asserted_statements", 
                    "column": "object",
                    "index_name": f"idx_{TABLE_PREFIX}_asserted_object_gin_trgm",
                    "index_type": "GIN",
                    "operator_class": "gin_trgm_ops"
                },
                
                # Subject columns for all main tables
                {
                    "table": f"{TABLE_PREFIX}_literal_statements",
                    "column": "subject", 
                    "index_name": f"idx_{TABLE_PREFIX}_literal_subject_gin_trgm",
                    "index_type": "GIN",
                    "operator_class": "gin_trgm_ops"
                },
                
                {
                    "table": f"{TABLE_PREFIX}_asserted_statements",
                    "column": "subject",
                    "index_name": f"idx_{TABLE_PREFIX}_asserted_subject_gin_trgm", 
                    "index_type": "GIN",
                    "operator_class": "gin_trgm_ops"
                },
                
                # Predicate columns for predicate-based text search
                {
                    "table": f"{TABLE_PREFIX}_literal_statements",
                    "column": "predicate",
                    "index_name": f"idx_{TABLE_PREFIX}_literal_predicate_gin_trgm",
                    "index_type": "GIN", 
                    "operator_class": "gin_trgm_ops"
                },
                
                {
                    "table": f"{TABLE_PREFIX}_asserted_statements",
                    "column": "predicate",
                    "index_name": f"idx_{TABLE_PREFIX}_asserted_predicate_gin_trgm",
                    "index_type": "GIN",
                    "operator_class": "gin_trgm_ops"
                }
            ]
            
            print(f"\n--- Creating {len(indexes_to_create)} text search indexes ---")
            
            for idx_config in indexes_to_create:
                table = idx_config["table"]
                column = idx_config["column"] 
                index_name = idx_config["index_name"]
                index_type = idx_config["index_type"]
                operator_class = idx_config["operator_class"]
                
                print(f"\nCreating index: {index_name}")
                print(f"  Table: {table}")
                print(f"  Column: {column}")
                print(f"  Type: {index_type} using {operator_class}")
                
                # Check if index already exists
                check_sql = text("""
                    SELECT indexname FROM pg_indexes 
                    WHERE tablename = :table AND indexname = :index_name
                """)
                
                result = conn.execute(check_sql, {"table": table, "index_name": index_name})
                if result.fetchone():
                    print(f"  ⚠️  Index {index_name} already exists - skipping")
                    continue
                
                # Create the index
                create_sql = text(f"""
                    CREATE INDEX CONCURRENTLY {index_name} 
                    ON {table} 
                    USING {index_type} ({column} {operator_class})
                """)
                
                try:
                    conn.execute(create_sql)
                    conn.commit()
                    print(f"  ✅ Index {index_name} created successfully")
                except Exception as e:
                    print(f"  ❌ Error creating index {index_name}: {e}")
                    conn.rollback()
            
            # Verify created indexes
            print(f"\n--- Verifying text search indexes ---")
            verify_sql = text(f"""
                SELECT 
                    schemaname,
                    tablename, 
                    indexname,
                    indexdef
                FROM pg_indexes 
                WHERE tablename LIKE '{TABLE_PREFIX}_%' 
                AND indexname LIKE '%gin_trgm%'
                ORDER BY tablename, indexname
            """)
            
            result = conn.execute(verify_sql)
            indexes = result.fetchall()
            
            print(f"Found {len(indexes)} text search indexes:")
            for idx in indexes:
                print(f"  • {idx.indexname} on {idx.tablename}")
            
            # Show index sizes
            print(f"\n--- Index size analysis ---")
            size_sql = text(f"""
                SELECT 
                    schemaname,
                    tablename,
                    indexname,
                    pg_size_pretty(pg_relation_size(indexname::regclass)) as index_size
                FROM pg_indexes 
                WHERE tablename LIKE '{TABLE_PREFIX}_%'
                AND indexname LIKE '%gin_trgm%'
                ORDER BY pg_relation_size(indexname::regclass) DESC
            """)
            
            result = conn.execute(size_sql)
            sizes = result.fetchall()
            
            for size_info in sizes:
                print(f"  • {size_info.indexname}: {size_info.index_size}")
        
        print(f"\n✅ Text search index creation completed")
        
    except Exception as e:
        print(f"❌ Error during index creation: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    add_text_search_indexes()
