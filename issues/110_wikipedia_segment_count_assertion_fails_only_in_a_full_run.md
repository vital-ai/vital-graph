# A Wikipedia Segment-Count Assertion Fails Only in a Full API Run

## Status: OPEN — reproduced twice, never with the assertion captured

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
