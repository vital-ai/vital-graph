#!/usr/bin/env python3
"""
KGType Relationships Test Case

Client-based test case for KGType relationship operations using VitalGraph client.
Tests get, create, and delete of type-level relationship edges.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class KGTypeRelationshipsTester:
    """Test case for KGType relationship operations."""

    def __init__(self, client):
        self.client = client

    async def run_tests(
        self, space_id: str, graph_id: str, created_kgtype_uris: List[str],
        entity_type_uris: List[str], frame_type_uris: List[str],
    ) -> Dict[str, Any]:
        """
        Run KGType relationship tests.

        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            created_kgtype_uris: All created KGType URIs
            entity_type_uris: URIs of KGEntityType objects
            frame_type_uris: URIs of KGFrameType objects

        Returns:
            Test results dictionary
        """
        logger.info("🔗 Testing KGType relationship operations...")

        results = []

        # Test 1: Get relationships for a type (initially empty)
        if entity_type_uris:
            get_result = await self._test_get_relationships_empty(space_id, graph_id, entity_type_uris[0])
            results.append(get_result)

        # Test 2: Create a relationship between two entity types
        created_edge_uri = None
        if len(entity_type_uris) >= 2:
            create_result = await self._test_create_relationship(
                space_id, graph_id, entity_type_uris[0], entity_type_uris[1]
            )
            results.append(create_result)
            if create_result['passed']:
                created_edge_uri = create_result.get('edge_uri')

        # Test 3: Get relationships after creation (should now have one)
        if entity_type_uris and created_edge_uri:
            get_result2 = await self._test_get_relationships_with_edge(space_id, graph_id, entity_type_uris[0])
            results.append(get_result2)

        # Test 4: Delete the relationship
        if entity_type_uris and created_edge_uri:
            delete_result = await self._test_delete_relationship(
                space_id, graph_id, entity_type_uris[0], created_edge_uri
            )
            results.append(delete_result)

        # Test 5: Verify relationship is gone
        if entity_type_uris and created_edge_uri:
            verify_result = await self._test_get_relationships_empty(space_id, graph_id, entity_type_uris[0])
            verify_result['name'] = 'Get Relationships After Delete (empty)'
            results.append(verify_result)

        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"✅ KGType relationship tests completed: {passed_tests}/{len(results)} passed")

        return {
            'name': 'KGType Relationship Tests',
            'passed': passed_tests == len(results),
            'total_tests': len(results),
            'passed_tests': passed_tests,
            'results': results,
        }

    async def _test_get_relationships_empty(self, space_id: str, graph_id: str, type_uri: str) -> Dict[str, Any]:
        """Test getting relationships for a type that has none."""
        logger.info(f"  Testing get relationships (empty) for {type_uri}...")

        try:
            response = await self.client.kgtypes.get_type_relationships(space_id, graph_id, type_uri)

            if response.is_success:
                return {
                    'name': 'Get Relationships (empty)',
                    'passed': True,
                    'details': f"Got relationships for {type_uri}: {len(response.edges)} edges",
                    'edge_count': len(response.edges),
                }
            else:
                return {
                    'name': 'Get Relationships (empty)',
                    'passed': False,
                    'error': response.error_message or "Failed to get relationships",
                }
        except Exception as e:
            return {
                'name': 'Get Relationships (empty)',
                'passed': False,
                'error': f"Exception: {e}",
            }

    async def _test_create_relationship(
        self, space_id: str, graph_id: str, source_uri: str, target_uri: str
    ) -> Dict[str, Any]:
        """Test creating a type-level relationship edge."""
        logger.info(f"  Testing create relationship {source_uri} -> {target_uri}...")

        edge_type = "http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGEntityType"

        try:
            response = await self.client.kgtypes.create_type_relationship(
                space_id, graph_id, source_uri, edge_type, target_uri
            )

            if response.is_success:
                return {
                    'name': 'Create Type Relationship',
                    'passed': True,
                    'details': f"Created edge {response.edge_uri}",
                    'edge_uri': response.edge_uri,
                    'edge_type': response.edge_type,
                    'source_uri': response.source_uri,
                    'destination_uri': response.destination_uri,
                }
            else:
                return {
                    'name': 'Create Type Relationship',
                    'passed': False,
                    'error': response.error_message or "Failed to create relationship",
                }
        except Exception as e:
            return {
                'name': 'Create Type Relationship',
                'passed': False,
                'error': f"Exception: {e}",
            }

    async def _test_get_relationships_with_edge(self, space_id: str, graph_id: str, type_uri: str) -> Dict[str, Any]:
        """Test getting relationships for a type that has edges."""
        logger.info(f"  Testing get relationships (with edge) for {type_uri}...")

        try:
            response = await self.client.kgtypes.get_type_relationships(space_id, graph_id, type_uri)

            if response.is_success and len(response.edges) > 0:
                return {
                    'name': 'Get Relationships (with edge)',
                    'passed': True,
                    'details': f"Found {len(response.edges)} edges",
                    'edge_count': len(response.edges),
                }
            elif response.is_success:
                return {
                    'name': 'Get Relationships (with edge)',
                    'passed': False,
                    'error': "Expected edges but found none",
                }
            else:
                return {
                    'name': 'Get Relationships (with edge)',
                    'passed': False,
                    'error': response.error_message or "Failed to get relationships",
                }
        except Exception as e:
            return {
                'name': 'Get Relationships (with edge)',
                'passed': False,
                'error': f"Exception: {e}",
            }

    async def _test_delete_relationship(
        self, space_id: str, graph_id: str, type_uri: str, edge_uri: str
    ) -> Dict[str, Any]:
        """Test deleting a type-level relationship edge."""
        logger.info(f"  Testing delete relationship {edge_uri}...")

        try:
            response = await self.client.kgtypes.delete_type_relationship(
                space_id, graph_id, type_uri, edge_uri
            )

            if response.is_success and response.deleted:
                return {
                    'name': 'Delete Type Relationship',
                    'passed': True,
                    'details': f"Deleted edge {edge_uri}",
                }
            else:
                return {
                    'name': 'Delete Type Relationship',
                    'passed': False,
                    'error': response.error_message or "Failed to delete relationship",
                }
        except Exception as e:
            return {
                'name': 'Delete Type Relationship',
                'passed': False,
                'error': f"Exception: {e}",
            }
