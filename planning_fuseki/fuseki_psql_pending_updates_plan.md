# VitalGraph Pending Updates Plan

**Date:** January 28, 2026  
**Status:** Planning Phase

## Overview

This document tracks critical updates needed for VitalGraph client and implementation:

1. **True Streaming File Upload/Download** - Implement chunk-based streaming for file operations

**KGTypes client migration summary (completed):** KGTypes client + mock + tests were migrated to accept `List[GraphObject]` (instead of JSON-LD models) and validated by client and multi-org tests.

---

## 1. True Streaming File Upload/Download

### Current State

**Problems:**
- Server endpoints load entire files into memory (not true streaming)
- Client uses synchronous generators (`BinaryGenerator`, `BinaryConsumer`)
- Incompatible with async FastAPI request chains: `request → API → VitalGraph → S3`
- No chunk-based processing

**Current Implementation:**
- **Server:** `vitalgraph/endpoint/files_endpoint.py`
  - `download_file()` - loads entire file into memory
  - `upload_file()` - reads entire upload into memory
- **Client:** `vitalgraph/client/binary/streaming.py`
  - `BinaryGenerator` - sync generator
  - `BinaryConsumer` - sync consumer
  - `CallableGenerator` - wrapper for plain generators

### Target State

**Goals:**
- True chunk-based streaming (configurable chunk size, default 8KB)
- Async generators for client compatibility with FastAPI
- Direct streaming to/from S3/MinIO without memory buffering
- Optional separate endpoints for streaming operations

### Implementation Plan

#### Phase 1: Server-Side Streaming (VitalGraph)

**1.1 Create New Streaming Endpoints (Optional Approach)**
- [ ] Add `POST /api/files/stream/upload` endpoint
- [ ] Add `GET /api/files/stream/download/{file_uri}` endpoint
- [ ] Keep existing endpoints for backward compatibility

**1.2 Implement Chunk-Based Upload**
- [ ] Update `files_endpoint.py` to use `StreamingResponse` with async generators
- [ ] Add configurable chunk size (default: 8192 bytes)
- [ ] Stream directly to S3/MinIO using `put_object` with streaming
- [ ] Add progress tracking/logging for large files
- [ ] Handle partial upload failures and cleanup

**Files to modify:**
- `vitalgraph/endpoint/files_endpoint.py`
- `vitalgraph/endpoint/impl/files_impl.py`

**1.3 Implement Chunk-Based Download**
- [ ] Use `StreamingResponse` with async generator
- [ ] Stream directly from S3/MinIO using `get_object` streaming API
- [ ] Add range request support for partial downloads
- [ ] Implement proper error handling for connection drops

**S3/MinIO Integration:**
- Verify `aioboto3` or MinIO async client supports streaming
- Use `get_object()['Body']` for streaming reads
- Use `put_object()` with file-like object for streaming writes

#### Phase 2: Client-Side Async Generators

**2.1 Create Async Binary Streaming Classes**
- [ ] Create `AsyncBinaryGenerator` class
  - Async generator yielding chunks
  - Compatible with `async for` loops
  - Configurable chunk size
- [ ] Create `AsyncBinaryConsumer` class
  - Async consumer processing chunks
  - Compatible with async iteration
- [ ] Add backward compatibility wrappers for sync code

**Files to create/modify:**
- `vitalgraph/client/binary/streaming.py`
  - Add `AsyncBinaryGenerator`
  - Add `AsyncBinaryConsumer`
  - Keep existing sync classes for compatibility

**2.2 Update Client Endpoints**
- [ ] Update `files_endpoint.py` client to use async generators
- [ ] Add streaming upload method: `upload_file_stream()`
- [ ] Add streaming download method: `download_file_stream()`
- [ ] Maintain backward compatibility with existing methods

**Files to modify:**
- `vitalgraph/client/endpoint/files_endpoint.py`

**2.3 Update MockVitalGraphClient**
- [ ] Add async streaming support to mock client
- [ ] Implement mock streaming for testing
- [ ] Ensure test compatibility

**Files to modify:**
- `vitalgraph/client/mock/mock_vitalgraph_client.py`

#### Phase 3: Configuration and Testing

**3.1 Add Configuration**
- [ ] Add `STREAMING_CHUNK_SIZE` config parameter (default: 8192)
- [ ] Add `STREAMING_ENABLED` feature flag
- [ ] Add `MAX_STREAMING_FILE_SIZE` limit

**3.2 Create Tests**
- [ ] Unit tests for async generators
- [ ] Integration tests for streaming upload/download
- [ ] Performance tests comparing memory usage
- [ ] Large file tests (>100MB)
- [ ] Connection interruption tests

**Test files to create:**
- `tests/test_streaming_upload.py`
- `tests/test_streaming_download.py`
- `tests/test_async_generators.py`

**Existing test files to update with streaming:**
- [ ] `vitalgraph_client_test/test_files_endpoint.py`
  - Add streaming upload test case
  - Add streaming download test case
  - Add large file streaming test (>100MB)
  - Compare memory usage: streaming vs. non-streaming
  - Test chunk-based progress tracking
- [ ] `vitalgraph_client_test/test_multiple_organizations_crud.py`
  - Add streaming upload for organization attachment files
  - Test streaming with multiple concurrent uploads
  - Verify streaming works in CRUD workflow context

#### Phase 4: Documentation

- [ ] Update API documentation with streaming endpoints
- [ ] Add client usage examples for async streaming
- [ ] Document chunk size configuration
- [ ] Add migration guide from sync to async

### Technical Details

**Async Generator Pattern:**
```python
async def async_binary_generator(file_path: str, chunk_size: int = 8192):
    async with aiofiles.open(file_path, 'rb') as f:
        while chunk := await f.read(chunk_size):
            yield chunk
```

**FastAPI Streaming Response:**
```python
async def stream_file(file_uri: str):
    async def generate():
        async for chunk in s3_client.stream_object(file_uri):
            yield chunk
    return StreamingResponse(generate(), media_type="application/octet-stream")
```

**Client Async Upload:**
```python
async def upload_file_stream(self, file_path: str, space_id: str):
    async def file_generator():
        async with aiofiles.open(file_path, 'rb') as f:
            while chunk := await f.read(8192):
                yield chunk
    
    async with self.session.post(url, data=file_generator()) as response:
        return await response.json()
```

### Success Criteria

- [ ] Memory usage remains constant regardless of file size
- [ ] Upload/download of 1GB+ files works without memory issues
- [ ] Client works seamlessly in async FastAPI contexts
- [ ] Backward compatibility maintained for existing code
- [ ] All tests passing

---

## Implementation Timeline

### Week 1: Streaming Implementation
- Days 1-2: Server-side streaming endpoints
- Days 3-4: Client async generators
- Day 5: Testing and bug fixes

---

## Dependencies

- `aiofiles` - for async file operations
- `aioboto3` or MinIO async client - for S3 streaming
- VitalSigns - for GraphObject operations

---

## Status Tracking

| Task | Status | Assignee | Notes |
|------|--------|----------|-------|
| Streaming server endpoints | Not Started | | |
| Async client generators | Not Started | | |
| Testing | Not Started | | |
| Documentation | Not Started | | |

---

**Last Updated:** January 28, 2026

**Test Run Results (Jan 28, 2026)**

- **[KGTypes client test]** PASS (16/16)
- **[Multi-org CRUD test]** PASS (`vitalgraph_client_test/test_multiple_organizations_crud.py`)
- **[Note]** Space `space_multi_org_crud_test` preserved for inspection (test intentionally skips deletion)
