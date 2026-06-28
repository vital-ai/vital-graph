#!/usr/bin/env python3
"""
File Streaming Download Test Case

Tests streaming file download operations using the new /api/files/stream/download endpoint.
Includes comprehensive timing tests for performance analysis.
"""

import asyncio
import logging
import time
import hashlib
from pathlib import Path
from typing import Optional, Dict, List
from vitalgraph.client.binary.async_streaming import AsyncFilePathConsumer


async def run_file_stream_download_tests(
    client,
    space_id: str,
    graph_id: str,
    file_uri: str,
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    Run file streaming download tests with comprehensive timing analysis.
    
    **ASYNC CONTEXT**: This function runs in async context and uses async consumers,
    making it suitable for deployment in FastAPI async endpoints. All streaming
    operations use proper async/await patterns for optimal performance.
    
    Args:
        client: VitalGraph client instance
        space_id: Space identifier
        graph_id: Graph identifier
        file_uri: File URI to download from
        logger: Optional logger instance
        
    Returns:
        bool: True if all tests passed, False otherwise
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🔧 Testing File Streaming Download operations with timing analysis...")
    
    all_passed = True
    timing_results: List[Dict[str, any]] = []
    
    # Test 1: Stream download with AsyncFilePathConsumer - 8KB chunks
    logger.info("  Test 1: Stream download with AsyncFilePathConsumer - 8KB chunks...")
    try:
        download_dir = Path("/Users/hadfield/Local/vital-git/vital-graph/test_files_download")
        download_path = download_dir / "stream_download_test_1.bin"
        chunk_size = 8192
        
        try:
            consumer = AsyncFilePathConsumer(download_path, create_dirs=False)
            
            start_time = time.perf_counter()
            response = await client.files.download_file_stream_async(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=file_uri,
                destination=consumer,
                chunk_size=chunk_size
            )
            end_time = time.perf_counter()
            duration = end_time - start_time
            
            if response and hasattr(response, 'file_size'):
                if download_path.exists() and download_path.stat().st_size > 0:
                    file_size = download_path.stat().st_size
                    throughput_mbps = (file_size / (1024 * 1024)) / duration
                    timing_results.append({
                        'test': 'AsyncFilePathConsumer 8KB',
                        'size_mb': file_size / (1024 * 1024),
                        'chunk_size': chunk_size,
                        'duration': duration,
                        'throughput_mbps': throughput_mbps
                    })
                    logger.info(f"    ✅ Download successful: {file_size:,} bytes in {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
                else:
                    logger.error(f"    ❌ Download failed: File empty or not created")
                    all_passed = False
            else:
                logger.error(f"    ❌ Download failed: Invalid response")
                all_passed = False
        finally:
            download_path.unlink(missing_ok=True)
            
    except Exception as e:
        logger.error(f"    ❌ Download failed: {e}")
        all_passed = False
    
    # Test 2: Stream download with 64KB chunks
    logger.info("  Test 2: Stream download with 64KB chunks...")
    try:
        download_dir = Path("/Users/hadfield/Local/vital-git/vital-graph/test_files_download")
        download_path = download_dir / "stream_download_test_2.dat"
        chunk_size = 65536  # 64KB
        
        try:
            consumer = AsyncFilePathConsumer(download_path, create_dirs=False)
            
            start_time = time.perf_counter()
            response = await client.files.download_file_stream_async(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=file_uri,
                destination=consumer,
                chunk_size=chunk_size
            )
            end_time = time.perf_counter()
            duration = end_time - start_time
            
            if response and hasattr(response, 'file_size'):
                if download_path.exists() and download_path.stat().st_size > 0:
                    file_size = download_path.stat().st_size
                    throughput_mbps = (file_size / (1024 * 1024)) / duration
                    timing_results.append({
                        'test': '64KB chunks',
                        'size_mb': file_size / (1024 * 1024),
                        'chunk_size': chunk_size,
                        'duration': duration,
                        'throughput_mbps': throughput_mbps
                    })
                    logger.info(f"    ✅ Download successful: {file_size:,} bytes in {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
                else:
                    logger.error(f"    ❌ Download failed: File empty or not created")
                    all_passed = False
            else:
                logger.error(f"    ❌ Download failed: Invalid response")
                all_passed = False
        finally:
            download_path.unlink(missing_ok=True)
            
    except Exception as e:
        logger.error(f"    ❌ Download failed: {e}")
        all_passed = False
    
    # Test 3: Content integrity verification with checksum
    logger.info("  Test 3: Content integrity verification with checksum...")
    try:
        download_dir = Path("/Users/hadfield/Local/vital-git/vital-graph/test_files_download")
        download_path = download_dir / "stream_download_test_3.verify"
        chunk_size = 4096
        
        try:
            consumer = AsyncFilePathConsumer(download_path, create_dirs=False)
            
            start_time = time.perf_counter()
            response = await client.files.download_file_stream_async(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=file_uri,
                destination=consumer,
                chunk_size=chunk_size
            )
            end_time = time.perf_counter()
            duration = end_time - start_time
            
            if response and hasattr(response, 'file_size'):
                actual_size = download_path.stat().st_size
                reported_size = response.file_size
                
                # Calculate checksum
                md5_hash = hashlib.md5()
                with open(download_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(8192), b''):
                        md5_hash.update(chunk)
                checksum = md5_hash.hexdigest()
                
                if actual_size == reported_size:
                    throughput_mbps = (actual_size / (1024 * 1024)) / duration
                    timing_results.append({
                        'test': 'Integrity check 4KB',
                        'size_mb': actual_size / (1024 * 1024),
                        'chunk_size': chunk_size,
                        'duration': duration,
                        'throughput_mbps': throughput_mbps
                    })
                    logger.info(f"    ✅ Integrity verified: {actual_size:,} bytes, MD5: {checksum[:16]}...")
                    logger.info(f"       {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
                else:
                    logger.error(f"    ❌ Integrity failed: Expected {reported_size}, got {actual_size}")
                    all_passed = False
            else:
                logger.error(f"    ❌ Integrity check failed: Invalid response")
                all_passed = False
        finally:
            download_path.unlink(missing_ok=True)
            
    except Exception as e:
        logger.error(f"    ❌ Integrity check failed: {e}")
        all_passed = False
    
    # Test 4: Chunk size comparison
    logger.info("  Test 4: Chunk size comparison...")
    chunk_sizes = [4096, 8192, 16384, 32768, 65536, 131072]  # 4KB to 128KB
    
    for chunk_size in chunk_sizes:
        try:
            download_dir = Path("/Users/hadfield/Local/vital-git/vital-graph/test_files_download")
            download_path = download_dir / f"stream_download_chunk_{chunk_size}.dat"
            
            try:
                consumer = AsyncFilePathConsumer(download_path, create_dirs=False)
                
                start_time = time.perf_counter()
                response = await client.files.download_file_stream_async(
                    space_id=space_id,
                    graph_id=graph_id,
                    file_uri=file_uri,
                    destination=consumer,
                    chunk_size=chunk_size
                )
                end_time = time.perf_counter()
                duration = end_time - start_time
                
                if response and hasattr(response, 'file_size'):
                    if download_path.exists():
                        file_size = download_path.stat().st_size
                        throughput_mbps = (file_size / (1024 * 1024)) / duration
                        timing_results.append({
                            'test': f'{chunk_size//1024}KB chunks',
                            'size_mb': file_size / (1024 * 1024),
                            'chunk_size': chunk_size,
                            'duration': duration,
                            'throughput_mbps': throughput_mbps
                        })
                        logger.info(f"    ✅ {chunk_size//1024}KB chunks: {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
                    else:
                        logger.error(f"    ❌ {chunk_size//1024}KB chunks failed: File not created")
                        all_passed = False
                else:
                    logger.error(f"    ❌ {chunk_size//1024}KB chunks failed: Invalid response")
                    all_passed = False
            finally:
                download_path.unlink(missing_ok=True)
                
        except Exception as e:
            logger.error(f"    ❌ {chunk_size//1024}KB chunks failed: {e}")
            all_passed = False
    
    # Test 5: Parallel downloads (5 concurrent)
    logger.info("  Test 5: Parallel downloads (5 concurrent, 64KB chunks)...")
    try:
        download_dir = Path("/Users/hadfield/Local/vital-git/vital-graph/test_files_download")
        chunk_size = 65536
        num_parallel = 5
        
        async def download_file(index: int):
            download_path = download_dir / f"stream_download_parallel_{index}.dat"
            try:
                consumer = AsyncFilePathConsumer(download_path, create_dirs=False)
                response = await client.files.download_file_stream_async(
                    space_id=space_id,
                    graph_id=graph_id,
                    file_uri=file_uri,
                    destination=consumer,
                    chunk_size=chunk_size
                )
                return download_path, response
            except Exception as e:
                logger.error(f"      Parallel download {index} failed: {e}")
                return download_path, None
        
        start_time = time.perf_counter()
        results = await asyncio.gather(*[download_file(i) for i in range(num_parallel)])
        end_time = time.perf_counter()
        duration = end_time - start_time
        
        successful = 0
        total_size = 0
        for download_path, response in results:
            if response and download_path.exists():
                total_size += download_path.stat().st_size
                successful += 1
            download_path.unlink(missing_ok=True)
        
        if successful == num_parallel:
            throughput_mbps = (total_size / (1024 * 1024)) / duration
            timing_results.append({
                'test': f'{num_parallel} parallel downloads',
                'size_mb': total_size / (1024 * 1024),
                'chunk_size': chunk_size,
                'duration': duration,
                'throughput_mbps': throughput_mbps
            })
            logger.info(f"    ✅ {num_parallel} parallel downloads: {total_size:,} bytes in {duration:.3f}s ({throughput_mbps:.2f} MB/s)")
        else:
            logger.error(f"    ❌ Parallel downloads failed: {successful}/{num_parallel} succeeded")
            all_passed = False
            
    except Exception as e:
        logger.error(f"    ❌ Parallel downloads failed: {e}")
        all_passed = False
    
    # Print timing summary
    if timing_results:
        logger.info("\n" + "=" * 80)
        logger.info("📊 STREAMING DOWNLOAD TIMING SUMMARY")
        logger.info("=" * 80)
        for result in timing_results:
            logger.info(f"  {result['test']:40s} | {result['size_mb']:6.2f} MB | "
                       f"{result['chunk_size']//1024:4d} KB chunks | "
                       f"{result['duration']:7.3f}s | {result['throughput_mbps']:7.2f} MB/s")
        logger.info("=" * 80)
    
    if all_passed:
        logger.info("\n✅ All File Streaming Download tests passed")
    else:
        logger.error("\n❌ Some File Streaming Download tests failed")
    
    return all_passed
