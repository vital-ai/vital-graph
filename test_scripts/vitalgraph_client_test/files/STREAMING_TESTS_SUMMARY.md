# File Streaming Tests - Comprehensive Timing Analysis

## Overview

The file streaming tests have been enhanced with comprehensive timing measurements and are designed to run in **async context**, making them production-ready for FastAPI async endpoint deployment.

## Test Architecture

### Async Context ✅
- All streaming tests use `async/await` patterns
- Proper async generators (`AsyncFilePathGenerator`, `AsyncBytesGenerator`)
- Proper async consumers (`AsyncFilePathConsumer`)
- Ready for FastAPI async endpoint integration
- No blocking operations

### Real File Testing ✅
All tests use actual large PDF files from `/test_files`:
- **rt2.pdf** - 15MB
- **rt1.pdf** - 14MB
- **the-illusion-of-thinking.pdf** - 13MB

## Test Suites

### 1. Regular Upload Tests (`case_file_upload.py`)
**Timing Measurements:**
- Upload from bytes (PDF)
- Upload from stream (PNG, 2.5MB)
- Upload large file (2.5MB)

**Output:** Timing summary table with throughput (MB/s)

### 2. Regular Download Tests (`case_file_download.py`)
**Timing Measurements:**
- Download as bytes
- Download to stream

**Output:** Timing summary table with throughput (MB/s)

### 3. Streaming Upload Tests (`case_file_stream_upload.py`)
**Test Cases:**
1. **rt2.pdf (15MB)** with 8KB chunks
2. **AsyncBytesGenerator** with 100KB, 4KB chunks
3. **rt1.pdf (14MB)** with 64KB chunks
4. **Chunk size comparison** - the-illusion-of-thinking.pdf (13MB) with 6 different chunk sizes:
   - 4KB, 8KB, 16KB, 32KB, 64KB, 128KB
5. **Multiple large files** with optimal 128KB chunks:
   - rt2.pdf (15MB)
   - rt1.pdf (14MB)
   - the-illusion-of-thinking.pdf (13MB)

**Output:** Comprehensive timing summary with:
- File size (MB)
- Chunk size (KB)
- Duration (seconds)
- Throughput (MB/s)

### 4. Streaming Download Tests (`case_file_stream_download.py`)
**Test Cases:**
1. **AsyncFilePathConsumer** with 8KB chunks
2. **64KB chunks** performance test
3. **Content integrity** with MD5 checksum verification
4. **Chunk size comparison** with 6 different chunk sizes:
   - 4KB, 8KB, 16KB, 32KB, 64KB, 128KB
5. **Parallel downloads** - 5 concurrent downloads with 64KB chunks

**Output:** Comprehensive timing summary with:
- File size (MB)
- Chunk size (KB)
- Duration (seconds)
- Throughput (MB/s)

## Performance Metrics

All tests report:
- ✅ **File size** in MB
- ✅ **Duration** in seconds (high-precision `time.perf_counter()`)
- ✅ **Throughput** in MB/s
- ✅ **Chunk size** for streaming operations

## Timing Summary Tables

Each test suite produces a formatted timing summary:

```
================================================================================
📊 STREAMING UPLOAD TIMING SUMMARY
================================================================================
  rt2.pdf (15MB), 8KB chunks              |  15.00 MB |    8 KB chunks |   2.345s |   6.40 MB/s
  AsyncBytesGenerator 100KB               |   0.10 MB |    4 KB chunks |   0.023s |   4.35 MB/s
  rt1.pdf (14MB), 64KB chunks             |  14.00 MB |   64 KB chunks |   1.987s |   7.05 MB/s
  13MB PDF, 4KB chunks                    |  13.00 MB |    4 KB chunks |   2.456s |   5.29 MB/s
  13MB PDF, 8KB chunks                    |  13.00 MB |    8 KB chunks |   2.123s |   6.12 MB/s
  ...
================================================================================
```

## FastAPI Integration Ready

The streaming tests demonstrate production-ready patterns:

```python
# Example FastAPI endpoint using the same patterns
@app.post("/api/files/stream/upload")
async def upload_file_stream(
    space_id: str,
    graph_id: str,
    file_uri: str,
    file: UploadFile
):
    # Use AsyncFilePathGenerator or AsyncBytesGenerator
    generator = AsyncFilePathGenerator(
        file_path=temp_path,
        chunk_size=65536,
        content_type=file.content_type
    )
    
    # Upload with async/await
    response = await client.files.upload_file_stream_async(
        space_id=space_id,
        graph_id=graph_id,
        file_uri=file_uri,
        source=generator,
        chunk_size=65536
    )
    
    return response

@app.get("/api/files/stream/download")
async def download_file_stream(
    space_id: str,
    graph_id: str,
    file_uri: str
):
    # Use AsyncFilePathConsumer
    consumer = AsyncFilePathConsumer(
        file_path=download_path,
        create_dirs=True
    )
    
    # Download with async/await
    response = await client.files.download_file_stream_async(
        space_id=space_id,
        graph_id=graph_id,
        file_uri=file_uri,
        destination=consumer,
        chunk_size=65536
    )
    
    return FileResponse(download_path)
```

## Key Features

✅ **Async/await throughout** - No blocking operations
✅ **Real file testing** - 13-15MB PDFs for realistic performance data
✅ **Comprehensive timing** - All operations timed with high precision
✅ **Chunk size analysis** - Tests 6 different chunk sizes (4KB to 128KB)
✅ **Parallel operations** - Tests concurrent downloads (5 simultaneous)
✅ **Content integrity** - MD5 checksum verification
✅ **Production-ready** - Patterns match FastAPI async endpoint requirements
✅ **Formatted reports** - Easy-to-read timing summary tables

## Running the Tests

```bash
cd /Users/hadfield/Local/vital-git/vital-graph
python vitalgraph_client_test/test_files_endpoint.py
```

The test will produce comprehensive timing reports for:
- Regular uploads
- Regular downloads
- Streaming uploads (with chunk size comparison)
- Streaming downloads (with parallel operations)

All timing data helps optimize chunk sizes and identify performance bottlenecks for production deployment.
