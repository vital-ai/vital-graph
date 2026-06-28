"""
Files Delete Test Cases

Tests for deleting file nodes via the Files endpoint client.
Updated to use new response objects with direct GraphObject access.
"""

import logging
from typing import Dict, Any
from vital_ai_domain.model.FileNode import FileNode


async def run_file_delete_tests(client, space_id: str, graph_id: str, logger=None) -> bool:
    """Run file deletion tests."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🧪 Running File Delete Tests")
    
    try:
        # Test 1: Create a file to delete
        logger.info("  Test 1: Create file for deletion test")
        
        file_node = FileNode()
        file_node.URI = "haley:file_test_delete_001"
        file_node.name = "File to Delete"
        
        response = await client.files.create_file(
            space_id=space_id,
            graph_id=graph_id,
            objects=[file_node]
        )
        
        if not response.is_success or response.created_count == 0:
            logger.error(f"  ❌ Failed to create file for deletion test: {response.error_message}")
            return False
        
        logger.info("  ✅ Created file for deletion test")
        
        # Test 2: Delete the file
        logger.info("  Test 2: Delete file by URI")
        
        response = await client.files.delete_file(
            space_id=space_id,
            graph_id=graph_id,
            uri="haley:file_test_delete_001"
        )
        
        if response.is_success and response.deleted_count > 0:
            logger.info("  ✅ File deleted successfully")
        else:
            logger.error(f"  ❌ Failed to delete file: {response.error_message}")
            return False
        
        # Test 3: Verify file is deleted
        logger.info("  Test 3: Verify file no longer exists")
        
        response = await client.files.get_file(
            space_id=space_id,
            graph_id=graph_id,
            uri="haley:file_test_delete_001"
        )
        
        # Check if response indicates file not found - file should be completely deleted
        if response.is_error or not response.file:
            logger.info("  ✅ Verified file was deleted")
        else:
            logger.error("  ❌ File still exists after deletion - FileNode was not removed from database")
            return False
        
        # Test 4: Create multiple files for batch deletion
        logger.info("  Test 4: Create multiple files for batch deletion")
        
        file_node_1 = FileNode()
        file_node_1.URI = "haley:file_test_batch_delete_001"
        file_node_1.name = "Batch Delete File 1"
        
        file_node_2 = FileNode()
        file_node_2.URI = "haley:file_test_batch_delete_002"
        file_node_2.name = "Batch Delete File 2"
        
        response = await client.files.create_file(
            space_id=space_id,
            graph_id=graph_id,
            objects=[file_node_1, file_node_2]
        )
        
        if not response.is_success or response.created_count < 2:
            logger.error(f"  ❌ Failed to create files for batch deletion test: {response.error_message}")
            return False
        
        logger.info(f"  ✅ Created {response.created_count} files for batch deletion")
        
        # Test 5: Batch delete files
        logger.info("  Test 5: Batch delete multiple files")
        
        uri_list = "haley:file_test_batch_delete_001,haley:file_test_batch_delete_002"
        
        response = await client.files.delete_files_batch(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=uri_list
        )
        
        if response and response.get('deleted_count', 0) >= 2:
            logger.info(f"  ✅ Batch deleted {response.get('deleted_count')} files successfully")
        else:
            logger.error("  ❌ Failed to batch delete files")
            return False
        
        # Test 6: Verify batch deleted files no longer exist
        logger.info("  Test 6: Verify batch deleted files no longer exist")
        
        response = await client.files.get_file(
            space_id=space_id,
            graph_id=graph_id,
            uri="haley:file_test_batch_delete_001"
        )
        
        if response.is_error or not response.file:
            logger.info("  ✅ Verified batch deleted files were removed")
        else:
            logger.error("  ❌ Batch deleted file still exists in database")
            return False
        
        logger.info("✅ All file delete tests passed")
        return True
        
    except Exception as e:
        logger.error(f"❌ File delete tests failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
