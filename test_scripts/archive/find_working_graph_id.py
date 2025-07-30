#!/usr/bin/env python3
"""
Systematically find the graph identifier that produces kb_bec6803d52
"""

import os
import sys
import hashlib
from sqlalchemy import URL

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.store.store import VitalGraphSQLStore
from rdflib import URIRef

# Database connection parameters
PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

def generate_interned_id(identifier):
    """Generate interned ID the same way VitalGraphSQLStore does"""
    identifier_hash = hashlib.sha1(identifier.encode("utf8")).hexdigest()[:10]
    return f"kb_{identifier_hash}"

def test_graph_identifier(identifier, db_url):
    """Test if a graph identifier produces the target interned ID"""
    try:
        graph_iri = URIRef(identifier)
        store = VitalGraphSQLStore(identifier=graph_iri, configuration=db_url)
        return store._interned_id
    except Exception as e:
        return f"ERROR: {e}"

def main():
    print("Systematically finding the working graph identifier...")
    print("=" * 60)
    
    target_interned_id = "kb_bec6803d52"
    target_hash = "bec6803d52"
    
    # Database connection
    db_url = URL.create(
        drivername="postgresql+psycopg",
        username=PG_USER,
        password=PG_PASSWORD or None,
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
    )
    
    print(f"Target interned ID: {target_interned_id}")
    print(f"Target hash: {target_hash}")
    
    # Since we know the data contains entities from haley.ai/chat-saas, 
    # let's try variations of that domain
    test_identifiers = []
    
    # Base patterns from the entity URIs we've seen
    base_domains = [
        "vital.ai/haley.ai/chat-saas",
        "haley.ai/chat-saas", 
        "vital.ai/haley.ai",
        "haley.ai",
        "chat-saas"
    ]
    
    # Common prefixes
    prefixes = [
        "",
        "http://",
        "https://",
        "urn:",
        "vital:",
        "http://www.",
        "https://www."
    ]
    
    # Common suffixes  
    suffixes = [
        "",
        "/",
        "#",
        "/graph",
        "/wordnet",
        "/kg",
        "/data",
        "/ontology"
    ]
    
    # Generate all combinations
    for base in base_domains:
        for prefix in prefixes:
            for suffix in suffixes:
                test_id = f"{prefix}{base}{suffix}"
                test_identifiers.append(test_id)
    
    # Add some specific variations based on what we've seen
    specific_tests = [
        "http://vital.ai/haley.ai/chat-saas/KGEntity",
        "http://vital.ai/haley.ai/chat-saas/Edge_hasKGRelation", 
        "http://vital.ai/ontology/haley-ai-kg",
        "http://vital.ai/ontology/vital-core",
        "haley.ai/chat-saas/wordnet",
        "vital.ai/haley.ai/chat-saas/wordnet"
    ]
    
    test_identifiers.extend(specific_tests)
    
    # Remove duplicates and sort
    test_identifiers = sorted(list(set(test_identifiers)))
    
    print(f"\nTesting {len(test_identifiers)} potential identifiers...")
    
    found_matches = []
    
    for i, test_id in enumerate(test_identifiers):
        # First check with hash calculation
        calculated_id = generate_interned_id(test_id)
        
        if calculated_id == target_interned_id:
            print(f"✓ HASH MATCH: {test_id}")
            print(f"  Calculated: {calculated_id}")
            
            # Verify with actual store creation
            actual_id = test_graph_identifier(test_id, db_url)
            if actual_id == target_interned_id:
                print(f"✓ STORE MATCH: {test_id}")
                print(f"  Store ID: {actual_id}")
                found_matches.append(test_id)
            else:
                print(f"✗ Store mismatch: {actual_id}")
        
        # Show progress every 50 tests
        if (i + 1) % 50 == 0:
            print(f"  Tested {i + 1}/{len(test_identifiers)} identifiers...")
    
    print(f"\n" + "=" * 60)
    
    if found_matches:
        print(f"🎉 FOUND {len(found_matches)} WORKING IDENTIFIERS:")
        for match in found_matches:
            print(f"  ✓ {match}")
        
        # Test the first match
        print(f"\nTesting the first match: {found_matches[0]}")
        try:
            graph_iri = URIRef(found_matches[0])
            store = VitalGraphSQLStore(identifier=graph_iri, configuration=db_url)
            
            print(f"Store interned ID: {store._interned_id}")
            print(f"Tables created successfully: {list(store.tables.keys())}")
            
            # Quick test query
            with store.engine.connect() as conn:
                from sqlalchemy import text
                result = conn.execute(text(f"""
                    SELECT COUNT(*) FROM {store._interned_id}_literal_statements
                    WHERE object ILIKE '%happy%'
                """))
                happy_count = result.scalar()
                print(f"Happy entities found: {happy_count}")
                
                result = conn.execute(text(f"""
                    SELECT COUNT(*) FROM {store._interned_id}_asserted_statements
                    WHERE predicate = 'http://vital.ai/ontology/vital-core#vital__hasEdgeSource'
                """))
                edge_count = result.scalar()
                print(f"Edge source triples found: {edge_count}")
            
            return found_matches[0]
            
        except Exception as e:
            print(f"Error testing match: {e}")
    
    else:
        print("❌ NO WORKING IDENTIFIERS FOUND")
        print(f"The identifier that generates {target_hash} is not in our test set.")
        print(f"\nThis suggests the data may have been loaded with a non-standard identifier")
        print(f"or there may be an issue with the hash generation logic.")
    
    return None

if __name__ == "__main__":
    result = main()
    if result:
        print(f"\n🎯 USE THIS IDENTIFIER: {result}")
        print(f"Update all scripts to use this graph identifier instead of 'http://vital.ai/graph/wordnet'")
    else:
        print(f"\n⚠️ Consider alternative approaches or manual investigation")
