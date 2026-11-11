# 335: Under load, segmentation jobs stick in 'vectorizing' or complete with an empty error

## Status: FIXED 2026-11-10 in `41eab77c`, and verified under a bulk load on a local install rebuilt with it (below). CI green.

Reported from a knowledge-base load into a local install (0.0.49, one worker,
sparql_sql backend). The checks behind the report were read-only.

## The defect

The load wrote batches of 25 entities and then their 25 documents, which
queued about 1,175 segmentation jobs within a minute. The index state came
out right: every segment had its vector and full-text rows. **The job states
came out wrong:**

* In one space, 2 jobs per load stayed `vectorizing` (attempt 1, no error),
  with nothing to move them on.
* 4 and then 8 jobs were recorded `completed` with the error text
  `Vectorization task failed: `, which ends at the colon.
* A second space on the same server, used by a test suite at the time, had 9
  jobs stuck and 26 with that error.

The log over the load showed 52 `pool state (acquire timed out): size=3
idle=0`, 8 `failed to update status after vectorization`, and 512 event-loop
stall warnings of up to ~3.3 s.

**Cause.** After segmentation, each job got its own task. The task queued
its subjects and then called `auto_sync.wait_until_synced`. That function
took a connection from the internal pool (max 3) every 0.5 s to ask the
queue about that one job's subjects, and a second acquire then wrote the
status. A thousand such tasks on a pool of 3 time out:

* the acquire raised `TimeoutError`, whose `str()` is empty, so the job was
  recorded `completed` with `"Vectorization task failed: "`;
* when the status write's acquire timed out as well, the error was logged
  and the row stayed `vectorizing`. Nothing reclaimed a `vectorizing` job.

The segments were embedded anyway, by the index sync workers, which take
their work from the queue and never depended on the job's poller.

**Second, smaller defect.** Dropping a graph left its job rows behind. A
dropped graph with 0 quads and 0 index rows still had 1,175 job rows, two of
them `vectorizing`.

## The fix

* **One completer per space, not one poller per job**
  (`document/vectorization_completer.py`). After queueing a job's subjects,
  the worker registers the job with the completer. Every 2 s the completer
  takes ONE connection:
  * one query (a join on `unnest`) finds which of every waiting job's
    subjects are still queued;
  * the drained jobs are completed on the same connection;
  * jobs past the 600 s wait are completed with `vectorization still queued
    after 600s`.

  A tick that fails, a pool timeout for example, is logged and retried, and
  the jobs stay registered, so no timeout can leave a job stuck.
* **A sweep for jobs no waiter is left for**, after a restart or a cancelled
  task. Every 5 minutes per space, a job left in `vectorizing` for over 20
  minutes and not tracked in this process is completed if its graph has
  nothing in the index-sync queue. The queue gives a failed row back with a
  backoff and never drops it, so an empty queue for the graph means its
  subjects were synced. A graph that is still busy keeps the job until a
  later sweep.
* **Error texts name the exception type**: `Vectorization task failed:
  TimeoutError`. `Lock timeout` and the generic job failure do the same.
* **A dropped or cleared graph takes its job rows**, in the transaction that
  removes its quads. That covers the graph API's `drop_graph` and
  `clear_graph`, and a SPARQL `CLEAR` or `DROP` of a named graph
  (`segmentation_job_manager.delete_jobs_for_graph`).

The worker's health report gains `jobs_vectorizing_tracked`.

## Verified

`tests/integration/test_vectorizing_jobs_are_finished.py`, on the test
database:

* 300 jobs, half with a subject still queued: one tick, ONE acquire,
  completes exactly the drained 150 and leaves the rest waiting;
* the loop completes a job once its queue rows go;
* a pool that raises `TimeoutError` keeps the jobs, and they complete once
  it recovers;
* error and deadline texts are recorded with their type;
* the sweep completes a stale job whose graph drained, and leaves a busy
  graph's job, a fresh job, and a job this process is tracking;
* `drop_graph` and SPARQL `DROP GRAPH` delete the graph's job rows and keep
  another graph's.

**Bulk load, 2026-11-10**, on the install that reported it, rebuilt with
`41eab77c`:

* **The sweep:** 11 s after the restart it completed all 13 stale
  `vectorizing` jobs (4 in one space, 9 in another). Only the old
  empty-error `completed` rows remain, as intended.
* **A load of 731 items,** with documents segmented and the rest indexed.
  From its start, the log shows:
  * 0 segmentation `acquire timed out`;
  * 0 `Vectorization task failed`;
  * 0 `failed to update status`;
  * no job left `vectorizing`.

  | | before the fix | with the fix |
  |---|---:|---:|
  | load | 598 s | 247 s |
  | searchable after the last write | 180 s | 3 s |
  | event-loop stall warnings | 512 (a longer, busier window) | 28 |
* **The graph drop:** dropping the run's graphs removed their job rows.
* **Caveat:** the server was quieter than during the reported runs, with
  fewer suites running at the same time.

## Existing rows

Jobs already stuck in `vectorizing` are finished by the sweep the first time
the fixed worker polls their space, once their graph's queue is empty. Jobs
already recorded `completed` with the empty error are left as they are.
Their segments are embedded; the error text is the only thing wrong.
