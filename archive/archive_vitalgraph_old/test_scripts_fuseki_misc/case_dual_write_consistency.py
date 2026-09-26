"""
Dual-Write Consistency Test Case

Tests dual-write consistency validation in the FUSEKI_POSTGRESQL hybrid backend including:
- Data consistency verification between Fuseki and PostgreSQL
- Triple comparison and analysis
- Pattern analysis for identifying synchronization issues
- Detailed debugging information for consistency failures
"""

import logging
from typing import Dict, Any, List, Tuple, Set

logger = logging.getLogger(__name__)


class DualWriteConsistencyTester:
    """
    Test case for dual-write consistency validation.
    
    Tests that data is consistently written to both Fuseki and PostgreSQL.
    """
    
    def __init__(self, components: Dict[str, Any], test_space_id: str, test_graph_uri: str):
        """
        Initialize dual-write consistency tester.
        
        Args:
            components: Dictionary of initialized backend components
            test_space_id: ID of the test space
            test_graph_uri: URI of the test graph
        """
        self.components = components
        self.test_space_id = test_space_id
        self.test_graph_uri = test_graph_uri
        
        # Extract components for easier access
        self.space_impl = components.get('space_impl')
        self.postgresql_impl = components.get('postgresql_impl')
    
    async def test_dual_write_consistency(self) -> Dict[str, Any]:
        """
        Test that data is consistently written to both Fuseki and PostgreSQL.
        
        Returns:
            Dictionary with test results
        """
        logger.info("🔄 Testing dual-write consistency...")
        
        results = {
            'success': True,
            'total_tests': 3,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': [],
            'consistency_data': {}
        }
        
        try:
            # Test 1: Data Retrieval from Both Systems
            logger.info("🔍 Test 1: Data Retrieval from Both Systems")
            retrieval_success, fuseki_triples, postgresql_triples = await self._test_data_retrieval()
            
            if retrieval_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'Data Retrieval',
                    'status': 'PASSED',
                    'message': f'Retrieved {len(fuseki_triples)} Fuseki triples, {len(postgresql_triples)} PostgreSQL triples'
                })
                logger.info("✅ Data Retrieval: PASSED")
            else:
                results['failed_tests'].append("Data Retrieval failed")
                results['test_details'].append({
                    'test': 'Data Retrieval',
                    'status': 'FAILED',
                    'message': 'Failed to retrieve data from one or both systems'
                })
                logger.error("❌ Data Retrieval: FAILED")
                return results
            
            # Test 2: Triple Comparison
            logger.info("🔍 Test 2: Triple Comparison")
            comparison_success, consistency_analysis = await self._test_triple_comparison(
                fuseki_triples, postgresql_triples
            )
            results['consistency_data'] = consistency_analysis
            
            if comparison_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'Triple Comparison',
                    'status': 'PASSED',
                    'message': f'All {len(fuseki_triples)} triples match between systems'
                })
                logger.info("✅ Triple Comparison: PASSED")
            else:
                results['failed_tests'].append("Triple Comparison failed")
                results['test_details'].append({
                    'test': 'Triple Comparison',
                    'status': 'FAILED',
                    'message': 'Triples do not match between Fuseki and PostgreSQL'
                })
                logger.error("❌ Triple Comparison: FAILED")
            
            # Test 3: Consistency Analysis
            logger.info("🔍 Test 3: Consistency Analysis")
            analysis_success = await self._test_consistency_analysis(consistency_analysis)
            
            if analysis_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'Consistency Analysis',
                    'status': 'PASSED',
                    'message': 'Detailed consistency analysis completed'
                })
                logger.info("✅ Consistency Analysis: PASSED")
            else:
                results['failed_tests'].append("Consistency Analysis failed")
                results['test_details'].append({
                    'test': 'Consistency Analysis',
                    'status': 'FAILED',
                    'message': 'Consistency analysis revealed issues'
                })
                logger.error("❌ Consistency Analysis: FAILED")
            
            # Update overall success
            results['success'] = len(results['failed_tests']) == 0
            
        except Exception as e:
            logger.error(f"❌ Dual-write consistency testing failed: {e}")
            results['success'] = False
            results['failed_tests'].append(f"Test execution error: {str(e)}")
        
        return results
    
    async def _test_data_retrieval(self) -> Tuple[bool, List[Tuple[str, str, str]], List[Tuple[str, str, str]]]:
        """Test data retrieval from both Fuseki and PostgreSQL."""
        try:
            # Get data from Fuseki
            fuseki_triples = await self._get_fuseki_triples()
            if fuseki_triples is None:
                logger.error("   Failed to retrieve Fuseki triples")
                return False, [], []
            
            # Get data from PostgreSQL
            postgresql_triples = await self._get_postgresql_triples()
            if postgresql_triples is None:
                logger.error("   Failed to retrieve PostgreSQL triples")
                return False, [], []
            
            logger.info(f"   Retrieved {len(fuseki_triples)} triples from Fuseki")
            logger.info(f"   Retrieved {len(postgresql_triples)} triples from PostgreSQL")
            
            return True, fuseki_triples, postgresql_triples
            
        except Exception as e:
            logger.error(f"   Data retrieval test failed: {e}")
            return False, [], []
    
    async def _test_triple_comparison(self, fuseki_triples: List[Tuple[str, str, str]], 
                                    postgresql_triples: List[Tuple[str, str, str]]) -> Tuple[bool, Dict[str, Any]]:
        """Test triple comparison between systems."""
        try:
            # Convert to sets for comparison
            fuseki_set = set(fuseki_triples)
            postgresql_set = set(postgresql_triples)
            
            # Perform comparison analysis
            consistency_analysis = {
                'fuseki_count': len(fuseki_set),
                'postgresql_count': len(postgresql_set),
                'matches': fuseki_set == postgresql_set,
                'only_in_fuseki': fuseki_set - postgresql_set,
                'only_in_postgresql': postgresql_set - fuseki_set,
                'common_triples': fuseki_set & postgresql_set
            }
            
            # Log analysis results
            logger.info(f"   Fuseki triples: {consistency_analysis['fuseki_count']}")
            logger.info(f"   PostgreSQL triples: {consistency_analysis['postgresql_count']}")
            logger.info(f"   Matches: {consistency_analysis['matches']}")
            
            if consistency_analysis['matches']:
                logger.info(f"   ✅ All {len(fuseki_set)} triples match between systems")
                return True, consistency_analysis
            else:
                logger.error("   ❌ Triple mismatch detected")
                logger.error(f"     Only in Fuseki: {len(consistency_analysis['only_in_fuseki'])}")
                logger.error(f"     Only in PostgreSQL: {len(consistency_analysis['only_in_postgresql'])}")
                return False, consistency_analysis
            
        except Exception as e:
            logger.error(f"   Triple comparison test failed: {e}")
            return False, {}
    
    async def _test_consistency_analysis(self, consistency_analysis: Dict[str, Any]) -> bool:
        """Test detailed consistency analysis."""
        try:
            if consistency_analysis.get('matches', False):
                logger.info("   ✅ Systems are consistent - no further analysis needed")
                return True
            
            # Detailed analysis for inconsistencies
            only_in_fuseki = consistency_analysis.get('only_in_fuseki', set())
            only_in_postgresql = consistency_analysis.get('only_in_postgresql', set())
            
            if only_in_fuseki:
                logger.error(f"   Triples only in Fuseki ({len(only_in_fuseki)}):")
                for triple in list(only_in_fuseki)[:5]:  # Show first 5
                    logger.error(f"     {triple}")
                if len(only_in_fuseki) > 5:
                    logger.error(f"     ... and {len(only_in_fuseki) - 5} more")
                logger.info("     ↳ These are likely from UPDATE operations that worked on Fuseki but not PostgreSQL")
            
            if only_in_postgresql:
                logger.error(f"   Triples only in PostgreSQL ({len(only_in_postgresql)}):")
                for triple in list(only_in_postgresql)[:5]:  # Show first 5
                    logger.error(f"     {triple}")
                if len(only_in_postgresql) > 5:
                    logger.error(f"     ... and {len(only_in_postgresql) - 5} more")
                logger.info("     ↳ These are likely stale data from DELETE operations that worked on Fuseki but not PostgreSQL")
            
            # Pattern analysis
            logger.info("   🔍 Pattern Analysis:")
            logger.info("     This suggests pattern-based DELETE/UPDATE operations are not being synchronized to PostgreSQL")
            logger.info("     - INSERT DATA operations: ✅ Working (data appears in both)")
            logger.info("     - DELETE/UPDATE with WHERE: ❌ Not working (changes only in Fuseki)")
            
            return False  # Inconsistency found
            
        except Exception as e:
            logger.error(f"   Consistency analysis test failed: {e}")
            return False
    
    async def _get_fuseki_triples(self) -> List[Tuple[str, str, str]]:
        """Get all triples from Fuseki."""
        try:
            if not self.space_impl:
                logger.error("   Space implementation not available")
                return None
            
            # Query Fuseki for current data
            fuseki_query = f"""
            PREFIX ex: <http://example.org/>
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            
            SELECT ?s ?p ?o WHERE {{
                GRAPH <{self.test_graph_uri}> {{
                    ?s ?p ?o .
                }}
            }}
            """
            
            fuseki_results = await self.space_impl.query_quads(self.test_space_id, fuseki_query)
            fuseki_triples = []
            for result in fuseki_results:
                triple = (
                    result['s']['value'],
                    result['p']['value'],
                    result['o']['value']
                )
                fuseki_triples.append(triple)
            
            return fuseki_triples
            
        except Exception as e:
            logger.error(f"   Error querying Fuseki: {e}")
            return None
    
    async def _get_postgresql_triples(self) -> List[Tuple[str, str, str]]:
        """Get all triples from PostgreSQL backup tables."""
        try:
            if not self.postgresql_impl:
                logger.error("   PostgreSQL implementation not available")
                return None
            
            # Use the PostgreSQL connection pool properly
            async with self.postgresql_impl.connection_pool.acquire() as conn:
                # First, check what tables exist
                table_query = f"""
                SELECT table_name FROM information_schema.tables 
                WHERE table_name LIKE '{self.test_space_id}%'
                """
                tables = await conn.fetch(table_query)
                logger.info(f"   PostgreSQL tables for space {self.test_space_id}: {[t['table_name'] for t in tables]}")
                
                # Check if the expected tables exist
                quad_table = f"{self.test_space_id}_rdf_quad"
                term_table = f"{self.test_space_id}_term"
                
                # Count total rows in each table
                try:
                    quad_count = await conn.fetchval(f"SELECT COUNT(*) FROM {quad_table}")
                    term_count = await conn.fetchval(f"SELECT COUNT(*) FROM {term_table}")
                    logger.info(f"   Table counts - {quad_table}: {quad_count} rows, {term_table}: {term_count} rows")
                except Exception as table_error:
                    logger.error(f"   Error checking table counts: {table_error}")
                    return []
                
                # Use correct column names based on actual schema
                all_query = f"""
                SELECT t_s.term_text as subject, t_p.term_text as predicate, t_o.term_text as object
                FROM {quad_table} q
                JOIN {term_table} t_s ON q.subject_uuid = t_s.term_uuid
                JOIN {term_table} t_p ON q.predicate_uuid = t_p.term_uuid  
                JOIN {term_table} t_o ON q.object_uuid = t_o.term_uuid
                """
                
                logger.info(f"   Querying ALL PostgreSQL data (no graph filter)")
                rows = await conn.fetch(all_query)
                logger.info(f"   PostgreSQL query returned {len(rows)} rows")
                
                triples = []
                for row in rows:
                    triple = (row['subject'], row['predicate'], row['object'])
                    triples.append(triple)
                
                return triples
            
        except Exception as e:
            logger.error(f"   Error querying PostgreSQL: {e}")
            return None
