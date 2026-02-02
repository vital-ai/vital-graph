"""
Files Create Test Cases

Tests for creating file nodes via the Files endpoint client.
Updated to use new response objects with direct GraphObject access.
"""

import logging
from typing import Dict, Any
from vital_ai_domain.model.FileNode import FileNode


async def run_file_creation_tests(client, space_id: str, graph_id: str, logger=None) -> tuple[bool, list]:
    """
    Run file creation tests.
    
    Returns:
        tuple: (success: bool, created_uris: list) - Test success and list of created file URIs
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🧪 Running File Creation Tests")
    
    created_uris = []
    
    try:
        # Test 1: Create single file node using VitalSigns FileNode graph object
        logger.info("  Test 1: Create single file node")
        
        # Create VitalSigns FileNode
        file_node = FileNode()
        file_node.URI = "haley:file_test_document_001"
        file_node.name = "Test Document"
        
        # Pass GraphObject directly - no JSON-LD conversion needed
        response = client.files.create_file(
            space_id=space_id,
            graph_id=graph_id,
            objects=[file_node]
        )
        
        if response.is_success and response.created_count > 0:
            logger.info(f"  ✅ Single file node created successfully (URI: {response.file_uri})")
            created_uris.append(str(file_node.URI))
            
            # Validate FileNode is stored in database by retrieving it
            get_response = client.files.get_file(
                space_id=space_id,
                graph_id=graph_id,
                uri=str(file_node.URI)
            )
            if get_response.is_success and get_response.file:
                logger.info(f"     ✅ Verified FileNode stored in database: {file_node.URI}")
            else:
                logger.error(f"     ❌ FileNode not found in database: {file_node.URI}")
                return False, created_uris
        else:
            logger.error(f"  ❌ Failed to create single file node: {response.error_message}")
            return False, created_uris
        
        # Test 2: Create multiple file nodes using VitalSigns FileNode graph objects
        logger.info("  Test 2: Create multiple file nodes")
        
        # Create first FileNode
        file_node_1 = FileNode()
        file_node_1.URI = "haley:file_test_image_001"
        file_node_1.name = "Test Image"
        
        # Create second FileNode
        file_node_2 = FileNode()
        file_node_2.URI = "haley:file_test_data_001"
        file_node_2.name = "Test Data"
        
        # Pass GraphObjects directly - no JSON-LD conversion needed
        response = client.files.create_file(
            space_id=space_id,
            graph_id=graph_id,
            objects=[file_node_1, file_node_2]
        )
        
        if response.is_success and response.created_count >= 2:
            logger.info(f"  ✅ Multiple file nodes created successfully ({response.created_count} files)")
            created_uris.append(str(file_node_1.URI))
            created_uris.append(str(file_node_2.URI))
            
            # Validate FileNodes are stored in database by retrieving them
            for file_uri in [str(file_node_1.URI), str(file_node_2.URI)]:
                get_response = client.files.get_file(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=file_uri
                )
                if get_response.is_success and get_response.file:
                    logger.info(f"     ✅ Verified FileNode stored in database: {file_uri}")
                else:
                    logger.error(f"     ❌ FileNode not found in database: {file_uri}")
                    return False, created_uris
        else:
            logger.error(f"  ❌ Failed to create multiple file nodes: {response.error_message}")
            return False, created_uris
        
        logger.info("✅ All file creation tests passed")
        logger.info(f"   Created {len(created_uris)} file(s): {created_uris}")
        return True, created_uris
        
    except Exception as e:
        logger.error(f"❌ File creation tests failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False, created_uris
