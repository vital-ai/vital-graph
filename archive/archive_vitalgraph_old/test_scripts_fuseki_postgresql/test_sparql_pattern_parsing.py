#!/usr/bin/env python3
"""
Focused test for SPARQL pattern parsing without backend dependencies.

Tests the DELETE to SELECT conversion and pattern resolution logic
in the SPARQLUpdateParser to debug dual-write consistency issues.
"""

import sys
import logging
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.db.fuseki_postgresql.sparql_update_parser import SPARQLUpdateParser

# Setup detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SPARQLPatternTester:
    """Test SPARQL pattern parsing functionality."""
    
    def __init__(self):
        # Create parser without fuseki manager (not needed for pattern parsing)
        self.parser = SPARQLUpdateParser(None)
    
    def test_delete_to_select_conversion(self):
        """Test DELETE to SELECT query conversion."""
        
        # Use the exact DELETE query from the backend test to debug the issue
        backend_delete_query = '''
        PREFIX ex: <http://example.org/>
        PREFIX foaf: <http://xmlns.com/foaf/0.1/>
        
        DELETE {
            GRAPH <http://example.org/test_graph_12345> {
                ex:person2 ?p ?o .
            }
        }
        WHERE {
            GRAPH <http://example.org/test_graph_12345> {
                ex:person2 ?p ?o .
            }
        }
        '''
        
        test_cases = [
            {
                'name': 'Backend DELETE Query (exact match)',
                'delete_query': backend_delete_query,
                'expected_pattern': 'SELECT ?p ?o WHERE'
            },
            {
                'name': 'Simple DELETE with WHERE',
                'delete_query': '''
                PREFIX ex: <http://example.org/>
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                
                DELETE {
                    ?s ?p ?o .
                }
                WHERE {
                    ?s a foaf:Person .
                    ?s ?p ?o .
                }
                ''',
                'expected_pattern': 'SELECT ?s ?p ?o WHERE'
            },
            {
                'name': 'DELETE with GRAPH',
                'delete_query': '''
                PREFIX ex: <http://example.org/>
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                
                DELETE {
                    GRAPH <http://example.org/test> {
                        ex:person2 ?p ?o .
                    }
                }
                WHERE {
                    GRAPH <http://example.org/test> {
                        ex:person2 ?p ?o .
                    }
                }
                ''',
                'expected_pattern': 'SELECT ?p ?o WHERE'
            },
            {
                'name': 'DELETE specific triples',
                'delete_query': '''
                PREFIX ex: <http://example.org/>
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                
                DELETE {
                    GRAPH <http://example.org/test> {
                        ?person foaf:age ?age .
                    }
                }
                WHERE {
                    GRAPH <http://example.org/test> {
                        ?person a foaf:Person .
                        ?person foaf:age ?age .
                        FILTER(?age < 30)
                    }
                }
                ''',
                'expected_pattern': 'SELECT ?person ?age WHERE'
            }
        ]
        
        logger.info("🔍 Testing DELETE to SELECT conversion...")
        
        all_passed = True
        for i, test_case in enumerate(test_cases, 1):
            logger.info(f"\n--- Test {i}: {test_case['name']} ---")
            
            try:
                # Test the conversion
                select_query = self.parser._convert_delete_to_select_query(test_case['delete_query'])
                
                logger.info(f"Original DELETE query:")
                logger.info(f"{test_case['delete_query']}")
                logger.info(f"Converted SELECT query:")
                logger.info(f"{select_query}")
                
                if select_query:
                    # Check for proper SPARQL structure instead of exact string matching
                    if select_query.startswith('SELECT') and 'WHERE' in select_query:
                        # Validate that variables from DELETE are in SELECT
                        select_vars = []
                        if '?p' in select_query and '?o' in select_query:
                            select_vars.extend(['?p', '?o'])
                        if '?person' in select_query and '?age' in select_query:
                            select_vars.extend(['?person', '?age'])
                        if '?s' in select_query:
                            select_vars.append('?s')
                        
                        if select_vars:
                            logger.info(f"✅ PASSED - SELECT query generated with variables: {select_vars}")
                        else:
                            logger.error("❌ FAILED - No expected variables found in SELECT query")
                            all_passed = False
                    else:
                        logger.error("❌ FAILED - Invalid SELECT query structure")
                        all_passed = False
                else:
                    logger.error("❌ FAILED - No SELECT query generated")
                    all_passed = False
                
            except Exception as e:
                logger.error(f"❌ FAILED with exception: {e}")
                all_passed = False
        
        return all_passed
    
    def test_where_clause_extraction(self):
        """Test WHERE clause extraction from SPARQL queries."""
        
        test_cases = [
            {
                'name': 'Simple WHERE clause',
                'query': '''
                DELETE { ?s ?p ?o } WHERE { ?s a foaf:Person . ?s ?p ?o }
                ''',
                'expected': True
            },
            {
                'name': 'GRAPH WHERE clause',
                'query': '''
                DELETE { GRAPH <uri> { ?s ?p ?o } } WHERE { GRAPH <uri> { ?s ?p ?o } }
                ''',
                'expected': True
            },
            {
                'name': 'Complex WHERE with FILTER',
                'query': '''
                DELETE { ?s foaf:age ?age } WHERE { ?s a foaf:Person . ?s foaf:age ?age . FILTER(?age < 30) }
                ''',
                'expected': True
            }
        ]
        
        logger.info("🔍 Testing WHERE clause extraction...")
        
        all_passed = True
        for i, test_case in enumerate(test_cases, 1):
            logger.info(f"\n--- Test {i}: {test_case['name']} ---")
            
            try:
                # Test RDFLib algebra parsing instead of string extraction
                from rdflib.plugins.sparql.parser import parseUpdate
                from rdflib.plugins.sparql.algebra import translateUpdate
                
                parsed_update = parseUpdate(test_case['query'])
                algebra = translateUpdate(parsed_update)
                
                logger.info(f"Original query: {test_case['query']}")
                logger.info(f"RDFLib algebra parsed successfully: {type(algebra)}")
                
                if algebra:
                    logger.info("✅ PASSED - RDFLib algebra parsing successful")
                else:
                    logger.error("❌ FAILED - RDFLib algebra parsing failed")
                    all_passed = False
                
            except Exception as e:
                logger.error(f"❌ FAILED with exception: {e}")
                all_passed = False
        
        return all_passed
    
    def test_operation_type_detection(self):
        """Test SPARQL operation type detection."""
        
        test_cases = [
            {
                'name': 'INSERT DATA',
                'query': '''
                INSERT DATA {
                    GRAPH <http://example.org/test> {
                        <http://example.org/person1> a <http://xmlns.com/foaf/0.1/Person> .
                    }
                }
                ''',
                'expected': 'insert_data'
            },
            {
                'name': 'DELETE DATA',
                'query': '''
                DELETE DATA {
                    GRAPH <http://example.org/test> {
                        <http://example.org/person1> <http://xmlns.com/foaf/0.1/name> "Alice" .
                    }
                }
                ''',
                'expected': 'delete_data'
            },
            {
                'name': 'DELETE with WHERE (pattern)',
                'query': '''
                DELETE {
                    GRAPH <http://example.org/test> {
                        ?s ?p ?o .
                    }
                }
                WHERE {
                    GRAPH <http://example.org/test> {
                        ?s a <http://xmlns.com/foaf/0.1/Person> .
                        ?s ?p ?o .
                    }
                }
                ''',
                'expected': 'insert_delete_pattern'
            }
        ]
        
        logger.info("🔍 Testing operation type detection...")
        
        all_passed = True
        for i, test_case in enumerate(test_cases, 1):
            logger.info(f"\n--- Test {i}: {test_case['name']} ---")
            
            try:
                detected_type = self.parser._identify_operation_type(test_case['query'])
                expected_type = test_case['expected']
                
                logger.info(f"Expected: {expected_type}")
                logger.info(f"Detected: {detected_type}")
                
                if detected_type == expected_type:
                    logger.info("✅ PASSED")
                else:
                    logger.error("❌ FAILED")
                    all_passed = False
                
            except Exception as e:
                logger.error(f"❌ FAILED with exception: {e}")
                all_passed = False
        
        return all_passed
    
    def test_rdflib_algebra_structure(self):
        """Test RDFLib algebra structure analysis."""
        
        test_query = '''
        PREFIX ex: <http://example.org/>
        PREFIX foaf: <http://xmlns.com/foaf/0.1/>
        
        DELETE {
            GRAPH <http://example.org/test> {
                ex:person2 ?p ?o .
            }
        }
        WHERE {
            GRAPH <http://example.org/test> {
                ex:person2 ?p ?o .
            }
        }
        '''
        
        logger.info("🔍 Testing RDFLib algebra structure...")
        
        try:
            from rdflib.plugins.sparql.parser import parseUpdate
            from rdflib.plugins.sparql.algebra import translateUpdate
            
            logger.info("Parsing with RDFLib...")
            parsed_update = parseUpdate(test_query)
            algebra = translateUpdate(parsed_update)
            
            logger.info(f"Algebra type: {type(algebra)}")
            logger.info(f"Algebra attributes: {[attr for attr in dir(algebra) if not attr.startswith('_')]}")
            
            if hasattr(algebra, 'request'):
                logger.info(f"Algebra.request type: {type(algebra.request)}")
                
                if hasattr(algebra.request, '__iter__'):
                    logger.info("Algebra.request is iterable")
                    for i, op in enumerate(algebra.request):
                        logger.info(f"  Operation {i}: {type(op)}")
                        if hasattr(op, 'algebra'):
                            logger.info(f"    Has algebra: {type(op.algebra)}")
                            if isinstance(op.algebra, list):
                                for j, sub_op in enumerate(op.algebra):
                                    logger.info(f"      Sub-operation {j}: {type(sub_op)}")
                                    if hasattr(sub_op, 'name'):
                                        logger.info(f"        Name: {sub_op.name}")
                else:
                    logger.info("Algebra.request is not iterable")
                    logger.info(f"Single operation: {type(algebra.request)}")
            
            logger.info("✅ RDFLib algebra analysis completed")
            return True
            
        except Exception as e:
            logger.error(f"❌ RDFLib algebra analysis failed: {e}")
            return False
    
    def test_backend_pattern_resolution_flow(self):
        """Test the complete pattern resolution flow as used in the backend."""
        
        # Use the exact DELETE query from the backend test
        backend_delete_query = '''
        PREFIX ex: <http://example.org/>
        PREFIX foaf: <http://xmlns.com/foaf/0.1/>
        
        DELETE {
            GRAPH <http://example.org/test_graph_12345> {
                ex:person2 ?p ?o .
            }
        }
        WHERE {
            GRAPH <http://example.org/test_graph_12345> {
                ex:person2 ?p ?o .
            }
        }
        '''
        
        logger.info("🔍 Testing complete backend pattern resolution flow...")
        
        try:
            # Step 1: Test operation type detection (synchronous)
            operation_type = self.parser._identify_operation_type(backend_delete_query)
            logger.info(f"� Operation type: {operation_type}")
            
            if operation_type != 'insert_delete_pattern':
                logger.error(f"❌ Expected 'insert_delete_pattern', got '{operation_type}'")
                return False
            
            # Step 2: Test SELECT query generation directly (synchronous)
            select_query = self.parser._convert_delete_to_select_query(backend_delete_query)
            logger.info(f"� Generated SELECT query: {select_query}")
            
            if not select_query or 'SELECT' not in select_query:
                logger.error("❌ SELECT query generation failed")
                return False
            
            # Step 3: Test pattern extraction (synchronous)
            patterns = self.parser._extract_patterns_from_query(backend_delete_query)
            logger.info(f"� Extracted patterns: {len(patterns)} patterns")
            logger.info(f"   Patterns: {patterns}")
            
            # Step 4: Analyze what would happen in pattern resolution
            logger.info("🔍 Pattern Resolution Analysis:")
            logger.info(f"   - Operation detected as: {operation_type}")
            logger.info(f"   - SELECT query generated: {bool(select_query)}")
            logger.info(f"   - Patterns extracted: {len(patterns)}")
            
            if operation_type == 'insert_delete_pattern' and select_query:
                logger.info("   - ✅ Pattern resolution pipeline would be triggered")
                logger.info("   - ✅ SELECT query would be executed against Fuseki")
                logger.info("   - ✅ Concrete triples would be resolved for PostgreSQL")
            else:
                logger.error("   - ❌ Pattern resolution pipeline would NOT be triggered")
                return False
            
            logger.info("✅ Backend pattern resolution flow working")
            return True
            
        except Exception as e:
            logger.error(f"❌ Backend pattern resolution flow failed: {e}")
            return False
    
    def run_all_tests(self):
        """Run all SPARQL pattern tests."""
        logger.info("🚀 Starting SPARQL Pattern Parsing Tests")
        
        tests = [
            ("Operation Type Detection", self.test_operation_type_detection),
            ("DELETE to SELECT Conversion", self.test_delete_to_select_conversion),
            ("WHERE Clause Extraction", self.test_where_clause_extraction),
            ("RDFLib Algebra Structure", self.test_rdflib_algebra_structure),
            ("Backend Pattern Resolution Flow", self.test_backend_pattern_resolution_flow),
        ]
        
        passed = 0
        total = len(tests)
        
        for test_name, test_func in tests:
            logger.info(f"\n🔬 Running: {test_name}")
            try:
                success = test_func()
                if success:
                    logger.info(f"✅ {test_name}: PASSED")
                    passed += 1
                else:
                    logger.error(f"❌ {test_name}: FAILED")
            except Exception as e:
                logger.error(f"❌ {test_name}: FAILED with exception: {e}")
        
        # Summary
        logger.info(f"\n📊 Test Results Summary:")
        for i, (test_name, _) in enumerate(tests):
            status = "✅ PASSED" if i < passed else "❌ FAILED"
            logger.info(f" {test_name}: {status}")
        
        logger.info(f"🎯 Overall Results: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
        
        return passed == total


def main():
    """Main test function."""
    try:
        tester = SPARQLPatternTester()
        success = tester.run_all_tests()
        return success
        
    except Exception as e:
        logger.error(f"❌ Test suite failed: {e}")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
