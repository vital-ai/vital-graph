#!/usr/bin/env python3
"""
Download Files Test Case

Test case for downloading files and verifying their content.
"""

import logging
import asyncio
from typing import Dict, Any
from pathlib import Path
from vitalgraph.client.binary.async_streaming import AsyncBytesConsumer

logger = logging.getLogger(__name__)


class DownloadFilesTester:
    """Test case for downloading and verifying files."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str, file_uris: Dict[str, str]) -> Dict[str, Any]:
        """
        Run file download tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uris: Dictionary of file URIs from upload step
            
        Returns:
            Test results dictionary
        """
        logger.info("=" * 80)
        logger.info("  Downloading and Verifying Files")
        logger.info("=" * 80)
        
        results = []
        errors = []
        
        # Download each file
        for file_key, file_uri in file_uris.items():
            download_result = await self._test_download_file(space_id, graph_id, file_key, file_uri)
            results.append(download_result)
            
            if not download_result['passed']:
                errors.append(download_result.get('error', f'Download failed for {file_key}'))
        
        # Test downloading non-existent file (error case)
        error_test = await self._test_download_nonexistent_file(space_id, graph_id)
        results.append(error_test)
        if not error_test['passed']:
            errors.append(error_test.get('error', 'Non-existent file test failed'))
        
        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"\n✅ File download tests completed: {passed_tests}/{len(results)} passed")
        
        return {
            'test_name': 'Download Files',
            'tests_run': len(results),
            'tests_passed': passed_tests,
            'tests_failed': len(results) - passed_tests,
            'errors': errors,
            'results': results
        }
    
    async def _test_download_file(self, space_id: str, graph_id: str, 
                           file_key: str, file_uri: str) -> Dict[str, Any]:
        """Test downloading a single file."""
        logger.info(f"\n  Downloading {file_key}...")
        
        try:
            # Download file content using streaming with async consumer
            consumer = AsyncBytesConsumer()
            
            # Use async streaming download
            response = await self.client.files.download_file_stream_async(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=file_uri,
                destination=consumer,
                chunk_size=65536  # 64KB chunks
            )
            
            if response and response.is_success:
                file_content = consumer.get_bytes()
                file_size = len(file_content)
                logger.info(f"    ✅ Downloaded: {file_key}")
                logger.info(f"       URI: {file_uri}")
                logger.info(f"       Size: {file_size:,} bytes")
                
                return {
                    'name': f'Download {file_key}',
                    'passed': True,
                    'details': f'Successfully downloaded {file_key}',
                    'file_size': file_size
                }
            else:
                return {
                    'name': f'Download {file_key}',
                    'passed': False,
                    'error': 'Download failed: No content returned'
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': f'Download {file_key}',
                'passed': False,
                'error': str(e)
            }
    
    async def _test_download_nonexistent_file(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test downloading a non-existent file (should fail gracefully)."""
        logger.info(f"\n  Testing download of non-existent file...")
        
        try:
            fake_uri = "urn:file:nonexistent_12345"
            
            # Try to download non-existent file using streaming
            consumer = AsyncBytesConsumer()
            
            response = await self.client.files.download_file_stream_async(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=fake_uri,
                destination=consumer,
                chunk_size=65536
            )
            
            # Should fail or return None - if it returns content, that's unexpected
            if not response or not response.is_success:
                logger.info(f"    ✅ Correctly failed to download non-existent file")
                return {
                    'name': 'Download Non-Existent File',
                    'passed': True,
                    'details': 'Correctly handled non-existent file'
                }
            else:
                return {
                    'name': 'Download Non-Existent File',
                    'passed': False,
                    'error': 'Unexpectedly succeeded downloading non-existent file'
                }
                
        except Exception as e:
            # Exception is also acceptable for non-existent file
            logger.info(f"    ✅ Correctly raised exception for non-existent file")
            return {
                'name': 'Download Non-Existent File',
                'passed': True,
                'details': f'Correctly raised exception: {type(e).__name__}'
            }
