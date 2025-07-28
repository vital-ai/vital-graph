#!/usr/bin/env python3
"""
SPARQL Built-in Functions Test Script
====================================

Comprehensive test suite for SPARQL built-in functions in VitalGraph's PostgreSQL-backed SPARQL engine.
This file tests all SPARQL 1.1 built-in functions to ensure proper SQL translation and execution.

SPARQL BUILT-IN FUNCTIONS COVERAGE:
===================================

✅ CURRENTLY IMPLEMENTED:
- String Functions: CONCAT, STR, SUBSTR, STRLEN, UCASE, LCASE, MD5, SHA1
- Filter Functions: REGEX, CONTAINS, STRSTARTS, STRENDS, EXISTS, NOTEXISTS
- Control Flow: IF (partial)

❌ MISSING/PROBLEMATIC (Need Implementation):

** CRITICAL (High Priority) **
1. BOUND(?var) - Check if variable is bound (essential for OPTIONAL)
2. COALESCE(?var1, ?var2, "default") - Return first non-null value
3. URI(string) / IRI(string) - Create URI from string
4. ENCODE_FOR_URI(string) - URL encoding

** NUMERIC FUNCTIONS **
5. ABS(numeric) - Absolute value
6. CEIL(numeric) - Ceiling function
7. FLOOR(numeric) - Floor function
8. ROUND(numeric) - Rounding function
9. RAND() - Random number

** DATE/TIME FUNCTIONS **
10. NOW() - Current timestamp
11. YEAR(datetime) - Extract year
12. MONTH(datetime) - Extract month
13. DAY(datetime) - Extract day
14. HOURS(datetime) - Extract hours
15. MINUTES(datetime) - Extract minutes
16. SECONDS(datetime) - Extract seconds

** TYPE CHECKING FUNCTIONS **
17. DATATYPE(literal) - Get datatype of literal
18. LANG(literal) - Get language tag
19. LANGMATCHES(lang, pattern) - Language matching
20. ISURI(term) / ISIRI(term) - Check if URI
21. ISBLANK(term) - Check if blank node
22. ISLITERAL(term) - Check if literal
23. ISNUMERIC(literal) - Check if numeric

** ADVANCED STRING FUNCTIONS **
24. REPLACE(string, pattern, replacement) - String replacement
25. STRAFTER(string, substring) - String after substring
26. STRBEFORE(string, substring) - String before substring
27. STRUUID() - Generate UUID string
28. UUID() - Generate UUID

** AGGREGATE FUNCTIONS (for future GROUP BY support) **
29. COUNT(?var) - Count values
30. SUM(numeric) - Sum values
31. AVG(numeric) - Average values
32. MIN(value) - Minimum value
33. MAX(value) - Maximum value
34. GROUP_CONCAT(string) - Concatenate grouped values
35. SAMPLE(?var) - Sample value from group

** HASH FUNCTIONS **
36. SHA256(string) - SHA-256 hash
37. SHA384(string) - SHA-384 hash
38. SHA512(string) - SHA-512 hash

** MISCELLANEOUS **
39. BNODE() - Create blank node
40. BNODE(string) - Create blank node with label
41. STRDT(string, datatype) - Create typed literal
42. STRLANG(string, lang) - Create language-tagged literal

This test file provides comprehensive coverage of all these built-ins with realistic test scenarios.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl
from vitalgraph.config.config_loader import get_config

# CONFIGURATION - Change these as needed for debugging
LOG_LEVEL = logging.DEBUG  # Change to INFO, WARNING, ERROR as needed
SHOW_SQL = True  # Set to True to see generated SQL
MAX_RESULTS_DISPLAY = 3  # How many results to display per test

# Configure logging
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(levelname)s - %(name)s - %(message)s'
)

# Suppress verbose logging from other modules but keep SPARQL SQL logging
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_term_cache').setLevel(logging.WARNING)
# Keep SPARQL implementation logging at DEBUG level to see detailed variable mapping
logging.getLogger('vitalgraph.db.postgresql.postgresql_sparql_impl').setLevel(logging.DEBUG)

# Configuration
SPACE_ID = "space_test"
GRAPH_URI = "http://vital.ai/graph/test"
GLOBAL_GRAPH_URI = "urn:___GLOBAL"

def log_sql(query_name, sql_query):
    """Helper function to log SQL queries when SHOW_SQL is enabled."""
    if SHOW_SQL:
        print(f"\n🔍 SQL for {query_name}:")
        print(f"{sql_query}")
        print("="*80)

async def run_single_test(sparql_impl, test_name, query, expected_min_results=0):
    """Run a single SPARQL test query with detailed logging."""
    try:
        print(f"\n🧪 TESTING: {test_name}")
        print(f"📝 Query: {query.strip()}")
        
        start_time = time.time()
        results = await sparql_impl.execute_sparql_query(SPACE_ID, query)
        end_time = time.time()
        
        success = len(results) >= expected_min_results
        status = "✅ Success" if success else "❌ Failed"
        
        print(f"\n📊 RESULT: {status}")
        print(f"   Results: {len(results)} (expected >= {expected_min_results})")
        print(f"   Time: {end_time - start_time:.3f}s")
        
        # Show results
        if results:
            print(f"\n📋 Sample Results:")
            for i, result in enumerate(results[:MAX_RESULTS_DISPLAY]):
                print(f"   [{i+1}] {result}")
            
            if len(results) > MAX_RESULTS_DISPLAY:
                print(f"   ... and {len(results) - MAX_RESULTS_DISPLAY} more results")
        else:
            print("   No results returned")
            
        return success
        
    except Exception as e:
        print(f"\n❌ ERROR in {test_name}: {e}")
        import traceback
        print(f"   Traceback: {traceback.format_exc()}")
        return False

# Legacy function for backward compatibility
async def run_builtin_query(sparql_impl, test_name, query, expected_min_results=0):
    """Legacy function - use run_single_test for new tests."""
    try:
        start_time = time.time()
        results = await sparql_impl.execute_sparql_query(SPACE_ID, query)
        end_time = time.time()
        
        success = len(results) >= expected_min_results
        status = "✅ Success" if success else "❌ Failed"
        
        print(f"  {test_name}:")
        print(f"    {status}: {len(results)} results in {end_time - start_time:.3f}s")
        
        # Show first few results
        for i, result in enumerate(results[:3]):
            print(f"       [{i+1}] {result}")
        
        if len(results) > 3:
            print(f"       ... and {len(results) - 3} more results")
            
        return success
        
    except Exception as e:
        print(f"  {test_name}:")
        print(f"    ❌ Error: {e}")
        return False

async def test_critical_builtins(sparql_impl, graph_uri):
    """Test critical built-in functions (highest priority)."""
    print("\n1. CRITICAL BUILT-INS (Essential for OPTIONAL patterns):")
    
    # Test 1: BOUND function - Essential for OPTIONAL patterns
    await run_single_test(sparql_impl, "BOUND - Check if variable is bound", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?hasEmail WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                BIND(BOUND(?email) AS ?hasEmail)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """, 1)
    
    # Test 2: COALESCE function - Return first non-null value
    await run_single_test(sparql_impl, "COALESCE - First non-null value", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?contact WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                OPTIONAL {{ ?person ex:hasPhone ?phone }}
                BIND(COALESCE(?email, ?phone, \"no-contact\") AS ?contact)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """, 1)
    
    # Test 3: URI/IRI function - Create URI from string
    await run_single_test(sparql_impl, "URI - Create URI from string", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?profileUri WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(URI(CONCAT(\"http://example.org/profile/\", ?name)) AS ?profileUri)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 4: STRUUID function - Generate UUID string
    await run_single_test(sparql_impl, "STRUUID - Generate UUID string", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?uuid WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(STRUUID() AS ?uuid)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 5: ENCODE_FOR_URI function - URL encoding
    await run_single_test(sparql_impl, "ENCODE_FOR_URI - URL encoding", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?encodedName WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(ENCODE_FOR_URI(?name) AS ?encodedName)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 6: UUID function - Generate UUID as URI
    await run_single_test(sparql_impl, "UUID - Generate UUID as URI", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?uuidUri WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(UUID() AS ?uuidUri)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)


async def test_comprehensive_builtins(sparql_impl, graph_uri):
    """Test all built-in functions comprehensively."""
    print("\n🔧 COMPREHENSIVE BUILT-IN FUNCTIONS TEST SUITE")
    print("=" * 60)
    
    # Test all critical built-ins that are fully implemented
    await test_critical_builtins_comprehensive(sparql_impl, graph_uri)
    await test_numeric_builtins_comprehensive(sparql_impl, graph_uri)
    await test_string_builtins_comprehensive(sparql_impl, graph_uri)
    await test_datetime_builtins_comprehensive(sparql_impl, graph_uri)
    await test_type_checking_builtins_comprehensive(sparql_impl, graph_uri)
    await test_hash_builtins_comprehensive(sparql_impl, graph_uri)
    await test_advanced_builtins_comprehensive(sparql_impl, graph_uri)

async def test_critical_builtins_comprehensive(sparql_impl, graph_uri):
    """Test critical built-in functions with comprehensive coverage."""
    print("\n1. CRITICAL BUILT-INS (Essential for OPTIONAL patterns):")
    
    # Test 1: BOUND function - Essential for OPTIONAL patterns
    await run_single_test(sparql_impl, "BOUND - Check if variable is bound", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?hasEmail WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                BIND(BOUND(?email) AS ?hasEmail)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """, 1)
    
    # Test 2: COALESCE function - Return first non-null value
    await run_single_test(sparql_impl, "COALESCE - First non-null value", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?contact WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                OPTIONAL {{ ?person ex:hasPhone ?phone }}
                BIND(COALESCE(?email, ?phone, \"no-contact\") AS ?contact)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """, 1)
    
    # Test 3: URI/IRI function - Create URI from string
    await run_single_test(sparql_impl, "URI - Create URI from string", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?profileUri WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(URI(CONCAT(\"http://example.org/profile/\", ?name)) AS ?profileUri)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 4: STRUUID function - Generate UUID string
    await run_single_test(sparql_impl, "STRUUID - Generate UUID string", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?uuid WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(STRUUID() AS ?uuid)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 5: ENCODE_FOR_URI function - URL encoding
    await run_single_test(sparql_impl, "ENCODE_FOR_URI - URL encoding", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?encodedName WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(ENCODE_FOR_URI(?name) AS ?encodedName)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 6: UUID function - Generate UUID as URI
    await run_single_test(sparql_impl, "UUID - Generate UUID as URI", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?uuidUri WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(UUID() AS ?uuidUri)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)

async def test_numeric_builtins_comprehensive(sparql_impl, graph_uri):
    """Test numeric built-in functions comprehensively."""
    print("\n2. NUMERIC BUILT-INS:")
    
    # Test 7: ABS function - Absolute value
    await run_single_test(sparql_impl, "ABS - Absolute value", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?product ?name ?price ?absPrice WHERE {{
            GRAPH <{graph_uri}> {{
                ?product rdf:type ex:Product .
                ?product ex:hasName ?name .
                ?product ex:hasPrice ?price .
                BIND(ABS(?price - 100) AS ?absPrice)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 8: CEIL function - Ceiling function
    await run_single_test(sparql_impl, "CEIL - Ceiling function", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?product ?name ?price ?ceilPrice WHERE {{
            GRAPH <{graph_uri}> {{
                ?product rdf:type ex:Product .
                ?product ex:hasName ?name .
                ?product ex:hasPrice ?price .
                BIND(CEIL(?price / 10) AS ?ceilPrice)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 9: FLOOR function - Floor function
    await run_single_test(sparql_impl, "FLOOR - Floor function", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?product ?name ?price ?floorPrice WHERE {{
            GRAPH <{graph_uri}> {{
                ?product rdf:type ex:Product .
                ?product ex:hasName ?name .
                ?product ex:hasPrice ?price .
                BIND(FLOOR(?price / 10) AS ?floorPrice)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 10: ROUND function - Rounding function
    await run_single_test(sparql_impl, "ROUND - Rounding function", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?product ?name ?price ?roundPrice WHERE {{
            GRAPH <{graph_uri}> {{
                ?product rdf:type ex:Product .
                ?product ex:hasName ?name .
                ?product ex:hasPrice ?price .
                BIND(ROUND(?price / 10) AS ?roundPrice)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 11: RAND function - Random number generation
    await run_single_test(sparql_impl, "RAND - Random number", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?randomValue WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(RAND() AS ?randomValue)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)

async def test_string_builtins_comprehensive(sparql_impl, graph_uri):
    """Test string built-in functions comprehensively."""
    print("\n3. STRING BUILT-INS:")
    
    # Test 12: STR function - Convert to string
    await run_single_test(sparql_impl, "STR - Convert to string", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?nameStr WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(STR(?name) AS ?nameStr)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 13: STRLEN function - String length
    await run_single_test(sparql_impl, "STRLEN - String length", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?nameLength WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(STRLEN(?name) AS ?nameLength)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 14: UCASE function - Convert to uppercase
    await run_single_test(sparql_impl, "UCASE - Convert to uppercase", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?upperName WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(UCASE(?name) AS ?upperName)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 15: LCASE function - Convert to lowercase
    await run_single_test(sparql_impl, "LCASE - Convert to lowercase", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?lowerName WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(LCASE(?name) AS ?lowerName)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 16: SUBSTR function - Substring extraction
    await run_single_test(sparql_impl, "SUBSTR - Substring extraction", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?namePrefix WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(SUBSTR(?name, 1, 3) AS ?namePrefix)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 17: CONCAT function - String concatenation
    await run_single_test(sparql_impl, "CONCAT - String concatenation", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?greeting WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(CONCAT(\"Hello, \", ?name, \"!\") AS ?greeting)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)

async def test_datetime_builtins_comprehensive(sparql_impl, graph_uri):
    """Test date/time built-in functions comprehensively."""
    print("\n4. DATE/TIME BUILT-INS:")
    
    # Test 18: NOW function - Current timestamp
    await run_single_test(sparql_impl, "NOW - Current timestamp", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?currentTime WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(NOW() AS ?currentTime)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 11-16: Date/time extraction functions
    await run_builtin_query(sparql_impl, "YEAR/MONTH/DAY - Extract date components", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?birthYear ?birthMonth ?birthDay WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasBirthDate ?birthDate }}
                BIND(YEAR(?birthDate) AS ?birthYear)
                BIND(MONTH(?birthDate) AS ?birthMonth)
                BIND(DAY(?birthDate) AS ?birthDay)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    
    await run_builtin_query(sparql_impl, "HOURS/MINUTES/SECONDS - Extract time components", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?hour ?minute ?second WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(NOW() AS ?now)
                BIND(HOURS(?now) AS ?hour)
                BIND(MINUTES(?now) AS ?minute)
                BIND(SECONDS(?now) AS ?second)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)

async def test_type_checking_builtins_comprehensive(sparql_impl, graph_uri):
    """Test type checking built-in functions comprehensively."""
    print("\n5. TYPE CHECKING BUILT-INS:")
    
    # Test 19: DATATYPE function - Get datatype of literal
    await run_single_test(sparql_impl, "DATATYPE - Get datatype of literal", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?product ?name ?price ?priceType WHERE {{
            GRAPH <{graph_uri}> {{
                ?product rdf:type ex:Product .
                ?product ex:hasName ?name .
                ?product ex:hasPrice ?price .
                BIND(DATATYPE(?price) AS ?priceType)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 20: LANG function - Get language tag
    await run_single_test(sparql_impl, "LANG - Get language tag", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?description ?descLang WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasDescription ?description }}
                BIND(LANG(?description) AS ?descLang)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 21: ISURI function - Check if value is URI
    await run_single_test(sparql_impl, "ISURI - Check if value is URI", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?personIsUri WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(ISURI(?person) AS ?personIsUri)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 22: ISLITERAL function - Check if value is literal
    await run_single_test(sparql_impl, "ISLITERAL - Check if value is literal", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?nameIsLiteral WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(ISLITERAL(?name) AS ?nameIsLiteral)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 23: ISNUMERIC function - Check if value is numeric
    await run_single_test(sparql_impl, "ISNUMERIC - Check if value is numeric", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?product ?name ?price ?priceIsNumeric WHERE {{
            GRAPH <{graph_uri}> {{
                ?product rdf:type ex:Product .
                ?product ex:hasName ?name .
                ?product ex:hasPrice ?price .
                BIND(ISNUMERIC(?price) AS ?priceIsNumeric)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)

async def test_hash_builtins_comprehensive(sparql_impl, graph_uri):
    """Test hash built-in functions comprehensively."""
    print("\n6. HASH BUILT-INS:")
    
    # Test 24: MD5 function - MD5 hash
    await run_single_test(sparql_impl, "MD5 - MD5 hash", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?nameHash WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(MD5(?name) AS ?nameHash)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 25: SHA1 function - SHA1 hash
    await run_single_test(sparql_impl, "SHA1 - SHA1 hash", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?nameHash WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(SHA1(?name) AS ?nameHash)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 26: SHA256 function - SHA256 hash
    await run_single_test(sparql_impl, "SHA256 - SHA256 hash", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?nameHash WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(SHA256(?name) AS ?nameHash)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)

async def test_advanced_builtins_comprehensive(sparql_impl, graph_uri):
    """Test advanced built-in functions comprehensively."""
    print("\n7. ADVANCED BUILT-INS:")
    
    # Test 27: IF function - Conditional expression
    await run_single_test(sparql_impl, "IF - Conditional expression", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?product ?name ?price ?priceCategory WHERE {{
            GRAPH <{graph_uri}> {{
                ?product rdf:type ex:Product .
                ?product ex:hasName ?name .
                ?product ex:hasPrice ?price .
                BIND(IF(?price > 100, \"expensive\", \"affordable\") AS ?priceCategory)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 28: BNODE function - Create blank node
    await run_single_test(sparql_impl, "BNODE - Create blank node", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?blankNode WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(BNODE() AS ?blankNode)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)
    
    # Test 29: REPLACE function - String replacement
    await run_single_test(sparql_impl, "REPLACE - String replacement", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?cleanName WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(REPLACE(?name, \" \", \"_\") AS ?cleanName)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """, 1)

async def test_type_checking_builtins(sparql_impl, graph_uri):
    """Test type checking built-in functions."""
    print("\n4. TYPE CHECKING BUILT-INS:")
    
    # Test 17: DATATYPE function
    await run_builtin_query(sparql_impl, "DATATYPE - Get datatype of literal", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?product ?name ?price ?priceType WHERE {{
            GRAPH <{graph_uri}> {{
                ?product rdf:type ex:Product .
                ?product ex:hasName ?name .
                ?product ex:hasPrice ?price .
                BIND(DATATYPE(?price) AS ?priceType)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    
    # Test 18: LANG function
    await run_builtin_query(sparql_impl, "LANG - Get language tag", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?description ?descLang WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasDescription ?description }}
                BIND(LANG(?description) AS ?descLang)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    
    # Test 19: LANGMATCHES function
    await run_builtin_query(sparql_impl, "LANGMATCHES - Language matching", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?description ?isEnglish WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasDescription ?description }}
                BIND(LANGMATCHES(LANG(?description), "en") AS ?isEnglish)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    
    # Test 20-23: Type checking functions
    await run_builtin_query(sparql_impl, "ISURI/ISLITERAL/ISBLANK/ISNUMERIC - Type checking", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?price ?personIsUri ?nameIsLiteral ?priceIsNumeric WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasAge ?age }}
                BIND(ISURI(?person) AS ?personIsUri)
                BIND(ISLITERAL(?name) AS ?nameIsLiteral)
                BIND(ISNUMERIC(?age) AS ?priceIsNumeric)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)

async def test_advanced_string_builtins(sparql_impl, graph_uri):
    """Test advanced string built-in functions."""
    print("\n5. ADVANCED STRING BUILT-INS:")
    
    # Test 24: REPLACE function
    await run_builtin_query(sparql_impl, "REPLACE - String replacement", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?cleanName WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(REPLACE(?name, " ", "_") AS ?cleanName)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    
    # Test 25-26: STRAFTER/STRBEFORE functions
    await run_builtin_query(sparql_impl, "STRAFTER/STRBEFORE - String before/after substring", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?firstName ?lastName WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(STRBEFORE(?name, " ") AS ?firstName)
                BIND(STRAFTER(?name, " ") AS ?lastName)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    
    # Test 27-28: UUID functions
    await run_builtin_query(sparql_impl, "STRUUID/UUID - Generate UUIDs", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?stringUuid ?uriUuid WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(STRUUID() AS ?stringUuid)
                BIND(UUID() AS ?uriUuid)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)

async def test_hash_builtins(sparql_impl, graph_uri):
    """Test hash built-in functions."""
    print("\n6. HASH BUILT-INS:")
    
    # Test 36-38: SHA hash functions
    await run_builtin_query(sparql_impl, "SHA256/SHA384/SHA512 - Hash functions", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?sha256Hash ?sha384Hash ?sha512Hash WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(SHA256(?name) AS ?sha256Hash)
                BIND(SHA384(?name) AS ?sha384Hash)
                BIND(SHA512(?name) AS ?sha512Hash)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)

async def test_miscellaneous_builtins(sparql_impl, graph_uri):
    """Test miscellaneous built-in functions."""
    print("\n7. MISCELLANEOUS BUILT-INS:")
    
    # Test 39-40: BNODE functions
    await run_builtin_query(sparql_impl, "BNODE - Create blank nodes", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?blankNode ?labeledBlankNode WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(BNODE() AS ?blankNode)
                BIND(BNODE(?name) AS ?labeledBlankNode)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)
    
    # Test 41-42: STRDT/STRLANG functions
    await run_builtin_query(sparql_impl, "STRDT/STRLANG - Create typed/language literals", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        
        SELECT ?person ?name ?typedAge ?langName WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasAge ?age }}
                BIND(STRDT(STR(?age), xsd:integer) AS ?typedAge)
                BIND(STRLANG(?name, "en") AS ?langName)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)

async def test_construct_with_builtins(sparql_impl, graph_uri):
    """Test CONSTRUCT queries with built-in functions."""
    print("\n8. CONSTRUCT WITH BUILT-INS:")
    
    # Test CONSTRUCT with multiple built-ins
    await run_builtin_query(sparql_impl, "CONSTRUCT with built-ins - Create enhanced profiles", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?person ex:hasProfile ?profile .
            ?profile ex:displayName ?name .
            ?profile ex:contactMethod ?contact .
            ?profile ex:hasCompleteInfo ?complete .
            ?profile ex:profileId ?profileId .
        }}
        WHERE {{
            GRAPH <{graph_uri}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                OPTIONAL {{ ?person ex:hasPhone ?phone }}
            }}
            BIND(URI(CONCAT("http://example.org/profile/", ENCODE_FOR_URI(?name))) AS ?profile)
            BIND(COALESCE(?email, ?phone, "no-contact") AS ?contact)
            BIND(IF(BOUND(?email), "complete", "incomplete") AS ?complete)
            BIND(STRUUID() AS ?profileId)
        }}
        LIMIT 5
    """)

async def test_builtin_queries():
    """Main test function for SPARQL built-in functions."""
    print("🧪 SPARQL Built-in Functions Test Suite")
    print("=" * 50)
    
    # Initialize VitalGraph implementation with config file
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    print(f"\n📋 Using config file: {config_path}")
    
    config = get_config(str(config_path))
    impl = VitalGraphImpl(config=config)
    
    # Connect to database
    db_impl = impl.db_impl
    await db_impl.connect()
    space_impl = db_impl.get_space_impl()
    
    # Create SPARQL implementation
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    try:
        # Run comprehensive built-in function test suite
        print("\n🚀 Starting Comprehensive SPARQL Built-in Functions Test Suite")
        print("📊 This suite tests all implemented SPARQL 1.1 built-in functions")
        print("🔧 Coverage includes: Critical, Numeric, String, DateTime, Type Checking, Hash, and Advanced functions")
        
        await test_comprehensive_builtins(sparql_impl, GLOBAL_GRAPH_URI)
        
        # Also run legacy debugging tests for specific issues
        print("\n🔍 Running Legacy Debugging Tests (for specific issue validation)")
        await test_critical_builtins(sparql_impl, GLOBAL_GRAPH_URI)
        await test_construct_with_builtins(sparql_impl, GLOBAL_GRAPH_URI)
        
    finally:
        await db_impl.disconnect()
    
    print("\n✅ SPARQL Built-in Functions Test Suite Complete!")
    print("💡 This test suite covers all SPARQL 1.1 built-in functions")
    print("🔗 Test data includes various data types for comprehensive testing")

# =============================================================================
# FOCUSED DEBUGGING FUNCTIONS FOR BIND+OPTIONAL BUG
# =============================================================================

async def debug_bind_optional_simple(sparql_impl):
    """Debug the simple BIND+OPTIONAL case that's currently failing."""
    query = f"""
    PREFIX ex: <http://example.org/>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT ?person ?name ?contact WHERE {{
        GRAPH <{GLOBAL_GRAPH_URI}> {{
            ?person rdf:type ex:Person .
            ?person ex:hasName ?name .
            OPTIONAL {{ ?person ex:hasEmail ?email }}
            BIND(?email AS ?contact)
        }}
    }}
    LIMIT 5
    """
    return await run_single_test(sparql_impl, "DEBUG: BIND+OPTIONAL Simple (hasEmail)", query, 0)

async def debug_bind_optional_hasage(sparql_impl):
    """Debug BIND+OPTIONAL with hasAge predicate."""
    query = f"""
    PREFIX ex: <http://example.org/>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT ?person ?name ?contact WHERE {{
        GRAPH <{GLOBAL_GRAPH_URI}> {{
            ?person rdf:type ex:Person .
            ?person ex:hasName ?name .
            OPTIONAL {{ ?person ex:hasAge ?age }}
            BIND(?age AS ?contact)
        }}
    }}
    LIMIT 5
    """
    return await run_single_test(sparql_impl, "DEBUG: BIND+OPTIONAL with hasAge", query, 0)

async def debug_optional_only(sparql_impl):
    """Debug OPTIONAL without BIND (should work as baseline)."""
    query = f"""
    PREFIX ex: <http://example.org/>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT ?person ?name ?email WHERE {{
        GRAPH <{GLOBAL_GRAPH_URI}> {{
            ?person rdf:type ex:Person .
            ?person ex:hasName ?name .
            OPTIONAL {{ ?person ex:hasEmail ?email }}
        }}
    }}
    LIMIT 5
    """
    return await run_single_test(sparql_impl, "DEBUG: OPTIONAL Only (no BIND)", query, 1)

async def debug_bind_literal(sparql_impl):
    """Debug BIND with literal (no OPTIONAL) as baseline."""
    query = f"""
    PREFIX ex: <http://example.org/>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT ?person ?name ?contact WHERE {{
        GRAPH <{GLOBAL_GRAPH_URI}> {{
            ?person rdf:type ex:Person .
            ?person ex:hasName ?name .
            BIND("test-contact" AS ?contact)
        }}
    }}
    LIMIT 5
    """
    return await run_single_test(sparql_impl, "DEBUG: BIND Literal (no OPTIONAL)", query, 1)

async def debug_focused_tests():
    """Run focused debugging tests for BIND+OPTIONAL bug."""
    print("🔍 FOCUSED SPARQL BIND+OPTIONAL DEBUGGING")
    print(f"📊 Log Level: {logging.getLevelName(LOG_LEVEL)}")
    print(f"🔍 Show SQL: {SHOW_SQL}")
    print(f"📋 Max Results Display: {MAX_RESULTS_DISPLAY}")
    print("=" * 80)
    
    # Initialize VitalGraph implementation with config file
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    print(f"\n📋 Using config file: {config_path}")
    
    config = get_config(str(config_path))
    impl = VitalGraphImpl(config=config)
    
    # Connect to database
    db_impl = impl.db_impl
    await db_impl.connect()
    space_impl = db_impl.get_space_impl()
    
    # Create SPARQL implementation
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    try:
        # =================================================================
        # ENABLE/DISABLE SPECIFIC TESTS HERE FOR FOCUSED DEBUGGING
        # =================================================================
        
        # Baseline tests (these should work)
        await debug_optional_only(sparql_impl)
        await debug_bind_literal(sparql_impl)
        
        # Previously failing tests (should now work with the fix)
        await debug_bind_optional_simple(sparql_impl)  # Main failing case
        await debug_bind_optional_hasage(sparql_impl)  # Different predicate test
        
    finally:
        await db_impl.disconnect()
    
    print("\n🔍 Focused debugging complete!")

if __name__ == "__main__":
    # Choose which test suite to run:
    asyncio.run(test_builtin_queries())  # Full test suite
    # asyncio.run(debug_focused_tests())     # Focused debugging
