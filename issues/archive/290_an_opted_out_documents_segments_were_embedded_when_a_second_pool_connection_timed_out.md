# 290 — An opted-out document's segments were embedded when a second pool connection timed out

## ARCHIVED 2026-10-20 — fixed, verified on the local dev server, and in production with the current code (reported 2026-10-20); the pool review is done and its finding is `issues/291`. Evidence: tests/unit/test_kgdocument_upload_and_policy.py::TestTypePolicyLookup, test_scripts/debug/_issue290_dev_vectorize_check.py.

## Status: FIXED IN CODE 2026-10-20; in production with the current code. Verified on the local dev server.

**Related:** `issues/285` (the vectorize rule this enforces), `issues/274` (the
same anti-pattern: a holder asking its own pool for another connection),
`issues/291` (why the pool was full: the review below).

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
the internal pool while the worker already held one for the job. The internal
pool was full (see "Review" below for why), so the acquire waited out its 15 s
timeout. The
dev log showed it on 9 of 11 jobs, each about 15 s after the job started:

    Job 5: type policy lookup failed, using job settings:

The message is empty because it was a `TimeoutError`. The worker then segmented
with NOTHING stamped, and auto-sync embedded the segments. The jobs that got a
connection (11, 12) were stamped correctly. It never showed on AWS test, for a
reason not established (see "Review"). The failure direction was the expensive one: a lookup failure led
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

## Review — why the pool was full (2026-10-20)

The first account here blamed the derived-table backfills. It was wrong:
those ran as scripts on their own connections, not on the app's pool. Two
things fill a 3-connection internal pool on their own:

* **Auto-sync holds its connection across the embedding call.** One sync keeps
  one connection through the property fetch, the OpenAI round trip (seconds)
  and the writes. Nothing bounds how many syncs are spawned: each upload
  schedules one, and each job's vectorization another.
* **The worker processes one job at a time.** Pre-fix, that job held one
  connection and asked for a second. 11 uploads put the other two behind
  auto-sync tasks waiting on OpenAI.

"AWS's pool is larger" was an assumption. The default is the same 3 everywhere
this repo configures, and the AWS deploy configuration is not here. The cause
in the holding pattern is filed as `issues/291`. This issue's fix does not
depend on it: the worker no longer takes a second connection, and a failed
lookup fails the job instead of embedding.
