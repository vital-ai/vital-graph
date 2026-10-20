# 285 — Nothing can keep a document out of vector indexes

## ARCHIVED 2026-10-20 — the rule released in 0.0.48 and deployed; the type-change follow-up fixed and verified on the vg test stack; the FileNode is not stamped by design (ontology); nothing remaining. Evidence: tests/integration/test_vectorize_policy.py; tests/api/test_kgdocument_vectorize_and_upload.py.

## Status: RELEASED IN 0.0.48 AND DEPLOYED 2026-10-20 to AWS test and AWS production (reported by the deploy session). Type-change follow-up FIXED IN CODE 2026-10-20 (not yet released).

**Related:** `issues/284` and `issues/286`, from the same request. `issues/219`
(auto-sync scoped to each index's mapping, which this builds on). `issues/245`
(segment classification).

## What was missing

Research documents must not be embedded. Creating a document scheduled
vectorization, and segmentation queued it again for every segment. Nothing could
opt out, either per request or per document type:

- **`auto_vectorize` was stored and never read.** It exists on every segmentation
  config, with a client parameter, and the worker vectorized segments
  unconditionally.
- **Excluding a type through a disabled vector mapping covered only half the
  case.** It worked for the document but not its segments. Every segment's
  `kGDocumentType` is `urn:kgdoctype:document_segment`, and nothing on a segment
  names the source document's type. The comment in `auto_sync` claiming segments
  "carry the parent's document type" was wrong, and is corrected.

**The premise was half wrong: creating a document never vectorized it.** The
document endpoint's `_schedule_auto_sync` read `space_impl.backend`, which
`SpaceImpl` does not have, so `db_impl` was always None and the method returned
without logging anything. That has been true since the endpoint was written
(`3e1e40b3`), and it covers every document create, update and delete:

- nothing was embedded,
- nothing was FTS-, geo- or fuzzy-indexed,
- and on delete, rows already indexed for the document were left behind.

Only the segmentation worker, which resolves the backend itself, ever synced
anything. The entity endpoint passes the right object. This was found when the
API test for this issue saw no whole-document vector at all. **Fixing it changes
behaviour:** from this release a document is synced on write, so a space with a
catch-all `kgdocument` vector or FTS mapping starts indexing new documents.

Three more defects found on the way:

- **An untyped document was embedded as an entity.** With no `kGDocumentType`,
  the classifier fell through to `kgentity`. Since uploads set no type, every
  upload went into any index with a catch-all entity mapping. The bulk populator
  already treated such a subject as a `kgdocument`, so the two paths disagreed.
- **The client's `setup_document_segments_mapping` created a `kgdocument`
  mapping.** That matches whole documents only, so segments routed through it
  were never embedded. The server's own setup uses `kgdocument_segment`.
- **`POST /kgdocuments/segment` checked no permission,** although it replaces a
  document's segments.
- **Deleting segmentation output left its index rows behind.**
  `delete_segmentation` removed the quads but no vector, FTS, geo or fuzzy row.
  Every re-segmentation orphaned the previous run's segment vectors, because new
  segments get new URIs, and deleting a document left its segments' rows
  matching searches. Found when `vectorize=false` on an embedded document left
  its old segments' vectors in place.
- **One vector index whose provider could not be built aborted the whole
  sync.** That stopped every other index and the geo, fuzzy and FTS steps after
  it. Every new space bootstraps an OpenAI `document_segments` index, so on a
  stack without an OpenAI key no write synced anything.

## Fix — one rule, `vitalgraph/document/vectorize_policy.py`

Applied by every vector writer: auto-sync, the segmentation worker (through
auto-sync), and the bulk reindex.

1. **An explicit `hasKGIndexStatusURI` on the subject decides.**
   `KGIndexStatus_NO_INDEX` means skip and remove any existing vectors.
   `KGIndexStatus_VECTOR` means embed even if the type's default is off. The
   ontology already declared this property on every `KGNode` with exactly these
   two values; nothing used it.
2. **Otherwise, a whole document whose type has enabled segmentation configs is
   skipped when none of them sets `auto_vectorize`.**
3. **Otherwise it is embedded**, as before.

How each part reaches the data:

- **The per-request override** is `vectorize=true|false`:
  - a query parameter on `POST /kgdocuments`,
  - a form field on the upload,
  - a field on `POST /kgdocuments/segment`.

  It is stored on the document, not carried with the request, so it survives
  later updates and re-segmentation. From the segment endpoint it replaces the
  document's status and re-syncs it, so turning vectorization off also removes
  vectors already written.
- **Segments carry the decision by stamp.** The worker resolves the original's
  decision (its explicit status, or `NO_INDEX` if its type is off) and writes it
  onto the parent copy and every segment. From then on rule 1 covers them
  everywhere.
- **`NO_INDEX` means "no vector index".** `VECTOR` is the only other value the
  ontology defines. Full-text search is unaffected.

The defects above are fixed:

- `_schedule_auto_sync` resolves the backend with `get_db_space_impl()`, and
  logs a WARNING if it still finds none.
- `delete_segmentation` schedules an auto-sync delete for every URI it removes.
- A provider that cannot be built skips that index with a WARNING; the rest of
  the sync continues.
- An untyped KGDocument is classified as `("kgdocument", None)`, matching only
  catch-all document mappings.
- The client helper creates a `kgdocument_segment` mapping.
- The segment route requires space write access.

## Verified

- `tests/integration/test_vectorize_policy.py` covers the precedence rule:
  type on, off, mixed (on wins), no config, a disabled config, explicit overrides
  both ways, and segments stamped and unstamped. It also checks that an untyped
  document is classified as a document.
- `tests/api/test_kgdocument_vectorize_and_upload.py`, end to end through the
  client:
  - With an index carrying catch-all document and segment mappings, a type-on
    document and its segments are embedded, and a type-off one is not.
  - `vectorize=True` overrides a type that is off, and `vectorize=False` a type
    that is on.
  - `segment_document(vectorize=False)` removes the vectors a document already
    had.
  - Absence is asserted only after the "on" documents, created at the same time,
    have their vectors.

**Worth knowing when reading these results:** a `default` mapping embeds
`hasKGraphDescription` and nothing else. Under one, a whole document without a
description is never embedded, whatever the policy says; its segments, which the
processor gives a description, are. Uploads set no description, so under a
`default` mapping an upload's vectors are its segments' vectors. The API test
sets descriptions on created documents and uses a type-on upload as a control,
so that no "not embedded" assertion passes vacuously; the first version of the
test did not, and passed for the wrong reason.

## Follow-up fix (2026-10-20, not yet released)

- **A config change that flips a type's default reaches its existing output.**
  Creating, updating or deleting a segmentation config compares the type's
  decision before and after (`types_with_vectorize_off`). Only a flip does
  anything (`_on_type_default_change`). Re-syncing a type whose decision did
  not change would re-embed every one of its documents for nothing, and an
  embedding can be billed. On a flip, a background task (`_apply_type_default`):
  - finds every original of the type with no explicit status, plus its parent
    copies and segments;
  - restamps those copies and segments: `NO_INDEX` when the type turns off,
    stamp removed when it turns on;
  - re-syncs them and the originals, so vectors are removed or written.

  An original WITH an explicit status is left alone; its decision is its own.
  The first version selected parent copies through a `BIND(?parent AS ?x)`
  UNION branch. That branch is its own group, where `?parent` is unbound, so
  parent copies were silently left out. The API test caught it.
- **The FileNode that holds an upload's original: not stamped, by design.**
  The ontology does not declare `hasKGIndexStatusURI` on FileNode (it is on
  `KGNode`), and the quad converter drops it ("not properties of FileNode
  were dropped"). A FileNode is classified `kgentity` by auto-sync. Under a
  `default` mapping it has no `hasKGraphDescription` and so no text, so it is
  never embedded. Only a catch-all entity mapping with a name-based source
  could embed its file name.

Verified: `tests/api/test_kgdocument_vectorize_and_upload.py::TestTypeDefaultChange`.
- **A type flipped off, then on.** Its document's vectors and its parent copy
  and segments' vectors all go to 0, and every segmentation subject is stamped
  `NO_INDEX` while the original stays unstamped. Flipped back on, the stamps
  are gone and everything is re-embedded.
- **An explicit decision survives the flips.** Turning `TYPE_OFF` on embeds
  its unstamped document, which is the positive signal. Through both flips,
  `forced_on` (the same type, created `vectorize=True`) keeps `VECTOR` on
  every segment.

Both pass, with the rest of the file (16 passed).
