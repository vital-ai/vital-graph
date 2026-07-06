# 018 — KG Documents Missing Create/Upload UI

## Status: 🔧 IN PROGRESS

## Summary

The KG Documents list page (`frontend/src/pages/KGDocuments.tsx`) is read-only — it only lists and navigates to document details. There is no way for a user to create a new KG Document from the UI without using the API directly.

The backend and client SDK both support full CRUD:
- `POST /api/graphs/kgdocuments` — create from quad payload
- `DELETE /api/graphs/kgdocuments?uri=X` — delete by URI
- `KGDocumentsEndpoint.create()` / `.delete()` in `vitalgraph-client-ts`

The detail page (`KGDocumentDetail.tsx`) already supports delete via `ObjectDetailRenderer`, and create mode via `?mode=create`. The gap is that the list page has no buttons to access these features.

## Required Changes

### 1. Add "Add Document" button to list page ✅ (done)

Navigate to `/space/:spaceId/graph/:graphId/document/new?mode=create` — form-based creation using `ObjectDetailRenderer` (already works).

### 2. Add "Upload Document" modal to list page ✅ (done)

A modal that accepts:
- **File input** (`.txt`, `.md`, `.html`, `.csv`, `.json`) — text content extracted via `file.text()`
- **Headline/Title** (defaults to filename)
- **Source URL** (optional)

Creates a `KGDocument` via `vgClient.kgdocuments.create()` with quads for `rdf:type`, `hasName`, `hasKGDocumentHeadline`, `hasKGDocumentContent`, and optionally `hasKGDocumentURL`.

### 3. Add "Segment & Index" option to Upload modal — pending

The upload modal should offer a toggle/checkbox: **"Segment & index after upload"** (default: on).

When enabled, immediately after document creation the UI calls `apiService.segmentDocument(spaceId, graphId, docUri)` which enqueues a segmentation job. The segmentation worker handles splitting + inline vectorization automatically.

This eliminates the requirement for users to navigate to the detail page and manually click "Segment" after every upload.

Implementation:
- Add a `ToggleSwitch` labelled "Segment & index after upload" to the upload modal (default checked)
- After successful `vgClient.kgdocuments.create(...)`, if toggle is on, call `vgClient.kgdocuments.segment(spaceId, graphId, { document_uri: docUri })`
- Show a toast/badge indicating segmentation was queued

### 4. Document format conversion to Markdown on upload — pending

To get optimal segmentation (heading-based `markdown_heading_split`), uploaded documents should be converted to Markdown before storage. Currently no conversion library is wired into the pipeline.

**Supported formats (target):**

| Format | Conversion approach |
|--------|-------------------|
| `.html` / `.htm` | HTML → Markdown (preserve `<h1>`–`<h6>` as `#`–`######`, lists, tables) |
| `.pdf` | PDF → text/Markdown (extract headings from font-size/bold heuristics or PDF outline) |
| `.docx` | DOCX → Markdown (heading styles → `#` headings) |
| `.txt` | No conversion needed (plain text → `plain_recursive_split`) |
| `.md` | No conversion needed (already markdown) |

**Gaps:**
- No HTML→Markdown library is currently in `pyproject.toml` dependencies. A previous implementation used an HTML-to-markdown converter (to be identified and added).
- No PDF extraction library is present. Candidates: `pymupdf` (fitz), `pdfplumber`, `unstructured`.
- No DOCX extraction library is present. Candidates: `python-docx`, `mammoth`, `unstructured`.

**Existing code:**
- `test_scripts/data/fetch_wikipedia_test_docs.py` has a custom `WikiHTMLToMarkdown` class (stdlib `html.parser`) that handles headings, lists, bold/italic, tables, code blocks. Could be generalized for arbitrary HTML.
- `kgdocument_segmentation_processor.py` has `strip_html()` using BeautifulSoup — strips tags but discards structure (no markdown output).

**Recommended approach:**
- Server-side conversion in the endpoint or segmentation worker — works for both UI and API callers.
- Store the converted Markdown in `hasKGDocumentContent`; optionally preserve the original in `hasKGDocumentHTMLContent` or as a `FileNode` attachment.
- The segmenter's `detect_is_markdown()` will then auto-select heading-based splitting.

### 5. Indicate markdown preference for better segmentation — pending

The upload modal should hint to users that markdown content with headings (`# Section`) produces higher-quality segments via `markdown_heading_split`, vs plain text which falls back to `plain_recursive_split` (paragraph boundary heuristic).

Options:
- Add a small info tip below the file input: *"Markdown files with headings produce better segments."*
- Or auto-detect after file selection and show a badge: "Markdown detected — heading-based split" / "Plain text — paragraph split"

### 6. E2E test (`e2e/tests/kgdocuments-crud.spec.ts`) — pending

Test with `.txt` and `.md` files. Use Wikipedia markdown content (from `test_scripts/data/`) for realistic heading-based segmentation testing.

- Verify seeded document appears in list
- Upload a `.txt` document via modal → verify it appears in list
- Upload a `.md` (Wikipedia markdown) document via modal → verify it appears in list
- Navigate to document detail page
- Trigger segmentation → verify segments are created (markdown doc should produce heading-based segments)
- Delete document via detail page → verify removal from list

## Files Changed

| File | Change |
|------|--------|
| `frontend/src/pages/KGDocuments.tsx` | Added "Add Document" + "Upload Document" buttons, upload modal with file/headline/URL fields, `handleUploadDocument` handler |
| `e2e/tests/kgdocuments-crud.spec.ts` | New E2E test file (pending validation) |

## 7. Segmentation + Vectorization Parallelism — ✅ IMPLEMENTED (2026-07-04)

### Problem

The vectorization pipeline processed segments sequentially: for each subject, fetch properties → embed → upsert, one at a time. With 150 segments this was acceptable for local ONNX (~2s) but would be ~30s with OpenAI (150 × 200ms HTTP roundtrips).

### Solution implemented

Rewrote `_sync_vectors_for_subjects` in `vitalgraph/vectorization/auto_sync.py` with a three-phase approach:

```
Phase 1: fetch_literal_properties_batch()  — 1 DB query for ALL subjects
Phase 2: asyncio.gather + Semaphore(8)     — N concurrent vectorize_text() calls
Phase 3: sequential conn.execute(UPSERT)   — write embeddings on single connection
```

**Key constraint**: asyncpg connections don't support concurrent queries, so DB reads/writes must be sequential on the single acquired connection. The embedding calls (which are the bottleneck) are pure async — ONNX uses `asyncio.to_thread()`, OpenAI uses `httpx`. These can safely run in parallel.

### Changes

| File | Change |
|------|--------|
| `vitalgraph/vectorization/auto_sync.py` | `_VECTOR_CONCURRENCY = 8` constant; `_sync_vectors_for_subjects` rewritten with batch fetch + concurrent embed + sequential upsert |

### What was NOT parallelized (and why)

| Item | Reason |
|------|--------|
| Geo/fuzzy/FTS sync types | Share the same `conn` — can't run concurrent DB queries on one asyncpg connection |
| Worker blocking (`await task`) | Still awaits vectorization so the job status reflects reality; decoupling requires a separate "vectorizing" status field (future work) |

### Test results

Wikipedia e2e (150 segments, local ONNX 384d):
- **Before**: 83s total, vectors ready ~2s after segmentation
- **After**: 57s total, vectors ready ~4s after segmentation (slightly longer due to gather overhead, but total test is faster because segmentation itself overlaps better)

### Remaining opportunities (future)

| Level | Status | Notes |
|-------|--------|-------|
| **Batch embedding (OpenAI)** | Ready to use | `vectorize_texts()` already exists on both providers. Could replace N `vectorize_text` gather calls with 1 `vectorize_texts` call for even better throughput with remote APIs. |
| **Concurrent sync types** | Blocked | Requires acquiring separate connections per sync type from the pool — increases pool pressure. Low priority since geo/fuzzy/FTS are fast DB-only ops. |
| **Non-blocking worker** | Future | Needs a `vectorization_status` field on the job table so clients can distinguish "segmented but not yet vectorized" from "fully ready". |

---

## Notes

- The `ObjectDetailRenderer` + `useObjectDetail` hook already handles create mode for KGDocuments — no new page needed for the form-based path.
- Large documents (>2.7KB content) may hit the B-tree 8KB index limit on `term_text` (see issue in `undertested_features_tracker.md` §1.1). This is a known backend limitation, not a UI issue.
