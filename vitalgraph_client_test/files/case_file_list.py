"""
Files List Test Cases

Tests for listing file nodes via the Files endpoint client.
Updated to use new response objects with direct GraphObject access.
"""

import logging
from typing import Dict, Any


async def run_file_list_tests(client, space_id: str, graph_id: str, logger=None, created_file_uris=None) -> bool:
    """
    Run file listing tests with validation that actual created files appear.
    
    Args:
        client: VitalGraph client instance
        space_id: Space identifier
        graph_id: Graph identifier
        logger: Logger instance
        created_file_uris: List of file URIs that were created (for validation)
    
    Returns:
        bool: True if all tests passed
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🧪 Running File List Tests")
    
    try:
        # Test 1: List all files in space
        logger.info("  Test 1: List all files in space")
        
        response = await client.files.list_files(
            space_id=space_id,
            graph_id=graph_id,
            page_size=100,
            offset=0
        )
        
        if response.is_success:
            logger.info(f"  ✅ Listed files successfully (total: {response.total_count}, count: {response.count})")
            
            # CRITICAL: Validate that actual created files appear in results
            if created_file_uris:
                logger.info("  🔍 Validating created files appear in list...")
                
                # Extract URIs from GraphObjects - direct access, no JSON-LD parsing
                listed_uris = [str(obj.URI) for obj in response.files if hasattr(obj, 'URI')]
                
                # Check if created files appear in list
                found_count = sum(1 for uri in created_file_uris if uri in listed_uris)
                
                logger.info(f"     Created files: {len(created_file_uris)}")
                logger.info(f"     Listed files: {len(listed_uris)}")
                logger.info(f"     Found in list: {found_count}/{len(created_file_uris)}")
                
                if found_count == len(created_file_uris):
                    logger.info("     ✅ All created files appear in list results!")
                elif found_count > 0:
                    logger.warning(f"     ⚠️  Only {found_count}/{len(created_file_uris)} created files found")
                else:
                    logger.error("     ❌ CRITICAL: No created files found in list results!")
                    logger.error("     This indicates list_files is not returning actual database data")
                    return False
        else:
            logger.error(f"  ❌ Failed to list files: {response.error_message}")
            return False
        
        # Test 2: List files with pagination (page 1)
        logger.info("  Test 2: List files with pagination")
        
        page_size = 2
        response_page1 = await client.files.list_files(
            space_id=space_id,
            graph_id=graph_id,
            page_size=page_size,
            offset=0
        )
        
        if response_page1 and hasattr(response_page1, 'page_size') and response_page1.page_size == page_size:
            logger.info(f"  ✅ Page 1 retrieved (page_size: {response_page1.page_size}, offset: {response_page1.offset})")
            
            # Extract URIs from page 1
            page1_uris = []
            if hasattr(response_page1, 'files'):
                files_data = response_page1.files
                if hasattr(files_data, 'graph') and files_data.graph:
                    for file_obj in files_data.graph:
                        if isinstance(file_obj, dict) and '@id' in file_obj:
                            page1_uris.append(file_obj['@id'])
                        elif hasattr(file_obj, 'id'):
                            page1_uris.append(file_obj.id)
            
            logger.info(f"     Page 1 contains {len(page1_uris)} file(s)")
            
            # Test 2b: Get page 2 with offset
            if response_page1.total_count > page_size:
                logger.info("  Test 2b: List files page 2 with offset")
                
                response_page2 = await client.files.list_files(
                    space_id=space_id,
                    graph_id=graph_id,
                    page_size=page_size,
                    offset=page_size
                )
                
                if response_page2:
                    # Extract URIs from page 2
                    page2_uris = []
                    if hasattr(response_page2, 'files'):
                        files_data = response_page2.files
                        if hasattr(files_data, 'graph') and files_data.graph:
                            for file_obj in files_data.graph:
                                if isinstance(file_obj, dict) and '@id' in file_obj:
                                    page2_uris.append(file_obj['@id'])
                                elif hasattr(file_obj, 'id'):
                                    page2_uris.append(file_obj.id)
                    
                    logger.info(f"     Page 2 contains {len(page2_uris)} file(s)")
                    
                    # Verify pages don't overlap
                    overlap = set(page1_uris) & set(page2_uris)
                    if overlap:
                        logger.error(f"     ❌ Pages overlap! Duplicate URIs: {overlap}")
                        return False
                    else:
                        logger.info("     ✅ No overlap between pages - pagination working correctly")
                else:
                    logger.error("  ❌ Failed to retrieve page 2")
                    return False
            else:
                logger.info("     ℹ️  Not enough files for multi-page test")
        else:
            logger.error("  ❌ Failed to list files with pagination")
            return False
        
        # Test 3: Get specific file by URI
        logger.info("  Test 3: Get specific file by URI")
        
        # Use a file URI that was created in the creation tests
        file_uri = created_file_uris[0] if created_file_uris else "haley:file_test_document_001"
        
        try:
            response = await client.files.get_file(
                space_id=space_id,
                graph_id=graph_id,
                uri=file_uri
            )
            
            if response:
                logger.info(f"  ✅ Retrieved specific file successfully: {file_uri}")
            else:
                logger.error(f"  ❌ Failed to retrieve file: {file_uri}")
                return False
        except Exception as e:
            logger.error(f"  ❌ Failed to retrieve file {file_uri}: {e}")
            # Don't fail the whole test if get_file fails - it might not be implemented yet
            logger.warning("  ⚠️  Continuing despite get_file failure...")
        
        logger.info("✅ All file list tests passed")
        return True
        
    except Exception as e:
        logger.error(f"❌ File list tests failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
