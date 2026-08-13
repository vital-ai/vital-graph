#!/usr/bin/env python3
"""
Simple SQL diagnostic to examine WordNet data structure directly.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import psycopg
from psycopg.rows import dict_row
from vitalgraph.config.config_loader import get_config

def diagnose_wordnet_data():
    """Examine the actual WordNet data structure using direct SQL."""
    
    # Load the actual VitalGraph config
    config = get_config('vitalgraphdb_config/vitalgraphdb-config.yaml')
    db_config = config.database
    
    # Build connection string from config
    conn_str = f"host={db_config.host} port={db_config.port} dbname={db_config.database} user={db_config.username}"
    if db_config.password:
        conn_str += f" password={db_config.password}"
    
    try:
        print("=" * 80)
        print("WORDNET DATA STRUCTURE DIAGNOSIS")
        print("=" * 80)
        
        with psycopg.connect(conn_str, row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                
                # 1. Check table structure
                print("1. TABLE STRUCTURE:")
                print("-" * 40)
                
                cursor.execute("""
                    SELECT table_name, column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name LIKE '%wordnet%' 
                    ORDER BY table_name, ordinal_position
                """)
                
                current_table = None
                for row in cursor.fetchall():
                    if row['table_name'] != current_table:
                        current_table = row['table_name']
                        print(f"\nTable: {current_table}")
                    print(f"  - {row['column_name']}: {row['data_type']}")
                
                print()
                
                # 2. Check data counts
                print("2. DATA COUNTS:")
                print("-" * 40)
                
                # Count terms
                cursor.execute("SELECT COUNT(*) as count FROM vitalgraph1__wordnet_space__term_unlogged")
                term_count = cursor.fetchone()['count']
                print(f"Total terms: {term_count:,}")
                
                # Count quads
                cursor.execute("SELECT COUNT(*) as count FROM vitalgraph1__wordnet_space__rdf_quad_unlogged")
                quad_count = cursor.fetchone()['count']
                print(f"Total quads: {quad_count:,}")
                
                print()
                
                # 3. Sample predicates
                print("3. SAMPLE PREDICATES:")
                print("-" * 40)
                
                cursor.execute("""
                    SELECT DISTINCT t.term_text as predicate, COUNT(*) as usage_count
                    FROM vitalgraph1__wordnet_space__rdf_quad_unlogged q
                    JOIN vitalgraph1__wordnet_space__term_unlogged t ON q.predicate_uuid = t.term_uuid
                    WHERE t.term_type = 'U'
                    GROUP BY t.term_text
                    ORDER BY usage_count DESC
                    LIMIT 15
                """)
                
                predicates = cursor.fetchall()
                for i, pred in enumerate(predicates, 1):
                    print(f"  {i:2d}. {pred['predicate']} ({pred['usage_count']:,} uses)")
                
                print()
                
                # 4. Sample subjects (entities)
                print("4. SAMPLE SUBJECTS (ENTITIES):")
                print("-" * 40)
                
                cursor.execute("""
                    SELECT DISTINCT t.term_text as subject
                    FROM vitalgraph1__wordnet_space__rdf_quad_unlogged q
                    JOIN vitalgraph1__wordnet_space__term_unlogged t ON q.subject_uuid = t.term_uuid
                    WHERE t.term_type = 'U'
                    LIMIT 10
                """)
                
                subjects = cursor.fetchall()
                for i, subj in enumerate(subjects, 1):
                    subj_text = subj['subject']
                    if len(subj_text) > 80:
                        subj_text = subj_text[:77] + "..."
                    print(f"  {i:2d}. {subj_text}")
                
                print()
                
                # 5. Check for hasName predicate specifically
                print("5. CHECKING FOR hasName PREDICATE:")
                print("-" * 40)
                
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM vitalgraph1__wordnet_space__rdf_quad_unlogged q
                    JOIN vitalgraph1__wordnet_space__term_unlogged t ON q.predicate_uuid = t.term_uuid
                    WHERE t.term_text = 'http://vital.ai/ontology/vital-core#hasName'
                """)
                
                hasname_count = cursor.fetchone()['count']
                print(f"Triples with hasName predicate: {hasname_count:,}")
                
                if hasname_count > 0:
                    cursor.execute("""
                        SELECT s.term_text as subject, o.term_text as name
                        FROM vitalgraph1__wordnet_space__rdf_quad_unlogged q
                        JOIN vitalgraph1__wordnet_space__term_unlogged p ON q.predicate_uuid = p.term_uuid
                        JOIN vitalgraph1__wordnet_space__term_unlogged s ON q.subject_uuid = s.term_uuid
                        JOIN vitalgraph1__wordnet_space__term_unlogged o ON q.object_uuid = o.term_uuid
                        WHERE p.term_text = 'http://vital.ai/ontology/vital-core#hasName'
                        LIMIT 5
                    """)
                    
                    hasname_samples = cursor.fetchall()
                    print("Sample hasName triples:")
                    for i, sample in enumerate(hasname_samples, 1):
                        subj = sample['subject'][:50] + "..." if len(sample['subject']) > 50 else sample['subject']
                        name = sample['name'][:30] + "..." if len(sample['name']) > 30 else sample['name']
                        print(f"  {i}. {subj} -> {name}")
                
    except Exception as e:
        print(f"Error in diagnosis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    diagnose_wordnet_data()
