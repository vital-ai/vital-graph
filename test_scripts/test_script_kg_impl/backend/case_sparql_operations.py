"""
SPARQL Operations Test Case

Tests SPARQL operations in the FUSEKI_POSTGRESQL hybrid backend including:
- SPARQL INSERT DATA operations with dual-write
- SPARQL QUERY operations (read from Fuseki)
- SPARQL UPDATE operations (DELETE/INSERT) with dual-write
- SPARQL DELETE operations with dual-write
- Result validation and verification
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class SPARQLOperationsTester:
    """
    Test case for SPARQL operations functionality.
    
    Tests comprehensive SPARQL operations with dual-write coordination.
    """
    
    def __init__(self, components: Dict[str, Any], test_space_id: str, test_graph_uri: str):
        """
        Initialize SPARQL operations tester.
        
        Args:
            components: Dictionary of initialized backend components
            test_space_id: ID of the test space
            test_graph_uri: URI of the test graph
        """
        self.components = components
        self.test_space_id = test_space_id
        self.test_graph_uri = test_graph_uri
        
        # Extract components for easier access
        self.dual_coordinator = components.get('dual_coordinator')
        self.fuseki_manager = components.get('fuseki_manager')
    
    async def test_sparql_operations(self) -> Dict[str, Any]:
        """
        Test comprehensive SPARQL operations.
        
        Returns:
            Dictionary with test results
        """
        logger.info("📝 Testing SPARQL operations...")
        
        results = {
            'success': True,
            'total_tests': 4,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': []
        }
        
        try:
            # Test 1: SPARQL INSERT Operations
            logger.info("🔍 Test 1: SPARQL INSERT Operations")
            insert_success = await self._test_sparql_insert()
            
            if insert_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'SPARQL INSERT',
                    'status': 'PASSED',
                    'message': 'INSERT DATA operations successful'
                })
                logger.info("✅ SPARQL INSERT: PASSED")
            else:
                results['failed_tests'].append("SPARQL INSERT failed")
                results['test_details'].append({
                    'test': 'SPARQL INSERT',
                    'status': 'FAILED',
                    'message': 'INSERT DATA operations failed'
                })
                logger.error("❌ SPARQL INSERT: FAILED")
            
            # Test 2: SPARQL QUERY Operations
            logger.info("🔍 Test 2: SPARQL QUERY Operations")
            query_success = await self._test_sparql_query()
            
            if query_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'SPARQL QUERY',
                    'status': 'PASSED',
                    'message': 'SELECT queries successful with expected results'
                })
                logger.info("✅ SPARQL QUERY: PASSED")
            else:
                results['failed_tests'].append("SPARQL QUERY failed")
                results['test_details'].append({
                    'test': 'SPARQL QUERY',
                    'status': 'FAILED',
                    'message': 'SELECT queries failed or returned unexpected results'
                })
                logger.error("❌ SPARQL QUERY: FAILED")
            
            # Test 3: SPARQL UPDATE Operations
            logger.info("🔍 Test 3: SPARQL UPDATE Operations")
            update_success = await self._test_sparql_update()
            
            if update_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'SPARQL UPDATE',
                    'status': 'PASSED',
                    'message': 'DELETE/INSERT UPDATE operations successful'
                })
                logger.info("✅ SPARQL UPDATE: PASSED")
            else:
                results['failed_tests'].append("SPARQL UPDATE failed")
                results['test_details'].append({
                    'test': 'SPARQL UPDATE',
                    'status': 'FAILED',
                    'message': 'DELETE/INSERT UPDATE operations failed'
                })
                logger.error("❌ SPARQL UPDATE: FAILED")
            
            # Test 4: SPARQL DELETE Operations
            logger.info("🔍 Test 4: SPARQL DELETE Operations")
            delete_success = await self._test_sparql_delete()
            
            if delete_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'SPARQL DELETE',
                    'status': 'PASSED',
                    'message': 'DELETE operations successful'
                })
                logger.info("✅ SPARQL DELETE: PASSED")
            else:
                results['failed_tests'].append("SPARQL DELETE failed")
                results['test_details'].append({
                    'test': 'SPARQL DELETE',
                    'status': 'FAILED',
                    'message': 'DELETE operations failed'
                })
                logger.error("❌ SPARQL DELETE: FAILED")
            
            # Update overall success
            results['success'] = len(results['failed_tests']) == 0
            
        except Exception as e:
            logger.error(f"❌ SPARQL operations testing failed: {e}")
            results['success'] = False
            results['failed_tests'].append(f"Test execution error: {str(e)}")
        
        return results
    
    async def _test_sparql_insert(self) -> bool:
        """Test SPARQL INSERT operations with dual-write."""
        try:
            if not self.dual_coordinator:
                logger.error("   Dual-write coordinator not available")
                return False
            
            # Test data - create some RDF triples
            insert_sparql = f"""
            PREFIX ex: <http://example.org/>
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            
            INSERT DATA {{
                GRAPH <{self.test_graph_uri}> {{
                    ex:person1 a foaf:Person ;
                               foaf:name "Alice Johnson" ;
                               foaf:age 30 ;
                               foaf:email "alice@example.org" .
                    
                    ex:person2 a foaf:Person ;
                               foaf:name "Bob Smith" ;
                               foaf:age 25 ;
                               foaf:email "bob@example.org" .
                    
                    ex:person3 a foaf:Person ;
                               foaf:name "Carol Davis" ;
                               foaf:age 35 ;
                               foaf:email "carol@example.org" .
                }}
            }}
            """
            
            # Execute SPARQL INSERT using dual-write coordinator
            success = await self.dual_coordinator.execute_sparql_update(
                space_id=self.test_space_id,
                sparql_update=insert_sparql
            )
            
            if success:
                logger.info("   INSERT DATA operations completed successfully")
                return True
            else:
                logger.error("   INSERT DATA operations failed")
                return False
                
        except Exception as e:
            logger.error(f"   SPARQL INSERT test failed: {e}")
            return False
    
    async def _test_sparql_query(self) -> bool:
        """Test SPARQL QUERY operations (read from Fuseki)."""
        try:
            if not self.fuseki_manager:
                logger.error("   Fuseki manager not available")
                return False
            
            # Query the inserted data
            query_sparql = f"""
            PREFIX ex: <http://example.org/>
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            
            SELECT ?person ?name ?age ?email
            WHERE {{
                GRAPH <{self.test_graph_uri}> {{
                    ?person a foaf:Person ;
                           foaf:name ?name ;
                           foaf:age ?age ;
                           foaf:email ?email .
                }}
            }}
            ORDER BY ?name
            """
            
            # Execute query using Fuseki manager
            bindings = await self.fuseki_manager.query_dataset(
                space_id=self.test_space_id,
                sparql_query=query_sparql
            )
            
            if not bindings:
                logger.error("   SPARQL QUERY returned no results")
                return False
            
            # Validate results
            if len(bindings) != 3:
                logger.error(f"   Expected 3 results, got {len(bindings)}")
                return False
            
            # Check specific results
            expected_names = ["Alice Johnson", "Bob Smith", "Carol Davis"]
            actual_names = [binding['name']['value'] for binding in bindings]
            
            if actual_names != expected_names:
                logger.error(f"   Expected names {expected_names}, got {actual_names}")
                return False
            
            logger.info(f"   SPARQL QUERY successful - found {len(bindings)} persons")
            for binding in bindings:
                name = binding['name']['value']
                age = binding['age']['value']
                email = binding['email']['value']
                logger.info(f"     - {name}, age {age}, email {email}")
            
            return True
                
        except Exception as e:
            logger.error(f"   SPARQL QUERY test failed: {e}")
            return False
    
    async def _test_sparql_update(self) -> bool:
        """Test SPARQL UPDATE operations with dual-write."""
        try:
            if not self.dual_coordinator or not self.fuseki_manager:
                logger.error("   Required components not available")
                return False
            
            # Update Alice's age and add a new property using separate DELETE DATA and INSERT DATA
            # First delete the old age
            delete_old_age = f"""
            PREFIX ex: <http://example.org/>
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            
            DELETE DATA {{
                GRAPH <{self.test_graph_uri}> {{
                    ex:person1 foaf:age "30" .
                }}
            }}
            """
            
            # Then insert new age and title
            insert_new_data = f"""
            PREFIX ex: <http://example.org/>
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            
            INSERT DATA {{
                GRAPH <{self.test_graph_uri}> {{
                    ex:person1 foaf:age "31" ;
                              foaf:title "Senior Developer" .
                }}
            }}
            """
            
            # Execute SPARQL UPDATE using dual-write coordinator (two separate operations)
            # First delete the old age
            success1 = await self.dual_coordinator.execute_sparql_update(
                space_id=self.test_space_id,
                sparql_update=delete_old_age
            )
            
            if not success1:
                logger.error("   SPARQL DELETE old age failed")
                return False
            
            # Then insert new age and title
            success2 = await self.dual_coordinator.execute_sparql_update(
                space_id=self.test_space_id,
                sparql_update=insert_new_data
            )
            
            success = success1 and success2
            
            if not success:
                logger.error("   SPARQL UPDATE failed")
                return False
            
            # Verify the update by querying
            verify_query = f"""
            PREFIX ex: <http://example.org/>
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            
            SELECT ?age ?title
            WHERE {{
                GRAPH <{self.test_graph_uri}> {{
                    ex:person1 foaf:age ?age .
                    OPTIONAL {{ ex:person1 foaf:title ?title }}
                }}
            }}
            """
            
            bindings = await self.fuseki_manager.query_dataset(
                space_id=self.test_space_id,
                sparql_query=verify_query
            )
            
            if len(bindings) != 1:
                logger.error(f"   Expected 1 result for verification, got {len(bindings)}")
                return False
            
            binding = bindings[0]
            age = binding['age']['value']
            title = binding.get('title', {}).get('value', 'No title')
            
            if age != '31':
                logger.error(f"   Expected age 31, got {age}")
                return False
            
            if title != 'Senior Developer':
                logger.error(f"   Expected title 'Senior Developer', got '{title}'")
                return False
            
            logger.info(f"   SPARQL UPDATE successful - Alice now age {age}, title '{title}'")
            return True
                
        except Exception as e:
            logger.error(f"   SPARQL UPDATE test failed: {e}")
            return False
    
    async def _test_sparql_delete(self) -> bool:
        """Test SPARQL DELETE operations with dual-write."""
        try:
            if not self.dual_coordinator or not self.fuseki_manager:
                logger.error("   Required components not available")
                return False
            
            # Delete Bob's record entirely using DELETE DATA (explicit triples)
            delete_sparql = f"""
            PREFIX ex: <http://example.org/>
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            
            DELETE DATA {{
                GRAPH <{self.test_graph_uri}> {{
                    ex:person2 a foaf:Person .
                    ex:person2 foaf:name "Bob Smith" .
                    ex:person2 foaf:age "25" .
                    ex:person2 foaf:email "bob@example.org" .
                }}
            }}
            """
            
            # Execute SPARQL DELETE using dual-write coordinator
            success = await self.dual_coordinator.execute_sparql_update(
                space_id=self.test_space_id,
                sparql_update=delete_sparql
            )
            
            if not success:
                logger.error("   SPARQL DELETE failed")
                return False
            
            # Verify deletion by counting remaining persons
            count_query = f"""
            PREFIX ex: <http://example.org/>
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            
            SELECT (COUNT(?person) AS ?count)
            WHERE {{
                GRAPH <{self.test_graph_uri}> {{
                    ?person a foaf:Person .
                }}
            }}
            """
            
            bindings = await self.fuseki_manager.query_dataset(
                space_id=self.test_space_id,
                sparql_query=count_query
            )
            
            if len(bindings) != 1:
                logger.error(f"   Expected 1 count result, got {len(bindings)}")
                return False
            
            count = int(bindings[0]['count']['value'])
            if count != 2:
                logger.error(f"   Expected 2 remaining persons, got {count}")
                return False
            
            logger.info(f"   SPARQL DELETE successful - {count} persons remaining")
            return True
                
        except Exception as e:
            logger.error(f"   SPARQL DELETE test failed: {e}")
            return False
