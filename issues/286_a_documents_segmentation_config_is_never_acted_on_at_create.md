# 286 — A document's segmentation config is never acted on at create

## Status: RELEASED IN 0.0.48 AND DEPLOYED 2026-10-20 to AWS test and AWS production (reported by the deploy session).

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

## Not done

- **An update through `PUT /kgdocuments` that changes content does not
  re-segment.** The SPARQL UPDATE hook does; this path does not.
- **`AutoSegmentationHook` is still unused.** It segments inline rather than
  queueing, and the create path now queues instead.
