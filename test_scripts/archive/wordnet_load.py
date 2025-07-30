import logging
import os
import time
from rdflib import Graph, URIRef
from vitalgraph.store.store import VitalGraphSQLStore

PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""           # empty password
PG_DATABASE = "vitalgraphdb"

GRAPH_NAME = "wordnet"
DATA_FILE = "test_data/kgentity_wordnet.nt"


def main():
    # Enable INFO-level logging so you can see VitalGraphSQLStore DDL/DML
    logging.basicConfig(level=logging.INFO)

    # Build the VitalGraphSQLStore connection URI.
    # If PG_PASSWORD is empty, omit the colon:
    DRIVER = "postgresql+psycopg"  # tells VitalGraphSQLStore to use psycopg3 (v3 driver)
    if PG_PASSWORD:
        db_uri = f"{DRIVER}://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    else:
        db_uri = f"{DRIVER}://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"

    # Check if data file exists
    if not os.path.exists(DATA_FILE):
        print(f"Error: Data file '{DATA_FILE}' not found!")
        return

    # Get file size for progress tracking
    file_size = os.path.getsize(DATA_FILE)
    print(f"Data file size: {file_size:,} bytes ({file_size / (1024*1024):.1f} MB)")

    store = VitalGraphSQLStore()

    graph_uri = f"http://vital.ai/graph/{GRAPH_NAME}"

    g = Graph(store=store, identifier=graph_uri)

    try:
        g.open(db_uri)
        print(f"Connected to WordNet graph in PostgreSQL at {db_uri}")
        
        # Check initial triple count
        initial_count = len(g)
        print(f"Initial triple count: {initial_count:,}")
        
        print(f"Loading N-Triples data from {DATA_FILE}...")
        start_time = time.time()
        
        # Parse the N-Triples file with progress logging
        # We'll read the file in chunks to provide progress updates
        lines_processed = 0
        bytes_processed = 0
        
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            # Count total lines first for better progress tracking
            print("Counting total lines in file...")
            total_lines = sum(1 for _ in f)
            print(f"Total lines to process: {total_lines:,}")
            
            # Reset file pointer
            f.seek(0)
            
            # Process in batches for better performance and progress tracking
            batch_size = 10000
            batch_lines = []
            
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line and not line.startswith('#'):  # Skip empty lines and comments
                    batch_lines.append(line)
                    bytes_processed += len(line.encode('utf-8'))
                
                lines_processed += 1
                
                # Process batch when it's full or at end of file
                if len(batch_lines) >= batch_size or line_num == total_lines:
                    if batch_lines:
                        # Create a temporary string with the batch
                        batch_data = '\n'.join(batch_lines)
                        try:
                            # Parse the batch as N-Triples
                            g.parse(data=batch_data, format='nt')
                        except Exception as e:
                            print(f"Error parsing batch at line {line_num}: {e}")
                            # Continue with next batch
                        
                        batch_lines = []
                    
                    # Log progress every 100k lines
                    if lines_processed % 100000 == 0 or line_num == total_lines:
                        elapsed = time.time() - start_time
                        progress = (lines_processed / total_lines) * 100
                        rate = lines_processed / elapsed if elapsed > 0 else 0
                        
                        print(f"Progress: {lines_processed:,}/{total_lines:,} lines "
                              f"({progress:.1f}%) - {rate:.0f} lines/sec - "
                              f"Elapsed: {elapsed:.1f}s")
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Check final triple count
        final_count = len(g)
        triples_added = final_count - initial_count
        
        print(f"\nLoading completed!")
        print(f"Total time: {total_time:.1f} seconds")
        print(f"Lines processed: {lines_processed:,}")
        print(f"Triples added: {triples_added:,}")
        print(f"Final triple count: {final_count:,}")
        print(f"Average rate: {triples_added / total_time:.0f} triples/sec")
        
        g.close()
        
    except Exception as e:
        print(f"Error loading WordNet data: {e}")
        if 'g' in locals():
            g.close()


if __name__ == "__main__":
    main()
