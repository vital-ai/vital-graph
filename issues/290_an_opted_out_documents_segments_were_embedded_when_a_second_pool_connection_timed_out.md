# 290 — An opted-out document's segments were embedded when a second pool connection timed out

## Status: FIXED IN CODE 2026-10-20 (not yet released). Verified on the local dev server.

**Related:** `issues/285` (the vectorize rule this enforces), `issues/274` (the
same anti-pattern: a holder asking its own pool for another connection).

## What showed it

A consumer test on the local dev server (:8001) matched the AWS test server
everywhere except one place: a document uploaded and segmented with
`vectorize=False` recorded `NO_INDEX` on itself, but its segments carried no
status and were embedded, with billed OpenAI calls. On AWS test the same flow
gave 0 vector rows. Only one short sample got `NO_INDEX` on its segments
locally.

## Cause

The segmentation worker resolves the vectorize decision it stamps on the
segments in `_resolve_type_policy`. That method took a SECOND connection from
the internal pool while the worker already held one for the job. The dev
server's internal pool is small, and it was busy with derived-table backfills
and maintenance at the time, so the acquire waited out its 15 s timeout. The
dev log showed it on 9 of 11 jobs, each about 15 s after the job started:

    Job 5: type policy lookup failed, using job settings:

The message is empty because it was a `TimeoutError`. The worker then segmented
with NOTHING stamped, and auto-sync embedded the segments. The jobs that got a
connection (11, 12) were stamped correctly. AWS's pool is larger, so it never
showed there. The failure direction was the expensive one: a lookup failure led
to embedding against an explicit opt-out.

## Fix (`segmentation_worker._resolve_type_policy`)

* **It uses the connection the worker already holds** (`manager.conn`), never
  the pool.
* **The document's own explicit status needs no lookup.** It is in the fetched
  document properties, so it is applied even if the type-config lookup fails.
* **It fails closed.** With no explicit status, a failed type lookup raises; the
  job is failed and retried (up to 3 attempts, with backoff) instead of
  segmenting with no decision.
* **Errors name their type**, so a timeout no longer logs as an empty string.

## Verified

* `tests/unit/test_kgdocument_upload_and_policy.py::TestTypePolicyLookup`:
  * the lookup uses the held connection and never touches the pool;
  * an explicit `NO_INDEX` survives a lookup that raises `TimeoutError`;
  * with no explicit status, a failed lookup fails the job.
* On the local dev server, rebuilt with the fix,
  `test_scripts/debug/_issue290_dev_vectorize_check.py` (scratch space, real
  OpenAI-backed `document_segments` index, the consumer's upload-then-segment
  flow):
  * `vectorize=False`: 7 of 7 parent copy and segments stamped `NO_INDEX`,
    0 vector rows;
  * `vectorize=True`: 7 of 7 stamped `VECTOR`, 7 vector rows;
  * no lookup warnings in the log.

## Not done

* Why the dev server's internal pool was saturated. The backfills explain
  today; the pool's sizing on a single-instance dev server is not examined.
