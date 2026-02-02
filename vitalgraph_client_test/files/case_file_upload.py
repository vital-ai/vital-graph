"""
Files Upload Test Cases

Tests for uploading file content via the Files endpoint client.
Updated to use new FileUploadResponse objects.
Includes comprehensive timing measurements.
"""

import logging
import io
import time
from pathlib import Path
from typing import Dict, Any, List


async def run_file_upload_tests(client, space_id: str, graph_id: str, file_uri: str, logger=None) -> bool:
    """Run file upload tests with timing measurements."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🧪 Running File Upload Tests with timing analysis...")
    
    timing_results: List[Dict[str, any]] = []
    
    try:
        # Test 1: Upload file from bytes
        logger.info("  Test 1: Upload file from bytes (real PDF)")
        pdf_path = Path("/Users/hadfield/Local/vital-git/vital-graph/test_files/2502.16143v1.pdf")
        test_content = pdf_path.read_bytes()
        file_size = len(test_content)
        
        start_time = time.perf_counter()
        response = client.files.upload_file_content(
            space_id=space_id,
            graph_id=graph_id,
            file_uri=file_uri,
            source=test_content,
            filename="2502.16143v1.pdf",
            content_type="application/pdf"
        )
        end_time = time.perf_counter()
        duration = end_time - start_time
        
        if response.is_success:
            throughput_mbps = (file_size / (1024 * 1024)) / duration
            timing_results.append({
                'test': 'Upload from bytes (PDF)',
                'size_mb': file_size / (1024 * 1024),
                'duration': duration,
                'throughput_mbps': throughput_mbps
            })
            logger.info(f"  ✅ Upload successful: {response.size:,} bytes in {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
        else:
            logger.error(f"  ❌ Failed to upload file from bytes: {response.error_message}")
            return False
        
        # Test 2: Upload file from stream
        logger.info("  Test 2: Upload file from stream (real PNG)")
        png_path = Path("/Users/hadfield/Local/vital-git/vital-graph/test_files/vampire_queen_baby.png")
        stream_content = png_path.read_bytes()
        file_size = len(stream_content)
        stream = io.BytesIO(stream_content)
        
        start_time = time.perf_counter()
        response = client.files.upload_file_content(
            space_id=space_id,
            graph_id=graph_id,
            file_uri=file_uri,
            source=stream,
            filename="vampire_queen_baby.png",
            content_type="image/png"
        )
        end_time = time.perf_counter()
        duration = end_time - start_time
        
        if response.is_success:
            throughput_mbps = (file_size / (1024 * 1024)) / duration
            timing_results.append({
                'test': 'Upload from stream (PNG)',
                'size_mb': file_size / (1024 * 1024),
                'duration': duration,
                'throughput_mbps': throughput_mbps
            })
            logger.info(f"  ✅ Upload successful: {response.size:,} bytes in {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
        else:
            logger.error(f"  ❌ Failed to upload file from stream: {response.error_message}")
            return False
        
        # Test 3: Upload larger file (using real PNG which is 2.5MB)
        logger.info("  Test 3: Upload larger file (2.5MB PNG)")
        large_content = png_path.read_bytes()
        file_size = len(large_content)
        
        start_time = time.perf_counter()
        response = client.files.upload_file_content(
            space_id=space_id,
            graph_id=graph_id,
            file_uri=file_uri,
            source=large_content,
            filename="large_file.bin",
            content_type="application/octet-stream"
        )
        end_time = time.perf_counter()
        duration = end_time - start_time
        
        if response.is_success:
            throughput_mbps = (file_size / (1024 * 1024)) / duration
            timing_results.append({
                'test': 'Upload large file (2.5MB)',
                'size_mb': file_size / (1024 * 1024),
                'duration': duration,
                'throughput_mbps': throughput_mbps
            })
            logger.info(f"  ✅ Upload successful: {response.size:,} bytes in {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
        else:
            logger.error(f"  ❌ Failed to upload large file: {response.error_message}")
            return False
        
        # Print timing summary
        if timing_results:
            logger.info("\n" + "=" * 80)
            logger.info("📊 REGULAR UPLOAD TIMING SUMMARY")
            logger.info("=" * 80)
            for result in timing_results:
                logger.info(f"  {result['test']:35s} | {result['size_mb']:6.2f} MB | "
                           f"{result['duration']:7.3f}s | {result['throughput_mbps']:7.2f} MB/s")
            logger.info("=" * 80)
        
        logger.info("\n✅ All file upload tests passed")
        return True
        
    except Exception as e:
        logger.error(f"❌ File upload tests failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
