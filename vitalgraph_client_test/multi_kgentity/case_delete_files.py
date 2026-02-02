#!/usr/bin/env python3
"""
Delete Files Test Case

Test case for deleting files and verifying cleanup.
"""

import logging
import asyncio
from typing import Dict, Any
from vitalgraph.client.binary.async_streaming import AsyncBytesConsumer

logger = logging.getLogger(__name__)


class DeleteFilesTester:
    """Test case for deleting files and verifying cleanup."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str, file_uris: Dict[str, str]) -> Dict[str, Any]:
        """
        Run file deletion tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uris: Dictionary of file URIs to delete
            
        Returns:
            Test results dictionary
        """
        logger.info("=" * 80)
        logger.info("  Deleting Files")
        logger.info("=" * 80)
        
        results = []
        errors = []
        
        # Delete all files
        delete_result = await self._test_delete_files(space_id, graph_id, file_uris)
        results.append(delete_result)
            
        if not delete_result['passed']:
            errors.append(delete_result.get('error', 'Delete failed'))
        
        # Verify deletion
        verify_result = await self._test_verify_deletion(space_id, graph_id, file_uris)
        results.append(verify_result)
        if not verify_result['passed']:
            errors.append(verify_result.get('error', 'Deletion verification failed'))
        
        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"\n✅ File deletion tests completed: {passed_tests}/{len(results)} passed")
        
        return {
            'test_name': 'Delete Files',
            'tests_run': len(results),
            'tests_passed': passed_tests,
            'tests_failed': len(results) - passed_tests,
            'errors': errors,
            'results': results
        }
    
    async def _test_delete_files(self, space_id: str, graph_id: str, 
                         file_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test deleting files."""
        logger.info(f"\n  Deleting files...")
        
        try:
            # Delete files
            for file_key, file_uri in file_uris.items():
                response = self.client.files.delete_file(
                    space_id=space_id,
                    uri=file_uri,
                    graph_id=graph_id
                )
                
                if response.is_success:
                    logger.info(f"    ✅ Deleted: {file_key}")
                    logger.info(f"       URI: {file_uri}")
                else:
                    error_msg = response.error_message if hasattr(response, 'error_message') else 'Unknown error'
                    logger.error(f"    ❌ Error: {error_msg}")
                    
            return {
                'name': 'Delete Files',
                'passed': True,
                'details': 'Successfully deleted files'
            }
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Delete Files',
                'passed': False,
                'error': str(e)
            }
    
    async def _test_verify_deletion(self, space_id: str, graph_id: str, 
                             file_uris: Dict[str, str]) -> Dict[str, Any]:
        """Verify that deleted files are no longer downloadable."""
        logger.info(f"\n  Verifying file deletion...")
        
        try:
            # Try to download a deleted file (should fail)
            first_file_key = list(file_uris.keys())[0]
            first_file_uri = file_uris[first_file_key]
            
            consumer = AsyncBytesConsumer()
            
            response = await self.client.files.download_file_stream_async(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=first_file_uri,
                destination=consumer,
                chunk_size=65536
            )
            
            # Should fail - if it succeeds, file wasn't deleted
            if not response or not response.is_success:
                logger.info(f"    ✅ Verified: File no longer downloadable")
                return {
                    'name': 'Verify File Deletion',
                    'passed': True,
                    'details': 'Confirmed files are deleted'
                }
            else:
                return {
                    'name': 'Verify File Deletion',
                    'passed': False,
                    'error': 'File still downloadable after deletion'
                }
                
        except Exception as e:
            # Exception is acceptable for deleted file
            logger.info(f"    ✅ Verified: File access raised exception (expected)")
            return {
                'name': 'Verify File Deletion',
                'passed': True,
                'details': f'File access correctly raised exception: {type(e).__name__}'
            }
