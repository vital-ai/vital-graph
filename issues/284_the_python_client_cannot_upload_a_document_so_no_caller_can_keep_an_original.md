# 284 — The Python client cannot upload a document, so no caller can keep an original

## Status: FIXED IN CODE 2026-10-19 (not yet released). Callers need the next client release; 0.0.47 does not have it.

**Related:** `issues/283`, whose reporter is moving long reports into KG documents.
`issues/285` and `issues/286` came from the same request. `issues/281` (the
upload's `store_original` form field).

## What was missing

`POST /kgdocuments/upload` converts a file to Markdown, creates the KGDocument,
and by default keeps the uploaded bytes in object storage as a FileNode. The
TypeScript client has `upload()`. The Python client (0.0.47) has no method for it.
Its only way to make a document is `create_kgdocuments`, which takes objects and
cannot carry a file, so a Python caller gets no original in S3.

The upload also had no way to set `kGDocumentType`. That meant an uploaded
document never matched a segmentation config, and auto-sync classified it as an
entity (`issues/285`).

## Fix

- **Client:** `kgdocuments.upload_kgdocument(space_id, graph_id, file,
  filename=None, content_type=None, headline=None, source_url=None,
  store_original=True, document_type=None, vectorize=None)`.
  - `file` is a path or bytes. `filename` is required for bytes, because the
    server picks the converter by extension.
  - Returns `KGDocumentUploadClientResponse`. An unsupported file is a domain
    outcome: `is_success` False, with the reason in `message`.
  - Not retried: it is a POST, and a replay would create a second document.
- **Server:** the upload accepts `document_type` (written as
  `hasKGDocumentType`) and `vectorize` (`issues/285`) as form fields.

## Verified

- `tests/unit/test_kgdocument_upload_and_policy.py::TestUploadClient` checks the
  exact form, file part and params the client sends.
- `tests/api/test_kgdocument_vectorize_and_upload.py::TestUpload` uploads through
  the client and checks that a FileNode is kept, the type is set, the type's
  vectorize default applies, and the document is segmented on upload.

## Not done

- ~~The TypeScript client's `upload()` does not send `document_type` or
  `vectorize`.~~ Done in TS client 0.1.6: `upload()` takes `documentType` and
  `vectorize`, `create()` takes `{ vectorize }`, and `segment()` accepts
  `vectorize`.
- The release itself (0.0.48): the version bump and changelog are made in the
  release commit.
