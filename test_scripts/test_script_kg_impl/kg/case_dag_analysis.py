"""
DAG Analysis Test Case

Tests DAG (Directed Acyclic Graph) analysis functionality for KGEntity structures.
Validates graph_utils functionality including DAG detection, sorting, and comparison.
"""

import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class DAGAnalysisTester:
    """
    Test case for DAG analysis functionality.
    
    Tests graph_utils DAG operations including detection, sorting,
    and structure comparison for KGEntity graphs.
    """
    
    def __init__(self, test_data_creator, graph_utils):
        """
        Initialize DAG analysis tester.
        
        Args:
            test_data_creator: KGEntityTestDataCreator instance
            graph_utils: Graph utilities module with DAG functions
        """
        self.test_data_creator = test_data_creator
        self.graph_utils = graph_utils
    
    async def test_dag_analysis(self) -> Dict[str, Any]:
        """
        Test DAG analysis for KGEntity test data.
        
        Returns:
            Dictionary with test results
        """
        logger.info("🔍 Testing DAG analysis functionality...")
        
        results = {
            'success': True,
            'total_tests': 0,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': []
        }
        
        try:
            # Create test data
            logger.info("📊 Creating KGEntity test data...")
            test_data_lists = self.test_data_creator.create_basic_entities()
            
            # Convert list of lists to dictionary format for easier processing
            test_data = {}
            for i, entity_objects in enumerate(test_data_lists):
                entity_name = f"entity_{i+1}"
                
                # Organize objects by type
                entity_data = {
                    'entity': None,
                    'frames': [],
                    'slots': [],
                    'edges': []
                }
                
                for obj in entity_objects:
                    obj_type = type(obj).__name__
                    if 'KGEntity' in obj_type:
                        entity_data['entity'] = obj
                    elif 'KGFrame' in obj_type:
                        entity_data['frames'].append(obj)
                    elif 'Slot' in obj_type:
                        entity_data['slots'].append(obj)
                    elif 'Edge' in obj_type:
                        entity_data['edges'].append(obj)
                
                test_data[entity_name] = entity_data
            
            if not test_data:
                results['success'] = False
                results['failed_tests'].append("Failed to create test data")
                return results
            
            # Test 1: DAG Detection
            results['total_tests'] += 1
            logger.info("🔍 Test 1: DAG Detection")
            
            dag_detection_success = True
            for entity_name, entity_data in test_data.items():
                logger.info(f"   Analyzing entity: {entity_name}")
                
                # Extract graph objects
                graph_objects = []
                if 'entity' in entity_data:
                    graph_objects.append(entity_data['entity'])
                if 'frames' in entity_data:
                    graph_objects.extend(entity_data['frames'])
                if 'slots' in entity_data:
                    graph_objects.extend(entity_data['slots'])
                if 'edges' in entity_data:
                    graph_objects.extend(entity_data['edges'])
                
                # Test DAG detection
                try:
                    is_dag_result = self.graph_utils.is_dag(graph_objects)
                    logger.info(f"   DAG detection result: {is_dag_result}")
                    
                    if is_dag_result is None:
                        logger.warning(f"   DAG detection returned None for {entity_name}")
                        dag_detection_success = False
                        
                except Exception as e:
                    logger.error(f"   DAG detection failed for {entity_name}: {e}")
                    dag_detection_success = False
            
            if dag_detection_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'DAG Detection',
                    'status': 'PASSED',
                    'message': 'All entities analyzed successfully'
                })
                logger.info("✅ DAG Detection: PASSED")
            else:
                results['failed_tests'].append("DAG Detection failed")
                results['test_details'].append({
                    'test': 'DAG Detection',
                    'status': 'FAILED',
                    'message': 'Some entities failed DAG analysis'
                })
                logger.error("❌ DAG Detection: FAILED")
            
            # Test 2: DAG Sorting
            results['total_tests'] += 1
            logger.info("🔍 Test 2: DAG Sorting")
            
            dag_sorting_success = True
            for entity_name, entity_data in test_data.items():
                logger.info(f"   Sorting entity: {entity_name}")
                
                # Extract graph objects
                graph_objects = []
                if 'entity' in entity_data:
                    graph_objects.append(entity_data['entity'])
                if 'frames' in entity_data:
                    graph_objects.extend(entity_data['frames'])
                if 'slots' in entity_data:
                    graph_objects.extend(entity_data['slots'])
                if 'edges' in entity_data:
                    graph_objects.extend(entity_data['edges'])
                
                # Test DAG sorting
                try:
                    dag_structure = self.graph_utils.sort_objects_into_dag(graph_objects)
                    logger.info(f"   DAG sorting result: {type(dag_structure)}")
                    
                    if dag_structure is None:
                        logger.warning(f"   DAG sorting returned None for {entity_name}")
                        dag_sorting_success = False
                        
                except Exception as e:
                    logger.error(f"   DAG sorting failed for {entity_name}: {e}")
                    dag_sorting_success = False
            
            if dag_sorting_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'DAG Sorting',
                    'status': 'PASSED',
                    'message': 'All entities sorted successfully'
                })
                logger.info("✅ DAG Sorting: PASSED")
            else:
                results['failed_tests'].append("DAG Sorting failed")
                results['test_details'].append({
                    'test': 'DAG Sorting',
                    'status': 'FAILED',
                    'message': 'Some entities failed DAG sorting'
                })
                logger.error("❌ DAG Sorting: FAILED")
            
            # Test 3: DAG Pretty Printing
            results['total_tests'] += 1
            logger.info("🔍 Test 3: DAG Pretty Printing")
            
            pretty_print_success = True
            try:
                # Use first entity for pretty printing test
                first_entity_name = list(test_data.keys())[0]
                first_entity_data = test_data[first_entity_name]
                
                # Extract graph objects
                graph_objects = []
                if 'entity' in first_entity_data:
                    graph_objects.append(first_entity_data['entity'])
                if 'frames' in first_entity_data:
                    graph_objects.extend(first_entity_data['frames'])
                if 'slots' in first_entity_data:
                    graph_objects.extend(first_entity_data['slots'])
                if 'edges' in first_entity_data:
                    graph_objects.extend(first_entity_data['edges'])
                
                # Sort into DAG structure
                dag_structure = self.graph_utils.sort_objects_into_dag(graph_objects)
                
                if dag_structure:
                    # Test pretty printing
                    pretty_output = self.graph_utils.pretty_print_dag(dag_structure)
                    logger.info(f"   Pretty print output length: {len(pretty_output) if pretty_output else 0}")
                    
                    if pretty_output:
                        logger.info("✅ DAG Pretty Printing: PASSED")
                        results['passed_tests'] += 1
                        results['test_details'].append({
                            'test': 'DAG Pretty Printing',
                            'status': 'PASSED',
                            'message': 'Pretty printing generated output'
                        })
                    else:
                        pretty_print_success = False
                else:
                    pretty_print_success = False
                    
            except Exception as e:
                logger.error(f"   DAG pretty printing failed: {e}")
                pretty_print_success = False
            
            if not pretty_print_success:
                results['failed_tests'].append("DAG Pretty Printing failed")
                results['test_details'].append({
                    'test': 'DAG Pretty Printing',
                    'status': 'FAILED',
                    'message': 'Pretty printing failed or returned empty output'
                })
                logger.error("❌ DAG Pretty Printing: FAILED")
            
            # Update overall success
            results['success'] = len(results['failed_tests']) == 0
            
        except Exception as e:
            logger.error(f"❌ DAG analysis testing failed: {e}")
            results['success'] = False
            results['failed_tests'].append(f"Test execution error: {str(e)}")
        
        return results
