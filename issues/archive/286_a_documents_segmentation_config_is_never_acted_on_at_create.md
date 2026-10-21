# 286 — A document's segmentation config is never acted on at create

## ARCHIVED 2026-10-20 — the create path released in 0.0.48 and deployed; the PUT follow-up fixed and verified on the vg test stack; nothing remaining. Evidence: tests/api/test_kgdocument_vectorize_and_upload.py::TestAutoSegmentationOnCreate, ::TestUpdate; tests/unit/test_kgdocument_upload_and_policy.py::TestWorkerConfig.

## Status: RELEASED IN 0.0.48 AND DEPLOYED 2026-10-20 to AWS test and AWS production (reported by the deploy session). PUT follow-up RELEASED IN v0.0.95, deployed to production 2026-10-21.

**Related:** `issues/285` (the same config's `auto_vectorize`), `issues/284`
(uploads gain a `document_type`), `issues/287` (what the segmenter drops).

## What was missing

`{space}_document_segmentation_config` registers, per `kGDocumentType`, a
segmentation method, token sizes and `auto_vectorize`. It can be managed through
the API and the client, but nothing used it:

- **Nothing segmented a new document.** `AutoSegmentationHook` was written to
  segment at create time and is never called. A created or uploaded document
  stayed unsegmented until someone called `POST /kgdocuments/segment`. The only
  automatic trigger is the quad-level hook on SPARQL UPDATE, which ignores the
  config table.
- **The worker ignored the config even when a job ran.** It hardcoded
  `min_segment_tokens=20`, never applied `overlap_tokens`, and used only the
  method and maximum carried by the job.

## Fix

- **Create and upload queue segmentation.** After a successful store, each
  original KGDocument (one with no segment index) whose type has an enabled
  config gets a job using that config's method and maximum (`_auto_segment`).
  - Jobs are keyed on the document, so when a type has several configs the first
    by `config_id` is used and the choice is logged.
  - Best effort: a failed lookup leaves the document created and unsegmented,
    which is how every create behaved before.
- **The worker reads the config.** `_resolve_type_policy` finds the enabled
  config for the document's type, matching the job's method if it names one.
  `_build_config` then takes the job's own method and maximum and fills the
  rest (method, maximum, minimum, overlap) from the config. With no config the
  old defaults still apply.

## Verified

- `tests/api/test_kgdocument_vectorize_and_upload.py::TestAutoSegmentationOnCreate`:
  six documents (five created, one uploaded) and no explicit segment call. Every
  one reaches a completed job with segments.
- `tests/unit/test_kgdocument_upload_and_policy.py::TestWorkerConfig` checks that
  the config fills what the job leaves unset, that the job's own values win, and
  that the defaults hold without a config.

## Follow-up fix (2026-10-20, released in v0.0.95, deployed to production 2026-10-21) — PUT

- **`PUT /kgdocuments` re-segments on a content change** (`_auto_resegment`).
  A document qualifies when it is already segmented (the job reuses the
  method it has) or its type has an enabled config (the method create would
  pick). The job carries the new content's hash, and `enqueue` skips it when
  the last completed job has the same one. A PUT that changes only a name or a
  status queues nothing.
- **Found doing it: PUT never replaced anything.** It inserted the new quads
  with an empty delete list (`delete_quads_for_subj = []  # Will be replaced
  atomically`), so a changed content, name or type was stored NEXT TO the old
  value, and a failed write still answered UPDATED. Each object now replaces
  its subject's quads in one `update_subjects_graph` call, and a failure is a
  500. The fix also:
  - **keeps the vectorize decision:** an explicit `hasKGIndexStatusURI` the
    payload omits stays (`issues/285`), since a PUT has no `vectorize` knob to
    restate it;
  - **fills the grouping URI:** a missing one is set to the document's own
    URI, as create does.
- **`AutoSegmentationHook` is deleted,** along with its export. Nothing called
  it.

Verified: `tests/api/test_kgdocument_vectorize_and_upload.py::TestUpdate`.
- One test does a name-only PUT, then a content PUT. It checks that:
  - each replaces the stored value rather than adding one;
  - the content change leaves new segments carrying the new text and none of
    the old ones;
  - exactly two segmentation jobs complete (create and the content change; the
    name change queues none).
- A second test checks that a PUT sent without a status keeps the document's
  `NO_INDEX`.

Both pass, with the rest of the file (16 passed).
