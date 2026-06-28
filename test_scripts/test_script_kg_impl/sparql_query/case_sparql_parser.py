"""
SPARQL Parser Test Case

Tests SPARQL operation type detection and parsing functionality.
Consolidates the SPARQL parsing tests including DELETE WHERE, INSERT DATA,
DELETE DATA, and complex MODIFY operations.
"""

import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class SPARQLParserTester:
    """
    Test case for SPARQL parser functionality.
    
    Tests operation type detection, RDFLib integration, and parsing
    of various SPARQL UPDATE operations.
    """
    
    def __init__(self, sparql_parser):
        """
        Initialize SPARQL parser tester.
        
        Args:
            sparql_parser: SPARQLUpdateParser instance to test
        """
        self.sparql_parser = sparql_parser
        self.test_cases = self._get_test_cases()
    
    def _get_test_cases(self) -> List[Dict[str, Any]]:
        """Get comprehensive SPARQL test cases."""
        return [
            {
                'name': 'INSERT DATA (simple)',
                'sparql': '''INSERT DATA {
                    GRAPH <http://example.org/test> {
                        <http://example.org/person1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://xmlns.com/foaf/0.1/Person> .
                        <http://example.org/person1> <http://xmlns.com/foaf/0.1/name> "John Doe" .
                    }
                }''',
                'expected': 'insert_data'
            },
            {
                'name': 'DELETE DATA (simple)',
                'sparql': '''DELETE DATA {
                    GRAPH <http://example.org/test> {
                        <http://example.org/person1> <http://xmlns.com/foaf/0.1/name> "John Doe" .
                    }
                }''',
                'expected': 'delete_data'
            },
            {
                'name': 'DELETE with WHERE (pattern)',
                'sparql': '''DELETE {
                    GRAPH <http://example.org/test> {
                        ?person <http://xmlns.com/foaf/0.1/name> ?name .
                    }
                }
                WHERE {
                    GRAPH <http://example.org/test> {
                        ?person <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://xmlns.com/foaf/0.1/Person> .
                        ?person <http://xmlns.com/foaf/0.1/name> ?name .
                    }
                }''',
                'expected': 'delete'
            },
            {
                'name': 'INSERT with WHERE (pattern)',
                'sparql': '''INSERT {
                    GRAPH <http://example.org/test> {
                        ?person <http://xmlns.com/foaf/0.1/status> "active" .
                    }
                }
                WHERE {
                    GRAPH <http://example.org/test> {
                        ?person <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://xmlns.com/foaf/0.1/Person> .
                    }
                }''',
                'expected': 'insert'
            },
            {
                'name': 'DELETE WHERE (simple)',
                'sparql': '''DELETE WHERE {
                    GRAPH <http://example.org/test> {
                        ?s ?p ?o .
                    }
                }''',
                'expected': 'delete_where'
            },
            {
                'name': 'DELETE WHERE (complex - Edge cleanup)',
                'sparql': '''DELETE WHERE {
    GRAPH <http://example.org/test> {
        ?edge a <http://example.org/Edge> .
        ?edge <http://example.org/source> <http://example.org/entity/123> .
        ?edge <http://example.org/destination> ?frame_uri .
        FILTER(?frame_uri = <http://example.org/frame/1>)
        ?edge ?p ?o .
    }
}''',
                'expected': 'delete_where'
            },
            {
                'name': 'Complex DELETE/INSERT (Modify operation)',
                'sparql': '''
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                PREFIX kg: <http://vital.ai/ontology/haley-ai-kg#>
                
                DELETE {
                    GRAPH <http://vital.ai/graph/test_graph> {
                        ?entity ?old_prop ?old_value .
                    }
                }
                INSERT {
                    GRAPH <http://vital.ai/graph/test_graph> {
                        ?entity ?new_prop ?new_value .
                    }
                }
                WHERE {
                    GRAPH <http://vital.ai/graph/test_graph> {
                        ?entity a kg:KGEntity .
                        ?entity ?old_prop ?old_value .
                    }
                }
                ''',
                'expected': 'insert_delete_pattern'
            },
            {
                'name': 'Backend UPDATE (Age and Title) - Real scenario',
                'sparql': '''
                PREFIX ex: <http://example.org/>
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                
                DELETE {
                    GRAPH <http://vital.ai/test/graph/test_backend> {
                        ex:person1 foaf:age ?oldAge .
                    }
                }
                INSERT {
                    GRAPH <http://vital.ai/test/graph/test_backend> {
                        ex:person1 foaf:age 31 ;
                                  foaf:title "Senior Developer" .
                    }
                }
                WHERE {
                    GRAPH <http://vital.ai/test/graph/test_backend> {
                        ex:person1 foaf:age ?oldAge .
                    }
                }
                ''',
                'expected': 'insert_delete_pattern'
            },
            {
                'name': 'Backend DELETE (Person removal) - Real scenario',
                'sparql': '''
                PREFIX ex: <http://example.org/>
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                
                DELETE {
                    GRAPH <http://vital.ai/test/graph/test_backend> {
                        ex:person2 ?p ?o .
                    }
                }
                WHERE {
                    GRAPH <http://vital.ai/test/graph/test_backend> {
                        ex:person2 ?p ?o .
                    }
                }
                ''',
                'expected': 'delete'
            },
            {
                'name': 'DELETE with Variable Pattern - Pattern extraction test',
                'sparql': '''
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                
                DELETE {
                    GRAPH <http://example.org/test> {
                        ?person foaf:name ?name .
                        ?person foaf:age ?age .
                    }
                }
                WHERE {
                    GRAPH <http://example.org/test> {
                        ?person a foaf:Person .
                        ?person foaf:name ?name .
                        ?person foaf:age ?age .
                        FILTER(?age < 18)
                    }
                }
                ''',
                'expected': 'delete'
            },
            {
                'name': 'UPDATE with Multiple Properties - Complex pattern',
                'sparql': '''
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                PREFIX ex: <http://example.org/>
                
                DELETE {
                    GRAPH <http://example.org/test> {
                        ?person foaf:status ?oldStatus .
                        ?person ex:lastUpdated ?oldTime .
                    }
                }
                INSERT {
                    GRAPH <http://example.org/test> {
                        ?person foaf:status "updated" .
                        ?person ex:lastUpdated "2024-01-01T00:00:00Z" .
                        ?person ex:version ?newVersion .
                    }
                }
                WHERE {
                    GRAPH <http://example.org/test> {
                        ?person a foaf:Person .
                        ?person foaf:status ?oldStatus .
                        ?person ex:lastUpdated ?oldTime .
                        ?person ex:version ?version .
                        BIND(?version + 1 AS ?newVersion)
                    }
                }
                ''',
                'expected': 'insert_delete_pattern'
            },
            {
                'name': 'DELETE WHERE with OPTIONAL - Advanced pattern',
                'sparql': '''DELETE WHERE {
                    GRAPH <http://example.org/test> {
                        ?entity a <http://example.org/TemporaryEntity> .
                        OPTIONAL { ?entity <http://example.org/hasProperty> ?prop }
                        ?entity ?p ?o .
                    }
                }''',
                'expected': 'delete_where'
            },
            {
                'name': 'Nested GRAPH DELETE - Multi-graph scenario',
                'sparql': '''
                PREFIX ex: <http://example.org/>
                
                DELETE {
                    GRAPH ?targetGraph {
                        ?entity ex:temporaryProperty ?value .
                    }
                }
                WHERE {
                    GRAPH <http://example.org/metadata> {
                        ?entity ex:hasTargetGraph ?targetGraph .
                    }
                    GRAPH ?targetGraph {
                        ?entity ex:temporaryProperty ?value .
                        ?entity ex:isTemporary true .
                    }
                }
                ''',
                'expected': 'delete'
            },
            # Alternative DELETE patterns that avoid problematic DELETE WHERE with variables
            {
                'name': 'DELETE with explicit bindings + simple WHERE',
                'sparql': '''
                PREFIX ex: <http://example.org/>
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                
                DELETE {
                    GRAPH <http://example.org/test> {
                        ex:person2 foaf:name "Bob Smith" .
                        ex:person2 foaf:age "25" .
                        ex:person2 foaf:email "bob@example.org" .
                        ex:person2 a foaf:Person .
                    }
                }
                WHERE {
                    GRAPH <http://example.org/test> {
                        ex:person2 a foaf:Person .
                    }
                }
                ''',
                'expected': 'delete'
            },
            {
                'name': 'DELETE DATA with multiple explicit triples',
                'sparql': '''
                PREFIX ex: <http://example.org/>
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                
                DELETE DATA {
                    GRAPH <http://example.org/test> {
                        ex:person2 a foaf:Person .
                        ex:person2 foaf:name "Bob Smith" .
                        ex:person2 foaf:age "25" .
                        ex:person2 foaf:email "bob@example.org" .
                    }
                }
                ''',
                'expected': 'delete_data'
            },
            {
                'name': 'DELETE with property-specific patterns',
                'sparql': '''
                PREFIX ex: <http://example.org/>
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                
                DELETE {
                    GRAPH <http://example.org/test> {
                        ex:person1 foaf:age "30" .
                    }
                }
                WHERE {
                    GRAPH <http://example.org/test> {
                        ex:person1 a foaf:Person .
                        ex:person1 foaf:age "30" .
                    }
                }
                ''',
                'expected': 'delete'
            },
            {
                'name': 'Sequential DELETE DATA operations',
                'sparql': '''
                PREFIX ex: <http://example.org/>
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                
                DELETE DATA {
                    GRAPH <http://example.org/test> {
                        ex:person2 foaf:name "Bob Smith" .
                    }
                } ;
                DELETE DATA {
                    GRAPH <http://example.org/test> {
                        ex:person2 foaf:age "25" .
                    }
                } ;
                DELETE DATA {
                    GRAPH <http://example.org/test> {
                        ex:person2 a foaf:Person .
                    }
                }
                ''',
                'expected': 'delete_data'
            },
            {
                'name': 'DELETE with type-based filtering (no variables)',
                'sparql': '''
                PREFIX ex: <http://example.org/>
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                
                DELETE {
                    GRAPH <http://example.org/test> {
                        ex:person2 foaf:name "Bob Smith" .
                        ex:person2 foaf:email "bob@example.org" .
                    }
                }
                WHERE {
                    GRAPH <http://example.org/test> {
                        ex:person2 a foaf:Person .
                        ex:person2 foaf:name "Bob Smith" .
                        ex:person2 foaf:email "bob@example.org" .
                    }
                }
                ''',
                'expected': 'delete'
            },
            {
                'name': 'UPDATE using separate DELETE DATA + INSERT DATA',
                'sparql': '''
                PREFIX ex: <http://example.org/>
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                
                DELETE DATA {
                    GRAPH <http://example.org/test> {
                        ex:person1 foaf:age "30" .
                    }
                } ;
                INSERT DATA {
                    GRAPH <http://example.org/test> {
                        ex:person1 foaf:age "31" .
                        ex:person1 foaf:title "Senior Developer" .
                    }
                }
                ''',
                'expected': 'delete_data'
            },
            # Graph management operations used by graphs endpoint
            {
                'name': 'CREATE GRAPH (basic)',
                'sparql': 'CREATE GRAPH <http://vital.ai/graph/test_create>',
                'expected': 'create_graph'
            },
            {
                'name': 'CREATE SILENT GRAPH',
                'sparql': 'CREATE SILENT GRAPH <http://vital.ai/graph/test_create_silent>',
                'expected': 'create_graph'
            },
            {
                'name': 'DROP GRAPH (basic)',
                'sparql': 'DROP GRAPH <http://vital.ai/graph/test_drop>',
                'expected': 'drop_graph'
            },
            {
                'name': 'DROP SILENT GRAPH',
                'sparql': 'DROP SILENT GRAPH <http://vital.ai/graph/test_drop_silent>',
                'expected': 'drop_graph'
            },
            {
                'name': 'CLEAR GRAPH (basic)',
                'sparql': 'CLEAR GRAPH <http://vital.ai/graph/test_clear>',
                'expected': 'clear_graph'
            },
            {
                'name': 'CLEAR SILENT GRAPH',
                'sparql': 'CLEAR SILENT GRAPH <http://vital.ai/graph/test_clear_silent>',
                'expected': 'clear_graph'
            }
        ]
    
    async def test_sparql_parsing(self) -> Dict[str, Any]:
        """
        Test SPARQL parsing for all test cases.
        
        Returns:
            Dictionary with test results
        """
        logger.info("🔍 Testing SPARQL parser operation type detection...")
        
        results = {
            'success': True,
            'total_tests': len(self.test_cases),
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': []
        }
        
        for i, test_case in enumerate(self.test_cases, 1):
            logger.info(f"  Test {i}/{len(self.test_cases)}: {test_case['name']}")
            
            try:
                # Test the parser
                detected_type = self.sparql_parser._identify_operation_type(test_case['sparql'])
                expected_type = test_case['expected']
                
                test_result = {
                    'name': test_case['name'],
                    'expected': expected_type,
                    'detected': detected_type,
                    'passed': detected_type == expected_type
                }
                
                if test_result['passed']:
                    logger.info(f"    ✅ PASSED - Expected: {expected_type}, Detected: {detected_type}")
                    results['passed_tests'] += 1
                else:
                    logger.error(f"    ❌ FAILED - Expected: {expected_type}, Detected: {detected_type}")
                    results['failed_tests'].append(test_case['name'])
                    results['success'] = False
                
                results['test_details'].append(test_result)
                
            except Exception as e:
                logger.error(f"    ❌ FAILED - Exception: {e}")
                test_result = {
                    'name': test_case['name'],
                    'expected': test_case['expected'],
                    'detected': 'ERROR',
                    'passed': False,
                    'error': str(e)
                }
                results['test_details'].append(test_result)
                results['failed_tests'].append(test_case['name'])
                results['success'] = False
        
        # Summary
        if results['success']:
            logger.info(f"✅ All {results['total_tests']} SPARQL parser tests passed!")
        else:
            failed_count = len(results['failed_tests'])
            logger.error(f"❌ {failed_count}/{results['total_tests']} SPARQL parser tests failed")
            logger.error(f"   Failed tests: {', '.join(results['failed_tests'])}")
        
        return results
    
    def test_rdflib_parsing_direct(self, sparql_query: str) -> Dict[str, Any]:
        """
        Test RDFLib parsing directly for debugging.
        
        Args:
            sparql_query: SPARQL query to test
            
        Returns:
            Dictionary with parsing details
        """
        try:
            from rdflib.plugins.sparql.parser import parseUpdate
            from rdflib.plugins.sparql.algebra import translateUpdate
            
            logger.debug("Testing RDFLib parsing directly...")
            
            # Parse with RDFLib
            parsed_update = parseUpdate(sparql_query)
            algebra = translateUpdate(parsed_update)
            
            result = {
                'success': True,
                'parsed_type': type(parsed_update).__name__,
                'algebra_type': type(algebra).__name__,
                'operations': []
            }
            
            # Extract operation details
            if hasattr(algebra, 'algebra'):
                operations = algebra.algebra if hasattr(algebra.algebra, '__iter__') else [algebra.algebra]
                
                for op in operations:
                    op_info = {
                        'type': type(op).__name__,
                        'name': getattr(op, 'name', None) if hasattr(op, 'name') else None
                    }
                    result['operations'].append(op_info)
            
            logger.debug(f"RDFLib parsing successful: {result}")
            return result
            
        except Exception as e:
            logger.error(f"RDFLib parsing failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }


class SPARQLExecutionTester:
    """
    Test case for SPARQL execution functionality.
    
    Tests actual SPARQL query execution against the hybrid backend.
    """
    
    def __init__(self, hybrid_backend):
        """
        Initialize SPARQL execution tester.
        
        Args:
            hybrid_backend: Hybrid backend instance for testing
        """
        self.hybrid_backend = hybrid_backend
    
    async def test_sparql_execution(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Test SPARQL execution operations.
        
        Args:
            space_id: Test space ID
            graph_id: Test graph ID
            
        Returns:
            Dictionary with execution test results
        """
        logger.info("⚡ Testing SPARQL execution operations...")
        
        results = {
            'success': True,
            'tests': []
        }
        
        # Test INSERT DATA
        insert_result = await self._test_insert_execution(space_id, graph_id)
        results['tests'].append(insert_result)
        if not insert_result['passed']:
            results['success'] = False
        
        # Test DELETE WHERE
        delete_result = await self._test_delete_execution(space_id, graph_id)
        results['tests'].append(delete_result)
        if not delete_result['passed']:
            results['success'] = False
        
        return results
    
    async def _test_insert_execution(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test INSERT DATA execution."""
        logger.info("  Testing INSERT DATA execution...")
        
        sparql = f"""
        INSERT DATA {{
            GRAPH <{graph_id}> {{
                <http://example.org/test/exec1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                <http://example.org/test/exec1> <http://vital.ai/ontology/vital-core#hasName> "Execution Test 1" .
            }}
        }}
        """
        
        try:
            result = await self.hybrid_backend.execute_sparql_update(space_id, sparql)
            
            return {
                'name': 'INSERT DATA execution',
                'passed': result if isinstance(result, bool) else result.get('success', False),
                'details': result
            }
            
        except Exception as e:
            return {
                'name': 'INSERT DATA execution',
                'passed': False,
                'error': str(e)
            }
    
    async def _test_delete_execution(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test DELETE WHERE execution."""
        logger.info("  Testing DELETE WHERE execution...")
        
        sparql = f"""
        DELETE WHERE {{
            GRAPH <{graph_id}> {{
                <http://example.org/test/exec1> ?p ?o .
            }}
        }}
        """
        
        try:
            result = await self.hybrid_backend.execute_sparql_update(space_id, sparql)
            
            return {
                'name': 'DELETE WHERE execution',
                'passed': result if isinstance(result, bool) else result.get('success', False),
                'details': result
            }
            
        except Exception as e:
            return {
                'name': 'DELETE WHERE execution',
                'passed': False,
                'error': str(e)
            }
