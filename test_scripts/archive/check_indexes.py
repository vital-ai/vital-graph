#!/usr/bin/env python3
"""
Script to analyze current table structure and indexes for PostgreSQL regex optimization planning.
"""

from sqlalchemy import create_engine, text

# Database connection parameters
PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_USER = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

def create_db_engine():
    """Create SQLAlchemy engine for PostgreSQL database"""
    DRIVER = "postgresql+psycopg"
    if PG_PASSWORD:
        db_uri = f"{DRIVER}://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    else:
        db_uri = f"{DRIVER}://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    
    return create_engine(db_uri)

def analyze_table_structure():
    """Analyze current table structure and indexes for WordNet data"""
    print("=== CURRENT TABLE STRUCTURE & INDEX ANALYSIS ===")
    print(f"Database: {PG_DATABASE} on {PG_HOST}:{PG_PORT}")
    
    # Focus on the main WordNet tables (kb_bec6803d52 - "hardcoded" identifier)
    table_prefix = "kb_bec6803d52"
    table_types = ["asserted_statements", "literal_statements", "type_statements", "quoted_statements"]
    
    engine = create_db_engine()
    
    with engine.begin() as conn:
        for table_type in table_types:
            table_name = f"{table_prefix}_{table_type}"
            print(f"\n{'='*60}")
            print(f"TABLE: {table_name}")
            print(f"{'='*60}")
            
            # Get table columns
            try:
                result = conn.execute(text("""
                    SELECT column_name, data_type, is_nullable, character_maximum_length
                    FROM information_schema.columns 
                    WHERE table_name = :table_name
                    ORDER BY ordinal_position;
                """), {"table_name": table_name})
                
                columns = result.fetchall()
                print("\nCOLUMNS:")
                for col_name, data_type, nullable, max_length in columns:
                    length_info = f"({max_length})" if max_length else ""
                    print(f"  {col_name:<20} {data_type}{length_info:<15} NULL: {nullable}")
                
            except Exception as e:
                print(f"  Error getting columns: {e}")
                continue
            
            # Get indexes
            try:
                result = conn.execute(text("""
                    SELECT 
                        indexname, 
                        indexdef,
                        CASE 
                            WHEN indexdef LIKE '%USING gin%' THEN 'GIN'
                            WHEN indexdef LIKE '%USING gist%' THEN 'GiST'
                            WHEN indexdef LIKE '%USING btree%' THEN 'B-tree'
                            WHEN indexdef LIKE '%USING hash%' THEN 'Hash'
                            ELSE 'Unknown'
                        END as index_type
                    FROM pg_indexes 
                    WHERE tablename = :table_name
                    ORDER BY indexname;
                """), {"table_name": table_name})
                
                indexes = result.fetchall()
                print(f"\nINDEXES ({len(indexes)}):")
                if indexes:
                    for idx_name, idx_def, idx_type in indexes:
                        print(f"  {idx_name} ({idx_type})")
                        print(f"    {idx_def}")
                        print()
                else:
                    print("  No indexes found")
                
            except Exception as e:
                print(f"  Error getting indexes: {e}")
            
            # Get row count for context
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = result.fetchone()[0]
                print(f"ROW COUNT: {count:,}")
            except Exception as e:
                print(f"  Error getting row count: {e}")

def check_text_search_extensions():
    """Check if PostgreSQL text search extensions are available"""
    print(f"\n{'='*60}")
    print("POSTGRESQL TEXT SEARCH EXTENSIONS")
    print(f"{'='*60}")
    
    engine = create_db_engine()
    
    with engine.begin() as conn:
        # Check for pg_trgm extension
        try:
            result = conn.execute(text("""
                SELECT extname, extversion, extrelocatable
                FROM pg_extension 
                WHERE extname IN ('pg_trgm', 'btree_gin', 'btree_gist');
            """))
            
            extensions = result.fetchall()
            print("\nINSTALLED EXTENSIONS:")
            if extensions:
                for ext_name, ext_version, relocatable in extensions:
                    print(f"  {ext_name}: version {ext_version} (relocatable: {relocatable})")
            else:
                print("  No relevant text search extensions found")
                
        except Exception as e:
            print(f"  Error checking extensions: {e}")
        
        # Check available extensions
        try:
            result = conn.execute(text("""
                SELECT name, default_version, comment
                FROM pg_available_extensions 
                WHERE name IN ('pg_trgm', 'btree_gin', 'btree_gist')
                ORDER BY name;
            """))
            
            available = result.fetchall()
            print(f"\nAVAILABLE EXTENSIONS:")
            if available:
                for ext_name, default_ver, comment in available:
                    print(f"  {ext_name}: {default_ver}")
                    print(f"    {comment}")
            else:
                print("  No relevant extensions available")
                
        except Exception as e:
            print(f"  Error checking available extensions: {e}")

def main():
    """Main analysis function"""
    try:
        analyze_table_structure()
        check_text_search_extensions()
        
        print(f"\n{'='*60}")
        print("ANALYSIS COMPLETE")
        print(f"{'='*60}")
        print("\nKey findings for PostgreSQL regex optimization:")
        print("1. Check which columns need regex search support")
        print("2. Identify missing indexes for text search performance")
        print("3. Verify pg_trgm extension availability for trigram indexes")
        print("4. Plan index strategy for subject/predicate/object/context regex queries")
        
    except Exception as e:
        print(f"Error during analysis: {e}")

if __name__ == "__main__":
    main()
