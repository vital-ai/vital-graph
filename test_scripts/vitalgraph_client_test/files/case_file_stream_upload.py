#!/usr/bin/env python3
"""
File Streaming Upload Test Case

Tests streaming file upload operations using the new /api/files/stream/upload endpoint.
Includes comprehensive timing tests for performance analysis.
"""

import logging
import tempfile
import time
import asyncio
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from vitalgraph.client.binary.async_streaming import AsyncFilePathGenerator, AsyncBytesGenerator


async def run_file_stream_upload_tests(
    client,
    space_id: str,
    graph_id: str,
    file_uri: str,
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    Run file streaming upload tests with comprehensive timing analysis.
    
    **ASYNC CONTEXT**: This function runs in async context and uses async generators,
    making it suitable for deployment in FastAPI async endpoints. All streaming
    operations use proper async/await patterns for optimal performance.
    
    Args:
        client: VitalGraph client instance
        space_id: Space identifier
        graph_id: Graph identifier
        file_uri: File URI to upload to
        logger: Optional logger instance
        
    Returns:
        bool: True if all tests passed, False otherwise
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🔧 Testing File Streaming Upload operations with timing analysis...")
    
    all_passed = True
    timing_results: List[Dict[str, any]] = []
    
    # Test 1: Stream upload with AsyncFilePathGenerator - Large PDF (15MB)
    logger.info("  Test 1: Stream upload - rt2.pdf (15MB), 8KB chunks...")
    try:
        test_file_path = Path("/Users/hadfield/Local/vital-git/vital-graph/test_files/rt2.pdf")
        chunk_size = 8192
        
        if not test_file_path.exists():
            logger.error(f"    ❌ Test file not found: {test_file_path}")
            all_passed = False
        else:
            actual_size = test_file_path.stat().st_size
            
            # Create async generator for streaming upload
            generator = AsyncFilePathGenerator(
                file_path=str(test_file_path),
                chunk_size=chunk_size,
                content_type="application/pdf"
            )
            
            # Time the upload
            start_time = time.perf_counter()
            response = await client.files.upload_file_stream_async(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=file_uri,
                source=generator,
                chunk_size=chunk_size
            )
            end_time = time.perf_counter()
            duration = end_time - start_time
            
            if response and hasattr(response, 'message'):
                throughput_mbps = (actual_size / (1024 * 1024)) / duration
                timing_results.append({
                    'test': 'rt2.pdf (15MB), 8KB chunks',
                    'size_mb': actual_size / (1024 * 1024),
                    'chunk_size': chunk_size,
                    'duration': duration,
                    'throughput_mbps': throughput_mbps
                })
                logger.info(f"    ✅ Upload successful: {actual_size:,} bytes in {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
            else:
                logger.error(f"    ❌ Stream upload failed: Invalid response")
                all_passed = False
            
    except Exception as e:
        logger.error(f"    ❌ Stream upload failed: {e}")
        all_passed = False
    
    # Test 2: Stream upload with AsyncBytesGenerator - Small data (100KB)
    logger.info("  Test 2: Stream upload with AsyncBytesGenerator - 100KB, 4KB chunks...")
    try:
        # Create test data
        test_bytes = b"Streaming bytes test data " * 4000  # ~100KB
        actual_size = len(test_bytes)
        chunk_size = 4096
        
        # Create async generator for streaming upload
        generator = AsyncBytesGenerator(
            data=test_bytes,
            chunk_size=chunk_size,
            filename="test_bytes.bin",
            content_type="application/octet-stream"
        )
        
        # Time the upload
        start_time = time.perf_counter()
        response = await client.files.upload_file_stream_async(
            space_id=space_id,
            graph_id=graph_id,
            file_uri=file_uri,
            source=generator,
            chunk_size=chunk_size
        )
        end_time = time.perf_counter()
        duration = end_time - start_time
        
        if response and hasattr(response, 'message'):
            throughput_mbps = (actual_size / (1024 * 1024)) / duration
            timing_results.append({
                'test': 'AsyncBytesGenerator 100KB',
                'size_mb': actual_size / (1024 * 1024),
                'chunk_size': chunk_size,
                'duration': duration,
                'throughput_mbps': throughput_mbps
            })
            logger.info(f"    ✅ Upload successful: {actual_size:,} bytes in {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
        else:
            logger.error(f"    ❌ Stream upload failed: Invalid response")
            all_passed = False
            
    except Exception as e:
        logger.error(f"    ❌ Stream upload failed: {e}")
        all_passed = False
    
    # Test 3: Stream upload - rt1.pdf (14MB) with 64KB chunks
    logger.info("  Test 3: Stream upload - rt1.pdf (14MB), 64KB chunks...")
    try:
        test_file_path = Path("/Users/hadfield/Local/vital-git/vital-graph/test_files/rt1.pdf")
        chunk_size = 65536  # 64KB
        
        if not test_file_path.exists():
            logger.error(f"    ❌ Test file not found: {test_file_path}")
            all_passed = False
        else:
            actual_size = test_file_path.stat().st_size
            
            generator = AsyncFilePathGenerator(
                file_path=str(test_file_path),
                chunk_size=chunk_size,
                content_type="application/pdf"
            )
            
            start_time = time.perf_counter()
            response = await client.files.upload_file_stream_async(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=file_uri,
                source=generator,
                chunk_size=chunk_size
            )
            end_time = time.perf_counter()
            duration = end_time - start_time
            
            if response and hasattr(response, 'message'):
                throughput_mbps = (actual_size / (1024 * 1024)) / duration
                timing_results.append({
                    'test': 'rt1.pdf (14MB), 64KB chunks',
                    'size_mb': actual_size / (1024 * 1024),
                    'chunk_size': chunk_size,
                    'duration': duration,
                    'throughput_mbps': throughput_mbps
                })
                logger.info(f"    ✅ Upload successful: {actual_size:,} bytes in {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
            else:
                logger.error(f"    ❌ Stream upload failed: Invalid response")
                all_passed = False
            
    except Exception as e:
        logger.error(f"    ❌ Stream upload failed: {e}")
        all_passed = False
    
    # Test 4: Chunk size comparison - the-illusion-of-thinking.pdf (13MB)
    logger.info("  Test 4: Chunk size comparison - the-illusion-of-thinking.pdf (13MB)...")
    chunk_sizes = [4096, 8192, 16384, 32768, 65536, 131072]  # 4KB to 128KB
    test_file_path = Path("/Users/hadfield/Local/vital-git/vital-graph/test_files/the-illusion-of-thinking.pdf")
    
    if not test_file_path.exists():
        logger.error(f"    ❌ Test file not found: {test_file_path}")
        all_passed = False
    else:
        actual_size = test_file_path.stat().st_size
        
        for chunk_size in chunk_sizes:
            try:
                generator = AsyncFilePathGenerator(
                    file_path=str(test_file_path),
                    chunk_size=chunk_size,
                    content_type="application/pdf"
                )
                
                start_time = time.perf_counter()
                response = await client.files.upload_file_stream_async(
                    space_id=space_id,
                    graph_id=graph_id,
                    file_uri=file_uri,
                    source=generator,
                    chunk_size=chunk_size
                )
                end_time = time.perf_counter()
                duration = end_time - start_time
                
                if response and hasattr(response, 'message'):
                    throughput_mbps = (actual_size / (1024 * 1024)) / duration
                    timing_results.append({
                        'test': f'13MB PDF, {chunk_size//1024}KB chunks',
                        'size_mb': actual_size / (1024 * 1024),
                        'chunk_size': chunk_size,
                        'duration': duration,
                        'throughput_mbps': throughput_mbps
                    })
                    logger.info(f"    ✅ {chunk_size//1024}KB chunks: {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
                else:
                    logger.error(f"    ❌ {chunk_size//1024}KB chunks failed")
                    all_passed = False
                    
            except Exception as e:
                logger.error(f"    ❌ {chunk_size//1024}KB chunks failed: {e}")
                all_passed = False
    
    # Test 5: Multiple file upload comparison
    logger.info("  Test 5: Multiple large files with optimal chunk size (128KB)...")
    test_files = [
        ("rt2.pdf", 15),
        ("rt1.pdf", 14),
        ("the-illusion-of-thinking.pdf", 13)
    ]
    chunk_size = 131072  # 128KB
    
    for filename, expected_mb in test_files:
        try:
            test_file_path = Path(f"/Users/hadfield/Local/vital-git/vital-graph/test_files/{filename}")
            
            if not test_file_path.exists():
                logger.warning(f"    ⚠️ Test file not found: {filename}")
                continue
                
            actual_size = test_file_path.stat().st_size
            
            generator = AsyncFilePathGenerator(
                file_path=str(test_file_path),
                chunk_size=chunk_size,
                content_type="application/pdf"
            )
            
            start_time = time.perf_counter()
            response = await client.files.upload_file_stream_async(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=file_uri,
                source=generator,
                chunk_size=chunk_size
            )
            end_time = time.perf_counter()
            duration = end_time - start_time
            
            if response and hasattr(response, 'message'):
                throughput_mbps = (actual_size / (1024 * 1024)) / duration
                timing_results.append({
                    'test': f'{filename} ({expected_mb}MB)',
                    'size_mb': actual_size / (1024 * 1024),
                    'chunk_size': chunk_size,
                    'duration': duration,
                    'throughput_mbps': throughput_mbps
                })
                logger.info(f"    ✅ {filename}: {actual_size:,} bytes in {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
            else:
                logger.error(f"    ❌ {filename} upload failed")
                all_passed = False
                
        except Exception as e:
            logger.error(f"    ❌ {filename} upload failed: {e}")
            all_passed = False
    
    # Print timing summary
    if timing_results:
        logger.info("\n" + "=" * 80)
        logger.info("📊 STREAMING UPLOAD TIMING SUMMARY")
        logger.info("=" * 80)
        for result in timing_results:
            logger.info(f"  {result['test']:40s} | {result['size_mb']:6.2f} MB | "
                       f"{result['chunk_size']//1024:4d} KB chunks | "
                       f"{result['duration']:7.3f}s | {result['throughput_mbps']:7.2f} MB/s")
        logger.info("=" * 80)
    
    if all_passed:
        logger.info("✅ All File Streaming Upload tests passed")
    else:
        logger.error("❌ Some File Streaming Upload tests failed")
    
    return all_passed
