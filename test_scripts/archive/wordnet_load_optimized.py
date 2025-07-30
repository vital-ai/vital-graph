import logging
import os
import time
from rdflib import Graph, URIRef, Literal, BNode
from rdflib.namespace import XSD
from vitalgraph.store.store import VitalGraphSQLStore

PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""           # empty password
PG_DATABASE = "vitalgraphdb"

GRAPH_NAME = "wordnet"
DATA_FILE = "test_data/kgentity_wordnet.nt"

_logger = None


def parse_ntriple_line(line):
    """
    Fast N-Triple line parser that avoids RDFLib overhead.
    
    Returns (subject, predicate, object) tuple or None if line should be skipped.
    """
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    
    try:
        # Simple N-Triple parsing - assumes well-formed input
        # Format: <subject> <predicate> <object> .
        parts = line.rstrip(' .').split(' ', 2)
        if len(parts) != 3:
            return None
            
        subject_str, predicate_str, object_str = parts
        
        # Parse subject (always URI in N-Triples)
        if subject_str.startswith('<') and subject_str.endswith('>'):
            subject = URIRef(subject_str[1:-1])
        else:
            return None  # Invalid subject
            
        # Parse predicate (always URI in N-Triples)
        if predicate_str.startswith('<') and predicate_str.endswith('>'):
            predicate = URIRef(predicate_str[1:-1])
        else:
            return None  # Invalid predicate
            
        # Parse object (can be URI, literal, or blank node)
        if object_str.startswith('<') and object_str.endswith('>'):
            # URI object
            obj = URIRef(object_str[1:-1])
        elif object_str.startswith('"'):
            # Literal object
            if object_str.endswith('"'):
                # Simple literal
                obj = Literal(object_str[1:-1])
            elif '^^' in object_str:
                # Typed literal
                literal_part, type_part = object_str.rsplit('^^', 1)
                literal_value = literal_part[1:-1]  # Remove quotes
                if type_part.startswith('<') and type_part.endswith('>'):
                    datatype = URIRef(type_part[1:-1])
                    obj = Literal(literal_value, datatype=datatype)
                else:
                    obj = Literal(literal_value)
            elif '@' in object_str:
                # Language-tagged literal
                literal_part, lang_part = object_str.rsplit('@', 1)
                literal_value = literal_part[1:-1]  # Remove quotes
                obj = Literal(literal_value, lang=lang_part)
            else:
                # Fallback for complex literals
                obj = Literal(object_str[1:-1])
        elif object_str.startswith('_:'):
            # Blank node
            obj = BNode(object_str[2:])
        else:
            return None  # Invalid object
            
        return (subject, predicate, obj)
        
    except Exception as e:
        if _logger:
            _logger.warning(f"Failed to parse line: {line[:100]}... Error: {e}")
        return None


def load_ntriples_optimized(graph, file_path, batch_size=10000):
    """
    Optimized N-Triples loader that bypasses RDFLib parsing.
    
    Args:
        graph: RDFLib Graph with VitalGraphSQLStore
        file_path: Path to N-Triples file
        batch_size: Number of triples to process per batch
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Data file '{file_path}' not found!")
    
    file_size = os.path.getsize(file_path)
    print(f"Data file size: {file_size:,} bytes ({file_size / (1024*1024):.1f} MB)")
    
    # Count total lines for progress tracking
    print("Counting total lines in file...")
    with open(file_path, 'r', encoding='utf-8') as f:
        total_lines = sum(1 for _ in f)
    print(f"Total lines to process: {total_lines:,}")
    
    start_time = time.time()
    lines_processed = 0
    triples_parsed = 0
    batch_quads = []
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            lines_processed += 1
            
            # Parse the N-Triple line
            triple = parse_ntriple_line(line)
            if triple:
                subject, predicate, obj = triple
                # Create quad with graph context (use graph object, not graph.identifier)
                quad = (subject, predicate, obj, graph)
                batch_quads.append(quad)
                triples_parsed += 1
            
            # Process batch when full or at end of file
            if len(batch_quads) >= batch_size or line_num == total_lines:
                if batch_quads:
                    # Use optimized addN method
                    graph.store.addN(batch_quads)
                    batch_quads = []
                
                # Log progress every 100k lines
                if lines_processed % 100000 == 0 or line_num == total_lines:
                    elapsed = time.time() - start_time
                    progress = (lines_processed / total_lines) * 100
                    rate = lines_processed / elapsed if elapsed > 0 else 0
                    
                    print(f"Progress: {lines_processed:,}/{total_lines:,} lines "
                          f"({progress:.1f}%) - {rate:.0f} lines/sec - "
                          f"Triples: {triples_parsed:,} - Elapsed: {elapsed:.1f}s")
    
    return triples_parsed


def main():
    # Enable INFO-level logging
    logging.basicConfig(level=logging.INFO)
    global _logger
    _logger = logging.getLogger(__name__)

    # Build the VitalGraphSQLStore connection URI
    DRIVER = "postgresql+psycopg"
    if PG_PASSWORD:
        db_uri = f"{DRIVER}://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    else:
        db_uri = f"{DRIVER}://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"

    store = VitalGraphSQLStore()
    graph_uri = f"http://vital.ai/graph/{GRAPH_NAME}"
    g = Graph(store=store, identifier=graph_uri)

    try:
        g.open(db_uri)
        print(f"Connected to WordNet graph in PostgreSQL at {db_uri}")
        
        # Check initial triple count
        initial_count = len(g)
        print(f"Initial triple count: {initial_count:,}")
        
        print(f"Loading N-Triples data from {DATA_FILE} using optimized parser...")
        start_time = time.time()
        
        # Use optimized loading
        triples_added = load_ntriples_optimized(g, DATA_FILE, batch_size=10000)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Check final triple count
        final_count = len(g)
        actual_triples_added = final_count - initial_count
        
        print(f"\nOptimized loading completed!")
        print(f"Total time: {total_time:.1f} seconds")
        print(f"Triples parsed: {triples_added:,}")
        print(f"Triples added to database: {actual_triples_added:,}")
        print(f"Final triple count: {final_count:,}")
        print(f"Average rate: {triples_added / total_time:.0f} triples/sec")
        
        # Performance comparison note
        print(f"\n--- PERFORMANCE COMPARISON ---")
        print(f"This optimized loader bypasses RDFLib parsing overhead")
        print(f"and uses bulk SQL operations for maximum performance.")
        print(f"Compare with original wordnet_load.py for performance gains.")
        
        g.close()
        
    except Exception as e:
        print(f"Error loading WordNet data: {e}")
        if 'g' in locals():
            g.close()


if __name__ == "__main__":
    main()
