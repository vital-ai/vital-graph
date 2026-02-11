"""
Files Download Test Cases

Tests for downloading file content via the Files endpoint client.
Updated to use new FileDownloadResponse objects.
Includes comprehensive timing measurements.
"""

import logging
import io
import time
from pathlib import Path
from typing import Dict, Any, List


async def run_file_download_tests(client, space_id: str, graph_id: str, file_uri: str, logger=None) -> bool:
    """Run file download tests with timing measurements."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🧪 Running File Download Tests with timing analysis...")
    
    timing_results: List[Dict[str, any]] = []
    
    try:
        # Test 1: Download file as bytes
        logger.info("  Test 1: Download file as bytes")
        
        start_time = time.perf_counter()
        content = await client.files.download_file_content(
            space_id=space_id,
            graph_id=graph_id,
            file_uri=file_uri,
            destination=None  # Returns bytes
        )
        end_time = time.perf_counter()
        duration = end_time - start_time
        
        if content and isinstance(content, bytes):
            file_size = len(content)
            throughput_mbps = (file_size / (1024 * 1024)) / duration
            timing_results.append({
                'test': 'Download as bytes',
                'size_mb': file_size / (1024 * 1024),
                'duration': duration,
                'throughput_mbps': throughput_mbps
            })
            logger.info(f"  ✅ Download successful: {file_size:,} bytes in {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
        else:
            logger.error("  ❌ Failed to download file as bytes")
            return False
        
        # Test 2: Download file to stream
        logger.info("  Test 2: Download file to stream")
        stream = io.BytesIO()
        
        start_time = time.perf_counter()
        result = await client.files.download_file_content(
            space_id=space_id,
            graph_id=graph_id,
            file_uri=file_uri,
            destination=stream
        )
        end_time = time.perf_counter()
        duration = end_time - start_time
        
        if result.is_success:
            stream.seek(0)
            downloaded_content = stream.read()
            file_size = len(downloaded_content)
            throughput_mbps = (file_size / (1024 * 1024)) / duration
            timing_results.append({
                'test': 'Download to stream',
                'size_mb': file_size / (1024 * 1024),
                'duration': duration,
                'throughput_mbps': throughput_mbps
            })
            logger.info(f"  ✅ Download successful: {result.size:,} bytes in {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
        else:
            logger.error(f"  ❌ Failed to download file to stream: {result.error_message}")
            return False
        
        # Print timing summary
        if timing_results:
            logger.info("\n" + "=" * 80)
            logger.info("📊 REGULAR DOWNLOAD TIMING SUMMARY")
            logger.info("=" * 80)
            for result in timing_results:
                logger.info(f"  {result['test']:35s} | {result['size_mb']:6.2f} MB | "
                           f"{result['duration']:7.3f}s | {result['throughput_mbps']:7.2f} MB/s")
            logger.info("=" * 80)
        
        logger.info("\n✅ All file download tests passed")
        return True
        
    except Exception as e:
        logger.error(f"❌ File download tests failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
