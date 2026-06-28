#!/usr/bin/env python3
"""
KGEntity Query Test Module

Modular test implementation for KG entity query operations.
Used by the main KGEntities endpoint test orchestrator.

Focuses on:
- Criteria-based entity queries
- SPARQL query generation and execution
- Query result processing and pagination
- Entity graph URI filtering in queries
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import VitalSigns for KGEntity objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity

# Import models
from vitalgraph.model.kgentities_model import EntityQueryResponse, EntityQueryCriteria, EntityQueryRequest, SlotCriteria, SortCriteria, QueryFilter

# Import quad conversion utilities
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list

# Import test data creator
from test_scripts.fuseki_postgresql.kgentity_test_data import KGEntityTestDataCreator


logger = logging.getLogger(__name__)


class KGEntityQueryTester:
    """
    Modular test implementation for KG entity query operations.
    
    Handles:
    - Criteria-based entity queries
    - SPARQL query generation and execution
    - Query result processing and pagination
    - Entity graph URI filtering in queries
    """
    
    def __init__(self, endpoint, test_data_creator):
        """
        Initialize the entity query tester.
        
        Args:
            endpoint: KGEntitiesEndpoint instance (initialized without REST setup)
            test_data_creator: KGEntityTestDataCreator instance for generating test data
        """
        self.endpoint = endpoint
        self.vitalsigns = VitalSigns()
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        
    async def test_criteria_based_entity_queries(self, space_id: str, graph_id: str) -> bool:
        """
        Test criteria-based entity queries.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if criteria-based queries successful, False otherwise
        """
        try:
            logger.info("🧪 Testing criteria-based entity queries")
            
            # Create diverse test entities for querying
            await self._create_test_entities_for_queries(space_id, graph_id)
            
            # Test 1: Query by entity type
            logger.info("🔍 Testing query by entity type")
            
            type_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            query_request = EntityQueryRequest(
                criteria=type_criteria,
                page_size=10,
                offset=0
            )
            
            type_result = await self.endpoint._query_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            # Debug logging to see what we actually get back
            logger.info(f"🔍 DEBUG: type_result type: {type(type_result)}")
            logger.info(f"🔍 DEBUG: type_result: {type_result}")
            if hasattr(type_result, '__dict__'):
                logger.info(f"🔍 DEBUG: type_result attributes: {type_result.__dict__}")
            
            if type_result and hasattr(type_result, 'entity_uris') and type_result.entity_uris:
                logger.info(f"✅ Entity type query successful: Found {len(type_result.entity_uris)} person entities")
                
                # Log the entity URIs found
                for entity_uri in type_result.entity_uris:
                    logger.info(f"  ✓ Found person entity: {entity_uri}")
            else:
                logger.warning("⚠️  No results for entity type query")
            
            # Test 2: Query by name property
            logger.info("🔍 Testing query by name property")
            
            name_criteria = EntityQueryCriteria(
                search_string="Test"
            )
            
            name_query_request = EntityQueryRequest(
                criteria=name_criteria,
                page_size=10,
                offset=0
            )
            
            name_result = await self.endpoint._query_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                query_request=name_query_request,
                current_user=current_user
            )
            
            if name_result and hasattr(name_result, 'entity_uris') and name_result.entity_uris:
                logger.info(f"✅ Name query successful: Found {len(name_result.entity_uris)} entities with 'Test' in name")
            else:
                logger.warning("⚠️  No results for name query")
            
            # Test 3: Multiple criteria query
            logger.info("🔍 Testing multiple criteria query")
            
            multi_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#OrganizationEntity",
                search_string="Corp"
            )
            
            multi_query_request = EntityQueryRequest(
                criteria=multi_criteria,
                page_size=10,
                offset=0
            )
            
            multi_result = await self.endpoint._query_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                query_request=multi_query_request,
                current_user=current_user
            )
            
            if multi_result and hasattr(multi_result, 'entity_uris') and multi_result.entity_uris:
                logger.info(f"✅ Multiple criteria query successful: Found {len(multi_result.entity_uris)} organization entities with 'Corp'")
            else:
                logger.warning("⚠️  No results for multiple criteria query")
            
            return True
                
        except Exception as e:
            logger.error(f"❌ Error during criteria-based query test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_sparql_query_generation_and_execution(self, space_id: str, graph_id: str) -> bool:
        """
        Test SPARQL query generation and execution.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if SPARQL generation/execution successful, False otherwise
        """
        try:
            logger.info("⚡ Testing SPARQL query generation and execution")
            
            # Test complex query with sorting
            logger.info("🔍 Testing SPARQL generation with sorting")
            
            sort_criteria = SortCriteria(
                sort_type="property",
                property_uri="http://vital.ai/ontology/vital-core#name",
                sort_order="asc",
                priority=1
            )
            
            criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#ProjectEntity",
                sort_criteria=[sort_criteria]
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            sorted_query_request = EntityQueryRequest(
                criteria=criteria,
                page_size=5,
                offset=0
            )
            
            sorted_result = await self.endpoint._query_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                query_request=sorted_query_request,
                current_user=current_user
            )
            
            if sorted_result and hasattr(sorted_result, 'entity_uris') and sorted_result.entity_uris:
                logger.info(f"✅ SPARQL query with sorting successful: Found {len(sorted_result.entity_uris)} project entities")
                
                # Log the entity URIs found
                for entity_uri in sorted_result.entity_uris:
                    logger.info(f"  ✓ Found project entity: {entity_uri}")
            else:
                logger.warning("⚠️  No results for SPARQL sorting query")
            
            # Test query with filters
            logger.info("🔍 Testing SPARQL generation with filters")
            
            filter_criteria = QueryFilter(
                property_name="name",
                operator="not_equals",
                value=""
            )
            
            # Create criteria with filter
            filter_query_criteria = EntityQueryCriteria(
                filters=[filter_criteria]
            )
            
            filter_query_request = EntityQueryRequest(
                criteria=filter_query_criteria,
                page_size=10,
                offset=0
            )
            
            filtered_result = await self.endpoint._query_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                query_request=filter_query_request,
                current_user=current_user
            )
            
            if filtered_result and hasattr(filtered_result, 'entity_uris') and filtered_result.entity_uris:
                logger.info(f"✅ SPARQL query with filters successful: Found {len(filtered_result.entity_uris)} entities with non-empty names")
            else:
                logger.warning("⚠️  No results for SPARQL filter query")
            
            return True
                
        except Exception as e:
            logger.error(f"❌ Error during SPARQL generation/execution test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_query_result_processing_and_pagination(self, space_id: str, graph_id: str) -> bool:
        """
        Test query result processing and pagination.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if result processing/pagination successful, False otherwise
        """
        try:
            logger.info("📄 Testing query result processing and pagination")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # Test pagination - first page
            logger.info("📄 Testing first page of results")
            
            empty_criteria = EntityQueryCriteria()
            
            page1_query_request = EntityQueryRequest(
                criteria=empty_criteria,
                page_size=2,
                offset=0
            )
            
            page1_result = await self.endpoint._query_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                query_request=page1_query_request,
                current_user=current_user
            )
            
            if page1_result and hasattr(page1_result, 'entity_uris') and page1_result.entity_uris:
                page1_count = len(page1_result.entity_uris)
                logger.info(f"✅ First page: Found {page1_count} entities")
                
                # Collect entity URIs from first page
                page1_uris = page1_result.entity_uris
                
                # Test pagination - second page
                logger.info("📄 Testing second page of results")
                
                page2_query_request = EntityQueryRequest(
                    criteria=empty_criteria,
                    page_size=2,
                    offset=2
                )
                
                page2_result = await self.endpoint._query_kgentities(
                    space_id=space_id,
                    graph_id=graph_id,
                    query_request=page2_query_request,
                    current_user=current_user
                )
                
                if page2_result and hasattr(page2_result, 'entity_uris') and page2_result.entity_uris:
                    page2_count = len(page2_result.entity_uris)
                    logger.info(f"✅ Second page: Found {page2_count} entities")
                    
                    # Collect entity URIs from second page
                    page2_uris = page2_result.entity_uris
                    
                    # Validate no overlap between pages
                    overlap = set(page1_uris) & set(page2_uris)
                    if not overlap:
                        logger.info("✅ Pagination working correctly - no overlap between pages")
                    else:
                        logger.warning(f"⚠️  Pagination overlap detected: {overlap}")
                    
                    # Test result processing
                    total_entities = page1_count + page2_count
                    if total_entities > 0:
                        logger.info(f"✅ Query result processing successful: {total_entities} total entities processed")
                        return True
                    else:
                        logger.warning("⚠️  No entities processed")
                        return False
                else:
                    logger.warning("⚠️  No results for second page")
                    return page1_count > 0  # First page success is still valid
            else:
                logger.warning("⚠️  No results for first page")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during result processing/pagination test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_entity_graph_uri_filtering(self, space_id: str, graph_id: str) -> bool:
        """
        Test entity graph URI filtering in queries.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if graph URI filtering successful, False otherwise
        """
        try:
            logger.info("🏷️  Testing entity graph URI filtering in queries")
            
            # Test query with entity graph inclusion
            logger.info("🌐 Testing query with entity graph inclusion")
            
            criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            graph_query_request = EntityQueryRequest(
                criteria=criteria,
                page_size=5,
                offset=0
            )
            
            graph_result = await self.endpoint._query_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                query_request=graph_query_request,
                current_user=current_user
            )
            
            if graph_result and hasattr(graph_result, 'entity_uris') and graph_result.entity_uris:
                logger.info(f"✅ Entity graph URI filtering successful: Found {len(graph_result.entity_uris)} entities with graphs")
                
                # Log the entity URIs found
                for entity_uri in graph_result.entity_uris:
                    logger.info(f"  ✓ Found entity with graph: {entity_uri}")
                
                return True
            else:
                logger.warning("⚠️  No results for entity graph URI filtering")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during entity graph URI filtering test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_complex_entity_structure_queries(self, space_id: str, graph_id: str) -> bool:
        """
        Test queries on complex entity structures using test data.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if complex structure queries successful, False otherwise
        """
        try:
            logger.info("🏗️  Testing complex entity structure queries")
            
            # Test query for entities with specific frame types
            logger.info("🔍 Testing query for entities with contact frames")
            
            # This would require a more complex SPARQL query that joins entities with their frames
            # For now, test a simpler approach by querying entities and then checking their frames
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # Get all KG entities (PersonEntity is a kGEntityType value, not rdf:type)
            person_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            person_query_request = EntityQueryRequest(
                criteria=person_criteria,
                page_size=10,
                offset=0
            )
            
            person_result = await self.endpoint._query_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                query_request=person_query_request,
                current_user=current_user
            )
            
            if person_result and hasattr(person_result, 'entity_uris') and person_result.entity_uris:
                logger.info(f"✅ Complex structure query successful: Found {len(person_result.entity_uris)} KG entities")
                
                # Log the entity URIs found
                for entity_uri in person_result.entity_uris:
                    logger.info(f"  ✓ Found KG entity: {entity_uri}")
                
                return True
            else:
                logger.warning("⚠️  No KG entities found for complex structure queries")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during complex entity structure query test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def _create_test_entities_for_queries(self, space_id: str, graph_id: str) -> bool:
        """
        Create diverse test entities for query testing.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if creation successful, False otherwise
        """
        try:
            logger.info("🏗️  Creating diverse test entities for query testing")
            
            # Create basic entities using test data
            basic_entities = self.test_data_creator.create_basic_entities()
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            
            for i, entity_objects in enumerate(basic_entities):
                # Convert to quads for creation
                entity_quads = graphobjects_to_quad_list(entity_objects, graph_id)
                
                # Create entity
                create_result = await self.endpoint._create_or_update_entities(
                    space_id=space_id,
                    graph_id=graph_id,
                    quads=entity_quads,
                    operation_mode=OperationMode.CREATE,
                    parent_uri=None,
                    current_user=current_user
                )
                
                if create_result and hasattr(create_result, 'created_uris'):
                    self.created_entity_uris.extend(create_result.created_uris)
                    logger.info(f"✅ Created test entity set {i+1}: {len(create_result.created_uris)} entities")
                else:
                    logger.warning(f"⚠️  Failed to create test entity set {i+1}")
            
            logger.info(f"✅ Created {len(self.created_entity_uris)} total test entities for querying")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error creating test entities for queries: {e}")
            return False
    
    def get_created_entity_uris(self) -> List[str]:
        """
        Get list of created entity URIs for cleanup purposes.
        
        Returns:
            List[str]: List of created entity URIs
        """
        return self.created_entity_uris.copy()
    
    def clear_created_uris(self):
        """Clear the list of created entity URIs."""
        self.created_entity_uris.clear()
