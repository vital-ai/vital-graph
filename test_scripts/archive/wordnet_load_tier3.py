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


def load_ntriples_tier3(graph, file_path, batch_size=50000, disable_indexes=True):
    """
    Ultra-high-performance N-Triples loader using PostgreSQL COPY optimization.
    
    Args:
        graph: RDFLib Graph with VitalGraphSQLStore
        file_path: Path to N-Triples file
        batch_size: Number of triples to process per COPY batch (default: 50000)
        disable_indexes: Whether to disable indexes during loading (default: True)
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
    
    def quad_generator():
        """Generator that yields quads for PostgreSQL COPY processing"""
        nonlocal lines_processed, triples_parsed
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                lines_processed += 1
                
                # Parse the N-Triple line
                triple = parse_ntriple_line(line)
                if triple:
                    subject, predicate, obj = triple
                    # Create quad with graph context
                    quad = (subject, predicate, obj, graph)
                    triples_parsed += 1
                    yield quad
                
                # Log progress every 500k lines
                if lines_processed % 500000 == 0:
                    elapsed = time.time() - start_time
                    progress = (lines_processed / total_lines) * 100
                    rate = lines_processed / elapsed if elapsed > 0 else 0
                    
                    print(f"Parsing progress: {lines_processed:,}/{total_lines:,} lines "
                          f"({progress:.1f}%) - {rate:.0f} lines/sec - "
                          f"Triples: {triples_parsed:,} - Elapsed: {elapsed:.1f}s")
    
    print(f"Loading using PostgreSQL COPY optimization...")
    print(f"Batch size: {batch_size:,} quads per COPY operation")
    print(f"Index management: {'Enabled' if disable_indexes else 'Disabled'}")
    
    # Use the ultra-high-performance PostgreSQL COPY method
    copy_start_time = time.time()
    quads_loaded = graph.store.addN_postgresql_copy(
        quad_generator(), 
        batch_size=batch_size,
        disable_indexes=disable_indexes
    )
    copy_end_time = time.time()
    
    return triples_parsed, quads_loaded, copy_end_time - copy_start_time


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
        
        print(f"\n=== TIER 3 ULTRA-HIGH-PERFORMANCE LOADING ===")
        print(f"Using PostgreSQL COPY optimization with index management")
        
        start_time = time.time()
        
        # Use Tier 3 ultra-high-performance loading
        triples_parsed, quads_loaded, copy_time = load_ntriples_tier3(
            g, DATA_FILE, 
            batch_size=50000,  # Large batch size for PostgreSQL COPY
            disable_indexes=True  # Disable indexes during loading
        )
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Check final triple count
        final_count = len(g)
        actual_triples_added = final_count - initial_count
        
        print(f"\n=== TIER 3 LOADING COMPLETED ===")
        print(f"Total time: {total_time:.1f} seconds")
        print(f"PostgreSQL COPY time: {copy_time:.1f} seconds")
        print(f"Triples parsed: {triples_parsed:,}")
        print(f"Quads loaded via COPY: {quads_loaded:,}")
        print(f"Triples added to database: {actual_triples_added:,}")
        print(f"Final triple count: {final_count:,}")
        print(f"Average parsing rate: {triples_parsed / total_time:.0f} triples/sec")
        print(f"Average COPY rate: {quads_loaded / copy_time:.0f} quads/sec")
        
        # Performance comparison note
        print(f"\n=== PERFORMANCE ANALYSIS ===")
        print(f"This Tier 3 loader uses:")
        print(f"1. PostgreSQL COPY FROM STDIN (50-100x faster than INSERT)")
        print(f"2. Index management (2-5x improvement during loading)")
        print(f"3. Direct N-Triples parsing (2-5x faster than RDFLib)")
        print(f"4. Large batch processing (optimized for PostgreSQL)")
        print(f"Expected total improvement: 500-2,500x over original loader")
        
        g.close()
        
    except Exception as e:
        print(f"Error loading WordNet data: {e}")
        import traceback
        traceback.print_exc()
        if 'g' in locals():
            g.close()


if __name__ == "__main__":
    main()
