import logging
import time
from sqlalchemy import text
from vitalgraph.store.store import VitalGraphSQLStore

PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""           # empty password
PG_DATABASE = "vitalgraphdb"

GRAPH_NAME = "wordnet"


def main():
    # Enable INFO-level logging
    logging.basicConfig(level=logging.INFO)

    # Build the VitalGraphSQLStore connection URI
    DRIVER = "postgresql+psycopg"
    if PG_PASSWORD:
        db_uri = f"{DRIVER}://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    else:
        db_uri = f"{DRIVER}://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"

    store = VitalGraphSQLStore()
    
    # We need to get the table names for the wordnet graph
    # The interned_id is based on the store identifier
    interned_id = store._interned_id
    
    print(f"Adding pg_trgm indexes for WordNet graph (interned_id: {interned_id})")
    print(f"Database URI: {db_uri}")
    
    # Connect directly to the database
    import sqlalchemy
    engine = sqlalchemy.create_engine(db_uri)
    
    # First, enable extension in a transaction
    with engine.begin() as connection:
        try:
            # Enable pg_trgm extension if not already enabled
            print("Enabling pg_trgm extension...")
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
            
            # Get table names
            asserted_table = f"{interned_id}_asserted_statements"
            literal_table = f"{interned_id}_literal_statements"
            type_table = f"{interned_id}_type_statements"
            
            print(f"Table names:")
            print(f"  Asserted: {asserted_table}")
            print(f"  Literal: {literal_table}")
            print(f"  Type: {type_table}")
            
            # Check current table sizes
            for table_name in [asserted_table, literal_table, type_table]:
                result = connection.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = result.scalar()
                print(f"  {table_name}: {count:,} rows")
        
        except Exception as e:
            print(f"Error during setup: {e}")
            raise
    
    # Now create indexes outside of transaction (required for CONCURRENTLY)
    print("\nAdding pg_trgm GIN indexes for general text search optimization...")
    print("These indexes will speed up ALL text search operations (CONTAINS, STRSTARTS, REGEX, etc.)")
    print("Note: Creating indexes CONCURRENTLY to avoid blocking database operations...")
    
    # Get table names again
    asserted_table = f"{interned_id}_asserted_statements"
    literal_table = f"{interned_id}_literal_statements"
    type_table = f"{interned_id}_type_statements"
    
    try:
        # Use direct psycopg connection for CONCURRENTLY operations
        # SQLAlchemy doesn't handle autocommit properly for this case
        import psycopg
        
        # Parse the database URI to get connection parameters
        from urllib.parse import urlparse
        parsed = urlparse(db_uri)
        
        # Connect directly with psycopg in autocommit mode
        conn = psycopg.connect(
            host=parsed.hostname,
            port=parsed.port,
            dbname=parsed.path[1:],  # Remove leading slash
            user=parsed.username,
            password=parsed.password,
            autocommit=True
        )
        
        try:
            # Index 1: All objects in asserted_statements (covers all string/text values)
            index_name_1 = f"idx_{interned_id}_asserted_objects_trgm"
            print(f"Creating index: {index_name_1}")
            start_time = time.time()
            
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name_1}
                    ON {asserted_table} USING gin (object gin_trgm_ops)
                """)
            
            elapsed = time.time() - start_time
            print(f"  Created in {elapsed:.1f} seconds")
            
            # Index 2: All subjects in asserted_statements (for subject text search)
            index_name_2 = f"idx_{interned_id}_asserted_subjects_trgm"
            print(f"Creating index: {index_name_2}")
            start_time = time.time()
            
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name_2}
                    ON {asserted_table} USING gin (subject gin_trgm_ops)
                """)
            
            elapsed = time.time() - start_time
            print(f"  Created in {elapsed:.1f} seconds")
            
            # Index 3: All objects in literal_statements
            index_name_3 = f"idx_{interned_id}_literal_objects_trgm"
            print(f"Creating index: {index_name_3}")
            start_time = time.time()
            
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name_3}
                    ON {literal_table} USING gin (object gin_trgm_ops)
                """)
            
            elapsed = time.time() - start_time
            print(f"  Created in {elapsed:.1f} seconds")
            
            # Index 4: All subjects in literal_statements
            index_name_4 = f"idx_{interned_id}_literal_subjects_trgm"
            print(f"Creating index: {index_name_4}")
            start_time = time.time()
            
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name_4}
                    ON {literal_table} USING gin (subject gin_trgm_ops)
                """)
            
            elapsed = time.time() - start_time
            print(f"  Created in {elapsed:.1f} seconds")
            
            # Index 5: All members in type_statements
            index_name_5 = f"idx_{interned_id}_type_members_trgm"
            print(f"Creating index: {index_name_5}")
            start_time = time.time()
            
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name_5}
                    ON {type_table} USING gin (member gin_trgm_ops)
                """)
            
            elapsed = time.time() - start_time
            print(f"  Created in {elapsed:.1f} seconds")
            
            # Index 6: All classes in type_statements
            index_name_6 = f"idx_{interned_id}_type_classes_trgm"
            print(f"Creating index: {index_name_6}")
            start_time = time.time()
            
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name_6}
                    ON {type_table} USING gin (klass gin_trgm_ops)
                """)
            
            elapsed = time.time() - start_time
            print(f"  Created in {elapsed:.1f} seconds")
            
            print("\n" + "="*60)
            print("SUCCESS: All pg_trgm indexes created!")
            print("="*60)
            
            # Show index information
            print("\nIndex information:")
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT 
                        schemaname,
                        tablename,
                        indexname,
                        indexdef
                    FROM pg_indexes 
                    WHERE tablename IN ('{asserted_table}', '{literal_table}', '{type_table}')
                    AND indexname LIKE '%trgm%'
                    ORDER BY tablename, indexname
                """)
                
                for row in cursor.fetchall():
                    print(f"\nTable: {row[1]}")
                    print(f"Index: {row[2]}")
                    print(f"Definition: {row[3]}")
            
            print(f"\nNow your SPARQL queries with CONTAINS, STRSTARTS, and regex")
            print(f"filters should be much faster!")
            
        finally:
            # Always close the connection
            conn.close()
            
    except Exception as e:
        print(f"Error creating indexes: {e}")
        raise


if __name__ == "__main__":
    main()
