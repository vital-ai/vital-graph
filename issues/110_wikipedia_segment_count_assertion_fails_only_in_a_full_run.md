# A Wikipedia Segment-Count Assertion Fails Only in a Full API Run

## Status: FIXED 2026-08-19 — a shared tokenizer, not a flaky test

    AssertionError: Completed job 2 has unexpected error: Already borrowed

`RuntimeError: Already borrowed` is the PyO3 RefCell refusing re-entry: one
HuggingFace tokenizer used from two threads. `registry._instance_by_signature`
hands every caller the SAME provider, and its tokenizer was reachable and
unguarded from two directions at once — auto_sync embedding in an
`asyncio.to_thread` worker, and document segmentation counting tokens.

Not a test problem. 11 occurrences in one run, which failed a segmentation job
outright (`_process_job - ERROR - Job 2 failed: Already borrowed`) and lost an
83-text auto_sync batch. `vectorization_failed` records that as **status
completed with an error message**, on the argument that segments are still
searchable via FTS — so the visible outcome is a completed job and vectors that
silently are not there. One assertion in the Wikipedia end-to-end test was the
only thing that ever complained.

### Two fixes, because the first one was not enough

**1. A lock around embedding.** `threading.Lock`, not asyncio: the collision is
between worker THREADS and the provider is reachable from more than one event
loop. Held across a whole batch rather than per text, since re-acquiring 83 times
interleaves the batch with every other caller.

**That did not fix it**, and the cold run failed again with the lock in place.
The log showed every survivor was an auto_sync embed racing a segmentation job.

**2. The TOKENIZER is the shared object, not just the embed call.** Two callers
reached straight into `provider._embedder.tokenizer` for segment sizing —
`segmentation_worker._get_tokenizer` and `kgdocuments_endpoint._get_tokenizer`,
each returning `lambda text: len(tokenizer.encode(text))`. They now call
`provider.count_tokens`, which takes the same lock, and `max_input_tokens` takes
it too because reading `model_max_length` borrows the same cell.

Removing the reach-through is worth it on its own: it had already caused a bug,
looking for a `_tokenizer` attribute the provider does not have, getting None,
and silently falling back to whitespace counting.

    before   1 cold full-suite run   11 occurrences, 3 tests failed
    after    4 cold full-suite runs   0 occurrences, 0 failures

### How it was found, after two wrong turns

**The repeat-until-it-fires loop could never have caught it.** Six warm runs were
queued; the failure only happens on a COLD container, because it needs
segmentation and vectorization to overlap while nothing is cached. The pattern
was in the timestamps all along:

    18:28 FAILED   first run after a rebuild+restart
    18:43 clean    warm rerun
    21:48 FAILED   first run after a rebuild+restart
    22:03 clean    warm rerun
    22:11-22:18 clean   three warm runs

Two cold runs, two failures; seven warm runs, none. Restarting the container
before each run reproduced it on the second attempt.

**The module alone passes even cold** — it needs the full suite's load as well,
which is why the isolated rerun was never evidence of anything.

**And an early hypothesis was disconfirmed by its own evidence.** Vectorization
failure was suspected first and dismissed after grepping the log for it and
finding nothing — the grep was right, the dismissal was wrong: the error arrives
as `Already borrowed`, not as anything naming vectorization. It was the right
suspect under a name nobody searched for.

`tests/api/test_wikipedia_document_e2e.py::TestWikipediaVectorization::test_completed_jobs_have_segments`
failed in 2 of 5 full `tests/api` runs on 2026-08-19, and passed every time it
was run alone:

    module alone      35 passed, 1 skipped     (twice)
    full tests/api    FAILED, then passed on rerun with no change

**The assertion output was never captured.** Both failing runs used `--tb=line`,
which prints the FAILED line and nothing else, and both reruns were green — so
what actually tripped is still unknown. That is the whole of the open work: run
the suite with `--tb=long` until it fires once.

## Why it is not obviously environmental

The test iterates EVERY job the space reports and asserts each completed one has
a positive `segment_count`, a `segment_method_uri`, and no `error_message`:

    for job in status_resp.jobs:
        if job["status"] != "completed":
            continue
        assert job["segment_count"] is not None and job["segment_count"] > 0

`wiki_env` uses the module-scoped `apitest_*` space, so cross-module contamination
is not the obvious explanation it first looked like. Checked while failing:
**no completed job anywhere on the stack had a null or zero `segment_count`** —
so whatever the state was, it did not survive to be inspected afterwards, which
points at a timing window rather than a durable wrong value.

Segmentation runs in a background worker. The plausible shape is a job observed
as `completed` before the row carrying its `segment_count` is visible to the
reader, which a busier full run would widen and an isolated module run would not.
That is a hypothesis; nothing has confirmed it.

## What it is NOT

* Not the grouping-root change (`issues/091`). It failed once BEFORE that change
  landed and once after, and the change only adds an absent `kGGraphURI`.
* Not the probe document created by hand while verifying that change: that lived
  in `e2e_test_space`, and this test's space is a module-scoped `apitest_*` one.

## What to do

1. Run `tests/api` with `--tb=long` in a loop until it fires, and keep the
   assertion — which job, which field, which value.
2. If it is the visibility window, the fix belongs in the test: assert against
   jobs it enqueued and waited for, rather than every job the space reports.

## Related

- `issues/022` — the unswept flake class this belongs to
- `issues/108` — a green suite that measures something other than what it names;
  a test that passes on rerun is the same problem with a shorter half-life
