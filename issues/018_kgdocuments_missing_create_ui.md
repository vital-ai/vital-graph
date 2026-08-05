# 018 — KG Documents Missing Create/Upload UI

## Status: ✅ COMPLETE (2026-08-04)

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

### 3. Add "Segment & Index" option to Upload modal ✅ (done 2026-08-04)

The upload modal should offer a toggle/checkbox: **"Segment & index after upload"** (default: on).

When enabled, immediately after document creation the UI calls `apiService.segmentDocument(spaceId, graphId, docUri)` which enqueues a segmentation job. The segmentation worker handles splitting + inline vectorization automatically.

This eliminates the requirement for users to navigate to the detail page and manually click "Segment" after every upload.

Implementation (as built):
- `ToggleSwitch` labelled "Segment & index after upload" in the upload modal, default checked, wrapped in `data-testid="upload-segment-toggle"`.
- After a successful `vgClient.kgdocuments.create(...)`, when the toggle is on the handler calls `vgClient.kgdocuments.segment(spaceId, graphId, { document_uri: docUri })`.
- A dismissible info `Alert` (`data-testid="upload-notice"`) reports what happened: created, and whether segmentation was queued.
- A segmentation failure is reported in that notice but does **not** surface as an upload failure — the document was created either way, and the user is told they can retry from the detail page.

### 4. Document format conversion to Markdown ✅ (done 2026-08-04)

Uploaded documents are converted to Markdown server-side so the segmenter picks
`markdown_heading_split` instead of the paragraph heuristic.

**Libraries chosen** — licence was the deciding constraint. This project ships
under Apache-2.0 (`pyproject.toml:13`), so the AGPL and GPL candidates the
original list suggested were excluded:

| Format | Library | Licence | Notes |
|--------|---------|---------|-------|
| `.html` / `.htm` | `markdownify` | MIT | ATX headings (`heading_style="ATX"`) — the underline style would not be detected |
| `.docx` | `mammoth` → `markdownify` | BSD-2 + MIT | mammoth maps Word heading *styles* to `<h1>`–`<h6>`, so headings survive rather than becoming bold text |
| `.pdf` | `pdfplumber` | MIT | text extraction; each page emitted under a `## Page N` heading |
| `.md` / `.txt` | — | — | passthrough; converting plain text would invent structure that is not there |

Rejected: **`pymupdf`** (AGPL-3.0) and **`html2text`** (GPL-3.0) — both copyleft
and incompatible with shipping under Apache-2.0. `unstructured` is
Apache-2.0 but pulls a very large dependency tree.

**Where conversion runs:** server-side, in the ingest endpoint
(`POST /api/graphs/kgdocuments/upload`), so API callers get it too and multi-MB
parsing stays off the request thread of the quad-based create path.

**Property mapping** — no ontology changes were needed; this follows the
priority order `extract_content` already implements
(`kgdocument_segmentation_processor.py:52`), so the segmenter is untouched:

| Property | Holds |
|---|---|
| `hasKGDocumentExtractedContent` | the Markdown (preferred by the reader) |
| `hasKGDocumentHTMLContent` | the original HTML, when the source was HTML |
| `hasKGDocumentContent` | the raw text, when the source was already text |
| `Edge_hasKGDocumentFileNode` | edge to the FileNode holding the original bytes |

**Transport.** The modal used to read the file with `file.text()` in the
browser, which cannot work for PDF or DOCX. It now POSTs the file as multipart
to the new endpoint; the original bytes go to MinIO via the existing
`S3FileManager`, with a `FileNode` and an edge linking it to the document.

**Failure policy.** Conversion failures are loud: `ConversionError` for an
unsupported extension, a corrupt file, or a scanned PDF with no text layer,
surfaced as HTTP 200 + `success:false` per the project convention (issues/034).
This is deliberately unlike the old `strip_html`, which degraded silently.
Retaining the original is best-effort — if object storage is unavailable or
full, the document is still created and the notice says the original was not
kept.

**Limits.** Conversion needs the whole file in memory (pdfplumber and mammoth
both want a seekable buffer), so this path cannot stream the way
`/files/stream/upload` does. Bounded at 64 MB (`MAX_UPLOAD_BYTES`).

**Not supported:** scanned PDFs (no OCR) — reported explicitly rather than
stored as an empty document. PDF headings are page-based, since a PDF carries
no heading semantics to recover.

**Three bugs found and fixed while building this:**

1. **Quad literals were not N-Quads encoded.** `Quad.o` carries a *term*, not a
   value. A bare string usually survives because the parser falls through to
   "plain literal" — but a value starting with `<` and ending with `>` is read
   back as a URI and loses both characters. Every HTML document looks exactly
   like that, so `<p>alpha</p>` round-tripped as `p>alpha</p`. Fixed with
   explicit `_uri_term`/`_literal_term` encoding;
   `tests/unit/test_kgdocument_quad_encoding.py` pins it, including a test that
   demonstrates the bad behaviour.
2. **`hasKGDocumentFileNode` is an Edge class, not a datatype property.**
   Written as a plain predicate it was accepted by the API and silently dropped
   at store time — the link just vanished. Now modelled as a real
   `Edge_hasKGDocumentFileNode` with `hasEdgeSource`/`hasEdgeDestination`.
   Also note `FileNode` lives in the `vital#` namespace, not `vital-core#`.
3. **The storage endpoint was normalised ad hoc at each use site.** It is
   supplied both ways — the docstring says `localhost:9000`, deployments set
   `http://minio:9000` (`STORAGE_ENDPOINT`) — and each consumer re-derived what
   it needed: `__init__` stripped the scheme into a local variable for the Minio
   client, while `get_file_url` prepended one unconditionally, so every stored
   `hasFileURL` was `http://http://minio:9000/...`. Pre-existing, and it
   affected the Files API too.

   Fixed generally rather than at the call site: `_split_endpoint()` splits the
   endpoint once in `__init__` into `endpoint_host` (never carries a scheme) and
   the scheme, so no consumer has to think about it and a new one cannot get it
   wrong. An explicit scheme now also decides the client's `secure` flag —
   previously `https://…` with `use_ssl=False` would silently connect
   insecurely; a mismatch is logged. Covered by
   `tests/unit/test_s3_file_url.py`, which exercises the real constructor with
   Minio patched (23 tests, verified to fail if the fix is reverted).

**Tests:** 53 unit tests for this item (`test_document_converter.py` 18,
`test_kgdocument_quad_encoding.py` 12, `test_s3_file_url.py` 23) plus three E2E
tests covering HTML conversion with byte-exact original preservation, DOCX
heading styles, and the unsupported-type refusal. Items 8 and the token-limit
follow-up add 22 more (`test_embedding_model_warmup.py` 9,
`test_segment_token_limit.py` 13).

### 5. Indicate markdown preference for better segmentation ✅ (done 2026-08-04)

Took the auto-detect option: on file selection the modal reads the file once
and shows a badge (`data-testid="upload-format-hint"`) — either *"Markdown
detected — heading-based split"* or *"Plain text — paragraph split. Markdown
headings (# Section) produce better segments."*

The detection mirrors the server's `detect_is_markdown`
(`vitalgraph/document/document_segmenter.py:35`) exactly — two or more
`^#{1,6}\s+` lines. **These must stay in sync**: a hint that disagrees with the
split the segmenter actually picks is worse than no hint. The file is read once
on selection and reused for the upload rather than being read twice.

### 6. E2E test (`e2e/tests/kgdocuments-crud.spec.ts`) ✅ (done — validated 2026-08-04)

Every checklist item below is covered, and the spec goes further (ONNX index +
search mapping creation, semantic search, the list-page "Ready" badge).

- ✅ Verify seeded document appears in list
- ✅ Upload a `.txt` document via modal → verify it appears in list
- ✅ Upload a `.md` document via modal → uses the real Wikipedia coffee article
  (`test_files/wikipedia/coffee.md`, ~59KB, 41 headings)
- ✅ Navigate to document detail page
- ✅ Trigger segmentation → asserts the full status transition chain
  (pending → segmenting → segmented/vectorizing → Ready) and heading-based
  segments
- ✅ Delete document via detail page → verify removal from list

Plus, added with items 3 and 5:

- ✅ The format hint badge matches the file (markdown vs plain text)
- ✅ Toggle ON → a `POST /api/graphs/kgdocuments/segment` is sent, the notice
  says segmentation was queued, and a real job exists via
  `/api/graphs/kgdocuments/segmentation-status`
- ✅ Toggle OFF → no segment request is sent

**Validation:** 14/14 passing, three consecutive runs, plus full-suite runs.
The two pre-existing upload tests now switch the toggle OFF explicitly — the
segmentation block asserts *"No segmentation jobs found"* before driving the
trigger itself, so it must not share a document with an upload that queues
segmentation. The new coverage lives in its own describe block for the same
reason.

~~Note: the first run immediately after a stack rebuild failed at the final
"✅ Ready" assertion (30 s budget) and passed on every warm run.~~
**Resolved (2026-08-04) — two separate causes, do not conflate them:**

1. A real product inefficiency: the embedding model was loaded per
   segmentation. See item 8.
2. **The assertion's budget was simply too small.** Fixing (1) was not enough —
   the test failed again afterwards. Measured from the worker log, vectorising
   this article's 80 segments takes **8.3 s when run alone but 39.4 s under
   full-suite parallel load** (ONNX is CPU-bound and the suite runs unbounded
   workers). Against a 30 s budget that is a coin flip, which reads as flake but
   is just work exceeding its allowance. Stage 3 now allows 90 s and the test
   180 s, with the measurement recorded inline so the next person can tell a
   regression from normal variance.

## Files Changed

| File | Change |
|------|--------|
| `frontend/src/pages/KGDocuments.tsx` | "Add Document" + "Upload Document" buttons; upload modal with file/headline/URL fields; **(2026-08-04)** "Segment & index after upload" toggle, format hint, post-upload notice, and multipart upload to the new endpoint (replacing browser-side `file.text()`) |
| `vitalgraph/document/document_converter.py` | **New** — HTML/DOCX/PDF → Markdown, with explicit `ConversionError` rather than silent degradation |
| `vitalgraph/endpoint/kgdocuments_endpoint.py` | `POST /kgdocuments/upload`; N-Quads term encoding; FileNode + edge creation; `_get_tokenizer` uses the shared provider |
| `vitalgraph/document/segmentation_worker.py` | `_get_tokenizer` uses the shared provider; passes the model's `max_input_tokens` |
| `vitalgraph/document/document_segmenter.py`, `segment_config.py` | Segment ceiling clamped to the model's limit; default 1024 → 512 |
| `vitalgraph/vectorization/{base,registry,vitalsigns_provider,openai_provider}.py` | `max_input_tokens` on the provider interface; `warm_local_provider()` / `get_local_provider()` under a shared cache key |
| `vitalgraph/impl/vitalgraphapp_impl.py` | Warms the embedding model at startup, before the segmentation worker |
| `vitalgraph/storage/s3_file_manager.py` | Endpoint normalised once (`_split_endpoint`); fixes the doubled URL scheme |
| `vitalgraph-client-ts/src/endpoint/KGDocumentsEndpoint.ts` | `upload()` (multipart) + `KGDocumentUploadResponse` |
| `e2e/tests/kgdocuments-crud.spec.ts` | E2E spec — 17 tests, validated green |
| `pyproject.toml` | `markdownify`, `pdfplumber`, `mammoth`, `beautifulsoup4` (all permissive licences) |

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

## 8. Embedding model loaded per segmentation — ✅ FIXED (2026-08-04)

### Problem

`kgdocuments-crud.spec.ts` "trigger segmentation" failed on the **first run
after a rebuild**, three separate times, and passed on every warm run. Easy to
dismiss as a cold-start timeout; it was not.

`_get_tokenizer()` — in both `segmentation_worker.py` and
`kgdocuments_endpoint.py` — called:

```python
provider = get_provider("vitalsigns_onnx")      # no cache_key
if provider and hasattr(provider, "_tokenizer"):
    return provider._tokenizer
```

Two defects compounding:

1. **No `cache_key`**, so `get_provider` built a fresh tokenizer and ONNX
   `InferenceSession` on **every** segmentation — hundreds of ms to seconds,
   per job, not just the first.
2. **`_tokenizer` is not an attribute of this provider** (it holds `_embedder`),
   so after paying the full load cost the function returned `None` and the
   segmenter fell back to whitespace token counting. The model was loaded and
   thrown away, every time, for nothing.

### Fix

- `warm_local_provider()` runs at **application startup**, before the
  segmentation worker starts, under a shared `LOCAL_PROVIDER_CACHE_KEY`. It also
  runs one throwaway inference — the *first* inference pays for graph
  optimisation and arena setup, not just construction. Executed via
  `asyncio.to_thread` so it does not block startup, and wrapped so a failure
  degrades to lazy loading rather than preventing boot.
- Both `_get_tokenizer()` sites now use `get_local_provider()`, which returns
  the shared cached instance, and reach the tokenizer correctly
  (`provider._embedder.tokenizer`).

### Consequence worth knowing

Because the old lookup always returned `None`, **segmentation had been using the
whitespace approximation all along**. It now uses the model's tokenizer, as
`DocumentSegmenter` documents it should. On the Wikipedia fixture the segment
count is unchanged (80 either way — heading boundaries dominate), but the
recorded `token_length` for the largest segment went 322 → 415: the old counts
under-reported by ~30%. That under-reporting is what hid the 1024-vs-512
mismatch described in the follow-ups below.

### Verification

`tests/unit/test_embedding_model_warmup.py` — 9 tests pinning the shared
instance, including one documenting that an uncached `get_provider` call still
returns a *different* object each time. The E2E spec passes 17/17 on a cold
build; full suite 278/278 cold.

### Still loose

Two `VitalSignsProvider initialized` lines appear at startup ~0.36 s apart, so
something besides the warm-up still constructs its own instance. Same
missing-cache-key pattern; now costs one duplicate load at startup rather than
one per request, so it is cheap — but worth tracking down.

## Remaining work

**None — all items are complete.** Verified with 75 unit tests across five new
files (`test_document_converter.py`, `test_kgdocument_quad_encoding.py`,
`test_s3_file_url.py`, `test_embedding_model_warmup.py`,
`test_segment_token_limit.py`), 17 E2E tests in `kgdocuments-crud.spec.ts`, and
a full suite of **278/278 on a cold build**.

Follow-ups this work surfaced, tracked elsewhere or worth their own issue:

- `beautifulsoup4` is now declared, so `strip_html()` finally takes its intended
  BeautifulSoup path instead of the silent regex fallback. The `except
  ImportError` branch is still there and still silent — worth removing, since
  the conversion path supersedes it.
- Unknown predicates are **silently dropped** at store time (that is how the
  `hasKGDocumentFileNode` mistake stayed invisible). A warning when a quad's
  predicate is not an allowed property of the object's class would have turned a
  half-hour of debugging into a log line.
- `DELETE /api/files` **without `graph_id` silently no-ops**, returning
  `success:true, status:"no_op", "File node not found - no deletion needed"`.
  `files-crud.spec.ts` omitted it, so its cleanup had never deleted anything:
  103 orphaned FileNodes had accumulated in the shared graph and eventually
  pushed that spec's own fixture off page 1 of the Files list — an issues/022
  failure with a different root cause. Fixed in the spec and the residue purged,
  but a delete that finds nothing while the object plainly exists in another
  graph is a sharp edge worth reconsidering.
- **Segment size now matches the embedding model.** `max_segment_tokens`
  defaulted to 1024 while the bundled model accepts 512, so a long section was
  embedded truncated — its tail never reached the vector, silently. It was
  hidden by the whitespace token approximation, which under-reported by ~30%
  (the Wikipedia fixture's largest segment measured 322 by whitespace, 415 by
  the model's tokenizer). Fixed on two levels: providers now report
  `max_input_tokens` (local model 512 from its own tokenizer, OpenAI 8191), the
  dataclass default is `DEFAULT_MAX_SEGMENT_TOKENS = 512` — matching what
  `segmentation_config_manager` already stored — and the segmenter clamps to the
  provider's ceiling, so a stored config asking for more cannot produce a
  segment that will be truncated. Covered by
  `tests/unit/test_segment_token_limit.py`.
- Deleting a KGDocument does **not** remove the FileNode holding its original
  bytes. Reasonable as a storage decision, but it means every uploaded document
  leaves an orphan unless the caller cleans up. The E2E suite now sweeps
  `urn:kgdocument:…:source` FileNodes; a server-side cascade (or a documented
  contract) would be better.
- OCR for scanned PDFs is deliberately out of scope; a scanned file is refused
  with an explicit message.

## Notes

- The `ObjectDetailRenderer` + `useObjectDetail` hook already handles create mode for KGDocuments — no new page needed for the form-based path.
- ~~Large documents (>2.7KB content) may hit the B-tree 8KB index limit on `term_text`.~~ **Stale (corrected 2026-08-04):** the index is a hash, not a B-tree, so there is no 8KB key limit. The E2E suite round-trips the 59KB Wikipedia coffee article — upload, segmentation into heading-based segments, and semantic search — on every run.
