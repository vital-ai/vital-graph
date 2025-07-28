#!/usr/bin/env python3
"""
Reload Test Data for BIND Expression Testing
============================================

This script loads a small, focused dataset specifically designed for testing
BIND expressions, CONSTRUCT queries, and other SPARQL features.

The data includes:
- Entities with various string properties for CONCAT, SUBSTR, STRLEN testing
- Numeric properties for IF conditions and comparisons
- Hash-friendly strings for SHA1/MD5 testing
- Edge cases and special characters

Usage:
    python test_scripts/data/reload_test_data.py
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime
import uuid
from rdflib import Graph, URIRef, Literal, Namespace, RDF, RDFS, XSD

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_space_impl import PostgreSQLSpaceImpl

# Configuration
SPACE_ID = "space_test"
GRAPH_URI = "http://vital.ai/graph/test"
GLOBAL_GRAPH_URI = "urn:___GLOBAL"

# Namespaces
VITAL = Namespace("http://vital.ai/ontology/vital-core#")
TEST = Namespace("http://example.org/test#")
EX = Namespace("http://example.org/")



async def reload_test_data():
    """Reload test data optimized for BIND expression testing."""
    
    print("🔧 Test Data Reload for BIND Expression Testing")
    print("=" * 60)
    
    # Initialize VitalGraph with config
    print("\n1. Initializing VitalGraphImpl with config file...")
    try:
        project_root = Path(__file__).parent.parent.parent  # Go up to project root from test_scripts/data
        config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
        print(f"   Using config file: {config_path}")
        
        from vitalgraph.config.config_loader import get_config
        config = get_config(str(config_path))
        
        # Initialize VitalGraphImpl
        impl = VitalGraphImpl(config=config)
        db_impl = impl.get_db_impl()
        
        if not config:
            print("❌ Failed to load configuration")
            return False
            
        if not db_impl:
            print("❌ Failed to initialize database implementation")
            return False
            
        print("✅ VitalGraphImpl initialized successfully")
        print(f"   Config loaded: {config is not None}")
        print(f"   DB implementation: {type(db_impl).__name__}")
        
    except Exception as e:
        print(f"❌ Error initializing VitalGraph: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 2: Connect to database
    print("\n2. Connecting to database...")
    try:
        await db_impl.connect()
        space_impl = db_impl.get_space_impl()
        print("✅ Connected to database successfully")
        print(f"   Space implementation: {type(space_impl).__name__}")
        
    except Exception as e:
        print(f"❌ Error connecting to database: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Delete existing space tables
    print(f"\n🗑️  Deleting existing space tables for '{SPACE_ID}'...")
    try:
        space_impl.delete_space_tables(SPACE_ID)
        print("✅ Existing tables deleted")
    except Exception as e:
        print(f"ℹ️  No existing tables to delete: {e}")
    
    # Create new space tables
    print(f"\n🏗️  Creating space tables for '{SPACE_ID}'...")
    space_impl.create_space_tables(SPACE_ID)
    print("✅ Space tables created")
    
    # Create test graph
    test_graph = Graph()
    
    print(f"\n📝 Building test dataset...")
    
    # Test entities for string operations
    entities = [
        {
            "uri": TEST.entity1,
            "name": "Hello World",
            "description": "A simple greeting message",
            "category": "greeting",
            "length": 11,
            "age": 25
        },
        {
            "uri": TEST.entity2, 
            "name": "SPARQL Query Language",
            "description": "A powerful query language for RDF data",
            "category": "technology",
            "length": 20,
            "age": 15
        },
        {
            "uri": TEST.entity3,
            "name": "Test",
            "description": "Short test string for edge cases",
            "category": "test",
            "length": 4,
            "age": 35
        },
        {
            "uri": TEST.entity4,
            "name": "VitalGraph Database System",
            "description": "A graph database built on PostgreSQL",
            "category": "database",
            "length": 26,
            "age": 45
        },
        {
            "uri": TEST.entity5,
            "name": "AI",
            "description": "Artificial Intelligence abbreviation",
            "category": "ai",
            "length": 2,
            "age": 5
        }
    ]
    
    # Add entity data to graph
    for entity in entities:
        # Basic properties
        test_graph.add((entity["uri"], RDF.type, TEST.TestEntity))
        test_graph.add((entity["uri"], TEST.hasName, Literal(entity["name"])))
        test_graph.add((entity["uri"], TEST.hasDescription, Literal(entity["description"])))
        test_graph.add((entity["uri"], TEST.hasCategory, Literal(entity["category"])))
        test_graph.add((entity["uri"], TEST.hasLength, Literal(entity["length"], datatype=XSD.integer)))
        test_graph.add((entity["uri"], TEST.hasAge, Literal(entity["age"], datatype=XSD.integer)))
        
        # Additional properties for testing
        test_graph.add((entity["uri"], TEST.hasID, Literal(str(entity["uri"]).split("/")[-1])))
        test_graph.add((entity["uri"], TEST.createdAt, Literal(datetime.now().isoformat())))
    
    # Add relationships between entities
    test_graph.add((TEST.entity1, TEST.relatedTo, TEST.entity2))
    test_graph.add((TEST.entity2, TEST.relatedTo, TEST.entity3))
    test_graph.add((TEST.entity3, TEST.relatedTo, TEST.entity4))
    test_graph.add((TEST.entity4, TEST.relatedTo, TEST.entity5))
    test_graph.add((TEST.entity5, TEST.relatedTo, TEST.entity1))  # Circular reference
    
    # Add some numeric test data for mathematical operations
    numbers = [
        (TEST.number1, 10),
        (TEST.number2, 25),
        (TEST.number3, 50),
        (TEST.number4, 100),
        (TEST.number5, 0)
    ]
    
    for num_uri, value in numbers:
        test_graph.add((num_uri, RDF.type, TEST.NumberEntity))
        test_graph.add((num_uri, TEST.hasValue, Literal(value, datatype=XSD.integer)))
        test_graph.add((num_uri, TEST.hasDoubleValue, Literal(value * 2, datatype=XSD.integer)))
        test_graph.add((num_uri, TEST.hasLabel, Literal(f"Number {value}")))
    
    # Add UNION-specific test data for comprehensive UNION testing
    print(f"\n🔗 Adding UNION-specific test data...")
    
    # Additional entities with mixed properties (some have descriptions, some don't)
    union_entities = [
        {
            "uri": TEST.unionEntity1,
            "name": "Entity with Description",
            "description": "This entity has both name and description",
            "category": "complete",
            "hasDescription": True
        },
        {
            "uri": TEST.unionEntity2,
            "name": "Entity without Description",
            "category": "incomplete",
            "hasDescription": False
        },
        {
            "uri": TEST.unionEntity3,
            "name": "Another Complete Entity",
            "description": "Another entity with description for UNION testing",
            "category": "complete",
            "hasDescription": True
        },
        {
            "uri": TEST.unionEntity4,
            "name": "Minimal Entity",
            "category": "minimal",
            "hasDescription": False
        }
    ]
    
    # Add union entities to graph
    for entity in union_entities:
        test_graph.add((entity["uri"], RDF.type, TEST.UnionTestEntity))
        test_graph.add((entity["uri"], TEST.hasName, Literal(entity["name"])))
        test_graph.add((entity["uri"], TEST.hasCategory, Literal(entity["category"])))
        
        # Only add description if the entity has one (for UNION testing)
        if entity["hasDescription"]:
            test_graph.add((entity["uri"], TEST.hasDescription, Literal(entity["description"])))
    
    # Add entities with different identifier patterns for UNION testing
    identifier_entities = [
        (TEST.idEntity1, "ID-001", "First identifier entity"),
        (TEST.idEntity2, "CODE-002", "Second identifier entity"),
        (TEST.idEntity3, "REF-003", "Third identifier entity")
    ]
    
    for entity_uri, identifier, description in identifier_entities:
        test_graph.add((entity_uri, RDF.type, TEST.IdentifierEntity))
        test_graph.add((entity_uri, TEST.hasIdentifier, Literal(identifier)))
        test_graph.add((entity_uri, TEST.hasDescription, Literal(description)))
        # Some have names, some have labels (for UNION testing)
        if "001" in identifier:
            test_graph.add((entity_uri, TEST.hasName, Literal(f"Name for {identifier}")))
        else:
            test_graph.add((entity_uri, TEST.hasLabel, Literal(f"Label for {identifier}")))
    
    # Add mixed-type entities for type-based UNION testing
    mixed_types = [
        (TEST.mixedA1, TEST.TypeA, "Alpha One"),
        (TEST.mixedA2, TEST.TypeA, "Alpha Two"),
        (TEST.mixedB1, TEST.TypeB, "Beta One"),
        (TEST.mixedB2, TEST.TypeB, "Beta Two"),
        (TEST.mixedC1, TEST.TypeC, "Gamma One")
    ]
    
    for entity_uri, entity_type, name in mixed_types:
        test_graph.add((entity_uri, RDF.type, entity_type))
        test_graph.add((entity_uri, TEST.hasName, Literal(name)))
        test_graph.add((entity_uri, TEST.belongsToType, entity_type))
    
    # Add cross-reference relationships for relationship UNION testing
    cross_refs = [
        (TEST.entity1, TEST.references, TEST.unionEntity1),
        (TEST.entity2, TEST.mentions, TEST.unionEntity2),
        (TEST.unionEntity3, TEST.references, TEST.idEntity1),
        (TEST.idEntity2, TEST.mentions, TEST.mixedA1),
        (TEST.mixedB1, TEST.crossLinks, TEST.mixedC1)
    ]
    
    for subj, pred, obj in cross_refs:
        test_graph.add((subj, pred, obj))
    
    # ===== SUBQUERY TEST DATA =====
    print("\n🔗 Adding subquery-specific test data...")
    
    # Add entities with varying name lengths for length-based subqueries
    length_entities = [
        (TEST.shortEntity1, "Al", "Short name entity 1"),
        (TEST.shortEntity2, "Bo", "Short name entity 2"),
        (TEST.mediumEntity1, "Charlie", "Medium length name entity 1"),
        (TEST.mediumEntity2, "Diana", "Medium length name entity 2"),
        (TEST.longEntity1, "Alexander", "Very long name entity 1"),
        (TEST.longEntity2, "Elizabeth", "Very long name entity 2"),
        (TEST.veryLongEntity1, "Christopher", "Extremely long name entity 1"),
        (TEST.veryLongEntity2, "Anastasia", "Extremely long name entity 2")
    ]
    
    for entity_uri, name, description in length_entities:
        test_graph.add((entity_uri, RDF.type, TEST.TestEntity))
        test_graph.add((entity_uri, TEST.hasName, Literal(name)))
        test_graph.add((entity_uri, TEST.hasDescription, Literal(description)))
        test_graph.add((entity_uri, TEST.hasCategory, TEST.lengthCategory))
    
    # Add entities with/without descriptions for EXISTS/NOT EXISTS testing
    exists_entities = [
        (TEST.withDesc1, "Entity With Desc 1", "This entity has a description"),
        (TEST.withDesc2, "Entity With Desc 2", "This entity also has a description"),
        (TEST.withDesc3, "Entity With Desc 3", "Another entity with description"),
        (TEST.noDesc1, "Entity No Desc 1", None),
        (TEST.noDesc2, "Entity No Desc 2", None),
        (TEST.noDesc3, "Entity No Desc 3", None)
    ]
    
    for entity_uri, name, description in exists_entities:
        test_graph.add((entity_uri, RDF.type, TEST.TestEntity))
        test_graph.add((entity_uri, TEST.hasName, Literal(name)))
        if description:
            test_graph.add((entity_uri, TEST.hasDescription, Literal(description)))
        test_graph.add((entity_uri, TEST.hasCategory, TEST.existsCategory))
    
    # Add entities with varying connection counts for aggregation subqueries
    connection_entities = [
        (TEST.hub1, "Hub Entity 1", [TEST.spoke1, TEST.spoke2, TEST.spoke3, TEST.spoke4]),
        (TEST.hub2, "Hub Entity 2", [TEST.spoke5, TEST.spoke6, TEST.spoke7]),
        (TEST.hub3, "Hub Entity 3", [TEST.spoke8, TEST.spoke9]),
        (TEST.isolated1, "Isolated Entity 1", []),
        (TEST.isolated2, "Isolated Entity 2", [])
    ]
    
    for hub_uri, hub_name, spokes in connection_entities:
        test_graph.add((hub_uri, RDF.type, TEST.TestEntity))
        test_graph.add((hub_uri, TEST.hasName, Literal(hub_name)))
        test_graph.add((hub_uri, TEST.hasCategory, TEST.connectionCategory))
        
        for spoke_uri in spokes:
            test_graph.add((spoke_uri, RDF.type, TEST.TestEntity))
            test_graph.add((spoke_uri, TEST.hasName, Literal(f"Spoke {spoke_uri.split('/')[-1]}")))
            test_graph.add((hub_uri, TEST.relatedTo, spoke_uri))
    
    # Add hierarchical categories for nested subquery testing
    categories = [
        (TEST.topCategory1, "Top Category Alpha", None),
        (TEST.topCategory2, "Top Category Beta", None),
        (TEST.midCategory1, "Mid Category 1", TEST.topCategory1),
        (TEST.midCategory2, "Mid Category 2", TEST.topCategory1),
        (TEST.midCategory3, "Mid Category 3", TEST.topCategory2),
        (TEST.leafCategory1, "Leaf Category A", TEST.midCategory1),
        (TEST.leafCategory2, "Leaf Category B", TEST.midCategory2),
        (TEST.leafCategory3, "Leaf Category C", TEST.midCategory3)
    ]
    
    for cat_uri, cat_name, parent_cat in categories:
        test_graph.add((cat_uri, RDF.type, TEST.Category))
        test_graph.add((cat_uri, TEST.hasName, Literal(cat_name)))
        if parent_cat:
            test_graph.add((cat_uri, TEST.hasParentCategory, parent_cat))
    
    # Add entities assigned to different category levels
    category_assignments = [
        (TEST.topLevelEntity1, TEST.topCategory1),
        (TEST.topLevelEntity2, TEST.topCategory2),
        (TEST.midLevelEntity1, TEST.midCategory1),
        (TEST.midLevelEntity2, TEST.midCategory2),
        (TEST.midLevelEntity3, TEST.midCategory3),
        (TEST.leafLevelEntity1, TEST.leafCategory1),
        (TEST.leafLevelEntity2, TEST.leafCategory2),
        (TEST.leafLevelEntity3, TEST.leafCategory3)
    ]
    
    for entity_uri, category_uri in category_assignments:
        test_graph.add((entity_uri, RDF.type, TEST.TestEntity))
        test_graph.add((entity_uri, TEST.hasName, Literal(f"Entity in {category_uri.split('/')[-1]}")))
        test_graph.add((entity_uri, TEST.hasCategory, category_uri))
    
    # Add ranking/scoring data for ORDER BY and LIMIT subqueries
    scored_entities = [
        (TEST.scored1, "Alpha Entity", 95),
        (TEST.scored2, "Beta Entity", 87),
        (TEST.scored3, "Gamma Entity", 92),
        (TEST.scored4, "Delta Entity", 78),
        (TEST.scored5, "Epsilon Entity", 89),
        (TEST.scored6, "Zeta Entity", 83),
        (TEST.scored7, "Eta Entity", 96),
        (TEST.scored8, "Theta Entity", 71)
    ]
    
    for entity_uri, name, score in scored_entities:
        test_graph.add((entity_uri, RDF.type, TEST.TestEntity))
        test_graph.add((entity_uri, TEST.hasName, Literal(name)))
        test_graph.add((entity_uri, TEST.hasScore, Literal(score)))
        test_graph.add((entity_uri, TEST.hasCategory, TEST.scoredCategory))
    
    # Add comprehensive test data for SPARQL built-in functions
    print(f"\n🧪 Adding built-in function test data...")
    
    # Person entities for BOUND/COALESCE testing (some with email, some with phone, some with both, some with neither)
    person_entities = [
        {
            "uri": EX.person1,
            "name": "Alice Smith",
            "age": 30,
            "email": "alice@example.com",
            "phone": None,
            "birth_date": "1993-05-15T10:30:00Z",
            "description_en": "Software engineer from California",
            "description_fr": "Ingénieur logiciel de Californie"
        },
        {
            "uri": EX.person2,
            "name": "Bob Johnson",
            "age": 25,
            "email": None,
            "phone": "+1-555-0123",
            "birth_date": "1998-12-03T14:45:00Z",
            "description_en": "Data scientist from New York",
            "description_fr": None
        },
        {
            "uri": EX.person3,
            "name": "Carol Davis",
            "age": 35,
            "email": "carol@example.com",
            "phone": "+1-555-0456",
            "birth_date": "1988-08-22T09:15:00Z",
            "description_en": "Product manager from Texas",
            "description_fr": "Chef de produit du Texas"
        },
        {
            "uri": EX.person4,
            "name": "David Wilson",
            "age": 28,
            "email": None,
            "phone": None,
            "birth_date": "1995-03-10T16:20:00Z",
            "description_en": "Designer from Oregon",
            "description_fr": None
        },
        {
            "uri": EX.person5,
            "name": "Eve Brown",
            "age": 42,
            "email": "eve@example.com",
            "phone": "+1-555-0789",
            "birth_date": "1981-11-07T11:30:00Z",
            "description_en": None,
            "description_fr": "Directrice marketing de Floride"
        }
    ]
    
    for person in person_entities:
        # Basic person properties
        test_graph.add((person["uri"], RDF.type, EX.Person))
        test_graph.add((person["uri"], EX.hasName, Literal(person["name"])))
        test_graph.add((person["uri"], EX.hasAge, Literal(person["age"], datatype=XSD.integer)))
        
        # Optional contact information (for BOUND/COALESCE testing)
        if person["email"]:
            test_graph.add((person["uri"], EX.hasEmail, Literal(person["email"])))
        if person["phone"]:
            test_graph.add((person["uri"], EX.hasPhone, Literal(person["phone"])))
        
        # Birth dates for date/time function testing
        if person["birth_date"]:
            test_graph.add((person["uri"], EX.hasBirthDate, Literal(person["birth_date"], datatype=XSD.dateTime)))
        
        # Multi-language descriptions for LANG/LANGMATCHES testing
        if person["description_en"]:
            test_graph.add((person["uri"], EX.hasDescription, Literal(person["description_en"], lang="en")))
        if person["description_fr"]:
            test_graph.add((person["uri"], EX.hasDescription, Literal(person["description_fr"], lang="fr")))
    
    # Product entities for numeric function testing
    product_entities = [
        {
            "uri": EX.product1,
            "name": "Laptop Computer",
            "price": 1299.99,
            "warranty_months": 24,
            "rating": 4.5
        },
        {
            "uri": EX.product2,
            "name": "Smartphone",
            "price": 799.50,
            "warranty_months": 12,
            "rating": 4.2
        },
        {
            "uri": EX.product3,
            "name": "Tablet Device",
            "price": 449.00,
            "warranty_months": 18,
            "rating": 4.0
        },
        {
            "uri": EX.product4,
            "name": "Wireless Headphones",
            "price": 199.99,
            "warranty_months": 6,
            "rating": 4.7
        },
        {
            "uri": EX.product5,
            "name": "Smart Watch",
            "price": 349.00,
            "warranty_months": 12,
            "rating": 3.8
        }
    ]
    
    for product in product_entities:
        test_graph.add((product["uri"], RDF.type, EX.Product))
        test_graph.add((product["uri"], EX.hasName, Literal(product["name"])))
        test_graph.add((product["uri"], EX.hasPrice, Literal(product["price"], datatype=XSD.decimal)))
        test_graph.add((product["uri"], EX.hasWarrantyMonths, Literal(product["warranty_months"], datatype=XSD.integer)))
        test_graph.add((product["uri"], EX.hasRating, Literal(product["rating"], datatype=XSD.decimal)))
    
    # String test entities for advanced string functions
    string_entities = [
        {
            "uri": EX.string1,
            "text": "Hello World Example",
            "category": "greeting"
        },
        {
            "uri": EX.string2,
            "text": "SPARQL Query Language",
            "category": "technology"
        },
        {
            "uri": EX.string3,
            "text": "Test String with Spaces",
            "category": "test"
        },
        {
            "uri": EX.string4,
            "text": "Special-Characters_123",
            "category": "special"
        }
    ]
    
    for string_entity in string_entities:
        test_graph.add((string_entity["uri"], RDF.type, EX.StringEntity))
        test_graph.add((string_entity["uri"], EX.hasText, Literal(string_entity["text"])))
        test_graph.add((string_entity["uri"], EX.hasCategory, Literal(string_entity["category"])))
    
    # Numeric test entities for mathematical operations
    numeric_entities = [
        (EX.num1, 10.5, -5.2),
        (EX.num2, -15.7, 8.3),
        (EX.num3, 0.0, 100.0),
        (EX.num4, 42.42, -42.42),
        (EX.num5, 999.999, 0.001)
    ]
    
    for num_uri, positive_val, negative_val in numeric_entities:
        test_graph.add((num_uri, RDF.type, EX.NumericEntity))
        test_graph.add((num_uri, EX.hasPositiveValue, Literal(positive_val, datatype=XSD.decimal)))
        test_graph.add((num_uri, EX.hasNegativeValue, Literal(negative_val, datatype=XSD.decimal)))
        test_graph.add((num_uri, EX.hasLabel, Literal(f"Number {positive_val}")))
    
    print(f"📊 Created {len(test_graph)} test triples (including UNION, subquery, and built-in function test data)")
    # Step 4: Drop indexes before bulk loading for optimal performance
    print(f"\n4. Dropping indexes before bulk loading for optimal performance...")
    try:
        space_impl.drop_indexes_for_bulk_load(SPACE_ID)
        print(f"✅ Indexes dropped - bulk loading will be faster")
    except Exception as e:
        print(f"⚠️  Warning: Index drop failed: {e}")
    
    # Step 5: Add test data to main graph
    print(f"\n5. Adding test data to main graph ({GRAPH_URI})...")
    
    # Convert graph to quads with explicit graph URI
    quads = [(s, p, o, URIRef(GRAPH_URI)) for s, p, o in test_graph]
    quad_count = len(quads)
    
    # Use batch insert for efficiency (no index overhead)
    await space_impl.add_rdf_quads_batch(SPACE_ID, quads)
    print(f"✅ Added {quad_count} test quads to main graph")
    
    # Add some global graph data for testing
    print(f"\n🌐 Adding global graph test data...")
    
    global_quads = [
        # People for IF condition testing
        # Person 1: Has both email and phone (for COALESCE testing)
        (EX.person1, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person1, EX.hasName, Literal("Alice Johnson"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person1, EX.hasAge, Literal(28, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person1, EX.hasEmail, Literal("alice@example.com"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person1, EX.hasPhone, Literal("+1-555-0101"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person1, EX.hasBirthDate, Literal("1995-03-15", datatype=XSD.date), URIRef(GLOBAL_GRAPH_URI)),
        
        # Person 2: Has only email (for COALESCE testing)
        (EX.person2, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person2, EX.hasName, Literal("Bob Smith"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person2, EX.hasAge, Literal(35, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person2, EX.hasEmail, Literal("bob@example.com"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person2, EX.hasBirthDate, Literal("1988-07-22", datatype=XSD.date), URIRef(GLOBAL_GRAPH_URI)),
        
        # Person 3: Has only phone (for COALESCE testing)
        (EX.person3, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person3, EX.hasName, Literal("Charlie Brown"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person3, EX.hasAge, Literal(22, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person3, EX.hasPhone, Literal("+1-555-0303"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person3, EX.hasBirthDate, Literal("2001-12-05", datatype=XSD.date), URIRef(GLOBAL_GRAPH_URI)),
        
        # Person 4: Has neither email nor phone (for COALESCE default testing)
        (EX.person4, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person4, EX.hasName, Literal("Diana Prince"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person4, EX.hasAge, Literal(30, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person4, EX.hasTitle, Literal("Wonder Woman"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person4, EX.hasBirthDate, Literal("1993-10-21", datatype=XSD.date), URIRef(GLOBAL_GRAPH_URI)),
        
        # Person 5: Has phone but no email (for COALESCE testing)
        (EX.person5, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person5, EX.hasName, Literal("Clark Kent"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person5, EX.hasAge, Literal(32, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person5, EX.hasPhone, Literal("+1-555-0505"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person5, EX.hasTitle, Literal("Superman"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person5, EX.hasBirthDate, Literal("1991-06-18", datatype=XSD.date), URIRef(GLOBAL_GRAPH_URI)),
        
        # Organizations for type-based UNION testing
        (EX.org1, RDF.type, EX.Organization, URIRef(GLOBAL_GRAPH_URI)),
        (EX.org1, EX.hasName, Literal("Daily Planet"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.org1, EX.hasType, Literal("newspaper"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.org2, RDF.type, EX.Organization, URIRef(GLOBAL_GRAPH_URI)),
        (EX.org2, EX.hasName, Literal("Wayne Enterprises"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.org2, EX.hasType, Literal("corporation"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Projects for mixed entity UNION testing
        (EX.project1, RDF.type, EX.Project, URIRef(GLOBAL_GRAPH_URI)),
        (EX.project1, EX.hasName, Literal("Justice League Initiative"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.project1, EX.hasStatus, Literal("active"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.project2, RDF.type, EX.Project, URIRef(GLOBAL_GRAPH_URI)),
        (EX.project2, EX.hasName, Literal("Metropolis Protection"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.project2, EX.hasStatus, Literal("ongoing"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Relationships for relationship UNION testing
        (EX.person1, EX.knows, EX.person2, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person2, EX.knows, EX.person3, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person3, EX.knows, EX.person1, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person4, EX.knows, EX.person5, URIRef(GLOBAL_GRAPH_URI)),
        
        # Work relationships
        (EX.person5, EX.worksFor, EX.org1, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person1, EX.worksFor, EX.org2, URIRef(GLOBAL_GRAPH_URI)),
        
        # Project memberships
        (EX.person4, EX.memberOf, EX.project1, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person5, EX.memberOf, EX.project1, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person5, EX.memberOf, EX.project2, URIRef(GLOBAL_GRAPH_URI)),
        
        # Additional properties for comprehensive UNION testing
        (EX.person1, EX.hasSkill, Literal("leadership"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person2, EX.hasSkill, Literal("analysis"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person4, EX.hasSkill, Literal("combat"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person5, EX.hasSkill, Literal("flight"), URIRef(GLOBAL_GRAPH_URI)),
        
        # OPTIONAL pattern test data - entities with missing optional properties
        # Some people have email, some don't (for OPTIONAL email testing)
        (EX.person1, EX.hasEmail, Literal("bruce.wayne@wayneenterprises.com"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person3, EX.hasEmail, Literal("diana.prince@themyscira.gov"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person5, EX.hasEmail, Literal("clark.kent@dailyplanet.com"), URIRef(GLOBAL_GRAPH_URI)),
        # person2 and person4 deliberately have no email for OPTIONAL testing
        
        # Some people have phone numbers, some don't
        (EX.person1, EX.hasPhone, Literal("+1-555-BATMAN"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person4, EX.hasPhone, Literal("+1-555-WONDER"), URIRef(GLOBAL_GRAPH_URI)),
        # person2, person3, person5 have no phone for OPTIONAL testing
        
        # Some organizations have websites, some don't
        (EX.org1, EX.hasWebsite, Literal("https://dailyplanet.com"), URIRef(GLOBAL_GRAPH_URI)),
        # org2 has no website for OPTIONAL testing
        
        # Some projects have budgets, some don't
        (EX.project1, EX.hasBudget, Literal(1000000, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        # project2 has no budget for OPTIONAL testing
        
        # Additional entities specifically for OPTIONAL testing
        (EX.employee1, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee1, EX.hasName, Literal("John Smith"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee1, EX.hasEmployeeId, Literal("EMP001"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee1, EX.hasDepartment, Literal("Engineering"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee1, EX.hasManager, EX.manager1, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.employee2, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee2, EX.hasName, Literal("Jane Doe"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee2, EX.hasEmployeeId, Literal("EMP002"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee2, EX.hasDepartment, Literal("Marketing"), URIRef(GLOBAL_GRAPH_URI)),
        # employee2 has no manager for OPTIONAL testing
        
        (EX.employee3, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee3, EX.hasName, Literal("Bob Johnson"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee3, EX.hasEmployeeId, Literal("EMP003"), URIRef(GLOBAL_GRAPH_URI)),
        # employee3 has no department or manager for OPTIONAL testing
        
        (EX.manager1, RDF.type, EX.Manager, URIRef(GLOBAL_GRAPH_URI)),
        (EX.manager1, EX.hasName, Literal("Alice Manager"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.manager1, EX.hasTitle, Literal("Engineering Director"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Products with optional specifications
        (EX.product1, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.product1, EX.hasName, Literal("Laptop Pro"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product1, EX.hasPrice, Literal(1299.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product1, EX.hasWarranty, Literal("2 years"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product1, EX.hasColor, Literal("Silver"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.product2, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.product2, EX.hasName, Literal("Desktop Basic"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product2, EX.hasPrice, Literal(799.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        # product2 has no warranty or color for OPTIONAL testing
        
        (EX.product3, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.product3, EX.hasName, Literal("Tablet Mini"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product3, EX.hasColor, Literal("Black"), URIRef(GLOBAL_GRAPH_URI)),
        # product3 has no price or warranty for OPTIONAL testing
        
        # Additional data for comprehensive aggregate function testing
        
        # More employees for department aggregation
        (EX.employee4, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee4, EX.hasName, Literal("Sarah Wilson"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee4, EX.hasEmployeeId, Literal("EMP004"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee4, EX.hasDepartment, Literal("Engineering"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee4, EX.hasAge, Literal(28, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee4, EX.hasSalary, Literal(75000, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.employee5, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee5, EX.hasName, Literal("Mike Davis"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee5, EX.hasEmployeeId, Literal("EMP005"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee5, EX.hasDepartment, Literal("Engineering"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee5, EX.hasAge, Literal(35, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee5, EX.hasSalary, Literal(85000, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.employee6, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee6, EX.hasName, Literal("Lisa Chen"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee6, EX.hasEmployeeId, Literal("EMP006"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee6, EX.hasDepartment, Literal("Marketing"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee6, EX.hasAge, Literal(31, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee6, EX.hasSalary, Literal(70000, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.employee7, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee7, EX.hasName, Literal("Tom Rodriguez"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee7, EX.hasEmployeeId, Literal("EMP007"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee7, EX.hasDepartment, Literal("Sales"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee7, EX.hasAge, Literal(29, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee7, EX.hasSalary, Literal(65000, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.employee8, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee8, EX.hasName, Literal("Amy Johnson"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee8, EX.hasEmployeeId, Literal("EMP008"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee8, EX.hasDepartment, Literal("Sales"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee8, EX.hasAge, Literal(26, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee8, EX.hasSalary, Literal(60000, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        
        # Add salary data to existing employees
        (EX.employee1, EX.hasAge, Literal(33, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee1, EX.hasSalary, Literal(90000, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.employee2, EX.hasAge, Literal(27, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee2, EX.hasSalary, Literal(68000, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.employee3, EX.hasAge, Literal(24, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.employee3, EX.hasSalary, Literal(55000, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        
        # More products for price aggregation
        (EX.product4, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.product4, EX.hasName, Literal("Monitor 4K"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product4, EX.hasPrice, Literal(599.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product4, EX.hasColor, Literal("Black"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product4, EX.hasCategory, Literal("Electronics"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.product5, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.product5, EX.hasName, Literal("Keyboard Wireless"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product5, EX.hasPrice, Literal(89.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product5, EX.hasColor, Literal("White"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product5, EX.hasCategory, Literal("Electronics"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.product6, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.product6, EX.hasName, Literal("Mouse Gaming"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product6, EX.hasPrice, Literal(129.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product6, EX.hasColor, Literal("Black"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product6, EX.hasCategory, Literal("Electronics"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Add categories to existing products
        (EX.product1, EX.hasCategory, Literal("Computers"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product2, EX.hasCategory, Literal("Computers"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product3, EX.hasCategory, Literal("Tablets"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Sales data for more complex aggregations
        (EX.sale1, RDF.type, EX.Sale, URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale1, EX.hasProduct, EX.product1, URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale1, EX.hasQuantity, Literal(2, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale1, EX.hasSaleDate, Literal("2024-01-15", datatype=XSD.date), URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale1, EX.hasSalesperson, EX.employee7, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.sale2, RDF.type, EX.Sale, URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale2, EX.hasProduct, EX.product2, URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale2, EX.hasQuantity, Literal(1, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale2, EX.hasSaleDate, Literal("2024-01-20", datatype=XSD.date), URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale2, EX.hasSalesperson, EX.employee8, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.sale3, RDF.type, EX.Sale, URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale3, EX.hasProduct, EX.product4, URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale3, EX.hasQuantity, Literal(3, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale3, EX.hasSaleDate, Literal("2024-02-01", datatype=XSD.date), URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale3, EX.hasSalesperson, EX.employee7, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.sale4, RDF.type, EX.Sale, URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale4, EX.hasProduct, EX.product5, URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale4, EX.hasQuantity, Literal(5, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale4, EX.hasSaleDate, Literal("2024-02-10", datatype=XSD.date), URIRef(GLOBAL_GRAPH_URI)),
        (EX.sale4, EX.hasSalesperson, EX.employee8, URIRef(GLOBAL_GRAPH_URI)),
        
        # Additional test data for filter functions
        # Language-tagged literals for LANG() testing
        (EX.entity1, EX.hasLabel, Literal("Hello World", lang="en"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.entity1, EX.hasLabel, Literal("Bonjour le monde", lang="fr"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.entity1, EX.hasDescription, Literal("A test entity", lang="en"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.entity2, EX.hasLabel, Literal("Good Morning", lang="en"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.entity2, EX.hasLabel, Literal("Bon matin", lang="fr"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.entity3, EX.hasLabel, Literal("Test Data", lang="en"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Various data types for DATATYPE() testing
        (EX.datatest1, EX.hasString, Literal("Plain string"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatest1, EX.hasInteger, Literal(42, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatest1, EX.hasDecimal, Literal(3.14159, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatest1, EX.hasFloat, Literal(2.718, datatype=XSD.float), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatest1, EX.hasBoolean, Literal(True, datatype=XSD.boolean), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatest1, EX.hasDate, Literal("2024-01-15", datatype=XSD.date), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatest1, EX.hasDateTime, Literal("2024-01-15T10:30:00", datatype=XSD.dateTime), URIRef(GLOBAL_GRAPH_URI)),
        
        # Test data for REGEX() patterns
        (EX.regex1, EX.hasPattern, Literal("test123"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.regex1, EX.hasPattern, Literal("TEST456"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.regex1, EX.hasPattern, Literal("pattern_with_underscore"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.regex1, EX.hasPattern, Literal("special-chars@example.com"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.regex1, EX.hasPattern, Literal("http://example.org/resource"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Additional email addresses for testing
        (EX.person6, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person6, EX.hasName, Literal("Jane Smith"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person6, EX.hasAge, Literal(28, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person6, EX.hasEmail, Literal("jane.smith@example.org"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.person7, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person7, EX.hasName, Literal("Bob Johnson"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person7, EX.hasAge, Literal(35, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person7, EX.hasEmail, Literal("bob.johnson@example.org"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Additional test data to fix result count mismatches
        (EX.person8, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person8, EX.hasName, Literal("John Doe"), URIRef(GLOBAL_GRAPH_URI)),  # Second "John" name
        (EX.person8, EX.hasEmail, Literal("john.doe@example.org"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person9, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person9, EX.hasEmail, Literal("test1@example.org"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person10, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person10, EX.hasEmail, Literal("test2@example.org"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person11, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person11, EX.hasEmail, Literal("test3@example.org"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person7, EX.hasEmail, Literal("bob.johnson@test.com"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Test data for string function filters
        (EX.stringtest1, EX.hasValue, Literal("Contains Smith in middle"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.stringtest2, EX.hasValue, Literal("Smith at beginning"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.stringtest3, EX.hasValue, Literal("Ends with Smith"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.stringtest4, EX.hasValue, Literal("No target word here"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Additional products for Gaming/Pro pattern testing
        (EX.product7, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.product7, EX.hasName, Literal("Gaming Chair Pro"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product7, EX.hasPrice, Literal(299.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.product8, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.product8, EX.hasName, Literal("Pro Keyboard"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product8, EX.hasPrice, Literal(159.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        
        # ========== LANG() and DATATYPE() Test Data ==========
        
        # Multilingual names for LANG() testing - using separate entities to avoid conflicts
        (EX.multilingual_person1, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.multilingual_person1, EX.hasName, Literal("John Smith", lang="en"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.multilingual_person1, EX.hasName, Literal("Jean Dupont", lang="fr"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.multilingual_person1, EX.hasName, Literal("Juan García", lang="es"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.multilingual_person1, EX.hasName, Literal("Johann Schmidt", lang="de"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.multilingual_person2, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.multilingual_person2, EX.hasName, Literal("Alice Johnson", lang="en"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.multilingual_person2, EX.hasName, Literal("Alice Dubois", lang="fr"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.multilingual_person3, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.multilingual_person3, EX.hasName, Literal("Bob Wilson", lang="en"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.multilingual_person3, EX.hasName, Literal("Roberto Gonzalez", lang="es"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Names without language tags (should return empty string for LANG())
        (EX.person4, EX.hasName, Literal("Charlie Brown"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person5, EX.hasName, Literal("Diana Prince"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Multilingual descriptions
        (EX.product1, EX.hasDescription, Literal("High-quality laptop computer", lang="en"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product1, EX.hasDescription, Literal("Ordinateur portable de haute qualité", lang="fr"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.product1, EX.hasDescription, Literal("Computadora portátil de alta calidad", lang="es"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Various datatypes for DATATYPE() testing
        (EX.datatypetest1, EX.hasStringValue, Literal("Plain string without datatype"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatypetest1, EX.hasExplicitString, Literal("Explicit string", datatype=XSD.string), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatypetest1, EX.hasIntegerValue, Literal(42, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatypetest1, EX.hasLongValue, Literal(9223372036854775807, datatype=XSD.long), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatypetest1, EX.hasDecimalValue, Literal(3.14159, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatypetest1, EX.hasFloatValue, Literal(2.718, datatype=XSD.float), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatypetest1, EX.hasDoubleValue, Literal(1.41421356, datatype=XSD.double), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatypetest1, EX.hasBooleanValue, Literal(True, datatype=XSD.boolean), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatypetest1, EX.hasDateValue, Literal("2024-01-15", datatype=XSD.date), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatypetest1, EX.hasTimeValue, Literal("14:30:00", datatype=XSD.time), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatypetest1, EX.hasDateTimeValue, Literal("2024-01-15T14:30:00", datatype=XSD.dateTime), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.datatypetest2, EX.hasIntegerValue, Literal(-123, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatypetest2, EX.hasDecimalValue, Literal(-99.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.datatypetest2, EX.hasBooleanValue, Literal(False, datatype=XSD.boolean), URIRef(GLOBAL_GRAPH_URI)),
        
        # Mixed language and datatype examples
        (EX.mixedtest1, EX.hasPrice, Literal("29.99", datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.mixedtest1, EX.hasCurrency, Literal("USD", lang="en"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.mixedtest1, EX.hasCurrency, Literal("Dollar américain", lang="fr"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.mixedtest2, EX.hasQuantity, Literal(5, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.mixedtest2, EX.hasUnit, Literal("pieces", lang="en"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.mixedtest2, EX.hasUnit, Literal("pièces", lang="fr"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Edge cases for testing
        (EX.edgecase1, EX.hasEmptyString, Literal(""), URIRef(GLOBAL_GRAPH_URI)),
        (EX.edgecase1, EX.hasZeroInteger, Literal(0, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.edgecase1, EX.hasZeroDecimal, Literal(0.0, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.edgecase1, EX.hasSpecialChars, Literal("Special: @#$%^&*()", lang="en"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Additional age data with explicit integer datatype (for persons not already having ages)
        (EX.person4, EX.hasAge, Literal(28, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person5, EX.hasAge, Literal(32, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
    ]
    
    await space_impl.add_rdf_quads_batch(SPACE_ID, global_quads)
    print(f"✅ Added {len(global_quads)} global graph quads")
    
    # Optimize indexes for bulk loading (drop before, recreate after)
    print(f"\n🔧 Optimizing indexes after bulk loading...")
    try:
        # Drop indexes (in case they exist from previous runs)
        space_impl.drop_indexes_for_bulk_load(SPACE_ID)
        print(f"✅ Indexes dropped for optimization")
        
        # Recreate all indexes for optimal performance
        success = space_impl.recreate_indexes_after_bulk_load(SPACE_ID, concurrent=False)
        if success:
            print(f"✅ All indexes recreated successfully")
        else:
            print(f"⚠️  Warning: Some indexes may not have been recreated")
    except Exception as e:
        print(f"⚠️  Warning: Index optimization failed: {e}")
    
    # Verify data loading
    print(f"\n🔍 Verifying data loading...")
    
    # Simple verification - data was loaded successfully
    print(f"📊 Main graph ({GRAPH_URI}): {quad_count} quads")
    print(f"📊 Global graph ({GLOBAL_GRAPH_URI}): {len(global_quads)} quads")
    print(f"📊 Total quads loaded: {quad_count + len(global_quads)}")
    
    # Show cache statistics
    try:
        cache_stats = space_impl.term_cache.get_stats()
        print(f"📊 Cache: {cache_stats['size']} terms, {cache_stats['hits']} hits, {cache_stats['misses']} misses")
    except AttributeError:
        print("📊 Cache: Statistics not available")
    
    print(f"✅ Test Data Reload Complete!")
    
    # ===== SPARQL 1.1 UPDATE TEST DATA =====
    print("\n🔄 Adding SPARQL 1.1 UPDATE-specific test data...")
    
    # Base entities for UPDATE operations testing
    update_test_data = [
        # Employee entities for pattern-based updates
        (EX.emp001, RDF.type, EX.Employee, URIRef(GRAPH_URI)),
        (EX.emp001, EX.hasName, Literal("Alice Johnson"), URIRef(GRAPH_URI)),
        (EX.emp001, EX.hasEmployeeId, Literal("EMP001"), URIRef(GRAPH_URI)),
        (EX.emp001, EX.hasDepartment, Literal("Engineering"), URIRef(GRAPH_URI)),
        (EX.emp001, EX.hasSalary, Literal(75000, datatype=XSD.integer), URIRef(GRAPH_URI)),
        (EX.emp001, EX.hasStatus, Literal("active"), URIRef(GRAPH_URI)),
        
        (EX.emp002, RDF.type, EX.Employee, URIRef(GRAPH_URI)),
        (EX.emp002, EX.hasName, Literal("Bob Smith"), URIRef(GRAPH_URI)),
        (EX.emp002, EX.hasEmployeeId, Literal("EMP002"), URIRef(GRAPH_URI)),
        (EX.emp002, EX.hasDepartment, Literal("Marketing"), URIRef(GRAPH_URI)),
        (EX.emp002, EX.hasSalary, Literal(65000, datatype=XSD.integer), URIRef(GRAPH_URI)),
        (EX.emp002, EX.hasStatus, Literal("active"), URIRef(GRAPH_URI)),
        
        (EX.emp003, RDF.type, EX.Employee, URIRef(GRAPH_URI)),
        (EX.emp003, EX.hasName, Literal("Carol Davis"), URIRef(GRAPH_URI)),
        (EX.emp003, EX.hasEmployeeId, Literal("EMP003"), URIRef(GRAPH_URI)),
        (EX.emp003, EX.hasDepartment, Literal("Engineering"), URIRef(GRAPH_URI)),
        (EX.emp003, EX.hasSalary, Literal(85000, datatype=XSD.integer), URIRef(GRAPH_URI)),
        (EX.emp003, EX.hasStatus, Literal("active"), URIRef(GRAPH_URI)),
        
        # Product entities for INSERT/DELETE testing
        (EX.prod001, RDF.type, EX.Product, URIRef(GRAPH_URI)),
        (EX.prod001, EX.hasName, Literal("Laptop Pro"), URIRef(GRAPH_URI)),
        (EX.prod001, EX.hasPrice, Literal(1299.99, datatype=XSD.decimal), URIRef(GRAPH_URI)),
        (EX.prod001, EX.hasCategory, Literal("Electronics"), URIRef(GRAPH_URI)),
        (EX.prod001, EX.hasStatus, Literal("available"), URIRef(GRAPH_URI)),
        
        (EX.prod002, RDF.type, EX.Product, URIRef(GRAPH_URI)),
        (EX.prod002, EX.hasName, Literal("Smartphone X"), URIRef(GRAPH_URI)),
        (EX.prod002, EX.hasPrice, Literal(799.99, datatype=XSD.decimal), URIRef(GRAPH_URI)),
        (EX.prod002, EX.hasCategory, Literal("Electronics"), URIRef(GRAPH_URI)),
        (EX.prod002, EX.hasStatus, Literal("discontinued"), URIRef(GRAPH_URI)),
        
        # Account entities for transaction testing
        (EX.account001, RDF.type, EX.Account, URIRef(GRAPH_URI)),
        (EX.account001, EX.hasAccountId, Literal("ACC001"), URIRef(GRAPH_URI)),
        (EX.account001, EX.hasOwner, Literal("Alice Johnson"), URIRef(GRAPH_URI)),
        (EX.account001, EX.hasBalance, Literal(1000.00, datatype=XSD.decimal), URIRef(GRAPH_URI)),
        (EX.account001, EX.hasAccountType, Literal("checking"), URIRef(GRAPH_URI)),
        
        (EX.account002, RDF.type, EX.Account, URIRef(GRAPH_URI)),
        (EX.account002, EX.hasAccountId, Literal("ACC002"), URIRef(GRAPH_URI)),
        (EX.account002, EX.hasOwner, Literal("Bob Smith"), URIRef(GRAPH_URI)),
        (EX.account002, EX.hasBalance, Literal(500.00, datatype=XSD.decimal), URIRef(GRAPH_URI)),
        (EX.account002, EX.hasAccountType, Literal("savings"), URIRef(GRAPH_URI)),
        
        # Inventory items for stock updates
        (EX.item001, RDF.type, EX.InventoryItem, URIRef(GRAPH_URI)),
        (EX.item001, EX.hasItemId, Literal("ITEM001"), URIRef(GRAPH_URI)),
        (EX.item001, EX.hasName, Literal("Widget A"), URIRef(GRAPH_URI)),
        (EX.item001, EX.hasQuantity, Literal(100, datatype=XSD.integer), URIRef(GRAPH_URI)),
        (EX.item001, EX.hasLocation, Literal("Warehouse A"), URIRef(GRAPH_URI)),
        
        (EX.item002, RDF.type, EX.InventoryItem, URIRef(GRAPH_URI)),
        (EX.item002, EX.hasItemId, Literal("ITEM002"), URIRef(GRAPH_URI)),
        (EX.item002, EX.hasName, Literal("Widget B"), URIRef(GRAPH_URI)),
        (EX.item002, EX.hasQuantity, Literal(50, datatype=XSD.integer), URIRef(GRAPH_URI)),
        (EX.item002, EX.hasLocation, Literal("Warehouse B"), URIRef(GRAPH_URI)),
        
        # Customer entities for relationship updates
        (EX.customer001, RDF.type, EX.Customer, URIRef(GRAPH_URI)),
        (EX.customer001, EX.hasCustomerId, Literal("CUST001"), URIRef(GRAPH_URI)),
        (EX.customer001, EX.hasName, Literal("John Doe"), URIRef(GRAPH_URI)),
        (EX.customer001, EX.hasEmail, Literal("john.doe@example.com"), URIRef(GRAPH_URI)),
        (EX.customer001, EX.hasStatus, Literal("active"), URIRef(GRAPH_URI)),
        
        (EX.customer002, RDF.type, EX.Customer, URIRef(GRAPH_URI)),
        (EX.customer002, EX.hasCustomerId, Literal("CUST002"), URIRef(GRAPH_URI)),
        (EX.customer002, EX.hasName, Literal("Jane Smith"), URIRef(GRAPH_URI)),
        (EX.customer002, EX.hasEmail, Literal("jane.smith@example.com"), URIRef(GRAPH_URI)),
        (EX.customer002, EX.hasStatus, Literal("inactive"), URIRef(GRAPH_URI)),
        
        # Order entities for complex updates
        (EX.order001, RDF.type, EX.Order, URIRef(GRAPH_URI)),
        (EX.order001, EX.hasOrderId, Literal("ORD001"), URIRef(GRAPH_URI)),
        (EX.order001, EX.hasCustomer, EX.customer001, URIRef(GRAPH_URI)),
        (EX.order001, EX.hasTotal, Literal(299.99, datatype=XSD.decimal), URIRef(GRAPH_URI)),
        (EX.order001, EX.hasStatus, Literal("pending"), URIRef(GRAPH_URI)),
        (EX.order001, EX.hasOrderDate, Literal("2024-01-15", datatype=XSD.date), URIRef(GRAPH_URI)),
        
        (EX.order002, RDF.type, EX.Order, URIRef(GRAPH_URI)),
        (EX.order002, EX.hasOrderId, Literal("ORD002"), URIRef(GRAPH_URI)),
        (EX.order002, EX.hasCustomer, EX.customer002, URIRef(GRAPH_URI)),
        (EX.order002, EX.hasTotal, Literal(149.99, datatype=XSD.decimal), URIRef(GRAPH_URI)),
        (EX.order002, EX.hasStatus, Literal("shipped"), URIRef(GRAPH_URI)),
        (EX.order002, EX.hasOrderDate, Literal("2024-01-10", datatype=XSD.date), URIRef(GRAPH_URI)),
        
        # Project entities for graph management testing
        (EX.project001, RDF.type, EX.Project, URIRef(GRAPH_URI)),
        (EX.project001, EX.hasProjectId, Literal("PROJ001"), URIRef(GRAPH_URI)),
        (EX.project001, EX.hasName, Literal("Database Migration"), URIRef(GRAPH_URI)),
        (EX.project001, EX.hasStatus, Literal("active"), URIRef(GRAPH_URI)),
        (EX.project001, EX.hasBudget, Literal(50000, datatype=XSD.integer), URIRef(GRAPH_URI)),
        
        (EX.project002, RDF.type, EX.Project, URIRef(GRAPH_URI)),
        (EX.project002, EX.hasProjectId, Literal("PROJ002"), URIRef(GRAPH_URI)),
        (EX.project002, EX.hasName, Literal("UI Redesign"), URIRef(GRAPH_URI)),
        (EX.project002, EX.hasStatus, Literal("planning"), URIRef(GRAPH_URI)),
        (EX.project002, EX.hasBudget, Literal(25000, datatype=XSD.integer), URIRef(GRAPH_URI)),
        
        # Task entities for hierarchical updates
        (EX.task001, RDF.type, EX.Task, URIRef(GRAPH_URI)),
        (EX.task001, EX.hasTaskId, Literal("TASK001"), URIRef(GRAPH_URI)),
        (EX.task001, EX.hasName, Literal("Setup Database"), URIRef(GRAPH_URI)),
        (EX.task001, EX.hasProject, EX.project001, URIRef(GRAPH_URI)),
        (EX.task001, EX.hasAssignee, EX.emp001, URIRef(GRAPH_URI)),
        (EX.task001, EX.hasStatus, Literal("todo"), URIRef(GRAPH_URI)),
        (EX.task001, EX.hasPriority, Literal("high"), URIRef(GRAPH_URI)),
        
        (EX.task002, RDF.type, EX.Task, URIRef(GRAPH_URI)),
        (EX.task002, EX.hasTaskId, Literal("TASK002"), URIRef(GRAPH_URI)),
        (EX.task002, EX.hasName, Literal("Data Migration"), URIRef(GRAPH_URI)),
        (EX.task002, EX.hasProject, EX.project001, URIRef(GRAPH_URI)),
        (EX.task002, EX.hasAssignee, EX.emp003, URIRef(GRAPH_URI)),
        (EX.task002, EX.hasStatus, Literal("in_progress"), URIRef(GRAPH_URI)),
        (EX.task002, EX.hasPriority, Literal("medium"), URIRef(GRAPH_URI)),
        
        # Configuration entities for system updates
        (EX.config001, RDF.type, EX.Configuration, URIRef(GRAPH_URI)),
        (EX.config001, EX.hasConfigKey, Literal("max_connections"), URIRef(GRAPH_URI)),
        (EX.config001, EX.hasConfigValue, Literal("100"), URIRef(GRAPH_URI)),
        (EX.config001, EX.hasConfigType, Literal("integer"), URIRef(GRAPH_URI)),
        (EX.config001, EX.hasEnvironment, Literal("production"), URIRef(GRAPH_URI)),
        
        (EX.config002, RDF.type, EX.Configuration, URIRef(GRAPH_URI)),
        (EX.config002, EX.hasConfigKey, Literal("debug_mode"), URIRef(GRAPH_URI)),
        (EX.config002, EX.hasConfigValue, Literal("false"), URIRef(GRAPH_URI)),
        (EX.config002, EX.hasConfigType, Literal("boolean"), URIRef(GRAPH_URI)),
        (EX.config002, EX.hasEnvironment, Literal("production"), URIRef(GRAPH_URI)),
        
        # Audit log entities for deletion testing
        (EX.audit001, RDF.type, EX.AuditLog, URIRef(GRAPH_URI)),
        (EX.audit001, EX.hasLogId, Literal("LOG001"), URIRef(GRAPH_URI)),
        (EX.audit001, EX.hasAction, Literal("CREATE"), URIRef(GRAPH_URI)),
        (EX.audit001, EX.hasEntity, EX.emp001, URIRef(GRAPH_URI)),
        (EX.audit001, EX.hasTimestamp, Literal("2024-01-01T10:00:00Z", datatype=XSD.dateTime), URIRef(GRAPH_URI)),
        (EX.audit001, EX.hasUser, Literal("admin"), URIRef(GRAPH_URI)),
        
        (EX.audit002, RDF.type, EX.AuditLog, URIRef(GRAPH_URI)),
        (EX.audit002, EX.hasLogId, Literal("LOG002"), URIRef(GRAPH_URI)),
        (EX.audit002, EX.hasAction, Literal("UPDATE"), URIRef(GRAPH_URI)),
        (EX.audit002, EX.hasEntity, EX.emp002, URIRef(GRAPH_URI)),
        (EX.audit002, EX.hasTimestamp, Literal("2024-01-02T14:30:00Z", datatype=XSD.dateTime), URIRef(GRAPH_URI)),
        (EX.audit002, EX.hasUser, Literal("manager"), URIRef(GRAPH_URI)),
        
        # Temporary entities for cleanup testing
        (EX.temp001, RDF.type, EX.TemporaryEntity, URIRef(GRAPH_URI)),
        (EX.temp001, EX.hasName, Literal("Temporary Item 1"), URIRef(GRAPH_URI)),
        (EX.temp001, EX.hasCreatedAt, Literal("2024-01-01T00:00:00Z", datatype=XSD.dateTime), URIRef(GRAPH_URI)),
        (EX.temp001, EX.hasStatus, Literal("temporary"), URIRef(GRAPH_URI)),
        
        (EX.temp002, RDF.type, EX.TemporaryEntity, URIRef(GRAPH_URI)),
        (EX.temp002, EX.hasName, Literal("Temporary Item 2"), URIRef(GRAPH_URI)),
        (EX.temp002, EX.hasCreatedAt, Literal("2024-01-02T00:00:00Z", datatype=XSD.dateTime), URIRef(GRAPH_URI)),
        (EX.temp002, EX.hasStatus, Literal("temporary"), URIRef(GRAPH_URI)),
    ]
    
    # Load UPDATE test data
    await space_impl.add_rdf_quads_batch(SPACE_ID, update_test_data)
    print(f"✅ Added {len(update_test_data)} UPDATE test quads to main graph")
    
    # Add test data to named graphs for graph management testing
    update_test_graph_uri = "http://example.org/update-test"
    named_graph_data = [
        # Test entities in named graph
        (EX.namedEntity1, RDF.type, EX.TestEntity, URIRef(update_test_graph_uri)),
        (EX.namedEntity1, EX.hasName, Literal("Named Entity 1"), URIRef(update_test_graph_uri)),
        (EX.namedEntity1, EX.hasValue, Literal(42, datatype=XSD.integer), URIRef(update_test_graph_uri)),
        
        (EX.namedEntity2, RDF.type, EX.TestEntity, URIRef(update_test_graph_uri)),
        (EX.namedEntity2, EX.hasName, Literal("Named Entity 2"), URIRef(update_test_graph_uri)),
        (EX.namedEntity2, EX.hasValue, Literal(84, datatype=XSD.integer), URIRef(update_test_graph_uri)),
        
        # Product data in named graph
        (EX.namedProduct1, RDF.type, EX.Product, URIRef(update_test_graph_uri)),
        (EX.namedProduct1, EX.hasName, Literal("Named Product"), URIRef(update_test_graph_uri)),
        (EX.namedProduct1, EX.hasPrice, Literal(199.99, datatype=XSD.decimal), URIRef(update_test_graph_uri)),
        (EX.namedProduct1, EX.hasCategory, Literal("Test Category"), URIRef(update_test_graph_uri)),
    ]
    
    await space_impl.add_rdf_quads_batch(SPACE_ID, named_graph_data)
    print(f"✅ Added {len(named_graph_data)} quads to named graph '{update_test_graph_uri}'")
    
    # Add test data to another named graph for COPY/MOVE/ADD testing
    source_graph_uri = "http://example.org/source-graph"
    source_graph_data = [
        (EX.sourceEntity1, RDF.type, EX.SourceEntity, URIRef(source_graph_uri)),
        (EX.sourceEntity1, EX.hasName, Literal("Source Entity 1"), URIRef(source_graph_uri)),
        (EX.sourceEntity1, EX.hasData, Literal("Source data 1"), URIRef(source_graph_uri)),
        
        (EX.sourceEntity2, RDF.type, EX.SourceEntity, URIRef(source_graph_uri)),
        (EX.sourceEntity2, EX.hasName, Literal("Source Entity 2"), URIRef(source_graph_uri)),
        (EX.sourceEntity2, EX.hasData, Literal("Source data 2"), URIRef(source_graph_uri)),
    ]
    
    await space_impl.add_rdf_quads_batch(SPACE_ID, source_graph_data)
    print(f"✅ Added {len(source_graph_data)} quads to source graph '{source_graph_uri}'")
    
    print(f"🔄 UPDATE test data setup complete!")
    
    # ===== VALUES CLAUSE TEST DATA =====
    print("\n🎯 Adding VALUES clause-specific test data...")
    
    # Add specific entities that can be used with VALUES clauses for testing
    values_test_data = [
        # Cities with populations for numeric VALUES testing
        (EX.city1, RDF.type, EX.City, URIRef(GLOBAL_GRAPH_URI)),
        (EX.city1, EX.hasName, Literal("New York"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.city1, EX.hasPopulation, Literal(8336817, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.city1, EX.hasCountry, Literal("USA"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.city2, RDF.type, EX.City, URIRef(GLOBAL_GRAPH_URI)),
        (EX.city2, EX.hasName, Literal("Los Angeles"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.city2, EX.hasPopulation, Literal(3979576, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.city2, EX.hasCountry, Literal("USA"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.city3, RDF.type, EX.City, URIRef(GLOBAL_GRAPH_URI)),
        (EX.city3, EX.hasName, Literal("Chicago"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.city3, EX.hasPopulation, Literal(2693976, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.city3, EX.hasCountry, Literal("USA"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.city4, RDF.type, EX.City, URIRef(GLOBAL_GRAPH_URI)),
        (EX.city4, EX.hasName, Literal("Houston"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.city4, EX.hasPopulation, Literal(2320268, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.city4, EX.hasCountry, Literal("USA"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.city5, RDF.type, EX.City, URIRef(GLOBAL_GRAPH_URI)),
        (EX.city5, EX.hasName, Literal("Phoenix"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.city5, EX.hasPopulation, Literal(1680992, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.city5, EX.hasCountry, Literal("USA"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Countries for string VALUES testing
        (EX.country1, RDF.type, EX.Country, URIRef(GLOBAL_GRAPH_URI)),
        (EX.country1, EX.hasName, Literal("United States"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.country1, EX.hasCode, Literal("USA"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.country1, EX.hasContinent, Literal("North America"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.country2, RDF.type, EX.Country, URIRef(GLOBAL_GRAPH_URI)),
        (EX.country2, EX.hasName, Literal("Canada"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.country2, EX.hasCode, Literal("CAN"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.country2, EX.hasContinent, Literal("North America"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.country3, RDF.type, EX.Country, URIRef(GLOBAL_GRAPH_URI)),
        (EX.country3, EX.hasName, Literal("Mexico"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.country3, EX.hasCode, Literal("MEX"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.country3, EX.hasContinent, Literal("North America"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Books with ISBNs for mixed VALUES testing
        (EX.book1, RDF.type, EX.Book, URIRef(GLOBAL_GRAPH_URI)),
        (EX.book1, EX.hasTitle, Literal("The Great Gatsby"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.book1, EX.hasISBN, Literal("978-0-7432-7356-5"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.book1, EX.hasAuthor, Literal("F. Scott Fitzgerald"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.book1, EX.hasYear, Literal(1925, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.book2, RDF.type, EX.Book, URIRef(GLOBAL_GRAPH_URI)),
        (EX.book2, EX.hasTitle, Literal("To Kill a Mockingbird"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.book2, EX.hasISBN, Literal("978-0-06-112008-4"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.book2, EX.hasAuthor, Literal("Harper Lee"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.book2, EX.hasYear, Literal(1960, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.book3, RDF.type, EX.Book, URIRef(GLOBAL_GRAPH_URI)),
        (EX.book3, EX.hasTitle, Literal("1984"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.book3, EX.hasISBN, Literal("978-0-452-28423-4"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.book3, EX.hasAuthor, Literal("George Orwell"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.book3, EX.hasYear, Literal(1949, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        
        # Colors for simple VALUES testing
        (EX.color1, RDF.type, EX.Color, URIRef(GLOBAL_GRAPH_URI)),
        (EX.color1, EX.hasName, Literal("Red"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.color1, EX.hasHex, Literal("#FF0000"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.color2, RDF.type, EX.Color, URIRef(GLOBAL_GRAPH_URI)),
        (EX.color2, EX.hasName, Literal("Green"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.color2, EX.hasHex, Literal("#00FF00"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.color3, RDF.type, EX.Color, URIRef(GLOBAL_GRAPH_URI)),
        (EX.color3, EX.hasName, Literal("Blue"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.color3, EX.hasHex, Literal("#0000FF"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.color4, RDF.type, EX.Color, URIRef(GLOBAL_GRAPH_URI)),
        (EX.color4, EX.hasName, Literal("Yellow"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.color4, EX.hasHex, Literal("#FFFF00"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.color5, RDF.type, EX.Color, URIRef(GLOBAL_GRAPH_URI)),
        (EX.color5, EX.hasName, Literal("Purple"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.color5, EX.hasHex, Literal("#800080"), URIRef(GLOBAL_GRAPH_URI)),
        
        # ========== MINUS Pattern Test Data ==========
        
        # People with exclusion flags for MINUS testing
        (EX.excluded_person1, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.excluded_person1, EX.hasName, Literal("Excluded Person 1"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.excluded_person1, EX.hasAge, Literal(25, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.excluded_person1, EX.isExcluded, Literal("true"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.excluded_person2, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.excluded_person2, EX.hasName, Literal("Excluded Person 2"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.excluded_person2, EX.hasAge, Literal(35, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.excluded_person2, EX.isExcluded, Literal("true"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Regular people without exclusion flags (for comparison)
        (EX.regular_person1, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.regular_person1, EX.hasName, Literal("Regular Person 1"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.regular_person1, EX.hasAge, Literal(30, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.regular_person2, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.regular_person2, EX.hasName, Literal("Regular Person 2"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.regular_person2, EX.hasAge, Literal(40, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        
        # Products with discontinuation flags for MINUS testing
        (EX.discontinued_product1, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.discontinued_product1, EX.hasName, Literal("Discontinued Product 1"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.discontinued_product1, EX.hasPrice, Literal(99.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.discontinued_product1, EX.isDiscontinued, Literal("true"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.discontinued_product2, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.discontinued_product2, EX.hasName, Literal("Discontinued Product 2"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.discontinued_product2, EX.hasPrice, Literal(149.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.discontinued_product2, EX.isDiscontinued, Literal("true"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Active products without discontinuation flags
        (EX.active_product1, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.active_product1, EX.hasName, Literal("Active Product 1"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.active_product1, EX.hasPrice, Literal(79.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.active_product2, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.active_product2, EX.hasName, Literal("Active Product 2"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.active_product2, EX.hasPrice, Literal(129.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        
        # People with departments for complex MINUS testing
        (EX.hr_person1, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.hr_person1, EX.hasName, Literal("HR Person 1"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.hr_person1, EX.hasAge, Literal(32, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.hr_person1, EX.hasDepartment, Literal("HR"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.it_person1, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.it_person1, EX.hasName, Literal("IT Person 1"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.it_person1, EX.hasAge, Literal(28, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.it_person1, EX.hasDepartment, Literal("IT"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.it_person2, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.it_person2, EX.hasName, Literal("IT Person 2"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.it_person2, EX.hasAge, Literal(35, datatype=XSD.integer), URIRef(GLOBAL_GRAPH_URI)),
        (EX.it_person2, EX.hasDepartment, Literal("IT"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Products with categories for complex MINUS testing
        (EX.electronics_product1, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.electronics_product1, EX.hasName, Literal("Electronics Product 1"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.electronics_product1, EX.hasPrice, Literal(199.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.electronics_product1, EX.hasCategory, Literal("electronics"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.electronics_product2, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.electronics_product2, EX.hasName, Literal("Electronics Product 2"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.electronics_product2, EX.hasPrice, Literal(299.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.electronics_product2, EX.hasCategory, Literal("electronics"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.furniture_product1, RDF.type, EX.Product, URIRef(GLOBAL_GRAPH_URI)),
        (EX.furniture_product1, EX.hasName, Literal("Furniture Product 1"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.furniture_product1, EX.hasPrice, Literal(89.99, datatype=XSD.decimal), URIRef(GLOBAL_GRAPH_URI)),
        (EX.furniture_product1, EX.hasCategory, Literal("furniture"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Global entities for edge case testing (no shared variables)
        (EX.global_flag, EX.isGlobal, Literal("true"), URIRef(GLOBAL_GRAPH_URI)),
        
        # People with manager roles for nested MINUS testing
        (EX.hr_manager, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.hr_manager, EX.hasName, Literal("HR Manager"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.hr_manager, EX.hasDepartment, Literal("HR"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.hr_manager, EX.hasRole, Literal("manager"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.hr_employee, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.hr_employee, EX.hasName, Literal("HR Employee"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.hr_employee, EX.hasDepartment, Literal("HR"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Additional people for email testing with MINUS
        (EX.person_with_email1, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person_with_email1, EX.hasName, Literal("Person With Email 1"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person_with_email1, EX.hasEmail, Literal("person1@example.org"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.person_with_email2, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.person_with_email2, EX.hasName, Literal("Person With Email 2"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person_with_email2, EX.hasEmail, Literal("person2@example.org"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.person_with_email2, EX.isExcluded, Literal("true"), URIRef(GLOBAL_GRAPH_URI)),
    ]
    
    # ===== PROPERTY PATHS TEST DATA =====
    print("\n🛤️  Adding property path test data...")
    
    # Property path test data for transitive relationships, sequences, and alternatives
    property_path_test_data = [
        # Social network data for transitive knows relationships (foaf:knows+, foaf:knows*)
        (EX.alice, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.alice, EX.hasName, Literal("Alice"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.alice, EX.knows, EX.bob, URIRef(GLOBAL_GRAPH_URI)),
        (EX.alice, EX.directlyKnows, EX.bob, URIRef(GLOBAL_GRAPH_URI)),  # Alternative property
        
        (EX.bob, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.bob, EX.hasName, Literal("Bob"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.bob, EX.knows, EX.charlie, URIRef(GLOBAL_GRAPH_URI)),
        (EX.bob, EX.directlyKnows, EX.charlie, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.charlie, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.charlie, EX.hasName, Literal("Charlie"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.charlie, EX.knows, EX.david, URIRef(GLOBAL_GRAPH_URI)),
        (EX.charlie, EX.directlyKnows, EX.david, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.david, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.david, EX.hasName, Literal("David"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.david, EX.knows, EX.eve, URIRef(GLOBAL_GRAPH_URI)),
        (EX.david, EX.directlyKnows, EX.eve, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.eve, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.eve, EX.hasName, Literal("Eve"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.eve, EX.knows, EX.alice, URIRef(GLOBAL_GRAPH_URI)),  # Creates cycle
        (EX.eve, EX.directlyKnows, EX.alice, URIRef(GLOBAL_GRAPH_URI)),
        
        # Additional names and properties for sequence path testing (knows/hasName)
        (EX.frank, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.frank, EX.hasName, Literal("Frank"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.frank, EX.nickname, Literal("Frankie"), URIRef(GLOBAL_GRAPH_URI)),  # Alternative name property
        (EX.alice, EX.knows, EX.frank, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.grace, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.grace, EX.hasName, Literal("Grace"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.grace, EX.nickname, Literal("Gracie"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.bob, EX.knows, EX.grace, URIRef(GLOBAL_GRAPH_URI)),
        
        # Organizational hierarchy for transitive management relationships
        (EX.ceo, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.ceo, EX.hasName, Literal("CEO"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.ceo, EX.hasTitle, Literal("Chief Executive Officer"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.vp_engineering, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.vp_engineering, EX.hasName, Literal("VP Engineering"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.vp_engineering, EX.hasTitle, Literal("Vice President of Engineering"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.ceo, EX.manages, EX.vp_engineering, URIRef(GLOBAL_GRAPH_URI)),
        (EX.ceo, EX.supervises, EX.vp_engineering, URIRef(GLOBAL_GRAPH_URI)),  # Alternative management property
        
        (EX.director_backend, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.director_backend, EX.hasName, Literal("Backend Director"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.director_backend, EX.hasTitle, Literal("Director of Backend Engineering"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.vp_engineering, EX.manages, EX.director_backend, URIRef(GLOBAL_GRAPH_URI)),
        (EX.vp_engineering, EX.supervises, EX.director_backend, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.senior_dev1, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.senior_dev1, EX.hasName, Literal("Senior Developer 1"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.senior_dev1, EX.hasTitle, Literal("Senior Software Engineer"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.director_backend, EX.manages, EX.senior_dev1, URIRef(GLOBAL_GRAPH_URI)),
        (EX.director_backend, EX.supervises, EX.senior_dev1, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.junior_dev1, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.junior_dev1, EX.hasName, Literal("Junior Developer 1"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.junior_dev1, EX.hasTitle, Literal("Software Engineer"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.senior_dev1, EX.manages, EX.junior_dev1, URIRef(GLOBAL_GRAPH_URI)),
        (EX.senior_dev1, EX.supervises, EX.junior_dev1, URIRef(GLOBAL_GRAPH_URI)),
        
        # Parallel branch for testing multiple paths
        (EX.director_frontend, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.director_frontend, EX.hasName, Literal("Frontend Director"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.director_frontend, EX.hasTitle, Literal("Director of Frontend Engineering"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.vp_engineering, EX.manages, EX.director_frontend, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.senior_dev2, RDF.type, EX.Employee, URIRef(GLOBAL_GRAPH_URI)),
        (EX.senior_dev2, EX.hasName, Literal("Senior Developer 2"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.senior_dev2, EX.hasTitle, Literal("Senior Frontend Engineer"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.director_frontend, EX.manages, EX.senior_dev2, URIRef(GLOBAL_GRAPH_URI)),
        
        # Family relationships for inverse path testing (~parentOf = childOf)
        (EX.parent1, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.parent1, EX.hasName, Literal("Parent 1"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.parent2, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.parent2, EX.hasName, Literal("Parent 2"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.child1, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.child1, EX.hasName, Literal("Child 1"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.parent1, EX.parentOf, EX.child1, URIRef(GLOBAL_GRAPH_URI)),
        (EX.parent2, EX.parentOf, EX.child1, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.child2, RDF.type, EX.Person, URIRef(GLOBAL_GRAPH_URI)),
        (EX.child2, EX.hasName, Literal("Child 2"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.parent1, EX.parentOf, EX.child2, URIRef(GLOBAL_GRAPH_URI)),
        
        # Location hierarchy for nested sequence paths (locatedIn+/hasName)
        (EX.country_usa, RDF.type, EX.Location, URIRef(GLOBAL_GRAPH_URI)),
        (EX.country_usa, EX.hasName, Literal("United States"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.country_usa, EX.locationType, Literal("country"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.state_california, RDF.type, EX.Location, URIRef(GLOBAL_GRAPH_URI)),
        (EX.state_california, EX.hasName, Literal("California"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.state_california, EX.locationType, Literal("state"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.state_california, EX.locatedIn, EX.country_usa, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.city_san_francisco, RDF.type, EX.Location, URIRef(GLOBAL_GRAPH_URI)),
        (EX.city_san_francisco, EX.hasName, Literal("San Francisco"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.city_san_francisco, EX.locationType, Literal("city"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.city_san_francisco, EX.locatedIn, EX.state_california, URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.neighborhood_mission, RDF.type, EX.Location, URIRef(GLOBAL_GRAPH_URI)),
        (EX.neighborhood_mission, EX.hasName, Literal("Mission District"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.neighborhood_mission, EX.locationType, Literal("neighborhood"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.neighborhood_mission, EX.locatedIn, EX.city_san_francisco, URIRef(GLOBAL_GRAPH_URI)),
        
        # Buildings and addresses for deep nesting
        (EX.building_123_main, RDF.type, EX.Location, URIRef(GLOBAL_GRAPH_URI)),
        (EX.building_123_main, EX.hasName, Literal("123 Main Street"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.building_123_main, EX.locationType, Literal("building"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.building_123_main, EX.locatedIn, EX.neighborhood_mission, URIRef(GLOBAL_GRAPH_URI)),
        
        # Transportation network for alternative path testing (bus|train|subway)
        (EX.station_a, RDF.type, EX.TransportStation, URIRef(GLOBAL_GRAPH_URI)),
        (EX.station_a, EX.hasName, Literal("Station A"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.station_b, RDF.type, EX.TransportStation, URIRef(GLOBAL_GRAPH_URI)),
        (EX.station_b, EX.hasName, Literal("Station B"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.station_c, RDF.type, EX.TransportStation, URIRef(GLOBAL_GRAPH_URI)),
        (EX.station_c, EX.hasName, Literal("Station C"), URIRef(GLOBAL_GRAPH_URI)),
        
        # Multiple transport connections between stations
        (EX.station_a, EX.busRoute, EX.station_b, URIRef(GLOBAL_GRAPH_URI)),
        (EX.station_a, EX.trainRoute, EX.station_c, URIRef(GLOBAL_GRAPH_URI)),
        (EX.station_b, EX.subwayRoute, EX.station_c, URIRef(GLOBAL_GRAPH_URI)),
        (EX.station_b, EX.busRoute, EX.station_c, URIRef(GLOBAL_GRAPH_URI)),
        
        # Cycle in transport network
        (EX.station_c, EX.trainRoute, EX.station_a, URIRef(GLOBAL_GRAPH_URI)),
        
        # Academic relationships for complex path combinations
        (EX.professor1, RDF.type, EX.Academic, URIRef(GLOBAL_GRAPH_URI)),
        (EX.professor1, EX.hasName, Literal("Professor Smith"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.professor1, EX.hasTitle, Literal("Professor"), URIRef(GLOBAL_GRAPH_URI)),
        
        (EX.student1, RDF.type, EX.Academic, URIRef(GLOBAL_GRAPH_URI)),
        (EX.student1, EX.hasName, Literal("Student Jones"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.student1, EX.hasTitle, Literal("Graduate Student"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.professor1, EX.advises, EX.student1, URIRef(GLOBAL_GRAPH_URI)),
        (EX.professor1, EX.mentors, EX.student1, URIRef(GLOBAL_GRAPH_URI)),  # Alternative relationship
        
        (EX.student2, RDF.type, EX.Academic, URIRef(GLOBAL_GRAPH_URI)),
        (EX.student2, EX.hasName, Literal("Student Brown"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.student2, EX.hasTitle, Literal("PhD Candidate"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.student1, EX.collaboratesWith, EX.student2, URIRef(GLOBAL_GRAPH_URI)),
        
        # Research papers for sequence paths (advises+/hasName, collaboratesWith/hasTitle)
        (EX.paper1, RDF.type, EX.ResearchPaper, URIRef(GLOBAL_GRAPH_URI)),
        (EX.paper1, EX.hasTitle, Literal("Advanced Graph Theory"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.student1, EX.authored, EX.paper1, URIRef(GLOBAL_GRAPH_URI)),
        (EX.student2, EX.authored, EX.paper1, URIRef(GLOBAL_GRAPH_URI)),
        
        # Self-referential relationships for zero-or-more testing
        (EX.node1, RDF.type, EX.GraphNode, URIRef(GLOBAL_GRAPH_URI)),
        (EX.node1, EX.hasName, Literal("Node 1"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.node1, EX.connectsTo, EX.node1, URIRef(GLOBAL_GRAPH_URI)),  # Self-loop
        
        (EX.node2, RDF.type, EX.GraphNode, URIRef(GLOBAL_GRAPH_URI)),
        (EX.node2, EX.hasName, Literal("Node 2"), URIRef(GLOBAL_GRAPH_URI)),
        (EX.node1, EX.connectsTo, EX.node2, URIRef(GLOBAL_GRAPH_URI)),
        (EX.node2, EX.connectsTo, EX.node1, URIRef(GLOBAL_GRAPH_URI)),  # Bidirectional
    ]
    
    # Add property path test data to global graph using space_impl
    await space_impl.add_rdf_quads_batch(SPACE_ID, property_path_test_data)
    print(f"   Added {len(property_path_test_data)} property path test quads to global graph")
    print("   - Social network with transitive 'knows' relationships (Alice -> Bob -> Charlie -> David -> Eve -> Alice)")
    print("   - Organizational hierarchy with 'manages' relationships (CEO -> VP -> Directors -> Developers)")
    print("   - Family relationships with 'parentOf' for inverse path testing")
    print("   - Location hierarchy (Country -> State -> City -> Neighborhood -> Building)")
    print("   - Transportation network with alternative routes (bus|train|subway)")
    print("   - Academic relationships (professor advises/mentors students, students collaborate)")
    print("   - Self-referential graph nodes for zero-or-more path testing")
    
    # Add VALUES test data to global graph using space_impl
    await space_impl.add_rdf_quads_batch(SPACE_ID, values_test_data)
    print(f"   Added {len(values_test_data)} VALUES-specific test quads to global graph")
    print("   - Cities with populations for numeric VALUES testing")
    print("   - Countries with codes for string VALUES testing")
    print("   - Books with ISBNs for mixed VALUES testing")
    print("   - Colors with hex codes for simple VALUES testing")
    
    print(f"💡 Use space_id='{SPACE_ID}' and graph_uri='{GRAPH_URI}' for testing")
    print(f"💡 Global graph data available at '{GLOBAL_GRAPH_URI}'")
    
    # Implementation cleanup handled automatically

async def reload_test_data_for_reset():
    """
    Simple wrapper function that can be called by external scripts like CRUD tests.
    This just calls the main reload_test_data function.
    """
    await reload_test_data()

if __name__ == "__main__":
    asyncio.run(reload_test_data())
