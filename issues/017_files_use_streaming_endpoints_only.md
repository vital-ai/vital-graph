# 017 — Client & Frontend Should Use Streaming File Endpoints Only

## Summary

The TypeScript client SDK (`FilesEndpoint.ts`) and the frontend (`FileUpload.tsx`) currently use the **non-streaming** file endpoints (`/api/files/upload`, `/api/files/download`), which buffer the entire file into memory on both upload and download. The backend already provides true stream-pump endpoints (`/api/files/stream/upload`, `/api/files/stream/download`) but they are unused.

## Problem

- **Upload** (`_upload_file_content`): calls `await file.read()` — loads entire file into server memory before forwarding to MinIO.
- **Download** (`_download_file_content`): calls `file_manager.download_file(object_key)` — loads entire file into server memory, then wraps in `StreamingResponse(io.BytesIO(...))`.

This caps practical file size at available server RAM and adds latency (must fully buffer before sending first byte to client).

## Streaming Endpoints (already implemented)

- `POST /api/files/stream/upload` — passes `file.file` directly to MinIO `put_object` with `length=-1` (multipart streaming, no full buffer).
- `GET /api/files/stream/download` — yields 8KB chunks via `response.read(chunk_size)` in an async generator (true chunked response).

Both are in `files_streaming_impl.py` and already wired into `files_endpoint.py`.

## Required Changes — ALL COMPLETED ✅

### 1. TypeScript Client (`vitalgraph-client-ts/src/endpoint/FilesEndpoint.ts`) ✅

- `upload()` → now calls `/api/files/stream/upload`
- `download()` → now calls `/api/files/stream/download`
- `get()` → fixed to use `/api/files?uri=X` (was broken: `/api/files/file` doesn't exist)
- `delete()` → fixed to use `uri` param (was `file_uri`)
- Added `graphId` parameter to `get()` and `delete()`

### 2. Frontend ✅

- `ApiService.getFile()` → now passes `graphId` to `files.get()`
- `ApiService.deleteFile()` → now passes `graphId` to `files.delete()`
- No changes needed to `FileUpload.tsx` — it already uses `vgClient.files.upload()`

### 3. E2E Test (`e2e/tests/files-crud.spec.ts`) ✅

- Byte-level round-trip verification for 57B, 100KB, and 1MB files
- Upload via streaming endpoint + download via streaming endpoint
- Exact binary comparison with `Buffer.equals()`
- UI lifecycle test: list + delete via detail page

### 4. Deprecate Non-Streaming Endpoints ✅

- `POST /api/files/upload` marked `deprecated=True` with migration note
- `GET /api/files/download` marked `deprecated=True` with migration note

## Impact

- Eliminates O(filesize) server memory usage per concurrent upload/download.
- Enables arbitrarily large file transfers.
- Aligns E2E tests with production behavior.

## Priority

Medium — functional correctness is unaffected but scalability and memory safety are limited without this.
